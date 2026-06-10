#!/usr/bin/env python3
"""
USCIS Form Instructions — PDF Downloader + Text Extractor

Downloads instruction PDFs from USCIS and extracts text per section,
outputting a JSON file suitable for ingest_form_instructions.py.

Output: perm-research/data/form_instructions.json
        perm-research/data/pdfs/  (raw PDFs cached locally)

Usage:
    python3 scrape_form_instructions.py              # download + extract all
    python3 scrape_form_instructions.py --dry-run    # log only, no writes
    python3 scrape_form_instructions.py --form I-129 # single form
    python3 scrape_form_instructions.py --force      # re-download cached PDFs
"""

import argparse
import io
import json
import logging
import re
import time
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).resolve().parent / "data"
PDF_DIR    = OUTPUT_DIR / "pdfs"
OUTPUT_JSON = OUTPUT_DIR / "form_instructions.json"

CHECKLIST_TARGETS = [
    ("I-129",  "https://www.uscis.gov/sites/default/files/document/forms/i-129instr.pdf"),
    ("I-130",  "https://www.uscis.gov/sites/default/files/document/forms/i-130instr.pdf"),
    ("I-131",  "https://www.uscis.gov/sites/default/files/document/forms/i-131instr.pdf"),
    ("I-140",  "https://www.uscis.gov/sites/default/files/document/forms/i-140instr.pdf"),
    ("I-290B", "https://www.uscis.gov/sites/default/files/document/forms/i-290binstr.pdf"),
    ("I-485",  "https://www.uscis.gov/sites/default/files/document/forms/i-485instr.pdf"),
    ("I-539",  "https://www.uscis.gov/sites/default/files/document/forms/i-539instr.pdf"),
    ("I-765",  "https://www.uscis.gov/sites/default/files/document/forms/i-765instr.pdf"),
    ("N-400",  "https://www.uscis.gov/sites/default/files/document/forms/n-400instr.pdf"),
    ("N-600",  "https://www.uscis.gov/sites/default/files/document/forms/n-600instr.pdf"),
]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Download ──────────────────────────────────────────────────────────────────

def download_pdf(form: str, url: str, force: bool = False) -> bytes | None:
    pdf_path = PDF_DIR / f"{form.lower().replace('-', '_')}_instr.pdf"
    if pdf_path.exists() and not force:
        log.info(f"  Using cached PDF: {pdf_path.name}")
        return pdf_path.read_bytes()

    log.info(f"  Downloading {url}")
    try:
        with httpx.Client(
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=60.0,
        ) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code} — skipping {form}")
            return None
        data = resp.content
        pdf_path.write_bytes(data)
        log.info(f"  Saved {len(data):,} bytes → {pdf_path.name}")
        return data
    except Exception as e:
        log.error(f"  Download failed for {form}: {e}")
        return None

# ── Text extraction ───────────────────────────────────────────────────────────

# Section headings typically appear as ALL-CAPS or Title Case lines
_HEADING_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z\s,\-/()']{4,}"          # ALL-CAPS headings (≥5 chars)
    r"|Part\s+\d+[\.\.].*"               # Part 1. ...
    r"|Section\s+[A-Z\d].*"             # Section A ...
    r"|(?:What Is|Who May|How To|When To|Where To|General|Special)\s+.+"  # common USCIS instruction headers
    r")$"
)


def _clean(text: str) -> str:
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 4 or len(stripped) > 120:
        return False
    return bool(_HEADING_RE.match(stripped))


def extract_sections(pdf_bytes: bytes, form: str, url: str) -> list[dict]:
    """
    Extract text from PDF pages, split into sections by heading detection.
    Returns list of {form, classification, content, ...} dicts.
    """
    today = date.today().isoformat()
    records = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                full_text += text + "\n"
    except Exception as e:
        log.error(f"  pdfplumber failed for {form}: {e}")
        return []

    full_text = _clean(full_text)

    if not full_text.strip():
        log.warning(f"  No text extracted from {form} PDF (may be scanned)")
        return []

    # Split into sections by heading lines
    sections: list[tuple[str, list[str]]] = []
    current_heading = f"{form} Instructions"
    current_lines: list[str] = []

    for line in full_text.splitlines():
        if _is_heading(line):
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    sections.append((current_heading, body))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Final section
    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_heading, body))

    if not sections:
        # Fallback: whole document as one record
        log.info(f"  No sections detected — storing as single document")
        records.append({
            "form": form,
            "classification": "General Instructions",
            "requirement_type": "form_instructions",
            "content": full_text,
            "source_url": url,
            "scraped_date": today,
        })
        return records

    log.info(f"  Extracted {len(sections)} section(s)")
    for heading, body in sections:
        records.append({
            "form": form,
            "classification": heading,
            "requirement_type": "form_instructions",
            "content": body,
            "source_url": url,
            "scraped_date": today,
        })

    return records

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download USCIS form instruction PDFs and extract text"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Log only, do not write any files")
    parser.add_argument("--force", action="store_true",
                        help="Re-download PDFs even if cached")
    parser.add_argument("--form", default=None,
                        help="Only process one form (e.g. I-129)")
    args = parser.parse_args()

    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        PDF_DIR.mkdir(parents=True, exist_ok=True)

    targets = CHECKLIST_TARGETS
    if args.form:
        targets = [(f, u) for f, u in targets if f.upper() == args.form.upper()]
        if not targets:
            log.error(f"Unknown form: {args.form}")
            return

    all_records: list[dict] = []

    for form, url in targets:
        log.info(f"\nProcessing {form}: {url}")

        if args.dry_run:
            log.info("  [dry-run] skipping download")
            continue

        pdf_bytes = download_pdf(form, url, force=args.force)
        if not pdf_bytes:
            continue

        records = extract_sections(pdf_bytes, form, url)
        log.info(f"  → {len(records)} record(s) for {form}")
        all_records.extend(records)

        time.sleep(1.5)  # polite crawl delay

    if args.dry_run:
        log.info("\n[dry-run] No files written.")
        return

    if all_records:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_records, f, indent=2, ensure_ascii=False)
        log.info(f"\n{'='*60}")
        log.info(f"Total: {len(all_records)} records across {len(targets)} form(s)")
        log.info(f"Saved combined output: {OUTPUT_JSON}")
        log.info("Run ingest_form_instructions.py --ingest to load into PostgreSQL")
    else:
        log.warning("No records extracted.")


if __name__ == "__main__":
    main()
