#!/usr/bin/env python3
"""
download_cfr_title29.py — Download immigration-relevant Title 29 CFR parts
===========================================================================
Uses the eCFR versioner API to download XML for all immigration-relevant
Title 29 parts, extracts clean plain text, and saves to the Regulations
folder so ingest_regulations.py picks them up automatically.

Note: eCFR no longer serves PDFs via API — we download XML and convert
to plain text, which the ingest script handles via the --text-dir flag.

Usage:
    venv/bin/python3 scripts/scrape/download_cfr_title29.py
    venv/bin/python3 scripts/scrape/download_cfr_title29.py --dry-run
    venv/bin/python3 scripts/scrape/download_cfr_title29.py --part 541
"""

import argparse
import logging
import re
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

OUT_DIR = Path(
    "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/Regulations"
)

HEADERS = {
    "User-Agent": "Casebase/1.0 (immigration law research; kellen@casebase.law)",
    "Accept": "application/xml",
}

PARTS = [
    (18,  "Rules of Practice and Procedure — OALJ (H-1B / H-2 Hearings)"),
    (541, "FLSA White-Collar Exemptions (Specialty Occupation Context)"),
    (810, "USMCA High-Wage Labor Value Content Requirements"),
    (1,   "Procedures for Predetermination of Wage Rates (Davis-Bacon)"),
    (516, "FLSA Recordkeeping — Records to Be Kept by Employers"),
    (778, "FLSA Overtime Compensation"),
]

def get_last_issue_date() -> str:
    """Fetch the most recent issue date for Title 29 from eCFR."""
    try:
        r = requests.get(
            "https://www.ecfr.gov/api/versioner/v1/titles.json",
            headers=HEADERS, timeout=15,
        )
        if r.ok:
            for t in r.json().get("titles", []):
                if t.get("number") == 29:
                    return t["latest_issue_date"]
    except Exception as e:
        log.warning(f"Could not fetch title date: {e}")
    return date.today().strftime("%Y-%m-%d")


def xml_to_text(xml_bytes: bytes) -> str:
    """
    Extract clean plain text from eCFR XML.
    Preserves section numbers and headings.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Fall back to regex stripping if XML is malformed
        text = xml_bytes.decode("utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s{3,}", "\n\n", text).strip()

    lines = []

    def walk(node, depth=0):
        tag = node.tag.upper() if node.tag else ""

        # Emit section/paragraph markers
        if tag in ("HEAD", "SUBJECT"):
            heading = (node.text or "").strip()
            if heading:
                lines.append(("\n" if depth <= 2 else "") + heading)

        elif tag in ("P", "FP", "FP-1", "FP-2"):
            text = "".join(node.itertext()).strip()
            if text:
                lines.append(text)

        elif tag == "SECTION":
            sectno = node.find("SECTNO")
            subject = node.find("SUBJECT")
            if sectno is not None:
                num = (sectno.text or "").strip()
                subj = (subject.text or "").strip() if subject is not None else ""
                lines.append(f"\n§ {num}  {subj}".rstrip())

        # Recurse into children regardless
        for child in node:
            walk(child, depth + 1)

        # Plain text tail (text after a closing tag)
        tail = (node.tail or "").strip()
        if tail and tag not in ("HEAD", "SUBJECT", "SECTNO"):
            lines.append(tail)

    walk(root)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_as_of_date(part: int, issue_date: str) -> str:
    """
    Get the last-amended date for this specific part.
    Falls back to the title issue date.
    """
    try:
        r = requests.get(
            f"https://www.ecfr.gov/api/versioner/v1/versions/title-29/part-{part}.json",
            headers=HEADERS, timeout=15,
        )
        if r.ok:
            versions = r.json().get("content_versions", [])
            if versions:
                raw = versions[0].get("date", "")
                if raw:
                    y, m, d = raw.split("-")
                    return f"{int(m)}-{int(d)}-{y}"
    except Exception as e:
        log.warning(f"  Could not get amendment date for Part {part}: {e}")
    # Convert issue_date YYYY-MM-DD → M-D-YYYY
    y, m, d = issue_date.split("-")
    return f"{int(m)}-{int(d)}-{y}"


def download_part(part: int, name: str, issue_date: str, dry_run: bool = False) -> bool:
    as_of    = get_as_of_date(part, issue_date)
    filename = f"29 CFR Part {part} (up to date as of {as_of}).txt"
    out_path = OUT_DIR / filename

    # Skip if any version already exists
    existing = (list(OUT_DIR.glob(f"29 CFR Part {part} (up to date as of*).txt")) +
                list(OUT_DIR.glob(f"29 CFR Part {part} (up to date as of*).pdf")))
    if existing:
        log.info(f"  Part {part:4}: already exists → {existing[0].name}")
        return True

    if dry_run:
        log.info(f"  Part {part:4}: DRY RUN → {filename}")
        return True

    log.info(f"  Part {part:4}: downloading {name[:55]}...")
    url = f"https://www.ecfr.gov/api/versioner/v1/full/{issue_date}/title-29.xml"
    try:
        r = requests.get(url, headers=HEADERS, params={"part": str(part)}, timeout=60)
        r.raise_for_status()
        text = xml_to_text(r.content)
        if len(text) < 200:
            log.warning(f"    Suspiciously short text ({len(text)} chars) — skipping")
            return False
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        log.info(f"    ✓ Saved {filename} ({len(text):,} chars)")
        time.sleep(1.0)
        return True
    except Exception as e:
        log.error(f"    ✗ Failed Part {part}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download immigration-relevant Title 29 CFR parts"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--part",    type=int, default=None,
                        help="Download a single part number")
    args = parser.parse_args()

    issue_date = get_last_issue_date()
    log.info(f"Title 29 last issue date: {issue_date}")
    log.info(f"Output directory: {OUT_DIR}")

    parts_to_fetch = PARTS if not args.part else [(args.part, f"29 CFR Part {args.part}")]
    success = failed = 0

    for part, name in parts_to_fetch:
        if download_part(part, name, issue_date, dry_run=args.dry_run):
            success += 1
        else:
            failed += 1

    log.info(f"\n✅ Done. {success} saved, {failed} failed.")
    if not args.dry_run and success:
        log.info(
            "\nNext: run ingest_regulations.py to load into DB.\n"
            "  venv/bin/python3 scripts/ingest/ingest_regulations.py"
        )


if __name__ == "__main__":
    main()
