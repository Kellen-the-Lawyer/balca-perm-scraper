#!/usr/bin/env python3
"""
Federal Register Final Rules — PDF Extractor + RAG Ingestion

Reads Federal Register final rule PDFs, strips page headers, and loads
chunked text into rag_chunks (corpus='final_rules').

Documents are split into major sections where detectable (Roman numeral
headings, lettered sections) and chunked at ~800 tokens with 80-token
overlap. Each PDF is a separate source; sections become source_id variants.

Usage:
    python3 ingest_final_rules.py --extract          # parse PDFs → JSON
    python3 ingest_final_rules.py --ingest           # JSON → PostgreSQL chunks
    python3 ingest_final_rules.py --extract --ingest # both in one pass
    python3 ingest_final_rules.py --embed            # embed chunks via Ollama
    python3 ingest_final_rules.py --status           # show chunk/embedding counts
    python3 ingest_final_rules.py --reset --ingest   # wipe corpus and re-ingest
    python3 ingest_final_rules.py --list             # list configured PDFs

Reads:  FINAL_RULES_DIR env var  (default: ~/Downloads)
Writes: perm-research/data/final_rules.json
        rag_chunks (corpus='final_rules') in perm_decisions database
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
CORPUS       = "final_rules"
DOC_INSTRUCT = ""

PDF_DIR     = Path(os.environ.get("FINAL_RULES_DIR", str(Path.home() / "Downloads")))
OUTPUT_JSON = Path(__file__).resolve().parent / "data" / "final_rules.json"

# Each tuple: (filename, short_title, form_type)
RULE_CATALOG: list[tuple[str, str, str]] = [
    (
        "PERM Regulations.pdf",
        "PERM Final Rule (20 CFR 656) — 69 FR 77326 (Dec. 27, 2004)",
        "20 CFR 656",
    ),
    (
        "AC21 Regulation.pdf",
        "AC21 Final Rule (8 CFR 204/214/245) — 81 FR 82398 (Nov. 18, 2016)",
        "8 CFR 214",
    ),
    (
        "Weighted Selection Process .pdf",
        "H-1B Weighted Selection Process Final Rule (8 CFR 214) — 90 FR 60864 (Dec. 29, 2025)",
        "8 CFR 214",
    ),
    (
        "Improving the H-1B Registration Selection Process and Program Integrity.pdf",
        "H-1B Registration Selection & Program Integrity Final Rule (8 CFR 214) — 89 FR 7456 (Feb. 2, 2024)",
        "8 CFR 214",
    ),
    (
        "H-1B Modernization Rule.pdf",
        "H-1B Modernization Final Rule (8 CFR 214) — 89 FR 103054 (Dec. 18, 2024)",
        "8 CFR 214",
    ),
    (
        "Enhancing Opportunities for H-1B1, CW-1, and E-3 Nonimmigrants and EB-1 Immigrants.pdf",
        "H-1B1/CW-1/E-3/EB-1 Enhancement Final Rule (8 CFR 204/214/248) — 81 FR 2068 (Jan. 15, 2016)",
        "8 CFR 214",
    ),
    (
        "FMJ Update Final Rule.pdf",
        "F/M/J Nonimmigrant Update Final Rule (8 CFR 214) — 89 FR 22903 (Apr. 3, 2024)",
        "8 CFR 214",
    ),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Page noise patterns ───────────────────────────────────────────────────────

# Federal Register page headers and footers to strip
_FR_HEADER_RE = re.compile(
    r"^(?:\d{4,6}\s+)?Federal\s+Register\s*/\s*Vol\.\s*\d+.*Rules\s+and\s+Regulations.*$"
    r"|^Federal\s+Register\s*/\s*Vol\.\s*\d+.*$"
    r"|^Rules\s+and\s+Regulations\s+\d+$",
    re.IGNORECASE,
)


def _is_noise(line: str) -> bool:
    return bool(_FR_HEADER_RE.match(line.strip()))

# ── Section detection ─────────────────────────────────────────────────────────

# Roman numeral major sections: "I. Background", "II. Discussion of Comments"
_ROMAN_RE = re.compile(
    r"^((?:I{1,3}|IV|V[I]{0,3}|IX|X[I]{0,3}|XIV|XV[I]{0,3}|XIX|XX[I]{0,3})\.\s+.{3,80})$"
)
# Lettered subsections: "A. Summary", "B. Legal Authority"
_LETTER_SECTION_RE = re.compile(r"^([A-Z]\.\s+.{3,80})$")


def _is_section_heading(line: str) -> bool:
    s = line.strip()
    return bool(_ROMAN_RE.match(s)) or bool(_LETTER_SECTION_RE.match(s))

# ── PDF extraction ────────────────────────────────────────────────────────────

def extract_document(pdf_path: Path, title: str) -> list[dict]:
    """
    Extract text from a Federal Register PDF, split into sections,
    return list of section records.
    """
    today = __import__("datetime").date.today().isoformat()

    with pdfplumber.open(pdf_path) as pdf:
        full_lines: list[str] = []
        for page in pdf.pages:
            raw = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            for line in raw.splitlines():
                if not _is_noise(line):
                    full_lines.append(line)

    # Collapse into text, clean up
    full_text = "\n".join(full_lines)
    full_text = re.sub(r"[ \t]+", " ", full_text)
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    # Split into sections by Roman numeral or lettered headings
    sections: list[tuple[str, str]] = []
    current_heading = "Preamble"
    current_buf: list[str] = []

    for line in full_text.splitlines():
        if _is_section_heading(line):
            body = "\n".join(current_buf).strip()
            body = re.sub(r"\n{3,}", "\n\n", body)
            if body and len(body) > 80:
                sections.append((current_heading, body))
            current_heading = line.strip()
            current_buf = []
        else:
            current_buf.append(line)

    # Final section
    body = "\n".join(current_buf).strip()
    if body and len(body) > 80:
        sections.append((current_heading, body))

    if not sections:
        # Fallback: whole document as one section
        sections = [("Full Text", full_text.strip())]

    records = []
    for sec_title, content in sections:
        records.append({
            "title":        title,
            "section":      sec_title,
            "content":      content,
            "source_file":  pdf_path.name,
            "source_url":   f"https://www.federalregister.gov",
            "scraped_date": today,
        })

    return records

# ── --extract ─────────────────────────────────────────────────────────────────

def run_extract() -> list[dict]:
    all_records: list[dict] = []

    for filename, title, form_type in RULE_CATALOG:
        path = PDF_DIR / filename
        if not path.exists():
            log.warning(f"  Not found — skipping: {filename}")
            continue

        log.info(f"\nExtracting: {filename}")
        records = extract_document(path, title)
        for r in records:
            r["form_type"] = form_type
        log.info(f"  → {len(records)} section(s)")
        all_records.extend(records)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    log.info(f"\nTotal: {len(all_records)} sections from {len(RULE_CATALOG)} rules")
    log.info(f"Saved: {OUTPUT_JSON}")
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


def make_source_id(title: str, section: str) -> str:
    raw = f"{title}__{section}"
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
        title       = rec.get("title", "")
        section     = rec.get("section", "")
        content     = rec.get("content", "").strip()
        source_url  = rec.get("source_url", "")
        scraped_date = rec.get("scraped_date")
        form_type   = rec.get("form_type", "")

        if not content:
            continue

        source_id    = make_source_id(title, section)
        source_label = f"{title} — {section}" if section != "Full Text" else title

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
                "cfr_citation":   title,
                "form_type":      form_type,
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

    by_rule: dict[str, int] = {}
    for r in rows:
        key = r["cfr_citation"][:60]
        by_rule[key] = by_rule.get(key, 0) + 1
    for rule, count in sorted(by_rule.items()):
        log.info(f"  {rule}: {count} chunk(s)")

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

# ── --list ────────────────────────────────────────────────────────────────────

def run_list():
    print(f"\nConfigured rules ({PDF_DIR}):\n")
    for filename, title, form_type in RULE_CATALOG:
        path = PDF_DIR / filename
        status = "✓" if path.exists() else "✗ NOT FOUND"
        print(f"  [{status}] {filename}")
        print(f"         {title}")
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"Ingest Federal Register final rules into RAG (corpus='{CORPUS}')"
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
                        help="List configured PDFs and their availability")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap number of sections (for testing)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Ollama embedding batch size")
    args = parser.parse_args()

    if not any([args.extract, args.ingest, args.embed, args.status, args.list]):
        parser.print_help()
        sys.exit(0)

    if args.list:
        run_list()

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
