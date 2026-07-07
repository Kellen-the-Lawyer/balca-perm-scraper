"""O*NET Job Zone / SVP checks — T2-014 and T4-007.

These are the misrepresentation catchers: they compare what the form CLAIMS
against O*NET's classification of the occupation.

  T2-014  H.b marked non-professional (1b) but the occupation's Job Zone is
          4-5 (bachelor's-usual) -> professional recruitment steps were
          required. Zone 3 -> YELLOW borderline (T2-015).
  T4-007  G.9 answered "No" (requirements do NOT exceed SVP) but the PWD's
          required experience months alone exceed the Job Zone's SVP upper
          bound. Conservative by design: education is NOT converted to SVP
          time (that conversion is contested); if experience alone busts the
          entire SVP range, the requirements exceed SVP a fortiori.

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

SVP_UPPER_MONTHS = {1: 12, 2: 12, 3: 24, 4: 48, 5: None}


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

    req_months = (pwd or {}).get("experience_months_required")
    g9 = str(_get(form, "G_job_info.exceeds_svp"))
    bound = SVP_UPPER_MONTHS.get(zone)
    if req_months and bound is not None and req_months > bound:
        if g9 in ("No", "N/A", "None"):
            F(Flag(RED, "T4-007", "G.9",
                   f"G.9 answered '{g9}' but required experience "
                   f"({req_months} months) alone exceeds the Job Zone {zone} "
                   f"SVP ceiling ({bound} months) for {matched} — before even "
                   f"counting the education requirement. Answer G.9 'Yes' with "
                   f"an Appendix C business-necessity justification, or reduce "
                   f"the requirements.",
                   "regulation",
                   "20 CFR 656.17(h)(1); ETA-9089 Instructions §G.9; "
                   "O*NET Job Zone SVP range"))
        else:
            F(Flag(YELLOW, "T4-007b", "G.9",
                   f"Requirements exceed Job Zone {zone} SVP ceiling "
                   f"({req_months} > {bound} months) and G.9 is Yes — ensure "
                   f"the Appendix C business-necessity statement meets the "
                   f"Information Industries standard.",
                   "balca",
                   "Information Industries, 1988-INA-82 (en banc); "
                   "20 CFR 656.17(h)(1)"))
    return flags
