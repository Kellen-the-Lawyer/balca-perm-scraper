"""Tier 3 — wage and PWD cross-checks. Requires an extracted ETA-9141 dict
(app.perm_verify.extract_9141.extract) alongside the 9089 form dict.

Also runs worker-qualification cross-checks (T4-014 family) that need the
PWD's minimum requirements: education level and experience months vs the
foreign worker's Appendix A education / work-experience entries.
"""
from __future__ import annotations
import re
from datetime import date

from .rules import Flag, RED, YELLOW, _get, _d

DEGREE_RANK = {"None": 0, "High School/GED": 1, "High school/GED": 1,
               "Associate": 2, "Associate's": 2, "Bachelor's": 3,
               "Master's": 4, "Doctorate": 5, "Other": 3, "Other Degree": 3}

ANNUALIZE = {"Hour": 2080, "Week": 52, "Bi-Weekly": 26, "Month": 12, "Year": 1}


def _annual(amount, per):
    if amount is None:
        return None
    return amount * ANNUALIZE.get(per or "Year", 1)


def tier3(form, pwd, filing_date=None):
    flags = []
    F = flags.append
    fd = filing_date or date.today()

    # ---- linkage: PWD number match (E.1) ------------------------------------
    e1 = str(_get(form, "E_job_wage.pwd_case_number") or "").strip()
    pnum = str(pwd.get("pwd_case_number") or "").strip()
    if e1 and pnum and e1 != pnum:
        F(Flag(RED, "T3-010", "E.1",
               f"PWD number on 9089 ({e1}) does not match the supplied "
               f"determination ({pnum}). Wrong PWD attached or typo.",
               "typo", "ETA-9089 Instructions §E.1"))
        return flags  # remaining cross-checks would compare the wrong case

    # ---- employer identity ----------------------------------------------------
    fein_9089 = str(_get(form, "A_employer.fein") or "").replace("-", "")
    fein_9141 = str(pwd.get("employer_fein") or "").replace("-", "")
    if fein_9141 and fein_9089 and fein_9141 != fein_9089:
        F(Flag(RED, "T3-011", "A.12",
               f"Employer FEIN differs between 9089 ({fein_9089}) and PWD "
               f"({fein_9141}); employer on the 9089 must match the PWD.",
               "form_instructions", "ETA-9089 Instructions §A note (must match PWD)"))
    name_9089 = (_get(form, "A_employer.legal_business_name") or "").strip().lower()
    name_9141 = (pwd.get("employer_name") or "").strip().lower()
    if name_9089 and name_9141 and name_9089 != name_9141:
        F(Flag(YELLOW, "T3-012", "A.1",
               f"Employer name differs: 9089 '{name_9089}' vs PWD '{name_9141}'. "
               f"Confirm same legal entity (exact-name rule).",
               "form_instructions", "ETA-9089 Instructions §A note"))

    # ---- wage floor -----------------------------------------------------------
    offered = _get(form, "E_job_wage.offered_wage_from")
    offered_per = _get(form, "E_job_wage.wage_per") or "Year"
    offered_annual = _annual(offered, offered_per)
    pw_min = _annual(pwd.get("pw_minimum"), pwd.get("pw_per"))
    pw_alt = _annual(pwd.get("pw_alternative"), pwd.get("pw_per"))
    governing = max(x for x in (pw_min, pw_alt) if x is not None) \
        if (pw_min or pw_alt) else None

    if governing is not None and offered_annual is not None:
        if offered_annual < governing:
            which = "higher of the two PWD wages" if pw_alt else "prevailing wage"
            F(Flag(RED, "T3-001", "E.3",
                   f"Offered wage ${offered_annual:,.2f}/yr is below the "
                   f"{which} ${governing:,.2f}/yr on PWD {pnum}.",
                   "regulation",
                   "20 CFR 656.10(c)(1); ETA-9089 Instructions §E note "
                   "(higher-of-two rule)"))
        elif offered_annual < governing * 1.02:
            F(Flag(YELLOW, "T3-003", "E.3",
                   f"Offered wage ${offered_annual:,.2f}/yr is within 2% of the "
                   f"prevailing wage ${governing:,.2f}/yr — no cushion for a "
                   f"renewal-year PW increase before the I-140/start date.",
                   "data_check", "practice heuristic"))

    # ---- PWD validity at filing ------------------------------------------------
    v_from, v_to = _d(pwd.get("validity_from")), _d(pwd.get("validity_to"))
    if v_from and v_to:
        if fd < v_from:
            F(Flag(RED, "T3-005", "E.1",
                   f"Filing date {fd} precedes PWD validity start {v_from}.",
                   "regulation", "20 CFR 656.40(c)"))
        elif fd > v_to:
            # 656.40(c): filing after expiration is PERMITTED if recruitment
            # began during the validity period. Check recruitment starts.
            from .rules import _steps
            starts = [s for s, e in _steps(form).values() if s]
            first_recruit = min(starts) if starts else None
            if first_recruit and v_from <= first_recruit <= v_to:
                pass  # lawful: recruitment began during validity
            elif first_recruit:
                F(Flag(RED, "T3-005", "E.1",
                       f"PWD {pnum} expired {v_to}; filing date {fd} is after "
                       f"expiration AND recruitment began {first_recruit}, "
                       f"outside the validity period {v_from}-{v_to}.",
                       "regulation", "20 CFR 656.40(c)"))
            else:
                F(Flag(YELLOW, "T3-005", "E.1",
                       f"PWD {pnum} expired {v_to} before the filing date "
                       f"{fd}. Lawful only if recruitment began during "
                       f"validity ({v_from}-{v_to}) - no recruitment dates "
                       f"available to confirm.",
                       "regulation", "20 CFR 656.40(c)"))
        elif (v_to - fd).days <= 14:
            F(Flag(YELLOW, "T3-013", "E.1",
                   f"PWD expires {v_to} — only {(v_to - fd).days} days after "
                   f"the presumed filing date. Verify filing occurs in time.",
                   "regulation", "20 CFR 656.40(c)"))

    # ---- geography ---------------------------------------------------------------
    msa_9089 = (_get(form, "F_worksite.msa_oes_area_title") or "").strip().lower()
    bls_9141 = (pwd.get("bls_area") or "").strip().lower()
    if msa_9089 and bls_9141 and msa_9089 != bls_9141:
        F(Flag(RED, "T3-014", "F.a.8a",
               f"9089 MSA '{msa_9089}' differs from PWD BLS area '{bls_9141}'; "
               f"the PWD does not cover the stated worksite.",
               "regulation", "20 CFR 656.40(a); 656.10"))
    ws_zip_9089 = (_get(form, "F_worksite.postal_code") or "").strip()
    ws_zip_9141 = (pwd.get("worksite_postal") or "").strip()
    if ws_zip_9089 and ws_zip_9141 and ws_zip_9089 != ws_zip_9141:
        F(Flag(YELLOW, "T3-015", "F.a.7",
               f"Worksite ZIP differs: 9089 {ws_zip_9089} vs PWD {ws_zip_9141}. "
               f"Fine if same BLS area, but confirm.",
               "data_check", "20 CFR 656.40(a)"))

    # ---- worker qualification vs PWD minimums ------------------------------------
    req_deg = pwd.get("education_required")
    if req_deg:
        worker_best = 0
        for edu in _get(form, "appendix_A.education", []) or []:
            worker_best = max(worker_best, DEGREE_RANK.get(edu.get("degree"), 0))
        need = DEGREE_RANK.get(req_deg, 0)
        if worker_best and worker_best < need:
            F(Flag(RED, "T3-020", "AppA.B",
                   f"PWD requires {req_deg} but Appendix A shows highest degree "
                   f"rank below that. Worker does not facially meet the minimum "
                   f"education requirement.",
                   "regulation", "20 CFR 656.17(i); INA 212(a)(5)(A)"))

    req_months = pwd.get("experience_months_required")
    if req_months:
        total = 0
        for we in _get(form, "appendix_A.work_experience", []) or []:
            s, e = _d(we.get("start")), _d(we.get("end"))
            if s:
                e = e or fd
                total += max(0, (e.year - s.year) * 12 + (e.month - s.month))
        if total and total < req_months:
            F(Flag(YELLOW, "T3-021", "AppA.E",
                   f"Appendix A work experience totals ~{total} months; PWD "
                   f"requires {req_months}. Verify qualifying experience "
                   f"(and exclude experience with the sponsoring employer "
                   f"unless G.5 analysis supports it).",
                   "regulation", "20 CFR 656.17(i)"))

    # travel consistency
    trav_9141 = (pwd.get("travel_details") or "").strip().lower()
    trav_9089 = (_get(form, "F_worksite.other_geographic_areas") or "").strip().lower()
    if trav_9141 and not trav_9089:
        F(Flag(YELLOW, "T3-016", "F.c.1",
               f"PWD discloses travel ('{trav_9141[:60]}') but 9089 F.c is "
               f"empty — keep the two consistent.",
               "data_check", "20 CFR 656.10"))

    return flags
