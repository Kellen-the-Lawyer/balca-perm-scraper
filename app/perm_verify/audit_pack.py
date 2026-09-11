"""
Tier 5 — PERM audit-pack verification (redesigned 9/10).

Takes the audit file (compliance pack PDF), turns every page into a
generic EVIDENCE record keyed to the ETA-9089's own recruitment-method
codes, and cross-checks those records against the 9089 (and the PWD copy
found in the pack).  Emits GREEN "affirmatively verified" entries as well
as RED/YELLOW.

Evidence contract — one record per page, produced by either classifier:
    {"kind": <code>, "page": n, "readable": bool, "dates": ["M/D/YYYY",..],
     "publication": str|None, "wage_figures": [float], "text": str,
     "reference_number": str|None, "notes": str}
kind codes:
    document kinds: eta_9089 eta_9141 cover_letter posting_notice
                    recruitment_report
    9089 H.c:       swa_job_order sunday_ad
    9089 H.d:       job_fair employer_website job_search_website on_campus
                    trade_org private_firm employee_referral
                    campus_placement local_ethnic_newspaper radio_tv
    other

Two classifiers:
  * VLM (default, AUDIT_CLASSIFIER=vlm): every page rasterized and read by
    the local VLM (LM Studio, qwen3-vl-8b), which returns the record
    directly.  Local -> no API cost.  This is the "each recruitment piece
    looks different" path.
  * fingerprint (AUDIT_CLASSIFIER=fingerprint, or VLM unreachable): regex
    text fingerprints mapped into the same contract.  Only knows the
    publications seen in packs to date; kept as a no-model fallback.

Whatever the classifier could not read (no kind, or a recruitment page
with no usable date) is surfaced as T5-050 YELLOW rather than silently
becoming a RED "missing evidence" (Kellen 9/10).
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta

from .rules import Flag, RED, YELLOW, _get, _d, filing_window

VLM_URL = os.environ.get(
    "AUDIT_VLM_URL", "http://localhost:1234/v1/chat/completions")
VLM_MODEL = os.environ.get("AUDIT_VLM_MODEL", "qwen/qwen3-vl-8b")
CLASSIFIER = os.environ.get("AUDIT_CLASSIFIER", "vlm")

GREEN = "GREEN"

STEP_CODES = ["job_fair", "employer_website", "job_search_website",
              "on_campus", "trade_org", "private_firm", "employee_referral",
              "campus_placement", "local_ethnic_newspaper", "radio_tv"]
DOC_KINDS = ["eta_9089", "eta_9141", "cover_letter", "posting_notice",
             "recruitment_report"]
HC_KINDS = ["swa_job_order", "sunday_ad"]
ALL_KINDS = DOC_KINDS + HC_KINDS + STEP_CODES + ["other"]

STEP_LABELS = {
    "swa_job_order": "SWA job order", "sunday_ad": "Sunday newspaper ad",
    "job_fair": "job fair", "employer_website": "employer's website",
    "job_search_website": "job search website", "on_campus": "on-campus recruiting",
    "trade_org": "trade or professional organization",
    "private_firm": "private employment firm",
    "employee_referral": "employee referral program",
    "campus_placement": "campus placement office",
    "local_ethnic_newspaper": "local or ethnic newspaper",
    "radio_tv": "radio or television ad",
    "posting_notice": "Notice of Filing (posting notice)",
    "recruitment_report": "recruitment report",
    "eta_9089": "filed ETA-9089", "eta_9141": "ETA-9141 PWD",
    "cover_letter": "cover letter",
}
# Ad-type kinds whose wage figures must match E.3 (T5-024) and that EPT
# laws reach (T5-025); RED for the web/job-order kinds, YELLOW for print/
# broadcast where OCR of a tear sheet is the likelier culprit.
AD_KINDS_WAGE_LEVEL = {
    "swa_job_order": RED, "employer_website": RED, "job_search_website": RED,
    "sunday_ad": YELLOW, "local_ethnic_newspaper": YELLOW, "radio_tv": YELLOW,
    "trade_org": YELLOW, "private_firm": YELLOW,
}


# ---------------------------------------------------------------- helpers

DATE_HDR_RX = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
ISO_DATE_RX = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
LONG_DATE_RX = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s*(\d{1,2}),?\s*(\d{4})", re.I)


def _d2(s):
    """Like rules._d but tolerant of 2-digit years (5/4/26 -> 2026)."""
    d = _d(s)
    if d and d.year < 100:
        d = d.replace(year=d.year + 2000)
    if d is None and s:
        for fmt in ("%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(s).strip(), fmt).date()
            except ValueError:
                continue
    return d


def _mdy(d):
    return f"{d.month}/{d.day}/{d.year}" if d else None


def _same_day(a, b):
    da, db = _d2(a), _d2(b)
    return da is not None and da == db


def _biz_days(a, b):
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


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
    """Dollar figures in a wage context within evidence text (keyword window
    keeps prices in surrounding newspaper content out)."""
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


def _all_dates(text, limit=4000):
    """Every date-looking token in the first `limit` chars, as M/D/YYYY."""
    t = (text or "")[:limit]
    out = []
    for m in DATE_HDR_RX.finditer(t):
        d = _d2(m.group(1))
        if d and _mdy(d) not in out:
            out.append(_mdy(d))
    for m in ISO_DATE_RX.finditer(t):
        d = _d2(m.group(0))
        if d and _mdy(d) not in out:
            out.append(_mdy(d))
    for m in LONG_DATE_RX.finditer(t):
        try:
            d = datetime.strptime(
                f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
        except ValueError:
            continue
        if _mdy(d) not in out:
            out.append(_mdy(d))
    return out


def _cid_decode(text):
    """Decode the shifted-by-16 subset font seen in some newspaper tear
    sheets: (cid:N) -> chr(N+16), literal chars -> chr(ord+16)."""
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


def _record(kind, page, text="", dates=None, publication=None,
            wage_figures=None, readable=None, reference_number=None,
            notes=""):
    dates = dates or []
    if readable is None:
        readable = bool(dates) or kind in DOC_KINDS
    return {"kind": kind, "page": page, "readable": readable, "dates": dates,
            "publication": publication,
            "wage_figures": wage_figures if wage_figures is not None
            else _wage_figures(text),
            "text": text, "reference_number": reference_number,
            "notes": notes}


def _rasterize_page(pdf_path, page_no, out_dir, dpi=150):
    prefix = os.path.join(out_dir, f"pg{page_no}")
    subprocess.run(
        ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", str(dpi),
         "-jpeg", "-jpegopt", "quality=75", pdf_path, prefix],
        check=True, capture_output=True)
    for name in sorted(os.listdir(out_dir)):
        if name.startswith(f"pg{page_no}") and name.endswith(".jpg"):
            return os.path.join(out_dir, name)
    raise RuntimeError("rasterization produced no output")


def _vlm(prompt, jpg_path=None, max_tokens=1500, timeout=600):
    """One local-VLM call; returns parsed JSON object or None."""
    import urllib.request
    content = [{"type": "text", "text": prompt}]
    if jpg_path:
        b64 = base64.b64encode(open(jpg_path, "rb").read()).decode()
        content.append({"type": "image_url", "image_url": {
            "url": f"data:image/jpeg;base64,{b64}"}})
    payload = {"model": VLM_MODEL, "temperature": 0,
               "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(
        VLM_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    raw = out["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- classify

def segment_pack(pdf_path):
    """Per-page text layer.  [{page, text}]"""
    import pdfplumber
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            pages.append({"page": i + 1, "text": page.extract_text() or ""})
    return pages


# --- fingerprint classifier (no model) -------------------------------------
# Only knows publications/sites seen in packs so far.  Extend the table as
# new ones show up; the VLM path is the general answer.
FINGERPRINTS = [
    ("cover_letter",        r"PERM Audit File|Audit File Index"),
    ("recruitment_report",  r"RECRUITMENT REPORT|Recruitment Checklist for PERM"),
    ("eta_9141",            r"Form ETA-?9141|ETA Form 9141"),
    ("eta_9089",            r"Form ETA-?9089|ETA Form 9089"),
    ("posting_notice",      r"NOTICE OF FILING|IMG_\d+\.(HEIC|JPG|JPEG)|Powered by Box"),
    ("swa_job_order",       r"Eightfold Career Hub|labor\.ny\.gov|WorkInTexas|"
                            r"CalJOBS|jobs\.state\.|Job Order (No|Number)"),
    ("sunday_ad",           r"THE NEW YORK TIMES|nytimes\.com/jobs|nylimes\.com|"
                            r"Dallas Morning News|Chicago Tribune|Los Angeles Times|"
                            r"Washington Post|Houston Chronicle"),
    ("job_search_website",  r"jobvertise\.com|indeed\.com|linkedin\.com/jobs|"
                            r"dice\.com|monster\.com|ziprecruiter"),
    ("local_ethnic_newspaper", r"www\.amNY\.com|amNY CLASSIFIED|Epoch Times|"
                            r"El Diario|World Journal|India Abroad"),
    ("radio_tv",            r"IHeart[Mm]edia|WLTW|Audacy|Cumulus|radio script|"
                            r"air(ed|ing)? on|broadcast confirmation"),
    ("employer_website",    r"careers\.|/careers/|Our Careers|Careers at"),
    ("employee_referral",   r"employee referral|referral program|referral bonus"),
]


def classify_page_fingerprint(text):
    for kind, rx in FINGERPRINTS:
        if re.search(rx, text, re.I):
            return kind
    return "other"


def _fingerprint_record(page):
    text = page["text"]
    kind = classify_page_fingerprint(text)
    dates = _all_dates(text)
    if kind == "sunday_ad" and not dates:
        dates = _all_dates(_cid_decode(text[:2000]))
    pub = None
    m = re.search(r"(THE NEW YORK TIMES|Dallas Morning News|Chicago Tribune|"
                  r"Los Angeles Times|Washington Post|Houston Chronicle|amNY|"
                  r"jobvertise|indeed|linkedin|dice|monster|ziprecruiter|"
                  r"iHeartMedia|WLTW|Eightfold|labor\.ny\.gov)", text, re.I)
    if m:
        pub = m.group(1)
    ref = None
    m = re.search(r"(?:Ref(?:erence)?\.?|Req(?:uisition)?\.?|Job)\s*(?:#|No\.?|Number|ID)?[:\s]*"
                  r"([A-Z]{0,4}-?\d{4,12})", text)
    if m:
        ref = m.group(1)
    return _record(kind, page["page"], text, dates, pub,
                   reference_number=ref, notes="fingerprint")


# --- VLM classifier ---------------------------------------------------------
PAGE_PROMPT = """You are reviewing one page of a PERM labor certification
audit file (recruitment evidence for an ETA-9089).  Classify the page and
extract facts.  Reply with ONLY a JSON object:

{"kind": one of %s,
 "publication": "newspaper / website / station / job bank name, or null",
 "dates": ["M/D/YYYY", ...],   // every date the page evidences (publication
                               // date, posting date, air date, printout date,
                               // date range endpoints)
 "wage_figures": [numbers],    // any salary/wage amounts stated for the job
 "reference_number": "job/requisition/reference number or null",
 "readable": true/false,       // false if the page is an image you cannot
                               // read well enough to trust the fields above
 "summary": "one line"}

kind guide: swa_job_order = state workforce agency job bank listing;
sunday_ad = Sunday newspaper tear sheet or newspaper ad proof;
job_search_website = Indeed/LinkedIn/Dice/etc. posting printout;
employer_website = the employer's own careers page; local_ethnic_newspaper =
non-Sunday local or ethnic newspaper ad; radio_tv = broadcast script/invoice/
confirmation; trade_org = professional journal or association posting;
private_firm = staffing/recruiter agreement or posting; employee_referral =
referral program notice; job_fair / on_campus / campus_placement = event
flyers, confirmations, sign-in sheets; posting_notice = Notice of Filing
posted at the worksite (often a photo, often handwritten dates);
recruitment_report = the employer's signed recruitment report or applicant
evaluations; eta_9089 / eta_9141 = the forms; cover_letter = index or
transmittal letter; other = anything else.  Use null for unknown fields.
Do not guess dates.""" % json.dumps(ALL_KINDS)


def _vlm_record(pdf_path, page, td):
    hint = page["text"][:1500]
    prompt = PAGE_PROMPT
    if hint.strip():
        prompt += "\n\nText layer of this page (may be partial):\n" + hint
    try:
        jpg = _rasterize_page(pdf_path, page["page"], td)
        js = _vlm(prompt, jpg)
    except Exception as e:  # VLM down / rasterize failure -> fingerprint
        rec = _fingerprint_record(page)
        rec["notes"] = f"vlm unavailable ({type(e).__name__}); fingerprint"
        return rec
    if not js or js.get("kind") not in ALL_KINDS:
        rec = _fingerprint_record(page)
        rec["notes"] = "vlm returned no usable classification; fingerprint"
        return rec
    dates = []
    for s in js.get("dates") or []:
        d = _d2(s)
        if d and _mdy(d) not in dates:
            dates.append(_mdy(d))
    figs = []
    for v in js.get("wage_figures") or []:
        n = _wage_num(v)
        if n and n not in figs:
            figs.append(n)
    figs = figs or _wage_figures(page["text"])
    readable = bool(js.get("readable", True))
    return _record(js["kind"], page["page"], page["text"], dates,
                   js.get("publication"), figs,
                   readable=readable and (bool(dates) or js["kind"] in DOC_KINDS),
                   reference_number=js.get("reference_number"),
                   notes=f"vlm: {js.get('summary') or ''}")


def classify_pack(pdf_path, pages, use_vlm=None):
    """[evidence record] for every page."""
    use_vlm = (CLASSIFIER == "vlm") if use_vlm is None else use_vlm
    if not use_vlm:
        return [_fingerprint_record(p) for p in pages]
    with tempfile.TemporaryDirectory() as td:
        return [_vlm_record(pdf_path, p, td) for p in pages]


# ---------------------------------------------------------------- facts

def extract_pack_facts(evidence):
    """Document-level facts from the evidence records: the pack's 9141 copy,
    cover-letter claims, recruitment-report statements."""
    f = {"evidence": evidence,
         "kinds_present": sorted({e["kind"] for e in evidence} - {"other"}),
         "pages_by_kind": {}}
    for e in evidence:
        f["pages_by_kind"].setdefault(e["kind"], []).append(e["page"])

    def _text(kind):
        return "\n".join(e["text"] for e in evidence if e["kind"] == kind)

    cov = _text("cover_letter")
    if cov:
        f["cover_letter"] = {
            "claims_filed_9089": bool(re.search(r"Filed ETA Form 9089|ETA[- ]9089", cov)),
        }

    p9141 = _text("eta_9141")
    if p9141:
        pwd = {}
        m = re.search(r"PWD? (?:Case|Tracking) Number:?\s*(P-100-\d{5}-\d{6})", p9141)
        pwd["pwd_case_number"] = m.group(1) if m else None
        m = re.search(r"Validity Period:?\s*(\d{1,2}/\d{1,2}/\d{4})\s*to\s*"
                      r"(\d{1,2}/\d{1,2}/\d{4})", p9141)
        if m:
            pwd["validity_from"], pwd["validity_to"] = m.group(1), m.group(2)
        m = re.search(r"SOC code:?\s*([\d-]{6,10})", p9141)
        pwd["soc_code"] = m.group(1) if m else None
        wages = re.findall(r"\$[\s\n]*([\d,]{4,})[\s\n]*\.", p9141)
        if len(wages) < 2:
            wages += re.findall(r"\$[\s\n]*([\d,]{4,})[\s\n]*\.", _cid_decode(p9141))
        wages = [int(w.replace(",", "")) for w in wages if int(w.replace(",", "")) > 10000]
        if wages:
            pwd["pw_primary"] = wages[0]
            pwd["pw_alternative"] = wages[1] if len(wages) > 1 else None
        pwd["readable"] = bool(pwd.get("pwd_case_number") or pwd.get("validity_to"))
        f["pwd_in_pack"] = pwd

    rr = _text("recruitment_report")
    if rr:
        m = re.search(r"notice of filing[^\d]{0,40}(\d{1,2}/\d{1,2}/\d{2,4})\s*"
                      r"(?:to|through|-|–)\s*(\d{1,2}/\d{1,2}/\d{2,4})", rr, re.I)
        f["recruitment_report"] = {
            "pages": f["pages_by_kind"].get("recruitment_report", []),
            "notice_posted": m.group(1) if m else None,
            "notice_removed": m.group(2) if m else None,
        }
    return f


NOTICE_PROMPT = """You are reading a photograph of a PERM Notice of Filing
physically posted at a worksite. Some fields are HANDWRITTEN. Reply with ONLY
a JSON object:
{"job_title": "...", "reference_number": "...", "salary_min": "...",
 "salary_max": "...", "date_posted": "M/D/YY", "date_removed": "M/D/YY",
 "posting_location": "...", "signer_name": "...", "signer_title": "...",
 "has_signature": true/false, "readable": true/false}
Use null for unreadable fields. Do not guess."""


def vlm_read_notice(pdf_path, page_no):
    with tempfile.TemporaryDirectory() as td:
        jpg = _rasterize_page(pdf_path, page_no, td, dpi=200)
        return _vlm(NOTICE_PROMPT, jpg, max_tokens=4000)


# ---------------------------------------------------------------- T5 rules

# Evidence that must exist in every audit file (RED if absent).  The
# recruitment report is a YELLOW (T5-040) per Kellen.
REQUIRED_EVIDENCE = ["eta_9089", "eta_9141", "posting_notice"]


def crosscheck(form, pack, notice=None, filing_date=None):
    """Cross-check evidence records against the 9089.  Returns [Flag]."""
    flags = []
    F = flags.append
    ev = pack.get("evidence", [])
    by_kind = {}
    for e in ev:
        by_kind.setdefault(e["kind"], []).append(e)
    present = set(by_kind) - {"other"}
    first_day, last_day = filing_window(form)

    # --- T5-050: pages the classifier could not read ----------------------
    # Fired once per unreadable page; the method-level checks below then
    # treat that page as "present but unverified" (YELLOW), never as a
    # missing-evidence RED.
    for e in ev:
        if e["kind"] == "other" and e.get("readable") is False:
            F(Flag(YELLOW, "T5-050", "audit-file",
                   f"Page {e['page']} could not be classified or read "
                   f"({e.get('notes') or 'no text, no model read'}) — review "
                   f"manually.", "data_check", "unreadable"))
        elif e["kind"] not in DOC_KINDS and e["kind"] != "other" and not e["readable"]:
            F(Flag(YELLOW, "T5-050", "audit-file",
                   f"Page {e['page']} looks like {STEP_LABELS.get(e['kind'], e['kind'])} "
                   f"evidence but no usable date could be read from it "
                   f"({e.get('notes') or ''}) — verify manually.",
                   "data_check", "unreadable"))

    # --- T5-001 required documents ---------------------------------------
    for kind in REQUIRED_EVIDENCE:
        if kind not in present:
            F(Flag(RED, "T5-001", "audit-file",
                   f"Audit file is missing: {STEP_LABELS[kind]}.",
                   "regulation", "20 CFR 656.10(f); 656.17(e)"))
    cov = pack.get("cover_letter") or {}
    if cov.get("claims_filed_9089") and "eta_9089" not in present:
        F(Flag(YELLOW, "T5-002", "audit-file",
               "Cover letter says the filed ETA-9089 is enclosed but no 9089 "
               "was found in the pack.", "data_check", "letter-vs-contents"))
    # T5-003 (retention-letter placeholder) retired 9/10.

    # --- T5-010/011/012 the PWD copy in the pack ---------------------------
    pwd = pack.get("pwd_in_pack") or {}
    form_pwd = _get(form, "E_job_wage.pwd_case_number")
    if "eta_9141" in present and pwd and not pwd.get("readable"):
        F(Flag(YELLOW, "T5-050", "E.1",
               "An ETA-9141 is in the pack but its case number and validity "
               "period could not be read — PWD checks (T5-010/011/012) "
               "skipped; verify manually.", "data_check", "unreadable"))
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
    vf, vt = _d2(pwd.get("validity_from")), _d2(pwd.get("validity_to"))
    rs = _d2(_get(form, "H_recruitment.swa_job_order_start"))
    if vf and vt and rs:
        if vf <= rs <= vt:
            F(Flag(GREEN, "T5-011", "PWD",
                   f"Recruitment began {_mdy(rs)} within PWD validity "
                   f"{_mdy(vf)}-{_mdy(vt)} (656.40(c) satisfied even if "
                   f"filing is after expiration).", "regulation", "20 CFR 656.40(c)"))
        elif first_day and vt < first_day:
            F(Flag(RED, "T5-011", "PWD",
                   f"PWD expired {_mdy(vt)}, before the first day to file "
                   f"({_mdy(first_day)}), and recruitment did not begin "
                   f"within the validity period.", "regulation", "20 CFR 656.40(c)"))
    offered = _wage_num(_get(form, "E_job_wage.offered_wage_from"))
    cands = [w for w in (pwd.get("pw_alternative"), pwd.get("pw_primary")) if w]
    governing = max(cands) if cands else None
    if offered and governing:
        which = "higher of the two PWD wages" if len(cands) == 2 else "prevailing wage"
        if offered < governing:
            F(Flag(RED, "T5-012", "E.3",
                   f"Offered wage {offered:,.0f} is below the {which} "
                   f"{governing:,.0f} from the PWD.", "regulation", "20 CFR 656.10(c)(1)"))
        else:
            F(Flag(GREEN, "T5-012", "E.3",
                   f"Offered wage {offered:,.0f} meets the {which} "
                   f"{governing:,.0f}.", "regulation", "verified"))

    # --- T5-020/021/022: every recruitment method the 9089 claims -------
    # One generic check per claimed method: no evidence of that kind -> RED;
    # evidence but unreadable -> already T5-050 (silent here); readable and
    # dates cover the 9089 dates -> GREEN; readable but dates don't -> YELLOW.
    def _method(rule, item, kind, want, label=None, cite="20 CFR 656.17(e)"):
        label = label or STEP_LABELS.get(kind, kind)
        want = list(dict.fromkeys(w for w in want if w))
        recs = by_kind.get(kind, [])
        if not recs:
            F(Flag(RED, rule, item,
                   f"9089 claims {label}"
                   + (f" ({', '.join(want)})" if want else "")
                   + f" but no evidence of it was found in the audit file.",
                   "regulation", cite))
            return
        readable = [r for r in recs if r["readable"]]
        if not readable:
            return  # T5-050 already covers it
        have = {d for r in readable for d in r["dates"]}
        hit = [w for w in want if any(_same_day(w, d) for d in have)]
        pubs = sorted({r["publication"] for r in readable if r.get("publication")})
        pub_note = f" [{', '.join(pubs)}]" if pubs else ""
        if want and len(hit) == len(want):
            F(Flag(GREEN, rule, item,
                   f"Evidence documents {label} on {', '.join(want)}{pub_note}.",
                   "data_check", "verified"))
        elif want:
            miss = [w for w in want if w not in hit]
            unread = [r["page"] for r in recs if not r["readable"]]
            F(Flag(YELLOW, rule, item,
                   f"{label} evidence found{pub_note} (pages "
                   f"{[r['page'] for r in readable]}, dates "
                   f"{sorted(have)}) but it does not document the 9089 "
                   f"date(s) {', '.join(miss)}."
                   + (f" Page(s) {unread} of the same kind could not be "
                      f"read and may cover it." if unread else ""),
                   "data_check", "cross-document"))
        else:
            F(Flag(YELLOW, rule, item,
                   f"{label} evidence found{pub_note} but the 9089 gives no "
                   f"date to check it against.", "data_check", "cross-document"))

    H = lambda k: _get(form, f"H_recruitment.{k}")
    if H("swa_job_order_start") or H("swa_job_order_end"):
        _method("T5-020", "H.c.1", "swa_job_order",
                [H("swa_job_order_start"), H("swa_job_order_end")],
                cite="20 CFR 656.17(e)(1)(i)(A)")
    for i, key in enumerate(["ad1_date", "ad2_date"], 1):
        if H(key):
            _method("T5-021", f"H.c.{i+1}b", "sunday_ad", [H(key)],
                    label=f"Sunday ad {i}", cite="20 CFR 656.17(e)(1)(i)(B)")
    steps = H("additional_steps") or {}
    if isinstance(steps, list):  # tolerate [{code, from, to}] shape
        steps = {s.get("code"): s for s in steps if isinstance(s, dict)}
    for code, span in steps.items():
        if code not in STEP_CODES:
            continue
        span = span or {}
        want = [span.get("from") or span.get("from_date"),
                span.get("to") or span.get("to_date")]
        _method("T5-022", "H.d", code, want, cite="20 CFR 656.17(e)(1)(ii)")
    # T5-023 (Jobvertise ref / radio salary) retired 9/10: no requisition
    # number or wage is required in those materials.


    # --- T5-024 wage stated in recruitment materials must MATCH E.3 -----
    ok_vals = set()
    for k in ("offered_wage_from", "offered_wage_to"):
        v = _wage_num(_get(form, f"E_job_wage.{k}"))
        if v:
            ok_vals.add(round(v, 2))
    per = _get(form, "E_job_wage.wage_per") or "Year"
    mult = {"Hour": 2080, "Week": 52, "Bi-Weekly": 26, "Month": 12, "Year": 1}.get(per, 1)
    ok_vals |= {round(v * mult, 2) for v in list(ok_vals)}
    if ok_vals:
        for kind, lvl in AD_KINDS_WAGE_LEVEL.items():
            for e in by_kind.get(kind, []):
                figs = e.get("wage_figures") or []
                if not figs:
                    continue
                item = "H.c" if kind in HC_KINDS else "H.d"
                label = STEP_LABELS[kind]
                if any(round(x, 2) in ok_vals for x in figs):
                    F(Flag(GREEN, "T5-024", item,
                           f"{label} (page {e['page']}) states a wage matching "
                           f"the 9089 offered wage.", "data_check", "verified"))
                else:
                    F(Flag(lvl, "T5-024", item,
                           f"{label} (page {e['page']}) states wage figure(s) "
                           f"{[f'{x:,.0f}' for x in figs]} that do not match "
                           f"the 9089 offered wage — recruitment materials "
                           f"must state the same wage as the 9089.",
                           "regulation", "20 CFR 656.17(f)(7)"))

    # --- T5-025 EPT wage-disclosure laws ----------------------------------
    from .ept import lookup_ept
    ept = lookup_ept(_get(form, "F_worksite.state"), _get(form, "F_worksite.city"))
    if ept:
        try:
            n_area = int(str(_get(form, "A_employer.num_employees_in_area")).replace(",", ""))
        except (TypeError, ValueError):
            n_area = None
        thresh_met = (ept["threshold_count"] == 0 or
                      (n_area is not None and n_area >= ept["threshold_count"]))
        basis = (f"threshold met (A.14 shows {n_area} employees in the area "
                 f"\u2265 {ept['threshold_count']})" if thresh_met else
                 f"could not confirm the {ept['threshold_count']}-employee "
                 f"threshold from A.14 alone \u2014 verify "
                 f"{ept['threshold_scope']}-level headcount")
        for kind in AD_KINDS_WAGE_LEVEL:
            for e in by_kind.get(kind, []):
                if not e["readable"] or e.get("wage_figures"):
                    continue
                ad = min((_d2(d) for d in e["dates"] if _d2(d)), default=None)
                if not ad or ad < ept["effective"]:
                    continue
                F(Flag(YELLOW, "T5-025", "H.c" if kind in HC_KINDS else "H.d",
                       f"{STEP_LABELS[kind]} (page {e['page']}, {_mdy(ad)}) "
                       f"states no wage, but {ept['state']} requires "
                       f"compensation disclosure in job postings "
                       f"({ept['citation']}, eff. {ept['effective']}); "
                       f"{basis}. {ept['note']}", "data_check", ept["citation"]))

    # --- T5-030/031/033/034 posting notice (VLM-read) -----------------------
    rr_meta = pack.get("recruitment_report") or {}
    if "posting_notice" in present and notice is None:
        F(Flag(YELLOW, "T5-050", "H.e",
               "A posting notice is in the pack but could not be read — "
               "notice checks (T5-030/031/033) skipped; verify manually.",
               "data_check", "unreadable"))
    if notice:
        dp, dr = _d2(notice.get("date_posted")), _d2(notice.get("date_removed"))
        if notice.get("readable") is False or not (dp and dr):
            F(Flag(YELLOW, "T5-050", "H.e",
                   "Posting notice was read but the posting/removal dates "
                   "were not legible (handwritten?) — verify manually.",
                   "data_check", "unreadable"))
        rp, rr_ = _d2(rr_meta.get("notice_posted")), _d2(rr_meta.get("notice_removed"))
        if dp and rp and (dp != rp or (dr and rr_ and dr != rr_)):
            F(Flag(YELLOW, "T5-034", "H.e",
                   f"Notice photo reads {_mdy(dp)}-{_mdy(dr)} but the "
                   f"recruitment report states {_mdy(rp)}-{_mdy(rr_)} — "
                   f"verify the handwritten dates.", "data_check", "cross-source"))
        elif dp and rp:
            F(Flag(GREEN, "T5-034", "H.e",
                   f"Handwritten notice dates corroborated by the recruitment "
                   f"report ({_mdy(rp)}-{_mdy(rr_)}).", "data_check", "verified"))
        if dp and dr:
            days = _biz_days(dp, dr)
            if days >= 10:
                F(Flag(GREEN, "T5-030", "H.e",
                       f"Notice posted {_mdy(dp)} to {_mdy(dr)}: {days} "
                       f"business days (>=10 required).",
                       "regulation", "20 CFR 656.10(d)(1)(ii)"))
            else:
                F(Flag(RED, "T5-030", "H.e",
                       f"Notice posted {_mdy(dp)} to {_mdy(dr)}: only {days} "
                       f"business days (<10).", "regulation", "20 CFR 656.10(d)(1)(ii)"))
        n_sal = _wage_num(notice.get("salary_min"))
        if n_sal and offered and n_sal != offered:
            F(Flag(RED, "T5-031", "H.e",
                   f"Notice salary ({n_sal:,.0f}) differs from 9089 offered "
                   f"wage ({offered:,.0f}).", "data_check", "cross-document"))
        elif n_sal and offered:
            F(Flag(GREEN, "T5-031", "H.e",
                   f"Notice salary matches 9089 offered wage ({offered:,.0f}).",
                   "data_check", "verified"))
        # T5-032 (signer vs Section B contact) retired 9/10: the NOF signer
        # need not be the 9089 point of contact.
        if notice.get("has_signature") is False:
            F(Flag(RED, "T5-033", "H.e",
                   "Posting notice does not appear to be signed.",
                   "data_check", "documentation"))

    # --- T5-040 recruitment report present? --------------------------------
    if "recruitment_report" not in present:
        F(Flag(YELLOW, "T5-040", "audit-file",
               "No recruitment report found in the audit file.",
               "regulation", "20 CFR 656.17(g)"))
    return flags


def verify_audit_pack(pack_pdf, form, filing_date=None, use_vlm=True):
    """Full Tier-5 run: segment -> classify -> facts -> notice -> crosscheck."""
    pages = segment_pack(pack_pdf)
    evidence = classify_pack(pack_pdf, pages, use_vlm=use_vlm)
    pack = extract_pack_facts(evidence)
    notice = None
    if use_vlm and pack["pages_by_kind"].get("posting_notice"):
        try:
            notice = vlm_read_notice(pack_pdf, pack["pages_by_kind"]["posting_notice"][0])
        except Exception:
            notice = None
    flags = crosscheck(form, pack, notice, filing_date)
    summary = {lvl: sum(1 for f in flags if f.level == lvl)
               for lvl in ("RED", "YELLOW", "GREEN")}
    slim = [{k: v for k, v in e.items() if k != "text"} for e in evidence]
    return {"pack_facts": {**pack, "evidence": slim}, "notice": notice,
            "flags": [f.to_dict() for f in flags], "summary": summary}
