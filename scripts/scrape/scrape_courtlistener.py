#!/usr/bin/env python3
"""
scrape_courtlistener.py — Fetch immigration opinions from CourtListener API v4
===============================================================================
Pulls published circuit court opinions (2000-present) from 13 federal courts,
stores metadata + full text as JSON, ready for ingest_courtlistener.py.

Strategy:
  - Iterates all 13 circuits + SCOTUS via the /clusters/ endpoint
  - Filters: precedential_status=Published, date_filed >= 2000-01-01
  - For each cluster, fetches the lead opinion text (html_with_citations)
  - Strips HTML tags, saves cleaned plain text
  - Cursor-based pagination — no page limits

Usage:
    python3 scripts/scrape/scrape_courtlistener.py --scrape
    python3 scripts/scrape/scrape_courtlistener.py --scrape --court ca9
    python3 scripts/scrape/scrape_courtlistener.py --scrape --since 2020-01-01
    python3 scripts/scrape/scrape_courtlistener.py --status

Output: $COURTLISTENER_DATA_DIR/<court_id>/  (one JSON per cluster)
"""

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN   = os.environ.get("COURTLISTENER_TOKEN", "177d15d21ae11462542b0029637d457c9cb229eb")
BASE    = "https://www.courtlistener.com/api/rest/v4"
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "User-Agent": "Casebase/1.0 (immigration law research; kellen@casebase.law)",
}
DATA_DIR = Path(
    os.environ.get(
        "COURTLISTENER_DATA_DIR",
        str(Path.home() / "courtlistener_opinions"),
    )
)
SLEEP_BETWEEN_REQUESTS = 0.5   # seconds — be polite; CL allows ~5k/day free
SLEEP_ON_429           = 65.0  # back off a full minute on rate-limit
REQUEST_TIMEOUT        = 60    # seconds — clusters endpoint can be slow

COURTS = [
    "scotus", "ca1", "ca2", "ca3", "ca4", "ca5",
    "ca6",    "ca7", "ca8", "ca9", "ca10","ca11", "cadc",
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def api_get(url: str, params: dict | None = None, retries: int = 4) -> dict:
    """GET with retry + 429 back-off. Returns parsed JSON dict."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                log.warning(f"429 rate-limited — sleeping {SLEEP_ON_429}s")
                time.sleep(SLEEP_ON_429)
                continue
            r.raise_for_status()
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            return r.json()
        except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning(f"HTTP error {e} — retry in {wait}s")
            time.sleep(wait)
    return {}


def strip_html(html: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;",  " ", text)
    text = re.sub(r"&amp;",   "&", text)
    text = re.sub(r"&lt;",    "<", text)
    text = re.sub(r"&gt;",    ">", text)
    text = re.sub(r"&quot;",  '"', text)
    text = re.sub(r"&#\d+;",  " ", text)
    text = re.sub(r"\s{3,}",  "\n\n", text)
    return text.strip()


def best_text(opinion: dict) -> str:
    """Return cleaned opinion text from the most reliable available field."""
    for field in ("plain_text", "html_with_citations", "xml_harvard", "html"):
        raw = opinion.get(field) or ""
        if not raw.strip():
            continue
        if field == "plain_text":
            return raw.strip()
        return strip_html(raw)
    return ""


# ── Citation helper ──────────────────────────────────────────────────────────

def format_citation(citations: list[dict]) -> str:
    """Pick the best citation string from the cluster citations list."""
    # Prefer reporter type 1 (official), then 8 (neutral), then first available
    type_priority = {1: 0, 8: 1, 3: 2}
    ranked = sorted(
        citations,
        key=lambda c: type_priority.get(c.get("type"), 9)
    )
    for c in ranked:
        vol, rep, page = c.get("volume"), c.get("reporter"), c.get("page")
        if vol and rep and page:
            return f"{vol} {rep} {page}"
    return ""


# ── Core scrape loop ──────────────────────────────────────────────────────────

def scrape_court(court_id: str, since: str, out_dir: Path, limit: int | None = None) -> tuple[int, int]:
    """
    Paginate through all published opinions for one court since `since` date.
    Uses the /search/ endpoint (fast, cursor-paginated) rather than /clusters/.
    Returns (fetched, skipped) counts.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched = skipped = 0
    next_url = f"{BASE}/search/"
    params = {
        "type":        "o",
        "court":       court_id,
        "filed_after": since,
        "order_by":    "dateFiled asc",
        "page_size":   20,
    }

    while next_url:
        data = api_get(next_url, params=params if "?" not in next_url else None)
        params = None  # subsequent pages: cursor is baked into next_url
        results = data.get("results", [])

        for op in results:
            if limit and fetched >= limit:
                return fetched, skipped

            cluster_id = op.get("cluster_id")
            if not cluster_id:
                continue

            out_file = out_dir / f"{cluster_id}.json"
            if out_file.exists():
                skipped += 1
                continue

            # Fetch full opinion text directly — filter opinions by cluster ID
            opinion_text = opinion_type = opinion_author = ""
            try:
                op_data = api_get(
                    f"{BASE}/opinions/",
                    params={
                        "cluster": cluster_id,
                        "fields": "id,type,author_str,plain_text,"
                                  "html_with_citations,xml_harvard",
                        "page_size": 10,
                    },
                )
                for opinion in op_data.get("results", []):
                    text    = best_text(opinion)
                    op_type = opinion.get("type", "")
                    if text and (not opinion_text or "020lead" in op_type):
                        opinion_text   = text
                        opinion_type   = op_type
                        opinion_author = opinion.get("author_str", "")
                        if "020lead" in op_type:
                            break
            except Exception as e:
                log.warning(f"  Text fetch failed cluster {cluster_id}: {e}")

            record = {
                "cluster_id":          cluster_id,
                "court_id":            court_id,
                "case_name":           op.get("caseName", ""),
                "date_filed":          op.get("dateFiled", ""),
                "citation":            " ".join(op.get("citation", [])),
                "precedential_status": "Published",
                "opinion_type":        opinion_type,
                "author":              opinion_author,
                "full_text":           opinion_text,
                "cl_url": f"https://www.courtlistener.com{op.get('absolute_url', '')}",
            }
            out_file.write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8"
            )
            fetched += 1

            if fetched % 100 == 0:
                log.info(f"  [{court_id}] {fetched} fetched, {skipped} skipped")

        next_url = data.get("next")

    return fetched, skipped


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_status():
    log.info(f"Data directory: {DATA_DIR}")
    if not DATA_DIR.exists():
        print("  (no data directory yet — run --scrape first)")
        return
    total = 0
    for court_id in COURTS:
        court_dir = DATA_DIR / court_id
        count = len(list(court_dir.glob("*.json"))) if court_dir.exists() else 0
        total += count
        print(f"  {court_id:8}  {count:6,} files")
    print(f"  {'TOTAL':8}  {total:6,} files")


def run_scrape(courts: list[str], since: str, limit: int | None = None):
    log.info(f"Scraping {len(courts)} court(s) from {since} → {DATA_DIR}")
    grand_fetched = grand_skipped = 0

    for court_id in courts:
        out_dir = DATA_DIR / court_id
        log.info(f"\n── {court_id.upper()} ──────────────────────")
        try:
            fetched, skipped = scrape_court(court_id, since, out_dir, limit)
        except Exception as e:
            log.error(f"  {court_id} FAILED: {e}")
            continue
        grand_fetched += fetched
        grand_skipped += skipped
        log.info(
            f"  {court_id}: {fetched} new, {skipped} already cached"
        )

    log.info(
        f"\n✅ Done. {grand_fetched} fetched, {grand_skipped} skipped."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scrape CourtListener immigration opinions"
    )
    parser.add_argument(
        "--scrape", action="store_true",
        help="Fetch opinion clusters from CourtListener API",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show file counts per court",
    )
    parser.add_argument(
        "--court", default=None,
        help=f"Single court ID to scrape (default: all). Choices: {', '.join(COURTS)}",
    )
    parser.add_argument(
        "--since", default="2000-01-01",
        help="Only fetch opinions filed on/after this date (YYYY-MM-DD, default: 2000-01-01)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after fetching this many new opinions per court (for testing)",
    )
    args = parser.parse_args()

    if args.status:
        run_status()
    elif args.scrape:
        courts = [args.court] if args.court else COURTS
        unknown = [c for c in courts if c not in COURTS]
        if unknown:
            parser.error(f"Unknown court(s): {unknown}. Valid: {COURTS}")
        run_scrape(courts, args.since, args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
