#!/usr/bin/env python3
"""
USCIS Data Library Catalog Scraper
=====================================
Phase 1: Scrapes all 1,728 entries from the USCIS Data Library and loads
metadata into uscis_report_catalog + uscis_report_files (status=pending).

Usage:
    python scripts/scrape/scrape_uscis_data_catalog.py [--dry-run] [--start-page N]

robots.txt:
    Crawl-delay: 10  ->  we sleep 11s + jitter between page requests.
    /tools/reports-and-studies/immigration-and-citizenship-data  ALLOWED.
    /sites/default/files/archive/  DISALLOWED -> automatically skipped.
"""

import argparse
import logging
import os
import re
import sys
import time
import random
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx
    from bs4 import BeautifulSoup
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "httpx", "beautifulsoup4", "lxml", "psycopg2-binary", "python-dotenv"])
    import httpx
    from bs4 import BeautifulSoup
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_URL    = "https://www.uscis.gov"
INDEX_PATH  = "/tools/reports-and-studies/immigration-and-citizenship-data"
PAGE_SIZE   = 100
CRAWL_DELAY = 11.0
JITTER      = 2.0

DB_URL = os.environ.get("DATABASE_URL",
                        "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")

USER_AGENTS = [
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

_FY_RE   = re.compile(r"(?:fiscal year|fy)\s*(\d{4})", re.IGNORECASE)
_Q_RE    = re.compile(r"quarter\s*(\d)|q(\d)", re.IGNORECASE)
_FORM_RE = re.compile(r"\b(I-\d{2,4}[A-Z]?|N-\d{3}|G-\d{3,4}|ETA-\d{4})\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)
_MONTHS  = {m: i for i, m in enumerate(["january","february","march","april","may","june",
    "july","august","september","october","november","december"], 1)}


def _parse_date(s: str) -> date | None:
    m = _DATE_RE.search(s)
    if m:
        return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None

def _file_type(url: str) -> str:
    s = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return s if s in {"xlsx","xls","csv","pdf","zip"} else "other"

def _stable_id(url: str) -> str:
    path = urlparse(url).path
    rel  = re.sub(r"^/sites/default/files/", "", path)
    return re.sub(r"\.\w+$", "", rel)

def _kb(title: str):
    m = re.search(r"\([\w,\s]+,\s*([\d.]+)\s*KB\)", title, re.IGNORECASE)
    return float(m.group(1)) if m else None

def _clean(title: str) -> str:
    return re.sub(r"\s*\([\w,\s]+,\s*[\d.]+\s*KB\)\s*$", "", title, flags=re.IGNORECASE).strip()


def _headers(i=0): return {
    "User-Agent": USER_AGENTS[i % len(USER_AGENTS)],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.google.com/",
}

def fetch_page(page: int) -> str:
    url = f"{BASE_URL}{INDEX_PATH}?page={page}&items_per_page={PAGE_SIZE}"
    for attempt in range(len(USER_AGENTS)):
        log.info(f"  Fetching page {page} (UA {attempt}): {url}")
        try:
            with httpx.Client(timeout=30, headers=_headers(attempt), follow_redirects=True) as c:
                resp = c.get(url)
                if resp.status_code in (403, 429) and attempt < len(USER_AGENTS)-1:
                    time.sleep(5); continue
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as e:
            if attempt < len(USER_AGENTS)-1:
                log.warning(f"  {e}, retrying..."); time.sleep(5); continue
            raise
    raise RuntimeError(f"All fetch attempts failed for page {page}")

def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    records = []
    for row in soup.select(".views-row"):
        link = row.select_one("a[href]")
        if not link: continue
        href = link["href"]
        if "/sites/default/files/archive/" in href: continue
        if not href.startswith(("http", "/sites/default/files/")): continue
        full_url  = href if href.startswith("http") else BASE_URL + href
        raw_title = link.get_text(" ", strip=True)
        date_el   = row.select_one("time")
        pub_date  = None
        if date_el:
            pub_date = (_parse_date(date_el.get("datetime","")) or
                        _parse_date(date_el.get_text(strip=True)))
        desc_el = row.select_one(".views-field-body .field-content")
        desc    = desc_el.get_text(" ", strip=True) if desc_el else None
        combined = f"{raw_title} {desc or ''}"
        fy  = None
        m = _FY_RE.search(combined)
        if m: fy = int(m.group(1))
        fq  = None
        m = _Q_RE.search(combined)
        if m: fq = int(m.group(1) or m.group(2))
        fm  = None
        m = _FORM_RE.search(combined)
        if m: fm = m.group(1).upper()
        records.append({
            "stable_id":      _stable_id(full_url),
            "title":          _clean(raw_title),
            "description":    desc,
            "published_date": pub_date,
            "file_url":       full_url,
            "file_type":      _file_type(full_url),
            "file_size_kb":   _kb(raw_title),
            "categories":     [],
            "fiscal_year":    fy,
            "quarter":        fq,
            "form_type":      fm,
        })
    return records

def total_pages(html: str) -> int:
    m = re.search(r"of\s+([\d,]+)\s+total", html, re.IGNORECASE)
    if m:
        total = int(m.group(1).replace(",",""))
        return (total + PAGE_SIZE - 1) // PAGE_SIZE
    return 18

def ensure_schema(conn):
    sql_path = Path(__file__).resolve().parents[2] / "schema" / "uscis_stats_schema.sql"
    if sql_path.exists():
        with conn.cursor() as cur:
            cur.execute(sql_path.read_text())
        conn.commit()
        log.info("Schema applied.")
    else:
        log.warning("Schema file not found — assuming tables exist.")

UPSERT_SQL = """
    INSERT INTO uscis_report_catalog
        (stable_id,title,description,published_date,file_url,file_type,
         file_size_kb,categories,fiscal_year,quarter,form_type,scraped_at,updated_at)
    VALUES
        (%(stable_id)s,%(title)s,%(description)s,%(published_date)s,%(file_url)s,
         %(file_type)s,%(file_size_kb)s,%(categories)s,%(fiscal_year)s,%(quarter)s,
         %(form_type)s,NOW(),NOW())
    ON CONFLICT (stable_id) DO UPDATE SET
        title=EXCLUDED.title, description=EXCLUDED.description,
        published_date=EXCLUDED.published_date, file_url=EXCLUDED.file_url,
        file_type=EXCLUDED.file_type, file_size_kb=EXCLUDED.file_size_kb,
        fiscal_year=EXCLUDED.fiscal_year, quarter=EXCLUDED.quarter,
        form_type=EXCLUDED.form_type, updated_at=NOW()
"""
FILE_SQL = """
    INSERT INTO uscis_report_files (report_id, download_status)
    SELECT id, 'pending' FROM uscis_report_catalog WHERE stable_id=%(stable_id)s
    ON CONFLICT (report_id) DO NOTHING
"""

def upsert(conn, records, dry_run=False):
    if dry_run:
        for r in records: log.info(f"  [DRY RUN] {r['stable_id']}")
        return
    for r in records: r["categories"] = r["categories"] or []
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SQL, records, page_size=100)
        psycopg2.extras.execute_batch(cur, FILE_SQL,   records, page_size=100)
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",    action="store_true")
    ap.add_argument("--start-page", type=int, default=0)
    args = ap.parse_args()

    conn = None
    if not args.dry_run:
        conn = psycopg2.connect(DB_URL)
        ensure_schema(conn)

    log.info("="*60)
    log.info("USCIS Data Library Catalog Scraper")
    log.info(f"Crawl-delay: {CRAWL_DELAY}s + up to {JITTER}s jitter (robots.txt)")
    log.info("="*60)

    all_records = []
    page = args.start_page
    n_pages = None

    while True:
        html = fetch_page(page)
        if n_pages is None:
            n_pages = total_pages(html)
            log.info(f"Total pages: {n_pages}")

        records = parse_page(html)
        log.info(f"  Page {page}/{n_pages-1}: {len(records)} records")
        if not records:
            break

        all_records.extend(records)
        upsert(conn, records, args.dry_run)

        page += 1
        if page >= n_pages:
            break

        sleep = CRAWL_DELAY + random.uniform(0, JITTER)
        log.info(f"  Sleeping {sleep:.1f}s...")
        time.sleep(sleep)

    if conn: conn.close()
    log.info("="*60)
    log.info(f"Done. {len(all_records)} catalog entries scraped.")
    log.info("="*60)

if __name__ == "__main__":
    main()
