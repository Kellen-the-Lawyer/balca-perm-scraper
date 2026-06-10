#!/usr/bin/env python3
"""
USCIS Evidence Checklists — RAG Ingestion
Reads the JSON output of scrape_uscis_checklists.py and loads each
form/classification pair into rag_chunks (corpus='uscis_checklists').

Each form+classification becomes a document; long content is chunked at
~800 tokens with 80-token overlap — same approach as ingest_rag.py.

Usage:
    python3 ingest_uscis_checklists.py --ingest          # parse JSON, upsert raw chunks
    python3 ingest_uscis_checklists.py --embed           # embed chunks missing vectors
    python3 ingest_uscis_checklists.py --ingest --embed  # both in one pass
    python3 ingest_uscis_checklists.py --status          # show chunk/embedding counts
    python3 ingest_uscis_checklists.py --reset --ingest  # wipe corpus and re-ingest
    python3 ingest_uscis_checklists.py --ingest --limit 3  # test with 3 records

Reads:
    USCIS_CHECKLISTS_JSON env var  (default: perm-research/data/uscis_checklists.json)

Writes:
    rag_chunks (corpus='uscis_checklists') in perm_decisions database
"""

import os
import re
import sys
import json
import time
import argparse
import urllib.request
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

DB_URL       = os.environ.get("DATABASE_URL",
               "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:latest")
EMBED_DIM    = 1024
CHUNK_TOKENS  = 800
OVERLAP_TOKENS = 80
BATCH_SIZE   = 5
CORPUS       = "uscis_checklists"
DOC_INSTRUCT = ""

DEFAULT_JSON = Path(__file__).resolve().parent / "data" / "uscis_checklists.json"
JSON_PATH    = Path(os.environ.get("USCIS_CHECKLISTS_JSON", str(DEFAULT_JSON)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


def ensure_corpus_allowed(conn):
    """
    Patch rag_chunks_corpus_check to include 'uscis_checklists' if missing.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'rag_chunks_corpus_check'
        """)
        row = cur.fetchone()
    if row is None:
        return
    defn = row[0]
    if CORPUS in defn:
        return
    log.info(f"Patching rag_chunks_corpus_check to add '{CORPUS}'…")
    existing = re.findall(r"'(\w+)'", defn)
    existing.append(CORPUS)
    arr = ",".join(f"'{v}'::text" for v in existing)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE rag_chunks DROP CONSTRAINT rag_chunks_corpus_check")
        cur.execute(f"""
            ALTER TABLE rag_chunks
            ADD CONSTRAINT rag_chunks_corpus_check
            CHECK (corpus = ANY (ARRAY[{arr}]))
        """)
    conn.commit()
    log.info("Constraint updated.")


UPSERT_SQL = """
    INSERT INTO rag_chunks
      (corpus, source_id, source_label, source_date, source_outcome,
       chunk_index, chunk_text, chunk_tokens, embedding, cfr_citation, form_type)
    VALUES
      (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s, %(source_outcome)s,
       %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s, %(embedding)s,
       %(cfr_citation)s, %(form_type)s)
    ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE
      SET chunk_text   = EXCLUDED.chunk_text,
          chunk_tokens = EXCLUDED.chunk_tokens,
          ingested_at  = NOW()
"""


def upsert_chunks(conn, rows: list):
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows, page_size=50)
    conn.commit()

# ── Chunking ──────────────────────────────────────────────────────────────────

def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _tail_str(text: str, n: int) -> str:
    chars = n * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(" ")
    return (snippet[idx + 1:] if idx > 0 else snippet) + " "


def _split_long(text: str, target: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts, buf, bt = [], [], 0
    for s in sentences:
        st = approx_tokens(s)
        if bt + st > target and buf:
            parts.append(" ".join(buf))
            buf, bt = [], 0
        buf.append(s)
        bt += st
    if buf:
        parts.append(" ".join(buf))
    return parts


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
    chunks, cur_parts, cur_tokens, ov_tail = [], [], 0, ""

    for para in paragraphs:
        pt = approx_tokens(para)
        if pt > target:
            if cur_parts:
                chunks.append((ov_tail + " ".join(cur_parts)).strip())
                ov_tail = _tail_str(" ".join(cur_parts), overlap)
                cur_parts, cur_tokens = [], 0
            for sub in _split_long(para, target):
                if sub.strip():
                    chunks.append((ov_tail + sub).strip())
                    ov_tail = _tail_str(sub, overlap)
            continue
        if cur_tokens + pt > target and cur_parts:
            chunks.append((ov_tail + " ".join(cur_parts)).strip())
            ov_tail = _tail_str(" ".join(cur_parts), overlap)
            cur_parts, cur_tokens = [], 0
        cur_parts.append(para)
        cur_tokens += pt

    if cur_parts:
        chunks.append((ov_tail + " ".join(cur_parts)).strip())
    return [c for c in chunks if c.strip()]

# ── source_id derivation ──────────────────────────────────────────────────────

def make_source_id(form: str, classification: str) -> str:
    """Stable, slug-form source_id for a form+classification pair."""
    slug = re.sub(r"[^\w]", "_", f"{form}__{classification}").lower()
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:200]

# ── Embedding ─────────────────────────────────────────────────────────────────

def check_ollama():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            tags = json.loads(r.read())
        models = [m["name"] for m in tags.get("models", [])]
        if not any(OLLAMA_MODEL.split(":")[0] in m for m in models):
            log.error(f"Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}")
            sys.exit(1)
        log.info(f"Ollama OK — model: {OLLAMA_MODEL}")
    except Exception as e:
        log.error(f"Cannot reach Ollama at {OLLAMA_URL}: {e}")
        log.error("Start Ollama first: ollama serve")
        sys.exit(1)


def embed_batch(texts: list[str]) -> list[list[float]]:
    cleaned = [(DOC_INSTRUCT + t.strip()[:32000]) or " " for t in texts]
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "input": cleaned,
        "options": {"num_ctx": 32768},
    }).encode()

    for attempt in range(5):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
            return [vec[:EMBED_DIM] for vec in data["embeddings"]]
        except Exception as e:
            wait = 15 * (attempt + 1)
            log.warning(f"Ollama error (attempt {attempt+1}/5): {e} — retry in {wait}s")
            time.sleep(wait)

    raise RuntimeError("Ollama failed after 5 attempts")

# ── HNSW index ────────────────────────────────────────────────────────────────

def rebuild_hnsw(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        n = cur.fetchone()[0]
    if n < 10:
        log.info(f"Only {n} vectors — skipping HNSW rebuild")
        return
    log.info(f"Rebuilding HNSW index ({n:,} vectors)…")
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
        cur.execute("""
            CREATE INDEX idx_rag_embedding
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
    conn.commit()
    log.info("HNSW index rebuilt")

# ── --status ──────────────────────────────────────────────────────────────────

def run_status(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT corpus,
                   COUNT(DISTINCT source_id)                       AS sources,
                   COUNT(*)                                        AS total_chunks,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL)  AS embedded,
                   COUNT(*) FILTER (WHERE embedding IS NULL)      AS pending
            FROM rag_chunks
            GROUP BY corpus ORDER BY corpus
        """)
        rows = cur.fetchall()
    print(f"\n{'corpus':<22} {'sources':>8} {'chunks':>8} {'embedded':>10} {'pending':>9}")
    print("─" * 62)
    for corpus, sources, total, embedded, pending in rows:
        marker = " ◀" if corpus == CORPUS else ""
        print(f"{corpus:<22} {sources:>8} {total:>8} {embedded:>10} {pending:>9}{marker}")
    print()

# ── --ingest ──────────────────────────────────────────────────────────────────

def run_ingest(conn, limit: int | None):
    if not JSON_PATH.exists():
        log.error(f"JSON not found: {JSON_PATH}")
        log.error("Run scrape_uscis_checklists.py first to generate it.")
        sys.exit(1)

    with open(JSON_PATH, encoding="utf-8") as f:
        records = json.load(f)

    log.info(f"Loaded {len(records)} records from {JSON_PATH}")

    if limit:
        records = records[:limit]
        log.info(f"Limited to first {limit} record(s) for testing")

    total_chunks = 0
    rows: list[dict] = []

    for rec in records:
        form           = rec.get("form", "")
        classification = rec.get("classification", "")
        content        = rec.get("content", "").strip()
        source_url     = rec.get("source_url", "")
        scraped_date   = rec.get("scraped_date")

        if not content:
            log.warning(f"  Empty content — skipping {form} / {classification}")
            continue

        source_id    = make_source_id(form, classification)
        source_label = f"{form} — {classification}"

        # Prepend label so standalone chunks carry retrieval context
        headed_text = f"{source_label}\n\n{content}"
        chunks = chunk_by_paragraphs(headed_text)

        for i, text in enumerate(chunks):
            rows.append({
                "corpus":         CORPUS,
                "source_id":      source_id,
                "source_label":   source_label,
                "source_date":    scraped_date,
                "source_outcome": None,
                "chunk_index":    i,
                "chunk_text":     text,
                "chunk_tokens":   approx_tokens(text),
                "embedding":      None,
                "cfr_citation":   source_url,
                "form_type":      form,
            })
        total_chunks += len(chunks)

    if not rows:
        log.warning("No chunks to ingest.")
        return

    upsert_chunks(conn, rows)
    log.info(
        f"Ingest complete — {len(records)} documents, "
        f"{total_chunks} chunks upserted (corpus='{CORPUS}')"
    )

    # Per-form summary
    by_form: dict[str, int] = {}
    for r in rows:
        ft = r["form_type"] or "?"
        by_form[ft] = by_form.get(ft, 0) + 1
    for form_name, count in sorted(by_form.items()):
        log.info(f"  {form_name}: {count} chunk(s)")

# ── --embed ───────────────────────────────────────────────────────────────────

def run_embed(conn, batch_size: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, chunk_text FROM rag_chunks
            WHERE corpus = %s AND embedding IS NULL
            ORDER BY id
        """, (CORPUS,))
        pending = cur.fetchall()

    if not pending:
        log.info("No chunks pending embedding")
        return

    log.info(f"Embedding {len(pending):,} chunk(s) (model: {OLLAMA_MODEL})")
    done = 0

    for i in range(0, len(pending), batch_size):
        batch = pending[i: i + batch_size]
        ids   = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        vecs  = embed_batch(texts)

        with conn.cursor() as cur:
            for rid, vec in zip(ids, vecs):
                vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                cur.execute(
                    "UPDATE rag_chunks SET embedding = %s::vector WHERE id = %s",
                    (vec_str, rid),
                )
        conn.commit()
        done += len(batch)

        if done % 50 == 0 or done == len(pending):
            log.info(f"  {done}/{len(pending)} embedded")

        if i + batch_size < len(pending):
            time.sleep(0.1)

    log.info(f"Embedding complete — {done} chunks embedded")
    rebuild_hnsw(conn)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"Ingest USCIS evidence checklists into RAG (corpus='{CORPUS}')"
    )
    parser.add_argument("--ingest",     action="store_true",
                        help="Parse JSON and upsert raw chunks")
    parser.add_argument("--embed",      action="store_true",
                        help="Embed chunks missing vectors via Ollama")
    parser.add_argument("--status",     action="store_true",
                        help="Show chunk/embedding counts per corpus")
    parser.add_argument("--reset",      action="store_true",
                        help=f"Delete existing '{CORPUS}' chunks before ingesting")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap number of source records (for testing)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Ollama embedding batch size")
    parser.add_argument("--json",       default=None,
                        help=f"Path to checklist JSON (default: {DEFAULT_JSON})")
    args = parser.parse_args()

    if not any([args.ingest, args.embed, args.status]):
        parser.print_help()
        sys.exit(0)

    if args.json:
        global JSON_PATH
        JSON_PATH = Path(args.json)

    conn = get_conn()
    ensure_corpus_allowed(conn)

    if args.status:
        run_status(conn)

    if args.reset:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE corpus = %s", (CORPUS,))
        conn.commit()
        log.info(f"Reset: deleted all chunks for corpus='{CORPUS}'")

    if args.ingest:
        run_ingest(conn, args.limit)

    if args.embed:
        check_ollama()
        run_embed(conn, args.batch_size)

    conn.close()


if __name__ == "__main__":
    main()
