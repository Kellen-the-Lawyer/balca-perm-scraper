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


# ---------------------------------------------------------------------------
# Section-aware checkbox mapping
#
# _checked_answers returns (top, x0, answer) but the form repeats the same
# answer words across F.b (minimum) and F.c (alternative) requirements, so the
# raw list is ambiguous.  Each checked box is instead bound to the nearest
# preceding item label by y-coordinate, which splits F.b from F.c and picks up
# the 5.a sub-items.  Labels print on every determination whether or not the
# item is answered, so unanswered items (e.g. G.3.d) resolve to None rather
# than going missing.
#
# UNVALIDATED PATHS — no fixture on hand exercises these; the parsing is
# written but unproven, so confirm against a real determination before any
# rule relies on them:
#   * F.b.5.a / F.c.5.a sub-items (i) License, (ii) Foreign language,
#     (iii) Residency.  Only (iv) appears in the current fixtures, and it is
#     read correctly, so the mechanism works — the sub-item labels are what
#     is unproven.
#   * G.3.d / G.3.e populated (combination of occupations).  The empty case
#     is validated across all three fixtures.
#   * training_months_primary / training_months_alternate (F.b.3.a, F.c.3.a).
# ---------------------------------------------------------------------------

_ANCHOR_RX = [
    ("F.a.3", r"does this position supervise"),
    ("F.b.1", r"minimum u\.?\s?s\.? degree required"),
    ("F.b.2", r"require a second u\.?\s?s\.? degree"),
    ("F.b.3", r"is training for the job opportunity required"),
    ("F.b.4", r"is employment experience required"),
    ("SKILLS", r"special skills or other requirements"),
    ("F.c.1", r"are alternate sets of education"),
    ("F.c.2", r"specify the alternate level of education"),
    ("F.c.3", r"is alternate training for the job"),
    ("F.c.4", r"is alternate employment experience accepted"),
    ("F.d.1", r"suggested soc"),
    ("F.d.3", r"will travel be required"),
    ("F.e.7", r"will work be performed in any bureau"),
]

SUBITEM_RX = re.compile(r"^\(i{1,3}v?\)$")


def _lines(page):
    """[(top, line_text)] with words grouped into visual lines."""
    buckets = {}
    for w in page.extract_words():
        buckets.setdefault(round(w["top"] / 3) * 3, []).append(w)
    return sorted((top, " ".join(x["text"] for x in sorted(ws,
                                                           key=lambda z: z["x0"])))
                  for top, ws in buckets.items())


def _anchors(pages):
    """[(page_index, top, item_key)] in document order.

    'Special skills or other requirements' appears verbatim under both F.b.5
    and F.c.5, so the first occurrence is taken as F.b.5 and the second as
    F.c.5 — the form always prints them in that order.
    """
    found, skills = [], 0
    for pi, page in enumerate(pages):
        for top, text in _lines(page):
            low = text.lower()
            for key, rx in _ANCHOR_RX:
                if re.search(rx, low):
                    if key == "SKILLS":
                        skills += 1
                        key = "F.b.5" if skills == 1 else "F.c.5"
                    found.append((pi, top, key))
                    break
    return found


def _checks_by_item(pages):
    """{item_key: [checked answer words]} bound by nearest preceding label."""
    anchors = _anchors(pages)
    out = {}
    for pi, page in enumerate(pages):
        page_anchors = [(t, k) for p, t, k in anchors if p == pi]
        if not page_anchors:
            continue
        for top, x0, ans in sorted(_checked_answers(page)):
            cands = [(abs(top - t), k) for t, k in page_anchors if top >= t - 6]
            if cands:
                out.setdefault(min(cands)[1], []).append(ans)
    return out


def _addendum(full, section):
    """Body text of 'Addendum for Section <section>', title stripped."""
    esc = re.escape(section)
    m = re.search(r"ADDENDUM\s*Section\s*" + esc + r":\s*(.+?)\s*"
                  r"Addendum for Section\s*" + esc + r":\s*(.+?)\s*"
                  r"(?:FOR DEPARTMENT|Page \d+ of)", full)
    if not m:
        return None
    title, body = m.group(1).strip(), m.group(2).strip()
    if body.startswith(title):
        body = body[len(title):].strip()
    return body or None


def _degree_of(answers):
    DEGREES = ["None", "High school/GED", "Associate's", "Bachelor's",
               "Master's", "Doctorate", "Other"]
    for ans in answers or []:
        for d in DEGREES:
            if d.split("/")[0].rstrip("'s").lower() in ans.lower().replace(
                    "\u2019", "'"):
                return d
    return None


def _yesno(answers):
    for a in answers or []:
        if a in ("Yes", "No"):
            return a
    return None


def _subitems(answers):
    return [a for a in (answers or []) if SUBITEM_RX.match(a)]


def extract(pdf_path):
    out = {"meta": {"source_pdf": str(pdf_path), "form": "ETA-9141"}}
    pages_text = []
    checks_by_page = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            pages_text.append(_norm(p.extract_text() or ""))
            checks_by_page.append(_checked_answers(p))
        items = _checks_by_item(pdf.pages)
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

    # ---- Section F.b minimum vs F.c alternative requirements ---------------
    out["education_primary"] = _degree_of(items.get("F.b.1"))
    out["second_degree_required"] = _yesno(items.get("F.b.2"))
    out["training_required"] = _yesno(items.get("F.b.3"))
    out["experience_required"] = _yesno(items.get("F.b.4"))
    out["special_reqs_primary"] = _yesno(items.get("F.b.5"))
    out["special_reqs_items_primary"] = _subitems(items.get("F.b.5"))

    out["alternate_reqs_accepted"] = _yesno(items.get("F.c.1"))
    out["education_alternate"] = _degree_of(items.get("F.c.2"))
    out["training_alternate_accepted"] = _yesno(items.get("F.c.3"))
    out["experience_alternate_accepted"] = _yesno(items.get("F.c.4"))
    out["special_reqs_alternate"] = _yesno(items.get("F.c.5"))
    out["special_reqs_items_alternate"] = _subitems(items.get("F.c.5"))

    # (ii) is the foreign-language sub-item under both 5.a lists
    out["foreign_language_primary"] = \
        "(ii)" in out["special_reqs_items_primary"]
    out["foreign_language_alternate"] = \
        "(ii)" in out["special_reqs_items_alternate"]

    # months: F.b.4.a (minimum) and F.c.4.a (alternate) — two-column interleave
    # puts each label adjacent to its own value in the text stream.  When the
    # field is blank the next thing in the stream is the following item number
    # ("5. Special skills..."), so reject a digit followed by a period and only
    # trust the value when its Yes/No parent says the requirement exists.
    def _months(rx, gate):
        if gate != "Yes":
            return None
        m = re.search(rx + r"\s*.{0,3}?\s*(\d{1,3})\b(?!\s*\.)", full)
        return int(m.group(1)) if m else None

    out["experience_months_primary"] = _months(
        r"experience required", out.get("experience_required"))
    out["experience_months_alternate"] = _months(
        r"alternate experience accepted", out.get("experience_alternate_accepted"))
    out["training_months_primary"] = _months(
        r"of training required", out.get("training_required"))
    out["training_months_alternate"] = _months(
        r"alternate training accepted", out.get("training_alternate_accepted"))


    # majors / occupation / special-skills text, following addendum pointers
    out["majors_primary"] = _addendum(full, "F.b.1.b")
    out["majors_alternate"] = _addendum(full, "F.c.2.b")
    out["experience_occupation"] = _addendum(full, "F.b.4.b")
    out["special_skills_text"] = _addendum(full, "F.b.5.a(iv)")
    out["special_skills_text_alternate"] = _addendum(full, "F.c.5.a(iv)")

    # Back-compat aliases: Tier 3 (T3-020/T3-021) and the O*NET check
    # (T4-007) still read the un-suffixed keys as "the" requirement.
    out["education_required"] = out["education_primary"]
    if out.get("experience_months_primary") is not None:
        out["experience_months_required"] = out["experience_months_primary"]

    # ---- Section F job offer -----------------------------------------------
    m = re.search(r"1\.\s*Job title \*\s*(.+?)\s*2\.\s*Job duties", full)
    if m:
        out["job_title"] = m.group(1).strip()

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

    # G.3.d/G.3.e — "other occupations" listed when the job opportunity is a
    # combination of occupations.  The labels print whether or not they are
    # answered, so an empty capture is the unanswered case.  The code may be a
    # 6- or 8-digit SOC/O*NET code; anything that is not blank or N/A counts.
    m = re.search(r"other occupations\.?\s*d\.\s*O\*NET code:\s*(.*?)\s*"
                  r"e\.\s*O\*NET occupation title:\s*(.*?)\s*4\.\s*Prevailing wage",
                  full)
    if m:
        code, title = m.group(1).strip(), m.group(2).strip()
        blank = lambda v: (not v) or v.upper() in ("N/A", "NA", "NONE")
        out["combination_code"] = None if blank(code) else code
        out["combination_title"] = None if blank(title) else title
        out["combination_of_occupations"] = not (blank(code) and blank(title))
    else:
        out["combination_of_occupations"] = None

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

    return out


if __name__ == "__main__":
    print(json.dumps(extract(sys.argv[1]), indent=2))
