#!/usr/bin/env python3
"""
Backfill recruitment-step flags (used_radio_ad etc.) on existing oflc_perm rows.

Reads new-form PERM disclosure files and UPDATEs by (case_number, fiscal_year).
Legacy-form files (no RECR_OCC_* columns) are skipped; those rows stay NULL.

Usage:
    python3 backfill_perm_recruitment.py
    DATABASE_URL=... python3 backfill_perm_recruitment.py
"""

import os, sys
from pathlib import Path
import pandas as pd
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parent))
from ingest_oflc import (  # noqa: E402
    DATA_DIR, RECR_OCC_STEPS, coerce_str, fy_from_path, g, recr_flags,
)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions",
)

FLAG_COLS = list(RECR_OCC_STEPS.keys())

UPDATE_SQL = (
    "UPDATE oflc_perm SET "
    + ", ".join(f"{c} = %({c})s" for c in FLAG_COLS)
    + " WHERE case_number = %(case_number)s AND fiscal_year = %(fiscal_year)s"
)


def main():
    files = sorted((DATA_DIR / "PERM").rglob("PERM_Disclosure_Data*FY*.xlsx"))
    if not files:
        print(f"No PERM files under {DATA_DIR / 'PERM'}")
        sys.exit(1)

    conn = psycopg2.connect(DB_URL)
    total = 0
    for path in files:
        fy = fy_from_path(path)
        df = pd.read_excel(path, engine="openpyxl", dtype=str)
        df.columns = [c.strip().upper() for c in df.columns]
        cols = set(df.columns)
        if not any(f"{p}_FROM" in cols for p in RECR_OCC_STEPS.values()):
            print(f"  {path.name}: legacy form, skipped")
            continue

        rows = []
        for _, r in df.iterrows():
            cn = coerce_str(r.get("CASE_NUMBER"))
            if not cn:
                continue
            rec = recr_flags(r, cols)
            rec["case_number"] = cn
            rec["fiscal_year"] = fy
            rows.append(rec)

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, UPDATE_SQL, rows, page_size=2000)
        conn.commit()
        total += len(rows)
        print(f"  {path.name}: {len(rows):,} rows updated ({fy})")

    conn.close()
    print(f"Done — {total:,} rows backfilled")


if __name__ == "__main__":
    main()
