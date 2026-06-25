#!/usr/bin/env python3
"""
EB Inventory Custom Parser
============================
Parses the USCIS "Pending Applications for Employment-Based Preference
Categories" XLSX files into a dedicated eb_inventory table.

These files have a fixed layout that the generic ingest_uscis_stats.py
cannot handle because they use a wide pivot format where each column
is a priority date year, not a metric name.

Schema produced:
    eb_inventory (one row per country x category x visa_status x
                  priority_month x priority_year)

Each file covers a 10-year sliding window of priority date years.
"D" values (suppressed, <10 cases) are stored as NULL with is_suppressed=TRUE.

Usage:
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/ingest/ingest_eb_inventory.py
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/ingest/ingest_eb_inventory.py --dry-run
"""

import argparse
import hashlib
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    import pandas as pd
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "pandas", "openpyxl", "psycopg2-binary", "python-dotenv"])
    import pandas as pd
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_URL    = os.environ.get("DATABASE_URL",
                           "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS eb_inventory (
    id                  BIGSERIAL PRIMARY KEY,

    -- Source traceability
    report_id           INTEGER REFERENCES uscis_report_catalog(id) ON DELETE CASCADE,
    report_date         DATE NOT NULL,      -- "As of April 3, 2026"
    source_file         TEXT NOT NULL,      -- original filename

    -- Dimensions (the key that uniquely identifies each observation)
    country             TEXT NOT NULL,      -- Rest of the World / China / India / Mexico / Philippines
    preference_category TEXT NOT NULL,      -- EB1 / EB2 / EB3 / EW3 / EB4 / EB5 / CRW
    visa_status         TEXT NOT NULL,      -- Available / Awaiting Availability
    priority_month      TEXT NOT NULL,      -- January ... December / Prior Years
    priority_year       INTEGER,            -- 2006-2026, NULL for "Prior Years" column

    -- The value
    pending_count       INTEGER,            -- NULL if suppressed
    is_suppressed       BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE when USCIS reports "D" (<10)

    -- Dedup
    stable_id           TEXT NOT NULL UNIQUE,

    ingested_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eb_inv_report_date  ON eb_inventory (report_date);
CREATE INDEX IF NOT EXISTS idx_eb_inv_country      ON eb_inventory (country);
CREATE INDEX IF NOT EXISTS idx_eb_inv_category     ON eb_inventory (preference_category);
CREATE INDEX IF NOT EXISTS idx_eb_inv_status       ON eb_inventory (visa_status);
CREATE INDEX IF NOT EXISTS idx_eb_inv_py           ON eb_inventory (priority_year);
CREATE INDEX IF NOT EXISTS idx_eb_inv_compound     ON eb_inventory
    (country, preference_category, priority_year, priority_month);
"""

# ---------------------------------------------------------------------------
# Category normalization
# ---------------------------------------------------------------------------
CATEGORY_MAP = {
    "employment-based 1st preference category (eb1)": "EB1",
    "employment-based 2nd preference category (eb2)": "EB2",
    "employment-based 3rd preference category (eb3)": "EB3",
    "employment-based 4th preference category (eb4)": "EB4",
    "employment-based 5th preference category (eb5)": "EB5",
    "employment-based 3rd preference unskilled workers (ew3)": "EW3",
    "employment-based 4th preference certain religious workers (crw)": "CRW",
    # Fallback: extract the code from parentheses
}

def _normalize_category(raw: str) -> str:
    key = raw.strip().lower()
    if key in CATEGORY_MAP:
        return CATEGORY_MAP[key]
    # Extract code from parentheses e.g. "(EB2)"
    m = re.search(r"\((\w+)\)", raw)
    return m.group(1).upper() if m else raw.strip()

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(
    r"as\s+of\s+(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE
)
_MONTHS = {m[:3].lower(): i for i, m in enumerate([
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
], 1)}

def _parse_report_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        return date(int(m.group(3)), mon, int(m.group(2))) if mon else None
    return None

def _parse_year_from_header(col_header: str) -> int | None:
    """Extract year from 'Priority Date Year - 2026' or None for 'Prior Years'."""
    if "prior years" in col_header.lower():
        return None
    m = re.search(r"\b(20\d{2})\b", col_header)
    return int(m.group(1)) if m else None

# ---------------------------------------------------------------------------
# Stable ID
# ---------------------------------------------------------------------------
def _stable_id(report_id: int, country: str, category: str,
               status: str, month: str, year) -> str:
    key = f"{report_id}:{country}:{category}:{status}:{month}:{year}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
SKIP_SHEETS = {"how to read this report"}

def parse_eb_inventory_file(path: Path, report_id: int) -> list[dict]:
    """
    Parse one EB inventory XLSX into a list of eb_inventory row dicts.
    """
    xl = pd.ExcelFile(path, engine="openpyxl")
    rows_out = []
    report_date = None

    for sheet_name in xl.sheet_names:
        if sheet_name.lower().strip() in SKIP_SHEETS:
            continue

        df = xl.parse(sheet_name, header=None, dtype=str)

        # Extract report date from row 2 ("As of April 3, 2026")
        if report_date is None:
            for i in range(min(4, len(df))):
                cell = str(df.iloc[i, 0]) if pd.notna(df.iloc[i, 0]) else ""
                d = _parse_report_date(cell)
                if d:
                    report_date = d
                    break

        # Row 3 is always the header
        if len(df) < 5:
            continue
        headers = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[3]]

        # Identify the year columns (cols 4-14)
        # Col 0: Country Of Chargeability
        # Col 1: Preference Category
        # Col 2: Visa Status
        # Col 3: Priority Date Month
        # Col 4+: Priority Date Year - YYYY (or Prior Years)
        year_cols = {}  # col_index -> priority_year (int or None for Prior Years)
        for ci, h in enumerate(headers):
            if "priority date year" in h.lower():
                year_cols[ci] = _parse_year_from_header(h)

        if not year_cols:
            log.warning(f"  No year columns found in sheet '{sheet_name}'")
            continue

        # Parse data rows (row 4 onward)
        for row_idx in range(4, len(df)):
            row = df.iloc[row_idx]

            country  = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
            category = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else None
            status   = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else None
            month    = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else None

            # Skip empty or subtotal rows
            if not country or not category or not month:
                continue
            if country.lower() in ("country of chargeability", "nan", ""):
                continue

            cat_code = _normalize_category(category)

            # Emit one row per year column
            for ci, priority_year in year_cols.items():
                if ci >= len(row):
                    continue
                raw = str(row.iloc[ci]).strip() if pd.notna(row.iloc[ci]) else ""

                if raw in ("", "nan"):
                    continue

                is_suppressed = raw.upper() == "D"
                pending_count = None
                if not is_suppressed:
                    try:
                        pending_count = int(float(raw))
                    except (ValueError, TypeError):
                        continue

                sid = _stable_id(report_id, country, cat_code, status or "", month,
                                  priority_year)

                rows_out.append({
                    "report_id":           report_id,
                    "report_date":         report_date,
                    "source_file":         path.name,
                    "country":             country,
                    "preference_category": cat_code,
                    "visa_status":         status,
                    "priority_month":      month,
                    "priority_year":       priority_year,
                    "pending_count":       pending_count,
                    "is_suppressed":       is_suppressed,
                    "stable_id":           sid,
                })

    log.info(f"  {path.name}: {len(rows_out)} rows (report_date={report_date})")
    return rows_out

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
UPSERT_SQL = """
    INSERT INTO eb_inventory (
        report_id, report_date, source_file,
        country, preference_category, visa_status,
        priority_month, priority_year,
        pending_count, is_suppressed, stable_id, ingested_at
    ) VALUES (
        %(report_id)s, %(report_date)s, %(source_file)s,
        %(country)s, %(preference_category)s, %(visa_status)s,
        %(priority_month)s, %(priority_year)s,
        %(pending_count)s, %(is_suppressed)s, %(stable_id)s, NOW()
    )
    ON CONFLICT (stable_id) DO UPDATE SET
        pending_count  = EXCLUDED.pending_count,
        is_suppressed  = EXCLUDED.is_suppressed,
        ingested_at    = NOW()
"""

def get_eb_inventory_catalog(conn) -> list[dict]:
    """Fetch all EB inventory catalog entries with their local paths."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.id AS report_id, c.title, c.stable_id AS catalog_stable_id,
                   f.local_path
            FROM uscis_report_catalog c
            JOIN uscis_report_files f ON f.report_id = c.id
            WHERE c.title ILIKE '%pending application%employment-based%'
               OR c.stable_id ILIKE '%eb_inventory%'
            ORDER BY c.published_date DESC NULLS LAST
        """)
        return [dict(r) for r in cur.fetchall()]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)

    # Ensure table exists
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE)
    conn.commit()
    log.info("eb_inventory table ready.")

    # Get catalog entries for EB inventory files
    records = get_eb_inventory_catalog(conn)
    log.info(f"Found {len(records)} EB inventory files in catalog.")

    total_rows = 0
    failed = 0

    for i, rec in enumerate(records):
        if not rec["local_path"]:
            log.warning(f"  [{i+1}] No local path: {rec['title'][:60]}")
            failed += 1
            continue

        path = Path(rec["local_path"])
        if not path.exists():
            log.warning(f"  [{i+1}] File missing: {path}")
            failed += 1
            continue

        log.info(f"[{i+1}/{len(records)}] {rec['title'][:65]}")

        try:
            rows = parse_eb_inventory_file(path, rec["report_id"])
        except Exception as e:
            log.error(f"  Parse error: {e}")
            failed += 1
            continue

        if not rows:
            log.warning(f"  0 rows — skipping")
            continue

        if args.dry_run:
            log.info(f"  [DRY RUN] Would upsert {len(rows)} rows")
            total_rows += len(rows)
            continue

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows, page_size=500)
        conn.commit()
        total_rows += len(rows)

    conn.close()

    log.info("=" * 60)
    log.info(f"Done. {total_rows:,} eb_inventory rows from {len(records)-failed} files.")
    if failed:
        log.warning(f"  {failed} files skipped/failed.")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
