#!/usr/bin/env python3
"""
Casebase — INA Ingestion
=========================
Reads ~/ina_data/ina_full.json, chunks it, and loads into rag_chunks.
Embedding is a separate pass so you can ingest now and embed later.

Usage:
    python ingest_ina.py --ingest                   # parse + insert raw chunks
    python ingest_ina.py --embed                    # embed all ina chunks missing vectors
    python ingest_ina.py --ingest --embed           # do both in one shot
    python ingest_ina.py --ingest --reset           # drop existing ina chunks first
    python ingest_ina.py --embed   --batch-size 4   # larger Ollama batches
    python ingest_ina.py --status                   # show chunk / embedding counts
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Config (mirrors ingest_rag.py) ────────────────────────────────────────────

DB_URL       = os.environ.get("DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:8b")
EMBED_DIM    = 1024
BATCH_SIZE   = 2

INA_JSON     = Path(os.environ.get("INA_JSON", Path.home() / "ina_data" / "ina_full.json"))

CORPUS       = "ina"
CHUNK_TOKENS = 800
OVERLAP_TOKENS = 80

DOC_INSTRUCT   = ""
QUERY_INSTRUCT = "Instruct: Given a legal research query, retrieve relevant passages that answer the query\nQuery: "


# ── Tokenisation + chunking (same logic as ingest_rag.py) ────────────────────

def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _tail_str(text: str, n_tokens: int) -> str:
    chars = n_tokens * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(" ")
    return (snippet[idx + 1:] if idx > 0 else snippet) + " "


def _tail(parts: list, n_tokens: int) -> str:
    return _tail_str(" ".join(parts), n_tokens)


def _split_long(text: str, target: int) -> list:
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


def chunk_by_paragraphs(text: str, target: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list:
    if not text or not text.strip():
        return []
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_parts: list = []
    current_tokens = 0
    overlap_tail = ""

    for para in paragraphs:
        para_tokens = approx_tokens(para)
        if para_tokens > target:
            if current_parts:
                chunks.append((overlap_tail + " ".join(current_parts)).strip())
                overlap_tail = _tail(current_parts, overlap)
                current_parts = []
                current_tokens = 0
            for sub in _split_long(para, target):
                if sub.strip():
                    chunks.append((overlap_tail + sub).strip())
                    overlap_tail = _tail_str(sub, overlap)
            continue
        if current_tokens + para_tokens > target and current_parts:
            chunks.append((overlap_tail + " ".join(current_parts)).strip())
            overlap_tail = _tail(current_parts, overlap)
            current_parts = []
            current_tokens = 0
        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        chunks.append((overlap_tail + " ".join(current_parts)).strip())
    return [c for c in chunks if c.strip()]


# ── INA-specific chunking ─────────────────────────────────────────────────────
# Prepend the section header to every chunk so each vector carries
# "§ 1101. Definitions — <text>" for better retrieval.

def chunk_section(section: dict) -> list[dict]:
    """
    Returns list of chunk dicts ready for DB insertion (no embedding yet).
    source_label  = "§ 1101 — Definitions"
    cfr_citation  = "8 USC 1101"
    """
    sec_num  = section.get("section", "")
    title    = section.get("title", "")
    text     = section.get("text", "")
    url      = section.get("source_url", "")
    label    = f"§ {sec_num} — {title}".strip(" —")
    citation = f"8 USC {sec_num}"

    # Prepend header so even standalone chunks have context
    headed_text = f"{label}\n\n{text}" if text.strip() else ""
    raw_chunks  = chunk_by_paragraphs(headed_text)

    return [
        {
            "corpus":         CORPUS,
            "source_id":      sec_num,       # use section number as stable ID
            "source_label":   label,
            "source_date":    None,
            "source_outcome": None,
            "chunk_index":    i,
            "chunk_text":     chunk,
            "chunk_tokens":   approx_tokens(chunk),
            "cfr_citation":   citation,
            "form_type":      None,
            "embedding":      None,
        }
        for i, chunk in enumerate(raw_chunks)
    ]


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


def upsert_chunks(conn, rows: list) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO rag_chunks
          (corpus, source_id, source_label, source_date, source_outcome,
           chunk_index, chunk_text, chunk_tokens, embedding, cfr_citation, form_type)
        VALUES
          (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s, %(source_outcome)s,
           %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s,
           %(embedding)s,
           %(cfr_citation)s, %(form_type)s)
        ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE
          SET chunk_text   = EXCLUDED.chunk_text,
              chunk_tokens = EXCLUDED.chunk_tokens,
              cfr_citation = EXCLUDED.cfr_citation,
              ingested_at  = NOW()
          -- intentionally does NOT overwrite an existing embedding
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)
    conn.commit()
    return len(rows)


# ── Ingest pass ───────────────────────────────────────────────────────────────

def run_ingest(conn, ina_json: Path, reset: bool = False) -> None:
    print(f"\n=== INA Ingest pass ===")
    print(f"Source: {ina_json}")

    if not ina_json.exists():
        print(f"ERROR: {ina_json} not found. Run the scraper first.", file=sys.stderr)
        sys.exit(1)

    if reset:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE corpus = %s", (CORPUS,))
        conn.commit()
        print("Reset: cleared existing INA chunks")

    data = json.loads(ina_json.read_text(encoding="utf-8"))

    all_chunks: list[dict] = []
    section_count = 0

    for sub in data.get("subchapters", []):
        sub_label = f"Subchapter {sub['subchapter']} — {sub['title']}"
        sections  = sub.get("sections", [])
        print(f"  {sub_label}: {len(sections)} sections")
        for sec in sections:
            if not sec.get("text", "").strip():
                continue   # skip repealed / empty sections
            chunks = chunk_section(sec)
            all_chunks.extend(chunks)
            section_count += 1

    print(f"\n  {section_count} sections → {len(all_chunks)} chunks")
    saved = upsert_chunks(conn, all_chunks)
    print(f"  ✓ {saved} chunks written to rag_chunks (embedding=NULL)")


# ── Embed pass ────────────────────────────────────────────────────────────────

def check_ollama(model: str) -> None:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = json.loads(resp.read())
        models = [m["name"] for m in tags.get("models", [])]
        if not any(model.split(":")[0] in m for m in models):
            print(f"WARNING: model '{model}' not found in Ollama. Available: {models}")
            print(f"Run:  ollama pull {model}")
            sys.exit(1)
        print(f"Ollama OK — model: {model}")
    except Exception as e:
        print(f"ERROR: Cannot reach Ollama at {OLLAMA_URL}: {e}")
        print("Run:  ollama serve")
        sys.exit(1)


def embed_batch(texts: list) -> list:
    cleaned = [(DOC_INSTRUCT + t.strip()[:32000]) if t.strip() else " " for t in texts]
    payload = json.dumps({
        "model":   OLLAMA_MODEL,
        "input":   cleaned,
        "options": {"num_ctx": 32768},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return [vec[:EMBED_DIM] for vec in data["embeddings"]]


def run_embed(conn, batch_size: int = BATCH_SIZE) -> None:
    print(f"\n=== INA Embed pass ===")
    check_ollama(OLLAMA_MODEL)

    # Count pending
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE corpus = %s AND embedding IS NULL",
            (CORPUS,)
        )
        total = cur.fetchone()[0]

    if total == 0:
        print("  Nothing to embed — all INA chunks already have vectors.")
        return

    print(f"  {total} chunks to embed (batch_size={batch_size})")

    done = 0
    while True:
        # Fetch next batch of un-embedded chunks
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, chunk_text FROM rag_chunks
                WHERE corpus = %s AND embedding IS NULL
                ORDER BY id
                LIMIT %s
                """,
                (CORPUS, batch_size),
            )
            rows = cur.fetchall()

        if not rows:
            break

        texts      = [r["chunk_text"] for r in rows]
        ids        = [r["id"]         for r in rows]
        embeddings = embed_batch(texts)

        with conn.cursor() as cur:
            for row_id, vec in zip(ids, embeddings):
                vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                cur.execute(
                    "UPDATE rag_chunks SET embedding = %s::vector WHERE id = %s",
                    (vec_str, row_id),
                )
        conn.commit()

        done += len(rows)
        pct   = done / total * 100
        print(f"  {done}/{total} ({pct:.1f}%) embedded")
        time.sleep(0.05)

    print(f"  ✓ Embedding complete — {done} vectors written")

    # Rebuild HNSW index if it exists
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        vec_total = cur.fetchone()[0]
    if vec_total >= 10:
        print(f"\n  Refreshing HNSW index ({vec_total} total vectors)...")
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
            cur.execute("""
                CREATE INDEX idx_rag_embedding
                ON rag_chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """)
        conn.commit()
        print("  ✓ Index rebuilt")


# ── Status ────────────────────────────────────────────────────────────────────

def run_status(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                corpus,
                COUNT(*)                                        AS total_chunks,
                COUNT(*) FILTER (WHERE embedding IS NOT NULL)  AS embedded,
                COUNT(*) FILTER (WHERE embedding IS NULL)      AS pending,
                COUNT(DISTINCT source_id)                      AS sources
            FROM rag_chunks
            GROUP BY corpus
            ORDER BY corpus
        """)
        rows = cur.fetchall()

    print(f"\n{'corpus':<14} {'sources':>8} {'chunks':>8} {'embedded':>10} {'pending':>9}")
    print("─" * 54)
    for corpus, total, embedded, pending, sources in rows:
        print(f"{corpus:<14} {sources:>8} {total:>8} {embedded:>10} {pending:>9}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Ingest and/or embed the INA into rag_chunks")
    p.add_argument("--ingest",      action="store_true", help="Parse INA JSON and insert raw chunks")
    p.add_argument("--embed",       action="store_true", help="Embed all INA chunks missing vectors")
    p.add_argument("--status",      action="store_true", help="Show chunk/embedding counts per corpus")
    p.add_argument("--reset",       action="store_true", help="Delete existing INA chunks before ingesting")
    p.add_argument("--ina-json",    default=str(INA_JSON), help=f"Path to ina_full.json (default: {INA_JSON})")
    p.add_argument("--batch-size",  type=int, default=BATCH_SIZE, help="Ollama embedding batch size")
    return p.parse_args()


def main():
    args = parse_args()

    if not any([args.ingest, args.embed, args.status]):
        print("Specify at least one of --ingest, --embed, or --status")
        sys.exit(1)

    conn = get_conn()

    if args.status:
        run_status(conn)

    if args.ingest:
        run_ingest(conn, Path(args.ina_json), reset=args.reset)

    if args.embed:
        run_embed(conn, batch_size=args.batch_size)

    if args.ingest and not args.embed:
        print("\nRun --embed when Ollama is ready:")
        print(f"  python ingest_ina.py --embed")

    conn.close()


if __name__ == "__main__":
    main()
