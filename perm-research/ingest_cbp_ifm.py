#!/usr/bin/env python3
"""
CBP Inspector's Field Manual (IFM) — PDF Extractor + RAG Ingestion

Reads the CBP IFM PDF, splits by chapter/section, and loads into
rag_chunks (corpus='cbp_ifm').

The IFM is organized as:
  - Pages 1-12: FOIA cover letter + table of contents (skipped)
  - Page 13+:   Chapters with numbered sections (N.M Title)

Each section becomes a document; long sections are chunked at
~800 tokens with 80-token overlap.

Usage:
    python3 ingest_cbp_ifm.py --extract          # parse PDF → JSON
    python3 ingest_cbp_ifm.py --ingest           # JSON → PostgreSQL chunks
    python3 ingest_cbp_ifm.py --extract --ingest # both in one pass
    python3 ingest_cbp_ifm.py --embed            # embed chunks via Ollama
    python3 ingest_cbp_ifm.py --status           # show chunk/embedding counts
    python3 ingest_cbp_ifm.py --reset --ingest   # wipe corpus and re-ingest

Reads:  CBP_IFM_PDF env var  (default: ~/Downloads/CPB-IFM_2006.pdf)
Writes: perm-research/data/cbp_ifm.json
        rag_chunks (corpus='cbp_ifm') in perm_decisions database
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
import pdfplumber
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

DB_URL       = os.environ.get("DATABASE_URL",
               "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
EMBED_DIM    = 1024
CHUNK_TOKENS  = 800
OVERLAP_TOKENS = 80
BATCH_SIZE   = 5
CORPUS       = "cbp_ifm"
DOC_INSTRUCT = ""

DEFAULT_PDF = Path.home() / "Downloads" / "CPB-IFM_2006.pdf"
PDF_PATH    = Path(os.environ.get("CBP_IFM_PDF", str(DEFAULT_PDF)))
OUTPUT_JSON = Path(__file__).resolve().parent / "data" / "cbp_ifm.json"

# Pages 1-12 are FOIA cover + TOC; content starts at page 13 (index 12)
CONTENT_START_PAGE = 12

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Heading detection ─────────────────────────────────────────────────────────

# Chapter header: "Chapter N" or "Chapter N: Title" or "Chapter N. Title"
_CHAPTER_RE = re.compile(
    r"^(?:Chapter\s+(\d+)[.:]\s*(.+)|Chapter\s+(\d+)\s+(.+))$",
    re.IGNORECASE,
)

# Section heading: "N.M Title" or "N.M.P Title" — number followed by text
_SECTION_RE = re.compile(
    r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s+(.+)$"
)

# Page noise to strip: "Page N of M", "Inspector's Field Manual", path breadcrumbs
_NOISE_RE = re.compile(
    r"^(?:Page\s+\d+\s+of\s+\d+|Inspector'?s?\s+Field\s+Manual"
    r"|INSERTS\s+PLUS/.+|rage\s+\d+\s+of\s+\d+)$",
    re.IGNORECASE,
)


def _clean_line(line: str) -> str:
    return line.strip()


def _is_noise(line: str) -> bool:
    return bool(_NOISE_RE.match(line.strip()))


def _is_chapter(line: str) -> re.Match | None:
    return _CHAPTER_RE.match(line.strip())


def _is_section(line: str) -> re.Match | None:
    return _SECTION_RE.match(line.strip())

# ── PDF extraction ────────────────────────────────────────────────────────────

def extract_full_text(pdf_path: Path) -> list[tuple[int, str]]:
    """Return list of (page_number, cleaned_text) for content pages."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        log.info(f"PDF has {total} pages; extracting from page {CONTENT_START_PAGE + 1} onward")
        for i in range(CONTENT_START_PAGE, total):
            raw = pdf.pages[i].extract_text(x_tolerance=2, y_tolerance=2) or ""
            # Clean noise lines
            lines = [l for l in raw.splitlines() if not _is_noise(l)]
            text = "\n".join(lines).strip()
            if text:
                pages.append((i + 1, text))
    return pages


def parse_sections(pages: list[tuple[int, str]]) -> list[dict]:
    """
    Split page text into records by chapter + section heading.
    Each section gets: chapter_num, chapter_title, section_num, section_title, content.
    """
    today = __import__("datetime").date.today().isoformat()
    records: list[dict] = []

    current_chapter_num   = ""
    current_chapter_title = "General"
    current_section_num   = ""
    current_section_title = ""
    current_lines: list[str] = []
    current_page = CONTENT_START_PAGE + 1

    def flush():
        body = "\n".join(current_lines).strip()
        # Collapse excessive blank lines
        body = re.sub(r"\n{3,}", "\n\n", body)
        if not body or len(body) < 40:
            return
        sec_label = (
            f"{current_section_num} {current_section_title}".strip()
            if current_section_num else current_chapter_title
        )
        chap_label = (
            f"Chapter {current_chapter_num}: {current_chapter_title}"
            if current_chapter_num else "Preliminary"
        )
        records.append({
            "form":             "CBP-IFM",
            "classification":   f"{chap_label} — {sec_label}",
            "chapter":          current_chapter_num,
            "chapter_title":    current_chapter_title,
            "section":          current_section_num,
            "section_title":    current_section_title,
            "requirement_type": "field_manual",
            "content":          body,
            "source_file":      PDF_PATH.name,
            "source_url":       "https://www.cbp.gov",
            "scraped_date":     today,
            "page":             current_page,
        })

    for page_num, text in pages:
        for line in text.splitlines():
            line = _clean_line(line)
            if not line:
                current_lines.append("")
                continue

            chap_m = _is_chapter(line)
            sec_m  = _is_section(line)

            if chap_m:
                flush()
                current_lines = []
                current_page  = page_num
                g = chap_m.groups()
                current_chapter_num   = g[0] or g[2]
                current_chapter_title = (g[1] or g[3] or "").strip()
                current_section_num   = ""
                current_section_title = ""

            elif sec_m:
                flush()
                current_lines = []
                current_page  = page_num
                current_section_num   = sec_m.group(1)
                current_section_title = sec_m.group(2).strip()

            else:
                current_lines.append(line)

    flush()
    return records

# ── --extract ─────────────────────────────────────────────────────────────────

def run_extract() -> list[dict]:
    if not PDF_PATH.exists():
        log.error(f"PDF not found: {PDF_PATH}")
        log.error("Set CBP_IFM_PDF env var or place file at default path.")
        sys.exit(1)

    log.info(f"Extracting text from {PDF_PATH.name}…")
    pages = extract_full_text(PDF_PATH)
    log.info(f"Extracted {len(pages)} content pages")

    records = parse_sections(pages)
    log.info(f"Parsed {len(records)} sections")

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    log.info(f"Saved: {OUTPUT_JSON}")

    # Chapter summary
    by_chap: dict[str, int] = {}
    for r in records:
        c = f"Ch.{r['chapter']}" if r['chapter'] else "Preliminary"
        by_chap[c] = by_chap.get(c, 0) + 1
    log.info(f"Chapters: {len(by_chap)}  |  Sections: {len(records)}")

    return records

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


def chunk_by_paragraphs(text: str, target: int = CHUNK_TOKENS,
                        overlap: int = OVERLAP_TOKENS) -> list[str]:
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


def make_source_id(chapter: str, section: str, title: str) -> str:
    raw = f"cbp_ifm_ch{chapter}_sec{section}_{title}" if section else f"cbp_ifm_ch{chapter}_{title}"
    slug = re.sub(r"[^\w]", "_", raw).lower()
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:200]

# ── --ingest ──────────────────────────────────────────────────────────────────

def run_ingest(conn, limit: int | None):
    if not OUTPUT_JSON.exists():
        log.error(f"JSON not found: {OUTPUT_JSON}")
        log.error("Run --extract first.")
        sys.exit(1)

    with open(OUTPUT_JSON, encoding="utf-8") as f:
        records = json.load(f)

    log.info(f"Loaded {len(records)} sections from {OUTPUT_JSON}")
    if limit:
        records = records[:limit]

    total_chunks = 0
    rows: list[dict] = []

    for rec in records:
        classification = rec.get("classification", "")
        content        = rec.get("content", "").strip()
        source_url     = rec.get("source_url", "")
        scraped_date   = rec.get("scraped_date")
        chapter        = rec.get("chapter", "")
        section        = rec.get("section", "")
        section_title  = rec.get("section_title", "")

        if not content:
            continue

        source_id    = make_source_id(chapter, section, section_title or classification[:40])
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
                "form_type":      "CBP-IFM",
            })
        total_chunks += len(chunks)

    if not rows:
        log.warning("No chunks to ingest.")
        return

    upsert_chunks(conn, rows)
    log.info(
        f"Ingest complete — {len(records)} sections, "
        f"{total_chunks} chunks upserted (corpus='{CORPUS}')"
    )

# ── Embedding ─────────────────────────────────────────────────────────────────

def embed_batch(texts: list) -> list:
    """Delegate to app.embed.embed_documents (Voyage API, voyage-4-large)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parents[2] if 'perm-research' in __file__ else _Path(__file__).parents[2]))
    from app.embed import embed_documents
    return embed_documents(list(texts))

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

    done = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i: i + batch_size]
        ids, texts = [r[0] for r in batch], [r[1] for r in batch]
        vecs = embed_batch(texts)
        with conn.cursor() as cur:
            for rid, vec in zip(ids, vecs):
                vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                cur.execute("UPDATE rag_chunks SET embedding = %s::vector WHERE id = %s",
                            (vec_str, rid))
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

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"Ingest CBP Inspector's Field Manual into RAG (corpus='{CORPUS}')"
    )
    parser.add_argument("--extract",    action="store_true",
                        help="Parse PDF and write JSON")
    parser.add_argument("--ingest",     action="store_true",
                        help="Parse JSON and upsert raw chunks")
    parser.add_argument("--embed",      action="store_true",
                        help="Embed chunks missing vectors via Ollama")
    parser.add_argument("--status",     action="store_true",
                        help="Show chunk/embedding counts per corpus")
    parser.add_argument("--reset",      action="store_true",
                        help=f"Delete existing '{CORPUS}' chunks before ingesting")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap number of sections (for testing)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Ollama embedding batch size")
    parser.add_argument("--pdf",        default=None,
                        help=f"Path to IFM PDF (default: {DEFAULT_PDF})")
    args = parser.parse_args()

    if not any([args.extract, args.ingest, args.embed, args.status]):
        parser.print_help()
        sys.exit(0)

    if args.pdf:
        global PDF_PATH
        PDF_PATH = Path(args.pdf)

    if args.extract:
        run_extract()

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
            run_embed(conn, args.batch_size)

        conn.close()


if __name__ == "__main__":
    main()
