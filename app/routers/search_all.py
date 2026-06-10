"""Unified cross-corpus search."""
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

@router.get("/api/search-all")
async def search_all(
    request: Request,
    query: str = Query(alias="q"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
):
    """
    Unified full-text search across all four corpora.
    Returns results sorted by ts_rank DESC, each annotated with 'corpus':
      balca | aao | regulation | policy
    """
    q_text = _clean_query(query)
    if not q_text:
        return {"total": 0, "page": page, "page_size": page_size, "results": []}

    offset = (page - 1) * page_size

    sql = text("""
        WITH ranked AS (
            -- BALCA decisions
            SELECT
                'balca'::text                                              AS corpus,
                d.id,
	                d.case_number                                              AS title,
	                d.employer_name                                            AS subtitle,
	                d.decision_date::text                                      AS date,
	                d.outcome,
	                (ts_rank(d.search_vector, websearch_to_tsquery('english', :q)) * 0.55
	                 + CASE WHEN d.case_number ILIKE :q_exact THEN 4.0 ELSE 0 END
	                 + CASE WHEN d.case_number ILIKE :q_like THEN 1.5 ELSE 0 END
	                 + CASE WHEN d.employer_name ILIKE :q_like THEN 2.0 ELSE 0 END
	                 + log(1 + COALESCE((SELECT COUNT(*) FROM citations c WHERE c.cited_id = d.id), 0)) * 0.30
	                 + log(1 + COALESCE((SELECT COUNT(*) FROM decision_regulations dr WHERE dr.decision_id = d.id), 0)) * 0.10)
	                                                                           AS rank,
	                ts_headline('english', d.full_text,
                    websearch_to_tsquery('english', :q),
	                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
	                                                                           AS headline
	            FROM decisions d
	            WHERE d.search_vector @@ websearch_to_tsquery('english', :q)
	               OR d.case_number ILIKE :q_like
	               OR d.employer_name ILIKE :q_like
	               OR d.job_title ILIKE :q_like

            UNION ALL

            -- AAO decisions
            SELECT
                'aao'::text,
                d.id,
                COALESCE(d.title, d.form_type, 'AAO Decision'),
	                d.regulation,
	                d.decision_date::text,
	                d.outcome,
	                (ts_rank(d.search_vector, websearch_to_tsquery('english', :q)) * 0.65
	                 + CASE WHEN d.title ILIKE :q_like THEN 1.5 ELSE 0 END
	                 + CASE WHEN d.filename ILIKE :q_like THEN 1.0 ELSE 0 END
	                 + CASE WHEN d.form_type ILIKE :q_like THEN 0.8 ELSE 0 END
	                 + CASE WHEN d.regulation ILIKE :q_like THEN 0.7 ELSE 0 END),
	                ts_headline('english', d.full_text,
                    websearch_to_tsquery('english', :q),
	                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
	            FROM aao_decisions d
	            WHERE d.search_vector @@ websearch_to_tsquery('english', :q)
	               OR d.title ILIKE :q_like
	               OR d.filename ILIKE :q_like
	               OR d.form_type ILIKE :q_like
	               OR d.regulation ILIKE :q_like

            UNION ALL

            -- Regulations docs
            SELECT
                'regulation'::text,
                d.id,
                d.title,
                d.part_name,
                d.as_of_date::text,
                NULL,
                ts_rank(d.search_vector, websearch_to_tsquery('english', :q)),
                ts_headline('english', d.full_text,
                    websearch_to_tsquery('english', :q),
                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
            FROM regulations_docs d
            WHERE d.search_vector @@ websearch_to_tsquery('english', :q)

            UNION ALL

            -- Policy docs
            SELECT
                'policy'::text,
                d.id,
                COALESCE(d.section || ' — ' || d.subject, d.subject, d.section),
                d.source,
                d.as_of_date::text,
                NULL,
                ts_rank(d.search_vector, websearch_to_tsquery('english', :q)),
                ts_headline('english', d.full_text,
                    websearch_to_tsquery('english', :q),
                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
            FROM policy_docs d
            WHERE d.search_vector @@ websearch_to_tsquery('english', :q)

            UNION ALL

            -- INA sections
            SELECT
                'ina'::text,
                NULL::int,
                source_label,
                cfr_citation,
                NULL::text,
                NULL::text,
                ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', :q)),
                ts_headline('english', chunk_text,
                    websearch_to_tsquery('english', :q),
                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
            FROM (
                SELECT DISTINCT ON (source_id)
                    source_label, cfr_citation, chunk_text
                FROM rag_chunks
                WHERE corpus = 'ina'
                  AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
                ORDER BY source_id,
                         ts_rank(to_tsvector('english', chunk_text),
                                 websearch_to_tsquery('english', :q)) DESC
            ) ina_best

            UNION ALL

            -- USCIS evidence checklists
            SELECT
                'uscis_checklists'::text,
                NULL::int,
                source_label,
                form_type,
                source_date,
                NULL::text,
                ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', :q)),
                ts_headline('english', chunk_text,
                    websearch_to_tsquery('english', :q),
                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
            FROM (
                SELECT DISTINCT ON (source_id)
                    source_label, form_type, source_date, chunk_text
                FROM rag_chunks
                WHERE corpus = 'uscis_checklists'
                  AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
                ORDER BY source_id,
                         ts_rank(to_tsvector('english', chunk_text),
                                 websearch_to_tsquery('english', :q)) DESC
            ) checklist_best

            UNION ALL

            -- USCIS form instructions
            SELECT
                'form_instructions'::text,
                NULL::int,
                source_label,
                form_type,
                source_date,
                NULL::text,
                ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', :q)),
                ts_headline('english', chunk_text,
                    websearch_to_tsquery('english', :q),
                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
            FROM (
                SELECT DISTINCT ON (source_id)
                    source_label, form_type, source_date, chunk_text
                FROM rag_chunks
                WHERE corpus = 'form_instructions'
                  AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
                ORDER BY source_id,
                         ts_rank(to_tsvector('english', chunk_text),
                                 websearch_to_tsquery('english', :q)) DESC
            ) instr_best

            UNION ALL

            -- DOL ETA foreign labor FAQs
            SELECT
                'dol_faqs'::text,
                NULL::int,
                source_label,
                form_type,
                source_date,
                NULL::text,
                ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', :q)),
                ts_headline('english', chunk_text,
                    websearch_to_tsquery('english', :q),
                    'MaxWords=25, MinWords=12, StartSel=<mark>, StopSel=</mark>')
            FROM (
                SELECT DISTINCT ON (source_id)
                    source_label, form_type, source_date, chunk_text
                FROM rag_chunks
                WHERE corpus = 'dol_faqs'
                  AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
                ORDER BY source_id,
                         ts_rank(to_tsvector('english', chunk_text),
                                 websearch_to_tsquery('english', :q)) DESC
            ) dol_best
        )
        SELECT corpus, id, title, subtitle, date, outcome, rank, headline
        FROM ranked
        ORDER BY rank DESC, date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """).bindparams(q=q_text, q_like=_like(q_text), q_exact=q_text, limit=page_size, offset=offset)

    count_sql = text("""
        SELECT (
	            SELECT COUNT(*) FROM decisions
	            WHERE search_vector @@ websearch_to_tsquery('english', :q)
	               OR case_number ILIKE :q_like
	               OR employer_name ILIKE :q_like
	               OR job_title ILIKE :q_like
	        ) + (
	            SELECT COUNT(*) FROM aao_decisions
	            WHERE search_vector @@ websearch_to_tsquery('english', :q)
	               OR title ILIKE :q_like
	               OR filename ILIKE :q_like
	               OR form_type ILIKE :q_like
	               OR regulation ILIKE :q_like
        ) + (
            SELECT COUNT(*) FROM regulations_docs WHERE search_vector @@ websearch_to_tsquery('english', :q)
        ) + (
            SELECT COUNT(*) FROM policy_docs WHERE search_vector @@ websearch_to_tsquery('english', :q)
        ) + (
            SELECT COUNT(DISTINCT source_id) FROM rag_chunks
            WHERE corpus = 'ina'
              AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
        ) + (
            SELECT COUNT(DISTINCT source_id) FROM rag_chunks
            WHERE corpus = 'uscis_checklists'
              AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
        ) + (
            SELECT COUNT(DISTINCT source_id) FROM rag_chunks
            WHERE corpus = 'form_instructions'
              AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
        ) + (
            SELECT COUNT(DISTINCT source_id) FROM rag_chunks
            WHERE corpus = 'dol_faqs'
              AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q)
        ) AS total
    """).bindparams(q=q_text, q_like=_like(q_text))

    total = await database.fetch_val(count_sql)
    rows = await database.fetch_all(sql)
    await log_search_event(
        request,
        corpus="all",
        query=q_text,
        filters={},
        result_count=total,
    )
    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}


# ── Citation Graph ────────────────────────────────────────────────────────────

