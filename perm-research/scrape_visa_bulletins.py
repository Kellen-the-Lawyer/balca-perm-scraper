#!/usr/bin/env python3
"""
Visa Bulletin Scraper & Ingestion
Scrapes all monthly visa bulletins from:
https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html

Extracts Employment-Based and Family-Sponsored priority date tables
(both Final Action Dates and Dates for Filing) and saves to DB.

Usage:
    python3 scrape_visa_bulletins.py            # scrape + ingest all
    python3 scrape_visa_bulletins.py --dry-run  # print parsed data, no DB
    python3 scrape_visa_bulletins.py --reset    # truncate table then reload
"""
import asyncio, logging, os, re, sys, argparse
from datetime import date, datetime
from typing import Optional
import httpx
import asyncpg
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL   = os.environ.get("DATABASE_URL",
    "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
INDEX_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
BASE_URL  = "https://travel.state.gov"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://travel.state.gov/",
}

# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS visa_bulletin (
    id               SERIAL PRIMARY KEY,
    bulletin_date    DATE        NOT NULL,
    bulletin_title   TEXT        NOT NULL,
    source_url       TEXT        NOT NULL,
    category_type    TEXT        NOT NULL,  -- employment / family
    date_type        TEXT        NOT NULL,  -- final_action / dates_for_filing
    preference       TEXT        NOT NULL,  -- EB1/EB2/EB3/EB3W/EB4/EB5 or F1/F2A/F2B/F3/F4
    chargeability    TEXT        NOT NULL,  -- ALL / CHINA / INDIA / MEXICO / PHILIPPINES
    priority_date    DATE,                  -- NULL when current or unavailable
    is_current       BOOLEAN     NOT NULL DEFAULT FALSE,
    is_unavailable   BOOLEAN     NOT NULL DEFAULT FALSE,
    raw_value        TEXT,                  -- original string e.g. "01JAN22", "C", "U"
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bulletin_date, category_type, date_type, preference, chargeability)
);
CREATE INDEX IF NOT EXISTS idx_vb_date         ON visa_bulletin(bulletin_date);
CREATE INDEX IF NOT EXISTS idx_vb_pref         ON visa_bulletin(preference);
CREATE INDEX IF NOT EXISTS idx_vb_chargeability ON visa_bulletin(chargeability);
CREATE INDEX IF NOT EXISTS idx_vb_type         ON visa_bulletin(category_type, date_type);
"""

# ── Date parsing ──────────────────────────────────────────────────────────────

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12
}

def parse_priority_date(raw: str) -> tuple:
    """
    Parse a priority date cell value.
    Returns (priority_date, is_current, is_unavailable, raw_value).
    Handles: "01JAN22", "01JAN2022", "C", "U", "Unavailable", "Current"
    """
    s = raw.strip().upper()
    if not s or s in ("", "-", "—"):
        return None, False, False, raw
    if s in ("C", "CURRENT"):
        return None, True, False, raw
    if s in ("U", "UNAVAILABLE", "UNAV."):
        return None, False, True, raw

    # Try dd-mmm-yy or ddMMMYY / ddMMMYYYY
    m = re.match(r"(\d{1,2})[\-\s]?([A-Za-z]{3})[\-\s]?(\d{2,4})$", s)
    if m:
        day, mon, yr = int(m.group(1)), m.group(2).lower(), m.group(3)
        month_num = MONTH_MAP.get(mon)
        if not month_num:
            return None, False, False, raw
        year = int(yr)
        if year < 100:
            year += 2000 if year < 50 else 1900
        try:
            return date(year, month_num, day), False, False, raw
        except ValueError:
            return None, False, False, raw

    return None, False, False, raw

# ── Table parsing ─────────────────────────────────────────────────────────────

# Known preference row label mappings → canonical names
EB_PREF_MAP = {
    "1st": "EB1", "1": "EB1", "first": "EB1",
    "2nd": "EB2", "2": "EB2", "second": "EB2",
    "3rd": "EB3", "3": "EB3", "third": "EB3",
    "other workers": "EB3W", "3rd other": "EB3W", "other": "EB3W",
    "4th": "EB4", "4": "EB4", "fourth": "EB4",
    "certain religious workers": "EB4R",
    "5th": "EB5", "5": "EB5", "fifth": "EB5",
    "5th unreserved": "EB5U", "unreserved": "EB5U",
    "5th reserved": "EB5R", "reserved": "EB5R",
    "5th targeted": "EB5T",
}
FB_PREF_MAP = {
    "1st": "F1", "1": "F1", "f1": "F1",
    "2a": "F2A", "2nd a": "F2A", "f2a": "F2A",
    "2b": "F2B", "2nd b": "F2B", "f2b": "F2B",
    "3rd": "F3", "3": "F3", "f3": "F3",
    "4th": "F4", "4": "F4", "f4": "F4",
}

# Column header → canonical chargeability
COUNTRY_MAP = {
    "all chargeability areas except those listed": "ALL",
    "all chargeability": "ALL",
    "all areas": "ALL",
    "china": "CHINA", "china-mainland born": "CHINA", "china (mainland-born)": "CHINA",
    "india": "INDIA",
    "mexico": "MEXICO",
    "philippines": "PHILIPPINES",
    "el salvador": "EL_SALVADOR",
    "guatemala": "GUATEMALA",
    "honduras": "HONDURAS",
}

def normalize_pref(raw: str, is_employment: bool) -> Optional[str]:
    key = re.sub(r"\s+", " ", raw.lower().strip().strip("*"))
    pmap = EB_PREF_MAP if is_employment else FB_PREF_MAP
    # exact match
    if key in pmap:
        return pmap[key]
    # partial match
    for k, v in pmap.items():
        if k in key:
            return v
    return None

def normalize_country(raw: str) -> Optional[str]:
    key = re.sub(r"\s+", " ", raw.lower().strip().strip("*"))
    if key in COUNTRY_MAP:
        return COUNTRY_MAP[key]
    for k, v in COUNTRY_MAP.items():
        if k in key:
            return v
    return None

def parse_bulletin_tables(html: str, bulletin_date: date,
                           bulletin_title: str, source_url: str) -> list[dict]:
    """
    Parse all priority date tables from a single bulletin HTML page.
    Scans elements in document order to correctly associate headings with tables.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # Walk ALL block elements in document order
    current_date_type = None
    current_category  = None

    for elem in soup.find_all(["h1","h2","h3","h4","h5","p","table","div"]):
        tag = elem.name

        if tag == "table":
            if not current_date_type or not current_category:
                continue
            rows += _parse_html_table(
                elem, bulletin_date, bulletin_title, source_url,
                current_date_type, current_category
            )
            continue

        # Only update context from non-table elements
        text = elem.get_text(" ", strip=True).lower()
        if not text or len(text) < 4:
            continue

        # Date type: only update from headings or short anchor lines, not body paragraphs
        # (footnotes often mention "final action" in passing and cause false flips)
        is_heading = tag in ("h1","h2","h3","h4","h5")
        is_short   = len(text) < 120  # short lines are likely section headers, not footnotes

        if is_heading or is_short:
            if "dates for filing" in text or "date for filing" in text:
                current_date_type = "dates_for_filing"
            elif "final action" in text:
                current_date_type = "final_action"

        # Category: update from headings and short lines too
        if is_heading or is_short:
            if "employment" in text and ("based" in text or "preference" in text):
                current_category = "employment"
            elif "family" in text and ("sponsored" in text or "preference" in text):
                current_category = "family"

    # Deduplicate: for each unique key, keep the row with a real priority_date
    # over a Current/Unavailable row — but never overwrite a real date with another real date
    # (first real date found wins — later duplicates from mislabeled tables are discarded)
    deduped = {}
    for r in rows:
        key = (r["category_type"], r["date_type"], r["preference"], r["chargeability"])
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = r
        elif existing["priority_date"] is None and r["priority_date"] is None:
            pass  # both C/U, keep existing
        elif existing["priority_date"] is None and r["priority_date"] is not None:
            deduped[key] = r  # upgrade from C/U to real date
        # elif existing has real date: keep it — first real date found wins
    return list(deduped.values())


def _parse_html_table(table, bulletin_date, bulletin_title,
                       source_url, date_type, category_type) -> list[dict]:
    """Parse one <table> element into row dicts."""
    rows_out = []
    all_rows = table.find_all("tr")
    if not all_rows:
        return rows_out

    # Header row → country columns
    header_cells = all_rows[0].find_all(["th","td"])
    if len(header_cells) < 3:
        return rows_out  # skip single-cell / tiny tables

    # First header cell should be a preference label (not a date or number)
    first_hdr = header_cells[0].get_text(" ", strip=True)
    # If it looks like a date value or number, skip this table
    import re as _re
    if _re.match(r'^\d{1,2}[A-Z]{3}\d{2,4}$', first_hdr.upper().strip()) or \
       _re.match(r'^\d+[\.,]?\d*$', first_hdr.strip()):
        return rows_out

    countries = []
    for cell in header_cells[1:]:
        raw = cell.get_text(" ", strip=True)
        country = normalize_country(raw)
        countries.append(country or raw)

    # Must have at least one recognized country to be a real bulletin table
    if not any(c in ("ALL", "CHINA", "INDIA", "MEXICO", "PHILIPPINES") for c in countries):
        return rows_out

    is_employment = (category_type == "employment")

    for tr in all_rows[1:]:
        cells = tr.find_all(["th","td"])
        if not cells:
            continue
        pref_raw = cells[0].get_text(" ", strip=True)
        pref = normalize_pref(pref_raw, is_employment)
        if not pref:
            continue

        for i, country in enumerate(countries):
            if i + 1 >= len(cells):
                break
            raw_val = cells[i+1].get_text(" ", strip=True)
            if not raw_val:
                continue
            pd, is_c, is_u, raw = parse_priority_date(raw_val)
            rows_out.append({
                "bulletin_date":  bulletin_date,
                "bulletin_title": bulletin_title,
                "source_url":     source_url,
                "category_type":  category_type,
                "date_type":      date_type,
                "preference":     pref,
                "chargeability":  country,
                "priority_date":  pd,
                "is_current":     is_c,
                "is_unavailable": is_u,
                "raw_value":      raw,
            })
    return rows_out


def parse_pre_tables(html: str, bulletin_date: date,
                      bulletin_title: str, source_url: str) -> list[dict]:
    """Fallback for older text-layout bulletins."""
    rows_out = []
    soup = BeautifulSoup(html, "html.parser")
    for pre in soup.find_all("pre"):
        text = pre.get_text()
        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            continue
        # Very basic: look for lines with dates
        for line in lines:
            if re.search(r'\d{1,2}[A-Z]{3}\d{2}', line.upper()):
                log.debug(f"pre-table line: {line[:80]}")
    return rows_out  # TODO: extend if needed for pre-2000 bulletins

# ── Index scraper ─────────────────────────────────────────────────────────────

MONTH_NUM = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
}

def parse_bulletin_links(html: str) -> list[dict]:
    """
    Parse the index page to extract all bulletin links.
    Returns list of {title, url, bulletin_date}.
    """
    soup = BeautifulSoup(html, "html.parser")
    bulletins = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "visa-bulletin" not in href.lower():
            continue
        if href in seen:
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        # Parse month/year from URL or title
        # URL pattern: /visa-bulletin/2025/visa-bulletin-for-october-2024.html
        url_m = re.search(r"visa-bulletin-for-([a-z]+)-(\d{4})", href.lower())
        if url_m:
            mon_str = url_m.group(1)
            year    = int(url_m.group(2))
            mon_num = MONTH_NUM.get(mon_str)
            if mon_num:
                bdate = date(year, mon_num, 1)
                full_url = BASE_URL + href if href.startswith("/") else href
                seen.add(href)
                bulletins.append({
                    "title":          title,
                    "url":            full_url,
                    "bulletin_date":  bdate,
                })

    # Sort oldest → newest
    bulletins.sort(key=lambda x: x["bulletin_date"])
    return bulletins


# ── Main async scraper ────────────────────────────────────────────────────────

async def fetch(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a URL, trying up to 3 times with backoff."""
    for attempt in range(1, 4):
        try:
            r = await client.get(url, follow_redirects=True, timeout=30)
            if r.status_code == 200:
                return r.text
            log.warning(f"  HTTP {r.status_code} for {url} (attempt {attempt})")
        except httpx.RequestError as e:
            log.warning(f"  Request error {url}: {e} (attempt {attempt})")
        if attempt < 3:
            await asyncio.sleep(2 ** attempt)
    return ""


async def main():
    parser = argparse.ArgumentParser(description="Scrape DOS Visa Bulletins")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print, no DB writes")
    parser.add_argument("--reset",   action="store_true",
                        help="Truncate visa_bulletin table before loading")
    parser.add_argument("--limit",   type=int, default=0,
                        help="Only process this many bulletins (0 = all)")
    parser.add_argument("--from-year", type=int, default=0,
                        help="Only process bulletins from this year onwards")
    args = parser.parse_args()

    conn = None if args.dry_run else await asyncpg.connect(DB_URL)

    if not args.dry_run:
        await conn.execute(CREATE_SQL)
        log.info("Schema ready")
        if args.reset:
            await conn.execute("TRUNCATE visa_bulletin RESTART IDENTITY")
            log.info("Table truncated")

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        # Step 1 — fetch index
        log.info(f"Fetching index: {INDEX_URL}")
        index_html = await fetch(client, INDEX_URL)
        if not index_html:
            log.error("Failed to fetch index page")
            return

        bulletins = parse_bulletin_links(index_html)
        log.info(f"Found {len(bulletins)} bulletin links")

        if args.from_year:
            bulletins = [b for b in bulletins if b["bulletin_date"].year >= args.from_year]
            log.info(f"Filtered to {len(bulletins)} bulletins from {args.from_year}+")

        if args.limit:
            bulletins = bulletins[-args.limit:]  # take most recent N
            log.info(f"Limited to {len(bulletins)} most recent bulletins")

        total_rows = 0
        for i, b in enumerate(bulletins):
            log.info(f"[{i+1}/{len(bulletins)}] {b['title']}  {b['url']}")

            html = await fetch(client, b["url"])
            if not html:
                log.warning(f"  Skipping — no content")
                continue

            rows = parse_bulletin_tables(
                html, b["bulletin_date"], b["title"], b["url"]
            )
            log.info(f"  Parsed {len(rows)} rows")

            if args.dry_run:
                for r in rows[:3]:
                    log.info(f"    {r['category_type']:10} {r['date_type']:20} "
                             f"{r['preference']:5} {r['chargeability']:12} "
                             f"{'C' if r['is_current'] else r['raw_value']}")
                total_rows += len(rows)
                continue

            if rows:
                await conn.executemany("""
                    INSERT INTO visa_bulletin (
                        bulletin_date, bulletin_title, source_url,
                        category_type, date_type, preference, chargeability,
                        priority_date, is_current, is_unavailable, raw_value
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
                    )
                    ON CONFLICT (bulletin_date, category_type, date_type, preference, chargeability)
                    DO UPDATE SET
                        priority_date  = EXCLUDED.priority_date,
                        is_current     = EXCLUDED.is_current,
                        is_unavailable = EXCLUDED.is_unavailable,
                        raw_value      = EXCLUDED.raw_value
                """, [
                    (r["bulletin_date"], r["bulletin_title"], r["source_url"],
                     r["category_type"], r["date_type"], r["preference"],
                     r["chargeability"], r["priority_date"],
                     r["is_current"], r["is_unavailable"], r["raw_value"])
                    for r in rows
                ])
                total_rows += len(rows)

            await asyncio.sleep(0.5)  # polite pacing

    if conn:
        final = await conn.fetchval("SELECT COUNT(*) FROM visa_bulletin")
        await conn.close()
        log.info(f"\nDone. {total_rows} rows processed, {final} total in DB.")
    else:
        log.info(f"\nDry run done. {total_rows} rows parsed across {len(bulletins)} bulletins.")


if __name__ == "__main__":
    asyncio.run(main())
