#!/usr/bin/env python3
"""
ingest_govinfo.py - Ingest GovInfo bulk/package downloads into Casebase.

Apply the schema first:
    psql "$DATABASE_URL" -f schema/govinfo_schema.sql

Usage:
    venv/bin/python3 scripts/ingest/ingest_govinfo.py --ingest
    venv/bin/python3 scripts/ingest/ingest_govinfo.py --ingest --collection FR --limit 10
    venv/bin/python3 scripts/ingest/ingest_govinfo.py --embed
    venv/bin/python3 scripts/ingest/ingest_govinfo.py --status

Environment:
    DATABASE_URL      PostgreSQL connection string.
    GOVINFO_OUT_DIR   Default: ~/casebase_govinfo
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
GOVINFO_OUT_DIR = Path(os.environ.get("GOVINFO_OUT_DIR", Path.home() / "casebase_govinfo"))
CORPUS = "govinfo"
CHUNK_TOKENS = 800
OVERLAP_TOKENS = 80

COLLECTION_LABELS = {
    "BILLS": "Congressional Bills",
    "BILLSTATUS": "Bill Status",
    "PLAW": "Public and Private Laws",
    "STATUTE": "Statutes at Large",
    "FR": "Federal Register",
    "USCODE": "United States Code",
    "CREC": "Congressional Record",
    "CRPT": "Congressional Reports",
    "CHRG": "Congressional Hearings",
    "CPRT": "Congressional Prints",
    "CDOC": "Congressional Documents",
    "CDIR": "Congressional Directory",
    "BUDGET": "Budget of the United States Government",
    "ECONI": "Economic Indicators",
    "ERP": "Economic Report of the President",
    "GOVMAN": "United States Government Manual",
    "PPP": "Public Papers of the Presidents",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _tail_str(text: str, n_tokens: int) -> str:
    chars = n_tokens * 4
    if len(text) <= chars:
        return text + " "
    snippet = text[-chars:]
    idx = snippet.find(" ")
    return (snippet[idx + 1:] if idx > 0 else snippet) + " "


def _split_long(text: str, target: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for sentence in sentences:
        tokens = approx_tokens(sentence)
        if buf_tokens + tokens > target and buf:
            parts.append(" ".join(buf))
            buf = []
            buf_tokens = 0
        buf.append(sentence)
        buf_tokens += tokens
    if buf:
        parts.append(" ".join(buf))
    return parts


def chunk_by_paragraphs(text: str, target: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    if not text or not text.strip():
        return []
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    overlap_tail = ""

    for para in paragraphs:
        para_tokens = approx_tokens(para)
        if para_tokens > target * 1.5:
            if current_parts:
                current = " ".join(current_parts)
                chunks.append((overlap_tail + current).strip())
                overlap_tail = _tail_str(current, overlap)
                current_parts = []
                current_tokens = 0
            for sub in _split_long(para, target):
                chunks.append((overlap_tail + sub).strip())
                overlap_tail = _tail_str(sub, overlap)
            continue
        if current_tokens + para_tokens > target and current_parts:
            current = " ".join(current_parts)
            chunks.append((overlap_tail + current).strip())
            overlap_tail = _tail_str(current, overlap)
            current_parts = []
            current_tokens = 0
        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        chunks.append((overlap_tail + " ".join(current_parts)).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def xml_to_text_and_metadata(raw: str) -> tuple[str, dict]:
    try:
        root = ET.fromstring(raw.encode("utf-8", errors="replace"))
    except ET.ParseError:
        return fallback_strip_tags(raw), {}

    metadata: dict[str, str] = {}
    lines: list[str] = []

    for elem in root.iter():
        tag = strip_ns(elem.tag)
        text = " ".join("".join(elem.itertext()).split())
        if not text:
            continue
        if tag in {"title", "dc:title"} and "title" not in metadata:
            metadata["title"] = text
        elif tag in {"date", "dc:date"} and "date" not in metadata:
            metadata["date"] = text
        elif tag in {"publisher", "dc:publisher"} and "publisher" not in metadata:
            metadata["publisher"] = text

        if tag in {
            "title",
            "official-title",
            "short-title",
            "header",
            "text",
            "p",
            "fp",
            "summary",
            "action",
            "agency",
            "subject",
            "toc-entry",
        }:
            lines.append(text)

    if not lines:
        lines = [" ".join(" ".join(root.itertext()).split())]
    clean_lines = [line if isinstance(line, str) else " ".join(line) for line in lines]
    return normalize_text("\n\n".join(clean_lines)), metadata


def fallback_strip_tags(raw: str) -> str:
    parser = TextHTMLParser()
    try:
        parser.feed(raw)
        text = parser.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    return normalize_text(text)


def normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_date(value: str | None):
    if not value:
        return None
    value = value.strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def load_manifest(path: Path) -> dict:
    manifest = path.parent / "manifest.json"
    if not manifest.exists():
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_package_id(package_id: str) -> dict:
    collection = package_id.split("-", 1)[0].upper()
    meta: dict[str, object] = {"collection": collection}

    bill = re.match(r"^BILLS-(\d+)([a-z]+)(\d+)([a-z0-9]+)$", package_id, re.I)
    if bill:
        meta.update({
            "congress": int(bill.group(1)),
            "doc_class": bill.group(2).lower(),
            "doc_number": bill.group(3),
            "doc_version": bill.group(4).lower(),
        })
        return meta

    bill_status = re.match(r"^BILLSTATUS-(\d+)([a-z]+)(\d+)$", package_id, re.I)
    if bill_status:
        meta.update({
            "congress": int(bill_status.group(1)),
            "doc_class": bill_status.group(2).lower(),
            "doc_number": bill_status.group(3),
        })
        return meta

    public_law = re.match(r"^PLAW-(\d+)(publ|priv)(\d+)$", package_id, re.I)
    if public_law:
        meta.update({
            "congress": int(public_law.group(1)),
            "doc_class": public_law.group(2).lower(),
            "doc_number": public_law.group(3),
        })
        return meta

    fr = re.match(r"^FR-(\d{4}-\d{2}-\d{2})$", package_id, re.I)
    if fr:
        meta["date_issued"] = parse_date(fr.group(1))
        return meta

    uscode = re.match(r"^USCODE-(\d{4})-title(\d+)", package_id, re.I)
    if uscode:
        meta.update({
            "doc_class": "title",
            "doc_number": uscode.group(2),
            "date_issued": parse_date(f"{uscode.group(1)}-01-01"),
        })
        return meta

    return meta


def extract_sections(text: str) -> list[dict]:
    patterns = [
        re.compile(r"(?im)^\s*Sec\.\s+([0-9A-Za-z.-]+)\.?\s+(.+)$"),
        re.compile(r"(?im)^\s*Section\s+([0-9A-Za-z.-]+)\.?\s+(.+)$"),
        re.compile(r"(?im)^\s*§\s*([0-9A-Za-z.-]+)\s+(.+)$"),
    ]
    seen: set[str] = set()
    sections: list[dict] = []
    for pattern in patterns:
        for match in pattern.finditer(text[:120_000]):
            sec = match.group(1).strip()
            if sec in seen:
                continue
            seen.add(sec)
            sections.append({"section": sec, "title": match.group(2).strip()[:160]})
            if len(sections) >= 400:
                return sections
    return sections


def read_doc(path: Path) -> dict | None:
    package_id = path.stem
    manifest = load_manifest(path)
    parsed = parse_package_id(package_id)
    collection = str(parsed.get("collection") or manifest.get("collection") or package_id.split("-", 1)[0]).upper()

    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".xml", ".mods"}:
        full_text, xml_meta = xml_to_text_and_metadata(raw)
    elif path.suffix.lower() in {".html", ".htm"}:
        full_text, xml_meta = fallback_strip_tags(raw), {}
    else:
        full_text, xml_meta = normalize_text(raw), {}

    if len(full_text) < 50:
        log.warning("too little text: %s", path)
        return None

    api_meta = manifest.get("api_metadata") or {}
    title = (
        xml_meta.get("title")
        or api_meta.get("title")
        or api_meta.get("packageTitle")
        or package_id
    )
    date_issued = (
        parse_date(xml_meta.get("date"))
        or parse_date(api_meta.get("dateIssued"))
        or parse_date(api_meta.get("lastModified"))
        or parsed.get("date_issued")
    )

    metadata = {
        "api_metadata": api_meta,
        "xml_metadata": xml_meta,
        "manifest": manifest,
    }

    return {
        "package_id": package_id,
        "collection": collection,
        "collection_label": COLLECTION_LABELS.get(collection, collection),
        "title": title[:1000],
        "date_issued": date_issued,
        "congress": parsed.get("congress"),
        "doc_class": parsed.get("doc_class"),
        "doc_number": parsed.get("doc_number"),
        "doc_version": parsed.get("doc_version"),
        "publisher": xml_meta.get("publisher") or api_meta.get("publisher"),
        "source_url": manifest.get("source_url"),
        "file_path": str(path),
        "file_format": path.suffix.lower().lstrip("."),
        "page_count": max(1, len(full_text) // 3000),
        "full_text": full_text,
        "sections": extract_sections(full_text),
        "metadata": metadata,
    }


def iter_source_files(root: Path, collection: str | None) -> list[Path]:
    if collection:
        bases = [root / collection.upper()]
    else:
        bases = [root]
    files: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        for suffix in ("*.xml", "*.txt", "*.htm", "*.html"):
            files.extend(base.rglob(suffix))
    return sorted(files)


def ensure_corpus_allowed(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'rag_chunks_corpus_check'
        """)
        row = cur.fetchone()
        if row and CORPUS in row[0]:
            return
        existing = re.findall(r"'([^']+)'::text", row[0]) if row else [
            "balca", "aao", "regulation", "policy",
        ]
        if CORPUS not in existing:
            existing.append(CORPUS)
        values = ", ".join(f"'{value}'" for value in existing)
        cur.execute("ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_corpus_check")
        cur.execute(f"""
            ALTER TABLE rag_chunks ADD CONSTRAINT rag_chunks_corpus_check
            CHECK (corpus = ANY (ARRAY[{values}]))
        """)
    conn.commit()


UPSERT_DOC_SQL = """
    INSERT INTO govinfo_docs (
        package_id, collection, collection_label, title, date_issued,
        congress, doc_class, doc_number, doc_version, publisher, source_url,
        file_path, file_format, page_count, full_text, sections, metadata
    ) VALUES (
        %(package_id)s, %(collection)s, %(collection_label)s, %(title)s, %(date_issued)s,
        %(congress)s, %(doc_class)s, %(doc_number)s, %(doc_version)s, %(publisher)s, %(source_url)s,
        %(file_path)s, %(file_format)s, %(page_count)s, %(full_text)s,
        %(sections)s::jsonb, %(metadata)s::jsonb
    )
    ON CONFLICT (package_id) DO UPDATE SET
        collection = EXCLUDED.collection,
        collection_label = EXCLUDED.collection_label,
        title = EXCLUDED.title,
        date_issued = EXCLUDED.date_issued,
        congress = EXCLUDED.congress,
        doc_class = EXCLUDED.doc_class,
        doc_number = EXCLUDED.doc_number,
        doc_version = EXCLUDED.doc_version,
        publisher = EXCLUDED.publisher,
        source_url = EXCLUDED.source_url,
        file_path = EXCLUDED.file_path,
        file_format = EXCLUDED.file_format,
        page_count = EXCLUDED.page_count,
        full_text = EXCLUDED.full_text,
        sections = EXCLUDED.sections,
        metadata = EXCLUDED.metadata,
        ingested_at = NOW()
    RETURNING id
"""

UPSERT_CHUNK_SQL = """
    INSERT INTO rag_chunks (
        corpus, source_id, source_label, source_date, source_outcome,
        chunk_index, chunk_text, chunk_tokens, embedding, cfr_citation, form_type
    ) VALUES (
        %(corpus)s, %(source_id)s, %(source_label)s, %(source_date)s, %(source_outcome)s,
        %(chunk_index)s, %(chunk_text)s, %(chunk_tokens)s, NULL, %(cfr_citation)s, %(form_type)s
    )
    ON CONFLICT (corpus, source_id, chunk_index) DO UPDATE SET
        source_label = EXCLUDED.source_label,
        source_date = EXCLUDED.source_date,
        source_outcome = EXCLUDED.source_outcome,
        chunk_text = EXCLUDED.chunk_text,
        chunk_tokens = EXCLUDED.chunk_tokens,
        cfr_citation = EXCLUDED.cfr_citation,
        form_type = EXCLUDED.form_type,
        embedding = NULL,
        ingested_at = NOW()
"""


def upsert_doc(conn, doc: dict) -> int:
    payload = dict(doc)
    payload["sections"] = json.dumps(doc["sections"])
    payload["metadata"] = json.dumps(doc["metadata"], default=str)
    with conn.cursor() as cur:
        cur.execute(UPSERT_DOC_SQL, payload)
        return cur.fetchone()[0]


def upsert_chunks(conn, doc: dict, chunks: list[str]) -> int:
    rows = []
    for index, text in enumerate(chunks):
        rows.append({
            "corpus": CORPUS,
            "source_id": doc["package_id"],
            "source_label": doc["title"] or doc["package_id"],
            "source_date": doc["date_issued"].isoformat() if doc.get("date_issued") else None,
            "source_outcome": doc["collection_label"],
            "chunk_index": index,
            "chunk_text": text,
            "chunk_tokens": approx_tokens(text),
            "cfr_citation": doc["package_id"],
            "form_type": doc.get("doc_class"),
        })
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_CHUNK_SQL, rows, page_size=200)
    return len(rows)


def run_ingest(conn, source_dir: Path, collection: str | None, reset: bool, limit: int | None) -> None:
    ensure_corpus_allowed(conn)
    files = iter_source_files(source_dir, collection)
    if limit:
        files = files[:limit]
    log.info("found %s govinfo files under %s", len(files), source_dir)

    if reset:
        with conn.cursor() as cur:
            if collection:
                cur.execute("DELETE FROM rag_chunks WHERE corpus = %s AND source_id IN (SELECT package_id FROM govinfo_docs WHERE collection = %s)",
                            (CORPUS, collection.upper()))
                cur.execute("DELETE FROM govinfo_docs WHERE collection = %s", (collection.upper(),))
            else:
                cur.execute("DELETE FROM rag_chunks WHERE corpus = %s", (CORPUS,))
                cur.execute("DELETE FROM govinfo_docs")
        conn.commit()
        log.info("reset complete")

    ok = skipped = errors = chunks_total = 0
    for path in files:
        try:
            doc = read_doc(path)
            if not doc:
                skipped += 1
                continue
            upsert_doc(conn, doc)
            chunks = chunk_by_paragraphs(doc["full_text"])
            chunks_total += upsert_chunks(conn, doc, chunks)
            conn.commit()
            ok += 1
            log.info("ingested %s (%s chars, %s chunks)", doc["package_id"], len(doc["full_text"]), len(chunks))
        except Exception as exc:
            conn.rollback()
            errors += 1
            log.error("%s failed: %s", path, exc)

    log.info("ingest done: %s ok, %s skipped, %s errors, %s chunks", ok, skipped, errors, chunks_total)


def embed_texts(texts: list[str]) -> list[list[float]]:
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from app.embed import embed_documents
    return embed_documents(texts)


def rebuild_hnsw_index(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        count = cur.fetchone()[0]
    if count < 10:
        return
    log.info("rebuilding HNSW index (%s vectors)", f"{count:,}")
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS idx_rag_embedding")
        cur.execute("""
            CREATE INDEX idx_rag_embedding
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
    conn.commit()


def run_embed(conn, batch_size: int, collection: str | None, limit: int | None) -> None:
    sql = """
        SELECT rc.id, rc.chunk_text
        FROM rag_chunks rc
        JOIN govinfo_docs gd ON gd.package_id = rc.source_id
        WHERE rc.corpus = %s AND rc.embedding IS NULL
    """
    params: list[object] = [CORPUS]
    if collection:
        sql += " AND gd.collection = %s"
        params.append(collection.upper())
    sql += " ORDER BY rc.id"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        log.info("no govinfo chunks pending embedding")
        return

    log.info("%s govinfo chunks pending embedding", f"{len(rows):,}")
    done = errors = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        ids = [row[0] for row in batch]
        texts = [row[1] for row in batch]
        try:
            vectors = embed_texts(texts)
            with conn.cursor() as cur:
                for chunk_id, vector in zip(ids, vectors):
                    cur.execute("UPDATE rag_chunks SET embedding = %s WHERE id = %s", (vector, chunk_id))
            conn.commit()
            done += len(batch)
            if done % 500 == 0 or done == len(rows):
                log.info("embedded %s/%s", f"{done:,}", f"{len(rows):,}")
        except Exception as exc:
            conn.rollback()
            errors += len(batch)
            log.error("embedding batch at %s failed: %s", offset, exc)
            time.sleep(5)
    log.info("embedding done: %s ok, %s errors", done, errors)
    rebuild_hnsw_index(conn)


def run_status(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT collection, collection_label, COUNT(*) docs,
                   COALESCE(SUM(length(full_text)), 0) chars
            FROM govinfo_docs
            GROUP BY collection, collection_label
            ORDER BY collection
        """)
        docs = cur.fetchall()
        cur.execute("""
            SELECT gd.collection,
                   COUNT(*) chunks,
                   COUNT(*) FILTER (WHERE rc.embedding IS NOT NULL) embedded,
                   COUNT(*) FILTER (WHERE rc.embedding IS NULL) pending
            FROM rag_chunks rc
            JOIN govinfo_docs gd ON gd.package_id = rc.source_id
            WHERE rc.corpus = 'govinfo'
            GROUP BY gd.collection
            ORDER BY gd.collection
        """)
        chunk_map = {row[0]: row for row in cur.fetchall()}

    print(f"\n{'Collection':<12} {'Docs':>8} {'Chars(M)':>10} {'Chunks':>9} {'Embedded':>9} {'Pending':>9}  Label")
    print("-" * 88)
    for collection, label, doc_count, chars in docs:
        chunks = chunk_map.get(collection, (collection, 0, 0, 0))
        print(
            f"{collection:<12} {doc_count:>8,} {chars / 1e6:>10.1f} "
            f"{chunks[1]:>9,} {chunks[2]:>9,} {chunks[3]:>9,}  {label or ''}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest GovInfo downloads into Casebase")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--source-dir", type=Path, default=GOVINFO_OUT_DIR)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--db-url", default=DB_URL)
    args = parser.parse_args()

    if not any([args.ingest, args.embed, args.status]):
        parser.print_help()
        sys.exit(0)
    if args.reset and not args.ingest:
        parser.error("--reset only applies with --ingest")

    conn = psycopg2.connect(args.db_url)
    conn.autocommit = False
    try:
        if args.ingest:
            run_ingest(conn, args.source_dir, args.collection, args.reset, args.limit)
        if args.embed:
            run_embed(conn, args.batch_size, args.collection, args.limit)
        if args.status:
            run_status(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
