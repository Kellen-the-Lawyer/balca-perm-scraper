#!/usr/bin/env python3
"""
USCIS Statistical Data Ingest Pipeline
=========================================
Phase 3: Parses downloaded XLSX/CSV files and loads rows into uscis_stat_rows.

Strategy: best-effort normalization via fuzzy column header matching.
  - Detect sheets, skip cover/legend/notes
  - Find header row (first row with 2+ non-numeric string cells)
  - Map columns to canonical fields by keyword matching
  - Emit one uscis_stat_rows record per (data row x metric column)
  - Store raw text_value alongside numeric_value so nothing is lost

Usage:
    python scripts/ingest/ingest_uscis_stats.py [--dry-run] [--limit N]
    python scripts/ingest/ingest_uscis_stats.py --stable-id document/reports/foo_v1
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

DB_URL = os.environ.get("DATABASE_URL",
                        "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column name -> canonical field mapping
# (keyword list, field_name, unit)  -- first match wins, specific first
# ---------------------------------------------------------------------------
COLUMN_MAP = [
    # Period / time
    (["fiscal year","fy"],                    "fiscal_year",         ""),
    (["quarter","qtr"],                       "fiscal_quarter",      ""),
    (["month"],                               "period_label",        ""),
    (["period","reporting period"],           "period_label",        ""),
    # Geography
    (["country of birth","nativity","country"], "country_of_birth",  ""),
    (["state"],                               "state_code",          ""),
    (["office","field office","service center"], "uscis_office",     ""),
    # Case attributes
    (["form type","form number","form"],      "form_type",           ""),
    (["case status","decision","status"],     "case_status",         ""),
    (["category","eligibility","class of admission","preference"], "eligibility_category", ""),
    (["naics"],                               "naics_code",          ""),
    (["soc","occupation code"],               "soc_code",            ""),
    # Metric columns -- specific first
    (["received","filed","receipt"],          "Received",            "count"),
    (["approved","granted"],                  "Approved",            "count"),
    (["denied","rejected"],                   "Denied",              "count"),
    (["withdrawn"],                           "Withdrawn",           "count"),
    (["pending","backlog"],                   "Pending",             "count"),
    (["rfe issued","rfe sent"],               "RFE Issued",          "count"),
    (["rfe response"],                        "RFE Response",        "count"),
    (["completed","adjudicated"],             "Completed",           "count"),
    (["processing time","median days","average days"], "Processing Time", "days"),
    (["percent","pct"],                       "Percent",             "percent"),
    (["total"],                               "Total",               "count"),
    (["count","number","qty"],                "Count",               "count"),
]

DIMENSION_FIELDS = {
    "fiscal_year","fiscal_quarter","period_label",
    "country_of_birth","state_code","uscis_office",
    "form_type","case_status","eligibility_category",
    "naics_code","soc_code",
}

SKIP_SHEET_RE = re.compile(
    r"^(cover|note|legend|glossary|readme|table of content|about|instructions?|disclaimer)",
    re.IGNORECASE)

_FY_RE = re.compile(r"(?:fy|fiscal year)\s*(\d{4})", re.IGNORECASE)
_QR_RE = re.compile(r"q(\d)|quarter\s*(\d)",         re.IGNORECASE)
_YR_RE = re.compile(r"\b(20\d{2})\b")

_MONTHS = {m[:3]: i for i, m in enumerate(
    ["january","february","march","april","may","june",
     "july","august","september","october","november","december"], 1)}


def _parse_period(raw):
    """Returns (fiscal_year, fiscal_quarter, period_start, period_end)."""
    if not raw: return None, None, None, None
    s = str(raw).strip()
    fy = fq = None
    m = _FY_RE.search(s);  
    if m: fy = int(m.group(1))
    m = _QR_RE.search(s); 
    if m: fq = int(m.group(1) or m.group(2))
    if not fy:
        m = _YR_RE.search(s)
        if m: fy = int(m.group(1))
    p_start = p_end = None
    if fy and fq:
        qs = {1: date(fy-1,10,1), 2: date(fy,1,1), 3: date(fy,4,1), 4: date(fy,7,1)}
        qe = {1: date(fy-1,12,31),2: date(fy,3,31),3: date(fy,6,30),4: date(fy,9,30)}
        p_start = qs.get(fq); p_end = qe.get(fq)
    return fy, fq, p_start, p_end

def _find_header(df: pd.DataFrame) -> int:
    for i, row in df.reset_index(drop=True).iterrows():
        cells = [str(v).strip() for v in row if pd.notna(v) and str(v).strip()]
        if len(cells) >= 2 and sum(1 for v in cells if re.match(r"^[\d,.]+$", v)) == 0:
            return int(i)
    return 0

def _map_cols(headers: list[str]) -> dict:
    mapping = {}
    for ci, h in enumerate(headers):
        hl = str(h).lower().strip()
        for (kws, field, unit) in COLUMN_MAP:
            if any(kw in hl for kw in kws):
                mapping[ci] = (field, unit)
                break
    return mapping

def _to_num(val):
    if pd.isna(val): return None
    s = re.sub(r"[,$%\s]", "", str(val)).strip()
    try: return float(s)
    except: return None

def _unit(raw_str, col_unit):
    if col_unit: return col_unit
    if "%" in str(raw_str): return "percent"
    if "$" in str(raw_str): return "dollars"
    return "count"

def _sid(report_id, sheet, row_idx, metric):
    return hashlib.sha256(f"{report_id}:{sheet}:{row_idx}:{metric}".encode()).hexdigest()[:32]


def process_sheet(report_id, sheet_name, df_raw, catalog) -> list[dict]:
    if df_raw.empty: return []
    df = df_raw.reset_index(drop=True)
    hdr = _find_header(df)
    headers = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[hdr]]
    col_map = _map_cols(headers)
    if not col_map:
        log.debug(f"    '{sheet_name}': no mapping found")
        return []
    data = df.iloc[hdr+1:].reset_index(drop=True)
    if data.empty: return []

    dim_cols  = {ci: f for ci,(f,u) in col_map.items() if f in DIMENSION_FIELDS}
    metr_cols = {ci: (f,u) for ci,(f,u) in col_map.items() if f not in DIMENSION_FIELDS}
    rows_out  = []

    for row_idx, row in data.iterrows():
        vals = [row.iloc[ci] if ci < len(row) else None for ci in range(len(headers))]
        if all(pd.isna(v) or str(v).strip() in ("","-","N/A","n/a") for v in vals):
            continue
        dims = {}
        for ci, field in dim_cols.items():
            if ci < len(row):
                raw = row.iloc[ci]
                dims[field] = str(raw).strip() if pd.notna(raw) else None

        fy = dims.get("fiscal_year")
        fq = dims.get("fiscal_quarter")
        try: fy = int(float(fy)) if fy else None
        except: fy = None
        try: fq = int(float(fq)) if fq else None
        except: fq = None
        fy = fy or catalog.get("fiscal_year")
        fq = fq or catalog.get("quarter")
        _, _, p_start, p_end = _parse_period(
            dims.get("period_label") or (f"FY{fy} Q{fq}" if fy and fq else ""))

        for ci, (metric_name, col_unit) in metr_cols.items():
            if ci >= len(row): continue
            raw_val = row.iloc[ci]
            if pd.isna(raw_val) or str(raw_val).strip() in ("","-","N/A","n/a"): continue
            raw_str = str(raw_val).strip()
            rows_out.append({
                "report_id":          report_id,
                "sheet_name":         sheet_name,
                "row_index":          int(row_idx),
                "metric_name":        metric_name,
                "metric_category":    dims.get("eligibility_category"),
                "fiscal_year":        fy,
                "fiscal_quarter":     fq,
                "period_label":       dims.get("period_label"),
                "period_start":       p_start,
                "period_end":         p_end,
                "country_of_birth":   dims.get("country_of_birth"),
                "state_code":         dims.get("state_code"),
                "uscis_office":       dims.get("uscis_office"),
                "form_type":          dims.get("form_type") or catalog.get("form_type"),
                "case_status":        dims.get("case_status"),
                "eligibility_category": dims.get("eligibility_category"),
                "naics_code":         dims.get("naics_code"),
                "soc_code":           dims.get("soc_code"),
                "numeric_value":      _to_num(raw_val),
                "text_value":         raw_str,
                "unit":               _unit(raw_str, col_unit),
                "stable_id":          _sid(report_id, sheet_name, int(row_idx), metric_name),
            })
    return rows_out

def process_file(local_path, report_id, catalog) -> list[dict]:
    path = Path(local_path)
    if not path.exists(): return []
    ext = path.suffix.lower()
    all_rows = []
    try:
        if ext == ".csv":
            df = pd.read_csv(path, dtype=str, na_values=["","N/A","-"])
            all_rows.extend(process_sheet(report_id, "csv", df, catalog))
        elif ext in (".xlsx",".xls",".xlsm"):
            xl = pd.ExcelFile(path, engine="openpyxl")
            for sname in xl.sheet_names:
                if SKIP_SHEET_RE.match(sname.strip()):
                    log.debug(f"  Skip sheet: {sname}"); continue
                try:
                    df_raw = xl.parse(sname, header=None, dtype=str, na_values=["","N/A","-"])
                    rows = process_sheet(report_id, sname, df_raw, catalog)
                    log.info(f"  Sheet '{sname}': {len(rows)} rows")
                    all_rows.extend(rows)
                except Exception as e:
                    log.warning(f"  Sheet '{sname}' error: {e}")
    except Exception as e:
        log.error(f"  File error {path.name}: {e}")
    return all_rows

PENDING_SQL = """
    SELECT f.id AS file_id, f.report_id, f.local_path,
           c.stable_id, c.title, c.file_type, c.fiscal_year, c.quarter, c.form_type
    FROM uscis_report_files f
    JOIN uscis_report_catalog c ON c.id = f.report_id
    WHERE f.download_status='done' AND f.ingested_at IS NULL AND f.local_path IS NOT NULL
      AND (%(stable_id)s IS NULL OR c.stable_id=%(stable_id)s)
    ORDER BY c.published_date DESC NULLS LAST
    LIMIT %(limit)s
"""

UPSERT_SQL = """
    INSERT INTO uscis_stat_rows (
        report_id,sheet_name,row_index,metric_name,metric_category,
        fiscal_year,fiscal_quarter,period_label,period_start,period_end,
        country_of_birth,state_code,uscis_office,form_type,case_status,
        eligibility_category,naics_code,soc_code,
        numeric_value,text_value,unit,stable_id,ingested_at
    ) VALUES (
        %(report_id)s,%(sheet_name)s,%(row_index)s,%(metric_name)s,%(metric_category)s,
        %(fiscal_year)s,%(fiscal_quarter)s,%(period_label)s,%(period_start)s,%(period_end)s,
        %(country_of_birth)s,%(state_code)s,%(uscis_office)s,%(form_type)s,%(case_status)s,
        %(eligibility_category)s,%(naics_code)s,%(soc_code)s,
        %(numeric_value)s,%(text_value)s,%(unit)s,%(stable_id)s,NOW()
    )
    ON CONFLICT (stable_id) DO UPDATE SET
        numeric_value=EXCLUDED.numeric_value,
        text_value=EXCLUDED.text_value,
        ingested_at=NOW()
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stable-id")
    ap.add_argument("--limit", type=int, default=9999)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(PENDING_SQL, {"stable_id": args.stable_id, "limit": args.limit})
        pending = [dict(r) for r in cur.fetchall()]

    log.info("="*60)
    log.info(f"USCIS Stat Rows Ingest — {len(pending)} files to process")
    log.info("="*60)

    total = 0
    for i, rec in enumerate(pending):
        log.info(f"[{i+1}/{len(pending)}] {rec['title'][:60]}")
        rows = process_file(rec["local_path"], rec["report_id"], rec)
        log.info(f"  {len(rows)} rows extracted")
        if rows and not args.dry_run:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows, page_size=500)
            conn.commit()
        if not args.dry_run:
            with conn.cursor() as cur:
                cur.execute("UPDATE uscis_report_files SET ingested_at=NOW() WHERE id=%(fid)s",
                            {"fid": rec["file_id"]})
            conn.commit()
        total += len(rows)

    conn.close()
    log.info("="*60)
    log.info(f"Done. {total:,} stat rows ingested from {len(pending)} files.")
    log.info("="*60)

if __name__ == "__main__":
    main()
