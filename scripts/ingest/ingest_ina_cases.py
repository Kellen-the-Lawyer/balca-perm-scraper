#!/usr/bin/env python3
"""
Casebase — BALCA INA Case Decisions Ingest
===========================================
Reads PDF files from a directory of BALCA INA decisions, extracts text,
chunks, and loads into rag_chunks. Embedding is a separate pass.

Usage:
    python ingest_ina_cases.py --ingest                   # parse + insert raw chunks
    python ingest_ina_cases.py --embed                    # embed chunks missing vectors
    python ingest_ina_cases.py --ingest --embed           # both in one shot
    python ingest_ina_cases.py --ingest --reset           # drop existing ina_cases chunks first
    python ingest_ina_cases.py --status                   # show counts per corpus
    python ingest_ina_cases.py --ingest --limit 50        # test with 50 PDFs
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Config ─────────────────────────────────────────────────────────────────────

DB_URL       = os.environ.get("DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b")
SOURCE_DIR   = Path(os.environ.get("INA_CASES_DIR", "/Users/Dad/Documents/GitHub/casebase-app/data/ina/pdfs"))

CORPUS        = "ina_cases"
EMBED_DIM     = 1024
CHUNK_TOKENS  = 800
OVERLAP_TOKENS = 80
BATCH_SIZE    = 2

DOC_INSTRUCT   = ""
QUERY_INSTRUCT = "Instruct: Given a legal research query, retrieve relevant passages that answer the query\nQuery: "

# ── Regex patterns ─────────────────────────────────────────────────────────────

DOCKET_RE = re.compile(r"\b(\d{4})-?(INA)-?(\d{3,6})\b", re.IGNORECASE)
DATE_RE   = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),\s+(\d{4})", re.IGNORECASE
)
OUTCOME_PATTERNS = [
    (re.compile(r"\bSUSTAINED\b",  re.IGNORECASE), "Sustained"),
    (re.compile(r"\bDISMISSED\b",  re.IGNORECASE), "Dismissed"),
    (re.compile(r"\bREMANDED\b",   re.IGNORECASE), "Remanded"),
    (re.compile(r"\bWITHDRAWN\b",  re.IGNORECASE), "Withdrawn"),
    (re.compile(r"\bDENIED\b",     re.IGNORECASE), "Denied"),
    (re.compile(r"\bAPPROVED\b",   re.IGNORECASE), "Approved"),
    (re.compile(r"\bAFFIRMED\b",   re.IGNORECASE), "Affirmed"),
    (re.compile(r"\bREVERSED\b",   re.IGNORECASE), "Reversed"),
]


# ── Text extraction (top-level for pickling) ───────────────────────────────────

def extract_one(args: tuple) -> dict:
    """Runs in subprocess — must be top-level and picklable."""
    pdf_path, filename = args
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n\n".join(pages)
        return {"filename": filename, "text": text, "error": None}
    except Exception as e:
        return {"filename": filename, "text": "", "error": str(e)}


# ── Chunking ───────────────────────────────────────────────────────────────────

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
    chunks, current_parts, current_tokens, overlap_tail = [], [], 0, ""
    for para in paragraphs:
        para_tokens = approx_tokens(para)
        if para_tokens > target:
            if current_parts:
                chunks.append((overlap_tail + " ".join(current_parts)).strip())
                overlap_tail = _tail(current_parts, overlap)
                current_parts, current_tokens = [], 0
            for sub in _split_long(para, target):
                if sub.strip():
                    chunks.append((overlap_tail + sub).strip())
                    overlap_tail = _tail_str(sub, overlap)
            continue
        if current_tokens + para_tokens > target and current_parts:
            chunks.append((overlap_tail + " ".join(current_parts)).strip())
            overlap_tail = _tail(current_parts, overlap)
            current_parts, current_tokens = [], 0
        current_parts.append(para)
        current_tokens += para_tokens
    if current_parts:
        chunks.append((overlap_tail + " ".join(current_parts)).strip())
    return [c for c in chunks if c.strip()]


# ── Metadata extraction ────────────────────────────────────────────────────────

def detect_outcome(text: str) -> str | None:
    tail = text[-2000:] if len(text) > 2000 else text
    for pattern, label in OUTCOME_PATTERNS:
        if pattern.search(tail):
            return label
    return None

def extract_docket(filename: str, text: str) -> str:
    # Try filename first (most reliable)
    m = DOCKET_RE.search(filename)
    if m:
        return m.group(0).upper()
    m = DOCKET_RE.search(text[:2000])
    if m:
        return m.group(0).upper()
    return Path(filename).stem

def extract_date(text: str) -> str | None:
    m = DATE_RE.search(text[:3000])
    if m:
        try:
            from datetime import datetime
            return datetime.strptime(f"{m.group(1)} {m.group(2)}, {m.group(3)}", "%B %d, %Y").date().isoformat()
        except Exception:
            pass
    return None


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    return conn

def ensure_corpus_allowed(conn) -> None:
    """Add ina_cases to the corpus CHECK constraint if not already present."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'rag_chunks_corpus_check'
        """)
        row = cur.fetchone()
        if row and CORPUS in row[0]:
            return  # already there
        existing = re.findall(r"'([^']+)'::text", row[0]) if row else [
            'balca','aao','regulation','policy','ina','uscis_stats',
            'uscis_checklists','form_instructions','dol_faqs','cbp_ifm',
            'final_rules','court_opinions',
        ]
        if CORPUS not in existing:
            existing.append(CORPUS)
        values = ", ".join(f"'{v}'" for v in existing)
        cur.execute("ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_corpus_check")
        cur.execute(f"""
            ALTER TABLE rag_chunks ADD CONSTRAINT rag_chunks_corpus_check
            CHECK (corpus = ANY (ARRAY[{values}]))
        """)
    conn.commit()
    print(f"Corpus constraint updated to include '{CORPUS}'")

UPSERT_SQL = """
    INSERT INTO rag_chunks
      (corpus, source_id, source_label, source_date, source_outcome,
       chunk_index, chunk_text, chunk_tokens, embedding, cfr_citation, form_type)
    VALUES
      (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s, %(source_outcome)s,
       %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s,
       %(embedding)s, %(cfr_citation)s, %(form_type)s)
    ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE
      SET chunk_text    = EXCLUDED.chunk_text,
          chunk_tokens  = EXCLUDED.chunk_tokens,
          source_label  = EXCLUDED.source_label,
          source_date   = EXCLUDED.source_date,
          source_outcome = EXCLUDED.source_outcome,
          ingested_at   = NOW()
"""

def upsert_chunks(conn, rows: list) -> int:
    if not rows:
        return 0
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows, page_size=200)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


# ── Ingest pass ────────────────────────────────────────────────────────────────

def run_ingest(conn, source_dir: Path, reset: bool, workers: int, limit: int | None) -> None:
    print(f"\n=== INA Cases Ingest ===")
    print(f"Source dir : {source_dir}")

    ensure_corpus_allowed(conn)

    if not source_dir.exists():
        print(f"ERROR: {source_dir} not found.", file=sys.stderr)
        sys.exit(1)

    pdf_files = sorted(source_dir.glob("*.pdf")) + sorted(source_dir.glob("*.PDF"))
    if limit:
        pdf_files = pdf_files[:limit]
    print(f"PDFs found : {len(pdf_files)}")

    if reset:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE corpus = %s", (CORPUS,))
        conn.commit()
        print("Reset: cleared existing ina_cases chunks")

    # Check which source_ids are already ingested to support resume
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_id FROM rag_chunks WHERE corpus = %s", (CORPUS,))
        already_done = {r[0] for r in cur.fetchall()}

    todo = [(p, p.name) for p in pdf_files if Path(p.name).stem not in already_done]
    print(f"Already ingested: {len(already_done)} | Remaining: {len(todo)}")

    if not todo:
        print("Nothing to do.")
        return

    ok, errors, total_chunks = 0, 0, 0

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(extract_one, args): args[1] for args in todo}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            filename = result["filename"]
            stem     = Path(filename).stem

            if result["error"]:
                print(f"  [{i}/{len(todo)}] ERROR {filename}: {result['error']}")
                errors += 1
                continue

            text = result["text"]
            if not text.strip():
                print(f"  [{i}/{len(todo)}] SKIP  {filename} (empty text)")
                errors += 1
                continue

            docket  = extract_docket(filename, text)
            date    = extract_date(text)
            outcome = detect_outcome(text)
            label   = f"BALCA INA — {docket}"

            raw_chunks = chunk_by_paragraphs(text)
            rows = [
                {
                    "corpus":         CORPUS,
                    "source_id":      stem,
                    "source_label":   label,
                    "source_date":    date,
                    "source_outcome": outcome,
                    "chunk_index":    idx,
                    "chunk_text":     chunk,
                    "chunk_tokens":   approx_tokens(chunk),
                    "embedding":      None,
                    "cfr_citation":   None,
                    "form_type":      None,
                }
                for idx, chunk in enumerate(raw_chunks)
            ]

            upsert_chunks(conn, rows)
            total_chunks += len(rows)
            ok += 1

            if i % 100 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {ok} ok / {errors} errors / {total_chunks} chunks so far")

    print(f"\n✓ Ingest complete: {ok} PDFs / {total_chunks} chunks / {errors} errors")


# ── Embed pass ─────────────────────────────────────────────────────────────────

def check_ollama() -> None:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = json.loads(resp.read())
        models = [m["name"] for m in tags.get("models", [])]
        if not any(OLLAMA_MODEL.split(":")[0] in m for m in models):
            print(f"WARNING: model '{OLLAMA_MODEL}' not found. Available: {models}")
            print(f"Run: ollama pull {OLLAMA_MODEL}")
            sys.exit(1)
        print(f"Ollama OK — model: {OLLAMA_MODEL}")
    except Exception as e:
        print(f"ERROR: Cannot reach Ollama at {OLLAMA_URL}: {e}")
        sys.exit(1)

def embed_batch(texts: list) -> list:
    cleaned = [(DOC_INSTRUCT + t.strip()[:32000]) if t.strip() else " " for t in texts]
    payload = json.dumps({
        "model":      OLLAMA_MODEL,
        "input":      cleaned,
        "keep_alive": "30m",
        "options":    {"num_ctx": 32768},
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

def run_embed(conn, batch_size: int) -> None:
    print(f"\n=== INA Cases Embed pass ===")
    check_ollama()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE corpus = %s AND embedding IS NULL",
            (CORPUS,)
        )
        total = cur.fetchone()[0]

    if total == 0:
        print("Nothing to embed — all chunks already have vectors.")
        return

    print(f"{total} chunks to embed (batch_size={batch_size})")
    done = 0

    while True:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, chunk_text FROM rag_chunks WHERE corpus = %s AND embedding IS NULL ORDER BY id LIMIT %s",
                (CORPUS, batch_size),
            )
            rows = cur.fetchall()
        if not rows:
            break

        embeddings = embed_batch([r["chunk_text"] for r in rows])
        with conn.cursor() as cur:
            for row, vec in zip(rows, embeddings):
                vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                cur.execute(
                    "UPDATE rag_chunks SET embedding = %s::vector WHERE id = %s",
                    (vec_str, row["id"]),
                )
        conn.commit()
        done += len(rows)
        print(f"  {done}/{total} ({done/total*100:.1f}%) embedded")
        time.sleep(0.05)

    print(f"✓ Embedding complete — {done} vectors written")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        vec_total = cur.fetchone()[0]
    if vec_total >= 10:
        print(f"Rebuilding HNSW index ({vec_total} total vectors)...")
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
            cur.execute("""
                CREATE INDEX idx_rag_embedding
                ON rag_chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """)
        conn.commit()
        print("✓ HNSW index rebuilt")


# ── Status ─────────────────────────────────────────────────────────────────────

def run_status(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT corpus,
                   COUNT(DISTINCT source_id)                       AS sources,
                   COUNT(*)                                        AS total_chunks,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL)  AS embedded,
                   COUNT(*) FILTER (WHERE embedding IS NULL)      AS pending
            FROM rag_chunks GROUP BY corpus ORDER BY corpus
        """)
        rows = cur.fetchall()
    print(f"\n{'corpus':<16} {'sources':>8} {'chunks':>8} {'embedded':>10} {'pending':>9}")
    print("─" * 56)
    for corpus, sources, total, embedded, pending in rows:
        print(f"{corpus:<16} {sources:>8} {total:>8} {embedded:>10} {pending:>9}")


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Ingest BALCA INA case PDFs into rag_chunks")
    p.add_argument("--ingest",      action="store_true", help="Extract PDFs and insert raw chunks")
    p.add_argument("--embed",       action="store_true", help="Embed chunks missing vectors")
    p.add_argument("--status",      action="store_true", help="Show chunk/embedding counts")
    p.add_argument("--reset",       action="store_true", help="Delete existing ina_cases chunks first")
    p.add_argument("--source-dir",  default=str(SOURCE_DIR), help="Directory of INA PDFs")
    p.add_argument("--workers",     type=int, default=4, help="ProcessPoolExecutor workers")
    p.add_argument("--limit",       type=int, default=None, help="Cap number of PDFs (for testing)")
    p.add_argument("--batch-size",  type=int, default=BATCH_SIZE, help="Ollama embedding batch size")
    args = p.parse_args()

    if not any([args.ingest, args.embed, args.status]):
        print("Specify at least one of --ingest, --embed, or --status")
        sys.exit(1)

    conn = get_conn()

    if args.status:
        run_status(conn)
    if args.ingest:
        run_ingest(conn, Path(args.source_dir), reset=args.reset, workers=args.workers, limit=args.limit)
    if args.embed:
        run_embed(conn, batch_size=args.batch_size)
    if args.ingest and not args.embed:
        print(f"\nRun --embed when Ollama is ready:")
        print(f"  python3 ingest_ina_cases.py --embed")

    conn.close()

if __name__ == "__main__":
    main()
