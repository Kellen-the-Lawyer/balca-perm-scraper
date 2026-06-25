#!/usr/bin/env python3
"""
USCIS FOIA Documents -> rag_chunks Ingestion
=============================================
Extracts text from downloaded FOIA PDFs (uscis_foia_documents) and chunks +
embeds them into rag_chunks under corpus='uscis_foia'.

Reuses chunking + embedding utilities from ingest_rag.py to stay consistent
with the rest of the corpus (qwen3-embedding:4b, 1024-dim MRL, HNSW index).

Substantive prose categories only. foia-logs and data (tabular) are excluded
by default per project decision — they chunk poorly for semantic search.

Usage:
    venv/bin/python3 scripts/ingest/ingest_foia.py [--limit N] [--reset]
                                                    [--include-category foia-logs]
                                                    [--rebuild-index]

Resumes after a crash: skips documents already present in rag_chunks
(matched on source_id = uscis_foia_documents.id).
"""
import argparse, logging, os, sys, time
from pathlib import Path

import psycopg2, psycopg2.extras
import pdfplumber

# Reuse the battle-tested chunking + embedding from ingest_rag
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_rag import (
    chunk_by_paragraphs, approx_tokens, _embed_and_save,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL",
                        "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")

CORPUS = "uscis_foia"

# Categories to ingest (substantive prose). foia-logs + data excluded by default.
DEFAULT_CATEGORIES = [
    "foia", "guides", "lesson-plans", "memos", "notices",
    "questions-and-answers", "presentations", "legal-docs",
    "aao-decisions", "checklists", "reports", "tip-sheets",
    "outreach-engagements",
]


def extract_text(path: Path) -> tuple[str, int]:
    """Extract full text from a PDF. Returns (text, page_count)."""
    pages = []
    try:
        with pdfplumber.open(path) as pdf:
            npages = len(pdf.pages)
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        text = "\n\n".join(pages)
        # Strip NUL bytes (0x00) and other control chars that Postgres rejects
        # in text literals. Some FOIA PDFs embed nulls in extracted text.
        text = text.replace("\x00", "")
        text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
        return text, npages
    except Exception as e:
        log.error(f"  PDF extract error {path.name}: {e}")
        return "", 0


def get_conn():
    return psycopg2.connect(DB_URL)


def fetch_documents(conn, categories, limit):
    placeholders = ",".join(["%s"] * len(categories))
    sql = f"""
        SELECT id, title, file_url, local_path, doc_category, published_date::text
        FROM uscis_foia_documents
        WHERE download_status='done'
          AND file_type='pdf'
          AND local_path IS NOT NULL
          AND doc_category IN ({placeholders})
        ORDER BY published_date DESC NULLS LAST
    """
    params = list(categories)
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def already_ingested(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_id FROM rag_chunks WHERE corpus=%s", (CORPUS,))
        return {r[0] for r in cur.fetchall()}


def mark_ingested(conn, doc_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE uscis_foia_documents SET ingested_at=NOW() WHERE id=%s", (doc_id,))
    conn.commit()


def rebuild_index(conn):
    log.info("Rebuilding HNSW index...")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        count = cur.fetchone()[0]
        cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
        cur.execute("""
            CREATE INDEX idx_rag_embedding
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
    conn.commit()
    log.info(f"  HNSW index rebuilt for {count} vectors")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reset", action="store_true",
                    help="Delete existing uscis_foia chunks first")
    ap.add_argument("--include-category", action="append", default=[],
                    help="Add a category beyond the default set (e.g. foia-logs)")
    ap.add_argument("--only-category", action="append", default=[],
                    help="Restrict to specific categories")
    ap.add_argument("--rebuild-index", action="store_true",
                    help="Rebuild HNSW index after ingest")
    args = ap.parse_args()

    categories = args.only_category or (DEFAULT_CATEGORIES + args.include_category)

    conn = get_conn()

    if args.reset:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE corpus=%s", (CORPUS,))
        conn.commit()
        log.info(f"Reset: cleared all '{CORPUS}' chunks")

    docs = fetch_documents(conn, categories, args.limit)
    done_ids = already_ingested(conn)
    pending = [d for d in docs if d["id"] not in done_ids]

    log.info("=" * 60)
    log.info(f"FOIA Ingest -> rag_chunks (corpus='{CORPUS}')")
    log.info(f"Categories : {', '.join(categories)}")
    log.info(f"Documents  : {len(docs)} total, {len(done_ids)} already done, "
             f"{len(pending)} to process")
    log.info("=" * 60)

    total_chunks = 0
    skipped_empty = 0

    for i, doc in enumerate(pending):
        path = Path(doc["local_path"])
        if not path.exists():
            log.warning(f"[{i+1}/{len(pending)}] MISSING {path}")
            continue

        text, npages = extract_text(path)
        if not text.strip() or len(text) < 100:
            log.warning(f"[{i+1}/{len(pending)}] empty/scanned: {doc['title'][:50]}")
            skipped_empty += 1
            mark_ingested(conn, doc["id"])  # mark so we don't retry scanned PDFs forever
            continue

        chunks = chunk_by_paragraphs(text)
        if not chunks:
            skipped_empty += 1
            mark_ingested(conn, doc["id"])
            continue

        label = doc["title"]
        if doc["doc_category"]:
            label = f"[{doc['doc_category']}] {label}"

        pending_rows = []
        for ci, ctext in enumerate(chunks):
            pending_rows.append({
                "corpus": CORPUS,
                "source_id": doc["id"],
                "source_label": label[:300],
                "source_date": doc["published_date"],
                "source_outcome": None,
                "chunk_index": ci,
                "chunk_text": ctext,
                "chunk_tokens": approx_tokens(ctext),
                "cfr_citation": None,
                "form_type": None,
            })

        saved = _embed_and_save(conn, pending_rows)
        total_chunks += saved
        mark_ingested(conn, doc["id"])
        log.info(f"[{i+1}/{len(pending)}] {doc['title'][:50]} "
                 f"({npages}pp -> {saved} chunks)")

    if args.rebuild_index:
        rebuild_index(conn)

    conn.close()
    log.info("=" * 60)
    log.info(f"Done. {total_chunks:,} chunks from {len(pending)-skipped_empty} docs "
             f"({skipped_empty} empty/scanned skipped)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
