"""Profile denied PERM cases NOT caught by form-level rules — scopes Phase 4.

Layer 1: rerun the disclosure flag pass over all joined denied cases and
split flagged vs unflagged.
Layer 2: segment-lift analysis over ALL denied vs certified (full oflc_perm,
not just the oflc_pw join): which segments are over-represented among
denials that form-level checks cannot explain.

Output: printed digest + full report at /tmp/unflagged_denied_report.txt
"""
from __future__ import annotations
import os
from collections import Counter
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from .rules_tier3 import tier3
from .rules import RED
from .validate_disclosure import QUERY, row_to_dicts, zone_flags

load_dotenv(Path(__file__).parents[2] / ".env")
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")

SEGMENTS = [
    ("SOC major group", "LEFT(p.soc_code, 2)"),
    ("Occupation type", "p.occupation_type"),
    ("Employer state", "p.employer_state"),
    ("FW currently employed", "p.fw_currently_employed::text"),
    ("Layoff in occupation", "p.employer_layoff::text"),
    ("Fiscal year", "p.fiscal_year::text"),
]

SEG_SQL = """
WITH pop AS (
  SELECT {expr} AS seg,
         COUNT(*) FILTER (WHERE case_status ILIKE 'Denied%%') AS denied,
         COUNT(*) FILTER (WHERE case_status ILIKE 'Certified%%') AS certified
  FROM oflc_perm p
  WHERE {expr} IS NOT NULL
  GROUP BY 1
), tot AS (
  SELECT SUM(denied) AS d, SUM(certified) AS c FROM pop
)
SELECT seg, denied, certified,
       ROUND(denied::numeric / NULLIF(denied + certified, 0) * 100, 2) AS denial_rate,
       ROUND((denied::numeric / NULLIF((SELECT d FROM tot), 0)) /
             NULLIF(certified::numeric / NULLIF((SELECT c FROM tot), 0), 0), 2) AS lift
FROM pop
WHERE denied + certified >= {min_n}
ORDER BY lift DESC NULLS LAST
LIMIT {limit}
"""

REPEAT_SQL = """
SELECT {ent} AS entity, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE case_status ILIKE 'Denied%%') AS denied,
       ROUND(COUNT(*) FILTER (WHERE case_status ILIKE 'Denied%%')::numeric
             / COUNT(*) * 100, 1) AS denial_rate
FROM oflc_perm p
WHERE {ent} IS NOT NULL AND {ent} <> ''
GROUP BY 1
HAVING COUNT(*) >= 25
   AND COUNT(*) FILTER (WHERE case_status ILIKE 'Denied%%') >= 10
ORDER BY denial_rate DESC
LIMIT 15
"""


def main():
    conn = psycopg2.connect(DB_URL)
    out = []
    W = out.append

    # ---- Layer 1: flagged vs unflagged among joined denied ------------------
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY.format(status_clause="p.case_status ILIKE 'Denied%%'"))
        rows = cur.fetchall()
    flagged_ids, unflagged = set(), []
    for r in rows:
        form, pwd = row_to_dicts(r)
        reds = [f for f in tier3(form, pwd, r["received_date"])
                if f.level == RED] + \
               [x for x in zone_flags(r) if x[1] == RED]
        (flagged_ids.add(r["case_number"]) if reds else unflagged.append(r))
    W(f"LAYER 1 — joined denied cases: {len(rows)}")
    W(f"  form-level RED flagged: {len(flagged_ids)} "
      f"({len(flagged_ids)/len(rows)*100:.1f}%)")
    W(f"  UNFLAGGED (Phase-4 territory): {len(unflagged)} "
      f"({len(unflagged)/len(rows)*100:.1f}%)")

    # what do unflagged joined denials look like vs flagged (SOC groups)
    soc_unf = Counter((r["soc_code"] or "??")[:2] for r in unflagged)
    W("\n  Unflagged denied — top SOC major groups:")
    for soc, n in soc_unf.most_common(8):
        W(f"    SOC {soc}-xxxx: {n} ({n/len(unflagged)*100:.1f}%)")

    # ---- Layer 2: population segment lifts -----------------------------------
    W("\nLAYER 2 — full population (27K denied vs 623K certified)")
    with conn.cursor() as cur:
        for name, expr in SEGMENTS:
            cur.execute(SEG_SQL.format(expr=expr, min_n=200, limit=8))
            W(f"\n  {name} (lift = denied-share / certified-share):")
            for seg, d, c, rate, lift in cur.fetchall():
                W(f"    {str(seg)[:42]:<44} denied {d:>6}  "
                  f"denial-rate {rate:>6}%  lift {lift}")
        for label, ent in [("Employers", "p.employer_name"),
                           ("Law firms", "p.atty_law_firm")]:
            cur.execute(REPEAT_SQL.format(ent=ent))
            W(f"\n  {label} with highest denial rates (>=25 cases, >=10 denials):")
            for entity, total, denied, rate in cur.fetchall():
                W(f"    {str(entity)[:52]:<54} {denied}/{total} = {rate}%")
    conn.close()

    report = "\n".join(out)
    Path("/tmp/unflagged_denied_report.txt").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
