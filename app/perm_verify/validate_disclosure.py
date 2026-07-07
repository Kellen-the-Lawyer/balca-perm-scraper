"""Validate the PERM verification engine against OFLC disclosure data.

Joins oflc_perm (9089 outcomes) to oflc_pw (PWD determinations) on the PWD
number, maps each row into the engine's form/pwd dicts, runs the checks the
disclosure data can support, and scores flag rates against ground truth
(Certified* vs Denied).

Checks exercised here:
  T3-001  offered wage below governing (higher-of-two) PWD wage
  T3-005  PWD expired before the 9089 received_date
  T3-011  employer FEIN mismatch between 9089 and PWD
  T3-014  BLS area mismatch
  T2-014  non-professional recruitment on a Job Zone 4-5 occupation
  T2-015  Job Zone 3 borderline (YELLOW)

Not testable from disclosure data (no requirement/recruitment-date columns):
  Tier 1 completeness, Tier 2 timing windows, T4-007 SVP, T3-020/021.

Usage:
    venv/bin/python3 -m app.perm_verify.validate_disclosure [--certified-sample 20000]
"""
from __future__ import annotations
import argparse
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from .rules_tier3 import tier3
from .rules import RED, YELLOW

load_dotenv(Path(__file__).parents[2] / ".env")
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")

OCC_MAP = {
    "Professional occupation": "1a_professional",
    "Non-professional": "1b_nonprofessional",
    "College/University Teacher": "1c_college_university_teacher",
    "Schedule A": "1d_schedule_a_sheepherder",
    "None/Professional Athlete": "1e_professional_athlete",
}
PER_MAP = {"Annual": "Year", "Hourly": "Hour"}

QUERY = """
SELECT p.case_number, p.case_status, p.received_date,
       p.employer_fein AS p_fein, p.employer_name AS p_name,
       p.wage_from, p.wage_to, p.wage_per,
       p.worksite_bls_area AS p_bls, p.worksite_postal_code AS p_zip,
       p.occupation_type, p.pwd_number,
       w.employer_fein AS w_fein, w.employer_name AS w_name,
       w.pwd_wage_rate, w.pwd_unit, w.alt_pwd_wage_rate, w.alt_pwd_unit,
       w.pwd_wage_expiration_date, w.determination_date,
       w.bls_area AS w_bls, w.worksite_postal_code AS w_zip,
       w.soc_code, w.o_net_code,
       jz.job_zone
FROM oflc_perm p
JOIN oflc_pw w ON p.pwd_number = w.case_number
LEFT JOIN onet_job_zones jz
       ON jz.onetsoc_code = COALESCE(NULLIF(w.o_net_code, ''),
                                     w.soc_code || '.00')
WHERE p.received_date IS NOT NULL
  AND p.wage_from IS NOT NULL
  AND w.pwd_wage_rate IS NOT NULL
  AND ({status_clause})
"""


def row_to_dicts(r):
    per = PER_MAP.get(r["wage_per"], r["wage_per"]) or "Year"
    pwd_per = PER_MAP.get(r["pwd_unit"], r["pwd_unit"]) or "Year"
    alt_per = PER_MAP.get(r["alt_pwd_unit"], r["alt_pwd_unit"]) or pwd_per
    # tier3 annualizes min and alt with ONE per; disclosure has separate units.
    # Pre-annualize here and pass per="Year".
    from .rules_tier3 import ANNUALIZE
    pw_min = float(r["pwd_wage_rate"]) * ANNUALIZE.get(pwd_per, 1)
    pw_alt = (float(r["alt_pwd_wage_rate"]) * ANNUALIZE.get(alt_per, 1)) \
        if r["alt_pwd_wage_rate"] else None
    form = {
        "A_employer": {"fein": r["p_fein"], "legal_business_name": r["p_name"]},
        "E_job_wage": {
            "pwd_case_number": r["pwd_number"],
            "offered_wage_from": float(r["wage_from"]),
            "offered_wage_to": float(r["wage_to"]) if r["wage_to"] else None,
            "wage_per": per,
        },
        "F_worksite": {
            "msa_oes_area_title": r["p_bls"],
            "postal_code": r["p_zip"],
        },
        "H_recruitment": {
            "occupation_type": OCC_MAP.get(r["occupation_type"]),
        },
    }
    pwd = {
        "pwd_case_number": r["pwd_number"],
        "employer_fein": r["w_fein"], "employer_name": r["w_name"],
        "pw_minimum": pw_min, "pw_alternative": pw_alt, "pw_per": "Year",
        "validity_from": (r["determination_date"].strftime("%m/%d/%Y")
                          if r["determination_date"] else None),
        "validity_to": (r["pwd_wage_expiration_date"].strftime("%m/%d/%Y")
                        if r["pwd_wage_expiration_date"] else None),
        "bls_area": r["w_bls"], "worksite_postal": r["w_zip"],
    }
    return form, pwd


def zone_flags(r):
    """T2-014/T2-015 computed inline from the pre-joined job_zone."""
    out = []
    if r["job_zone"] is None:
        return out
    occ = OCC_MAP.get(r["occupation_type"])
    if occ == "1b_nonprofessional":
        if r["job_zone"] >= 4:
            out.append(("T2-014", RED))
        elif r["job_zone"] == 3:
            out.append(("T2-015", YELLOW))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--certified-sample", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    conn = psycopg2.connect(DB_URL)
    results = {}
    examples = defaultdict(list)
    for label, clause, sample in [
            ("Denied", "p.case_status ILIKE 'Denied%%'", None),
            ("Certified", "p.case_status ILIKE 'Certified%%'",
             args.certified_sample)]:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q = QUERY.format(status_clause=clause)
            if sample:
                q += f" ORDER BY random() LIMIT {sample}"
            cur.execute(q)
            rows = cur.fetchall()
        rule_counts = Counter()
        n_red = 0
        for r in rows:
            form, pwd = row_to_dicts(r)
            flags = [(f.rule_id, f.level, f.message)
                     for f in tier3(form, pwd, r["received_date"])]
            flags += [(rid, lvl, "") for rid, lvl in zone_flags(r)]
            reds = [f for f in flags if f[1] == RED]
            if reds:
                n_red += 1
                for rid, _, msg in reds:
                    rule_counts[rid] += 1
                    if len(examples[(label, rid)]) < 3:
                        examples[(label, rid)].append(
                            (r["case_number"], msg[:110]))
        results[label] = {"n": len(rows), "n_red": n_red,
                          "rules": rule_counts}
    conn.close()

    print(f"{'':<12}{'cases':>9}{'RED-flagged':>13}{'rate':>8}")
    for label, res in results.items():
        rate = res["n_red"] / res["n"] * 100 if res["n"] else 0
        print(f"{label:<12}{res['n']:>9}{res['n_red']:>13}{rate:>7.2f}%")
    print("\nPer-rule RED counts:")
    all_rules = sorted(set(results["Denied"]["rules"]) |
                       set(results["Certified"]["rules"]))
    for rid in all_rules:
        d = results["Denied"]["rules"].get(rid, 0)
        c = results["Certified"]["rules"].get(rid, 0)
        dn, cn = results["Denied"]["n"], results["Certified"]["n"]
        print(f"  {rid:<10} denied {d:>5} ({d/dn*100:5.2f}%)   "
              f"certified {c:>5} ({c/cn*100:5.2f}%)")
    print("\nExample flagged cases:")
    for (label, rid), exs in sorted(examples.items()):
        for cn_, msg in exs[:2]:
            print(f"  [{label}] {rid} {cn_}: {msg}")


if __name__ == "__main__":
    main()
