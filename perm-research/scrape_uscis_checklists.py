#!/usr/bin/env python3
"""
USCIS Required Evidence Checklist Scraper

Scrapes form-specific evidence checklists from uscis.gov.
Two page formats handled:
  - Accordion (I-129, I-765, I-485, etc.): sections per visa classification
  - Static table / list (N-400, N-600, etc.): single page with table rows

Primary: httpx + BeautifulSoup
Fallback: Playwright (full browser, JS-rendered DOM)

Usage:
    python3 scrape_uscis_checklists.py              # scrape all forms
    python3 scrape_uscis_checklists.py --form I-129 # single form
    python3 scrape_uscis_checklists.py --dry-run    # fetch and print, no file write

Output:
    perm-research/data/uscis_checklists.json
    (also writes per-form JSON for inspection)
"""

import json
import logging
import re
import subprocess
import sys
import time
import random
import argparse
from datetime import date
from pathlib import Path

# ── Dependencies ──────────────────────────────────────────────────────────────

def _ensure_deps():
    try:
        import httpx          # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "httpx", "beautifulsoup4", "lxml"]
        )

_ensure_deps()

import httpx
from bs4 import BeautifulSoup, Tag

# ── Config ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

TODAY = date.today().isoformat()

OUTPUT_DIR = Path(__file__).resolve().parent / "data"

# All target checklists.  (url, form_number)
# Short /iNNNNChecklist URLs — USCIS canonical checklist pages
# Long /forms/filing-guidance/checklist-of-required-initial-evidence-for-form-... URLs
# Form pages used for I-131, I-290B, N-600 (no standalone checklist page)
CHECKLIST_TARGETS = [
    ("https://www.uscis.gov/i-129Checklist",
     "I-129"),
    ("https://www.uscis.gov/forms/filing-guidance/checklist-of-required-initial-evidence-for-form-i-765-for-informational-purposes-only",
     "I-765"),
    ("https://www.uscis.gov/n-400",
     "N-400"),
    ("https://www.uscis.gov/forms/filing-guidance/checklist-of-required-initial-evidence-for-form-i-140-for-informational-purposes-only",
     "I-140"),
    ("https://www.uscis.gov/forms/filing-guidance/checklist-of-required-initial-evidence-for-form-i-485-for-informational-purposes-only",
     "I-485"),
    ("https://www.uscis.gov/i-539Checklist",
     "I-539"),
    ("https://www.uscis.gov/i-130",
     "I-130"),
    ("https://www.uscis.gov/i-131",
     "I-131"),
    ("https://www.uscis.gov/i-290b",
     "I-290B"),
    ("https://www.uscis.gov/n-600",
     "N-600"),
]

USER_AGENTS = [
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
     "Gecko/20100101 Firefox/125.0"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
     "Chrome/123.0.0.0 Safari/537.36"),
]

SLEEP_BASE   = 1.5
SLEEP_JITTER = 1.0

# ── HTTP fetch with cascade ───────────────────────────────────────────────────

def _browser_headers(ua: str) -> dict:
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
    }


_NOT_FOUND = object()  # sentinel: 404 — don't retry with other tiers


def _httpx_get(url: str, ua: str, timeout: float = 30.0):
    """Returns HTML string, None (transient failure), or _NOT_FOUND (hard 404)."""
    try:
        with httpx.Client(
            timeout=timeout,
            headers=_browser_headers(ua),
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            if resp.status_code == 404:
                return _NOT_FOUND
            if resp.status_code in (403, 429):
                log.warning(f"  {resp.status_code} from httpx")
                return None
            resp.raise_for_status()
            return resp.text if resp.text.strip() else None
    except Exception as e:
        log.warning(f"  httpx error: {type(e).__name__}: {e}")
        return None


def _wget_get(url: str, ua: str) -> str | None:
    out = Path("/tmp/_uscis_checklist_page.html")
    out.unlink(missing_ok=True)
    cmd = [
        "wget", "--quiet",
        f"--user-agent={ua}",
        "--wait=2", "--random-wait",
        "--tries=3", "--timeout=30",
        "--no-check-certificate",
        f"--output-document={out}", url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        log.info("  wget not installed — skipping to Playwright")
        return None
    if result.returncode != 0:
        log.warning(f"  wget failed: {result.stderr[:200]}")
        return None
    content = out.read_text(encoding="utf-8", errors="replace")
    return content if content.strip() else None


def _playwright_get(url: str, ua: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("  Playwright not installed (pip install playwright && playwright install chromium)")
        return None
    log.info("  Tier 5: Playwright")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=ua)
            page.goto(url, wait_until="networkidle", timeout=45_000)
            time.sleep(2)
            content = page.content()
            browser.close()
        return content if content.strip() else None
    except Exception as e:
        log.warning(f"  Playwright error: {e}")
        return None


def fetch_page(url: str) -> str | None:
    """Cascade: httpx (3 UAs) → wget → Playwright.
    Hard 404s short-circuit immediately — no point trying other tiers.
    """
    for i, ua in enumerate(USER_AGENTS):
        log.info(f"  Tier {i+2}: httpx UA[{i}]")
        result = _httpx_get(url, ua)
        if result is _NOT_FOUND:
            log.warning(f"  404 — page does not exist: {url}")
            return None
        if result:
            time.sleep(SLEEP_BASE + random.uniform(0, SLEEP_JITTER))
            return result
        time.sleep(2)

    log.info("  Tier 4: wget")
    html = _wget_get(url, USER_AGENTS[0])
    if html:
        return html

    return _playwright_get(url, USER_AGENTS[0])


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _clean_text(element) -> str:
    """Extract readable text from a BS4 element, collapsing whitespace."""
    if element is None:
        return ""
    text = element.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_empty(text: str) -> bool:
    return not text or len(text.strip()) < 20


def _make_record(form: str, classification: str, content: str, source_url: str) -> dict:
    return {
        "form":             form,
        "classification":   classification,
        "requirement_type": "initial_evidence",
        "content":          content.strip(),
        "source_url":       source_url,
        "scraped_date":     TODAY,
    }


# ── Format A: USWDS Accordion ─────────────────────────────────────────────────

def _parse_accordion(soup: BeautifulSoup, form: str, url: str) -> list[dict]:
    """
    Handle USCIS accordion pages (I-129, I-765, I-485, etc.).

    USCIS uses USWDS (US Web Design System) accordion markup:
      <div class="usa-accordion">
        <h4 class="usa-accordion__heading">
          <button class="usa-accordion__button" ...>Classification Name</button>
        </h4>
        <div class="usa-accordion__content">...</div>
      </div>

    Also handles older patterns with details/summary or div.accordion.
    """
    records: list[dict] = []

    # Strategy 1: USWDS accordion buttons + sibling content divs
    buttons = soup.select("button.usa-accordion__button, button.accordion__button")
    for btn in buttons:
        header_text = btn.get_text(" ", strip=True)
        if not header_text:
            continue
        # The content div follows the heading container
        heading = btn.parent  # <h4 class="usa-accordion__heading">
        if heading:
            content_div = heading.find_next_sibling(
                class_=re.compile(r"accordion.*content|content.*accordion", re.I)
            )
            if content_div is None:
                # Try next sibling of accordion heading parent
                content_div = heading.find_next_sibling("div")
            if content_div:
                content = _clean_text(content_div)
                if not _is_empty(content):
                    records.append(_make_record(form, header_text, content, url))

    if records:
        log.info(f"    USWDS accordion: {len(records)} classification(s)")
        return records

    # Strategy 2: <details>/<summary> elements (older USCIS pages)
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        header_text = summary.get_text(" ", strip=True)
        # Content is everything in <details> except the <summary>
        content_parts = []
        for child in details.children:
            if isinstance(child, Tag) and child.name != "summary":
                t = _clean_text(child)
                if t:
                    content_parts.append(t)
        content = "\n\n".join(content_parts)
        if not _is_empty(content):
            records.append(_make_record(form, header_text, content, url))

    if records:
        log.info(f"    details/summary accordion: {len(records)} classification(s)")
        return records

    # Strategy 3: heading-preceded divs (some USCIS pages use h2/h3 + sibling div)
    for heading in soup.find_all(["h2", "h3", "h4"]):
        header_text = heading.get_text(" ", strip=True)
        if not header_text or len(header_text) > 120:
            continue
        # Look for the first sibling div or ul/ol with real content
        sibling = heading.find_next_sibling(["div", "ul", "ol", "p"])
        if sibling:
            content = _clean_text(sibling)
            if not _is_empty(content):
                records.append(_make_record(form, header_text, content, url))

    if records:
        log.info(f"    heading+sibling: {len(records)} classification(s)")
    return records


# ── Format B: Static HTML Table ───────────────────────────────────────────────

def _parse_table(soup: BeautifulSoup, form: str, url: str) -> list[dict]:
    """
    Handle pages where evidence is listed in HTML tables (N-400, N-600, etc.).

    Each table or table section becomes one record.  If a table has a
    preceding heading (h2/h3), that heading becomes the classification.
    """
    records: list[dict] = []
    tables = soup.find_all("table")

    for table in tables:
        # Find closest preceding heading for classification label
        classification = f"{form} Required Evidence"
        for prev in table.find_previous_siblings():
            if prev.name in ("h2", "h3", "h4", "h5"):
                t = prev.get_text(" ", strip=True)
                if t:
                    classification = t
                    break

        rows_text: list[str] = []
        for row in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if cells:
                rows_text.append(" | ".join(cells))

        content = "\n".join(rows_text)
        if not _is_empty(content):
            records.append(_make_record(form, classification, content, url))

    if records:
        log.info(f"    table format: {len(records)} table(s)")
    return records


# ── Format C: Plain lists ─────────────────────────────────────────────────────

def _parse_lists(soup: BeautifulSoup, form: str, url: str) -> list[dict]:
    """
    Fallback: grab main content area and treat it as a single block.
    Used when neither accordion nor table structure is detected.
    """
    records: list[dict] = []

    # Try to isolate the main content area
    main = (
        soup.find("main")
        or soup.find("div", class_=re.compile(r"main-content|page-content|content", re.I))
        or soup.find("article")
        or soup.find("body")
    )
    if not main:
        return records

    content = _clean_text(main)
    if not _is_empty(content):
        records.append(_make_record(form, f"{form} Required Evidence", content, url))
        log.info(f"    plain-text fallback: 1 block")

    return records


def parse_checklist(html: str, form: str, url: str) -> list[dict]:
    """
    Route page to the correct parser.
    Try accordion first, then table, then plain-list fallback.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove nav, footer, breadcrumbs — they add noise
    for tag in soup.select("nav, footer, header, .usa-breadcrumb, .usa-nav, .usa-banner"):
        tag.decompose()

    # Accordion check (presence of accordion markup signals Format A)
    has_accordion = bool(
        soup.select("button.usa-accordion__button, button.accordion__button")
        or soup.find_all("details")
    )

    records = []
    if has_accordion:
        records = _parse_accordion(soup, form, url)

    if not records:
        records = _parse_table(soup, form, url)

    if not records:
        records = _parse_lists(soup, form, url)

    return records


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape_form(url: str, form: str, dry_run: bool = False) -> list[dict]:
    log.info(f"\nScraping {form}: {url}")
    html = fetch_page(url)
    if not html:
        log.error(f"  Could not fetch {url} — skipping")
        return []

    records = parse_checklist(html, form, url)
    log.info(f"  → {len(records)} record(s) extracted for {form}")

    if not dry_run and records:
        # Save per-form JSON for inspection
        out_file = OUTPUT_DIR / f"checklist_{form.lower().replace('-', '_')}.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(records, indent=2), encoding="utf-8")
        log.info(f"  Saved: {out_file}")

    return records


def main():
    parser = argparse.ArgumentParser(description="Scrape USCIS required evidence checklists")
    parser.add_argument(
        "--form",
        default=None,
        help="Scrape only this form (e.g. I-129, N-400). Default: all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print records but do not write files.",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR / "uscis_checklists.json"),
        help="Path for combined output JSON.",
    )
    args = parser.parse_args()

    targets = CHECKLIST_TARGETS
    if args.form:
        targets = [(u, f) for u, f in CHECKLIST_TARGETS if f.upper() == args.form.upper()]
        if not targets:
            log.error(f"Unknown form '{args.form}'. Available: {[f for _, f in CHECKLIST_TARGETS]}")
            sys.exit(1)

    all_records: list[dict] = []

    for i, (url, form) in enumerate(targets):
        records = scrape_form(url, form, dry_run=args.dry_run)
        all_records.extend(records)
        if i < len(targets) - 1:
            time.sleep(SLEEP_BASE + random.uniform(0, SLEEP_JITTER))

    log.info(f"\n{'='*60}")
    log.info(f"Total: {len(all_records)} records across {len(targets)} form(s)")

    if args.dry_run:
        for r in all_records:
            print(f"\n[{r['form']}] {r['classification']}")
            print(r["content"][:300] + ("..." if len(r["content"]) > 300 else ""))
        return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_records, indent=2), encoding="utf-8")
    log.info(f"Saved combined output: {out_path}")
    log.info(f"Run ingest_uscis_checklists.py --ingest to load into PostgreSQL")


if __name__ == "__main__":
    main()
