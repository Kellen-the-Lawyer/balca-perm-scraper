#!/usr/bin/env python3
"""
Ingest USCIS-adopted AAO decisions from the AAO Adopted folder.
Adds a decision_type='adopted' column to precedent_decisions.
"""
import asyncio, logging, os, re
import pdfplumber, asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

FOLDER = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/AAO Adopted"
DB_URL = "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"

ALTER_SQL = """
ALTER TABLE precedent_decisions
  ADD COLUMN IF NOT EXISTS decision_type TEXT NOT NULL DEFAULT 'precedent',
  ADD COLUMN IF NOT EXISTS pm_number     TEXT,
  ADD COLUMN IF NOT EXISTS adopted_num   TEXT;
"""


def parse_adopted_pdf(fpath: str) -> dict:
    with pdfplumber.open(fpath) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    full_text = "\n\n".join(pages)
    text2 = "\n".join(pages[:2])

    # Party name — two formats:
    # "Matter of X-, Adopted Decision YYYY-NN" (new style)
    # "Matter of X (date)" (old style memos)
    party = ""
    adopted_num = ""

    subj_m = re.search(
        r'SUBJECT[:\s]+Matter of ([^,\n]+?)(?:,\s*Adopted Decision\s*([\d]{4}-[\d]+))?(?:\s*\(AAO|\s*\n)',
        text2, re.IGNORECASE
    )
    if subj_m:
        party = subj_m.group(1).strip()
        adopted_num = subj_m.group(2) or ""

    # Fallback for old-style memos
    if not party:
        re_m = re.search(r'Matter of ([^\(]+)\s*\(', text2)
        if re_m:
            party = re_m.group(1).strip()

    # PM number
    pm_m = re.search(r'PM-602-[\d]+', text2)
    pm_number = pm_m.group(0) if pm_m else ""

    # Date
    date_m = re.search(
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})',
        text2
    )
    year = int(date_m.group(3)) if date_m else None
    date_str = date_m.group(0) if date_m else ""

    # Citation = adopted_num if we have it, else pm_number
    citation = f"Adopted {adopted_num}" if adopted_num else f"Adopted {pm_number}" if pm_number else f"Adopted {os.path.basename(fpath)}"

    return {
        "citation":      citation,
        "party_name":    party or os.path.basename(fpath),
        "year":          year,
        "body":          "USCIS AAO Adopted",
        "pdf_url":       f"file://{fpath}",
        "pdf_path":      fpath,
        "full_text":     full_text,
        "pm_number":     pm_number,
        "adopted_num":   adopted_num,
        "decision_type": "adopted",
        "volume":        None,
    }


async def main():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute(ALTER_SQL)
    log.info("Schema updated")

    pdfs = sorted(f for f in os.listdir(FOLDER) if f.endswith('.pdf'))
    log.info(f"Found {len(pdfs)} PDFs in {FOLDER}")

    ok = 0
    for fname in pdfs:
        fpath = os.path.join(FOLDER, fname)
        d = parse_adopted_pdf(fpath)
        log.info(f"  {d['citation']} — {d['party_name']} ({d['year']})")

        await conn.execute("""
            INSERT INTO precedent_decisions
              (volume, citation, party_name, year, body, pdf_url, pdf_path,
               full_text, decision_type, pm_number, adopted_num)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (citation) DO UPDATE SET
              full_text     = EXCLUDED.full_text,
              party_name    = EXCLUDED.party_name,
              pm_number     = EXCLUDED.pm_number,
              adopted_num   = EXCLUDED.adopted_num,
              decision_type = EXCLUDED.decision_type
        """, d["volume"], d["citation"], d["party_name"], d["year"],
             d["body"], d["pdf_url"], d["pdf_path"], d["full_text"],
             d["decision_type"], d["pm_number"], d["adopted_num"])
        ok += 1

    total = await conn.fetchval("SELECT COUNT(*) FROM precedent_decisions")
    by_type = await conn.fetch(
        "SELECT decision_type, COUNT(*) as n FROM precedent_decisions GROUP BY decision_type")
    log.info(f"\nDone. {ok} adopted decisions ingested. Total in DB: {total}")
    for row in by_type:
        log.info(f"  {row['decision_type']}: {row['n']}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
