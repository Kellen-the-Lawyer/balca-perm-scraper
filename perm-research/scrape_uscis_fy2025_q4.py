#!/usr/bin/env python3
"""
USCIS FY2025 Q4 Spreadsheet Scraper
Downloads all Excel/CSV spreadsheets from the
"Fiscal Year 2025: Quarter 4 Data Reports, July-September 2025" section
of https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data

Usage:
    python scrape_uscis_fy2025_q4.py

Output directory: /Users/Dad/Documents/GitHub/balca-perm-scraper/USCIS Reports
"""

import logging
import re
import subprocess
import sys
import time
import random
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TARGET_URL = "https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data"
OUTPUT_DIR = Path("/Users/Dad/Documents/GitHub/balca-perm-scraper/USCIS Reports")

# The section header text to look for (partial match, case-insensitive)
SECTION_KEYWORDS = [
    "fiscal year 2025",
    "quarter 4",
    "july",
    "september 2025",
    "fy2025",
    "fy 2025",
]

# File extensions to download
DOWNLOAD_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv", ".ods", ".zip"}

SLEEP_BETWEEN_DOWNLOADS = 2.5   # seconds (polite)
SLEEP_JITTER             = 1.0  # extra random seconds

USER_AGENTS = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Install dependencies if missing
# ---------------------------------------------------------------------------
def ensure_deps():
    try:
        import httpx          # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        log.info("Installing httpx and beautifulsoup4...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "httpx", "beautifulsoup4", "lxml"]
        )

ensure_deps()

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def _headers(ua_index: int = 0) -> dict:
    return {
        "User-Agent": USER_AGENTS[ua_index % len(USER_AGENTS)],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.google.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
    }


def fetch_page(url: str, ua_index: int = 0) -> str:
    """Fetch HTML, escalating User-Agent on 403."""
    for attempt in range(len(USER_AGENTS)):
        log.info(f"Fetching page (UA {attempt}): {url}")
        try:
            with httpx.Client(
                timeout=30,
                headers=_headers(attempt),
                follow_redirects=True,
            ) as client:
                resp = client.get(url)
                if resp.status_code == 404:
                    raise SystemExit(f"404 Not Found: {url}")
                if resp.status_code in (403, 429) and attempt < len(USER_AGENTS) - 1:
                    log.warning(f"Got {resp.status_code}, retrying with next UA...")
                    time.sleep(3)
                    continue
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as e:
            if attempt < len(USER_AGENTS) - 1:
                log.warning(f"httpx error: {e}, retrying...")
                time.sleep(3)
                continue
            raise

    # Last-resort: wget
    log.info("Falling back to wget for page fetch...")
    return _wget_fetch(url)


def _wget_fetch(url: str) -> str:
    out = Path("/tmp/_uscis_page.html")
    out.unlink(missing_ok=True)
    cmd = [
        "wget", "--quiet",
        f"--user-agent={USER_AGENTS[0]}",
        "--wait=2", "--random-wait",
        "--tries=3", "--timeout=30",
        f"--output-document={out}", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(f"wget failed: {result.stderr[:300]}")
    return out.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Parsing: find the FY2025 Q4 section and extract spreadsheet links
# ---------------------------------------------------------------------------
def _is_fy2025_q4_section(text: str) -> bool:
    """Return True if the text looks like it belongs to the FY2025 Q4 section."""
    t = text.lower()
    has_fy25 = any(k in t for k in ["2025", "fy2025", "fy 2025"])
    has_q4   = any(k in t for k in ["quarter 4", "q4", "july", "july-september", "july–september"])
    return has_fy25 and has_q4


def find_q4_links(html: str, base_url: str) -> list[dict]:
    """
    Parse HTML and find all spreadsheet download links inside the
    FY2025 Q4 section.  Returns a list of {url, filename, label} dicts.
    """
    soup = BeautifulSoup(html, "lxml")
    links = []

    # Strategy 1: look for accordion/details/section elements whose header
    # mentions FY2025 Q4, then harvest anchors inside them.
    candidates = []

    # Look for common USCIS accordion wrappers
    for tag in soup.find_all(True):
        if tag.name in ("details", "section", "div", "li", "article"):
            # Check any child heading or summary for Q4 text
            heading = tag.find(["summary", "h2", "h3", "h4", "h5", "button", "span"])
            if heading and _is_fy2025_q4_section(heading.get_text(" ", strip=True)):
                candidates.append(tag)

    if candidates:
        log.info(f"Found {len(candidates)} candidate section(s) matching FY2025 Q4 heading")
        for section in candidates:
            for a in section.find_all("a", href=True):
                href = a["href"]
                full_url = urljoin(base_url, href)
                ext = Path(urlparse(full_url).path).suffix.lower()
                if ext in DOWNLOAD_EXTENSIONS or any(
                    e in full_url.lower() for e in [".xlsx", ".xls", ".csv", ".zip"]
                ):
                    label = a.get_text(" ", strip=True) or Path(urlparse(full_url).path).name
                    links.append({"url": full_url, "label": label,
                                  "filename": _safe_filename(label, full_url)})
    else:
        log.warning("No section found by heading scan — doing full-page link scan filtered by context")

    # Strategy 2 (fallback / supplement): scan ALL links on the page,
    # keep those that look like spreadsheet downloads and whose nearby
    # text mentions FY2025 Q4.
    all_a = soup.find_all("a", href=True)
    seen = {d["url"] for d in links}
    for a in all_a:
        href = a["href"]
        full_url = urljoin(base_url, href)
        ext = Path(urlparse(full_url).path).suffix.lower()
        if ext not in DOWNLOAD_EXTENSIONS and not any(
            e in full_url.lower() for e in [".xlsx", ".xls", ".csv", ".zip"]
        ):
            continue
        if full_url in seen:
            continue
        # Check surrounding text for Q4 context
        context = ""
        for ancestor in a.parents:
            if ancestor.name in ("li", "div", "section", "article", "details"):
                context = ancestor.get_text(" ", strip=True)[:400]
                break
        if _is_fy2025_q4_section(context) or _is_fy2025_q4_section(a.get_text()):
            label = a.get_text(" ", strip=True) or Path(urlparse(full_url).path).name
            links.append({"url": full_url, "label": label,
                          "filename": _safe_filename(label, full_url)})
            seen.add(full_url)

    return links


def _safe_filename(label: str, url: str) -> str:
    """Derive a safe filename from the link label + URL extension."""
    ext = Path(urlparse(url).path).suffix or ".xlsx"
    # Use URL filename if label is very short / generic
    url_name = Path(urlparse(url).path).name
    if len(label) < 5:
        base = re.sub(r"[^\w\-. ]", "_", url_name)
    else:
        base = re.sub(r"[^\w\-. ]", "_", label[:120]).strip()
        if not base.lower().endswith(ext):
            base += ext
    return base


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------
def download_file(url: str, dest: Path, ua_index: int = 0) -> bool:
    """Download a file, trying httpx then wget."""
    if dest.exists():
        log.info(f"  Already exists, skipping: {dest.name}")
        return True

    log.info(f"  Downloading → {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Try httpx
    for attempt in range(len(USER_AGENTS)):
        try:
            with httpx.Client(
                timeout=60,
                headers=_headers(attempt),
                follow_redirects=True,
            ) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code in (403, 429) and attempt < len(USER_AGENTS) - 1:
                        log.warning(f"  {resp.status_code}, retrying with next UA...")
                        time.sleep(3)
                        continue
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=32_768):
                            f.write(chunk)
            size = dest.stat().st_size
            log.info(f"  ✓ {dest.name} ({size:,} bytes)")
            return True
        except Exception as e:
            log.warning(f"  httpx attempt {attempt} failed: {e}")
            if attempt < len(USER_AGENTS) - 1:
                time.sleep(3)
                continue

    # wget fallback
    log.info("  Trying wget...")
    cmd = [
        "wget", "--quiet",
        f"--user-agent={USER_AGENTS[0]}",
        "--tries=3", "--timeout=60",
        f"--output-document={dest}", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
        log.info(f"  ✓ (wget) {dest.name} ({dest.stat().st_size:,} bytes)")
        return True

    log.error(f"  ✗ Failed to download: {url}")
    if dest.exists():
        dest.unlink()
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("USCIS FY2025 Q4 Spreadsheet Scraper")
    log.info(f"Target : {TARGET_URL}")
    log.info(f"Output : {OUTPUT_DIR}")
    log.info("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch the main page
    html = fetch_page(TARGET_URL)
    log.info(f"Fetched page ({len(html):,} chars)")

    # 2. Find Q4 spreadsheet links
    links = find_q4_links(html, TARGET_URL)

    if not links:
        log.error(
            "No FY2025 Q4 spreadsheet links found!\n"
            "The page may be a JavaScript SPA. Try opening the page in Chrome,\n"
            "expanding the FY2025 Q4 section, then re-running with --from-cache,\n"
            "or install playwright: pip install playwright && playwright install chromium\n"
            "and set USE_PLAYWRIGHT=1 in the environment."
        )
        # Offer Playwright attempt
        _try_playwright_fallback(html)
        return

    log.info(f"Found {len(links)} spreadsheet link(s) in FY2025 Q4 section:")
    for i, link in enumerate(links, 1):
        log.info(f"  {i:2}. {link['label'][:80]}")
        log.info(f"      {link['url']}")

    # 3. Download each file
    ok, failed = 0, 0
    for link in links:
        dest = OUTPUT_DIR / link["filename"]
        success = download_file(link["url"], dest)
        if success:
            ok += 1
        else:
            failed += 1
        sleep = SLEEP_BETWEEN_DOWNLOADS + random.uniform(0, SLEEP_JITTER)
        time.sleep(sleep)

    log.info("=" * 60)
    log.info(f"Done. {ok} downloaded, {failed} failed.")
    log.info(f"Files saved to: {OUTPUT_DIR}")
    log.info("=" * 60)


def _try_playwright_fallback(existing_html: str):
    """
    If the initial HTML had no Q4 links (JS-rendered page),
    try Playwright to get the fully-rendered DOM.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info(
            "Playwright not installed. Install it with:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
            "Then re-run this script."
        )
        return

    log.info("Trying Playwright for JS-rendered content...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENTS[0])
        page.goto(TARGET_URL, wait_until="networkidle", timeout=45_000)
        # Try clicking the FY2025 Q4 accordion if present
        try:
            # Common USCIS accordion pattern
            page.click("text=Quarter 4", timeout=5000)
            time.sleep(2)
        except Exception:
            pass
        html = page.content()
        browser.close()

    links = find_q4_links(html, TARGET_URL)
    if not links:
        log.error("Playwright also found no links. The section header text may differ.")
        # Dump a snippet to help debug
        log.info("Dumping headings found on page for debugging:")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for h in soup.find_all(["h2", "h3", "h4", "summary", "button"])[:30]:
            log.info(f"  <{h.name}> {h.get_text(strip=True)[:100]}")
        return

    log.info(f"Playwright found {len(links)} link(s).")
    ok = 0
    for link in links:
        dest = OUTPUT_DIR / link["filename"]
        if download_file(link["url"], dest):
            ok += 1
        time.sleep(SLEEP_BETWEEN_DOWNLOADS + random.uniform(0, SLEEP_JITTER))
    log.info(f"Playwright run: {ok}/{len(links)} downloaded.")


if __name__ == "__main__":
    main()
