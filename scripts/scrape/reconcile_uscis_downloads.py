#!/usr/bin/env python3
"""
Reconcile downloaded files on disk with uscis_report_files in Docker DB.

The files were downloaded to data/uscis_reports/ during the first run
against local postgres. The Docker DB catalog was just re-scraped so all
records show download_status='pending'. This script:

  1. Scans data/uscis_reports/ for all files on disk
  2. Matches them to catalog entries by filename
  3. Updates uscis_report_files with local_path, size, sha256, status='done'

Usage:
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/scrape/reconcile_uscis_downloads.py
"""

import hashlib
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "psycopg2-binary", "python-dotenv"])
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

REPO_ROOT   = Path(__file__).resolve().parents[2]
OUTPUT_BASE = REPO_ROOT / "data" / "uscis_reports"
DB_URL      = os.environ.get("DATABASE_URL",
                             "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # Build index of all files on disk: filename -> Path
    log.info(f"Scanning {OUTPUT_BASE} for downloaded files...")
    disk_files: dict[str, Path] = {}
    for p in OUTPUT_BASE.rglob("*"):
        if p.is_file() and not p.name.endswith(".tmp"):
            disk_files[p.name] = p
    log.info(f"Found {len(disk_files)} files on disk.")

    conn = psycopg2.connect(DB_URL)

    # Fetch all pending catalog entries with their URLs
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT f.id AS file_id, f.report_id, c.file_url, c.file_type, c.fiscal_year
            FROM uscis_report_files f
            JOIN uscis_report_catalog c ON c.id = f.report_id
            WHERE f.download_status = 'pending'
        """)
        pending = [dict(r) for r in cur.fetchall()]

    log.info(f"Pending entries in DB: {len(pending)}")

    matched = 0
    unmatched = 0

    for rec in pending:
        filename = Path(urlparse(rec["file_url"]).path).name
        disk_path = disk_files.get(filename)

        if disk_path and disk_path.stat().st_size > 0:
            size = disk_path.stat().st_size
            checksum = sha256(disk_path)
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE uscis_report_files SET
                        local_path      = %s,
                        file_size_bytes = %s,
                        sha256          = %s,
                        download_status = 'done',
                        downloaded_at   = NOW()
                    WHERE id = %s
                """, (str(disk_path), size, checksum, rec["file_id"]))
            matched += 1
            if matched % 100 == 0:
                conn.commit()
                log.info(f"  {matched} matched so far...")
        else:
            unmatched += 1

    conn.commit()
    conn.close()

    log.info("=" * 50)
    log.info(f"Reconciliation complete.")
    log.info(f"  Matched (status -> done): {matched}")
    log.info(f"  No file on disk:          {unmatched}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
