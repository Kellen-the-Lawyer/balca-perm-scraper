#!/usr/bin/env python3
"""
USCIS Report File Downloader
==============================
Phase 2: Downloads all files from uscis_report_files WHERE status='pending'.

Usage:
    python scripts/scrape/download_uscis_reports.py [--form I-129] [--year 2026]
                                                    [--limit N] [--dry-run]
                                                    [--retry-failed]

Files are saved to:
    data/uscis_reports/<file_type>/<fiscal_year>/<original_filename>
"""

import argparse
import hashlib
import logging
import os
import re
import subprocess
import sys
import time
import random
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "httpx", "psycopg2-binary", "python-dotenv"])
    import httpx
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

REPO_ROOT   = Path(__file__).resolve().parents[2]
OUTPUT_BASE = REPO_ROOT / "data" / "uscis_reports"
DB_URL      = os.environ.get("DATABASE_URL",
                             "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
FILE_DELAY  = 10.0
JITTER      = 2.0
CHUNK_SIZE  = 65_536

USER_AGENTS = [
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def _dest(rec: dict) -> Path:
    fy    = rec.get("fiscal_year") or "unknown_year"
    ftype = rec.get("file_type") or "other"
    fname = Path(urlparse(rec["file_url"]).path).name
    return OUTPUT_BASE / ftype / str(fy) / fname

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""): h.update(chunk)
    return h.hexdigest()

def _headers(i=0): return {
    "User-Agent": USER_AGENTS[i % len(USER_AGENTS)],
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data",
}

def download(url: str, dest: Path) -> tuple[bool, str | None]:
    if "/sites/default/files/archive/" in url:
        return False, "Skipped: archived (robots.txt disallowed)"
    if dest.exists() and dest.stat().st_size > 0:
        log.info(f"  Already exists: {dest.name}")
        return True, None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    for attempt in range(len(USER_AGENTS)):
        try:
            with httpx.Client(timeout=120, headers=_headers(attempt),
                              follow_redirects=True) as c:
                with c.stream("GET", url) as resp:
                    if resp.status_code in (403,429) and attempt < len(USER_AGENTS)-1:
                        time.sleep(5); continue
                    if resp.status_code == 404:
                        return False, f"404 Not Found: {url}"
                    resp.raise_for_status()
                    with open(tmp,"wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=CHUNK_SIZE): f.write(chunk)
            tmp.rename(dest)
            log.info(f"  ✓ {dest.name} ({dest.stat().st_size:,} bytes)")
            return True, None
        except Exception as e:
            log.warning(f"  Attempt {attempt} failed: {e}")
            if attempt < len(USER_AGENTS)-1: time.sleep(5); continue
    # wget fallback
    log.info("  Trying wget...")
    r = subprocess.run(["wget","--quiet",f"--user-agent={USER_AGENTS[0]}",
                        "--tries=3","--timeout=60",f"--output-document={tmp}",url],
                       capture_output=True, text=True, timeout=120)
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        tmp.rename(dest)
        log.info(f"  ✓ (wget) {dest.name}")
        return True, None
    if tmp.exists(): tmp.unlink()
    return False, f"All methods failed: {url}"

PENDING_SQL = """
    SELECT f.id AS file_id, f.report_id, c.stable_id, c.file_url,
           c.file_type, c.fiscal_year, c.title
    FROM uscis_report_files f
    JOIN uscis_report_catalog c ON c.id = f.report_id
    WHERE f.download_status = %(status)s
      AND (%(form_type)s IS NULL OR c.form_type = %(form_type)s)
      AND (%(year)s IS NULL OR c.fiscal_year = %(year)s)
    ORDER BY c.published_date DESC NULLS LAST
    LIMIT %(limit)s
"""
UPDATE_SQL = """
    UPDATE uscis_report_files SET local_path=%(p)s, file_size_bytes=%(s)s, sha256=%(h)s,
        download_status=%(status)s, error_message=%(err)s, downloaded_at=NOW()
    WHERE id=%(fid)s
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--form",         help="Filter by form_type e.g. I-129")
    ap.add_argument("--year",         type=int)
    ap.add_argument("--limit",        type=int, default=9999)
    ap.add_argument("--dry-run",      action="store_true")
    ap.add_argument("--retry-failed", action="store_true")
    args = ap.parse_args()

    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(DB_URL)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(PENDING_SQL, {"status": "failed" if args.retry_failed else "pending",
                                  "form_type": args.form, "year": args.year,
                                  "limit": args.limit})
        records = [dict(r) for r in cur.fetchall()]

    log.info("="*60)
    log.info(f"USCIS Report File Downloader — {len(records)} files queued")
    log.info(f"Output: {OUTPUT_BASE}")
    log.info("="*60)

    ok = failed = 0
    for i, rec in enumerate(records):
        dest = _dest(rec)
        log.info(f"[{i+1}/{len(records)}] {rec['title'][:55]}")
        log.info(f"  {rec['file_url']}")
        if args.dry_run:
            log.info(f"  [DRY RUN] -> {dest}"); continue
        success, err = download(rec["file_url"], dest)
        if success:
            with conn.cursor() as cur:
                cur.execute(UPDATE_SQL, {"p": str(dest), "s": dest.stat().st_size,
                                         "h": _sha256(dest), "status": "done",
                                         "err": None, "fid": rec["file_id"]})
            conn.commit(); ok += 1
        else:
            log.error(f"  ✗ {err}")
            with conn.cursor() as cur:
                cur.execute(UPDATE_SQL, {"p": None, "s": None, "h": None,
                                         "status": "failed", "err": err,
                                         "fid": rec["file_id"]})
            conn.commit(); failed += 1
        if i < len(records)-1:
            sleep = FILE_DELAY + random.uniform(0, JITTER)
            log.info(f"  Sleeping {sleep:.1f}s...")
            time.sleep(sleep)

    conn.close()
    log.info("="*60)
    log.info(f"Done.  ✓ {ok}  ✗ {failed}  (dry-run skipped: {len(records)-ok-failed})")
    log.info("="*60)

if __name__ == "__main__":
    main()
