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

# Ranking used to pick the foreign worker's highest degree (Appendix A.B).
# Mirrors rules_tier3.DEGREE_RANK; consolidate the two when Tier 3 is reworked.
DEGREE_RANK = {"None": 0, "High School/GED": 1, "High school/GED": 1,
               "Associate": 2, "Associate's": 2, "Bachelor's": 3,
               "Master's": 4, "Doctorate": 5, "Other": 3, "Other Degree": 3}

US_COUNTRY_NAMES = {"united states of america", "united states", "usa",
                    "u.s.a.", "us", "u.s.", "united states of america (usa)"}

_ENTITY_SUFFIX_RX = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|"
    r"company|plc|lp|llp|pc|na|usa)\b\.?", re.I)



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


def _norm_entity(name):
    """Normalize a business name for comparison: drop punctuation and
    common entity suffixes so 'Chewy Inc.' == 'Chewy, Inc'."""
    s = re.sub(r"[^\w\s]", " ", str(name or "").lower())
    s = _ENTITY_SUFFIX_RX.sub(" ", s)
    return " ".join(s.split())


def _same_entity(a, b, threshold=0.88):
    na, nb = _norm_entity(a), _norm_entity(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    import difflib
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def _is_us(country):
    return str(country or "").strip().lower() in US_COUNTRY_NAMES


def _g5_checks(form):
    """T1-010a..e — G.5 family: reliance on experience gained with the
    petitioning employer.

    The correct G.5 answer is derived from Appendix A.E (work experience):
    if every employer listed there is the petitioner, the worker's qualifying
    experience was necessarily gained with the employer and G.5 must be Yes.
    Appendix A.D (special skills) is an attestation, not proof of general
    experience, so it is deliberately not consulted here.
    """
    flags = []
    F = flags.append
    g5 = _get(form, "G_job_info.relying_solely_on_experience_with_employer")
    g5a = _get(form, "G_job_info.experience_substantially_comparable")
    g5b = _get(form, "G_job_info.employer_paid_training")

    petitioner = _get(form, "A_employer.legal_business_name")
    employers = [w.get("employer_name")
                 for w in (_get(form, "appendix_A.work_experience", []) or [])
                 if w.get("employer_name")]
    only_petitioner = bool(employers) and bool(petitioner) and \
        all(_same_entity(e, petitioner) for e in employers)

    if only_petitioner and str(g5) == "No":
        F(Flag(RED, "T1-010a", "G.5",
               f"Every employer in Appendix A.E is the petitioner "
               f"('{petitioner}'), so all qualifying experience was gained "
               f"with the employer — G.5 should be Yes, not No.",
               "regulation",
               "20 CFR 656.17(i)(3); ETA-9089 Instructions §G.5"))

    if str(g5) == "Yes":
        F(Flag(YELLOW, "T1-010b", "G.5",
               "Employer is relying solely on experience the foreign worker "
               "gained with the employer — 656.17(i)(3) applies; be prepared "
               "to show the positions are not substantially comparable.",
               "balca",
               "20 CFR 656.17(i)(3); Delitizer Corp. of Newton, 1988-INA-482"))
        if str(g5a) == "Yes":
            F(Flag(RED, "T1-010d", "G.5a",
                   "G.5 and G.5a are both Yes: the employer is relying on "
                   "experience gained in a substantially comparable position, "
                   "which 656.17(i)(3) does not permit. Where a Delitizer "
                   "comparison shows the positions differ, G.5a should be No.",
                   "regulation",
                   "20 CFR 656.17(i)(3); Delitizer Corp. of Newton, 1988-INA-482"))
    elif str(g5) == "No":
        for item, val in (("G.5a", g5a), ("G.5b", g5b)):
            if not _is_na(val):
                F(Flag(RED, "T1-010c", item,
                       f"G.5 is No, so {item} must be N/A; it is answered "
                       f"'{val}'.", "completeness",
                       "20 CFR 656.17(a)(1); ETA-9089 Instructions §G.5"))

    if str(g5b) == "Yes":
        F(Flag(RED, "T1-010e", "G.5b",
               "G.5b is Yes: the employer paid for the training or experience "
               "on which the foreign worker qualifies.",
               "regulation", "20 CFR 656.17(i)(3); 656.17(l)"))
    return flags


def _g10_checks(form):
    """T1-011a/b — G.10 (credentialing service) derived from the country of
    institution on each Appendix A.B education record.

    A tie at the highest degree rank counts as US-conferred if any degree at
    that rank was conferred in the United States.
    """
    flags = []
    F = flags.append
    if str(_get(form, "G_job_info.credentialing_service")) != "No":
        return flags
    edus = [e for e in (_get(form, "appendix_A.education", []) or [])
            if e.get("degree")]
    foreign = [e for e in edus if e.get("country") and not _is_us(e["country"])]
    if not edus or not foreign:
        return flags

    top = max(DEGREE_RANK.get(e.get("degree"), 0) for e in edus)
    top_is_us = any(_is_us(e.get("country"))
                    for e in edus if DEGREE_RANK.get(e.get("degree"), 0) == top)
    names = ", ".join(f"{e.get('degree')} ({e.get('country')})"
                      for e in foreign)
    if not top_is_us:
        F(Flag(RED, "T1-011a", "G.10",
               f"The foreign worker's highest degree was conferred outside "
               f"the United States [{names}] but G.10 is answered No.",
               "form_instructions", "ETA-9089 Instructions §G.10"))
    else:
        F(Flag(YELLOW, "T1-011b", "G.10",
               f"A lower-level degree was conferred outside the United States "
               f"[{names}] while the highest degree is US-conferred and G.10 "
               f"is No. Correct if the worker qualifies on the US degree; "
               f"confirm the foreign degree is not being relied on.",
               "form_instructions", "ETA-9089 Instructions §G.10"))
    return flags


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

    # Cross-file identity guard: uploaded documents name different foreign
    # workers (e.g. two PERMs for the same employer mixed into one upload).
    mism = _get(form, "meta.beneficiary_mismatch")
    if mism:
        who = "; ".join(f"{m['file']}: {m['last_name']}, {m['first_name']}"
                        for m in mism)
        F(Flag(RED, "T1-021", "AppA.A.1",
               f"Uploaded documents name DIFFERENT foreign workers ({who}) — "
               f"the files appear to belong to different cases and this "
               f"review merged them. Re-upload one case's documents only.",
               "data_check", "cross-file consistency"))

    emp = _get(form, "A_employer.num_employees_in_area")
    try:
        if emp is not None and int(str(emp)) == 0:
            F(Flag(YELLOW, "T1-017", "A.14",
                   "Zero employees in the area of intended employment — expect "
                   "scrutiny of ability to employ.", "data_check", "audit heuristic"))
    except ValueError:
        F(Flag(RED, "T1-016", "A.14",
               f"A.14 is not a number: '{emp}'.", "typo", "format"))

    flags += _g5_checks(form)
    flags += _g10_checks(form)

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

    # ---- print advertisements: Sunday placement and spacing ----------------
    # The form has no ad1 type selector: H.c.2/2a/2b are definitionally the
    # newspaper-of-general-circulation ad, while H.c.3 carries a type for ad2
    # (the (B)(4) professional-journal substitution).  The Sunday test on ad1
    # therefore must never be gated on ad2's type.
    a1, a2 = steps.get("ad1"), steps.get("ad2")
    ad2_type = str(_get(form, "H_recruitment.ad2_type", "") or "")
    ad2_is_paper = ad2_type.startswith("Newspaper")
    sunday_avail = str(_get(form, "H_recruitment.sunday_edition_exists", "") or "")

    checks = [("ad1", "H.c.2b", a1, True)]
    if a2:
        checks.append(("ad2", "H.c.3b", a2, ad2_is_paper))

    for key, item, dt, is_paper in checks:
        if not (dt and dt[0] and is_paper) or dt[0].weekday() == 6:
            continue
        day = dt[0].strftime("%A")
        if sunday_avail == "Yes":
            F(Flag(RED, "T2-005", item,
                   f"{key} ran {dt[0]} (a {day}), but H.c.2 states a Sunday "
                   f"edition is available — the (B)(2) substitution does not "
                   f"apply where a Sunday edition serves the area.",
                   "regulation", "20 CFR 656.17(e)(1)(i)(B)(1)-(2)"))
        else:
            F(Flag(YELLOW, "T2-004", item,
                   f"{key} ran {dt[0]} (a {day}), not a Sunday. The (B)(2) "
                   f"substitution is written for rural areas with no Sunday "
                   f"edition; retain proof none serves the area of intended "
                   f"employment.",
                   "regulation", "20 CFR 656.17(e)(1)(i)(B)(1)-(2)"))

    if a1 and a2 and a1[0] and a2[0]:
        # No T2-004b "neither ad is a Sunday ad" rule: ad1 has no type field,
        # so two journal ads cannot be represented, and the only case it would
        # catch is a no-Sunday-edition market running two non-Sunday ads —
        # which is the (B)(2) carve-out, already YELLOW under T2-004.  Where a
        # Sunday edition does exist, T2-005 flags each ad RED on its own.
        if ad2_is_paper and a1[0] == a2[0]:
            F(Flag(RED, "T2-004a", "H.c.3b",
                   f"Both newspaper advertisements ran on {a1[0]}; the "
                   f"regulation requires two different Sundays.",
                   "regulation", "20 CFR 656.17(e)(1)(i)(B)(1)"))
        elif ad2_is_paper:
            # Consecutive weekly editions.  6-8 days catches both a skipped
            # edition and two ads inside the same week.  Skipped when ad2 is a
            # journal: there is only one newspaper ad to be consecutive with.
            gap = abs((a2[0] - a1[0]).days)
            if not 6 <= gap <= 8:
                F(Flag(YELLOW, "T2-016", "H.c.3b",
                       f"Print advertisements ran {gap} days apart ({a1[0]} "
                       f"and {a2[0]}); DOL expects consecutive weekly editions.",
                       "dol_practice",
                       "20 CFR 656.17(e)(1)(i)(B)(1) requires two different "
                       "Sundays; consecutive placement is DOL enforcement "
                       "practice, not regulatory text."))

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
    # T4-003 retired: the G.5/G.5a pair is now handled by T1-010b (G.5 = Yes,
    # YELLOW) and T1-010d (G.5 + G.5a both Yes, RED), which reflect that a
    # Delitizer comparison showing dissimilar positions yields G.5a = No.
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
