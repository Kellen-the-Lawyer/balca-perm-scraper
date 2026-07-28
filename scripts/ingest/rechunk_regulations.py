"""
Rebuild the corpus='regulation' rag_chunks from regulations_docs.full_text,
section-aware: each chunk carries its true section citation (e.g.
"8 CFR 214.2"), not the part-level fallback. Chunking follows the standard
project chunker at a finer 400-token target (~1.6K chars — the granularity
that validated better for retrieval than the 800-token default).

Phases (both resume-safe):
  --ingest   re-chunk every doc (per-doc transaction; --only-doc for tests)
  --embed    embed pending chunks via Voyage (app.embed.embed_documents)
  --status   corpus counts

Usage:
  DATABASE_URL=postgresql://perm@127.0.0.1:5433/perm_decisions \
    venv/bin/python scripts/ingest/rechunk_regulations.py --ingest
"""
import argparse, json, logging, os, re, sys
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
from ingest_regulations import SECTION_RE  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("rechunk_regs")

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm@127.0.0.1:5433/perm_decisions")

CHUNK_TOKENS   = 400
OVERLAP_TOKENS = 60


# ── standard project chunker (casebase-ingest convention) ────────────────────
def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def _tail_str(text: str, n_tokens: int) -> str:
    chars = n_tokens * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(" ")
    return (snippet[idx + 1:] if idx > 0 else snippet) + " "

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

def chunk_by_paragraphs(text, target=CHUNK_TOKENS, overlap=OVERLAP_TOKENS):
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
                overlap_tail = _tail_str(" ".join(current_parts), overlap)
                current_parts, current_tokens = [], 0
            for sub in _split_long(para, target):
                if sub.strip():
                    chunks.append((overlap_tail + sub).strip())
                    overlap_tail = _tail_str(sub, overlap)
            continue
        if current_tokens + para_tokens > target and current_parts:
            chunks.append((overlap_tail + " ".join(current_parts)).strip())
            overlap_tail = _tail_str(" ".join(current_parts), overlap)
            current_parts, current_tokens = [], 0
        current_parts.append(para)
        current_tokens += para_tokens
    if current_parts:
        chunks.append((overlap_tail + " ".join(current_parts)).strip())
    return [c for c in chunks if c.strip()]


# ── section-aware splitting ──────────────────────────────────────────────────
def split_by_section(full_text: str, cfr_part):
    """Yield (section_or_None, section_title, body_text) in document order.
    Text before the first section heading is the part preamble (None)."""
    prefix = f"{cfr_part}.".lower() if cfr_part else None
    matches = []
    for m in SECTION_RE.finditer(full_text):
        if prefix and not m.group(1).lower().startswith(prefix):
            continue  # cross-reference at line start; not this part's heading
        matches.append(m)
    if not matches:
        yield None, None, full_text
        return
    if matches[0].start() > 0:
        yield None, None, full_text[:matches[0].start()]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        yield m.group(1), m.group(2).strip(), full_text[m.start():end]


def doc_chunks(doc):
    """Build rag_chunks rows for one regulations_docs row."""
    cfr_title, cfr_part = doc["cfr_title"], doc["cfr_part"]
    label = doc["title"] or f"{cfr_title} CFR Part {cfr_part}"
    rows, idx = [], 0
    for sec, sec_title, body in split_by_section(doc["full_text"] or "",
                                                cfr_part):
        if sec and cfr_title:
            citation = f"{cfr_title} CFR {sec}"
            header = f"{cfr_title} CFR § {sec} — {sec_title}" if sec_title \
                     else f"{cfr_title} CFR § {sec}"
        elif cfr_title and cfr_part:
            citation = f"{cfr_title} CFR {cfr_part}"
            header = label
        else:
            citation, header = None, label
        for text in chunk_by_paragraphs(f"{header}\n\n{body}"):
            rows.append({
                "corpus": "regulation",
                "source_id": str(doc["id"]),
                "source_label": label,
                "source_date": str(doc["as_of_date"]) if doc["as_of_date"] else None,
                "source_outcome": None,
                "chunk_index": idx,
                "chunk_text": text,
                "chunk_tokens": approx_tokens(text),
                "embedding": None,
                "cfr_citation": citation,
                "form_type": None,
            })
            idx += 1
    return rows


UPSERT_SQL = """
    INSERT INTO rag_chunks
      (corpus, source_id, source_label, source_date, source_outcome,
       chunk_index, chunk_text, chunk_tokens, embedding, cfr_citation, form_type)
    VALUES
      (%(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s,
       %(source_outcome)s, %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s,
       %(embedding)s, %(cfr_citation)s, %(form_type)s)
"""


def run_ingest(conn, only_doc=None, limit=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        q = ("SELECT id, title, cfr_title, cfr_part, as_of_date, full_text "
             "FROM regulations_docs ")
        if only_doc:
            q += f"WHERE id = {int(only_doc)} "
        q += "ORDER BY id"
        if limit:
            q += f" LIMIT {int(limit)}"
        cur.execute(q)
        docs = cur.fetchall()
    log.info(f"{len(docs)} docs to re-chunk")
    total = 0
    for n, doc in enumerate(docs, 1):
        rows = doc_chunks(doc)
        with conn.cursor() as cur:
            # per-doc transaction: delete old, insert new — resume-safe
            cur.execute(
                "DELETE FROM rag_chunks WHERE corpus='regulation' "
                "AND source_id=%s", (str(doc["id"]),))
            if rows:
                psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows,
                                              page_size=500)
        conn.commit()
        total += len(rows)
        if n % 200 == 0 or n == len(docs):
            log.info(f"  [{n}/{len(docs)}] {doc['title']}: cumulative "
                     f"{total} chunks")
    log.info(f"Ingest done: {total} chunks")


def run_embed(conn, batch_chunks=25):
    """Embed pending regulation chunks via Voyage (app.embed.embed_documents).
    Resume-safe: only touches embedding IS NULL rows."""
    from embed import embed_documents  # app/embed.py — voyage-4-large
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM rag_chunks "
                    "WHERE corpus='regulation' AND embedding IS NULL")
        pending = cur.fetchone()[0]
    log.info(f"{pending} chunks pending embedding")
    done = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, chunk_text FROM rag_chunks "
                "WHERE corpus='regulation' AND embedding IS NULL "
                "ORDER BY id LIMIT %s", (batch_chunks,))
            batch = cur.fetchall()
        if not batch:
            break
        vecs = embed_documents([t for _, t in batch])
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                "UPDATE rag_chunks SET embedding=%s::vector WHERE id=%s",
                [("[" + ",".join(f"{v:.6f}" for v in vec) + "]", id_)
                 for (id_, _), vec in zip(batch, vecs)],
                page_size=100)
        conn.commit()
        done += len(batch)
        if done % 2500 < batch_chunks:
            log.info(f"  embedded {done}/{pending}")
    log.info(f"Embed done: {done} chunks")


def run_status(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT corpus, COUNT(DISTINCT source_id), COUNT(*),
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL),
                   COUNT(*) FILTER (WHERE embedding IS NULL)
            FROM rag_chunks GROUP BY corpus ORDER BY corpus""")
        rows = cur.fetchall()
    print(f"{'corpus':<18}{'sources':>9}{'chunks':>9}{'embedded':>10}{'pending':>9}")
    for r in rows:
        print(f"{r[0]:<18}{r[1]:>9}{r[2]:>9}{r[3]:>10}{r[4]:>9}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--only-doc", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    conn = psycopg2.connect(DB_URL)
    try:
        if args.ingest:
            run_ingest(conn, only_doc=args.only_doc, limit=args.limit)
        if args.embed:
            run_embed(conn)
        if args.status or not (args.ingest or args.embed):
            run_status(conn)
    finally:
        conn.close()
