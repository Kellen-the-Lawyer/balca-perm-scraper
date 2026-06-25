"""
RAG Ingestion Script — Casebase
Chunks all four corpora and embeds using text-embedding-3-small (1536 dims).

Usage:
    python3 ingest_rag.py [--corpus balca|aao|regulation|policy|all]
                          [--limit N]   # limit source rows for testing
                          [--reset]     # delete existing chunks first

Run regulations + policy first (fast), then balca, then aao (slow).
"""

import os
import re
import sys
import time
import json
import argparse
import urllib.request
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DB_URL         = os.environ.get("DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
EMBED_DIM      = 1024
CHUNK_TOKENS   = 800
OVERLAP_TOKENS = 80
BATCH_SIZE     = 50    # overnight runs — bump back to 20 for daytime use
# Instruction prefix — improves retrieval quality 1-5% per Qwen3 docs
QUERY_INSTRUCT = "Instruct: Given a legal research query, retrieve relevant passages that answer the query\nQuery: "
DOC_INSTRUCT   = ""    # no prefix on document side per Qwen3 recommendation

# ── Tokenisation ──────────────────────────────────────────────────────────────

def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_by_paragraphs(text: str, target: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list:
    if not text or not text.strip():
        return []
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    chunks = []
    current_parts = []
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

def _tail(parts: list, n_tokens: int) -> str:
    return _tail_str(" ".join(parts), n_tokens)

def _tail_str(text: str, n_tokens: int) -> str:
    chars = n_tokens * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(' ')
    return (snippet[idx+1:] if idx > 0 else snippet) + " "

def _split_long(text: str, target: int) -> list:
    sentences = re.split(r'(?<=[.!?])\s+', text)
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

def chunk_regulations(text: str, target: int = 600) -> list:
    if not text or not text.strip():
        return []
    section_pattern = re.compile(r'(?m)^§\s*\d+\.\d+[\w.]*')
    splits  = section_pattern.split(text)
    headers = section_pattern.findall(text)
    chunks  = []
    for i, body in enumerate(splits):
        header = headers[i-1] if i > 0 else ""
        full   = (header + "\n" + body).strip() if header else body.strip()
        if not full:
            continue
        if approx_tokens(full) <= target:
            chunks.append(full)
        else:
            chunks.extend(s for s in chunk_by_paragraphs(full, target) if s.strip())
    return chunks


# ── Embedding via Ollama ──────────────────────────────────────────────────────

def embed_batch(texts: list) -> list:
    """Embed texts via Voyage API (voyage-4-large). Delegates to app.embed."""
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parents[2]))
    from app.embed import embed_documents
    return embed_documents(texts)


def embed_query(text: str) -> list:
    """Embed a single query with the instruction prefix."""
    return embed_batch([QUERY_INSTRUCT + text.strip()[:32000]])[0]

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)

def upsert_chunks(conn, rows: list):
    sql = """
        INSERT INTO rag_chunks
          (corpus, source_id, source_label, source_date, source_outcome,
           chunk_index, chunk_text, chunk_tokens, embedding, cfr_citation, form_type)
        VALUES
          (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s, %(source_outcome)s,
           %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s, %(embedding)s::vector,
           %(cfr_citation)s, %(form_type)s)
        ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE
          SET chunk_text = EXCLUDED.chunk_text,
              embedding  = EXCLUDED.embedding,
              ingested_at = NOW()
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=50)
    conn.commit()

# ── Core batch embedder ───────────────────────────────────────────────────────

def _embed_and_save(conn, pending: list) -> int:
    if not pending:
        return 0
    texts = [p["chunk_text"] for p in pending]
    embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i+BATCH_SIZE]
        embeddings.extend(embed_batch(batch))
        done = i + len(batch)
        if done % (BATCH_SIZE * 10) == 0:
            print(f"    ... {done}/{len(texts)} embedded")
        # Small pause to avoid overwhelming Ollama on long runs
        if i + BATCH_SIZE < len(texts):
            time.sleep(0.05)

    rows_to_save = []
    for chunk_meta, vec in zip(pending, embeddings):
        row = dict(chunk_meta)
        row["embedding"] = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
        rows_to_save.append(row)

    upsert_chunks(conn, rows_to_save)
    return len(rows_to_save)

def _process_docs(conn, rows, corpus, id_key, text_key, chunk_fn,
                  label_key=None, label_fn=None, date_key=None, outcome_key=None):
    # Skip already-embedded docs so we can resume after a crash
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_id FROM rag_chunks WHERE corpus = %s", (corpus,))
        already_done = {r[0] for r in cur.fetchall()}
    if already_done:
        before = len(rows)
        rows = [r for r in rows if r[id_key] not in already_done]
        print(f"  Skipping {before - len(rows)} already-embedded docs, {len(rows)} remaining")

    all_pending = []
    total_chunks = 0
    for doc in rows:
        chunks = chunk_fn(doc[text_key])
        if not chunks:
            continue
        label   = label_fn(doc) if label_fn else doc.get(label_key, f"{corpus}-{doc[id_key]}")
        date    = doc.get(date_key) if date_key else None
        outcome = doc.get(outcome_key) if outcome_key else None
        for i, text in enumerate(chunks):
            all_pending.append({
                "corpus": corpus, "source_id": doc[id_key],
                "source_label": label or f"{corpus}-{doc[id_key]}",
                "source_date": date, "source_outcome": outcome,
                "chunk_index": i, "chunk_text": text,
                "chunk_tokens": approx_tokens(text),
                "cfr_citation": None, "form_type": None,
            })
        if len(all_pending) >= BATCH_SIZE * 5:
            total_chunks += _embed_and_save(conn, all_pending)
            all_pending = []
    if all_pending:
        total_chunks += _embed_and_save(conn, all_pending)
    print(f"  Done — {total_chunks} chunks ingested")


# ── Per-corpus ingestion ──────────────────────────────────────────────────────

def ingest_balca(conn, limit=None, date_from=None, date_to=None):
    print("\n=== Ingesting BALCA decisions ===")
    lim = f"LIMIT {limit}" if limit else ""
    conditions = ["text_extracted = TRUE", "full_text != ''"]
    if date_from:
        conditions.append(f"decision_date >= '{date_from}'")
    if date_to:
        conditions.append(f"decision_date <= '{date_to}'")
    where = " AND ".join(conditions)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT id, case_number, decision_date::text, outcome, full_text
            FROM decisions WHERE {where}
            ORDER BY decision_date DESC NULLS LAST {lim}
        """)
        rows = cur.fetchall()
    print(f"  {len(rows)} decisions to chunk")
    _process_docs(conn, rows, corpus="balca",
                  id_key="id", label_key="case_number",
                  date_key="decision_date", outcome_key="outcome",
                  text_key="full_text", chunk_fn=chunk_by_paragraphs)

def ingest_aao(conn, limit=None, date_from=None, date_to=None):
    print("\n=== Ingesting AAO decisions ===")
    lim = f"LIMIT {limit}" if limit else ""
    conditions = ["text_extracted = TRUE", "full_text != ''"]
    if date_from:
        conditions.append(f"decision_date >= '{date_from}'")
    if date_to:
        conditions.append(f"decision_date <= '{date_to}'")
    where = " AND ".join(conditions)

    # Get total count and already-done set
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM aao_decisions WHERE {where}")
        total_count = cur.fetchone()[0]
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_id FROM rag_chunks WHERE corpus = 'aao'")
        already_done = {r[0] for r in cur.fetchall()}

    remaining = total_count - len(already_done)
    print(f"  {total_count} decisions total, {len(already_done)} already embedded, {remaining} remaining")

    # Process in batches of 500 decisions to avoid loading all into RAM
    DECISION_BATCH = 500
    offset = 0
    total = 0

    while True:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT id, COALESCE(title, form_type, filename) AS label,
                       decision_date::text, outcome, form_type, full_text
                FROM aao_decisions WHERE {where}
                ORDER BY decision_date DESC NULLS LAST
                LIMIT {DECISION_BATCH} OFFSET {offset}
            """)
            rows = cur.fetchall()

        if not rows:
            break

        # Skip already embedded
        rows = [r for r in rows if str(r["id"]) not in already_done and r["id"] not in already_done]
        if not rows:
            offset += DECISION_BATCH
            continue

        all_pending = []
        for doc in rows:
            chunks = chunk_by_paragraphs(doc["full_text"])
            if not chunks:
                continue
            for i, text in enumerate(chunks):
                all_pending.append({
                    "corpus": "aao", "source_id": doc["id"],
                    "source_label": doc["label"] or f"AAO-{doc['id']}",
                    "source_date": doc["decision_date"], "source_outcome": doc["outcome"],
                    "chunk_index": i, "chunk_text": text,
                    "chunk_tokens": approx_tokens(text),
                    "cfr_citation": None, "form_type": doc.get("form_type"),
                })

        if all_pending:
            batch_total = _embed_and_save(conn, all_pending)
            total += batch_total
            print(f"  [{offset + DECISION_BATCH}/{total_count}] {total} chunks embedded so far")

        offset += DECISION_BATCH

    print(f"  Done — {total} chunks ingested")

def ingest_regulations(conn, limit=None):
    print("\n=== Ingesting Regulations ===")
    lim = f"LIMIT {limit}" if limit else ""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT id, title, cfr_title, cfr_part, as_of_date::text, full_text
            FROM regulations_docs WHERE full_text != ''
            ORDER BY cfr_title, cfr_part {lim}
        """)
        rows = cur.fetchall()
    print(f"  {len(rows)} regulation docs to chunk")
    all_pending = []
    for doc in rows:
        chunks = chunk_regulations(doc["full_text"])
        if not chunks:
            continue
        cfr   = f"{doc['cfr_title']} CFR {doc['cfr_part']}" if doc.get("cfr_title") and doc.get("cfr_part") else None
        label = doc["title"] or cfr or f"reg-{doc['id']}"
        for i, text in enumerate(chunks):
            m         = re.search(r'§\s*(\d+\.\d+[\w.]*)', text)
            chunk_cfr = f"{doc['cfr_title']} CFR {m.group(1)}" if m and doc.get("cfr_title") else cfr
            all_pending.append({
                "corpus": "regulation", "source_id": doc["id"],
                "source_label": label, "source_date": doc["as_of_date"],
                "source_outcome": None, "chunk_index": i, "chunk_text": text,
                "chunk_tokens": approx_tokens(text),
                "cfr_citation": chunk_cfr, "form_type": None,
            })
    total = _embed_and_save(conn, all_pending)
    print(f"  Done — {total} chunks ingested")

def ingest_policy(conn, limit=None):
    print("\n=== Ingesting Policy Docs ===")
    lim = f"LIMIT {limit}" if limit else ""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT id, source, title, section, subject, as_of_date::text, full_text
            FROM policy_docs WHERE full_text != ''
            ORDER BY source, section {lim}
        """)
        rows = cur.fetchall()
    print(f"  {len(rows)} policy sections to chunk")
    _process_docs(conn, rows, corpus="policy", id_key="id",
                  label_fn=lambda r: f"{r['source']} {r.get('section','')} — {r.get('subject','')}".strip(" —"),
                  date_key="as_of_date", outcome_key=None,
                  text_key="full_text",
                  chunk_fn=lambda t: chunk_by_paragraphs(t, target=600))


# ── Index rebuild ─────────────────────────────────────────────────────────────

def rebuild_index(conn):
    print("\nRebuilding HNSW index...")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        count = cur.fetchone()[0]
        if count < 10:
            print(f"  Only {count} vectors — skipping")
            return
        cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
        cur.execute("""
            CREATE INDEX idx_rag_embedding
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
    conn.commit()
    print(f"  Done — HNSW index built for {count} vectors")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest Casebase corpus into RAG vector store")
    parser.add_argument("--corpus", default="all",
                        choices=["balca","aao","regulation","policy","all"])
    parser.add_argument("--limit",     type=int, default=None,
                        help="Limit source rows per corpus (for testing)")
    parser.add_argument("--date-from", default=None,
                        help="Only ingest decisions on or after this date (YYYY-MM-DD) — AAO and BALCA only")
    parser.add_argument("--date-to",   default=None,
                        help="Only ingest decisions on or before this date (YYYY-MM-DD) — AAO and BALCA only")
    parser.add_argument("--reset",     action="store_true",
                        help="Delete existing chunks before ingesting")
    args = parser.parse_args()

    # Verify Ollama is running and model is available
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tags = json.loads(resp.read())
        models = [m["name"] for m in tags.get("models", [])]
            print("Run: ollama pull qwen3-embedding:8b")
            sys.exit(1)
    except Exception as e:
        print("Make sure Ollama is running: ollama serve")
        sys.exit(1)

    conn = get_conn()

    if args.reset:
        corp = args.corpus if args.corpus != "all" else None
        with conn.cursor() as cur:
            if corp:
                cur.execute("DELETE FROM rag_chunks WHERE corpus = %s", (corp,))
                print(f"Reset: cleared chunks for corpus={corp}")
            else:
                cur.execute("DELETE FROM rag_chunks")
                print("Reset: cleared all chunks")
        conn.commit()

    t0 = time.time()
    corpora = [args.corpus] if args.corpus != "all" else ["regulation","policy","balca","aao"]

    for corpus in corpora:
        if corpus == "balca":        ingest_balca(conn, args.limit, args.date_from, args.date_to)
        elif corpus == "aao":        ingest_aao(conn, args.limit, args.date_from, args.date_to)
        elif corpus == "regulation": ingest_regulations(conn, args.limit)
        elif corpus == "policy":     ingest_policy(conn, args.limit)

    rebuild_index(conn)
    conn.close()
    print(f"\nTotal time: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
