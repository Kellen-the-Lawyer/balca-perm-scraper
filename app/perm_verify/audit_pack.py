"""
Tier 5 — PERM audit-pack verification.

Takes the audit file (compliance pack PDF), classifies each page by text
fingerprint, extracts evidence facts (dates, publications, wages), reads
photographed evidence (posting notice) through a local VLM, and
cross-checks everything against the ETA-9089 form dict and the ETA-9141
PWD. Pure rules except the VLM step; the VLM loads on demand and unloads
after (keep_alive/TTL managed by the serving layer).

VLM endpoint: AUDIT_VLM_URL env (default LM Studio, qwen3-vl-8b).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timedelta

from .rules import Flag, RED, YELLOW, _get, _d, filing_window

VLM_URL = os.environ.get(
    "AUDIT_VLM_URL", "http://localhost:1234/v1/chat/completions")
VLM_MODEL = os.environ.get("AUDIT_VLM_MODEL", "qwen/qwen3-vl-8b")

GREEN = "GREEN"  # informational "verified" entries in the audit report

# ---------------------------------------------------------------- classify

FINGERPRINTS = [
    ("cover_letter",    r"PERM Audit File"),
    ("recruitment_report", r"RECRUITMENT REPORT|Recruitment Checklist for PERM"),
    ("eta_9141",        r"Form ETA-?9141|ETA Form 9141"),
    ("posting_notice",  r"IMG_\d+\.(HEIC|JPG|JPEG)|Powered by Box"),
    ("job_bank",        r"Eightfold Career Hub|labor\.ny\.gov"),
    ("nyt_tearsheet",   r"THE NEW YORK TIMES|nytimes\.com/jobs|nylimes\.com"),
    ("jobvertise",      r"jobvertise\.com/job|Search Jobvertise Jobs"),
    ("amny",            r"www\.amNY\.com|amNY CLASSIFIED"),
    ("radio_invoice",   r"IHeart[Mm]edia|WLTW"),
]

DATE_HDR_RX = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
NYT_MARKER_RX = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
LONG_DATE_RX = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s*(\d{1,2}),?\s*(\d{4})", re.I)


def classify_page(text):
    for kind, rx in FINGERPRINTS:
        if re.search(rx, text):
            return kind
    return "other"


def _hdr_date(text):
    m = DATE_HDR_RX.search(text[:200])
    return m.group(1) if m else None


def _long_date(text):
    m = LONG_DATE_RX.search(text)
    if not m:
        return None
    return datetime.strptime(
        f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()


def _cid_decode(text):
    """Decode the shifted-by-16 subset font used in some NYT tear sheets:
    (cid:N) -> chr(N+16), literal chars -> chr(ord+16). Normal text becomes
    garbage under this transform, so only regex hits on the decoded copy
    (e.g. the masthead date) are meaningful."""
    out = []
    for tok in re.split(r"(\(cid:\d+\))", text):
        m = re.match(r"\(cid:(\d+)\)", tok)
        if m:
            n = int(m.group(1)) + 16
            out.append(chr(n) if 32 <= n < 127 else " ")
        else:
            out.append("".join(
                chr(ord(c) + 16) if 32 <= ord(c) + 16 < 127 else " "
                for c in tok))
    return "".join(out)


def segment_pack(pdf_path):
    """Classify every page; extract per-kind facts from the text layer."""
    import pdfplumber
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            kind = classify_page(text)
            pages.append({"page": i + 1, "kind": kind, "text": text})
    return pages


# ---------------------------------------------------------------- extract

def extract_pack_facts(pages):
    """Reduce classified pages into evidence facts."""
    f = {"kinds_present": sorted({p["kind"] for p in pages} - {"other"}),
         "pages_by_kind": {}}
    for p in pages:
        f["pages_by_kind"].setdefault(p["kind"], []).append(p["page"])
    all_text = "\n".join(p["text"] for p in pages)

    # Cover letter: retention placeholder + claimed inventory
    cov = "\n".join(p["text"] for p in pages if p["kind"] == "cover_letter")
    if cov:
        f["cover_letter"] = {
            "retain_until_placeholder": bool(
                re.search(r"Retain until\s*DATE", cov)),
            "claims_filed_9089": bool(
                re.search(r"Filed ETA Form 9089", cov)),
        }

    # 9141 (from the pack's embedded copy): footer + Section G fields
    p9141 = "\n".join(p["text"] for p in pages if p["kind"] == "eta_9141")
    if p9141:
        pwd = {}
        m = re.search(r"PWD? (?:Case|Tracking) Number:?\s*(P-100-\d{5}-\d{6})",
                      p9141)
        pwd["pwd_case_number"] = m.group(1) if m else None
        m = re.search(r"Validity Period:?\s*(\d{1,2}/\d{1,2}/\d{4})\s*to\s*"
                      r"(\d{1,2}/\d{1,2}/\d{4})", p9141)
        if m:
            pwd["validity_from"], pwd["validity_to"] = m.group(1), m.group(2)
        m = re.search(r"SOC code:?\s*([\d-]{6,10})", p9141)
        pwd["soc_code"] = m.group(1) if m else None
        # G.4 primary wage / G.5 alternative wage ($ may wrap lines)
        wages = re.findall(r"\$[\s\n]*([\d,]{4,})[\s\n]*\.", p9141)
        if len(wages) < 2:
            wages += re.findall(r"\$[\s\n]*([\d,]{4,})[\s\n]*\.",
                                _cid_decode(p9141))
        wages = [int(w.replace(",", "")) for w in wages if
                 int(w.replace(",", "")) > 10000]
        if wages:
            pwd["pw_primary"] = wages[0]
            pwd["pw_alternative"] = wages[1] if len(wages) > 1 else None
        levels = re.findall(r"OEWS wage level[\s\S]{0,120}?"
                            r"\b(IV|III|II|I)\b", p9141)
        pwd["wage_levels"] = levels[:2]
        f["pwd_in_pack"] = pwd

    # SWA job order evidence (state job bank printouts)
    jb = [(_hdr_date(p["text"]), p["page"], p["text"]) for p in pages
          if p["kind"] == "job_bank"]
    f["job_bank_prints"] = [{"date": d, "page": pg,
                             "wage_figures": _wage_figures(t)}
                            for d, pg, t in jb if d]

    # NYT Sunday tear sheets: press marker, masthead date, or cid-decoded
    nyt = []
    for p in pages:
        if p["kind"] != "nyt_tearsheet":
            continue
        d = None
        m = NYT_MARKER_RX.search(p["text"][:200])
        if m:
            d = f"{int(m.group(2))}/{int(m.group(3))}/{m.group(1)}"
        if not d:
            ld = _long_date(p["text"][:2000]) or \
                _long_date(_cid_decode(p["text"][:2000]))
            if ld:
                d = f"{ld.month}/{ld.day}/{ld.year}"
        readable = "Software Engineer" in p["text"]
        nyt.append({"date": d, "page": p["page"],
                    "ad_text_readable": readable,
                    "wage_figures": _wage_figures(p["text"])
                    if readable else []})
    f["nyt_tearsheets"] = nyt

    # Jobvertise printouts
    f["jobvertise_prints"] = [
        {"date": _hdr_date(p["text"]), "page": p["page"],
         "contains_ref": "00089423" in p["text"],
         "contains_salary": bool(re.search(r"190,?000", p["text"])),
         "wage_figures": _wage_figures(p["text"])}
        for p in pages if p["kind"] == "jobvertise"]

    # amNY local paper
    amny = []
    for p in pages:
        if p["kind"] != "amny":
            continue
        ld = _long_date(p["text"][:3000])
        amny.append({"date": f"{ld.month}/{ld.day}/{ld.year}" if ld else None,
                     "page": p["page"],
                     "contains_ref": "00089423" in p["text"],
                     "wage_figures": _wage_figures(p["text"])})
    f["amny_tearsheets"] = amny

    # Radio invoice
    radio = "\n".join(p["text"] for p in pages if p["kind"] == "radio_invoice")
    if radio:
        m = re.search(r"(\d{2}/\d{2}/\d{4})", radio)
        f["radio_invoice"] = {
            "air_date": m.group(1) if m else None,
            "station": ("WLTW-FM" if "WLTW" in radio else None),
            "script_has_salary": bool(
                re.search(r"ONE HUNDRED NINETY THOUSAND", radio, re.I)),
            "script_has_ref": "00089423" in radio,
        }

    # Recruitment report / applicant evaluations
    rr = [p for p in pages if p["kind"] == "recruitment_report"]
    if rr:
        rr_text = "\n".join(p["text"] for p in rr)
        m = re.search(r"notice of filing from\s*(\d{1,2}/\d{1,2}/\d{4})\s*"
                      r"to\s*(\d{1,2}/\d{1,2}/\d{4})", rr_text, re.I)
        f["recruitment_report"] = {
            "pages": [p["page"] for p in rr],
            "applicant_evaluations": sum(
                1 for p in rr if "Recruitment Checklist" in p["text"]),
            "beneficiary_named": "BHARGAVA" in rr_text,
            "notice_posted": m.group(1) if m else None,
            "notice_removed": m.group(2) if m else None,
        }
    return f


# ---------------------------------------------------------------- VLM step

NOTICE_PROMPT = """You are reading a photograph of a PERM Notice of Filing
physically posted at a worksite. Some fields are HANDWRITTEN. Reply with ONLY
a JSON object:
{"job_title": "...", "reference_number": "...", "salary_min": "...",
 "salary_max": "...", "date_posted": "M/D/YY", "date_removed": "M/D/YY",
 "posting_location": "...", "signer_name": "...", "signer_title": "...",
 "has_signature": true/false}
Use null for unreadable fields. Do not guess."""


def _rasterize_page(pdf_path, page_no, out_dir, dpi=200):
    """poppler pdftoppm -> JPEG for one page; returns path."""
    prefix = os.path.join(out_dir, "pg")
    subprocess.run(
        ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", str(dpi),
         "-jpeg", "-jpegopt", "quality=80", pdf_path, prefix],
        check=True, capture_output=True)
    for name in os.listdir(out_dir):
        if name.startswith("pg") and name.endswith(".jpg"):
            return os.path.join(out_dir, name)
    raise RuntimeError("rasterization produced no output")


def vlm_read_notice(pdf_path, page_no):
    """Rasterize the posting-notice photo page and extract via local VLM."""
    import base64
    with tempfile.TemporaryDirectory() as td:
        jpg = _rasterize_page(pdf_path, page_no, td)
        img_b64 = base64.b64encode(open(jpg, "rb").read()).decode()
    payload = {
        "model": VLM_MODEL, "temperature": 0, "max_tokens": 4000,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": NOTICE_PROMPT},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{img_b64}"}}]}]}
    req = urllib.request.Request(
        VLM_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read())
    raw = out["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else None


# ---------------------------------------------------------------- helpers

def _biz_days(a, b):
    """Business days from a through b inclusive (no holiday calendar)."""
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _d2(s):
    """Like rules._d but tolerant of 2-digit years (5/4/26 -> 2026)."""
    d = _d(s)
    if d and d.year < 100:
        d = d.replace(year=d.year + 2000)
    if d is None and s:
        try:
            d = datetime.strptime(str(s).strip(), "%m/%d/%y").date()
        except ValueError:
            return None
    return d


def _same_day(a, b):
    da, db = _d2(a), _d2(b)
    return da is not None and da == db


def _wage_num(v):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


WAGE_FIG_RX = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2}|\d{4,7})")
WAGE_CTX_RX = re.compile(
    r"salary|wage|per\s+(?:year|hour|week|month|annum)|annually|"
    r"/\s?(?:yr|hr|year|hour)|compensation|pay(?:\s+rate)?", re.I)


def _wage_figures(text, window=80):
    """Dollar figures that appear in a wage context within ad/evidence text.

    Keyword-window guard keeps prices in surrounding newspaper content from
    being read as wages.  Returns floats, deduped, order preserved.
    """
    out = []
    for m in WAGE_FIG_RX.finditer(text or ""):
        ctx = text[max(0, m.start() - window):m.end() + window]
        if not WAGE_CTX_RX.search(ctx):
            continue
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if v not in out:
            out.append(v)
    return out


# ---------------------------------------------------------------- T5 rules

REQUIRED_EVIDENCE = {
    "eta_9141": "Prevailing wage determination (ETA-9141)",
    "posting_notice": "Notice of Filing (posting notice)",
    "job_bank": "SWA job order proof (state job bank printouts)",
    "nyt_tearsheet": "Sunday newspaper tear sheets",
    "recruitment_report": "Recruitment report / applicant evaluations",
}


def crosscheck(form, pack, notice=None, filing_date=None):
    """Cross-check audit-pack evidence against the 9089 (and its PWD refs).

    Returns a list of Flag objects. GREEN = affirmatively verified.
    """
    flags = []
    F = flags.append
    first_day, last_day = filing_window(form)

    # --- T5-001 evidence checklist -------------------------------------
    present = set(pack.get("kinds_present", []))
    for kind, label in REQUIRED_EVIDENCE.items():
        if kind not in present:
            F(Flag(RED, "T5-001", "audit-file",
                   f"Audit file is missing: {label}.",
                   "regulation", "20 CFR 656.10(f); 656.17(e)"))
    cov = pack.get("cover_letter", {})
    if cov.get("claims_filed_9089") and "eta_9089" not in present:
        F(Flag(YELLOW, "T5-002", "audit-file",
               "Cover letter inventory claims the filed ETA-9089 is included "
               "but no 9089 was found in the pack.",
               "data_check", "letter-vs-contents"))
    if cov.get("retain_until_placeholder"):
        F(Flag(YELLOW, "T5-003", "audit-file",
               "Retention letter contains an unfilled 'Retain until DATE' "
               "placeholder — retention deadline was never set.",
               "typo", "5-year retention, 20 CFR 656.10(f)"))

    # --- T5-010 PWD case number & validity ------------------------------
    pwd = pack.get("pwd_in_pack") or {}
    form_pwd = _get(form, "E_job_wage.pwd_case_number")
    if pwd.get("pwd_case_number") and form_pwd:
        if pwd["pwd_case_number"] != form_pwd:
            F(Flag(RED, "T5-010", "E.1",
                   f"PWD in audit file ({pwd['pwd_case_number']}) does NOT "
                   f"match 9089 E.1 ({form_pwd}) — wrong determination in "
                   f"the pack.", "data_check", "cross-document"))
        else:
            F(Flag(GREEN, "T5-010", "E.1",
                   f"PWD case number matches 9089: {form_pwd}.",
                   "data_check", "verified"))
    vf, vt = _d(pwd.get("validity_from")), _d(pwd.get("validity_to"))
    rs = _d(_get(form, "H_recruitment.swa_job_order_start"))
    if vf and vt and rs:
        if vf <= rs <= vt:
            F(Flag(GREEN, "T5-011", "PWD",
                   f"Recruitment began {rs} within PWD validity {vf}-{vt} "
                   f"(20 CFR 656.40(c) satisfied even if filing is after "
                   f"expiration).", "regulation", "20 CFR 656.40(c)"))
        elif first_day and vt < first_day:
            F(Flag(RED, "T5-011", "PWD",
                   f"PWD expired {vt}, before the first day to file "
                   f"({first_day}), and recruitment did not begin within "
                   f"the validity period.",
                   "regulation", "20 CFR 656.40(c)"))

    # --- T5-012 wage sufficiency ----------------------------------------
    offered = _wage_num(_get(form, "E_job_wage.offered_wage_from"))
    pw_alt = pwd.get("pw_alternative")
    pw_pri = pwd.get("pw_primary")
    # The offered wage must meet the HIGHEST wage on the PWD, not merely
    # the alternative when one exists (mirrors T3-001's higher-of-two).
    cands = [w for w in (pw_alt, pw_pri) if w]
    governing = max(cands) if cands else None
    if offered and governing:
        which = "higher of the two PWD wages" if len(cands) == 2 \
            else "prevailing wage"
        if offered < governing:
            F(Flag(RED, "T5-012", "E.3",
                   f"Offered wage {offered:,.0f} is below the {which} "
                   f"{governing:,.0f} from the PWD.",
                   "regulation", "20 CFR 656.10(c)(1)"))
        else:
            F(Flag(GREEN, "T5-012", "E.3",
                   f"Offered wage {offered:,.0f} meets the {which} "
                   f"{governing:,.0f}.",
                   "regulation", "verified"))

    # --- T5-020 SWA job order evidence ----------------------------------
    jo_s = _get(form, "H_recruitment.swa_job_order_start")
    jo_e = _get(form, "H_recruitment.swa_job_order_end")
    jb = pack.get("job_bank_prints", [])
    if jb:
        have_start = any(_same_day(p["date"], jo_s) for p in jb)
        have_end = any(_same_day(p["date"], jo_e) for p in jb)
        if have_start and have_end:
            F(Flag(GREEN, "T5-020", "H.c.1",
                   f"Job bank printouts document the job order at start "
                   f"({jo_s}) and end ({jo_e}).", "data_check", "verified"))
        else:
            F(Flag(YELLOW, "T5-020", "H.c.1",
                   f"Job bank printouts ({[p['date'] for p in jb]}) do not "
                   f"bracket the 9089 job order dates {jo_s}-{jo_e}.",
                   "data_check", "cross-document"))

    # --- T5-021 Sunday ad tear sheets -----------------------------------
    for i, key in enumerate(["ad1_date", "ad2_date"], 1):
        ad = _get(form, f"H_recruitment.{key}")
        hits = [t for t in pack.get("nyt_tearsheets", [])
                if _same_day(t["date"], ad)]
        if hits:
            note = "" if any(t["ad_text_readable"] for t in hits) else \
                " (ad text not machine-readable on the tear sheet; " \
                "visual check advised)"
            F(Flag(GREEN, "T5-021", f"H.c.{i+1}b",
                   f"Tear sheet documents Sunday ad {i} on {ad}.{note}",
                   "data_check", "verified"))
        else:
            F(Flag(RED, "T5-021", f"H.c.{i+1}b",
                   f"No tear sheet found for Sunday ad {i} ({ad}).",
                   "regulation", "20 CFR 656.17(e)(1)(i)(B)"))

    # --- T5-022 additional steps evidence -------------------------------
    steps = _get(form, "H_recruitment.additional_steps", {}) or {}
    ev_map = {
        "job_search_website": [p["date"] for p in
                               pack.get("jobvertise_prints", [])],
        "local_ethnic_newspaper": [t["date"] for t in
                                   pack.get("amny_tearsheets", [])],
        "radio_tv": [pack.get("radio_invoice", {}).get("air_date")],
    }
    for code, ev_dates in ev_map.items():
        if code not in steps:
            continue
        want_from = steps[code].get("from")
        want_to = steps[code].get("to")
        ev_dates = [d for d in ev_dates if d]
        ok_from = any(_same_day(d, want_from) for d in ev_dates)
        ok_to = any(_same_day(d, want_to) for d in ev_dates) or \
            want_to == want_from
        if ev_dates and ok_from and ok_to:
            F(Flag(GREEN, "T5-022", "H.d",
                   f"Evidence documents '{code}' on {want_from}"
                   + (f" through {want_to}" if want_to != want_from else "")
                   + ".", "data_check", "verified"))
        elif ev_dates:
            F(Flag(YELLOW, "T5-022", "H.d",
                   f"'{code}' evidence dates {ev_dates} do not match the "
                   f"9089 dates {want_from}-{want_to}.",
                   "data_check", "cross-document"))
        else:
            F(Flag(RED, "T5-022", "H.d",
                   f"No evidence found in the pack for additional step "
                   f"'{code}' ({want_from}).",
                   "regulation", "20 CFR 656.17(e)(1)(ii)"))

    # --- T5-023 ad content consistency ----------------------------------
    jv = pack.get("jobvertise_prints", [])
    if jv and not any(p["contains_ref"] for p in jv):
        F(Flag(YELLOW, "T5-023", "H.d.3",
               "Jobvertise printout does not contain the requisition "
               "reference number.", "data_check", "cross-document"))
    ri = pack.get("radio_invoice", {})
    if ri and not ri.get("script_has_salary"):
        F(Flag(YELLOW, "T5-023", "H.d.10",
               "Radio script does not state the offered salary.",
               "data_check", "cross-document"))

    # --- T5-024 wage stated in recruitment materials --------------------
    # Any wage figure appearing in recruitment evidence must MATCH the
    # wage on the 9089 (E.3) — match, not merely a floor.  Ads are not
    # federally required to state a wage, so silence when none is found
    # (some jurisdictions require it; jurisdiction-specific presence
    # checks are not implemented).  Accepted values: E.3 from/to as
    # stated, and their annualized equivalents.
    ok_vals = set()
    for _k in ("offered_wage_from", "offered_wage_to"):
        _v = _wage_num(_get(form, f"E_job_wage.{_k}"))
        if _v:
            ok_vals.add(round(_v, 2))
    _per = _get(form, "E_job_wage.wage_per") or "Year"
    _mult = {"Hour": 2080, "Week": 52, "Bi-Weekly": 26,
             "Month": 12, "Year": 1}.get(_per, 1)
    ok_vals |= {round(v * _mult, 2) for v in list(ok_vals)}
    if ok_vals:
        _srcs = [
            ("job_bank_prints", "SWA job order printout", RED, "H.c.1"),
            ("jobvertise_prints", "Job search website printout", RED, "H.d"),
            ("amny_tearsheets", "Local newspaper tear sheet", YELLOW, "H.d"),
            ("nyt_tearsheets", "Sunday newspaper tear sheet", YELLOW,
             "H.c"),
        ]
        for _key, _label, _lvl, _item in _srcs:
            for _ev in pack.get(_key, []) or []:
                _figs = _ev.get("wage_figures") or []
                if not _figs:
                    continue
                if any(round(x, 2) in ok_vals for x in _figs):
                    F(Flag(GREEN, "T5-024", _item,
                           f"{_label} (page {_ev.get('page')}) states a "
                           f"wage matching the 9089 offered wage.",
                           "data_check", "verified"))
                else:
                    F(Flag(_lvl, "T5-024", _item,
                           f"{_label} (page {_ev.get('page')}) states wage "
                           f"figure(s) {[f'{x:,.0f}' for x in _figs]} that "
                           f"do not match the 9089 offered wage — "
                           f"recruitment materials must state the same "
                           f"wage as the 9089.",
                           "regulation", "20 CFR 656.17(f)(7)"))

    # --- T5-025 EPT wage-disclosure laws (state/local) ------------------
    # If the worksite state has an Equal Pay Transparency law effective at
    # the time an ad ran, and no wage figure was detected in that ad,
    # flag YELLOW.  Applicability is hard to fully determine (employer
    # thresholds, remote coverage, long-arm reach), so this never goes
    # RED.  A.14 (employees in the area of intended employment) is a
    # lower bound on both state and total headcount: A.14 >= threshold
    # PROVES the count condition; below it proves nothing.
    from .ept import lookup_ept
    _ept = lookup_ept(_get(form, "F_worksite.state"),
                      _get(form, "F_worksite.city"))
    if _ept:
        try:
            _n_area = int(str(_get(
                form, "A_employer.num_employees_in_area")).replace(",", ""))
        except (TypeError, ValueError):
            _n_area = None
        _thresh_met = (_ept["threshold_count"] == 0 or
                       (_n_area is not None
                        and _n_area >= _ept["threshold_count"]))
        _basis = (f"threshold met (A.14 shows {_n_area} employees in the "
                  f"area \u2265 {_ept['threshold_count']})" if _thresh_met
                  else f"could not confirm the "
                       f"{_ept['threshold_count']}-employee threshold from "
                       f"A.14 alone \u2014 verify "
                       f"{_ept['threshold_scope']}-level headcount")
        _ept_srcs = [
            ("job_bank_prints", "SWA job order printout", "H.c.1"),
            ("jobvertise_prints", "Job search website printout", "H.d"),
            ("amny_tearsheets", "Local newspaper tear sheet", "H.d"),
            ("nyt_tearsheets", "Sunday newspaper tear sheet", "H.c"),
        ]
        for _key, _label, _item in _ept_srcs:
            for _ev in pack.get(_key, []) or []:
                _ad = _d2(_ev.get("date"))
                if not _ad or _ad < _ept["effective"]:
                    continue
                if _ev.get("wage_figures"):
                    continue
                F(Flag(YELLOW, "T5-025", _item,
                       f"{_label} (page {_ev.get('page')}, {_ev.get('date')})"
                       f" states no wage, but {_ept['state']} requires "
                       f"compensation disclosure in job postings "
                       f"({_ept['citation']}, eff. {_ept['effective']}); "
                       f"{_basis}. {_ept['note']}",
                       "data_check", _ept["citation"]))

    # --- T5-030 posting notice (VLM-read) --------------------------------
    rr_meta = pack.get("recruitment_report") or {}
    if notice:
        dp, dr = _d2(notice.get("date_posted")), _d2(notice.get("date_removed"))
        # Corroborate the VLM's handwriting read against the recruitment
        # report's machine-readable statement of the same dates.
        rp, rr_ = _d2(rr_meta.get("notice_posted")), \
            _d2(rr_meta.get("notice_removed"))
        if dp and rp and (dp != rp or (dr and rr_ and dr != rr_)):
            F(Flag(YELLOW, "T5-034", "H.e",
                   f"Notice photo reads {dp}-{dr} but the recruitment report "
                   f"states {rp}-{rr_} — verify the handwritten dates.",
                   "data_check", "cross-source"))
        elif dp and rp:
            F(Flag(GREEN, "T5-034", "H.e",
                   f"Handwritten notice dates corroborated by the "
                   f"recruitment report ({rp}-{rr_}).",
                   "data_check", "verified"))
        if dp and dr:
            days = _biz_days(dp, dr)
            if days >= 10:
                F(Flag(GREEN, "T5-030", "H.e",
                       f"Notice posted {dp} to {dr}: {days} business days "
                       f"(>=10 required).",
                       "regulation", "20 CFR 656.10(d)(1)(ii)"))
            else:
                F(Flag(RED, "T5-030", "H.e",
                       f"Notice posted {dp} to {dr}: only {days} business "
                       f"days (<10).",
                       "regulation", "20 CFR 656.10(d)(1)(ii)"))
        n_sal = _wage_num(notice.get("salary_min"))
        if n_sal and offered and n_sal != offered:
            F(Flag(RED, "T5-031", "H.e",
                   f"Notice salary ({n_sal:,.0f}) differs from 9089 offered "
                   f"wage ({offered:,.0f}).", "data_check", "cross-document"))
        elif n_sal and offered:
            F(Flag(GREEN, "T5-031", "H.e",
                   f"Notice salary matches 9089 offered wage "
                   f"({offered:,.0f}).", "data_check", "verified"))
        import difflib
        b_name = ((_get(form, "B_poc.first_name") or "") + " " +
                  (_get(form, "B_poc.last_name") or "")).strip().lower()
        s_name = (notice.get("signer_name") or "").strip().lower()
        if b_name and s_name:
            sim = difflib.SequenceMatcher(None, b_name, s_name).ratio()
            if sim >= 0.85 and b_name != s_name:
                F(Flag(GREEN, "T5-032", "H.e",
                       f"Notice signer '{notice.get('signer_name')}' matches "
                       f"the 9089 contact within OCR tolerance "
                       f"(similarity {sim:.2f}) — confirm visually.",
                       "data_check", "verified"))
            elif sim < 0.85:
                F(Flag(YELLOW, "T5-032", "H.e",
                       f"Notice signer '{notice.get('signer_name')}' does "
                       f"not match the 9089 employer contact.",
                       "data_check", "cross-document"))
        if not notice.get("has_signature"):
            F(Flag(RED, "T5-033", "H.e",
                   "Posting notice does not appear to be signed.",
                   "data_check", "documentation"))

    # --- T5-040 recruitment report ---------------------------------------
    if rr_meta and not rr_meta.get("beneficiary_named"):
        F(Flag(YELLOW, "T5-040", "audit-file",
               "Recruitment report does not reference the beneficiary.",
               "data_check", "cross-document"))
    return flags


def verify_audit_pack(pack_pdf, form, filing_date=None, use_vlm=True):
    """Full Tier-5 run: segment -> extract -> VLM notice -> crosscheck."""
    pages = segment_pack(pack_pdf)
    pack = extract_pack_facts(pages)
    notice = None
    if use_vlm and pack["pages_by_kind"].get("posting_notice"):
        notice = vlm_read_notice(pack_pdf,
                                 pack["pages_by_kind"]["posting_notice"][0])
    flags = crosscheck(form, pack, notice, filing_date)
    summary = {lvl: sum(1 for f in flags if f.level == lvl)
               for lvl in ("RED", "YELLOW", "GREEN")}
    return {"pack_facts": pack, "notice": notice,
            "flags": [f.to_dict() for f in flags], "summary": summary}
