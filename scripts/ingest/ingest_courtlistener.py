#!/usr/bin/env python3
"""
ingest_courtlistener.py — Load CourtListener opinions into Casebase RAG
========================================================================
Reads JSON files produced by scrape_courtlistener.py and ingests them
into the rag_chunks table using the standard Casebase pipeline.

Usage:
    python3 scripts/ingest/ingest_courtlistener.py --ingest
    python3 scripts/ingest/ingest_courtlistener.py --embed
    python3 scripts/ingest/ingest_courtlistener.py --status
    python3 scripts/ingest/ingest_courtlistener.py --ingest --reset  # drop & reload
    python3 scripts/ingest/ingest_courtlistener.py --ingest --court ca9
    python3 scripts/ingest/ingest_courtlistener.py --ingest --limit 500

Schema note:
    rag_chunks.source_id = cluster_id (TEXT)
    rag_chunks.corpus    = "court_opinions"
    rag_chunks.metadata  JSON keys: court_id, case_name, date_filed,
                                    citation, author, cl_url, chunk_index
"""

import argparse
import json
import logging
import math
import os
import re
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DB_URL      = os.environ.get(
    "DATABASE_URL",
    "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions",
)
DATA_DIR    = Path(
    os.environ.get(
        "COURTLISTENER_DATA_DIR",
        str(Path.home() / "courtlistener_opinions"),
    )
)
CORPUS      = "court_opinions"
EMBED_DIM   = 2560   # qwen3-embedding:4b output dimension
CHUNK_TOKENS   = 800
OVERLAP_TOKENS = 80

COURTS = [
    "scotus","ca1","ca2","ca3","ca4","ca5",
    "ca6","ca7","ca8","ca9","ca10","ca11","cadc",
]

# ── Chunking (standard Casebase algorithm) ────────────────────────────────────

def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def _tail_str(text: str, n_tokens: int) -> str:
    chars = n_tokens * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(" ")
    return (snippet[idx + 1:] if idx > 0 else snippet) + " "

def _split_long(text: str, target: int) -> list[str]:
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
    return parts or [text]

def chunk_by_paragraphs(
    text: str,
    target: int = CHUNK_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> list[str]:
    if not text or not text.strip():
        return []
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current_parts, current_tokens, overlap_tail = [], [], 0, ""

    for para in paragraphs:
        pt = approx_tokens(para)
        if pt > target:
            if current_parts:
                chunks.append(overlap_tail + " ".join(current_parts))
                overlap_tail = _tail_str(" ".join(current_parts), overlap)
                current_parts, current_tokens = [], 0
            for sub in _split_long(para, target):
                chunks.append(overlap_tail + sub)
                overlap_tail = _tail_str(sub, overlap)
            continue
        if current_tokens + pt > target and current_parts:
            chunks.append(overlap_tail + " ".join(current_parts))
            overlap_tail = _tail_str(" ".join(current_parts), overlap)
            current_parts, current_tokens = [], 0
        current_parts.append(para)
        current_tokens += pt

    if current_parts:
        chunks.append(overlap_tail + " ".join(current_parts))
    return [c.strip() for c in chunks if c.strip()]


# ── Embedding ─────────────────────────────────────────────────────────────────

def embed_batch(texts: list) -> list:
    """Delegate to app.embed.embed_documents (Voyage API, voyage-4-large)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parents[2] if 'perm-research' in __file__ else _Path(__file__).parents[2]))
    from app.embed import embed_documents
    return embed_documents(list(texts))

def ensure_corpus_allowed(conn):
    """Add court_opinions to the rag_chunks corpus CHECK constraint if absent."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'rag_chunks_corpus_check'
        """)
        row = cur.fetchone()
        if row and CORPUS in row[0]:
            return  # already there
        if row:
            log.info("Updating rag_chunks_corpus_check to include court_opinions...")
            # Fetch the current allowed values from the constraint definition
            # e.g. "CHECK ((corpus = ANY (ARRAY['balca'::text, 'aao'::text, ...])))"
            defn = row[0]
            # Extract existing quoted values
            existing = re.findall(r"'([^']+)'::text", defn)
            if not existing:
                # Fallback: known corpora
                existing = ['balca','aao','cfr','policy','ina',
                            'precedents','fam','visa_bulletin','bls_oews']
            if CORPUS not in existing:
                existing.append(CORPUS)
            values = ", ".join(f"'{v}'" for v in existing)
            cur.execute("ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_corpus_check")
            cur.execute(f"""
                ALTER TABLE rag_chunks ADD CONSTRAINT rag_chunks_corpus_check
                CHECK (corpus IN ({values}))
                NOT VALID
            """)
            conn.commit()
            log.info(f"Constraint updated: {existing}")


def upsert_chunks(cur, rows: list[dict]):
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO rag_chunks
            (corpus, source_id, source_label, source_date,
             chunk_index, chunk_text)
        VALUES
            (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s,
             %(chunk_index)s, %(chunk_text)s)
        ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE SET
            chunk_text   = EXCLUDED.chunk_text,
            source_label = EXCLUDED.source_label,
            source_date  = EXCLUDED.source_date,
            embedding    = NULL
        """,
        rows,
        page_size=500,
    )


def rebuild_hnsw(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL"
        )
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
    log.info("HNSW index rebuilt.")


# ── Ingest phase ──────────────────────────────────────────────────────────────

def run_ingest(conn, courts: list[str], limit: int | None, reset: bool):
    if reset:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rag_chunks WHERE corpus = %s", (CORPUS,)
            )
        conn.commit()
        log.info("Existing court_opinions chunks deleted.")

    ensure_corpus_allowed(conn)

    total_docs = total_chunks = skipped = 0

    for court_id in courts:
        court_dir = DATA_DIR / court_id
        if not court_dir.exists():
            log.warning(f"No data for {court_id} — run scrape first.")
            continue

        files = sorted(court_dir.glob("*.json"))
        log.info(f"\n── {court_id.upper()} ({len(files):,} files) ──")

        for json_file in files:
            if limit and total_docs >= limit:
                break
            try:
                rec = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"  Bad JSON {json_file.name}: {e}")
                continue

            text = rec.get("full_text", "").strip()
            if not text:
                skipped += 1
                continue

            source_id = str(rec["cluster_id"])

            # Skip if already loaded (unless reset)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM rag_chunks WHERE corpus=%s AND source_id=%s LIMIT 1",
                    (CORPUS, source_id),
                )
                if cur.fetchone():
                    skipped += 1
                    continue

            chunks = chunk_by_paragraphs(text)
            if not chunks:
                skipped += 1
                continue

            rows = [
                {
                    "corpus":       CORPUS,
                    "source_id":    source_id,
                    "source_label": (
                        f"{rec.get('case_name','')} "
                        f"({rec.get('citation','')}) "
                        f"[{court_id.upper()}]"
                    ).strip(),
                    "source_date":  rec.get("date_filed", ""),
                    "chunk_index":  i,
                    "chunk_text":   chunk,
                }
                for i, chunk in enumerate(chunks)
            ]

            with conn.cursor() as cur:
                upsert_chunks(cur, rows)
            conn.commit()

            total_docs   += 1
            total_chunks += len(chunks)

            if total_docs % 500 == 0:
                log.info(
                    f"  [{court_id}] {total_docs:,} docs, "
                    f"{total_chunks:,} chunks so far"
                )

    log.info(
        f"\n✅ Ingest done. {total_docs:,} docs, "
        f"{total_chunks:,} chunks, {skipped:,} skipped."
    )


# ── Embed phase ───────────────────────────────────────────────────────────────

def run_embed(conn, batch_size: int = 8):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM rag_chunks "
            "WHERE corpus=%s AND embedding IS NULL",
            (CORPUS,),
        )
        pending = cur.fetchone()[0]

    if pending == 0:
        log.info("No pending embeddings for court_opinions.")
        return

    log.info(f"Embedding {pending:,} pending chunks (batch={batch_size})...")
    done = errors = 0

    while True:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, chunk_text FROM rag_chunks
                WHERE corpus=%s AND embedding IS NULL
                ORDER BY id
                LIMIT %s
                """,
                (CORPUS, batch_size),
            )
            rows = cur.fetchall()

        if not rows:
            break

        ids   = [r[0] for r in rows]
        texts = [r[1] for r in rows]

        try:
            vecs = embed_batch(texts)
        except Exception as e:
            log.warning(f"Embed batch failed: {e} — skipping batch")
            errors += len(ids)
            # mark them with a zero vector so we don't loop forever
            with conn.cursor() as cur:
                for rid in ids:
                    cur.execute(
                        "UPDATE rag_chunks SET embedding=NULL WHERE id=%s",
                        (rid,)
                    )
            conn.commit()
            time.sleep(3)
            continue

        with conn.cursor() as cur:
            for rid, vec in zip(ids, vecs):
                cur.execute(
                    "UPDATE rag_chunks SET embedding=%s WHERE id=%s",
                    (vec[:EMBED_DIM], rid),
                )
        conn.commit()
        done += len(ids)

        if done % 1000 == 0:
            log.info(f"  Embedded {done:,} / {pending:,}")

    log.info(f"✅ Embed done. {done:,} embedded, {errors} errors.")
    rebuild_hnsw(conn)


# ── Status ────────────────────────────────────────────────────────────────────

def run_status(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT corpus,
                   COUNT(DISTINCT source_id)                      AS sources,
                   COUNT(*)                                       AS total_chunks,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL)  AS embedded,
                   COUNT(*) FILTER (WHERE embedding IS NULL)      AS pending
            FROM rag_chunks
            GROUP BY corpus
            ORDER BY corpus
        """)
        rows = cur.fetchall()
    print(f"\n{'corpus':<18} {'sources':>8} {'chunks':>8} {'embedded':>10} {'pending':>9}")
    print("─" * 60)
    for row in rows:
        print(f"{row[0]:<18} {row[1]:>8,} {row[2]:>8,} {row[3]:>10,} {row[4]:>9,}")

    # Also show scrape file counts
    print("\nScraped files on disk:")
    if DATA_DIR.exists():
        for court_id in COURTS:
            d = DATA_DIR / court_id
            n = len(list(d.glob("*.json"))) if d.exists() else 0
            if n:
                print(f"  {court_id:8} {n:6,} files")
    else:
        print("  (no data dir yet)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ingest CourtListener opinions into Casebase RAG"
    )
    parser.add_argument("--ingest",     action="store_true")
    parser.add_argument("--embed",      action="store_true")
    parser.add_argument("--status",     action="store_true")
    parser.add_argument("--reset",      action="store_true",
                        help="Delete existing court_opinions chunks before ingesting")
    parser.add_argument("--court",      default=None,
                        help="Single court to ingest (e.g. ca9)")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap total documents (for testing)")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Ollama embedding batch size (default: 32)")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)

    if args.status:
        run_status(conn)
    if args.ingest:
        courts = [args.court] if args.court else COURTS
        run_ingest(conn, courts, args.limit, args.reset)
    if args.embed:
        run_embed(conn, args.batch_size)

    conn.close()


if __name__ == "__main__":
    main()
