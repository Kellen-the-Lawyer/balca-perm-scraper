"""USCIS Policy Manual and policy documents."""
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

@router.get("/api/policy-docs")
async def list_policy_docs():
    rows = await database.fetch_all(q("""
        SELECT id, source, title, section, subject, as_of_date::text, page_count
        FROM policy_docs ORDER BY source, section"""))
    return [dict(r) for r in rows]

@router.get("/api/policy-docs/search")
async def search_policy(
    query: str = Query(default="", alias="q"),
    source: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {}

    if query.strip():
        conditions.append("d.search_vector @@ websearch_to_tsquery('english', :qtext)")
        bind["qtext"] = query.strip()
    if source:
        conditions.append("d.source = :source")
        bind["source"] = source

    where = " AND ".join(conditions)
    order = ("ts_rank(d.search_vector, websearch_to_tsquery('english', :qtext)) DESC, d.source, d.section"
             if query.strip() else "d.source, d.section")

    snippet = ""
    if query.strip():
        snippet = (", ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),"
                   " 'MaxWords=40, MinWords=20, StartSel=<mark>, StopSel=</mark>') AS headline")

    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM policy_docs d WHERE {where}").bindparams(**bind))
    bind["limit"] = page_size
    bind["offset"] = offset
    rows = await database.fetch_all(
        text(f"""SELECT d.id, d.source, d.title, d.section, d.subject,
               d.as_of_date::text, d.page_count {snippet}
        FROM policy_docs d WHERE {where}
        ORDER BY {order} LIMIT :limit OFFSET :offset""").bindparams(**bind))

    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}

@router.get("/api/policy-docs/{doc_id}")
async def get_policy_doc(doc_id: int):
    row = await database.fetch_one(q("SELECT * FROM policy_docs WHERE id = :id", id=doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    d["as_of_date"] = str(d["as_of_date"]) if d["as_of_date"] else None
    d["ingested_at"] = str(d["ingested_at"]) if d["ingested_at"] else None
    d["search_vector"] = None
    return d

@router.get("/api/policy-docs/{doc_id}/pdf")
async def serve_policy_pdf(doc_id: int):
    row = await database.fetch_one(q("SELECT filename, pdf_path, source FROM policy_docs WHERE id = :id", id=doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    filename = "Policy_Manual_USCIS.pdf" if row["source"] == "USCIS_PM" else row["filename"]
    return _serve_pdf_source(
        local_path=row["pdf_path"],
        gcs_object=_policy_gcs_object(row["pdf_path"], row["source"]),
        filename=filename or os.path.basename(row["pdf_path"]),
    )

@router.get("/api/policy-docs/stats/summary")
async def policy_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM policy_docs"))
    pages = await database.fetch_val(q("SELECT COALESCE(SUM(page_count),0) FROM policy_docs"))
    by_source = await database.fetch_all(q("""
        SELECT source, COUNT(*) as sections, SUM(page_count) as pages
        FROM policy_docs GROUP BY source ORDER BY source"""))
    return {"total_sections": total, "total_pages": pages,
            "by_source": [dict(r) for r in by_source]}


# ── Cross-corpus Search ───────────────────────────────────────────────────────

