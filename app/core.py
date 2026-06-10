"""
Casebase API — shared core: configuration, database connection, and common helpers.
Extracted from the original monolithic api.py.
"""
import os
import re
import json
import io
from datetime import date as _date
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import httpx
import databases
from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import text

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"
)
PDF_BASE_PATH = os.environ.get(
    "PDF_BASE_PATH", "/Users/Dad/Documents/GitHub/balca-perm-scraper/data/raw/pdfs"
)
GCS_RAW_BUCKET = os.environ.get("GCS_RAW_BUCKET", "").strip()
AAO_BASE_PATH = os.environ.get("AAO_BASE_PATH", "/Users/Dad/aao_decisions")
REGULATIONS_BASE_PATH = os.environ.get(
    "REGULATIONS_BASE_PATH",
    "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/Regulations",
)
FAM_BASE_PATH = os.environ.get(
    "FAM_BASE_PATH",
    "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/FAM",
)
USCIS_POLICY_MANUAL_GCS_OBJECT = os.environ.get(
    "USCIS_POLICY_MANUAL_GCS_OBJECT",
    "policy/uscis-policy-manual/Policy_Manual_USCIS.pdf",
)
GCS_CHUNK_SIZE = 1024 * 1024

database = databases.Database(DATABASE_URL)

def q(sql, **params):
    """Bind params to a SQLAlchemy text() clause."""
    return text(sql).bindparams(**params) if params else text(sql)


async def ensure_operational_schema() -> None:
    """Small additive migrations for operational metadata owned by this API."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS search_events (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            corpus TEXT NOT NULL,
            query TEXT NOT NULL,
            filters JSONB NOT NULL DEFAULT '{}'::jsonb,
            result_count INTEGER NOT NULL DEFAULT 0,
            clicked_result_id INTEGER,
            clicked_corpus TEXT,
            session_key TEXT,
            user_label TEXT,
            source_path TEXT,
            admin_private BOOLEAN NOT NULL DEFAULT TRUE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_search_events_corpus_query ON search_events(corpus, query)",
        "CREATE INDEX IF NOT EXISTS idx_search_events_created_at ON search_events(created_at DESC)",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extraction_error TEXT",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extraction_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extracted_at TIMESTAMPTZ",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extraction_page_count INTEGER",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extraction_char_count INTEGER",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS extraction_quality TEXT",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS citation_quality_status TEXT",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS regulation_quality_status TEXT",
        "ALTER TABLE IF EXISTS decisions ADD COLUMN IF NOT EXISTS search_quality_notes TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extraction_error TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extraction_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extracted_at TIMESTAMPTZ",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extraction_page_count INTEGER",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extraction_char_count INTEGER",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS extraction_quality TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS citation_quality_status TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS regulation_quality_status TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS search_quality_notes TEXT",
        # aao_citations — inter-corpus citation graph for AAO decisions
        """
        CREATE TABLE IF NOT EXISTS aao_citations (
            id                  SERIAL PRIMARY KEY,
            citing_id           INTEGER NOT NULL
                                    REFERENCES aao_decisions(id) ON DELETE CASCADE,
            cited_aao_id        INTEGER REFERENCES aao_decisions(id) ON DELETE SET NULL,
            cited_balca_id      INTEGER REFERENCES decisions(id) ON DELETE SET NULL,
            cited_precedent_id  INTEGER REFERENCES precedent_decisions(id) ON DELETE SET NULL,
            cited_raw           TEXT NOT NULL,
            citation_type       TEXT NOT NULL
                                    CHECK (citation_type IN ('aao','balca','precedent','matter_of')),
            context_snippet     TEXT,
            UNIQUE (citing_id, cited_raw)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_aao_citations_citing ON aao_citations(citing_id)",
        "CREATE INDEX IF NOT EXISTS idx_aao_citations_aao    ON aao_citations(cited_aao_id)",
        "CREATE INDEX IF NOT EXISTS idx_aao_citations_balca  ON aao_citations(cited_balca_id)",
        "CREATE INDEX IF NOT EXISTS idx_aao_citations_prec   ON aao_citations(cited_precedent_id)",
        "CREATE INDEX IF NOT EXISTS idx_aao_citations_type   ON aao_citations(citation_type)",
        # Precedent fields on aao_decisions (added when precedent_decisions were migrated in)
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS is_precedent BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS citation TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS party_name TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS volume INTEGER",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS decision_type TEXT",
        "ALTER TABLE IF EXISTS aao_decisions ADD COLUMN IF NOT EXISTS adopted_num TEXT",
        "CREATE INDEX IF NOT EXISTS idx_aao_decisions_is_precedent ON aao_decisions(is_precedent) WHERE is_precedent = TRUE",
        "CREATE INDEX IF NOT EXISTS idx_aao_decisions_citation ON aao_decisions(citation) WHERE citation IS NOT NULL",
    ]
    for statement in statements:
        await database.execute(text(statement))


def _clean_query(value: str) -> str:
    return " ".join((value or "").split())


def _like(value: str) -> str:
    return f"%{value}%"


def _search_filters(**values) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", False)}


async def log_search_event(
    request: Request,
    *,
    corpus: str,
    query: str,
    filters: dict[str, Any],
    result_count: int,
) -> None:
    query = _clean_query(query)
    if not query:
        return
    try:
        await database.execute(
            text("""
                INSERT INTO search_events (
                    corpus, query, filters, result_count, session_key, user_label, source_path
                ) VALUES (
                    :corpus, :query, CAST(:filters AS jsonb), :result_count,
                    :session_key, :user_label, :source_path
                )
            """).bindparams(
                corpus=corpus,
                query=query,
                filters=json.dumps(filters, sort_keys=True),
                result_count=int(result_count or 0),
                session_key=request.headers.get("x-session-id"),
                user_label=request.headers.get("x-user-label"),
                source_path=str(request.url.path),
            )
        )
    except Exception:
        return


def require_search_analytics_access(request: Request) -> None:
    expected = os.environ.get("SEARCH_ANALYTICS_TOKEN")
    if expected and request.headers.get("x-search-analytics-token") != expected:
        raise HTTPException(status_code=403, detail="Search analytics access denied")


def _text_quality(text_value: str, page_count: int) -> str:
    chars = len(text_value or "")
    if chars == 0:
        return "empty"
    if page_count and chars / page_count < 250:
        return "low_text"
    if chars < 1000:
        return "short"
    return "ok"


def _extract_pdf_text(path: str) -> dict[str, Any]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n\n".join(page for page in pages if page.strip())
    return {
        "full_text": full_text,
        "page_count": len(pages),
        "char_count": len(full_text),
        "quality": _text_quality(full_text, len(pages)),
    }


def _extract_pdf_text_from_bytes(pdf_bytes: bytes) -> dict[str, Any]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n\n".join(page for page in pages if page.strip())
    return {
        "full_text": full_text,
        "page_count": len(pages),
        "char_count": len(full_text),
        "quality": _text_quality(full_text, len(pages)),
    }


def _balca_pdf_path(filename: str | None) -> str | None:
    return os.path.join(PDF_BASE_PATH, filename) if filename else None


def _relative_object_path(path: str | None, base_path: str) -> str | None:
    if not path:
        return None
    value = str(path).replace("\\", "/")
    base = base_path.rstrip("/").replace("\\", "/")
    if value.startswith(f"{base}/"):
        return value[len(base) + 1:]
    return os.path.basename(value)


def _balca_gcs_object(filename: str | None) -> str | None:
    return f"balca/pdfs/{filename}" if filename else None


def _aao_gcs_object(pdf_path: str | None) -> str | None:
    rel = _relative_object_path(pdf_path, AAO_BASE_PATH)
    return f"aao/pdfs/{rel}" if rel else None


def _regulation_gcs_object(pdf_path: str | None) -> str | None:
    rel = _relative_object_path(pdf_path, REGULATIONS_BASE_PATH)
    return f"regulations/pdfs/{rel}" if rel else None


def _policy_gcs_object(pdf_path: str | None, source: str | None) -> str | None:
    if source == "USCIS_PM":
        return USCIS_POLICY_MANUAL_GCS_OBJECT
    rel = _relative_object_path(pdf_path, FAM_BASE_PATH)
    return f"policy/fam/{rel}" if rel else None


def _gcs_blob(object_name: str):
    if not GCS_RAW_BUCKET:
        return None
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="GCS document storage is not available; install google-cloud-storage.",
        ) from exc
    return storage.Client().bucket(GCS_RAW_BUCKET).blob(object_name)


def _iter_gcs_blob(blob):
    with blob.open("rb") as handle:
        while True:
            chunk = handle.read(GCS_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


def _download_gcs_bytes(object_name: str) -> bytes:
    blob = _gcs_blob(object_name)
    if not blob or not blob.exists():
        raise FileNotFoundError(f"GCS object not found: {object_name}")
    return blob.download_as_bytes()


def _serve_pdf_source(
    *,
    local_path: str | None,
    gcs_object: str | None,
    filename: str | None = None,
):
    if local_path and os.path.exists(local_path):
        return FileResponse(
            local_path,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=\"{filename or os.path.basename(local_path)}\""},
        )
    if gcs_object:
        blob = _gcs_blob(gcs_object)
        if blob and blob.exists():
            return StreamingResponse(
                _iter_gcs_blob(blob),
                media_type="application/pdf",
                headers={"Content-Disposition": f"inline; filename=\"{filename or os.path.basename(gcs_object)}\""},
            )
    raise HTTPException(status_code=404, detail="PDF not found")


def _extract_pdf_text_source(local_path: str | None, gcs_object: str | None) -> dict[str, Any]:
    if local_path and os.path.exists(local_path):
        return _extract_pdf_text(local_path)
    if gcs_object:
        return _extract_pdf_text_from_bytes(_download_gcs_bytes(gcs_object))
    raise FileNotFoundError(f"PDF not found: {local_path or gcs_object or 'missing path'}")

# ── Search ────────────────────────────────────────────────────────────────────


import json as _json

OLLAMA_URL        = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL      = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:latest")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "mistral:7b-instruct")
EMBED_DIM      = 1024  # MRL truncation to stay under pgvector's 2000-dim index limit
QUERY_INSTRUCT = "Instruct: Given a legal research query, retrieve relevant passages that answer the query\nQuery: "

async def embed_query(text: str) -> list:
    """Embed a single query via local Ollama, truncated to EMBED_DIM."""
    payload = _json.dumps({
        "model": OLLAMA_MODEL,
        "input": [QUERY_INSTRUCT + text.strip()[:32000]],
        "options": {"num_ctx": 32768},
    }).encode()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/embed",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    return data["embeddings"][0][:EMBED_DIM]

CORPUS_LABELS = {
    "balca":      "BALCA Decision",
    "aao":        "AAO Decision",
    "regulation": "Federal Regulation",
    "policy":     "USCIS/FAM Policy",
}


__all__ = [
    "AAO_BASE_PATH",
    "CORPUS_LABELS",
    "DATABASE_URL",
    "EMBED_DIM",
    "FAM_BASE_PATH",
    "GCS_CHUNK_SIZE",
    "GCS_RAW_BUCKET",
    "OLLAMA_CHAT_MODEL",
    "OLLAMA_MODEL",
    "OLLAMA_URL",
    "PDF_BASE_PATH",
    "QUERY_INSTRUCT",
    "REGULATIONS_BASE_PATH",
    "USCIS_POLICY_MANUAL_GCS_OBJECT",
    "_aao_gcs_object",
    "_balca_gcs_object",
    "_balca_pdf_path",
    "_clean_query",
    "_download_gcs_bytes",
    "_extract_pdf_text",
    "_extract_pdf_text_from_bytes",
    "_extract_pdf_text_source",
    "_gcs_blob",
    "_iter_gcs_blob",
    "_json",
    "_like",
    "_policy_gcs_object",
    "_regulation_gcs_object",
    "_relative_object_path",
    "_search_filters",
    "_serve_pdf_source",
    "_text_quality",
    "database",
    "embed_query",
    "ensure_operational_schema",
    "httpx",
    "log_search_event",
    "q",
    "require_search_analytics_access",
    "text",
]
