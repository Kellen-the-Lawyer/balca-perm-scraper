"""Extract a FLAG-printed (flattened) ETA-9089 PDF into the canonical schema JSON.

Strategy (validated against certified fixture G-100-24345-530692):
  - Field VALUES render in Helvetica >= 11pt (except wage digits, ~9.6pt).
  - Labels/instructions render at 6-9pt.
  - Checked boxes are ZapfDingbats '4'; the answer token (Yes/No/N/A/option
    text) is the label word immediately to the right.
  - Unchecked boxes are Wingdings glyphs (\uf071, \uf0a8).

Output: dict roughly mirroring app/perm_verify/form_9089_schema.json paths.
"""
from __future__ import annotations
import re
import sys
import json
from collections import defaultdict

import pdfplumber

VALUE_MIN_SIZE = 11.0


def _lines(words, y_tol=3):
    """Group word dicts into lines by top coordinate."""
    rows = defaultdict(list)
    for w in words:
        placed = False
        for key in rows:
            if abs(key - w["top"]) <= y_tol:
                rows[key].append(w)
                placed = True
                break
        if not placed:
            rows[round(w["top"])].append(w)
    out = []
    for top in sorted(rows):
        ws = sorted(rows[top], key=lambda w: w["x0"])
        out.append({
            "top": top,
            "x0": ws[0]["x0"],
            "text": " ".join(w["text"] for w in ws),
            "words": ws,
        })
    return out


def _page_layers(page):
    """Return (label_lines, value_lines, checks) for a page.

    checks: list of {top, x0, answer} for CHECKED boxes only.
    """
    words = page.extract_words(extra_attrs=["size", "fontname"])
    labels, values = [], []
    for w in words:
        if "Wingdings" in w["fontname"] or "Zapf" in w["fontname"]:
            continue
        if w["size"] >= VALUE_MIN_SIZE and "Helvetica" in w["fontname"]:
            values.append(w)
        else:
            labels.append(w)

    checks = []
    for c in page.chars:
        checked = "Zapf" in c["fontname"]
        if not checked:
            continue
        right = [
            w for w in labels
            if abs(w["top"] - c["top"]) < 5 and c["x0"] < w["x0"] < c["x0"] + 90
        ]
        right.sort(key=lambda w: w["x0"])
        answer = None
        if right:
            answer = right[0]["text"]
            # extend two-token answers ("I", "ACCEPT")
            if answer == "I" and len(right) > 1:
                answer = "I " + right[1]["text"]
        checks.append({"top": round(c["top"]), "x0": round(c["x0"]), "answer": answer})
    return _lines(labels), _lines(values), checks


SUBLABEL_RX = re.compile(r"^\d{1,2}[a-z]?\.$")


def _cells(line):
    """Split a merged label line into cells at numbered sub-label boundaries."""
    cells, cur = [], []
    for w in line["words"]:
        if SUBLABEL_RX.match(w["text"]) and cur:
            cells.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        cells.append(cur)
    out = []
    for k, ws in enumerate(cells):
        out.append({
            "top": line["top"],
            "x0": ws[0]["x0"],
            "x_max": cells[k + 1][0]["x0"] - 10 if k + 1 < len(cells) else None,
            "text": " ".join(w["text"] for w in ws),
        })
    return out


def _find_anchor(label_lines, pattern):
    """Find anchor cell; ^ in pattern means cell start, not line start."""
    rx = re.compile(pattern)
    for ln in label_lines:
        for cell in _cells(ln):
            if rx.search(cell["text"]):
                return cell
    return None


def _value_below(value_lines, anchor, max_dy=30, x_min=None, x_max=None, join=False):
    """Value line(s) whose top is within (anchor.top, anchor.top+max_dy]."""
    hits = []
    for vl in value_lines:
        if anchor["top"] < vl["top"] <= anchor["top"] + max_dy:
            ws = vl["words"]
            if x_min is not None or x_max is not None:
                lo = x_min if x_min is not None else -1e9
                hi = x_max if x_max is not None else 1e9
                ws = [w for w in ws if lo <= w["x0"] < hi]
            if ws:
                hits.append(" ".join(w["text"] for w in ws))
    if not hits:
        return None
    return " ".join(hits) if join else hits[0]


def _check_answer(checks, anchor, band_end):
    """Checked answer within the vertical band [anchor.top-6, band_end)."""
    for c in sorted(checks, key=lambda c: c["top"]):
        if anchor["top"] - 6 <= c["top"] < band_end:
            return c["answer"]
    return None


def _norm(v):
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def _value_same_row(value_lines, anchor, x_min=None, x_max=None):
    for vl in value_lines:
        if abs(vl["top"] - anchor["top"]) <= 8:
            ws = vl["words"]
            if x_min is not None:
                ws = [w for w in ws if w["x0"] >= x_min]
            if x_max is not None:
                ws = [w for w in ws if w["x0"] < x_max]
            if ws:
                return " ".join(w["text"] for w in ws)
    return None


def _next_anchor_top(label_lines, anchor, patterns):
    tops = []
    for p in patterns:
        rx = re.compile(p)
        for ln in label_lines:
            if ln["top"] > anchor["top"] and rx.search(ln["text"]):
                tops.append(ln["top"])
                break
    return min(tops) if tops else anchor["top"] + 40


# --- Declarative field maps -------------------------------------------------
# (path, anchor_regex, kind) kind: text | text_right | text_join | check | wage_row
SEC_A = [
    ("A_employer.legal_business_name", r"^1\.\s*Legal Business Name", "text"),
    ("A_employer.dba", r"^2\.\s*Trade Name", "text"),
    ("A_employer.address1", r"^3\.\s*Address 1", "text"),
    ("A_employer.address2", r"^4\.\s*Address 2", "text"),
    ("A_employer.city", r"^5\.\s*City", "text"),
    ("A_employer.state", r"^6\.\s*State", "text"),
    ("A_employer.postal_code", r"^7\.\s*Postal Code", "text"),
    ("A_employer.country", r"^8\.\s*Country", "text"),
    ("A_employer.province", r"9\.\s*Province", "text"),
    ("A_employer.phone", r"^10\.\s*Telephone", "text"),
    ("A_employer.extension", r"11\.\s*Extension", "text"),
    ("A_employer.fein", r"^12\.\s*Federal Employer", "text"),
    ("A_employer.naics_code", r"13\.\s*NAICS", "text"),
    ("A_employer.num_employees_in_area", r"^14\.\s*Number of current", "text"),
    ("A_employer.year_commenced_business", r"15\.\s*Year Commenced", "text"),
    ("A_employer.closely_held_ownership_interest", r"^16\.\s*Is the employer a closely held", "check"),
    ("A_employer.familial_relationship", r"^17\.\s*Is there a familial", "check"),
]
SEC_B = [
    ("B_poc.last_name", r"^1\.\s*Contact.s Last", "text"),
    ("B_poc.first_name", r"^2\.\s*First \(given\) Name", "text"),
    ("B_poc.middle_name", r"^3\.\s*Middle Name", "text"),
    ("B_poc.job_title", r"^4\.\s*Contact.s Job Title", "text"),
    ("B_poc.address1", r"^5\.\s*Address 1", "text"),
    ("B_poc.address2", r"^6\.\s*Address 2", "text"),
    ("B_poc.city", r"^7\.\s*City", "text"),
    ("B_poc.state", r"^8\.\s*State", "text"),
    ("B_poc.postal_code", r"^9\.\s*Postal Code", "text"),
    ("B_poc.country", r"^10\.\s*Country", "text"),
    ("B_poc.province", r"^11\.\s*Province", "text"),
    ("B_poc.phone", r"^12\.\s*Telephone", "text"),
    ("B_poc.extension", r"^13\.\s*Extension", "text"),
    ("B_poc.email", r"^14\.\s*Business Email", "text"),
]
SEC_C = [
    ("C_attorney_agent.representation_type", r"^1\.\s*Indicate the type of representation", "check"),
    ("C_attorney_agent.last_name", r"^2\.\s*Attorney or Agent.s Last", "text"),
    ("C_attorney_agent.first_name", r"^3\.\s*First \(given\) Name", "text"),
    ("C_attorney_agent.middle_name", r"^4\.\s*Middle Name", "text"),
    ("C_attorney_agent.address1", r"^5\.\s*Address 1", "text"),
    ("C_attorney_agent.address2", r"^6\.\s*Address 2", "text"),
    ("C_attorney_agent.city", r"^7\.\s*City", "text"),
    ("C_attorney_agent.state", r"^8\.\s*State", "text"),
    ("C_attorney_agent.postal_code", r"^9\.\s*Postal Code", "text"),
    ("C_attorney_agent.country", r"^10\.\s*Country", "text"),
    ("C_attorney_agent.province", r"^11\.\s*Province", "text"),
    ("C_attorney_agent.phone", r"^12\.\s*Telephone", "text"),
    ("C_attorney_agent.extension", r"^13\.\s*Extension", "text"),
    ("C_attorney_agent.email", r"^14\.\s*Law Firm/Business Email", "text"),
    ("C_attorney_agent.law_firm_name", r"^15\.\s*Law Firm/Business Name", "text"),
    ("C_attorney_agent.law_firm_fein", r"^16\.\s*Law Firm/Business FEIN", "text"),
    ("C_attorney_agent.state_bar_number", r"^17\.\s*State Bar Number", "text"),
    ("C_attorney_agent.state_of_good_standing", r"^18\.\s*State of highest court", "text"),
    ("C_attorney_agent.highest_court_name", r"^19\.\s*Name of the highest state court", "text"),
]
SEC_D = [
    ("D_foreign_worker_flags.appendix_a_attached", r"^1\.\s*A completed Appendix A", "check"),
    ("D_foreign_worker_flags.dual_representation", r"^2\.\s*Has the employer contracted", "check"),
]
SEC_E = [
    ("E_job_wage.pwd_case_number", r"^1\.\s*Enter the valid Prevailing Wage", "text_right"),
    ("E_job_wage.supervised_recruitment_9141_attached", r"^2\.\s*If a valid PWD has not", "check"),
    ("E_job_wage.offered_wage_raw", r"^3\.\s*Offered Wage", "wage_row"),
    ("E_job_wage.wage_per", r"^4\.\s*Per\b", "check"),
    ("E_job_wage.wage_conditions", r"^5\.\s*Additional conditions", "text_join"),
]
SEC_F = [
    ("F_worksite.worksite_type", r"^1\.\s*Type of worksite location", "check"),
    ("F_worksite.address1", r"^2\.\s*Worksite Address \*", "text"),
    ("F_worksite.address2", r"^3\.\s*Worksite Address", "text"),
    ("F_worksite.city", r"^4\.\s*City", "text"),
    ("F_worksite.county", r"^5\.\s*County", "text"),
    ("F_worksite.state", r"^6\.\s*State/District/Territory", "text"),
    ("F_worksite.postal_code", r"^7\.\s*Postal Code", "text"),
    ("F_worksite.msa_oes_area_code", r"^8\.\s*MSA/OES Area Code", "text"),
    ("F_worksite.msa_oes_area_title", r"^8a\.\s*MSA Name/OES Area Title", "text"),
    ("F_worksite.additional_worksites", r"^1\.\s*Will work be performed in geographic", "check"),
    ("F_worksite.appendix_b_attached", r"^2\.\s*If .Yes. is marked in question F\.b\.1", "check"),
    ("F_worksite.other_geographic_areas", r"^1\.\s*Identify the geographic area", "text_join"),
]
SEC_G = [
    ("G_job_info.full_time_35hrs", r"^1\.\s*Is this a permanent position", "check"),
    ("G_job_info.live_in_domestic", r"^2\.\s*Is the employer seeking permanent", "check"),
    ("G_job_info.live_in_1yr_experience", r"^2a\.", "check"),
    ("G_job_info.live_in_contract_executed", r"^2b\.", "check"),
    ("G_job_info.live_in_contract_copy_provided", r"^2c\.", "check"),
    ("G_job_info.accept_foreign_degree_equivalent", r"^3\.\s*Will the employer accept a foreign", "check"),
    ("G_job_info.fw_currently_employed", r"^4\.\s*Is the foreign worker currently", "check"),
    ("G_job_info.fw_qualifies_only_by_alternative_reqs", r"^4a\.", "check"),
    ("G_job_info.kellogg_suitable_combination", r"^4b\.", "check"),
    ("G_job_info.relying_solely_on_experience_with_employer", r"^5\.\s*Is the employer relying solely", "check"),
    ("G_job_info.experience_substantially_comparable", r"^5a\.", "check"),
    ("G_job_info.employer_paid_training", r"^5b\.", "check"),
    ("G_job_info.live_on_premises", r"^6\.\s*Does the job opportunity require", "check"),
    ("G_job_info.combination_of_occupations", r"^7\.\s*Does the job opportunity identified", "check"),
    ("G_job_info.foreign_language", r"^8\.\s*Is proficiency in a foreign language", "check"),
    ("G_job_info.exceeds_svp", r"^9\.\s*Do the job requirements", "check"),
    ("G_job_info.credentialing_service", r"^10\.\s*Did the employer use a credenti", "check"),
    ("G_job_info.employer_received_payment", r"^11\.\s*Has the employer received payment", "check"),
    ("G_job_info.layoff_6mo", r"^12\.\s*Has the employer had a layoff", "check"),
]

SEC_H_STEPS = [
    ("job_fair", r"Job fair"),
    ("employer_website", r"Employer website"),
    ("job_search_website", r"Job search website"),
    ("on_campus", r"On-campus recruiting"),
    ("trade_org", r"Trade or professional organization"),
    ("private_firm", r"Private employment firm"),
    ("employee_referral", r"Employee referral program"),
    ("campus_placement", r"Campus placement office"),
    ("local_ethnic_newspaper", r"Local or ethnic newspaper"),
    ("radio_tv", r"Radio and/or TV"),
]


def _set(out, path, value):
    parts = path.split(".")
    d = out
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = _norm(value) if isinstance(value, str) else value


def _run_map(fmap, labels, values, checks, out, page_no=None):
    anchors = [a for _, a, _ in fmap]
    fields = out.setdefault("_layout", {}).setdefault("fields", {})
    for path, pat, kind in fmap:
        a = _find_anchor(labels, pat)
        if a is None:
            continue
        if page_no is not None:
            fields[path] = {"page": page_no, "x": a["x0"], "y": a["top"]}
        if kind == "text":
            _set(out, path, _value_below(values, a, x_min=a["x0"] - 8,
                                         x_max=a.get("x_max")))
        elif kind == "text_right":
            _set(out, path, _value_same_row(values, a) or _value_below(values, a))
        elif kind == "text_join":
            _set(out, path, _value_below(values, a, max_dy=600, join=True))
        elif kind == "check":
            band_end = _next_anchor_top(labels, a, anchors)
            _set(out, path, _check_answer(checks, a, band_end))
        elif kind == "wage_row":
            hi = a.get("x_max") or 1e9
            toks_from, toks_to = [], []
            for ln in labels:
                if a["top"] < ln["top"] <= a["top"] + 40:
                    for w in ln["words"]:
                        if "Helvetica" in w["fontname"] and re.match(r"^[\d,.]+$", w["text"]):
                            (toks_from if w["x0"] < hi else toks_to).append(w["text"])
            _set(out, path, {"from": " ".join(toks_from) or None,
                             "to": " ".join(toks_to) or None})


def _extract_section_h(labels, values, checks, out, page_no=None):
    h = out.setdefault("H_recruitment", {})
    fields = out.setdefault("_layout", {}).setdefault("fields", {})

    def _mark(path, a):
        if a is not None and page_no is not None:
            fields[path] = {"page": page_no, "x": a["x0"], "y": a["top"]}
    a = _find_anchor(labels, r"^1\.\s*Is the employer required, by notice")
    if a:
        _mark("H_recruitment.supervised_recruitment", a)
        h["supervised_recruitment"] = _check_answer(checks, a, a["top"] + 26)
    # occupation type: which of 1a-1e is checked
    occ_anchor = _find_anchor(labels, r"Mark ONE appropriate box")
    if occ_anchor:
        band_end = occ_anchor["top"] + 230
        mark = None
        for c in sorted(checks, key=lambda c: c["top"]):
            if occ_anchor["top"] < c["top"] < band_end and c["x0"] < 120:
                mark = c
                break
        if mark:
            for code, pat in [("1a_professional", r"professional occupation"),
                              ("1b_nonprofessional", r"non-professional occupation"),
                              ("1c_college_university_teacher", r"college or university teacher"),
                              ("1d_schedule_a_sheepherder", r"Schedule A or sheepherder"),
                              ("1e_professional_athlete", r"professional athlete")]:
                ln = _find_anchor(labels, pat)
                if ln and abs(ln["top"] - mark["top"]) < 12:
                    h["occupation_type"] = code
                    break
    for path, pat in [("swa_job_order_start", r"^1a\.\s*Start date of SWA"),
                      ("swa_job_order_end", r"^1b\.\s*End date of SWA"),
                      ("ad1_date", r"^2b\.\s*Advertisement date"),
                      ("ad2_date", r"^3b\.\s*Advertisement Date")]:
        a = _find_anchor(labels, pat)
        if a:
            _mark(f"H_recruitment.{path}", a)
            h[path] = _norm(_value_same_row(values, a, x_min=a["x0"], x_max=a.get("x_max")) or
                            _value_below(values, a, max_dy=20, x_min=a["x0"] - 8,
                                         x_max=a.get("x_max")))
    for path, pat in [("ad1_newspaper_name", r"^2a\.\s*Name of newspaper of general"),
                      ("ad2_name", r"^3a\.\s*Name of newspaper or professional")]:
        a = _find_anchor(labels, pat)
        if a:
            h[path] = _norm(_value_below(values, a, max_dy=20, x_max=a.get("x_max")))
    a = _find_anchor(labels, r"^2\.\s*Is there a Sunday edition")
    if a:
        h["sunday_edition_exists"] = _check_answer(checks, a, a["top"] + 26)
    a = _find_anchor(labels, r"^3\.\s*Which of the following did the employer")
    if a:
        h["ad2_type"] = _check_answer(checks, a, a["top"] + 30)
    # additional steps table: From/To values share the row with the step label
    steps = h.setdefault("additional_steps", {})
    for code, pat in SEC_H_STEPS:
        a = _find_anchor(labels, pat)
        if a is None:
            continue
        _mark(f"H_recruitment.additional_steps.{code}", a)
        row = _value_same_row(values, a, x_min=a["x0"])
        if row:
            toks = row.split()
            steps[code] = {"from": toks[0] if toks else None,
                           "to": toks[1] if len(toks) > 1 else None}
    # notice of posting: checked options in section e
    a = _find_anchor(labels, r"Notice of Posting")
    if a:
        _mark("H_recruitment.notice_of_posting", a)
        posted = []
        for code, pat in [("1a_bargaining_rep", r"^1a\.\s*Bargaining Representative"),
                          ("1b_physical_notice", r"Physical Notice"),
                          ("1c_electronic_notice", r"Electronic Notice"),
                          ("1d_inhouse_media", r"In-House Media"),
                          ("1e_private_household", r"Private Household"),
                          ("1f_did_not_post", r"DID NOT post the notice")]:
            ln = _find_anchor(labels, pat)
            if ln is None:
                continue
            for c in checks:
                if -8 <= c["top"] - ln["top"] < 45 and c["x0"] < 120:
                    posted.append(code)
                    break
        h["notice_of_posting"] = posted
    a = _find_anchor(labels, r"^1\.\s*I certify under penalty of perjury")
    if a:
        _mark("I_attestations.certify_labor_condition_statements", a)
        out.setdefault("I_attestations", {})["certify_labor_condition_statements"] = \
            _check_answer(checks, a, a["top"] + 45)

SEC_J = [
    ("J_preparer.last_name", r"^1\.\s*Last \(family\) Name", "text"),
    ("J_preparer.first_name", r"^2\.\s*First \(given\) Name", "text"),
    ("J_preparer.middle_name", r"^3\.\s*Middle Name", "text"),
    ("J_preparer.fein", r"^4\.\s*Law Firm/Business FEIN", "text"),
    ("J_preparer.business_name", r"^5\.\s*Law Firm/Business Name", "text"),
    ("J_preparer.email", r"^6\.\s*Law Firm/Business Email", "text"),
]
APP_A_CONTACT = [
    ("appendix_A.contact.last_name", r"^1\.\s*Foreign Worker.s Last", "text"),
    ("appendix_A.contact.first_name", r"^2\.\s*Foreign Worker.s First", "text"),
    ("appendix_A.contact.middle_name", r"^3\.\s*Foreign Worker.s Middle", "text"),
    ("appendix_A.contact.address1", r"^4\.\s*Address 1", "text"),
    ("appendix_A.contact.address2", r"^5\.\s*Address 2", "text"),
    ("appendix_A.contact.city", r"^6\.\s*City", "text"),
    ("appendix_A.contact.state", r"^7\.\s*State", "text"),
    ("appendix_A.contact.postal_code", r"^8\.\s*Postal Code", "text"),
    ("appendix_A.contact.country", r"^9\.\s*Country", "text"),
    ("appendix_A.contact.province", r"^10\.\s*Province", "text"),
    ("appendix_A.contact.dob", r"^11\.\s*Date of Birth", "text"),
    ("appendix_A.contact.class_of_admission", r"^12\.\s*Class of Admission", "text"),
    ("appendix_A.contact.a_number", r"^13\.\s*Alien Registration", "text"),
    ("appendix_A.contact.country_of_birth", r"^14\.\s*Country of Birth", "text"),
    ("appendix_A.contact.country_of_citizenship", r"^15\.\s*Country of Citizenship", "text"),
]
DEGREES = ["None", "High School/GED", "Associate", "Bachelor's", "Master's",
           "Doctorate", "Other Degree"]


def _extract_app_a_blocks(labels, values, checks, out):
    app = out.setdefault("appendix_A", {})
    # Education sets: anchor "Educational Attainment Information N"
    edus = app.setdefault("education", [])
    for ln in labels:
        m = re.search(r"Educational Attainment Information (\d)", ln["text"])
        if not m:
            continue
        band_end = _next_anchor_top(
            labels, ln, [r"Educational Attainment Information " + str(int(m.group(1)) + 1),
                         r"Foreign Worker Training Qualifications"])
        entry = {"set": int(m.group(1))}
        # degree checkbox row (checked mark near "Education:" row)
        deg = None
        for c in checks:
            if ln["top"] < c["top"] < ln["top"] + 40:
                deg = c["answer"]
                break
        if deg:
            for d in DEGREES:
                if deg and d.split("/")[0].rstrip("'s") in deg:
                    entry["degree"] = d
                    break
            entry.setdefault("degree", deg)
        for key, pat in [("majors", r"1b\.\s*Specify major"),
                         ("institution", r"1c\.\s*Name of Institution"),
                         ("country", r"1d\.\s*Name of Country"),
                         ("month_year_attained", r"1e\.\s*Month/year attained")]:
            band = [l for l in labels if ln["top"] <= l["top"] < band_end]
            a = _find_anchor(band, pat)
            if a:
                entry[key] = _norm(_value_below(values, a, max_dy=22,
                                                x_min=a["x0"] - 8, x_max=a.get("x_max")))
        if entry.get("degree") or entry.get("institution"):
            edus.append(entry)
    # Skills sets
    skills = app.setdefault("skills", [])
    for ln in labels:
        m = re.search(r"Skills, Abilities, and Proficiencies (\d)", ln["text"])
        if not m or "Foreign Worker" in ln["text"]:
            continue
        band_end = ln["top"] + 90
        entry = {"set": int(m.group(1))}
        a = next((l for l in labels if ln["top"] <= l["top"] < band_end
                  and re.search(r"1\.\s*Name of Employer/Institution", l["text"])), None)
        if a:
            entry["provider"] = _norm(_value_below(values, a, max_dy=22))
        d = next((l for l in labels if ln["top"] <= l["top"] < ln["top"] + 130
                  and re.search(r"1c\.\s*Description of specific skills", l["text"])), None)
        if d:
            entry["description"] = _norm(_value_below(values, d, max_dy=600, join=True))
        if entry.get("provider"):
            skills.append(entry)
    # Work experience blocks
    wes = app.setdefault("work_experience", [])
    for ln in labels:
        m = re.search(r"Work Experience (\d)", ln["text"])
        if not m:
            continue
        band_end = ln["top"] + 320
        entry = {"set": int(m.group(1))}
        band = [l for l in labels if ln["top"] <= l["top"] < band_end]
        for key, pat, dy in [("employer_name", r"^1\.\s*Employer Name", 22),
                             ("job_title", r"^1g\.\s*Job Title", 22),
                             ("city", r"^1c\.\s*City or Town", 22)]:
            a = _find_anchor(band, pat)
            if a:
                entry[key] = _norm(_value_below(values, a, max_dy=dy,
                                                x_min=a["x0"] - 8, x_max=a.get("x_max")))
        for key, pat in [("start", r"^1h\.\s*Start Date"), ("end", r"^1i\.\s*End Date"),
                         ("hours_per_week", r"^1k\.\s*Hours Worked")]:
            a = _find_anchor(band, pat)
            if a:
                entry[key] = _norm(_value_below(values, a, max_dy=22,
                                                x_min=a["x0"] - 8, x_max=a.get("x_max")))
        a = _find_anchor(band, r"^1j\.\s*Present")
        if a:
            entry["present"] = _check_answer(
                [c for c in checks if abs(c["x0"] - a["x0"]) < 60], a, a["top"] + 35)
        d = next((l for l in labels if ln["top"] <= l["top"] < ln["top"] + 400
                  and re.search(r"1l\.\s*Job Duties", l["text"])), None)  # duties full-width
        if d:
            entry["duties"] = _norm(_value_below(values, d, max_dy=700, join=True))
        if entry.get("employer_name"):
            wes.append(entry)


def _extract_appendix_c(labels, values, checks, out):
    app = out.setdefault("appendix_C", {})
    entries = app.setdefault("entries", [])
    for ln in labels:
        m = re.search(r"Supplemental Information (\d) ", ln["text"] + " ")
        if not m or "Section Name" in ln["text"]:
            continue
        band_end = _next_anchor_top(
            labels, ln, [r"Supplemental Information " + str(int(m.group(1)) + 1) + r"\b",
                         r"For Public Burden Statement"])
        band = [l for l in labels if ln["top"] <= l["top"] < band_end]
        entry = {"set": int(m.group(1))}
        a = _find_anchor(band, r"^1\.\s*Section and")
        if a:
            entry["section_item"] = _norm(
                _value_same_row(values, a, x_min=a["x0"]) or
                _value_below(values, a, max_dy=25, x_min=a["x0"] - 8, x_max=a["x0"] + 200))
        c = _find_anchor(band, r"^1a\.\s*Section Name or Category")
        if c:
            entry["category"] = _norm(
                _value_same_row(values, c, x_min=c["x0"]) or
                _value_below(values, c, max_dy=25, x_min=c["x0"] - 8))
        d = _find_anchor(band, r"^1b\.\s*Supplemental Information")
        if d:
            entry["explanation"] = _norm(_value_below(
                values, d, max_dy=band_end - d["top"], join=True))
        if entry.get("section_item") or entry.get("explanation"):
            # normalize section_item like "G.9" out of any extra tokens
            si = entry.get("section_item") or ""
            mm = re.search(r"G\.\d{1,2}", si)
            if mm:
                entry["section_item"] = mm.group(0)
            entries.append(entry)


SECTION_DISPATCH = [
    (r"A\.\s*Employer Information", SEC_A),
    (r"B\.\s*Employer Point of Contact", SEC_B),
    (r"C\.\s*Attorney or Agent Information", SEC_C),
    (r"D\.\s*Foreign Worker Information", SEC_D),
    (r"E\.\s*Job Opportunity and Wage", SEC_E),
    (r"F\.\s*Area of Intended Employment", SEC_F),
    (r"G\.\s*Additional Job Opportunity", SEC_G),
    (r"J\.\s*Preparer", SEC_J),
    (r"FOREIGN WORKER INFORMATION", APP_A_CONTACT),
]


def extract(pdf_path):
    out = {"meta": {"source_pdf": str(pdf_path)}}
    out["_layout"] = {"pages": [], "fields": {}}
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages):
            out["_layout"]["pages"].append(
                {"w": float(page.width), "h": float(page.height)})
            labels, values, checks = _page_layers(page)
            page_text = " ".join(l["text"] for l in labels)
            if "meta" in out and "perm_case_number" not in out["meta"]:
                for vl in list(values) + list(labels):
                    mm = re.search(r"(G-\d{3}-\d{5}-\d{6})", vl["text"])
                    if mm:
                        out["meta"]["perm_case_number"] = mm.group(1)
                        break
                mm = re.search(r"Case Status:\s*(\w+)", page_text)
                if mm:
                    out["meta"]["case_status"] = mm.group(1)
                mm = re.search(r"Determination Date:\s*([\d/]+)", page_text)
                if mm:
                    out["meta"]["determination_date"] = mm.group(1)
            for header_pat, fmap in SECTION_DISPATCH:
                if re.search(header_pat, page_text):
                    _run_map(fmap, labels, values, checks, out, page_no=page_no)
            if re.search(r"H\.\s*Recruitment Information|Notice of Posting|Radio and/or TV", page_text):
                _extract_section_h(labels, values, checks, out, page_no=page_no)
            if re.search(r"Educational Attainment|Work Experience \d|Skills, Abilities", page_text):
                for ln in labels:
                    mm = re.search(r"(Educational Attainment Information 1|Work Experience 1)\b", ln["text"])
                    if mm:
                        key = ("appendix_A.education" if "Educational" in mm.group(1)
                               else "appendix_A.work_experience")
                        out["_layout"]["fields"].setdefault(
                            key, {"page": page_no, "x": ln["x0"], "y": ln["top"]})
                _extract_app_a_blocks(labels, values, checks, out)
            if "SUPPLEMENTAL INFORMATION" in page_text:
                _extract_appendix_c(labels, values, checks, out)
    # post-process wage
    e = out.get("E_job_wage", {})
    raw = e.get("offered_wage_raw") or {}

    def _money(s):
        if not s:
            return None
        s = s.replace(",", "").replace("$", "").strip()
        s = re.sub(r"\s*\.\s*", ".", s)
        toks = s.split()
        if len(toks) == 2 and "." not in s and len(toks[1]) <= 2:
            s = toks[0] + "." + toks[1]          # "121500 08" -> 121500.08
        else:
            s = "".join(toks)
        try:
            return float(s)
        except ValueError:
            return None

    if isinstance(raw, dict):
        e["offered_wage_from"] = _money(raw.get("from"))
        e["offered_wage_to"] = _money(raw.get("to"))
    return out


if __name__ == "__main__":
    print(json.dumps(extract(sys.argv[1]), indent=2))
