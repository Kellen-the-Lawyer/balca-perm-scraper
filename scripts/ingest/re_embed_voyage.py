#!/usr/bin/env python3
"""
re_embed_voyage.py — Re-embed all rag_chunks with voyage-4-large
=================================================================
Nulls existing embeddings and re-embeds everything using the Voyage API.
Resumable: skips chunks that already have a non-null embedding unless
--reset is passed.

Usage:
    # Dry run — shows counts, touches nothing
    venv/bin/python3 scripts/ingest/re_embed_voyage.py --dry-run

    # Test run — embed first 50 chunks only
    venv/bin/python3 scripts/ingest/re_embed_voyage.py --limit 50

    # Null all embeddings first, then re-embed everything
    venv/bin/python3 scripts/ingest/re_embed_voyage.py --reset

    # Resume an interrupted run (skips already-embedded chunks)
    venv/bin/python3 scripts/ingest/re_embed_voyage.py

    # Background full run
    nohup venv/bin/python3 scripts/ingest/re_embed_voyage.py --reset \\
        > ~/Library/Logs/re_embed_voyage.log 2>&1 &

Environment:
    DATABASE_URL    postgresql://perm@127.0.0.1:5433/perm_decisions
    VOYAGE_API_KEY  required
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

sys.path.insert(0, str(Path(__file__).parents[2]))
from app.embed import embed_documents

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_URL     = os.environ.get("DATABASE_URL",
             "postgresql://perm@127.0.0.1:5433/perm_decisions")
BATCH_SIZE = int(os.environ.get("VOYAGE_BATCH_SIZE", "128"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.expanduser("~/Library/Logs/re_embed_voyage.log"),
            mode="a"
        ),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_counts(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                corpus,
                COUNT(*) as total,
                COUNT(embedding) as embedded,
                COUNT(*) - COUNT(embedding) as pending
            FROM rag_chunks
            GROUP BY corpus
            ORDER BY corpus
        """)
        return cur.fetchall()

def print_status(conn):
    rows = get_counts(conn)
    total_t = total_e = total_p = 0
    print(f"\n{'Corpus':<20} {'Total':>8} {'Embedded':>10} {'Pending':>9}")
    print("─" * 52)
    for corpus, total, embedded, pending in rows:
        print(f"{corpus:<20} {total:>8,} {embedded:>10,} {pending:>9,}")
        total_t += total; total_e += embedded; total_p += pending
    print("─" * 52)
    print(f"{'TOTAL':<20} {total_t:>8,} {total_e:>10,} {total_p:>9,}")
    return total_p

def null_all_embeddings(conn):
    log.info("Nulling all embeddings in rag_chunks...")
    with conn.cursor() as cur:
        cur.execute("UPDATE rag_chunks SET embedding = NULL")
    conn.commit()
    log.info(f"Nulled {conn.cursor().rowcount if False else 'all'} embeddings.")

def get_pending(conn, limit=None):
    sql = """
        SELECT id, chunk_text
        FROM rag_chunks
        WHERE embedding IS NULL
        ORDER BY corpus, id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()

def rebuild_hnsw(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        n = cur.fetchone()[0]
    if n < 100:
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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Re-embed all rag_chunks with voyage-4-large")
    parser.add_argument("--reset",   action="store_true", help="Null all embeddings before starting")
    parser.add_argument("--limit",   type=int, default=None, help="Only embed this many chunks (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Show counts, do nothing")
    parser.add_argument("--db-url",  default=DB_URL)
    args = parser.parse_args()

    conn = psycopg2.connect(args.db_url)
    conn.autocommit = False

    log.info("=== re_embed_voyage.py starting ===")
    log.info(f"DB: {args.db_url}")

    pending_count = print_status(conn)

    if args.dry_run:
        print(f"\nDry run complete. {pending_count:,} chunks pending embedding.")
        conn.close()
        return

    if args.reset:
        null_all_embeddings(conn)
        pending_count = print_status(conn)

    rows = get_pending(conn, args.limit)
    if not rows:
        log.info("No chunks pending embedding. Done.")
        conn.close()
        return

    log.info(f"Embedding {len(rows):,} chunks in batches of {BATCH_SIZE}...")
    ok = err = 0
    t_start = time.time()

    for i in range(0, len(rows), BATCH_SIZE):
        batch     = rows[i : i + BATCH_SIZE]
        ids       = [r[0] for r in batch]
        texts     = [r[1] for r in batch]

        try:
            vecs = embed_documents(texts)
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    "UPDATE rag_chunks SET embedding = %s WHERE id = %s",
                    [(vec, chunk_id) for chunk_id, vec in zip(ids, vecs)],
                    page_size=200,
                )
            conn.commit()
            ok += len(batch)
        except Exception as e:
            conn.rollback()
            log.error(f"Batch {i//BATCH_SIZE + 1} failed: {e}")
            err += len(batch)
            time.sleep(10)
            continue

        # Progress log every 1000 chunks
        if ok % 1000 == 0 or ok + err >= len(rows):
            elapsed = time.time() - t_start
            rate    = ok / elapsed if elapsed > 0 else 0
            remain  = (len(rows) - ok - err) / rate / 60 if rate > 0 else 0
            log.info(
                f"  {ok:,}/{len(rows):,} embedded "
                f"({err:,} errors) — "
                f"{rate:.0f} chunks/sec — "
                f"~{remain:.0f} min remaining"
            )

    elapsed = time.time() - t_start
    log.info(f"Done: {ok:,} embedded, {err:,} errors in {elapsed/60:.1f} min")

    if not args.limit:
        rebuild_hnsw(conn)

    print_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
