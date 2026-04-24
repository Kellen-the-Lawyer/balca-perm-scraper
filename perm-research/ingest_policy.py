#!/usr/bin/env python3
"""
Casebase — Policy Manuals Ingestion
=====================================
Sources:
  1. FAM  — 205 individual PDFs in /Resources/FAM/
  2. USCIS Policy Manual — single 1,435-page PDF

Usage:
  python ingest_policy.py [--source all|fam|uscis_pm]
"""
import argparse, asyncio, logging, os, re
from pathlib import Path
from datetime import datetime
import asyncpg, pdfplumber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

FAM_DIR   = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/FAM"
USCIS_PM  = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/Policy Manual/Policy Manual _ USCIS.pdf"
DB_URL    = "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"

# Parse FAM filename: "8 FAM 302.1 PROCEDURES FOR DETERMINING CITIZENSHIP.pdf"
FAM_RE = re.compile(r"^(8 FAM [\d.]+)\s+(.+?)\.pdf$", re.IGNORECASE)

# USCIS PM section headers (Volume X, Part Y, Chapter Z patterns)
PM_SECTION_RE = re.compile(
    r"^(Volume\s+\d+[,\s]+Part\s+[A-Z][,\s]+Chapter\s+\d+|"
    r"Volume\s+\d+[,\s]+Part\s+[A-Z]|"
    r"Volume\s+\d+)\s*[–—-]\s*(.+)$",
    re.MULTILINE | re.IGNORECASE
)

def parse_fam_pdf(path: str) -> dict:
    fname = Path(path).name
    result = {
        "filename": fname, "pdf_path": path,
        "source": "FAM", "title": fname.replace(".pdf", ""),
        "section": None, "subject": None,
        "as_of_date": None, "page_count": 0, "full_text": "",
    }
    m = FAM_RE.match(fname)
    if m:
        result["section"] = m.group(1)
        result["subject"] = m.group(2).title()
        result["title"] = f"{m.group(1)} — {result['subject']}"

    try:
        pages = []
        with pdfplumber.open(path) as pdf:
            result["page_count"] = len(pdf.pages)
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        result["full_text"] = "\n\n".join(pages)

        # Extract as-of date from first page text
        date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", result["full_text"][:300])
        if date_m:
            try:
                d = datetime.strptime(date_m.group(1), "%m/%d/%y").date()
                result["as_of_date"] = d
            except ValueError:
                try:
                    d = datetime.strptime(date_m.group(1), "%m/%d/%Y").date()
                    result["as_of_date"] = d
                except ValueError:
                    pass
    except Exception as e:
        log.error(f"FAM PDF error {fname}: {e}")
    return result


def split_uscis_pm(path: str) -> list[dict]:
    """
    Split the 1,435-page USCIS PM into logical chunks by volume/part.
    Each chunk becomes a separate row in policy_docs for searchability.
    """
    log.info("Extracting USCIS Policy Manual (this takes a few minutes)...")
    chunks = []
    current_volume = None
    current_pages = []
    current_section = "Introduction"
    current_subject = "Policy Manual Introduction"

    try:
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages)
            log.info(f"  {total} pages total")

            for i, page in enumerate(pdf.pages):
                if i % 100 == 0:
                    log.info(f"  Processing page {i+1}/{total}...")

                text = page.extract_text() or ""

                # Detect volume/part headers to split chunks
                vol_m = re.search(
                    r"(Volume\s+[IVX\d]+[,\s–—-]+(?:Part\s+[A-Z])?)",
                    text[:300], re.IGNORECASE
                )
                if vol_m and i > 5:  # skip intro pages
                    vol_label = vol_m.group(1).strip()
                    if current_volume and vol_label != current_volume and len(current_pages) > 3:
                        # Save current chunk
                        chunks.append({
                            "filename": f"USCIS_PM_{current_section.replace(' ','_').replace(',','').replace('/','_')[:60]}.txt",
                            "pdf_path": path,
                            "source": "USCIS_PM",
                            "title": f"USCIS Policy Manual — {current_subject}",
                            "section": current_section,
                            "subject": current_subject,
                            "as_of_date": datetime(2026, 2, 3).date(),
                            "page_count": len(current_pages),
                            "full_text": "\n\n".join(current_pages),
                        })
                        current_pages = []

                    current_volume = vol_label
                    # Try to extract descriptive subject
                    subj_m = re.search(r"(?:Part\s+[A-Z]\s*[–—-]\s*)(.+?)(?:\n|$)", text[:400])
                    if subj_m:
                        current_subject = subj_m.group(1).strip()[:120]
                    else:
                        current_subject = vol_label
                    current_section = vol_label

                current_pages.append(text)

            # Save last chunk
            if current_pages:
                chunks.append({
                    "filename": f"USCIS_PM_{current_section.replace(' ','_').replace(',','').replace('/','_')[:60]}.txt",
                    "pdf_path": path,
                    "source": "USCIS_PM",
                    "title": f"USCIS Policy Manual — {current_subject}",
                    "section": current_section,
                    "subject": current_subject,
                    "as_of_date": datetime(2026, 2, 3).date(),
                    "page_count": len(current_pages),
                    "full_text": "\n\n".join(current_pages),
                })

    except Exception as e:
        log.error(f"USCIS PM error: {e}")

    # Deduplicate filenames
    seen = {}
    for c in chunks:
        fn = c["filename"]
        if fn in seen:
            seen[fn] += 1
            c["filename"] = fn.replace(".txt", f"_{seen[fn]}.txt")
        else:
            seen[fn] = 0

    log.info(f"  Split into {len(chunks)} sections")
    return chunks


async def upsert(conn, data: dict):
    await conn.execute("""
        INSERT INTO policy_docs
          (filename, pdf_path, source, title, section, subject,
           as_of_date, page_count, full_text)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (filename) DO UPDATE SET
          full_text  = EXCLUDED.full_text,
          title      = EXCLUDED.title,
          subject    = EXCLUDED.subject,
          page_count = EXCLUDED.page_count
    """,
        data["filename"], data["pdf_path"], data["source"],
        data["title"], data["section"], data["subject"],
        data["as_of_date"], data["page_count"], data["full_text"],
    )


async def main(source, db_url):
    conn = await asyncpg.connect(db_url)
    processed = errors = 0

    if source in ("all", "fam"):
        fam_pdfs = sorted(Path(FAM_DIR).glob("*.pdf"))
        log.info(f"Ingesting {len(fam_pdfs)} FAM PDFs...")
        for path in fam_pdfs:
            data = parse_fam_pdf(str(path))
            try:
                await upsert(conn, data)
                processed += 1
                log.info(f"  ✓ {data['section'] or data['filename']} ({data['page_count']}pp)")
            except Exception as e:
                log.error(f"  ✗ {data['filename']}: {e}")
                errors += 1

    if source in ("all", "uscis_pm"):
        chunks = split_uscis_pm(USCIS_PM)
        log.info(f"Ingesting {len(chunks)} USCIS PM sections...")
        for chunk in chunks:
            try:
                await upsert(conn, chunk)
                processed += 1
                log.info(f"  ✓ {chunk['section']} ({chunk['page_count']}pp)")
            except Exception as e:
                log.error(f"  ✗ {chunk['filename']}: {e}")
                errors += 1

    await conn.close()
    log.info(f"\nDone. Processed: {processed}, Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["all","fam","uscis_pm"], default="all")
    parser.add_argument("--db-url", default=DB_URL)
    args = parser.parse_args()
    asyncio.run(main(args.source, args.db_url))
