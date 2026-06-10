#!/usr/bin/env python3
"""
DOL ETA Foreign Labor FAQ — PDF Extractor + RAG Ingestion

Reads PDFs from perm-research/data/pdfs/dol/, extracts Q&A pairs,
and loads them into rag_chunks (corpus='dol_faqs').

Each Q&A pair becomes a document; long answers are chunked at
~800 tokens with 80-token overlap.

Usage:
    python3 ingest_dol_faqs.py --extract          # parse PDFs → JSON
    python3 ingest_dol_faqs.py --ingest           # JSON → PostgreSQL chunks
    python3 ingest_dol_faqs.py --embed            # embed chunks via Ollama
    python3 ingest_dol_faqs.py --extract --ingest --embed   # full pipeline
    python3 ingest_dol_faqs.py --status           # show chunk/embedding counts
    python3 ingest_dol_faqs.py --reset --ingest   # wipe corpus and re-ingest
    python3 ingest_dol_faqs.py --list             # list detected PDFs + categories

Reads:  perm-research/data/pdfs/dol/*.pdf
Writes: perm-research/data/dol_faqs.json
        rag_chunks (corpus='dol_faqs') in perm_decisions database
"""

import os
import re
import sys
import io
import json
import time
import argparse
import urllib.request
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras
import pdfplumber
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
CORPUS       = "dol_faqs"
DOC_INSTRUCT = ""

PDF_DIR     = Path(__file__).resolve().parent / "data" / "pdfs" / "dol"
OUTPUT_JSON = Path(__file__).resolve().parent / "data" / "dol_faqs.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Category detection ────────────────────────────────────────────────────────

# Maps filename keywords → canonical category label
# Note: underscores and hyphens may both appear in filenames
_CATEGORY_RULES: list[tuple[str, str]] = [
    (r"perm|perfm",                       "PERM"),       # "Perfm" is a DOL typo
    (r"h[-_]?2a|h2a",                     "H-2A"),
    (r"h[-_]?2b|h2b",                     "H-2B"),
    (r"h[-_]?1b|h1b|h[-_]?1b1|e[-_]?3",  "H-1B/H-1B1/E-3"),
    (r"cw[-_]?1|cnmi",                    "CW-1/CNMI"),
    (r"npwhc",                            "NPWHC"),
]


def detect_category(filename: str, first_page_text: str = "") -> str:
    name = filename.lower()
    for pattern, label in _CATEGORY_RULES:
        if re.search(pattern, name):
            return label
    # fallback: check first page text (catches files like Round-16/17 with no form in filename)
    text = first_page_text.lower()
    for pattern, label in _CATEGORY_RULES:
        if re.search(pattern, text):
            return label
    return "General"


def detect_round(filename: str, title_text: str = "") -> str:
    """Extract round/series label from filename or title."""
    for src in [filename, title_text]:
        lower = src.lower()
        # Named series take priority — checked before round numbers so that
        # "Fraud_Rule_Round2" stays "Fraud" rather than becoming "Round 2"
        for tag in ["fraud", "supervised", "appeals", "clarification",
                    "change of address", "rescinded", "implementation", "appendix"]:
            if tag in lower:
                return tag.title()
        # Match round numbers ≤ 30 (avoids Section 508 accessibility codes and dates)
        for m in re.finditer(
            r"(?:round|rd\.?)[-_\s]*(\d{1,2})\b|faq[-_\s]*(\d{1,2})\b",
            src, re.IGNORECASE,
        ):
            n = int(m.group(1) or m.group(2))
            if n <= 30:
                return f"Round {n}"
    return ""

# ── PDF text extraction ───────────────────────────────────────────────────────

def extract_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        pages = []
        for page in pdf.pages:
            t = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            pages.append(t)
    raw = "\n".join(pages)
    raw = re.sub(r"\r\n|\r", "\n", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


# ── Q&A pair extraction ───────────────────────────────────────────────────────

# Matches lines like:  Q:   Q.   Q1.   Q 1:   Question:   Question 1:
_Q_RE = re.compile(
    r"^\s*(?:Q(?:uestion)?\.?\s*\d*[:.]?\s*|Q\d+[:.]\s*)",
    re.IGNORECASE,
)
# Matches lines like:  A:   A.   Answer:
_A_RE = re.compile(
    r"^\s*(?:A(?:nswer)?\.?\s*[:.]?\s*)",
    re.IGNORECASE,
)


def _strip_qa_prefix(line: str) -> str:
    """Remove leading Q:/A: marker from a line."""
    return re.sub(r"^\s*(?:[QAqa](?:uestion|nswer)?\.?\s*\d*\s*[:.])\s*", "", line).strip()


def extract_qa_pairs(text: str) -> list[tuple[str, str]]:
    """
    Parse text into (question, answer) tuples.
    Falls back to paragraph blocks if no Q:/A: markers found.
    """
    lines = text.splitlines()
    pairs: list[tuple[str, str]] = []

    # Check whether the document uses Q:/A: markers
    q_count = sum(1 for l in lines if _Q_RE.match(l))
    if q_count < 2:
        return _fallback_pairs(text)

    state = None  # "Q" or "A"
    q_buf: list[str] = []
    a_buf: list[str] = []

    def flush():
        if q_buf and a_buf:
            q = " ".join(q_buf).strip()
            a = " ".join(a_buf).strip()
            if q and a:
                pairs.append((q, a))
        q_buf.clear()
        a_buf.clear()

    for line in lines:
        if _Q_RE.match(line):
            flush()
            state = "Q"
            q_buf.append(_strip_qa_prefix(line))
        elif _A_RE.match(line) and state in ("Q", "A"):
            state = "A"
            a_buf.append(_strip_qa_prefix(line))
        else:
            stripped = line.strip()
            if not stripped:
                continue
            if state == "Q":
                q_buf.append(stripped)
            elif state == "A":
                a_buf.append(stripped)

    flush()
    return pairs if pairs else _fallback_pairs(text)


def _fallback_pairs(text: str) -> list[tuple[str, str]]:
    """
    When no Q:/A: markers exist, split by double-newline paragraphs and
    pair consecutive paragraphs as (question, answer).
    """
    paras = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    pairs = []
    i = 0
    while i < len(paras) - 1:
        pairs.append((paras[i], paras[i + 1]))
        i += 2
    if i < len(paras):
        pairs.append((paras[i], ""))
    return pairs

# ── Record building ───────────────────────────────────────────────────────────

def pdf_to_records(pdf_path: Path) -> list[dict]:
    log.info(f"  Extracting: {pdf_path.name}")
    try:
        text = extract_text(pdf_path)
    except Exception as e:
        log.error(f"    pdfplumber failed: {e}")
        return []

    if not text.strip():
        log.warning(f"    No text extracted (may be scanned): {pdf_path.name}")
        return []

    # Use first 500 chars of text for category/round detection fallback
    first_block = text[:500]
    category = detect_category(pdf_path.stem, first_block)
    round_label = detect_round(pdf_path.stem, first_block)

    classification = f"{category} — {round_label}" if round_label else category

    pairs = extract_qa_pairs(text)
    log.info(f"    {len(pairs)} Q&A pair(s) → category: {classification}")

    today = __import__("datetime").date.today().isoformat()
    records = []
    for i, (question, answer) in enumerate(pairs):
        content = f"Q: {question}\n\nA: {answer}" if answer else f"Q: {question}"
        records.append({
            "form":             category,
            "classification":   classification,
            "question_index":   i,
            "question":         question,
            "answer":           answer,
            "requirement_type": "dol_faq",
            "content":          content,
            "source_file":      pdf_path.name,
            "source_url":       "https://www.dol.gov/agencies/eta/foreign-labor/faqs/print",
            "scraped_date":     today,
        })
    return records

# ── --extract ─────────────────────────────────────────────────────────────────

def run_extract(limit: int | None = None) -> list[dict]:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        log.error(f"No PDFs found in {PDF_DIR}")
        log.error("Drop DOL FAQ PDFs into that directory first.")
        sys.exit(1)

    log.info(f"Found {len(pdfs)} PDF(s) in {PDF_DIR}")
    if limit:
        pdfs = pdfs[:limit]

    all_records: list[dict] = []
    for pdf_path in pdfs:
        records = pdf_to_records(pdf_path)
        all_records.extend(records)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    log.info(f"\nExtracted {len(all_records)} Q&A records from {len(pdfs)} PDF(s)")
    log.info(f"Saved: {OUTPUT_JSON}")

    # Summary by category
    by_cat: dict[str, int] = {}
    for r in all_records:
        by_cat[r["form"]] = by_cat.get(r["form"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        log.info(f"  {cat}: {n} record(s)")

    return all_records

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


def ensure_corpus_allowed(conn):
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


def make_source_id(classification: str, question_index: int) -> str:
    slug = re.sub(r"[^\w]", "_", classification).lower()
    slug = re.sub(r"_+", "_", slug).strip("_")
    return f"{slug[:180]}__{question_index}"

# ── --ingest ──────────────────────────────────────────────────────────────────

def run_ingest(conn, limit: int | None):
    if not OUTPUT_JSON.exists():
        log.error(f"JSON not found: {OUTPUT_JSON}")
        log.error("Run --extract first.")
        sys.exit(1)

    with open(OUTPUT_JSON, encoding="utf-8") as f:
        records = json.load(f)

    log.info(f"Loaded {len(records)} records from {OUTPUT_JSON}")
    if limit:
        records = records[:limit]

    total_chunks = 0
    rows: list[dict] = []

    for rec in records:
        category       = rec.get("form", "")
        classification = rec.get("classification", "")
        content        = rec.get("content", "").strip()
        source_url     = rec.get("source_url", "")
        scraped_date   = rec.get("scraped_date")
        q_index        = rec.get("question_index", 0)

        if not content:
            continue

        source_id    = make_source_id(classification, q_index)
        source_label = classification

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
                "form_type":      category,
            })
        total_chunks += len(chunks)

    if not rows:
        log.warning("No chunks to ingest.")
        return

    upsert_chunks(conn, rows)
    log.info(
        f"Ingest complete — {len(records)} Q&A records, "
        f"{total_chunks} chunks upserted (corpus='{CORPUS}')"
    )

    by_cat: dict[str, int] = {}
    for r in rows:
        ft = r["form_type"] or "?"
        by_cat[ft] = by_cat.get(ft, 0) + 1
    for cat, count in sorted(by_cat.items()):
        log.info(f"  {cat}: {count} chunk(s)")

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


def rebuild_hnsw(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        n = cur.fetchone()[0]
    if n < 10:
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

# ── --list ────────────────────────────────────────────────────────────────────

def run_list():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}")
        return
    print(f"\n{len(pdfs)} PDF(s) in {PDF_DIR}:\n")
    for p in pdfs:
        cat = detect_category(p.stem)
        rnd = detect_round(p.stem)
        label = f"{cat} — {rnd}" if rnd else cat
        print(f"  {p.name:<60}  [{label}]")
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"Ingest DOL ETA Foreign Labor FAQs into RAG (corpus='{CORPUS}')"
    )
    parser.add_argument("--extract",    action="store_true",
                        help="Parse PDFs and write JSON")
    parser.add_argument("--ingest",     action="store_true",
                        help="Parse JSON and upsert raw chunks")
    parser.add_argument("--embed",      action="store_true",
                        help="Embed chunks missing vectors via Ollama")
    parser.add_argument("--status",     action="store_true",
                        help="Show chunk/embedding counts per corpus")
    parser.add_argument("--reset",      action="store_true",
                        help=f"Delete existing '{CORPUS}' chunks before ingesting")
    parser.add_argument("--list",       action="store_true",
                        help="List detected PDFs and their inferred categories")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap number of records (for testing)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Ollama embedding batch size")
    args = parser.parse_args()

    if not any([args.extract, args.ingest, args.embed, args.status, args.list]):
        parser.print_help()
        sys.exit(0)

    if args.list:
        run_list()

    if args.extract:
        run_extract(args.limit)

    if args.ingest or args.embed or args.status or args.reset:
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
