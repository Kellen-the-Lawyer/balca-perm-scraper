#!/usr/bin/env python3
"""
USCIS Statistical Reports — RAG Ingestion
Loads FY2025 Q4 (and any future quarter) USCIS Excel reports into rag_chunks.

Each workbook sheet is converted to a readable text block, chunked at ~800
tokens, and embedded via Ollama.  Source files live in the "USCIS Reports"
folder (read from USCIS_REPORTS_DIR env var or the default path below).

Usage:
    python3 ingest_uscis.py --ingest          # parse + upsert raw chunks
    python3 ingest_uscis.py --embed           # embed chunks missing vectors
    python3 ingest_uscis.py --ingest --embed  # do both in one pass
    python3 ingest_uscis.py --status          # show chunk/embedding counts
    python3 ingest_uscis.py --reset --ingest  # wipe uscis_stats and re-ingest
    python3 ingest_uscis.py --ingest --limit 5  # test with first 5 files
"""

import os, re, sys, json, time, argparse, urllib.request
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

DB_URL     = os.environ.get("DATABASE_URL",
             "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:latest")
EMBED_DIM  = 1024       # MRL truncation — matches rest of project
CHUNK_TOKENS  = 800
OVERLAP_TOKENS = 80
BATCH_SIZE = 1          # one at a time, consistent with ingest_rag.py
CORPUS     = "uscis_stats"

# Default source dir — override with USCIS_REPORTS_DIR in .env
DEFAULT_REPORTS_DIR = (
    Path(__file__).resolve().parents[1] / "USCIS Reports"
)
REPORTS_DIR = Path(
    os.environ.get("USCIS_REPORTS_DIR", str(DEFAULT_REPORTS_DIR))
)

DOC_INSTRUCT = ""   # no prefix on document side (Qwen3 recommendation)

# ── Logging ───────────────────────────────────────────────────────────────────

import logging
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
    Add 'uscis_stats' to the rag_chunks_corpus_check constraint if missing.
    Drops and recreates the CHECK constraint with the new value appended.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'rag_chunks_corpus_check'
        """)
        row = cur.fetchone()
    if row is None:
        return  # no constraint — nothing to do
    defn = row[0]
    if "uscis_stats" in defn:
        return  # already present
    log.info("Patching rag_chunks_corpus_check to add 'uscis_stats'…")
    existing = re.findall(r"'(\w+)'", defn)
    existing.append("uscis_stats")
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
       %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s, %(embedding)s::vector,
       %(cfr_citation)s, %(form_type)s)
    ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE
      SET chunk_text  = EXCLUDED.chunk_text,
          embedding   = EXCLUDED.embedding,
          ingested_at = NOW()
"""


def upsert_chunks(conn, rows: list):
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows, page_size=50)
    conn.commit()

# ── Excel → text ──────────────────────────────────────────────────────────────

def _cell_str(val) -> str:
    """Convert a cell value to a clean string, dropping NaN/None."""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s in ("nan", "NaT", "None", "<NA>") else s


def sheet_to_text(df: pd.DataFrame, sheet_name: str, file_label: str) -> str:
    """
    Convert a DataFrame to a human-readable text block.

    Strategy:
    - Row 0 is often a title; rows 1-3 may be subtitle/date lines.
    - The first row that looks like a header (≥3 non-empty cells) becomes
      the column header row.
    - All data rows are serialised as  "Col: value | Col: value …"
      so the text is parseable without needing the original grid.
    """
    lines: list[str] = [f"Report: {file_label}", f"Sheet: {sheet_name}", ""]

    # Find header row (first row with ≥3 non-empty cells, skipping pure-title rows)
    header_idx = None
    for i, row in df.iterrows():
        non_empty = [_cell_str(v) for v in row if _cell_str(v)]
        if len(non_empty) >= 3:
            header_idx = i
            break

    if header_idx is None:
        # No usable header — just dump all rows as plain text
        for _, row in df.iterrows():
            cells = [_cell_str(v) for v in row if _cell_str(v)]
            if cells:
                lines.append(" | ".join(cells))
        return "\n".join(lines)

    # Title / subtitle lines before the header
    for i in range(header_idx):
        cells = [_cell_str(v) for v in df.iloc[i] if _cell_str(v)]
        if cells:
            lines.append(" ".join(cells))
    lines.append("")

    # Column headers (some may be empty — fill forward)
    raw_headers = [_cell_str(v) for v in df.iloc[header_idx]]
    headers: list[str] = []
    last = ""
    for h in raw_headers:
        if h:
            last = h
        headers.append(last if h or last else f"col{len(headers)}")

    # Data rows
    for _, row in df.iloc[header_idx + 1:].iterrows():
        pairs = []
        for h, v in zip(headers, row):
            s = _cell_str(v)
            if s:
                pairs.append(f"{h}: {s}")
        if pairs:
            lines.append(" | ".join(pairs))

    return "\n".join(lines)


def workbook_to_texts(path: Path) -> list[dict]:
    """
    Return a list of {source_id, source_label, text, form_type} dicts —
    one entry per sheet that has usable content.
    """
    results = []
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as e:
        log.warning(f"Cannot open {path.name}: {e}")
        return results

    # Derive a short label and form type from the filename
    name = path.stem
    # Extract form number (I-140, N-400, etc.) if present
    form_match = re.search(r'\b(I[-_]\d+[A-Z]?|N[-_]\d+[A-Z]?)\b', name, re.IGNORECASE)
    form_type = form_match.group(1).replace("_", "-").upper() if form_match else None

    # Short label: first 80 chars of stem, cleaned
    label = re.sub(r'_+', ' ', name).strip()[:80]

    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet, header=None, dtype=str)
        except Exception as e:
            log.warning(f"  Skipping sheet '{sheet}' in {path.name}: {e}")
            continue

        if df.empty or df.shape[0] < 2:
            continue

        text = sheet_to_text(df, sheet, label)
        if len(text.strip()) < 50:
            continue  # effectively empty

        # source_id: filename_stem + sheet name, normalised
        sid = re.sub(r'[^\w]', '_', f"{path.stem}__{sheet}")[:200]

        results.append({
            "source_id":    sid,
            "source_label": f"{label} — {sheet}",
            "form_type":    form_type,
            "text":         text,
        })

    return results

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

# ── Embedding ─────────────────────────────────────────────────────────────────

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

# ── Rebuild HNSW index ────────────────────────────────────────────────────────

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
    print(f"\n{'corpus':<20} {'sources':>8} {'chunks':>8} {'embedded':>10} {'pending':>9}")
    print("─" * 60)
    for corpus, sources, total, embedded, pending in rows:
        print(f"{corpus:<20} {sources:>8} {total:>8} {embedded:>10} {pending:>9}")
    print()

# ── --ingest ──────────────────────────────────────────────────────────────────

def run_ingest(conn, limit: int | None):
    files = sorted(REPORTS_DIR.glob("*.xlsx"))
    if not files:
        log.error(f"No .xlsx files found in {REPORTS_DIR}")
        sys.exit(1)

    if limit:
        files = files[:limit]

    log.info(f"Found {len(files)} workbook(s) in {REPORTS_DIR}")

    total_sheets = 0
    total_chunks = 0

    for path in files:
        log.info(f"  Processing: {path.name[:80]}")
        sheet_texts = workbook_to_texts(path)
        if not sheet_texts:
            log.warning(f"    No usable sheets found")
            continue

        rows = []
        for sheet in sheet_texts:
            chunks = chunk_by_paragraphs(sheet["text"])
            for i, text in enumerate(chunks):
                rows.append({
                    "corpus":         CORPUS,
                    "source_id":      sheet["source_id"],
                    "source_label":   sheet["source_label"],
                    "source_date":    None,   # quarterly — no single date
                    "source_outcome": None,
                    "chunk_index":    i,
                    "chunk_text":     text,
                    "chunk_tokens":   approx_tokens(text),
                    "embedding":      None,
                    "cfr_citation":   None,
                    "form_type":      sheet["form_type"],
                })
            total_sheets += 1
            total_chunks += len(chunks)

        upsert_chunks(conn, rows)
        log.info(f"    → {len(sheet_texts)} sheet(s), {sum(len(chunk_by_paragraphs(s['text'])) for s in sheet_texts)} chunk(s) upserted")

    log.info(f"\nIngest complete — {total_sheets} sheets, {total_chunks} chunks written to rag_chunks (corpus='{CORPUS}')")

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
        batch = pending[i : i + batch_size]
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
    parser = argparse.ArgumentParser(description="Ingest USCIS statistical reports into RAG")
    parser.add_argument("--ingest",     action="store_true", help="Parse workbooks and upsert raw chunks")
    parser.add_argument("--embed",      action="store_true", help="Embed chunks missing vectors")
    parser.add_argument("--status",     action="store_true", help="Show chunk/embedding counts per corpus")
    parser.add_argument("--reset",      action="store_true", help="Delete existing uscis_stats chunks before ingesting")
    parser.add_argument("--limit",      type=int, default=None, help="Cap number of workbooks (for testing)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Ollama embedding batch size")
    args = parser.parse_args()

    if not any([args.ingest, args.embed, args.status]):
        parser.print_help()
        sys.exit(0)

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
        # Verify Ollama is up before starting a potentially long embedding run
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                tags = json.loads(resp.read())
            models = [m["name"] for m in tags.get("models", [])]
            if not any(OLLAMA_MODEL.split(":")[0] in m for m in models):
                log.error(f"Model '{OLLAMA_MODEL}' not found in Ollama. Available: {models}")
                log.error("Run: ollama pull qwen3-embedding:latest")
                sys.exit(1)
            log.info(f"Ollama OK — model: {OLLAMA_MODEL}")
        except Exception as e:
            log.error(f"Cannot reach Ollama at {OLLAMA_URL}: {e}")
            log.error("Start Ollama first: ollama serve")
            sys.exit(1)

        run_embed(conn, args.batch_size)

    conn.close()


if __name__ == "__main__":
    main()
