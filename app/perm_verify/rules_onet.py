"""O*NET Job Zone / SVP checks — T2-014 and T4-007.

These are the misrepresentation catchers: they compare what the form CLAIMS
against O*NET's classification of the occupation.

  T2-014  H.b marked non-professional (1b) but the occupation's Job Zone is
          4-5 (bachelor's-usual) -> professional recruitment steps were
          required. Zone 3 -> YELLOW borderline (T2-015).
  T4-007  G.9 answered "No" but PWD requirements (experience + training +
          education SVP-equivalent, per app/wage_level_data.py, on BOTH the
          F.b and F.c sets) exceed the Job Zone SVP ceiling -> RED.
  T4-007b Same excess with G.9 Yes -> YELLOW (Information Industries).
  T4-007c G.9 Yes but requirements are within the ceiling -> YELLOW.
          All skipped on a Level I PWD; Zone 5 never "exceeds".

SVP upper bounds in months by Job Zone (O*NET 30.2 svp_range):
  Zone 1-2: SVP < 6.0  -> <= 12 months
  Zone 3:   6.0-<7.0   -> <= 24 months
  Zone 4:   7.0-<8.0   -> <= 48 months
  Zone 5:   >= 8.0     -> unbounded

Data source: onet_job_zones / onet_job_zone_reference (loaded from
onet/db_30_2_mysql). Degrades gracefully (returns []) if DB unreachable
or the code is not found.
"""
from __future__ import annotations
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

from .rules import Flag, RED, YELLOW, _get

load_dotenv(Path(__file__).parents[1] / ".env")
load_dotenv(Path(__file__).parents[2] / ".env")

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")

# Shared with the Casebase SOC/wage-level tool (app/wage_level_data.py) so
# the verifier and the tool never disagree on the SVP math.
try:  # dev layout: app.perm_verify.rules_onet -> app.wage_level_data
    from app.wage_level_data import EDUCATION_SVP_MONTHS, ZONE_SVP_CEILING_MONTHS
except ImportError:  # deploy layout: api/ is top-level -> wage_level_data
    from wage_level_data import EDUCATION_SVP_MONTHS, ZONE_SVP_CEILING_MONTHS

SVP_UPPER_MONTHS = {1: 12, 2: 12, 3: 24, 4: 48, 5: None}   # T2-014/015 only

# 9141 degree strings -> wage_level_data keys
_DEGREE_KEY = {
    "none": "none", "high school/ged": "high_school",
    "associate's": "associates", "bachelor's": "bachelors",
    "master's": "masters", "doctorate": "doctorate", "other": "professional",
}


def _edu_svp(degree):
    if not degree:
        return 0
    return EDUCATION_SVP_MONTHS.get(_DEGREE_KEY.get(str(degree).lower().replace("\u2019", "'"), "none"), 0)


def _svp_paths(pwd):
    """[(label, degree, exp_mo, train_mo, combined_mo)] for F.b and, if
    alternate requirements are accepted, F.c."""
    out = []
    p_deg = pwd.get("education_primary") or pwd.get("education_required")
    p_exp = pwd.get("experience_months_primary") or pwd.get("experience_months_required") or 0
    p_trn = pwd.get("training_months_primary") or 0
    out.append(("F.b", p_deg, p_exp, p_trn, p_exp + p_trn + _edu_svp(p_deg)))
    if pwd.get("alternate_reqs_accepted") == "Yes":
        a_deg = pwd.get("education_alternate")
        a_exp = pwd.get("experience_months_alternate") or 0
        a_trn = pwd.get("training_months_alternate") or 0
        out.append(("F.c", a_deg, a_exp, a_trn, a_exp + a_trn + _edu_svp(a_deg)))
    return out


def _lookup_zone(conn, onet_code, soc_code):
    candidates = []
    if onet_code:
        candidates.append(onet_code)
    if soc_code:
        candidates.append(f"{soc_code}.00")
    with conn.cursor() as cur:
        for c in candidates:
            cur.execute("SELECT job_zone FROM onet_job_zones WHERE onetsoc_code=%s", (c,))
            r = cur.fetchone()
            if r:
                return int(r[0]), c
        if soc_code:
            cur.execute("SELECT MAX(job_zone) FROM onet_job_zones "
                        "WHERE onetsoc_code LIKE %s", (f"{soc_code}.%",))
            r = cur.fetchone()
            if r and r[0] is not None:
                return int(r[0]), f"{soc_code}.* (max across extensions)"
    return None, None


def onet_checks(form, pwd):
    flags = []
    F = flags.append
    soc = (pwd or {}).get("soc_code")
    onet = (pwd or {}).get("onet_code")
    if not (soc or onet):
        return flags
    try:
        conn = psycopg2.connect(DB_URL)
    except Exception:
        return flags
    try:
        zone, matched = _lookup_zone(conn, onet, soc)
    finally:
        conn.close()
    if zone is None:
        return flags

    occ_type = _get(form, "H_recruitment.occupation_type")
    if occ_type == "1b_nonprofessional":
        if zone >= 4:
            F(Flag(RED, "T2-014", "H.b",
                   f"Recruitment conducted as NON-professional (H.b.1b) but "
                   f"{matched} is O*NET Job Zone {zone} (bachelor's-usual "
                   f"occupation). Professional recruitment steps under "
                   f"656.17(e)(1) were required.",
                   "regulation", "20 CFR 656.17(e); 656.20; O*NET Job Zones"))
        elif zone == 3:
            F(Flag(YELLOW, "T2-015", "H.b",
                   f"Non-professional recruitment used and {matched} is Job "
                   f"Zone 3 — borderline professional/non-professional. "
                   f"Confirm bachelor's is not the usual requirement.",
                   "regulation", "20 CFR 656.20; O*NET Job Zones"))

    # ---- G.9: do the job requirements exceed the occupation's SVP? -------
    # Redesigned 9/10 (Kellen): SVP math shared with the SOC tool —
    # experience + training + education-equivalent months vs the Job Zone
    # ceiling, evaluated on BOTH the F.b and F.c requirement sets.  Skipped
    # when the NPWC issued a Level I wage (DOL already found the
    # requirements at entry level).  Zone 5 is open-ended (SVP 8+), so
    # nothing is flagged as exceeding it — same stance as the SOC tool.
    # T4-006 (bare "G.9 = Yes" YELLOW) was retired into this rule.
    level = str((pwd or {}).get("pw_oews_level") or "").strip().upper()
    if level in ("I", "1"):
        return flags
    g9 = str(_get(form, "G_job_info.exceeds_svp"))
    ceiling = ZONE_SVP_CEILING_MONTHS.get(zone)
    paths = _svp_paths(pwd or {})
    over = [p for p in paths if zone != 5 and ceiling and p[4] > ceiling]

    def _narr(p):
        label, deg, exp, trn, tot = p
        parts = [f"{exp} mo experience"]
        if trn:
            parts.append(f"{trn} mo training")
        parts.append(f"{_edu_svp(deg)} mo for {deg or 'no degree'}")
        return f"{label}: " + " + ".join(parts) + f" = {tot} mo"

    detail = "; ".join(_narr(p) for p in paths)
    if over:
        if g9 in ("No", "N/A", "None"):
            F(Flag(RED, "T4-007", "G.9",
                   f"G.9 answered '{g9}' but the PWD requirements exceed the "
                   f"Job Zone {zone} SVP ceiling of {ceiling} months for "
                   f"{matched} ({detail}). Answer G.9 'Yes' with an Appendix "
                   f"C business-necessity justification, or reduce the "
                   f"requirements. (Education-to-SVP conversion: bachelor's "
                   f"= 24 mo, master's = 48 mo, doctorate/professional = "
                   f"84 mo — a practitioner convention, not regulatory "
                   f"text.)",
                   "regulation",
                   "20 CFR 656.17(h)(1); ETA-9089 Instructions §G.9; "
                   "O*NET Job Zone SVP range"))
        else:
            F(Flag(YELLOW, "T4-007b", "G.9",
                   f"G.9 is Yes and the PWD requirements exceed the Job Zone "
                   f"{zone} SVP ceiling of {ceiling} months for {matched} "
                   f"({detail}) — the Appendix C business-necessity statement "
                   f"must meet the Information Industries standard.",
                   "balca",
                   "Information Industries, 1988-INA-82 (en banc); "
                   "20 CFR 656.17(h)(1)"))
    elif g9 == "Yes":
        F(Flag(YELLOW, "T4-007c", "G.9",
               f"G.9 is Yes but the PWD requirements are within the Job Zone "
               f"{zone} SVP " + (f"ceiling of {ceiling} months" if zone != 5
                                 else "range (Zone 5 is open-ended)") +
               f" for {matched} ({detail}). Confirm G.9 needs to be Yes — "
               f"it invites business-necessity scrutiny the employer may "
               f"not owe.",
               "regulation", "20 CFR 656.17(h)(1); ETA-9089 Instructions §G.9"))
    return flags
