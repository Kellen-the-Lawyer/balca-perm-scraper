#!/usr/bin/env python3
"""
USCIS Electronic Reading Room (FOIA) Catalog Scraper
======================================================
Scrapes all FOIA documents from
https://www.uscis.gov/records/electronic-reading-room
into uscis_foia_documents (download_status='pending').

Pages 0-20 with items_per_page=100 (~2,060 rows, ~98% real PDFs;
the first 1-2 rows per page are site navigation links, filtered out).

Usage:
    venv/bin/python3 scripts/scrape/scrape_uscis_reading_room.py [--dry-run] [--start-page N]

robots.txt:
    Crawl-delay: 10 -> we sleep 11s + jitter between page requests.
    /records/electronic-reading-room is ALLOWED.
    /sites/default/files/archive/ DISALLOWED -> auto-skipped.
"""

import argparse, logging, os, re, sys, time, random
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx
    from bs4 import BeautifulSoup
    import psycopg2, psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "httpx", "beautifulsoup4", "lxml", "psycopg2-binary", "python-dotenv"])
    import httpx
    from bs4 import BeautifulSoup
    import psycopg2, psycopg2.extras
    from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_URL    = "https://www.uscis.gov"
INDEX_PATH  = "/records/electronic-reading-room"
PAGE_SIZE   = 100
MAX_PAGE    = 20          # page 20 has 60 rows; 21+ empty
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

_DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(["january","february","march","april","may","june",
    "july","august","september","october","november","december"], 1)}

def _parse_date(s):
    if not s: return None
    # ISO datetime from <time datetime=...>
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DATE_RE.search(s)
    if m:
        return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None

def _file_type(url):
    s = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return s if s in {"pdf","xlsx","xls","csv","doc","docx","zip","html"} else "other"

def _stable_id(url):
    path = urlparse(url).path
    rel  = re.sub(r"^/sites/default/files/", "", path)
    return re.sub(r"\.\w+$", "", rel)

def _doc_category(url):
    # /sites/default/files/document/<category>/<file>
    m = re.search(r"/document/([^/]+)/", urlparse(url).path)
    return m.group(1) if m else None

def _kb(title):
    m = re.search(r"\([\w,\s]+,\s*([\d.]+)\s*KB\)", title, re.IGNORECASE)
    if m: return float(m.group(1))
    m = re.search(r"\([\w,\s]+,\s*([\d.]+)\s*MB\)", title, re.IGNORECASE)
    if m: return float(m.group(1)) * 1024
    return None

def _clean(title):
    return re.sub(r"\s*\([\w,\s]+,\s*[\d.]+\s*[KM]B\)\s*$", "", title, flags=re.IGNORECASE).strip()

def _headers(i=0):
    return {"User-Agent": USER_AGENTS[i % len(USER_AGENTS)],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.google.com/"}

def fetch_page(page):
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

def parse_page(html):
    soup = BeautifulSoup(html, "lxml")
    records = []
    for row in soup.select(".views-row"):
        link = row.select_one("a[href]")
        if not link: continue
        href = link["href"]
        # Only real file documents -- skip nav links
        if "/sites/default/files/" not in href: continue
        if "/sites/default/files/archive/" in href: continue
        full_url  = href if href.startswith("http") else BASE_URL + href
        raw_title = link.get_text(" ", strip=True)
        date_el   = row.select_one("time")
        pub_date  = None
        if date_el:
            pub_date = _parse_date(date_el.get("datetime","")) or _parse_date(date_el.get_text(strip=True))
        desc_el = row.select_one(".views-field-body .field-content, .field--name-body")
        desc    = desc_el.get_text(" ", strip=True) if desc_el else None
        records.append({
            "stable_id":      _stable_id(full_url),
            "title":          _clean(raw_title),
            "description":    desc,
            "published_date": pub_date,
            "file_url":       full_url,
            "file_type":      _file_type(full_url),
            "file_size_kb":   _kb(raw_title),
            "doc_category":   _doc_category(full_url),
        })
    return records

def ensure_schema(conn):
    sql_path = Path(__file__).resolve().parents[2] / "schema" / "uscis_foia_schema.sql"
    if sql_path.exists():
        with conn.cursor() as cur:
            cur.execute(sql_path.read_text())
        conn.commit()
        log.info("Schema applied.")

UPSERT_SQL = """
    INSERT INTO uscis_foia_documents
        (stable_id,title,description,published_date,file_url,file_type,
         file_size_kb,doc_category,download_status,scraped_at,updated_at)
    VALUES
        (%(stable_id)s,%(title)s,%(description)s,%(published_date)s,%(file_url)s,
         %(file_type)s,%(file_size_kb)s,%(doc_category)s,'pending',NOW(),NOW())
    ON CONFLICT (stable_id) DO UPDATE SET
        title=EXCLUDED.title, description=EXCLUDED.description,
        published_date=EXCLUDED.published_date, file_url=EXCLUDED.file_url,
        file_type=EXCLUDED.file_type, file_size_kb=EXCLUDED.file_size_kb,
        doc_category=EXCLUDED.doc_category, updated_at=NOW()
"""

def upsert(conn, records, dry_run=False):
    if dry_run:
        for r in records: log.info(f"  [DRY] {r['file_type']:4s} {r['stable_id'][:60]}")
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SQL, records, page_size=100)
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start-page", type=int, default=0)
    args = ap.parse_args()

    conn = None
    if not args.dry_run:
        conn = psycopg2.connect(DB_URL)
        ensure_schema(conn)

    log.info("="*60)
    log.info("USCIS Electronic Reading Room (FOIA) Scraper")
    log.info(f"Crawl-delay: {CRAWL_DELAY}s + up to {JITTER}s jitter")
    log.info("="*60)

    total = 0
    for page in range(args.start_page, MAX_PAGE + 1):
        html = fetch_page(page)
        records = parse_page(html)
        log.info(f"  Page {page}/{MAX_PAGE}: {len(records)} document rows")
        if records:
            upsert(conn, records, args.dry_run)
            total += len(records)
        if page < MAX_PAGE:
            sleep = CRAWL_DELAY + random.uniform(0, JITTER)
            log.info(f"  Sleeping {sleep:.1f}s...")
            time.sleep(sleep)

    if conn: conn.close()
    log.info("="*60)
    log.info(f"Done. {total} FOIA document entries scraped.")
    log.info("="*60)

if __name__ == "__main__":
    main()
