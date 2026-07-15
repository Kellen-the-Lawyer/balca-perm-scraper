"""Dev-only: validate the wage-level engine against OFLC PW disclosure data.

Usage:
  PYTHONPATH=/Users/Dad/Documents/GitHub/Casebase venv/bin/python3 app/wage_level_validate.py \
      data/raw/oflc/PW/FY2025_Q4/PW_Disclosure_Data_FY2025_Q4.xlsx

Test population: PWD_WAGE_SOURCE = 'OEWS (All Industries)' with
PWD_OES_WAGE_LEVEL in I-IV (H-2B 'Level V' rows use a different scheme and
are excluded). Engine inputs mapped from the disclosure's requirement
columns; Step 4 special-skills points = 0 (attorney-judgment input).

RESULTS — FY2025_Q4 (194,140 scored determinations, run 2026-07-14):
  exact match 82.2% | within-one-level 95.6%
  overprediction (engine ABOVE DOL) only 1.8% — misses are almost all one
  level LOW, concentrated where DOL awarded a Step-4 special-skills point
  the engine leaves to the attorney.
  per-level recall: I 95.5% / II 77.8% / III 58.3% / IV 83.6%
  PERM 82.3% exact; H-1B 74.5%.
  Auto-awarding +1 whenever SPECIAL_SKILLS_REQUIREMENTS='Y' drops exact to
  50.6% (39.5% within Y-rows) — DOL usually gives NO point for listed
  skills, so the tool's default of 0 is empirically correct.

CALIBRATION EXPERIMENTS (2026-07-14, both rejected):
  - Alternate requirements: scoring max(primary, ALT_EDUCATION_LEVEL /
    ALT_EXPERIENCE_MONTHS) is worse across the board (77.0% exact,
    overprediction 9.4%; LIII rows WITH alternates fall 62.5% -> 12.4%).
    NPWC scores the PRIMARY requirement set.
  - Boundary-inclusive Step 2 (months == range start earns a low-end
    point): worse (73.5% exact; Level I recall 95.5% -> 73.5%). The
    exclusive boundary (points only ABOVE the range start) matches both
    the DOT SVP scale and DOL behavior.
  LIII miss anatomy: 77% Zone 4; dominant profiles are Bachelor's+24mo,
  Master's+0-24mo, Bachelor's+36mo — engine lands I/II, DOL adds one
  discretionary Step-4 point (73% of misses have the skills box checked).
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent))          # app/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # repo root
from routers.wage_level import (step2_experience, step3_education,   # noqa: E402
                                step5_supervisory, normalize_soc)

DB_URL = "postgresql://perm@127.0.0.1:5433/perm_decisions"
EDU = {"Bachelor's": "bachelors", "Master's": "masters",
       "Associate's": "associates", "High School/GED": "high_school",
       "Doctorate (PhD)": "doctorate",
       "Other degree (JD, MD, etc.)": "professional"}
LVL = {"Level I": 1, "Level II": 2, "Level III": 3, "Level IV": 4}
COLS = ["VISA_CLASS", "REQUIRED_EDUCATION_LEVEL", "REQUIRED_EXPERIENCE_MONTHS",
        "SUPERVISE_OTHER_EMP", "SPECIAL_SKILLS_REQUIREMENTS",
        "SPEC_REQ_FOREIGN_LANG", "PWD_SOC_CODE", "O_NET_CODE",
        "PWD_OES_WAGE_LEVEL", "PWD_WAGE_SOURCE"]


def main(xlsx):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT onetsoc_code, job_zone FROM onet_job_zones")
    zones = dict(cur.fetchall())
    conn.close()

    def zone_for(base, onet_raw):
        if isinstance(onet_raw, str) and onet_raw.strip() in zones:
            return zones[onet_raw.strip()]
        if f"{base}.00" in zones:
            return zones[f"{base}.00"]
        ext = [v for k, v in zones.items() if k.startswith(base + ".")]
        return max(ext) if ext else None

    print(f"loading {xlsx} …")
    df = pd.read_excel(xlsx, usecols=COLS)
    d = df[(df.PWD_WAGE_SOURCE == "OEWS (All Industries)") &
           (df.PWD_OES_WAGE_LEVEL.isin(LVL))].copy()
    d["actual"] = d.PWD_OES_WAGE_LEVEL.map(LVL)
    print(f"test set: {len(d)} OES determinations")

    preds = []
    for row in d.itertuples():
        base, _ = normalize_soc(str(row.PWD_SOC_CODE or ""))
        z = zone_for(base, row.O_NET_CODE) if base else None
        if not z:
            preds.append(None)
            continue
        months = 0 if pd.isna(row.REQUIRED_EXPERIENCE_MONTHS) \
            else int(row.REQUIRED_EXPERIENCE_MONTHS)
        p2, _ = step2_experience(z, months)
        p3, _, _ = step3_education(z, base,
                                   EDU.get(row.REQUIRED_EDUCATION_LEVEL, "none"))
        p4 = 1 if (isinstance(row.SPEC_REQ_FOREIGN_LANG, str)
                   and row.SPEC_REQ_FOREIGN_LANG.strip()) else 0
        p5, _ = step5_supervisory(base, None, row.SUPERVISE_OTHER_EMP == "Y")
        preds.append(min(4, 1 + p2 + p3 + p4 + p5))
    d["pred"] = preds
    m = d.dropna(subset=["pred"])
    print(f"scored {len(m)} (no-zone dropped: {len(d) - len(m)})")
    print(f"exact {(m.pred == m.actual).mean():.1%} | "
          f"within-1 {((m.pred - m.actual).abs() <= 1).mean():.1%} | "
          f"overpredicted {(m.pred > m.actual).mean():.1%}")
    print(pd.crosstab(m.actual, m.pred, rownames=["DOL"], colnames=["engine"]))
    for L in (1, 2, 3, 4):
        g = m[m.actual == L]
        print(f"  Level {L}: n={len(g):>6}  recall {(g.pred == L).mean():.1%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "data/raw/oflc/PW/FY2025_Q4/PW_Disclosure_Data_FY2025_Q4.xlsx")
