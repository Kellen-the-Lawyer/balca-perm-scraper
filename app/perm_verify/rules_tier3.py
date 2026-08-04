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


def _worker_profile(form, fd):
    """(highest degree rank, total experience months) from Appendix A.

    Education comes from Appendix A.B, experience from Appendix A.E across all
    employers listed.  Appendix A.D (special skills) is an attestation and is
    deliberately not counted as general experience.

    Experience with the petitioner IS counted: G.5 asks whether the employer
    relies *solely* on experience gained with it, so partial petitioner
    experience does not disqualify the rest.  The narrow case where that
    experience is genuinely unusable — G.5 and G.5a both Yes under
    656.17(i)(3) — is flagged separately by T1-010d.

    Overlapping spans are merged rather than summed, so concurrent positions
    do not double-count calendar time.
    """
    best = 0
    for edu in _get(form, "appendix_A.education", []) or []:
        best = max(best, DEGREE_RANK.get(edu.get("degree"), 0))

    spans = []
    for we in _get(form, "appendix_A.work_experience", []) or []:
        s, e = _d(we.get("start")), _d(we.get("end"))
        if s:
            spans.append([s, e or fd])
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    total = sum(max(0, (e.year - s.year) * 12 + (e.month - s.month))
                for s, e in merged)
    return best, total



def _meets(rank, months, req_degree, req_months):
    """Does a worker profile satisfy one PWD requirement set?"""
    if req_degree and rank < DEGREE_RANK.get(req_degree, 0):
        return False
    if req_months and months < req_months:
        return False
    return True


def _requirement_paths(form, pwd, fd):
    """(meets_primary, meets_alternate, has_alternate) for this worker."""
    rank, months = _worker_profile(form, fd)
    has_alt = pwd.get("alternate_reqs_accepted") == "Yes"
    meets_primary = _meets(rank, months, pwd.get("education_primary"),
                           pwd.get("experience_months_primary"))
    meets_alt = has_alt and _meets(rank, months,
                                   pwd.get("education_alternate"),
                                   pwd.get("experience_months_alternate"))
    return meets_primary, meets_alt, has_alt



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

    # ---- PWD validity at filing / filing window ---------------------------------
    # 656.40(c): the validity period must cover either the filing date or the
    # start of at least one recruitment step.  Three postures:
    #   (a) >=1 step STARTS during validity -> filing is governed by the
    #       30/180 recruitment window (Tier 2, filing_window()), NOT by PWD
    #       expiry; the window can lawfully close months after the PWD expires.
    #   (b) recruitment began before the PWD issued and no step starts during
    #       validity -> the 9089 must be FILED during the validity period, so
    #       the effective deadline is min(180-day window close, validity end).
    #   (c) ALL recruitment starts after validity ends -> the recruitment is
    #       not usable with this determination.
    v_from, v_to = _d(pwd.get("validity_from")), _d(pwd.get("validity_to"))
    if v_from and v_to:
        from .rules import _steps, filing_window
        starts = [s for s, e in _steps(form).values() if s]
        in_validity = any(v_from <= s <= v_to for s in starts)
        _, window_last = filing_window(form)
        deadline = None
        binds = None

        if fd < v_from:
            F(Flag(RED, "T3-005", "E.1",
                   f"Filing date {fd} precedes PWD validity start {v_from}.",
                   "regulation", "20 CFR 656.40(c)"))
        elif in_validity:
            # posture (a): PWD expiry no longer gates the filing date.
            deadline, binds = window_last, "180-day recruitment window"
        elif starts and all(s > v_to for s in starts):
            # posture (c)
            F(Flag(RED, "T3-005", "H.c",
                   f"No recruitment step started during the PWD validity "
                   f"period {v_from}-{v_to}; every step began after "
                   f"expiration. The recruitment cannot be used with PWD "
                   f"{pnum}.",
                   "regulation", "20 CFR 656.40(c)"))
        elif starts:
            # posture (b): recruitment predates the PWD; must file while valid.
            if fd > v_to:
                F(Flag(RED, "T3-005", "E.1",
                       f"Recruitment began before PWD {pnum} issued and no "
                       f"step started during validity ({v_from}-{v_to}), so "
                       f"the 9089 had to be filed during the validity period; "
                       f"filing date {fd} is after expiration.",
                       "regulation", "20 CFR 656.40(c)"))
            else:
                cands = [x for x in (window_last, v_to) if x]
                deadline = min(cands) if cands else None
                binds = ("PWD expiration" if deadline == v_to
                         else "180-day recruitment window")
        else:
            # no recruitment dates on the form: can only test filing-in-validity.
            if fd > v_to:
                F(Flag(YELLOW, "T3-005", "E.1",
                       f"PWD {pnum} expired {v_to} before the filing date "
                       f"{fd}. Lawful only if recruitment began during "
                       f"validity ({v_from}-{v_to}) - no recruitment dates "
                       f"available to confirm.",
                       "regulation", "20 CFR 656.40(c)"))
            else:
                deadline, binds = v_to, "PWD expiration"

        # T3-013: filing window closing soon (Tier 2 flags windows already
        # blown; this is the prospective warning, PWD-aware per posture).
        if deadline and 0 <= (deadline - fd).days <= 14:
            F(Flag(YELLOW, "T3-013", "H.c",
                   f"The filing window closes {deadline} ({binds}) — only "
                   f"{(deadline - fd).days} days after the presumed filing "
                   f"date {fd}. Verify filing occurs in time.",
                   "regulation", "20 CFR 656.17(e); 656.40(c)"))

    # ---- geography ---------------------------------------------------------------
    # T3-014 (T3-015 folded in).  The MSA/BLS area titles on both forms are
    # AUTO-FILLED by FLAG from the entered address, so equal titles mean the
    # same OES area.  Differing titles are cross-checked against the
    # county->area-code map (geo.area_codes; split counties yield sets, so
    # "same area" = the sets intersect) before flagging RED, to absorb
    # formatting drift between the two forms' renderings of one area.
    from .geo import area_codes, norm_area_title, norm_county
    title_9089 = norm_area_title(_get(form, "F_worksite.msa_oes_area_title"))
    title_9141 = norm_area_title(pwd.get("bls_area"))
    areas_9089 = area_codes(_get(form, "F_worksite.county"),
                            _get(form, "F_worksite.state"))
    areas_9141 = area_codes(pwd.get("worksite_county"),
                            pwd.get("worksite_state"))

    if title_9089 and title_9141:
        same_area = title_9089 == title_9141
        if not same_area and areas_9089 and areas_9141 \
                and (areas_9089 & areas_9141):
            same_area = True   # title formatting drift; counties agree
    elif areas_9089 and areas_9141:
        same_area = bool(areas_9089 & areas_9141)
    else:
        same_area = None       # cannot resolve either way

    detail_pairs = [
        ("ZIP", _get(form, "F_worksite.postal_code"),
         pwd.get("worksite_postal"), str.strip),
        ("city", _get(form, "F_worksite.city"), pwd.get("worksite_city"),
         str.strip),
        ("county", _get(form, "F_worksite.county"),
         pwd.get("worksite_county"), norm_county),
        ("address", _get(form, "F_worksite.address1"),
         pwd.get("worksite_address1"), str.strip),
    ]
    diffs = [f"{k}: 9089 '{a}' vs PWD '{b}'"
             for k, a, b, norm in detail_pairs
             if a and b and norm(str(a).lower()) != norm(str(b).lower())]

    if same_area is False:
        F(Flag(RED, "T3-014", "F.a.8a",
               f"Worksites are in different OES areas — 9089 "
               f"'{_get(form, 'F_worksite.msa_oes_area_title')}' vs PWD "
               f"'{pwd.get('bls_area')}'. The PWD does not cover the stated "
               f"worksite.",
               "regulation", "20 CFR 656.40(a); 656.10"))
    elif same_area and diffs:
        F(Flag(YELLOW, "T3-014", "F.a",
               "Worksite details differ between the 9089 and PWD but both "
               "fall in the same OES area (" + "; ".join(diffs[:3]) + "). "
               "Confirm the intended worksite.",
               "data_check", "20 CFR 656.40(a)"))
    elif same_area is None and diffs:
        F(Flag(YELLOW, "T3-014", "F.a",
               "Worksite details differ between the 9089 and PWD (" +
               "; ".join(diffs[:3]) + ") and the OES area could not be "
               "resolved from either form. Verify the PWD covers the "
               "worksite.",
               "data_check", "20 CFR 656.40(a)"))

    # ---- worker qualification vs PWD minimums ------------------------------------
    # Only meaningful if the worker also fails the alternate set: an employer
    # may lawfully qualify the worker under F.c instead of F.b.
    meets_primary, meets_alt, has_alt = _requirement_paths(form, pwd, fd)
    rank, months_total = _worker_profile(form, fd)

    req_deg = pwd.get("education_primary") or pwd.get("education_required")
    if req_deg and rank and not meets_alt:
        if rank < DEGREE_RANK.get(req_deg, 0):
            alt = pwd.get("education_alternate")
            F(Flag(RED, "T3-020", "AppA.B",
                   f"PWD requires {req_deg} but Appendix A shows a lower "
                   f"highest degree"
                   + (f", and the alternate set ({alt}) is not met either."
                      if has_alt else " (no alternate set on the PWD).")
                   + " Worker does not facially meet the education requirement.",
                   "regulation", "20 CFR 656.17(i); INA 212(a)(5)(A)"))

    req_months = pwd.get("experience_months_primary") or \
        pwd.get("experience_months_required")
    if req_months and months_total and not meets_alt:
        if months_total < req_months:
            F(Flag(YELLOW, "T3-021", "AppA.E",
                   f"Appendix A work experience totals ~{months_total} months; "
                   f"PWD requires {req_months}"
                   + (f" ({pwd.get('experience_months_alternate')} under the "
                      f"alternate set, also unmet)." if has_alt else ".")
                   + " Verify qualifying experience (and exclude experience "
                     "with the sponsoring employer unless G.5 supports it).",
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


# ---------------------------------------------------------------------------
# T3-030..T3-036 — Section G answers derived from the PWD.
#
# These live in Tier 3 rather than Tier 1 because every one of them needs the
# determination: Tier 1 is form-only by contract.  Renumber into the T1-011x
# family in one pass if the G-section grouping matters more than the tier's
# data dependency.
# ---------------------------------------------------------------------------

def _appendix_c_items(form):
    return {e.get("section_item")
            for e in (_get(form, "appendix_C.entries", []) or [])}


def _mismatch(F, rule_id, item, expected, actual, why, citation):
    """Flag a derived answer that disagrees with the form.

    Understating (should be Yes, answered No) is RED — it hides a requirement
    the CO will test.  Overstating (should be No, answered Yes) is YELLOW,
    since it invites scrutiny but does not conceal anything.
    """
    if str(actual) == expected:
        return False
    level = RED if expected == "Yes" else YELLOW
    F(Flag(level, rule_id, item,
           f"{item} is answered '{actual}' but the PWD indicates it should be "
           f"'{expected}': {why}", "regulation", citation))
    return True


def derived_checks(form, pwd, filing_date=None):
    """G.4a, G.7, G.8 and G.10 answers cross-checked against the PWD."""
    flags = []
    F = flags.append
    fd = filing_date or date.today()
    appc = _appendix_c_items(form)

    # ---- G.4a: qualifying via primary vs alternate requirements -----------
    g4 = _get(form, "G_job_info.fw_currently_employed")
    g4a = _get(form, "G_job_info.fw_qualifies_only_by_alternative_reqs")
    meets_primary, meets_alt, has_alt = _requirement_paths(form, pwd, fd)

    if not has_alt:
        expected_g4a = "N/A"          # no alternate set in F.c
    elif meets_primary:
        expected_g4a = "No"           # qualifies on F.b.1 + F.b.4.a
    elif meets_alt:
        expected_g4a = "Yes"          # relying on F.c.2 + F.c.4.a
    else:
        expected_g4a = None

    if expected_g4a is None:
        F(Flag(RED, "T3-030", "G.4a",
               "The foreign worker's Appendix A education and experience meet "
               "neither the minimum requirements (F.b) nor the alternate "
               "requirements (F.c) on the PWD.",
               "regulation", "20 CFR 656.17(i); INA 212(a)(5)(A)"))
    else:
        _mismatch(F, "T3-031", "G.4a", expected_g4a, g4a,
                  "qualification was assessed against the PWD's F.b and F.c "
                  "requirement sets using Appendix A.B education and "
                  "Appendix A.E experience.",
                  "20 CFR 656.17(i); ETA-9089 Instructions §G.4a")

    if str(g4) == "Yes" and str(g4a) == "Yes":
        F(Flag(YELLOW, "T3-032", "G.4/G.4a",
               "Foreign worker is currently employed by the employer AND "
               "qualifies only through the alternate requirements — route to "
               "the legal team for Kellogg review before filing.",
               "balca", "Matter of Francis Kellogg, 1994-INA-465 (en banc)"))

    # ---- G.7: combination of occupations (PWD G.3.d/G.3.e) ---------------
    combo = pwd.get("combination_of_occupations")
    if combo is not None:
        expected_g7 = "Yes" if combo else "No"
        code = pwd.get("combination_code") or pwd.get("combination_title")
        _mismatch(F, "T3-033", "G.7", expected_g7,
                  _get(form, "G_job_info.combination_of_occupations"),
                  (f"PWD G.3.d/G.3.e list another occupation ({code})."
                   if combo else "PWD G.3.d/G.3.e are blank."),
                  "20 CFR 656.17(h)(3); ETA-9089 Instructions §G.7")
        if expected_g7 == "Yes" and "G.7" not in appc:
            F(Flag(RED, "T3-033a", "G.7",
                   "The PWD shows a combination of occupations, so G.7 "
                   "requires a business-necessity explanation in Appendix C; "
                   "none addresses G.7.",
                   "form_instructions",
                   "20 CFR 656.17(h)(3); ETA-9089 Instructions Appendix C"))

    # ---- G.8: foreign language (PWD F.b.5.a(ii) / F.c.5.a(ii)) -----------
    lang = bool(pwd.get("foreign_language_primary")) or \
        bool(pwd.get("foreign_language_alternate"))
    expected_g8 = "Yes" if lang else "No"
    which = "F.b.5.a(ii)" if pwd.get("foreign_language_primary") \
        else "F.c.5.a(ii)"
    _mismatch(F, "T3-034", "G.8", expected_g8,
              _get(form, "G_job_info.foreign_language"),
              (f"PWD {which} is checked."
               if lang else "no foreign-language box is checked on the PWD."),
              "20 CFR 656.17(h)(2); ETA-9089 Instructions §G.8")
    if expected_g8 == "Yes" and "G.8" not in appc:
        F(Flag(RED, "T3-034a", "G.8",
               "The PWD requires a foreign language, so G.8 requires a "
               "business-necessity explanation in Appendix C; none addresses "
               "G.8.", "form_instructions",
               "20 CFR 656.17(h)(2); ETA-9089 Instructions Appendix C"))

    # ---- G.10: foreign-equivalency language in the special-skills text ----
    if str(_get(form, "G_job_info.credentialing_service")) == "Yes":
        texts = [pwd.get("special_skills_text") or "",
                 pwd.get("special_skills_text_alternate") or ""]
        if not any(re.search(r"or\s+foreign\s+equivalent", t, re.I)
                   for t in texts):
            F(Flag(YELLOW, "T3-035", "G.10",
                   "G.10 is Yes (foreign degree accepted via credential "
                   "evaluation) but neither the F.b.5.a(iv) nor the "
                   "F.c.5.a(iv) addendum states 'or foreign equivalent' — the "
                   "PWD does not on its face permit the equivalency.",
                   "regulation", "20 CFR 656.17(h); 656.40"))

    return flags

