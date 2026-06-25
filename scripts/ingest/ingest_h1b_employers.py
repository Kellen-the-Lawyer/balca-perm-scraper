#!/usr/bin/env python3
"""
H-1B Approved Petitions by Employer — Custom Parser
=====================================================
Parses the USCIS "Approved H-1B Petitions by Employer" CSV files (FY2015-2017)
into a dedicated h1b_employers table.

These files have a master/detail layout the generic ingest can't handle:
  - Master row: tax#, employer name, total approved petitions, avg salary
  - Detail rows (FY2017): degree breakdown (Bachelor's/Master's/Doctorate/etc.)
    with counts per degree, employer fields blank (carry forward from master)

"D" = masked (<10, privacy). "H" = masked to prevent deducing a D.
Stored as NULL with a masked flag.

Produces a clean employer-year panel for analysis:
  approval volume by employer, salary levels, degree mix, year-over-year.

Usage:
    DATABASE_URL="postgresql://perm@127.0.0.1:5433/perm_decisions" \
      venv/bin/python3 scripts/ingest/ingest_h1b_employers.py [--reset] [--dry-run]
"""
import argparse, csv, logging, os, re, sys
from pathlib import Path

import psycopg2, psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL",
                        "postgresql://perm@127.0.0.1:5433/perm_decisions")

REPO = Path(__file__).resolve().parents[2]
FILES = {
    2015: REPO / "data/uscis_reports/csv/2015/approved-h-1b-petitions-by-employer-fy-2015.csv",
    2016: REPO / "data/uscis_reports/csv/2016/approved-h-1b-petitions-by-employer-fy-2016.csv",
    2017: REPO / "data/uscis_reports/csv/2017/approved-h-1b-petitions-by-employer-fy-2017.csv",
}

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS h1b_employers (
    id              BIGSERIAL PRIMARY KEY,
    fiscal_year     INTEGER NOT NULL,
    tax_id_last4    TEXT,                 -- last 4 of employer tax number
    employer_name   TEXT NOT NULL,
    total_petitions INTEGER,             -- NULL if masked
    total_masked    BOOLEAN DEFAULT FALSE,
    avg_salary      NUMERIC,             -- NULL if masked/blank
    -- degree breakdown (FY2017 has these; earlier years one row per employer)
    degree          TEXT,                 -- Bachelor's / Master's / Doctorate / etc, NULL = employer total
    degree_count    INTEGER,             -- NULL if masked
    degree_masked   BOOLEAN DEFAULT FALSE,
    stable_id       TEXT NOT NULL UNIQUE,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_h1b_emp_year   ON h1b_employers (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_h1b_emp_name   ON h1b_employers (employer_name);
CREATE INDEX IF NOT EXISTS idx_h1b_emp_total  ON h1b_employers (total_petitions);
CREATE INDEX IF NOT EXISTS idx_h1b_emp_degree ON h1b_employers (degree);
"""

def clean_num(v):
    """Parse ' 28,908 ' -> 28908. Returns (value, masked_bool)."""
    if v is None:
        return None, False
    s = v.strip().strip('"').strip()
    if s in ("", "-"):
        return None, False
    if s.upper() in ("D", "H"):
        return None, True
    s = s.replace(",", "").replace("$", "").strip()
    try:
        return int(float(s)), False
    except ValueError:
        return None, False

def clean_str(v):
    if v is None:
        return None
    s = v.strip().strip('"').strip()
    return s or None

def find_header_row(rows):
    """Return index of the row starting with 'Employer Tax Number'."""
    for i, row in enumerate(rows):
        if row and "employer tax number" in (row[0] or "").lower():
            return i
    return None

def parse_file(year, path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.reader(f))

    hdr = find_header_row(rows)
    if hdr is None:
        log.error(f"  FY{year}: no header row found")
        return []

    out = []
    cur_tax, cur_name = None, None
    seen_counter = {}

    for r in rows[hdr+1:]:
        if not r or all((c or "").strip() == "" for c in r):
            continue
        # pad short rows
        r = (r + [""] * 7)[:7]
        tax   = clean_str(r[0])
        name  = clean_str(r[1])
        total = r[2]
        salary= r[3]
        degree= clean_str(r[4])
        dcount= r[5]

        if name:  # master row: new employer
            cur_tax, cur_name = tax, name
            tot_val, tot_masked = clean_num(total)
            sal_val, _ = clean_num(salary)
            deg = degree
            dc_val, dc_masked = clean_num(dcount)
            # FY2015/16: degree is in col4 but one row per employer (the total row)
        else:
            # detail row: degree breakdown, carry employer forward
            if not cur_name:
                continue
            tot_val, tot_masked = None, False
            sal_val = None
            deg = degree
            dc_val, dc_masked = clean_num(dcount)

        if cur_name is None:
            continue

        # build a unique stable id (employer can repeat with same tax id + degree)
        key_base = f"{year}:{cur_tax}:{cur_name}:{deg}"
        n = seen_counter.get(key_base, 0)
        seen_counter[key_base] = n + 1
        stable = f"{key_base}:{n}"

        out.append({
            "fiscal_year": year,
            "tax_id_last4": cur_tax,
            "employer_name": cur_name,
            "total_petitions": tot_val if name else None,
            "total_masked": tot_masked if name else False,
            "avg_salary": sal_val if name else None,
            "degree": deg,
            "degree_count": dc_val,
            "degree_masked": dc_masked,
            "stable_id": stable,
        })

    log.info(f"  FY{year}: {len(out)} rows parsed")
    return out

UPSERT = """
INSERT INTO h1b_employers
  (fiscal_year, tax_id_last4, employer_name, total_petitions, total_masked,
   avg_salary, degree, degree_count, degree_masked, stable_id)
VALUES
  (%(fiscal_year)s, %(tax_id_last4)s, %(employer_name)s, %(total_petitions)s,
   %(total_masked)s, %(avg_salary)s, %(degree)s, %(degree_count)s,
   %(degree_masked)s, %(stable_id)s)
ON CONFLICT (stable_id) DO UPDATE SET
  total_petitions=EXCLUDED.total_petitions, avg_salary=EXCLUDED.avg_salary,
  degree_count=EXCLUDED.degree_count, ingested_at=NOW()
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
        cur.execute(CREATE_SQL)
    conn.commit()

    if args.reset:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE h1b_employers")
        conn.commit()
        log.info("Reset: truncated h1b_employers")

    total = 0
    for year, path in FILES.items():
        if not path.exists():
            log.warning(f"  FY{year}: file missing {path}"); continue
        rows = parse_file(year, path)
        if args.dry_run:
            for r in rows[:3]:
                log.info(f"    {r}")
            total += len(rows); continue
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, UPSERT, rows, page_size=1000)
        conn.commit()
        total += len(rows)

    conn.close()
    log.info("="*55)
    log.info(f"Done. {total:,} h1b_employer rows across {len(FILES)} years.")
    log.info("="*55)

if __name__ == "__main__":
    main()
