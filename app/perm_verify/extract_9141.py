"""Extract an ETA-9141 Prevailing Wage Determination PDF into a PWD dict
used by PERM-verify Tier 3 wage checks.

Validated against determination fixture P-100-24067-778988.

Techniques:
  - Labeled values captured by regex over normalized page text
    (labels are Times; values Helvetica, but adjacency in the text
    stream is reliable on this form).
  - Checked boxes are \uf071 Wingdings glyphs OVERLAID with small
    diagonal line strokes; unchecked boxes have no strokes.
  - Two-column rows interleave in the text stream; several regexes
    account for values appearing before/after their labels.
"""
from __future__ import annotations
import re
import sys
import json

import pdfplumber


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def _checked_answers(page):
    """Return list of (top, x0, answer_word) for boxes with stroke overlays."""
    words = page.extract_words(extra_attrs=["fontname"])
    boxes = [c for c in page.chars
             if "Wingdings" in c["fontname"] and c["text"] == "\uf071"]
    out = []
    for b in boxes:
        struck = any(abs(l["top"] - b["top"]) < 8 and
                     b["x0"] - 3 < l["x0"] < b["x0"] + 10
                     for l in page.lines)
        if not struck:
            continue
        right = sorted((w for w in words
                        if abs(w["top"] - b["top"]) < 5 and
                        b["x0"] < w["x0"] < b["x0"] + 120 and
                        "Wingdings" not in w["fontname"]),
                       key=lambda w: w["x0"])
        if right:
            ans = right[0]["text"]
            if ans in ("OEWS",):
                ans = " ".join(w["text"] for w in right[:3])
            out.append((round(b["top"]), round(b["x0"]), ans))
    return out


# FLAG prints sometimes interleave fill-line underscores with digits
MONEY_RX = r"\$?\s*([\d,_]+)\s*\.\s*([\d_]+)"


def _money(m1, m2):
    try:
        clean = lambda s: s.replace(",", "").replace("_", "")
        cents = (clean(m2) + "00")[:2]
        return float(clean(m1) + "." + cents)
    except (ValueError, AttributeError):
        return None


def extract(pdf_path):
    out = {"meta": {"source_pdf": str(pdf_path), "form": "ETA-9141"}}
    pages_text = []
    checks_by_page = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            pages_text.append(_norm(p.extract_text() or ""))
            checks_by_page.append(_checked_answers(p))
    full = " ".join(pages_text)

    # ---- footer / meta -----------------------------------------------------
    m = re.search(r"PWD? Case Number:\s*(P-\d{3}-\d{5}-\d{6})", full)
    if not m:
        m = re.search(r"PWD tracking number:\s*(P-\d{3}-\d{5}-\d{6})", full)
    if m:
        out["pwd_case_number"] = m.group(1)
    m = re.search(r"Case Status:\s*([A-Za-z][A-Za-z ]*?)\s+Validity Period", full)
    if m:
        out["case_status"] = m.group(1).strip()
    m = re.search(r"Validity Period:?\s*([\d/]+)\s*to\s*([\d/]+)", full)
    if m:
        out["validity_from"], out["validity_to"] = m.group(1), m.group(2)

    # ---- Section C employer -------------------------------------------------
    m = re.search(r"1\.\s*Legal business name \*\s*(.+?)\s*2\.\s*Trade name", full)
    if m:
        out["employer_name"] = m.group(1).strip()
    m = re.search(r"Federal Employer Identification Number[^*]*\*\s*(\d{2}-\d{7})", full)
    if m:
        out["employer_fein"] = m.group(1)
    m = re.search(r"13\.\s*NAICS code[^\d]*(\d{4,6})", full)
    if m:
        out["naics_code"] = m.group(1)

    # ---- Section F job offer -----------------------------------------------
    m = re.search(r"1\.\s*Job title \*\s*(.+?)\s*2\.\s*Job duties", full)
    if m:
        out["job_title"] = m.group(1).strip()
    # two-column interleave puts "experience required § <months>" together
    m = re.search(r"experience required\s*.{0,3}?\s*(\d{1,3})\b", full)
    if m:
        out["experience_months_required"] = int(m.group(1))
    m = re.search(r"Addendum for Section F\.b\.4\.b:?\s*Job Requirements Occupation\s*"
                  r"(.+?)\s*(?:FOR DEPARTMENT|Page \d)", full)
    if m:
        out["experience_occupation"] = m.group(1).strip()

    # education: checked degree box on the Minimum Job Requirements page
    DEGREES = ["None", "High school/GED", "Associate's", "Bachelor's",
               "Master's", "Doctorate", "Other"]
    for pi, txt in enumerate(pages_text):
        if "Minimum Job Requirements" in txt:
            for top, x0, ans in checks_by_page[pi]:
                for d in DEGREES:
                    if ans.rstrip("'s") and d.split("/")[0].rstrip("'s").lower() \
                            in ans.lower():
                        out.setdefault("education_required", d)
            break

    # worksite (F.e)
    m = re.search(r"1\.\s*Worksite address 1 \*\s*(.+?)\s*2\.\s*Address 2", full)
    if m:
        out["worksite_address1"] = m.group(1).strip()
    m = re.search(r"3\.\s*City \*\s*4\.\s*State \*\s*5\.\s*County \*\s*6\.\s*Postal code \*\s*"
                  r"(\S.*?)\s+([A-Z]{2})\s+(.+?)\s+(\d{5})", full)
    if m:
        out["worksite_city"], out["worksite_state"] = m.group(1), m.group(2)
        out["worksite_county"], out["worksite_postal"] = m.group(3), m.group(4)

    m = re.search(r"Addendum for Section F\.d\.3\.a:?\s*Travel Details\s*(.+?)\s*(?:FOR DEPARTMENT|Page \d)",
                  full)
    if m:
        out["travel_details"] = m.group(1).strip()

    # ---- Section G determination --------------------------------------------
    m = re.search(r"3\.\s*SOC code:\s*([\d-]+)\s*a\.\s*SOC occupation title:\s*(.+?)\s*While all",
                  full)
    if m:
        out["soc_code"], out["soc_title"] = m.group(1), m.group(2).strip()
    m = re.search(r"b\.\s*O\*NET code:\s*([\d.-]+)\s*c\.\s*O\*NET occupation title:\s*(.+?)\s*When the",
                  full)
    if m:
        out["onet_code"], out["onet_title"] = m.group(1), m.group(2).strip()

    m = re.search(r"4\.\s*Prevailing wage:.*?minimum job requirements for the position\.\s*"
                  + MONEY_RX, full)
    if m:
        out["pw_minimum"] = _money(m.group(1), m.group(2))
    m = re.search(r"5\.\s*Prevailing wage:.*?alternative job requirements for the position"
                  r".*?\$\s*(N/A|[\d,_]+(?:\s*\.\s*[\d_]+)?)", full)
    if m:
        raw = m.group(1)
        if raw.upper() == "N/A" or not re.search(r"\d", raw):
            out["pw_alternative"] = None
        else:
            mm = re.match(MONEY_RX, "$" + raw)
            out["pw_alternative"] = _money(mm.group(1), mm.group(2)) if mm else None

    # per + OEWS level from checked boxes on the G page
    for pi, txt in enumerate(pages_text):
        if "PWD tracking number" in txt:
            answers = [a for _, _, a in checks_by_page[pi]]
            for per in ("Hour", "Week", "Bi-Weekly", "Month", "Year"):
                if per in answers:
                    out["pw_per"] = per
                    break
            for lvl in ("IV", "III", "II", "I", "OEWS mean", "N/A"):
                if lvl in answers:
                    out["pw_oews_level"] = lvl
                    break
            for a in answers:
                if a.startswith("OEWS"):
                    out["pw_source"] = a
                elif a in ("CBA", "DBA", "SCA"):
                    out.setdefault("pw_source", a)
                elif a.startswith(("Alternate", "Alternative")):
                    out["pw_source"] = "Alternate survey"
            break

    m = re.search(r"4\.?c,? specify the name of the survey:\s*(.+?)(?:5\.\s*Prevailing wage|a\.\s*Per)",
                  full)
    if m:
        seg = m.group(1).replace("\uf071", " ")
        for opt in ("OEWS (All Industries)", "OEWS (ACWIA)", "CBA", "DBA", "SCA",
                    "Alternate survey", "Professional sports league rules or",
                    "regulations", "Professio"):
            seg = seg.replace(opt, " ")
        seg = " ".join(seg.split()).strip()
        if seg:
            out["pw_survey_name"] = seg
    m = re.search(r"6\.\s*The wage is based on the following BLS area[^:]*:\s*(.+?)\s*7\.",
                  full)
    if m:
        out["bls_area"] = m.group(1).strip()
    m = re.search(r"9\.\s*Determination date:\s*([\d/]+)\s*10\.\s*Expiration date:\s*([\d/]+)",
                  full)
    if not m:  # column interleave: values can precede the labels
        m = re.search(r"([\d/]{6,10})\s+([\d/]{6,10})\s+9\.\s*Determination date:\s*"
                      r"10\.\s*Expiration date:", full)
    if m:
        out["determination_date"], out["expiration_date"] = m.group(1), m.group(2)
    out.setdefault("determination_date", out.get("validity_from"))
    out.setdefault("expiration_date", out.get("validity_to"))

    # addendum: special skills text (majors + experience detail)
    m = re.search(r"Addendum for Section F\.b\.5\.a\(iv\).*?Requirements\s*(.+?)\s*(?:FOR DEPARTMENT|Page \d)",
                  full)
    if m:
        out["special_skills_text"] = m.group(1).strip()

    return out


if __name__ == "__main__":
    print(json.dumps(extract(sys.argv[1]), indent=2))
