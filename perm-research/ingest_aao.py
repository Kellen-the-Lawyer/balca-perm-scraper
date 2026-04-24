#!/usr/bin/env python3
"""
Casebase — AAO Decisions Ingestion Pipeline
============================================

Usage:
    python ingest_aao.py [--workers 6] [--limit 500] [--index-only]

Strategy:
  - Reads metadata directly from aao_index.csv (no header parsing needed)
  - Extracts full text from PDFs in parallel
  - --index-only: insert metadata without text extraction (fast first pass)
"""

import argparse
import asyncio
import csv
import logging
import os
import re
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import asyncpg
import pdfplumber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

AAO_BASE   = "/Users/Dad/aao_decisions"
INDEX_CSV  = "/Users/Dad/aao_decisions/aao_index.csv"

OUTCOME_PATTERNS = [
    (re.compile(r"\bSUSTAINED\b",  re.IGNORECASE), "Sustained"),
    (re.compile(r"\bDISMISSED\b",  re.IGNORECASE), "Dismissed"),
    (re.compile(r"\bREMANDED\b",   re.IGNORECASE), "Remanded"),
    (re.compile(r"\bWITHDRAWN\b",  re.IGNORECASE), "Withdrawn"),
]

def parse_date(s):
    if not s:
        return None
    for fmt in ["%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None

def extract_pdf(args):
    """Extract text from one PDF. Runs in subprocess pool."""
    filename, pdf_path, title, date_str, form_type, regulation = args
    result = {
        "filename": filename,
        "pdf_path": pdf_path,
        "title": title,
        "decision_date": date_str,
        "form_type": form_type,
        "regulation": regulation,
        "full_text": "",
        "outcome": None,
        "parse_errors": None,
    }
    try:
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        result["full_text"] = "\n\n".join(pages)
    except Exception as e:
        result["parse_errors"] = str(e)
        return result

    tail = result["full_text"][-2000:] if len(result["full_text"]) > 2000 else result["full_text"]
    for pattern, label in OUTCOME_PATTERNS:
        if pattern.search(tail):
            result["outcome"] = label
            break

    return result

async def upsert(conn, data):
    await conn.execute("""
        INSERT INTO aao_decisions
          (filename, pdf_path, title, decision_date, form_type, regulation,
           outcome, full_text, text_extracted, parse_errors)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (filename) DO UPDATE SET
          full_text      = EXCLUDED.full_text,
          outcome        = EXCLUDED.outcome,
          text_extracted = EXCLUDED.text_extracted,
          parse_errors   = EXCLUDED.parse_errors
    """,
        data["filename"], data["pdf_path"], data["title"],
        parse_date(data["decision_date"]), data["form_type"], data["regulation"],
        data["outcome"], data["full_text"], True, data["parse_errors"],
    )

async def upsert_index_only(conn, row):
    """Insert metadata row without text — for a fast first pass."""
    await conn.execute("""
        INSERT INTO aao_decisions
          (filename, pdf_path, title, decision_date, form_type, regulation, full_text, text_extracted)
        VALUES ($1,$2,$3,$4,$5,$6,'',$7)
        ON CONFLICT (filename) DO NOTHING
    """,
        row["filename"], row["pdf_path"], row["title"],
        parse_date(row["date"]), row["form"], row["regulation"], False,
    )

async def main(db_url, workers, limit, index_only):
    conn = await asyncpg.connect(db_url)
    log.info("Connected to database")

    # Read index CSV
    rows = []
    with open(INDEX_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        seen = set()
        for row in reader:
            fname = row.get("pdf_filename", "").strip()
            regulation = row.get("regulation", "").strip()
            if not fname or fname in seen:
                continue
            seen.add(fname)

            # Find actual file path
            reg_folder = os.path.join(AAO_BASE, regulation)
            pdf_path = os.path.join(reg_folder, fname)
            if not os.path.exists(pdf_path):
                # Search all folders
                found = None
                for folder in os.listdir(AAO_BASE):
                    candidate = os.path.join(AAO_BASE, folder, fname)
                    if os.path.exists(candidate):
                        found = candidate
                        break
                if not found:
                    continue
                pdf_path = found

            rows.append({
                "filename": fname,
                "pdf_path": pdf_path,
                "title": row.get("title", "").strip(),
                "date": row.get("date", "").strip(),
                "form": row.get("form", "").strip(),
                "regulation": regulation,
            })

    if limit:
        rows = rows[:limit]
    log.info(f"Found {len(rows)} decisions to process")

    if index_only:
        log.info("Index-only mode: inserting metadata without text extraction")
        for i, row in enumerate(rows, 1):
            await upsert_index_only(conn, row)
            if i % 5000 == 0:
                log.info(f"  Metadata inserted: {i}/{len(rows)}")
        log.info(f"Index-only complete: {len(rows)} rows")
        await conn.close()
        return

    # Full extraction
    processed = errors = 0
    loop = asyncio.get_running_loop()
    extract_args = [
        (r["filename"], r["pdf_path"], r["title"], r["date"], r["form"], r["regulation"])
        for r in rows
    ]

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [loop.run_in_executor(executor, extract_pdf, a) for a in extract_args]
        for i, future in enumerate(asyncio.as_completed(futures), 1):
            try:
                data = await future
            except Exception as e:
                log.error(f"Extraction failed: {e}")
                errors += 1
                continue
            try:
                await upsert(conn, data)
                processed += 1
            except Exception as e:
                log.error(f"DB error for {data.get('filename')}: {e}")
                errors += 1
            if i % 1000 == 0:
                log.info(f"  Progress: {i}/{len(rows)} | ok={processed} err={errors}")

    await conn.close()
    log.info(f"Done. Processed: {processed}, Errors: {errors}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=os.environ.get(
        "DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--index-only", action="store_true",
                        help="Insert metadata only, skip PDF text extraction")
    args = parser.parse_args()
    asyncio.run(main(args.db_url, args.workers, args.limit, args.index_only))
