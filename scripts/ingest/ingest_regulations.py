#!/usr/bin/env python3
"""
Casebase — Regulations Ingestion
=================================
Usage:  python ingest_regulations.py [--dir /path/to/regulations]
"""
import argparse, asyncio, logging, os, re
from pathlib import Path
from datetime import datetime
import asyncpg, pdfplumber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DIR = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/Regulations"

# Parse "8 CFR Part 214 (up to date as of 1-09-2026).pdf" and
# "41 CFR Part 301-10 (as of 2026-06-11).txt" (dashed parts) and
# ISO dates "2026-06-11".
FILENAME_RE = re.compile(
    r"^(\d+)\s+CFR\s+Part\s+([\w]+(?:-[\w]+)*)\s*\(.*?"
    r"(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE
)

# Section headers like "§ 214.1 Requirements for..." — anchored to line
# start (MULTILINE) so mid-sentence cross-references ("under § 1.4 of this
# chapter") are not mistaken for section headings. Section token must be
# followed by whitespace, killing glued-word artifacts like "214.1and".
SECTION_RE = re.compile(
    r"^\s*§§?\s*(\d+[a-z]?(?:-\d+[a-z]?)?\.\d+[a-z]?(?:-\d+)?)\s+(\S.*)$",
    re.MULTILINE
)

AGENCY_MAP = {
    8:  "DHS / USCIS",
    20: "DOL / ETA",
    22: "State Department",
    29: "DOL / WHD",
}

PART_NAMES = {
    # 8 CFR key parts
    "103": "Fees, Waivers, and Guarantors",
    "204": "Immigrant Petitions",
    "205": "Revocation of Approval",
    "207": "Admission of Refugees",
    "208": "Asylum and Withholding",
    "209": "Adjustment of Status of Refugees",
    "210": "Special Agricultural Workers",
    "211": "Reentry Permits",
    "212": "Documentary Requirements / Grounds of Inadmissibility",
    "213": "Bonding Requirements",
    "214": "Nonimmigrant Classes",
    "215": "Controls of Aliens Departing",
    "216": "Conditional Permanent Residence",
    "235": "Inspection of Persons Applying for Admission",
    "240": "Removal Proceedings",
    "241": "Apprehension and Detention",
    "244": "Temporary Protected Status",
    "245": "Adjustment of Status",
    "245a": "Legalization of Undocumented Aliens",
    "248": "Change of Nonimmigrant Classification",
    "264": "Registration",
    "270": "Penalties for Unlawful Employment",
    "274a": "Control of Employment of Aliens",
    "292": "Representation and Appearances",
    "316": "General Requirements for Naturalization",
    "319": "Special Classes of Persons — Naturalization",
    # 20 CFR
    "655": "H-2A / H-2B Temporary Worker Certifications",
    "656": "PERM Labor Certification",
    # 22 CFR
    "40":  "Visas: Grounds of Inadmissibility",
    "41":  "Visas: Nonimmigrant Visas",
    "42":  "Visas: Immigrant Visas",
    "62":  "Exchange Visitor Program",
    # 29 CFR
    "1":   "Procedures for Predetermination of Wage Rates (Davis-Bacon)",
    "18":  "Rules of Practice and Procedure — OALJ (H-1B / H-2 Hearings)",
    "500": "Migrant and Seasonal Agricultural Worker Protection",
    "501": "H-2A Agricultural Worker Contractual Obligations",
    "502": "H-2A Alien Agricultural Workers — Enforcement",
    "503": "H-2B Nonimmigrant Non-Agricultural Workers — Enforcement",
    "504": "Nonimmigrant Nurses — Attestations (H-1C)",
    "506": "Alien Crewmembers — Longshore Attestations",
    "507": "H-1B Labor Condition Applications",
    "508": "F-1 Students — Off-Campus Work Attestations",
    "516": "FLSA Recordkeeping — Records to Be Kept by Employers",
    "541": "FLSA White-Collar Exemptions (Specialty Occupation Context)",
    "778": "FLSA Overtime Compensation",
    "810": "USMCA High-Wage Labor Value Content Requirements",
}

def parse_date(s):
    for fmt in ["%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None

def extract_regulation(pdf_path: str) -> dict:
    path = Path(pdf_path)
    result = {
        "filename": path.name,
        "pdf_path": str(path),
        "title": path.stem,
        "cfr_title": None,
        "cfr_part": None,
        "part_name": None,
        "agency": None,
        "as_of_date": None,
        "page_count": 0,
        "full_text": "",
        "sections": [],
    }

    m = FILENAME_RE.match(path.name)
    if m:
        result["cfr_title"] = int(m.group(1))
        result["cfr_part"] = m.group(2).lower().strip()
        result["as_of_date"] = parse_date(m.group(3))
        result["agency"] = AGENCY_MAP.get(result["cfr_title"], "Federal")
        result["part_name"] = PART_NAMES.get(result["cfr_part"])
        result["title"] = f"{m.group(1)} CFR Part {m.group(2)}"

    try:
        if path.suffix.lower() == ".txt":
            result["full_text"] = path.read_text(encoding="utf-8", errors="replace")
            result["page_count"] = max(1, len(result["full_text"]) // 3000)
        else:
            pages = []
            with pdfplumber.open(pdf_path) as pdf:
                result["page_count"] = len(pdf.pages)
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
            result["full_text"] = "\n\n".join(pages)
    except Exception as e:
        log.error(f"PDF error {path.name}: {e}")
        return result

    # Extract section index from the FULL text (no 50K cap — § 214.1 alone
    # nearly fills 50K chars). Filter to the doc's own part when known, so
    # quoted cross-part references never pollute the index.
    result["sections"] = extract_sections(result["full_text"], result["cfr_part"])
    return result


def extract_sections(full_text: str, cfr_part: str | None) -> list[dict]:
    seen = set()
    sections = []
    prefix = f"{cfr_part}." if cfr_part else None
    for sm in SECTION_RE.finditer(full_text):
        sec = sm.group(1)
        if prefix and not sec.lower().startswith(prefix.lower()):
            continue
        if sec not in seen:
            seen.add(sec)
            sections.append({
                "section": sec,
                "title": sm.group(2).strip()[:120],
            })
    return sections

async def main(pdf_dir, db_url):
    conn = await asyncpg.connect(db_url)
    pdfs = sorted(Path(pdf_dir).glob("*.pdf")) + sorted(Path(pdf_dir).glob("*.txt"))
    log.info(f"Found {len(pdfs)} regulation files")

    processed = errors = 0
    for path in pdfs:
        data = extract_regulation(str(path))
        try:
            import json
            # Same part under a DIFFERENT filename (fresh scrape) → replace,
            # never duplicate. Keep an existing PDF path if the new source is
            # a .txt (so the "View PDF" button keeps working), and purge the
            # replaced doc's rag_chunks so retrieval never sees stale text.
            if data["cfr_title"] is not None and data["cfr_part"]:
                stale = await conn.fetch("""
                    SELECT id, pdf_path FROM regulations_docs
                    WHERE cfr_title = $1 AND lower(cfr_part) = lower($2)
                      AND filename <> $3
                """, data["cfr_title"], data["cfr_part"], data["filename"])
                if stale:
                    if data["pdf_path"].endswith(".txt"):
                        for s in stale:
                            if (s["pdf_path"] or "").lower().endswith(".pdf"):
                                data["pdf_path"] = s["pdf_path"]
                                break
                    ids = [str(s["id"]) for s in stale]
                    await conn.execute(
                        "DELETE FROM rag_chunks WHERE corpus='regulation' AND source_id = ANY($1)", ids)
                    await conn.execute(
                        "DELETE FROM regulations_docs WHERE id = ANY($1)",
                        [s["id"] for s in stale])
                    log.info(f"  ↻ replaced stale doc id(s) {ids} for {data['title']}")
            await conn.execute("""
                INSERT INTO regulations_docs
                  (filename, pdf_path, title, cfr_title, cfr_part, part_name,
                   agency, as_of_date, page_count, full_text, sections)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (filename) DO UPDATE SET
                  full_text  = EXCLUDED.full_text,
                  sections   = EXCLUDED.sections,
                  page_count = EXCLUDED.page_count,
                  as_of_date = EXCLUDED.as_of_date
            """,
                data["filename"], data["pdf_path"], data["title"],
                data["cfr_title"], data["cfr_part"], data["part_name"],
                data["agency"], data["as_of_date"], data["page_count"],
                data["full_text"], json.dumps(data["sections"]),
            )
            processed += 1
            log.info(f"  ✓ {data['title']} ({data['page_count']}pp, {len(data['sections'])} sections)")
        except Exception as e:
            log.error(f"  ✗ {data['filename']}: {e}")
            errors += 1

    await conn.close()
    log.info(f"Done. Processed: {processed}, Errors: {errors}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--db-url", default=os.environ.get(
        "DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"))
    args = parser.parse_args()
    asyncio.run(main(args.dir, args.db_url))
