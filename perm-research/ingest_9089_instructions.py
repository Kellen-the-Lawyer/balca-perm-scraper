#!/usr/bin/env python3
"""
ETA-9089 General Instructions (DOL/OFLC) — RAG Ingestion

Loads the Form ETA-9089 General Instructions PDF (current FLAG edition,
OMB 1205-0451 exp 02/28/2029) into rag_chunks (corpus='form_instructions_dol'),
chunked by form Section so PERM-verify flags can cite instruction chunks.

Usage:
    python3 ingest_9089_instructions.py --folder <dir-with-pdf> --ingest
    python3 ingest_9089_instructions.py --embed
    python3 ingest_9089_instructions.py --status
    python3 ingest_9089_instructions.py --reset --ingest --embed
"""

import os
import re
import sys
import time
import argparse
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras
import pdfplumber
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parents[1] / ".env")

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")
CORPUS = "form_instructions_dol"
CHUNK_TOKENS, OVERLAP_TOKENS = 800, 80
FORM_TYPE = "ETA-9089"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# Section header patterns in the General Instructions
SECTION_RX = re.compile(
    r"^(Section [A-J]\b.*|APPENDIX [A-D] –.*|Form ETA-9089 – Final Determination.*)$",
    re.MULTILINE)


def approx_tokens(t): return max(1, len(t) // 4)


def _split_long(text, target):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts, buf, n = [], [], 0
    for s in sentences:
        st = approx_tokens(s)
        if n + st > target and buf:
            parts.append(" ".join(buf)); buf, n = [], 0
        buf.append(s); n += st
    if buf:
        parts.append(" ".join(buf))
    return parts


def chunk_by_paragraphs(text, target=CHUNK_TOKENS, overlap=OVERLAP_TOKENS):
    if not text or not text.strip():
        return []
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, cur, n, tail = [], [], 0, ""
    for p in paragraphs:
        pt = approx_tokens(p)
        if pt > target:
            if cur:
                chunks.append(tail + "\n\n".join(cur)); tail = ""
                cur, n = [], 0
            for part in _split_long(p, target):
                chunks.append(part)
            continue
        if n + pt > target and cur:
            joined = "\n\n".join(cur)
            chunks.append(tail + joined)
            tail_chars = overlap * 4
            tail = (joined[-tail_chars:] + "\n\n") if len(joined) > tail_chars else ""
            cur, n = [], 0
        cur.append(p); n += pt
    if cur:
        chunks.append(tail + "\n\n".join(cur))
    return [c for c in chunks if c.strip()]


def extract_sections(pdf_path: Path):
    """Return list of (section_label, section_text)."""
    with pdfplumber.open(pdf_path) as pdf:
        full = "\n\n".join((p.extract_text() or "") for p in pdf.pages)
    # strip repeating headers/footers
    full = re.sub(r"OMB Approval: 1205-0451\s*", "", full)
    full = re.sub(r"Expiration Date:\s*\S+\s*", "", full)
    full = re.sub(r"Form ETA-9089 – General Instructions\s+Page \d+ of \d+", "", full)
    full = re.sub(r"Application for Permanent Employment Certification\s*", "", full)
    full = re.sub(r"U\.S\. Department of Labor\s*", "", full)

    marks = [(m.start(), m.group(1).strip()) for m in SECTION_RX.finditer(full)]
    # drop false positives: body sentences that begin with "Section X ..."
    marks = [(pos, lab) for pos, lab in marks
             if not (lab.startswith("Section") and len(lab) > 12)]
    if not marks:
        return [("General", full)]
    sections = []
    if marks[0][0] > 0:
        sections.append(("Preamble", full[:marks[0][0]]))
    for i, (pos, label) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(full)
        sections.append((label, full[pos:end]))
    return sections


def run_ingest(conn, folder: Path):
    pdfs = sorted(folder.glob("*General*Instructions*.pdf")) or \
           sorted(folder.glob("*.pdf"))
    if not pdfs:
        log.error(f"No PDFs found in {folder}"); sys.exit(1)
    rows = []
    for pdf in pdfs:
        log.info(f"Extracting {pdf.name}")
        for label, text in extract_sections(pdf):
            for idx, chunk in enumerate(chunk_by_paragraphs(text)):
                rows.append({
                    "corpus": CORPUS,
                    "source_id": f"9089-instr:{label}",
                    "source_label": f"ETA-9089 General Instructions — {label}",
                    "source_date": "2029-02-28-expiry-edition",
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "chunk_tokens": approx_tokens(chunk),
                    "form_type": FORM_TYPE,
                })
    sql = """
        INSERT INTO rag_chunks
          (corpus, source_id, source_label, source_date,
           chunk_index, chunk_text, chunk_tokens, form_type)
        VALUES
          (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s,
           %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s, %(form_type)s)
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
    conn.commit()
    log.info(f"Ingested {len(rows)} chunks into corpus '{CORPUS}'")


def run_embed(conn, batch_size=10):
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from app.embed import embed_documents
    with conn.cursor() as cur:
        cur.execute("SELECT id, chunk_text FROM rag_chunks "
                    "WHERE corpus=%s AND embedding IS NULL ORDER BY id", (CORPUS,))
        pending = cur.fetchall()
    if not pending:
        log.info("No chunks pending embedding"); return
    done = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        vecs = embed_documents([r[1] for r in batch])
        with conn.cursor() as cur:
            for (rid, _), vec in zip(batch, vecs):
                vs = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                cur.execute("UPDATE rag_chunks SET embedding=%s::vector WHERE id=%s",
                            (vs, rid))
        conn.commit()
        done += len(batch)
        log.info(f"  {done}/{len(pending)} embedded")
        time.sleep(0.1)


def run_status(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source_id, COUNT(*),
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL)
            FROM rag_chunks WHERE corpus=%s GROUP BY 1 ORDER BY 1
        """, (CORPUS,))
        for sid, n, emb in cur.fetchall():
            print(f"{sid:<60} {n:>4} chunks  {emb:>4} embedded")


def main():
    ap = argparse.ArgumentParser(description="Ingest ETA-9089 General Instructions")
    ap.add_argument("--folder", type=Path,
                    default=Path(os.environ.get("SOURCE_DIR_9089_INSTR",
                                                "/Users/Dad/Downloads")))
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    if args.reset:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE corpus=%s", (CORPUS,))
        conn.commit()
        log.info(f"Corpus '{CORPUS}' reset")
    if args.ingest:
        run_ingest(conn, args.folder)
    if args.embed:
        run_embed(conn, args.batch_size)
    if args.status or not any([args.ingest, args.embed, args.reset]):
        run_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
