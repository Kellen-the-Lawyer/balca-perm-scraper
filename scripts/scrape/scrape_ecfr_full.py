#!/usr/bin/env python3
"""
scrape_ecfr_full.py — Download all 50 CFR titles from eCFR
============================================================
Fetches every part of every title via the eCFR versioner XML API and
saves cleaned plain-text files to a local directory, organized by title.

Files are saved as:
    <OUT_DIR>/<title_num>/<title_num> CFR Part <part> (as of YYYY-MM-DD).txt

This is a scrape-only script. Ingestion into the DB is handled separately
by scripts/ingest/ingest_cfr_full.py.

Usage:
    venv/bin/python3 scripts/scrape/scrape_ecfr_full.py            # all titles
    venv/bin/python3 scripts/scrape/scrape_ecfr_full.py --title 20 # one title
    venv/bin/python3 scripts/scrape/scrape_ecfr_full.py --title 20 --part 655
    venv/bin/python3 scripts/scrape/scrape_ecfr_full.py --dry-run
    venv/bin/python3 scripts/scrape/scrape_ecfr_full.py --skip-complete
    venv/bin/python3 scripts/scrape/scrape_ecfr_full.py --list-titles

Environment (.env or shell):
    CFR_OUT_DIR   output root (default: ~/casebase_cfr)
    CFR_DELAY     seconds between requests (default: 0.5)
"""

import argparse
import logging
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://www.ecfr.gov/api/versioner/v1"
HEADERS = {
    "User-Agent": "Casebase/1.0 (immigration law research; contact kellen@kellenpowell.com)",
    "Accept":     "application/xml",
}

DEFAULT_OUT_DIR = Path(os.environ.get("CFR_OUT_DIR", Path.home() / "casebase_cfr"))
DEFAULT_DELAY   = float(os.environ.get("CFR_DELAY", "0.5"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agency map
# ---------------------------------------------------------------------------

AGENCY_MAP = {
    1: "Office of the Federal Register", 2: "OMB / Grants", 3: "The President",
    4: "GAO", 5: "OPM", 6: "DHS", 7: "USDA", 8: "DHS / USCIS",
    9: "USDA / APHIS", 10: "DOE", 11: "FEC", 12: "Federal Reserve / Banking Regulators",
    13: "SBA", 14: "FAA / DOT", 15: "Commerce / BIS", 16: "FTC",
    17: "SEC / CFTC", 18: "FERC", 19: "CBP", 20: "DOL / ETA",
    21: "FDA", 22: "State Department", 23: "FHWA", 24: "HUD",
    25: "Bureau of Indian Affairs", 26: "IRS", 27: "ATF / TTB", 28: "DOJ / EOIR",
    29: "DOL / WHD", 30: "MSHA / BSEE", 31: "Treasury / FinCEN", 32: "DoD",
    33: "Army Corps / Coast Guard", 34: "DOE / Education", 36: "NPS / Forest Service",
    37: "USPTO / Copyright", 38: "VA", 39: "USPS", 40: "EPA", 41: "GSA",
    42: "HHS / CMS", 43: "BLM / Interior", 44: "FEMA", 45: "HHS / ORR",
    46: "Coast Guard / Maritime", 47: "FCC", 48: "FAR / Acquisition",
    49: "DOT", 50: "FWS / NOAA",
}

# ---------------------------------------------------------------------------
# eCFR API helpers
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _get_json(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError:
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                log.warning(f"Rate limited; sleeping {wait}s")
                time.sleep(wait)
            elif attempt < retries - 1:
                time.sleep(5)
            else:
                raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(5)
            else:
                raise
    return {}


def _get_xml(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=90,
                            headers={**HEADERS, "Accept": "application/xml"})
            r.raise_for_status()
            return r.content
        except requests.HTTPError:
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                log.warning(f"Rate limited; sleeping {wait}s")
                time.sleep(wait)
            elif r.status_code == 404:
                return b""
            elif attempt < retries - 1:
                time.sleep(5)
            else:
                raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(5)
            else:
                raise
    return b""


def get_titles():
    data = _get_json(f"{BASE_URL}/titles.json")
    return [t for t in data.get("titles", []) if not t.get("reserved")]


def get_title_structure(title_num, issue_date):
    url = f"{BASE_URL}/structure/{issue_date}/title-{title_num}.json"
    data = _get_json(url)
    parts = []

    def walk(node):
        if node.get("type") == "part":
            identifier = node.get("identifier", "")
            label = node.get("label_description") or node.get("label", "")
            parts.append({"part": identifier, "name": label.strip()})
        for child in node.get("children", []):
            walk(child)

    walk(data)
    return parts


def get_part_amendment_date(title_num, part, fallback):
    url = f"{BASE_URL}/versions/title-{title_num}/part-{part}.json"
    try:
        data = _get_json(url)
        versions = data.get("content_versions", [])
        if versions:
            raw = versions[0].get("date", "")
            if raw:
                return raw
    except Exception:
        pass
    return fallback

# ---------------------------------------------------------------------------
# XML → plain text
# ---------------------------------------------------------------------------

def xml_to_text(xml_bytes):
    if not xml_bytes:
        return ""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        text = xml_bytes.decode("utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    lines = []

    def walk(node, depth=0):
        tag = (node.tag or "").upper()

        if tag == "SECTION":
            sectno  = node.find("SECTNO")
            subject = node.find("SUBJECT")
            num  = (sectno.text  or "").strip() if sectno  is not None else ""
            subj = (subject.text or "").strip() if subject is not None else ""
            if num:
                lines.append(f"\n§ {num}  {subj}".rstrip())

        elif tag in ("HEAD", "SUBJECT"):
            heading = "".join(node.itertext()).strip()
            if heading:
                prefix = "\n" if depth <= 3 else ""
                lines.append(f"{prefix}{heading}")
            return

        elif tag in ("P", "FP", "FP-1", "FP-2", "FP-DASH", "E"):
            text = "".join(node.itertext()).strip()
            if text:
                lines.append(text)
            return

        elif tag in ("NOTE", "NOTES", "FTREF"):
            text = "".join(node.itertext()).strip()
            if text:
                lines.append(f"[Note: {text}]")
            return

        elif tag == "XTBL":
            for row in node.iter("ROW"):
                cells = ["".join(c.itertext()).strip() for c in row]
                lines.append("\t".join(cells))
            return

        for child in node:
            walk(child, depth + 1)

        tail = (node.tail or "").strip()
        if tail and tag not in ("HEAD", "SUBJECT", "SECTNO", "E"):
            lines.append(tail)

    walk(root)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Per-part download logic
# ---------------------------------------------------------------------------

def output_path(out_dir, title_num, part, amend_date):
    return out_dir / str(title_num) / f"{title_num} CFR Part {part} (as of {amend_date}).txt"


def part_already_downloaded(out_dir, title_num, part):
    title_dir = out_dir / str(title_num)
    if not title_dir.exists():
        return False, None
    matches = (
        list(title_dir.glob(f"{title_num} CFR Part {part} (as of *).txt")) +
        list(title_dir.glob(f"{title_num} CFR Part {part} (up to date as of *).txt")) +
        list(title_dir.glob(f"{title_num} CFR Part {part} (up to date as of *).pdf"))
    )
    return (True, matches[0]) if matches else (False, None)


def download_part(title_num, part, part_name, issue_date, out_dir,
                  dry_run=False, delay=DEFAULT_DELAY):
    already, existing = part_already_downloaded(out_dir, title_num, part)
    if already:
        log.debug(f"    {title_num} CFR Part {part}: already on disk")
        return "skipped"

    if dry_run:
        log.info(f"    {title_num} CFR Part {part}: DRY RUN")
        return "ok"

    amend_date = get_part_amendment_date(title_num, part, issue_date)
    time.sleep(delay * 0.3)

    url = f"{BASE_URL}/full/{issue_date}/title-{title_num}.xml"
    try:
        xml_bytes = _get_xml(url, params={"part": part})
    except Exception as e:
        log.error(f"    {title_num} CFR Part {part}: download error — {e}")
        return "error"

    if not xml_bytes:
        log.warning(f"    {title_num} CFR Part {part}: empty response")
        return "empty"

    text = xml_to_text(xml_bytes)
    if len(text) < 100:
        log.warning(f"    {title_num} CFR Part {part}: text too short ({len(text)} chars)")
        return "empty"

    out = output_path(out_dir, title_num, part, amend_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    log.info(f"    {title_num} CFR Part {part}: ✓ {len(text):,} chars → {out.name}")
    time.sleep(delay)
    return "ok"


# ---------------------------------------------------------------------------
# Title-level loop
# ---------------------------------------------------------------------------

def process_title(title, out_dir, only_part=None, dry_run=False,
                  skip_complete=False, delay=DEFAULT_DELAY):
    title_num  = title["number"]
    issue_date = title.get("latest_issue_date") or date.today().strftime("%Y-%m-%d")
    agency     = AGENCY_MAP.get(title_num, "Federal")

    log.info(f"\n{'─'*60}")
    log.info(f"Title {title_num}: {title['name']} [{agency}]  (issue: {issue_date})")

    parts = get_title_structure(title_num, issue_date)
    if not parts:
        log.warning(f"  No parts found for Title {title_num}")
        return {"ok": 0, "skipped": 0, "empty": 0, "error": 0, "total": 0}

    if only_part:
        parts = [p for p in parts if p["part"] == only_part]
        if not parts:
            log.warning(f"  Part {only_part} not found in Title {title_num}")
            return {"ok": 0, "skipped": 0, "empty": 0, "error": 0, "total": 0}

    log.info(f"  {len(parts)} parts to check")

    if skip_complete and not only_part:
        on_disk = sum(1 for p in parts if part_already_downloaded(out_dir, title_num, p["part"])[0])
        if on_disk == len(parts):
            log.info(f"  All {len(parts)} parts already on disk — skipping")
            return {"ok": 0, "skipped": len(parts), "empty": 0, "error": 0, "total": len(parts)}

    counts = {"ok": 0, "skipped": 0, "empty": 0, "error": 0}
    for p in parts:
        result = download_part(title_num, p["part"], p["name"], issue_date,
                               out_dir, dry_run, delay)
        counts[result] = counts.get(result, 0) + 1

    counts["total"] = len(parts)
    log.info(
        f"  Title {title_num} done: "
        f"{counts['ok']} downloaded, {counts['skipped']} skipped, "
        f"{counts['empty']} empty, {counts['error']} errors"
    )
    return counts

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download all 50 CFR titles from eCFR to plain-text files"
    )
    parser.add_argument("--title",    type=int, default=None,
                        help="Download only this title number (1-50)")
    parser.add_argument("--part",     type=str, default=None,
                        help="Download only this part (requires --title)")
    parser.add_argument("--out-dir",  type=Path, default=DEFAULT_OUT_DIR,
                        help=f"Root output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--delay",    type=float, default=DEFAULT_DELAY,
                        help="Seconds between requests (default: 0.5)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="List what would be downloaded without downloading")
    parser.add_argument("--skip-complete", action="store_true",
                        help="Skip titles where all parts are already on disk")
    parser.add_argument("--list-titles", action="store_true",
                        help="Print title list and exit")
    args = parser.parse_args()

    if args.part and not args.title:
        parser.error("--part requires --title")

    out_dir = args.out_dir
    log.info(f"Output directory: {out_dir}")

    titles = get_titles()

    if args.list_titles:
        print(f"\n{'#':>3}  {'Name':<45}  {'Agency':<35}  Issue date")
        print("─" * 110)
        for t in titles:
            print(f"{t['number']:>3}  {t['name']:<45}  "
                  f"{AGENCY_MAP.get(t['number'], 'Federal'):<35}  "
                  f"{t.get('latest_issue_date', '?')}")
        return

    if args.title:
        titles = [t for t in titles if t["number"] == args.title]
        if not titles:
            log.error(f"Title {args.title} not found or is reserved")
            sys.exit(1)

    total_ok = total_skipped = total_empty = total_error = total_parts = 0
    start = time.time()

    for title in titles:
        counts = process_title(
            title=title,
            out_dir=out_dir,
            only_part=args.part if args.title else None,
            dry_run=args.dry_run,
            skip_complete=args.skip_complete,
            delay=args.delay,
        )
        total_ok      += counts["ok"]
        total_skipped += counts["skipped"]
        total_empty   += counts["empty"]
        total_error   += counts["error"]
        total_parts   += counts["total"]

    elapsed = time.time() - start
    log.info(f"\n{'='*60}")
    log.info(f"COMPLETE in {elapsed/60:.1f} min")
    log.info(f"  Parts checked  : {total_parts:,}")
    log.info(f"  Downloaded     : {total_ok:,}")
    log.info(f"  Skipped        : {total_skipped:,} (already on disk)")
    log.info(f"  Empty / 404    : {total_empty:,}")
    log.info(f"  Errors         : {total_error:,}")
    log.info(f"\nNext: run ingest_cfr_full.py --ingest")
    log.info(f"  venv/bin/python3 scripts/ingest/ingest_cfr_full.py --ingest")


if __name__ == "__main__":
    main()
