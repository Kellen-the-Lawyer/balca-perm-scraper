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
    """Annualize a wage. Coerces strings ('$190,000') so user-supplied
    and structured-caller values behave like extractor floats."""
    if amount is None:
        return None
    if not isinstance(amount, (int, float)):
        try:
            amount = float(str(amount).replace(",", "").replace("$", "")
                           .strip())
        except ValueError:
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


RANK_NAME = {0: "none listed", 1: "High School/GED", 2: "Associate's",
             3: "Bachelor's", 4: "Master's", 5: "Doctorate"}


def _worker_profile_full(form, fd):
    """(rank, months_all, months_excluding_sponsor, n_edu, n_we, has_other).

    Like _worker_profile but also computes experience with sponsoring-
    employer spans excluded (employer_name vs A.1, normalized), counts the
    Appendix A entries, and reports whether an 'Other Degree' is listed.
    """
    best, has_other = 0, False
    edus = _get(form, "appendix_A.education", []) or []
    for edu in edus:
        d = edu.get("degree")
        if d and str(d).lower().startswith("other"):
            has_other = True
        best = max(best, DEGREE_RANK.get(d, 0))
    sponsor = re.sub(r"[^a-z0-9]", "",
                     (_get(form, "A_employer.legal_business_name") or "")
                     .lower())
    spans = []
    wes = _get(form, "appendix_A.work_experience", []) or []
    for we in wes:
        s, e = _d(we.get("start")), _d(we.get("end"))
        if not s:
            continue
        emp = re.sub(r"[^a-z0-9]", "",
                     (we.get("employer_name") or "").lower())
        spans.append((s, e or fd, bool(sponsor) and emp == sponsor))

    def _merged_months(include_sponsor):
        sel = sorted([s, e] for s, e, sp in spans
                     if include_sponsor or not sp)
        merged = []
        for s, e in sel:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        return sum(max(0, (e.year - s.year) * 12 + (e.month - s.month))
                   for s, e in merged)

    return (best, _merged_months(True), _merged_months(False),
            len(edus), len(wes), has_other)


def _eval_path(rank, mo_all, mo_ext, req_deg, req_mo, label):
    """Evaluate one PWD requirement path against the worker profile.

    exp outcomes: "ok", "employer_dependent" (meets only when counting
    experience with the sponsor), "near_miss" (short by <=2 months —
    the form's month/year fields make that indistinguishable from
    rounding), "fail".
    """
    deg_ok = (not req_deg) or rank >= DEGREE_RANK.get(req_deg, 0)
    exp, short = "ok", 0
    if req_mo:
        if mo_all >= req_mo:
            exp = "ok" if mo_ext >= req_mo else "employer_dependent"
        else:
            short = req_mo - mo_all
            exp = "near_miss" if short <= 2 else "fail"
    gaps = []
    if not deg_ok:
        gaps.append(f"{req_deg} not listed (highest on Appendix A: "
                    f"{RANK_NAME.get(rank, rank)})")
    if exp in ("near_miss", "fail"):
        gaps.append(f"missing {short} month{'s' if short != 1 else ''} of "
                    f"experience ({mo_all} listed vs {req_mo} required)")
    reqs = " + ".join(x for x in
                      (req_deg, f"{req_mo} months" if req_mo else None) if x)         or "no stated requirements"
    return {"label": label, "reqs": reqs, "deg_ok": deg_ok, "exp": exp,
            "gaps": gaps,
            "passes": deg_ok and exp in ("ok", "employer_dependent")}


def _pwd_skill_atoms(text):
    """Split PWD special-skills text on the PWD's OWN delimiters only:
    semicolons, newlines, numbered items, bullets.  NEVER split on
    'and'/'or'/commas inside one delimited item — those connectors carry
    legally distinct meanings (both required vs either suffices)."""
    if not text:
        return []
    t = re.sub(r"\s+", " ", str(text)).strip()
    parts = re.split(r";|\n|(?:(?<=^)|(?<=\s))\d{1,2}[.)]\s+|[\u2022\u25aa\u00b7]\s*", t)
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


_SKILL_STOP = {"the", "a", "an", "of", "in", "and", "or", "with", "to",
               "for", "on", "using", "including", "knowledge", "experience",
               "skills", "skill", "ability", "must", "have", "required",
               # duration/qualifier words: "24 months of Python" should
               # match on "python", not fail on "24"/"months"
               "month", "months", "mo", "mos", "year", "years", "yr", "yrs",
               "minimum", "least", "at"}


def _skill_evidenced(atom, hay):
    """Is a PWD skill atom plausibly evidenced in the 9089 skills text?
    Exact substring, or >=80% of its content tokens present.  Numeric
    tokens and duration words are excluded so a stated duration in the
    PWD item does not defeat the presence match (duration is verified
    separately by T3-025)."""
    a = atom.lower()
    if a and a in hay:
        return True
    toks = [w for w in re.findall(r"[a-z0-9+#.]+", a)
            if w not in _SKILL_STOP and w not in _WORD_NUMS
            and not w.replace(".", "").isdigit()]
    if not toks:
        return True
    return sum(1 for w in toks if w in hay) / len(toks) >= 0.8


# ===========================================================================
# T3-025 — per-skill DURATION verification (deterministic core)
#
# Design (Kellen, 8/18/2026):
#   1. Split the PWD special-skills text into atomic items (PWD's own
#      delimiters only) and parse a required duration out of each item
#      where one is stated ("24 months of Python").  Items with no stated
#      duration are presence-only and remain T3-024's job.
#   2. Build the Section D table: skill descriptions grouped by
#      employer/institution/school/training provider (appendix_A.skills).
#   3. Providers that are schools/training institutions are COURSEWORK
#      attestations: no Section E join, no duration math — the skill is
#      taken as attested (per ruling: "we don't need to compare section D
#      to section E" for coursework/training).
#   4. Employer providers join to Section E work-experience entries by
#      normalized employer name; each entry contributes its span months
#      prorated by hours worked: >=35 hrs/week is full time (1.0),
#      anything less contributes hours/40.
#   5. Sum per-skill prorated months and compare to the PWD duration,
#      with the same 2-month tolerance the form's month/year fields
#      justify elsewhere.
#
# --- AI INSERTION POINTS (fine-tuned qwen3-vl-8b, QLoRA on PWD/PERM) ---
# When the fine-tuned local model is ready, it upgrades three fuzzy steps
# while ALL the duration/proration/comparison math below stays as-is:
#   (A) PWD atomization + duration parsing: replace _pwd_skill_atoms()
#       + _atom_duration_months() with a model call returning
#       [{"text": ..., "months": ...}].  The applicant-eval PWD parser
#       (evl_compare.extract_pwd_requirements) shows the target schema
#       and the atomic-floor prompt rules (never split and/or).
#   (B) Skill-to-description matching: replace _skill_evidenced() calls
#       in the T3-025 loop with model-scored semantic matches.
#   (C) Provider-to-employer joining: replace the normalized-string join
#       with model matching for name variants ("IBM" vs "International
#       Business Machines").
# Follow the evl_compare pattern for the transport: model/URL from env
# (e.g. VERIFY_SKILL_MODEL / VERIFY_SKILL_URL) so the swap is an env
# change, not a code change.  Route LOCAL only — cost containment.
# ===========================================================================

_EDU_PROVIDER_RX = re.compile(
    r"universit|college|school|institut|academy|training|bootcamp|"
    r"certificat|course", re.I)

_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _atom_duration_months(atom):
    """Stated duration in months for one PWD skill item, or None.

    Handles "24 months", "2 years", "two years", "18 mos".  Deterministic
    regex — see AI insertion point (A) above for the model upgrade.
    """
    t = str(atom).lower()
    m = re.search(r"(\d+|" + "|".join(_WORD_NUMS) + r")\s*\+?\s*"
                  r"(years?|yrs?|months?|mos?)\b", t)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _WORD_NUMS[m.group(1)]
    return n * 12 if m.group(2).startswith(("y",)) else n


def _provider_kind(name):
    """'coursework' for schools/training providers, else 'employer'."""
    return "coursework" if name and _EDU_PROVIDER_RX.search(str(name))         else "employer"


def _norm_name(n):
    return re.sub(r"[^a-z0-9]", "", str(n or "").lower())


def _prorated_months(we, fd):
    """Span months for one Section E entry, prorated by hours/week.

    >=35 hrs = full time (1.0); below that contributes hours/40.
    Missing/unparseable hours are assumed full time (the field is often
    blank on full-time entries; part-time is the marked case).
    """
    s, e = _d(we.get("start")), _d(we.get("end"))
    if not s:
        return 0.0
    e = e or fd
    months = max(0, (e.year - s.year) * 12 + (e.month - s.month))
    try:
        hours = float(str(we.get("hours_per_week")).replace(",", ""))
    except (TypeError, ValueError):
        hours = 35.0
    ratio = 1.0 if hours >= 35 else max(0.0, hours) / 40.0
    return months * ratio



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

    # ---- worker qualification vs PWD requirement paths ---------------------
    # Redesigned 8/18: evaluate BOTH paths (F.b primary, F.c alternate) and
    # report per-path gaps.  Degree strings come from F.b.1.b / F.c.2.b (or
    # addenda) via the 9141 extractor; a PWD may state a degree with no
    # experience requirement, or rely on special skills instead (T3-024).
    req_p_deg = pwd.get("education_primary") or pwd.get("education_required")
    req_p_mo = pwd.get("experience_months_primary") or \
        pwd.get("experience_months_required")
    has_alt = pwd.get("alternate_reqs_accepted") == "Yes"
    req_a_deg = pwd.get("education_alternate") if has_alt else None
    req_a_mo = pwd.get("experience_months_alternate") if has_alt else None

    if req_p_deg or req_p_mo or req_a_deg or req_a_mo:
        rank, mo_all, mo_ext, n_edu, n_we, has_other = \
            _worker_profile_full(form, fd)
        paths = [_eval_path(rank, mo_all, mo_ext, req_p_deg, req_p_mo,
                            "primary (F.b)")]
        if req_a_deg or req_a_mo:
            paths.append(_eval_path(rank, mo_all, mo_ext, req_a_deg,
                                    req_a_mo, "alternate (F.c)"))

        passing = [p for p in paths if p["passes"]]
        if passing:
            if all(p["exp"] == "employer_dependent" for p in passing):
                which = passing[0]
                F(Flag(YELLOW, "T3-022", "AppA.E",
                       f"The foreign worker meets the {which['label']} "
                       f"requirements ({which['reqs']}) only when counting "
                       f"experience gained with the sponsoring employer "
                       f"({mo_all} months total, {mo_ext} months excluding "
                       f"the sponsor). Review the G.5 answer and 656.17(i)(3) "
                       f"— whether this experience is usable depends on "
                       f"where and in what position it was gained.",
                       "regulation", "20 CFR 656.17(i)(3)"))
        else:
            detail = "; ".join(
                f"on the {p['label']} path ({p['reqs']}): "
                + (", ".join(p["gaps"]) or "not met")
                for p in paths)
            empty_note = ("" if (n_edu or n_we) else
                          " Appendix A lists no education or work-experience "
                          "entries — confirm this is not an extraction gap.")
            near = [p for p in paths
                    if p["deg_ok"] and p["exp"] == "near_miss"]
            if near:
                F(Flag(YELLOW, "T3-021", "AppA.E",
                       f"The foreign worker is within 2 months of meeting "
                       f"the experience requirement: {detail}. The form's "
                       f"month/year date fields cannot resolve partial "
                       f"months — verify actual employment dates before "
                       f"treating this as a failure." + empty_note,
                       "regulation", "20 CFR 656.17(i)"))
            else:
                F(Flag(RED, "T3-020", "AppA",
                       f"The foreign worker does not facially meet either "
                       f"requirement path on the PWD: {detail}."
                       + empty_note,
                       "regulation",
                       "20 CFR 656.17(i); INA 212(a)(5)(A)"))

        if has_other and (req_p_deg or req_a_deg):
            F(Flag(YELLOW, "T3-023", "AppA.B",
                   "'Other Degree' is selected on Appendix A — commonly used "
                   "to record a foreign degree equivalent. Confirm what the "
                   "degree is and whether it satisfies the PWD requirement "
                   "(a deeper equivalency check belongs in the audit-pack "
                   "review).",
                   "data_check", "20 CFR 656.17(h)(4)(ii)"))

    # ---- PWD special skills vs Appendix A skills (T3-024) ------------------
    # A PWD may require special skills instead of (or alongside) employment
    # experience.  Each PWD-delimited skill item must be evidenced in the
    # 9089's Skills, Abilities, and Proficiencies section.
    sk_texts = [t for t in (pwd.get("special_skills_text"),
                            pwd.get("special_skills_text_alternate")) if t]
    if sk_texts:
        hay = re.sub(r"\s+", " ", " ".join(
            (e.get("description") or "")
            for e in (_get(form, "appendix_A.skills", []) or []))).lower()
        atoms, seen = [], set()
        for t in sk_texts:
            for a in _pwd_skill_atoms(t):
                if a.lower() not in seen:
                    seen.add(a.lower())
                    atoms.append(a)
        missing = [a for a in atoms if not _skill_evidenced(a, hay)]
        if missing:
            F(Flag(YELLOW, "T3-024", "AppA.skills",
                   "PWD special-skills items not evidenced in the 9089 "
                   "Skills, Abilities, and Proficiencies section: "
                   + "; ".join(f"'{m[:70]}'" for m in missing[:5])
                   + (f" (+{len(missing) - 5} more)"
                      if len(missing) > 5 else "")
                   + ". Confirm the worker's skills entries cover each PWD "
                     "item (connector words matter: 'and' requires both, "
                     "'or' either).",
                   "data_check", "20 CFR 656.17(i); 656.40"))

        # ---- T3-025 per-skill durations (see design comment above) -------
        dur_atoms = [(a, _atom_duration_months(a)) for a in atoms]
        dur_atoms = [(a, m) for a, m in dur_atoms if m]
        if dur_atoms:
            skills_d = _get(form, "appendix_A.skills", []) or []
            wes_e = _get(form, "appendix_A.work_experience", []) or []
            we_by_emp = {}
            for we in wes_e:
                we_by_emp.setdefault(
                    _norm_name(we.get("employer_name")), []).append(we)

            for atom, req_mo in dur_atoms:
                # Section D entries evidencing this skill.
                # (AI insertion point B: model-scored matching.)
                ev = [e for e in skills_d if _skill_evidenced(
                    atom, re.sub(r"\s+", " ",
                                 (e.get("description") or "").lower()))]
                if not ev:
                    continue          # presence gap already = T3-024
                if any(_provider_kind(e.get("provider")) == "coursework"
                       for e in ev):
                    continue          # coursework attestation: no E join
                # Employer providers -> Section E spans, hours-prorated.
                # (AI insertion point C: name-variant joining.)
                months, unjoined = 0.0, []
                for e in ev:
                    key = _norm_name(e.get("provider"))
                    entries = we_by_emp.get(key, [])
                    if not entries:
                        unjoined.append(e.get("provider"))
                        continue
                    for we in entries:
                        months += _prorated_months(we, fd)
                months = int(months)
                if not months and unjoined:
                    F(Flag(YELLOW, "T3-025", "AppA",
                           f"PWD requires {req_mo} months for "
                           f"'{atom[:60]}'; the skill is attested by "
                           + ", ".join(f"'{u}'" for u in unjoined[:3])
                           + " in Section D but no Section E work-"
                           f"experience entry matches that employer — "
                           f"duration cannot be computed.",
                           "data_check", "20 CFR 656.17(i)"))
                    continue
                if months >= req_mo:
                    continue
                short = req_mo - months
                near = short <= 2
                F(Flag(YELLOW, "T3-025", "AppA",
                       f"PWD requires {req_mo} months of "
                       f"'{atom[:60]}'; Section D/E support ~{months} "
                       f"months (hours-prorated: >=35 hrs/wk = full time, "
                       f"else hours/40)"
                       + (", ".join([""] + [f"'{u}' has no Section E "
                                            f"entry" for u in unjoined[:2]])
                          if unjoined else "")
                       + (f" — within 2 months; the form's month/year "
                          f"fields cannot resolve partial months, verify "
                          f"actual dates." if near else
                          f" — short by {short} months."),
                       "data_check", "20 CFR 656.17(i)"))


    # ---- travel consistency (T3-016) -----------------------------------
    # Travel disclosed on the PWD can live in either of two places on the
    # 9089: E.5 (additional conditions of employment) or, more commonly,
    # F.c.1 (other geographic areas of employment).
    #   RED    — PWD discloses travel but NEITHER 9089 location mentions it:
    #            the certified job omits a condition the wage was set on.
    #   YELLOW — both disclose travel but the language differs: confirm the
    #            descriptions describe the same travel obligation.
    trav_9141 = (pwd.get("travel_details") or "").strip()
    trav_fc1 = (_get(form, "F_worksite.other_geographic_areas") or "").strip()
    # E.5 is a general "additional conditions" field: only count it as
    # travel language when it actually talks about travel, otherwise a
    # bonus/per-diem note would masquerade as a travel disclosure.
    _e5_raw = (_get(form, "E_job_wage.wage_conditions") or "").strip()
    trav_e5 = _e5_raw if re.search(
        r"travel|relocat|client site|unanticipated|various (work )?"
        r"location|roving|itinerant", _e5_raw, re.I) else ""
    trav_9089 = trav_fc1 or trav_e5
    if trav_9141 and not trav_9089:
        F(Flag(RED, "T3-016", "F.c.1",
               f"PWD discloses travel ('{trav_9141[:60]}') but the 9089 "
               f"states no travel in either E.5 (additional conditions) or "
               f"F.c.1 (other geographic areas). The certified job must "
               f"reflect the conditions the wage was determined on.",
               "regulation", "20 CFR 656.40; 656.10(c)"))
    elif trav_9089 and not trav_9141:
        where = "F.c.1" if trav_fc1 else "E.5"
        F(Flag(RED, "T3-016", where,
               f"9089 {where} discloses travel ('{trav_9089[:60]}') but the "
               f"PWD contains no travel language — the prevailing wage was "
               f"not determined for a job requiring travel.",
               "regulation", "20 CFR 656.40; 656.10(c)"))
    elif trav_9141 and trav_9089 \
            and trav_9141.lower() != trav_9089.lower():
        where = "F.c.1" if trav_fc1 else "E.5"
        F(Flag(YELLOW, "T3-016", where,
               f"Travel language differs between the PWD "
               f"('{trav_9141[:60]}') and 9089 {where} "
               f"('{trav_9089[:60]}') — confirm both describe the same "
               f"travel obligation.",
               "data_check", "20 CFR 656.40"))

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

