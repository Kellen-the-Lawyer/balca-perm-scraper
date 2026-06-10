"""CFR regulation documents: list, search, detail, PDFs."""
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

@router.get("/api/regulations-docs")
async def list_regulations_docs():
    rows = await database.fetch_all(q("""
        SELECT id, title, cfr_title, cfr_part, part_name, agency,
               as_of_date::text, page_count,
               jsonb_array_length(sections) AS section_count
        FROM regulations_docs
        ORDER BY cfr_title NULLS LAST, cfr_part"""))
    return [dict(r) for r in rows]


@router.get("/api/regulations-docs/search")
async def search_regulations(
    query: str = Query(default="", alias="q"),
    agency: Optional[str] = Query(default=None),
    cfr_title: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {}

    if query.strip():
        conditions.append("d.search_vector @@ websearch_to_tsquery('english', :qtext)")
        bind["qtext"] = query.strip()
    if agency:
        conditions.append("d.agency ILIKE :agency")
        bind["agency"] = f"%{agency}%"
    if cfr_title:
        conditions.append("d.cfr_title = :cfr_title")
        bind["cfr_title"] = cfr_title

    where = " AND ".join(conditions)
    order = ("ts_rank(d.search_vector, websearch_to_tsquery('english', :qtext)) DESC"
             if query.strip() else "d.cfr_title, d.cfr_part")

    snippet = ""
    if query.strip():
        snippet = (", ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),"
                   " 'MaxWords=40, MinWords=20, StartSel=<mark>, StopSel=</mark>') AS headline")

    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM regulations_docs d WHERE {where}").bindparams(**bind))

    bind["limit"] = page_size
    bind["offset"] = offset
    rows = await database.fetch_all(
        text(f"""SELECT d.id, d.title, d.cfr_title, d.cfr_part, d.part_name,
               d.agency, d.as_of_date::text, d.page_count {snippet}
        FROM regulations_docs d WHERE {where}
        ORDER BY {order} LIMIT :limit OFFSET :offset""").bindparams(**bind))

    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}


@router.get("/api/regulations-docs/{doc_id}")
async def get_regulation_doc(doc_id: int):
    row = await database.fetch_one(
        q("SELECT * FROM regulations_docs WHERE id = :id", id=doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    d["as_of_date"] = str(d["as_of_date"]) if d["as_of_date"] else None
    d["ingested_at"] = str(d["ingested_at"]) if d["ingested_at"] else None
    d["search_vector"] = None
    return d


@router.get("/api/regulations-docs/{doc_id}/pdf")
async def serve_regulation_pdf(doc_id: int):
    row = await database.fetch_one(
        q("SELECT filename, pdf_path FROM regulations_docs WHERE id = :id", id=doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_pdf_source(
        local_path=row["pdf_path"],
        gcs_object=_regulation_gcs_object(row["pdf_path"]),
        filename=row["filename"] or os.path.basename(row["pdf_path"]),
    )


@router.get("/api/regulations-docs/stats/summary")
async def regulations_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM regulations_docs"))
    pages = await database.fetch_val(q("SELECT COALESCE(SUM(page_count),0) FROM regulations_docs"))
    by_agency = await database.fetch_all(q("""
        SELECT agency, COUNT(*) as parts, SUM(page_count) as pages
        FROM regulations_docs GROUP BY agency ORDER BY parts DESC"""))
    return {"total_parts": total, "total_pages": pages,
            "by_agency": [dict(r) for r in by_agency]}


# ── Policy Manuals ────────────────────────────────────────────────────────────

