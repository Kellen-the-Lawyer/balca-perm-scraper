"""INA sections: browse and search."""
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

@router.get("/api/ina/sections")
async def list_ina_sections():
    """All INA sections (one row per section) from rag_chunks metadata."""
    rows = await database.fetch_all(q("""
        SELECT DISTINCT ON (source_id)
            source_id       AS section,
            source_label    AS title,
            cfr_citation    AS usc_citation
        FROM rag_chunks
        WHERE corpus = 'ina'
        ORDER BY source_id, chunk_index
    """))
    return [dict(r) for r in rows]


@router.get("/api/ina/sections/{section_id}")
async def get_ina_section(section_id: str):
    """Full text of a single INA section, reassembled from its chunks."""
    rows = await database.fetch_all(q("""
        SELECT chunk_index, chunk_text, source_label, cfr_citation
        FROM rag_chunks
        WHERE corpus = 'ina' AND source_id = :sid
        ORDER BY chunk_index
    """, sid=section_id))
    if not rows:
        raise HTTPException(status_code=404, detail=f"INA § {section_id} not found")
    return {
        "section":      section_id,
        "title":        rows[0]["source_label"],
        "usc_citation": rows[0]["cfr_citation"],
        "full_text":    "\n\n".join(r["chunk_text"] for r in rows),
        "chunk_count":  len(rows),
    }


@router.get("/api/ina/search")
async def search_ina(
    query: str = Query(alias="q"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Full-text search across INA section text."""
    offset = (page - 1) * page_size
    if not query.strip():
        return {"total": 0, "page": page, "page_size": page_size, "results": []}

    total = await database.fetch_val(text("""
        SELECT COUNT(DISTINCT source_id) FROM rag_chunks
        WHERE corpus = 'ina'
          AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
    """).bindparams(q=query.strip()))

    rows = await database.fetch_all(text("""
        SELECT DISTINCT ON (source_id)
            source_id    AS section,
            source_label AS title,
            cfr_citation AS usc_citation,
            ts_rank(to_tsvector('english', chunk_text),
                    websearch_to_tsquery('english', :q)) AS rank,
            ts_headline('english', chunk_text,
                        websearch_to_tsquery('english', :q),
                        'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline
        FROM rag_chunks
        WHERE corpus = 'ina'
          AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
        ORDER BY source_id, rank DESC
        LIMIT :lim OFFSET :off
    """).bindparams(q=query.strip(), lim=page_size, off=offset))

    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}


# ── USCIS Evidence Checklists ────────────────────────────────────────────────

