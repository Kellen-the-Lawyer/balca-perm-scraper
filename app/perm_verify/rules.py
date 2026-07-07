"""PERM verification rules engine — Tier 1 (completeness/consistency),
Tier 2 (regulatory timing), and Tier 4 form-only audit-risk checks over an
extracted ETA-9089 dict.

Flag levels: RED = will/likely will be denied as filed.
             YELLOW = grey area, audit trigger, or documentation risk.

See RULES_INVENTORY.md for the rule catalog and citations.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

RED = "RED"
YELLOW = "YELLOW"

MANDATORY_STEP_KEYS = ("swa_job_order", "ad1", "ad2")
PROFESSIONAL_MIN_ADDITIONAL_STEPS = 3


@dataclass
class Flag:
    level: str
    rule_id: str
    section_item: str
    message: str
    citation_type: str   # typo|completeness|regulation|form_instructions|balca|faq|data_check
    citation: str

    def to_dict(self):
        return asdict(self)


def _get(form, path, default=None):
    d = form
    for p in path.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return d if d is not None else default


def _d(s):
    """Parse M/D/YYYY or MM/YYYY; None on failure/N/A."""
    if not s or str(s).strip().upper() in ("N/A", "NA", ""):
        return None
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _is_na(v):
    return v is None or str(v).strip().upper() in ("N/A", "NA", "")


# ---------------------------------------------------------------------------
# Tier 1 — completeness & internal consistency
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    ("A.1", "A_employer.legal_business_name"),
    ("A.3", "A_employer.address1"),
    ("A.5", "A_employer.city"),
    ("A.6", "A_employer.state"),
    ("A.7", "A_employer.postal_code"),
    ("A.8", "A_employer.country"),
    ("A.10", "A_employer.phone"),
    ("A.12", "A_employer.fein"),
    ("A.13", "A_employer.naics_code"),
    ("A.14", "A_employer.num_employees_in_area"),
    ("A.15", "A_employer.year_commenced_business"),
    ("A.16", "A_employer.closely_held_ownership_interest"),
    ("A.17", "A_employer.familial_relationship"),
    ("B.1", "B_poc.last_name"),
    ("B.2", "B_poc.first_name"),
    ("B.4", "B_poc.job_title"),
    ("B.14", "B_poc.email"),
    ("D.1", "D_foreign_worker_flags.appendix_a_attached"),
    ("D.2", "D_foreign_worker_flags.dual_representation"),
    ("E.1", "E_job_wage.pwd_case_number"),
    ("E.3", "E_job_wage.offered_wage_from"),
    ("E.4", "E_job_wage.wage_per"),
    ("F.a.2", "F_worksite.address1"),
    ("F.a.4", "F_worksite.city"),
    ("F.a.5", "F_worksite.county"),
    ("F.a.6", "F_worksite.state"),
    ("F.a.7", "F_worksite.postal_code"),
    ("F.a.8", "F_worksite.msa_oes_area_code"),
    ("G.1", "G_job_info.full_time_35hrs"),
    ("G.2", "G_job_info.live_in_domestic"),
    ("G.4", "G_job_info.fw_currently_employed"),
    ("G.5", "G_job_info.relying_solely_on_experience_with_employer"),
    ("G.6", "G_job_info.live_on_premises"),
    ("G.7", "G_job_info.combination_of_occupations"),
    ("G.8", "G_job_info.foreign_language"),
    ("G.9", "G_job_info.exceeds_svp"),
    ("G.10", "G_job_info.credentialing_service"),
    ("G.11", "G_job_info.employer_received_payment"),
    ("G.12", "G_job_info.layoff_6mo"),
    ("H.a.1", "H_recruitment.supervised_recruitment"),
    ("H.b", "H_recruitment.occupation_type"),
    ("I.1", "I_attestations.certify_labor_condition_statements"),
    ("AppA.A.1", "appendix_A.contact.last_name"),
    ("AppA.A.11", "appendix_A.contact.dob"),
    ("AppA.A.14", "appendix_A.contact.country_of_birth"),
]

PO_BOX_RX = re.compile(r"\bP\.?\s*O\.?\s*BOX\b|\bPOST\s+OFFICE\s+BOX\b", re.I)
FEIN_RX = re.compile(r"^\d{2}-?\d{7}$")
PWD_RX = re.compile(r"^P-100-\d{5}-\d{6}$")
SSN_RX = re.compile(r"^\d{3}-\d{2}-\d{4}$")

# G question -> Appendix C trigger map
APPX_C_TRIGGERS = {
    "G.6": "G_job_info.live_on_premises",
    "G.7": "G_job_info.combination_of_occupations",
    "G.8": "G_job_info.foreign_language",
    "G.9": "G_job_info.exceeds_svp",
    "G.10": "G_job_info.credentialing_service",
    "G.11": "G_job_info.employer_received_payment",
    "G.12": "G_job_info.layoff_6mo",
}


def tier1(form):
    flags = []
    F = flags.append

    for item, path in REQUIRED_FIELDS:
        v = _get(form, path)
        if v is None or (isinstance(v, str) and not v.strip()):
            F(Flag(RED, "T1-001", item,
                   f"Required field {item} is blank; incomplete applications "
                   f"will be denied.", "completeness", "20 CFR 656.17(a)(1)"))

    if str(_get(form, "D_foreign_worker_flags.appendix_a_attached")) == "No":
        F(Flag(RED, "T1-002", "D.1",
               "Appendix A not attached — application will be denied.",
               "form_instructions", "ETA-9089 Instructions §D.1"))

    if str(_get(form, "I_attestations.certify_labor_condition_statements")) == "No":
        F(Flag(RED, "T1-003", "I.1",
               "Employer did not certify the Labor Condition Statements.",
               "regulation", "20 CFR 656.10(c)"))

    notice = _get(form, "H_recruitment.notice_of_posting", []) or []
    if "1f_did_not_post" in notice:
        F(Flag(RED, "T1-004", "H.e.1f",
               "Employer marked that it DID NOT post the notice of filing.",
               "regulation", "20 CFR 656.10(d)"))

    pwd = _get(form, "E_job_wage.pwd_case_number")
    if pwd and not PWD_RX.match(str(pwd).strip()):
        F(Flag(RED, "T1-005", "E.1",
               f"PWD case number '{pwd}' is not in P-100-xxxxx-xxxxxx format.",
               "typo", "ETA-9089 Instructions §E.1"))

    for item, path in [("A.3", "A_employer.address1"),
                       ("B.5", "B_poc.address1"),
                       ("F.a.2", "F_worksite.address1")]:
        v = _get(form, path) or ""
        if PO_BOX_RX.search(str(v)):
            F(Flag(RED, "T1-006", item,
                   f"{item} is a P.O. Box; a physical location is required.",
                   "form_instructions", f"ETA-9089 Instructions §{item}"))

    fein = str(_get(form, "A_employer.fein") or "").strip()
    if fein and SSN_RX.match(fein):
        F(Flag(RED, "T1-007", "A.12",
               "A.12 appears to contain an SSN, not a FEIN.",
               "form_instructions", "ETA-9089 Instructions §A.12"))
    elif fein and not FEIN_RX.match(fein):
        F(Flag(RED, "T1-007", "A.12",
               f"FEIN '{fein}' is not a valid 9-digit FEIN format.",
               "typo", "ETA-9089 Instructions §A.12"))

    # B vs C identity (T1-009)
    rep = _get(form, "C_attorney_agent.representation_type")
    if rep in ("Attorney", "Agent"):
        same_phone = _get(form, "B_poc.phone") and \
            _get(form, "B_poc.phone") == _get(form, "C_attorney_agent.phone")
        same_email = _get(form, "B_poc.email") and \
            _get(form, "B_poc.email") == _get(form, "C_attorney_agent.email")
        same_name = (_get(form, "B_poc.last_name"), _get(form, "B_poc.first_name")) == \
            (_get(form, "C_attorney_agent.last_name"), _get(form, "C_attorney_agent.first_name"))
        if same_name and (same_phone or same_email):
            F(Flag(RED, "T1-009", "B/C",
                   "Employer point of contact is identical to attorney/agent; "
                   "only permitted when the attorney is an employee of the employer.",
                   "form_instructions", "ETA-9089 Instructions §B note, §C note"))

    # Conditional dependency map (T1-010)
    def dep(trigger_path, trigger_val, dep_item, dep_path):
        # N/A is an accepted answer on FLAG-certified filings; flag only blanks.
        if str(_get(form, trigger_path)) == trigger_val and _get(form, dep_path) is None:
            F(Flag(RED, "T1-010", dep_item,
                   f"{dep_item} must be answered because its trigger is "
                   f"'{trigger_val}'.", "completeness", "20 CFR 656.17(a)(1)"))

    dep("G_job_info.live_in_domestic", "Yes", "G.2a", "G_job_info.live_in_1yr_experience")
    dep("G_job_info.live_in_domestic", "Yes", "G.2b", "G_job_info.live_in_contract_executed")
    dep("G_job_info.fw_currently_employed", "Yes", "G.4a",
        "G_job_info.fw_qualifies_only_by_alternative_reqs")
    dep("G_job_info.relying_solely_on_experience_with_employer", "Yes", "G.5a",
        "G_job_info.experience_substantially_comparable")
    dep("G_job_info.relying_solely_on_experience_with_employer", "Yes", "G.5b",
        "G_job_info.employer_paid_training")
    if str(_get(form, "G_job_info.fw_qualifies_only_by_alternative_reqs")) == "Yes" and \
       _get(form, "G_job_info.kellogg_suitable_combination") is None:
        F(Flag(RED, "T1-010", "G.4b",
               "G.4b (Kellogg suitable-combination statement) must be selected "
               "when G.4 and G.4a are both Yes.", "completeness",
               "20 CFR 656.17(a)(1); ETA-9089 Instructions §G.4b"))

    # Appendix C matching (T1-011/T1-012)
    appc_items = {e.get("section_item") for e in _get(form, "appendix_C.entries", []) or []}
    for gitem, path in APPX_C_TRIGGERS.items():
        if str(_get(form, path)) == "Yes" and gitem not in appc_items:
            F(Flag(RED, "T1-011", gitem,
                   f"{gitem} is Yes but no Appendix C section explains it.",
                   "form_instructions", "ETA-9089 Instructions Appendix C note"))
    for gitem in appc_items:
        path = APPX_C_TRIGGERS.get(gitem)
        if path and str(_get(form, path)) == "No":
            F(Flag(YELLOW, "T1-012", gitem,
                   f"Appendix C explains {gitem} but {gitem} is marked No "
                   f"(orphan explanation — likely typo).", "typo", "consistency"))

    if str(_get(form, "F_worksite.additional_worksites")) == "Yes" and \
       str(_get(form, "F_worksite.appendix_b_attached")) != "Yes":
        F(Flag(RED, "T1-013", "F.b.2",
               "F.b.1 is Yes but Appendix B is not attached.",
               "form_instructions", "ETA-9089 Instructions §F.b.2"))

    occ = _get(form, "H_recruitment.occupation_type")
    if occ == "1c_college_university_teacher" and not _get(form, "appendix_D"):
        F(Flag(RED, "T1-014", "H.b.1c",
               "College/university teacher marked but Appendix D not present.",
               "form_instructions", "ETA-9089 Instructions §H.b.1c"))
    if occ == "1d_schedule_a_sheepherder":
        F(Flag(YELLOW, "T1-015", "H.b.1d",
               "Schedule A / sheepherder: application must be filed with USCIS, "
               "not the Department.", "form_instructions",
               "ETA-9089 Instructions §H.b.1d"))

    wf = _get(form, "E_job_wage.offered_wage_from")
    wt = _get(form, "E_job_wage.offered_wage_to")
    if wf is not None and wt is not None and wt < wf:
        F(Flag(RED, "T1-020", "E.3",
               f"Wage range top ({wt}) is below bottom ({wf}).",
               "typo", "ETA-9089 Instructions §E.3"))

    emp = _get(form, "A_employer.num_employees_in_area")
    try:
        if emp is not None and int(str(emp)) == 0:
            F(Flag(YELLOW, "T1-017", "A.14",
                   "Zero employees in the area of intended employment — expect "
                   "scrutiny of ability to employ.", "data_check", "audit heuristic"))
    except ValueError:
        F(Flag(RED, "T1-016", "A.14",
               f"A.14 is not a number: '{emp}'.", "typo", "format"))

    return flags


# ---------------------------------------------------------------------------
# Tier 2 — recruitment timing (filing_date = date of review unless supplied)
# ---------------------------------------------------------------------------

def _steps(form):
    """Normalized recruitment events: {key: (start_date, end_date)}."""
    out = {}
    jo_s = _d(_get(form, "H_recruitment.swa_job_order_start"))
    jo_e = _d(_get(form, "H_recruitment.swa_job_order_end"))
    if jo_s or jo_e:
        out["swa_job_order"] = (jo_s, jo_e)
    a1 = _d(_get(form, "H_recruitment.ad1_date"))
    if a1:
        out["ad1"] = (a1, a1)
    a2 = _d(_get(form, "H_recruitment.ad2_date"))
    if a2:
        out["ad2"] = (a2, a2)
    for k, v in (_get(form, "H_recruitment.additional_steps", {}) or {}).items():
        s, e = _d(v.get("from")), _d(v.get("to"))
        if s or e:
            out[f"step:{k}"] = (s, e or s)
    return out


def filing_window(form):
    """Compute (first_day_to_file, last_day_to_file) from recruitment dates.

    first day: all mandatory recruitment (job order end, both ads) must be
      >= 30 days before filing; at most ONE additional step may have STARTED
      within 30 days of filing, so the second-latest additional-step start
      also gates the first day.  20 CFR 656.17(e)(1).
    last day: no step may be more than 180 days before filing, so
      earliest step start + 180.
    """
    steps = _steps(form)
    if not steps:
        return None, None
    gates = []
    for k in MANDATORY_STEP_KEYS:
        if k in steps:
            end = steps[k][1] or steps[k][0]
            if end:
                gates.append(end)
    add_starts = sorted(s for k, (s, e) in steps.items()
                        if k.startswith("step:") and s)
    if len(add_starts) >= 2:
        gates.append(add_starts[-2])   # all but one must be >=30 days out
    first = (max(gates) + timedelta(days=30)) if gates else None
    all_starts = [s for s, e in steps.values() if s]
    last = (min(all_starts) + timedelta(days=180)) if all_starts else None
    return first, last


def tier2(form, filing_date=None):
    flags = []
    F = flags.append
    fd = filing_date or date.today()
    steps = _steps(form)
    occ = _get(form, "H_recruitment.occupation_type")
    professional = occ == "1a_professional"
    recruiting = occ in ("1a_professional", "1b_nonprofessional")

    if not recruiting:
        return flags

    jo = steps.get("swa_job_order")
    if jo and jo[0] and jo[1]:
        if (jo[1] - jo[0]).days < 30:
            F(Flag(RED, "T2-001", "H.c.1",
                   f"SWA job order ran {(jo[1]-jo[0]).days} days; 30 required.",
                   "regulation", "20 CFR 656.17(e)(1)(i)(A)"))

    for key, item in [("swa_job_order", "H.c.1"), ("ad1", "H.c.2b"), ("ad2", "H.c.3b")]:
        ev = steps.get(key)
        if not ev:
            F(Flag(RED, "T2-003", item,
                   f"Mandatory recruitment step '{key}' has no date.",
                   "regulation", "20 CFR 656.17(e)(1)(i)"))
            continue
        end = ev[1] or ev[0]
        start = ev[0] or ev[1]
        days_before = (fd - end).days
        if days_before < 30:
            F(Flag(RED, "T2-002" if key == "swa_job_order" else "T2-003", item,
                   f"'{key}' ended {end} — only {days_before} days before filing "
                   f"({fd}); 30-day quiet period violated.",
                   "regulation", "20 CFR 656.17(e)(1)(i)"))
        if start and (fd - start).days > 180:
            F(Flag(RED, "T2-002" if key == "swa_job_order" else "T2-003", item,
                   f"'{key}' began {start} — more than 180 days before filing ({fd}).",
                   "regulation", "20 CFR 656.17(e)(1)(i)"))

    # Sunday check on ads
    for key, item, dt in [("ad1", "H.c.2b", steps.get("ad1")),
                          ("ad2", "H.c.3b", steps.get("ad2"))]:
        if dt and dt[0] and dt[0].weekday() != 6 and \
           str(_get(form, "H_recruitment.ad2_type", "")).startswith("Newspaper"):
            F(Flag(YELLOW, "T2-004", item,
                   f"Advertisement date {dt[0]} is a "
                   f"{dt[0].strftime('%A')}, not a Sunday.",
                   "regulation", "20 CFR 656.17(e)(1)(i)(B)(1)"))

    if professional:
        add = {k[5:]: v for k, v in steps.items() if k.startswith("step:")}
        if len(add) < PROFESSIONAL_MIN_ADDITIONAL_STEPS:
            F(Flag(RED, "T2-006", "H.d",
                   f"Professional occupation: only {len(add)} additional "
                   f"recruitment steps; 3 required.",
                   "regulation", "20 CFR 656.17(e)(1)(ii)"))
        solely_within_30 = [k for k, (s, e) in add.items()
                            if s and (fd - s).days < 30]
        if len(solely_within_30) > 1:
            F(Flag(RED, "T2-007", "H.d",
                   f"{len(solely_within_30)} additional steps occurred solely "
                   f"within 30 days of filing ({', '.join(solely_within_30)}); "
                   f"only one permitted.",
                   "regulation", "20 CFR 656.17(e)(1)(ii)"))
        for k, (s, e) in add.items():
            if s and (fd - s).days > 180:
                F(Flag(RED, "T2-008", "H.d",
                       f"Additional step '{k}' began {s}, more than 180 days "
                       f"before filing ({fd}).",
                       "regulation", "20 CFR 656.17(e)(1)(ii)"))
            if e and e > fd:
                F(Flag(YELLOW, "T2-013", "H.d",
                       f"Additional step '{k}' ends {e}, after the filing date.",
                       "regulation", "20 CFR 656.17(e)(1)(ii)"))
        if "employee_referral" in add:
            F(Flag(YELLOW, "T2-012", "H.d.7",
                   "Employee referral program used: be prepared to document "
                   "the incentive offered and that the program was in effect "
                   "during recruitment.", "balca",
                   "20 CFR 656.17(e)(1)(ii)(G); BALCA employee-referral line"))

    notice = _get(form, "H_recruitment.notice_of_posting", []) or []
    bad = ("1c_electronic_notice" in notice or "1d_inhouse_media" in notice) \
        and "1b_physical_notice" not in notice
    if bad:
        F(Flag(RED, "T2-011", "H.e",
               "Notice options 1c/1d selected without 1b (physical notice).",
               "form_instructions", "ETA-9089 Instructions §H.e note"))
    if "1b_physical_notice" in notice:
        F(Flag(YELLOW, "T2-010", "H.e.1b",
               "Physical notice attested: retain proof of 10 consecutive "
               "business days' posting in a conspicuous location.",
               "regulation", "20 CFR 656.10(d)(1)(ii)"))

    return flags


# ---------------------------------------------------------------------------
# Tier 4 (form-only subset) — audit-risk YELLOW flags
# ---------------------------------------------------------------------------

def tier4_form_only(form):
    flags = []
    F = flags.append
    yes = lambda p: str(_get(form, p)) == "Yes"

    if yes("A_employer.closely_held_ownership_interest"):
        F(Flag(YELLOW, "T4-001", "A.16",
               "Foreign worker has an ownership interest in a closely held "
               "employer — bona fide job opportunity scrutiny.",
               "balca", "20 CFR 656.17(l); Modular Container Systems, "
               "1989-INA-228 (en banc) totality factors"))
    if yes("A_employer.familial_relationship"):
        F(Flag(YELLOW, "T4-002", "A.17",
               "Familial relationship between foreign worker and "
               "owners/officers — audit highly likely.",
               "balca", "20 CFR 656.17(l)"))
    if yes("G_job_info.relying_solely_on_experience_with_employer") and \
       yes("G_job_info.experience_substantially_comparable"):
        F(Flag(YELLOW, "T4-003", "G.5/G.5a",
               "Qualifying experience gained with the employer in a "
               "substantially comparable position — infeasibility-to-train "
               "documentation required.",
               "balca", "20 CFR 656.17(i)(3); Delitizer Corp. of Newton, "
               "1988-INA-482"))
    if yes("G_job_info.combination_of_occupations"):
        F(Flag(YELLOW, "T4-004", "G.7",
               "Combination of occupations — business necessity/normalcy "
               "justification will be tested.",
               "regulation", "20 CFR 656.17(h)(3)"))
    if yes("G_job_info.foreign_language"):
        F(Flag(YELLOW, "T4-005", "G.8",
               "Foreign language requirement — business necessity per "
               "656.17(h)(2) must be documented.",
               "regulation", "20 CFR 656.17(h)(2)"))
    if yes("G_job_info.exceeds_svp"):
        F(Flag(YELLOW, "T4-006", "G.9",
               "Requirements exceed O*NET SVP — business necessity under the "
               "Information Industries test.",
               "balca", "20 CFR 656.17(h)(1); Information Industries, "
               "1988-INA-82 (en banc)"))
    if yes("G_job_info.employer_received_payment"):
        F(Flag(YELLOW, "T4-008", "G.11",
               "Employer received payment for filing — 656.12(b) prohibition "
               "analysis required.",
               "regulation", "20 CFR 656.12(b)"))
    if yes("G_job_info.layoff_6mo"):
        F(Flag(YELLOW, "T4-009", "G.12",
               "Layoff in the occupation/related occupation within 6 months — "
               "notify-and-consider obligations apply.",
               "regulation", "20 CFR 656.17(k)"))
    if str(_get(form, "G_job_info.kellogg_suitable_combination")) == "I DO NOT ACCEPT":
        F(Flag(YELLOW, "T4-010", "G.4b",
               "Employer will not accept a suitable combination — Kellogg "
               "denial risk where alternative requirements are not "
               "substantially equivalent.",
               "balca", "Matter of Francis Kellogg, 1994-INA-465 (en banc)"))
    geo = str(_get(form, "F_worksite.other_geographic_areas") or "")
    if re.search(r"travel|roving|various", geo, re.I):
        F(Flag(YELLOW, "T4-011", "F.c.1",
               f"Travel/roving language present ('{geo[:80]}') — confirm PWD "
               f"and recruitment cover the area(s) of employment.",
               "balca", "20 CFR 656.10; BALCA roving-employee line"))
    return flags
