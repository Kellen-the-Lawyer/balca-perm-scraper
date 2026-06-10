"""USCIS form evidence checklists."""
import os
import re
import json
import io
from datetime import date as _date
from typing import Any, Optional

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- shared db, config, helpers

router = APIRouter()

@router.get("/api/checklists")
async def list_checklists():
    """All form/classification pairs available in the checklists corpus."""
    rows = await database.fetch_all(q("""
        SELECT DISTINCT ON (source_id)
            source_id    AS id,
            source_label AS label,
            form_type    AS form,
            cfr_citation AS source_url,
            source_date  AS scraped_date
        FROM rag_chunks
        WHERE corpus = 'uscis_checklists'
        ORDER BY source_id, chunk_index
    """))
    return [dict(r) for r in rows]


@router.get("/api/checklists/search")
async def search_checklists(
    query: str = Query(alias="q"),
    form: Optional[str] = Query(default=None, description="Filter by form number (e.g. I-129)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Full-text search across USCIS evidence checklists."""
    offset = (page - 1) * page_size
    q_text = query.strip()
    if not q_text:
        return {"total": 0, "page": page, "page_size": page_size, "results": []}

    form_clause = "AND UPPER(form_type) = UPPER(:form)" if form else ""
    bind: dict = {"q": q_text, "lim": page_size, "off": offset}
    count_bind: dict = {"q": q_text}
    if form:
        bind["form"] = form
        count_bind["form"] = form

    total = await database.fetch_val(
        text(f"""
            SELECT COUNT(DISTINCT source_id) FROM rag_chunks
            WHERE corpus = 'uscis_checklists'
              {form_clause}
              AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
        """).bindparams(**count_bind)
    )

    rows = await database.fetch_all(
        text(f"""
            SELECT DISTINCT ON (source_id)
                source_id    AS id,
                source_label AS label,
                form_type    AS form,
                cfr_citation AS source_url,
                ts_rank(to_tsvector('english', chunk_text),
                        websearch_to_tsquery('english', :q)) AS rank,
                ts_headline('english', chunk_text,
                            websearch_to_tsquery('english', :q),
                            'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline
            FROM rag_chunks
            WHERE corpus = 'uscis_checklists'
              {form_clause}
              AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
            ORDER BY source_id, rank DESC
            LIMIT :lim OFFSET :off
        """).bindparams(**bind)
    )

    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}


@router.get("/api/checklists/{form}")
async def get_checklist(form: str):
    """All classifications for a given form, with full reassembled text."""
    rows = await database.fetch_all(q("""
        SELECT source_id, source_label, chunk_index, chunk_text, cfr_citation AS source_url
        FROM rag_chunks
        WHERE corpus = 'uscis_checklists'
          AND UPPER(form_type) = UPPER(:form)
        ORDER BY source_id, chunk_index
    """, form=form))
    if not rows:
        raise HTTPException(status_code=404, detail=f"No checklist found for form '{form}'")

    # Group chunks back into documents by source_id
    docs: dict[str, dict] = {}
    for r in rows:
        sid = r["source_id"]
        if sid not in docs:
            docs[sid] = {
                "id":          sid,
                "label":       r["source_label"],
                "source_url":  r["source_url"],
                "full_text":   "",
                "chunks":      [],
            }
        docs[sid]["chunks"].append(r["chunk_text"])
    for doc in docs.values():
        doc["full_text"] = "\n\n".join(doc["chunks"])
        del doc["chunks"]

    return {"form": form.upper(), "classifications": list(docs.values())}


# ── Anthropic API proxy ───────────────────────────────────────────────────────
# Keeps the API key server-side; frontend posts to /api/claude instead of
# calling Anthropic directly.

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

