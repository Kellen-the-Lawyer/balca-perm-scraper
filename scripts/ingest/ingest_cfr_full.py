#!/usr/bin/env python3
"""
ingest_cfr_full.py — Ingest all downloaded CFR parts into the DB
=================================================================
Reads plain-text files produced by scrape_ecfr_full.py and loads them into:

  regulations_docs — ALL parts, all 50 titles (full_text, metadata, section index)
  rag_chunks       — ONLY the titles in EMBED_TITLES (immigration-relevant)

TWO-PHASE DESIGN (Option C):
  --ingest  Load all .txt files into regulations_docs + pre-chunk EMBED_TITLES
  --embed   Embed pending rag_chunks for EMBED_TITLES (run on Mini)
  --status  Coverage report

EMBED_TITLES (immigration-relevant, embed immediately):
    8   Aliens & Nationality (DHS/USCIS)
   20   Employees' Benefits (DOL/ETA — PERM, H-1B)
   22   Foreign Relations (State Dept — visas)
   28   Judicial Administration (DOJ/EOIR — removal, BIA)
   29   Labor (DOL/WHD — FLSA, H-2A/H-2B enforcement)
   45   Public Welfare (HHS/ORR — refugee resettlement)

All other titles: stored in regulations_docs for full-text search and
future embedding; NOT chunked into rag_chunks yet.

Usage:
    venv/bin/python3 scripts/ingest/ingest_cfr_full.py --ingest
    venv/bin/python3 scripts/ingest/ingest_cfr_full.py --embed
    venv/bin/python3 scripts/ingest/ingest_cfr_full.py --embed --title 20
    venv/bin/python3 scripts/ingest/ingest_cfr_full.py --status
    venv/bin/python3 scripts/ingest/ingest_cfr_full.py --ingest --title 20 --reset

Environment (.env):
    DATABASE_URL        postgresql://perm:perm_local_pw@localhost:5432/perm_decisions
    CFR_OUT_DIR         ~/casebase_cfr
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_URL      = os.environ.get("DATABASE_URL",
              "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
CFR_OUT_DIR = Path(os.environ.get("CFR_OUT_DIR", Path.home() / "casebase_cfr"))
CORPUS      = "regulation"

CHUNK_TOKENS   = 800
OVERLAP_TOKENS = 80
EMBED_DIM      = 1024

# All titles are now chunked into rag_chunks (EMBED_TITLES restriction removed)
EMBED_TITLES = set()  # kept for status report backward compat only

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

# Supplement part names not reliably in the eCFR label field
PART_NAMES = {
    "8_103": "Fees, Waivers, and Guarantors",
    "8_204": "Immigrant Petitions",
    "8_205": "Revocation of Approval of Petitions",
    "8_207": "Admission of Refugees",
    "8_208": "Procedures for Asylum and Withholding of Removal",
    "8_209": "Adjustment of Status of Refugees and Asylees",
    "8_210": "Special Agricultural Workers",
    "8_212": "Documentary Requirements; Nonimmigrants; Waivers",
    "8_213": "Bonding Requirements",
    "8_214": "Nonimmigrant Classes",
    "8_215": "Controls of Aliens Departing from the United States",
    "8_216": "Conditional Basis of Lawful Permanent Residence Status",
    "8_235": "Inspection of Persons Applying for Admission",
    "8_240": "Removal Proceedings",
    "8_241": "Apprehension and Detention of Aliens Ordered Removed",
    "8_244": "Temporary Protected Status",
    "8_245": "Adjustment of Status to That of Person Admitted for Permanent Residence",
    "8_245a": "Adjustment of Status — Legalization of Undocumented Aliens",
    "8_248": "Change of Nonimmigrant Classification",
    "8_264": "Registration and Fingerprinting of Aliens",
    "8_270": "Penalties for Unlawful Employment of Aliens",
    "8_274a": "Control of Employment of Aliens",
    "8_292": "Representation and Appearances",
    "8_316": "General Requirements for Naturalization",
    "8_319": "Special Classes of Persons Who May Be Naturalized",
    "8_1003": "Executive Office for Immigration Review",
    "8_1208": "Procedures for Asylum and Withholding of Removal (EOIR)",
    "8_1240": "Proceedings to Determine Removability of Aliens",
    "8_1245": "Adjustment of Status (EOIR)",
    "20_655": "Temporary Employment of Foreign Workers in the United States",
    "20_656": "Labor Certification Process for Permanent Employment of Aliens (PERM)",
    "22_40": "Visas: Documentation of Nonimmigrants",
    "22_41": "Visas: Visas",
    "22_42": "Visas: Documentation of Immigrants",
    "22_62": "Exchange Visitor Program",
    "28_44": "Unfair Immigration-Related Employment Practices",
    "28_68": "Rules of Practice and Procedure — OCAHO",
    "29_1": "Procedures for Predetermination of Wage Rates (Davis-Bacon)",
    "29_18": "Rules of Practice and Procedure — Office of Administrative Law Judges",
    "29_500": "Migrant and Seasonal Agricultural Worker Protection",
    "29_501": "Obligations for Temporary Alien Agricultural Labor Contractors",
    "29_502": "Enforcement — Temporary Alien Agricultural Workers",
    "29_503": "Enforcement — Temporary Nonimmigrant Non-Agricultural Workers",
    "29_507": "Labor Condition Applications for Nonimmigrant Workers (H-1B)",
    "29_516": "FLSA Recordkeeping — Records to Be Kept by Employers",
    "29_541": "FLSA White-Collar Exemptions",
    "29_778": "FLSA Overtime Compensation",
    "29_810": "USMCA High-Wage Labor Value Content Requirements",
    "45_400": "Refugee Resettlement Program",
    "45_410": "Refugee Cash and Medical Assistance Programs",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

SECTION_RE = re.compile(r"§\s*(\d+[\w.]*)\s+(.+?)(?:\n|$)")

# ---------------------------------------------------------------------------
# Chunking (standard project algorithm)
# ---------------------------------------------------------------------------

def approx_tokens(text):
    return max(1, len(text) // 4)

def _tail_str(text, n_tokens):
    chars = n_tokens * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(" ")
    return (snippet[idx + 1:] if idx > 0 else snippet) + " "

def _split_long(text, target):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts, buf, buf_tokens = [], [], 0
    for s in sentences:
        st = approx_tokens(s)
        if buf_tokens + st > target and buf:
            parts.append(" ".join(buf))
            buf, buf_tokens = [], 0
        buf.append(s)
        buf_tokens += st
    if buf:
        parts.append(" ".join(buf))
    return parts

def chunk_by_paragraphs(text, target=CHUNK_TOKENS, overlap=OVERLAP_TOKENS):
    if not text or not text.strip():
        return []
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current_parts, current_tokens, overlap_tail = [], [], 0, ""

    for para in paragraphs:
        para_tokens = approx_tokens(para)
        if para_tokens > target * 1.5:
            if current_parts:
                chunks.append(overlap_tail + " ".join(current_parts))
                overlap_tail = _tail_str(" ".join(current_parts), overlap)
                current_parts, current_tokens = [], 0
            for sub in _split_long(para, target):
                chunks.append(overlap_tail + sub)
                overlap_tail = _tail_str(sub, overlap)
            continue
        if current_tokens + para_tokens > target and current_parts:
            chunks.append(overlap_tail + " ".join(current_parts))
            overlap_tail = _tail_str(" ".join(current_parts), overlap)
            current_parts, current_tokens = [], 0
        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        chunks.append(overlap_tail + " ".join(current_parts))

    return [c.strip() for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Filename parser
# ---------------------------------------------------------------------------

# New:    "8 CFR Part 214 (as of 2026-06-11).txt"
# Legacy: "29 CFR Part 541 (up to date as of 3-20-2026).pdf"
FILENAME_RE = re.compile(
    r"^(\d+)\s+CFR\s+Part\s+([\w.]+)"
    r".*?(?:as of\s+)(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.IGNORECASE,
)

def parse_date_str(s):
    for fmt in ["%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y"]:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None

def parse_filename(path):
    m = FILENAME_RE.match(path.stem)
    if not m:
        return None
    title_num = int(m.group(1))
    part      = m.group(2).lower().strip()
    as_of     = parse_date_str(m.group(3))
    key       = f"{title_num}_{part}"
    return {
        "title_num": title_num,
        "part":      part,
        "as_of":     as_of,
        "agency":    AGENCY_MAP.get(title_num, "Federal"),
        "part_name": PART_NAMES.get(key, ""),
    }

def extract_sections(text):
    seen, sections = set(), []
    for m in SECTION_RE.finditer(text[:60_000]):
        sec = m.group(1)
        if sec not in seen:
            seen.add(sec)
            sections.append({"section": sec, "title": m.group(2).strip()[:120]})
    return sections


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts, model=None):
    """Delegate to app.embed.embed_documents (Voyage API, voyage-4-large)."""
    import sys, os
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from app.embed import embed_documents
    return embed_documents(texts)

def rebuild_hnsw_index(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        n = cur.fetchone()[0]
    if n < 10:
        return
    log.info(f"Rebuilding HNSW index ({n:,} vectors)...")
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
        cur.execute("""
            CREATE INDEX idx_rag_embedding
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
    conn.commit()
    log.info("HNSW index rebuilt ✓")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def upsert_regulation(conn, data):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO regulations_docs
              (filename, pdf_path, title, cfr_title, cfr_part, part_name,
               agency, as_of_date, page_count, full_text, sections)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (filename) DO UPDATE SET
              full_text  = EXCLUDED.full_text,
              sections   = EXCLUDED.sections,
              page_count = EXCLUDED.page_count,
              as_of_date = EXCLUDED.as_of_date,
              part_name  = COALESCE(EXCLUDED.part_name, regulations_docs.part_name)
            RETURNING id
        """,
            (data["filename"], data["pdf_path"], data["title"],
             data["cfr_title"], data["cfr_part"], data["part_name"],
             data["agency"], data["as_of_date"], data["page_count"],
             data["full_text"], json.dumps(data["sections"]),)
        )
        return cur.fetchone()[0]

CHUNK_UPSERT = """
    INSERT INTO rag_chunks
      (corpus, source_id, source_label, source_date, chunk_index, chunk_text)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE SET
      chunk_text   = EXCLUDED.chunk_text,
      source_label = EXCLUDED.source_label,
      source_date  = EXCLUDED.source_date,
      embedding    = NULL
"""

def ingest_chunks(conn, doc_id, source_label, as_of, chunks):
    rows = [(CORPUS, str(doc_id), source_label, as_of, i, c) for i, c in enumerate(chunks)]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, CHUNK_UPSERT, rows, page_size=200)
    conn.commit()
    return len(rows)

def get_unembedded_chunks(conn, title_num=None):
    sql = """
        SELECT rc.id, rc.chunk_text
        FROM rag_chunks rc
        JOIN regulations_docs rd ON rd.id = rc.source_id::integer
        WHERE rc.corpus = %s AND rc.embedding IS NULL
    """
    params = [CORPUS]
    if title_num is not None:
        sql += " AND rd.cfr_title = %s"
        params.append(title_num)
    sql += " ORDER BY rc.id"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()

# ---------------------------------------------------------------------------
# Phase 1: --ingest
# ---------------------------------------------------------------------------

def run_ingest(conn, title_num, reset, limit):
    if title_num is not None:
        dirs = [CFR_OUT_DIR / str(title_num)]
    else:
        if not CFR_OUT_DIR.exists():
            log.error(f"CFR_OUT_DIR not found: {CFR_OUT_DIR}")
            log.error("Run scrape_ecfr_full.py first.")
            sys.exit(1)
        dirs = sorted(
            [d for d in CFR_OUT_DIR.iterdir() if d.is_dir()],
            key=lambda d: int(d.name) if d.name.isdigit() else 999
        )

    if reset and title_num is not None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM regulations_docs WHERE cfr_title = %s", (title_num,))
        conn.commit()
        log.info(f"Reset: deleted Title {title_num} from regulations_docs")

    total_ok = total_skip = total_err = 0
    processed = 0

    for title_dir in dirs:
        if not title_dir.is_dir():
            continue
        t_num = int(title_dir.name) if title_dir.name.isdigit() else None
        if t_num is None:
            continue

        files = sorted(title_dir.glob("*.txt")) + sorted(title_dir.glob("*.pdf"))
        log.info(f"\nTitle {t_num}: {len(files)} files")

        for path in files:
            if limit and processed >= limit:
                break

            meta = parse_filename(path)
            if not meta:
                log.warning(f"  Unparseable filename: {path.name}")
                total_skip += 1
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                log.error(f"  Read error {path.name}: {e}")
                total_err += 1
                continue

            text = text.replace("\x00", "")
            if len(text) < 50:
                log.warning(f"  Too short: {path.name}")
                total_skip += 1
                continue

            sections  = extract_sections(text)
            cfr_label = f"{meta['title_num']} CFR Part {meta['part']}"

            data = {
                "filename":   path.name,
                "pdf_path":   str(path),
                "title":      cfr_label,
                "cfr_title":  meta["title_num"],
                "cfr_part":   meta["part"],
                "part_name":  meta["part_name"],
                "agency":     meta["agency"],
                "as_of_date": meta["as_of"],
                "page_count": max(1, len(text) // 3000),
                "full_text":  text,
                "sections":   sections,
            }

            try:
                doc_id = upsert_regulation(conn, data)
                conn.commit()
            except Exception as e:
                conn.rollback()
                log.error(f"  DB error {path.name}: {e}")
                total_err += 1
                continue

            chunks = chunk_by_paragraphs(text)
            if chunks:
                label = cfr_label + (f" — {meta['part_name']}" if meta["part_name"] else "")
                n = ingest_chunks(conn, doc_id, label, meta["as_of"], chunks)
                log.info(f"  ✓ {path.name} ({len(text):,} chars, {n} chunks, {len(sections)} §§)")
            else:
                log.info(f"  ✓ {path.name} ({len(text):,} chars, no chunks)")

            total_ok += 1
            processed += 1

    log.info(f"\nIngest: {total_ok} ok, {total_skip} skipped, {total_err} errors")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT cfr_title, COUNT(*) as parts, SUM(length(full_text)) as chars
            FROM regulations_docs GROUP BY cfr_title ORDER BY cfr_title
        """)
        rows = cur.fetchall()

    print(f"\n{'Title':>6}  {'Parts':>6}  {'Chars':>14}")
    print("─" * 32)
    gp = gc = 0
    for title, parts, chars in rows:
        chars = chars or 0
        mark = " ← embed" if title in EMBED_TITLES else ""
        print(f"{title:>6}  {parts:>6}  {chars:>14,}{mark}")
        gp += parts; gc += chars
    print("─" * 32)
    print(f"{'TOTAL':>6}  {gp:>6}  {gc:>14,}")


# ---------------------------------------------------------------------------
# Phase 2: --embed
# ---------------------------------------------------------------------------

def run_embed(conn, title_num, batch_size):
    rows = get_unembedded_chunks(conn, title_num)
    if not rows:
        log.info("No chunks pending embedding.")
        return

    log.info(f"{len(rows):,} chunks to embed (model: voyage-4-large)")
    ok = err = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        ids   = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        try:
            vecs = embed_texts(texts)
            with conn.cursor() as cur:
                for chunk_id, vec in zip(ids, vecs):
                    cur.execute(
                        "UPDATE rag_chunks SET embedding = %s WHERE id = %s",
                        (vec, chunk_id)
                    )
            conn.commit()
            ok += len(batch)
            if ok % 500 == 0 or ok == len(rows):
                log.info(f"  Embedded {ok:,}/{len(rows):,}")
        except Exception as e:
            conn.rollback()
            log.error(f"  Batch error at chunk {i}: {e}")
            err += len(batch)
            time.sleep(5)

    log.info(f"Embedding done: {ok:,} ok, {err:,} errors")
    rebuild_hnsw_index(conn)


# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------

def run_status(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT cfr_title,
                   COUNT(*) as parts,
                   COUNT(*) FILTER (WHERE part_name IS NOT NULL AND part_name != '') as named,
                   SUM(length(full_text)) as chars
            FROM regulations_docs GROUP BY cfr_title ORDER BY cfr_title
        """)
        reg_rows = cur.fetchall()

        cur.execute("""
            SELECT rd.cfr_title,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE rc.embedding IS NOT NULL) as embedded,
                   COUNT(*) FILTER (WHERE rc.embedding IS NULL) as pending
            FROM rag_chunks rc
            JOIN regulations_docs rd ON rd.id = rc.source_id::integer
            WHERE rc.corpus = 'regulation'
            GROUP BY rd.cfr_title ORDER BY rd.cfr_title
        """)
        chunk_map = {r[0]: r for r in cur.fetchall()}

    print(f"\n{'Title':>6}  {'Parts':>6}  {'Chars(M)':>9}  "
          f"{'Chunks':>7}  {'Embedded':>9}  {'Pending':>8}  Note")
    print("─" * 80)
    for title, parts, named, chars in reg_rows:
        chars = chars or 0
        cr = chunk_map.get(title, (None, 0, 0, 0))
        note = "targeted" if title in EMBED_TITLES else "catalog"
        print(
            f"{title:>6}  {parts:>6}  {chars/1e6:>9.1f}  "
            f"{cr[1]:>7,}  {cr[2]:>9,}  {cr[3]:>8,}  {note}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest scraped CFR files into regulations_docs and rag_chunks"
    )
    parser.add_argument("--ingest",     action="store_true")
    parser.add_argument("--embed",      action="store_true")
    parser.add_argument("--status",     action="store_true")
    parser.add_argument("--title",      type=int, default=None)
    parser.add_argument("--reset",      action="store_true",
                        help="Delete existing records for --title before ingesting")
    parser.add_argument("--limit",      type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--db-url",     default=DB_URL)
    args = parser.parse_args()

    if not any([args.ingest, args.embed, args.status]):
        parser.print_help()
        sys.exit(0)

    if args.reset and not args.title:
        parser.error("--reset requires --title (safety guard)")

    conn = psycopg2.connect(args.db_url)
    conn.autocommit = False

    try:
        if args.status:
            run_status(conn)
        if args.ingest:
            run_ingest(conn, args.title, args.reset, args.limit)
        if args.embed:
            run_embed(conn, args.title, args.batch_size)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
