"""BALCA decisions: search, detail, tags, notes, stats, citation graph."""
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

@router.get("/api/search")
async def search_decisions(
    request: Request,
    query: str = Query(default="", alias="q"),
    regulation: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    employer: Optional[str] = Query(default=None),
    # Advanced fields
    case_number: Optional[str] = Query(default=None),
    panel: Optional[str] = Query(default=None),
    has_citations: Optional[bool] = Query(default=None),
    has_regulations: Optional[bool] = Query(default=None),
    include_docketing_notices: bool = Query(default=False),
    sort_by: str = Query(default="relevance"),   # relevance | date_desc | date_asc
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q_text = _clean_query(query)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    if not include_docketing_notices:
        conditions.append("d.doc_type != 'docketing_notice'")
    bind = {}

    if q_text:
        conditions.append("""(
            d.search_vector @@ websearch_to_tsquery('english', :qtext)
            OR d.case_number ILIKE :q_like
            OR d.employer_name ILIKE :q_like
            OR d.job_title ILIKE :q_like
        )""")
        bind["qtext"] = q_text
        bind["q_like"] = _like(q_text)
        bind["q_exact"] = q_text
    if regulation:
        conditions.append("d.id IN (SELECT dr.decision_id FROM decision_regulations dr JOIN regulations r ON r.id = dr.regulation_id WHERE r.citation ILIKE :reg)")
        bind["reg"] = f"%{regulation}%"
    if outcome:
        conditions.append("d.outcome = :outcome")
        bind["outcome"] = outcome
    if date_from:
        conditions.append("d.decision_date >= :date_from")
        bind["date_from"] = _date.fromisoformat(date_from)
    if date_to:
        conditions.append("d.decision_date <= :date_to")
        bind["date_to"] = _date.fromisoformat(date_to)
    if employer:
        conditions.append("d.employer_name ILIKE :employer")
        bind["employer"] = f"%{employer}%"
    if case_number:
        conditions.append("d.case_number ILIKE :case_number")
        bind["case_number"] = f"%{case_number}%"
    if panel:
        conditions.append("d.panel ILIKE :panel")
        bind["panel"] = f"%{panel}%"
    if has_citations is True:
        conditions.append("EXISTS (SELECT 1 FROM citations c WHERE c.citing_id = d.id AND c.cited_id IS NOT NULL)")
    if has_citations is False:
        conditions.append("NOT EXISTS (SELECT 1 FROM citations c WHERE c.citing_id = d.id AND c.cited_id IS NOT NULL)")
    if has_regulations is True:
        conditions.append("EXISTS (SELECT 1 FROM decision_regulations dr WHERE dr.decision_id = d.id)")
    if has_regulations is False:
        conditions.append("NOT EXISTS (SELECT 1 FROM decision_regulations dr WHERE dr.decision_id = d.id)")

    where = " AND ".join(conditions)

    if sort_by == "date_asc":
        order = "d.decision_date ASC NULLS LAST"
    elif sort_by == "date_desc":
        order = "d.decision_date DESC NULLS LAST"
    elif q_text:
        order = (
            "(ts_rank(d.search_vector, websearch_to_tsquery('english', :qtext)) * 0.55 "
            "+ CASE WHEN d.case_number ILIKE :q_exact THEN 4.0 ELSE 0 END "
            "+ CASE WHEN d.case_number ILIKE :q_like THEN 1.5 ELSE 0 END "
            "+ CASE WHEN d.employer_name ILIKE :q_like THEN 2.0 ELSE 0 END "
            "+ CASE WHEN d.job_title ILIKE :q_like THEN 0.5 ELSE 0 END "
            "+ log(1 + COALESCE((SELECT COUNT(*) FROM citations c WHERE c.cited_id = d.id), 0)) * 0.30 "
            "+ log(1 + COALESCE((SELECT COUNT(*) FROM decision_regulations dr WHERE dr.decision_id = d.id), 0)) * 0.10) "
            "DESC, d.decision_date DESC NULLS LAST"
        )
    else:
        order = "d.decision_date DESC NULLS LAST"

    snippet = ""
    if q_text:
        snippet = (", ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),"
                   " 'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline")

    count_bind = {key: value for key, value in bind.items() if f":{key}" in where}
    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM decisions d WHERE {where}").bindparams(**count_bind)
    )

    bind["limit"] = page_size
    bind["offset"] = offset
    rows = await database.fetch_all(
        text(f"""SELECT d.id, d.case_number, d.decision_date::text, d.employer_name,
               d.job_title, d.outcome, d.panel, d.extraction_status,
               d.citation_quality_status, d.regulation_quality_status {snippet},
               (SELECT COUNT(*) FROM decision_regulations dr WHERE dr.decision_id = d.id) AS regulation_count,
               (SELECT COUNT(*) FROM citations c WHERE c.citing_id = d.id) AS citation_count,
               (SELECT COUNT(*) FROM citations c WHERE c.cited_id = d.id) AS cited_by_count,
               (SELECT COUNT(*) FROM citations c WHERE c.citing_id = d.id AND c.cited_id IS NULL) AS unresolved_citation_count
        FROM decisions d WHERE {where} ORDER BY {order} LIMIT :limit OFFSET :offset"""
        ).bindparams(**bind)
    )
    await log_search_event(
        request,
        corpus="balca",
        query=q_text,
        filters=_search_filters(
            regulation=regulation,
            outcome=outcome,
            date_from=date_from,
            date_to=date_to,
            employer=employer,
            case_number=case_number,
            panel=panel,
            has_citations=has_citations,
            has_regulations=has_regulations,
            include_docketing_notices=include_docketing_notices,
            sort_by=sort_by,
        ),
        result_count=total,
    )
    return {"total": total, "page": page, "page_size": page_size, "results": [dict(r) for r in rows]}


@router.get("/api/search-analytics/common")
async def common_searches(
    request: Request,
    corpus: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=25, ge=1, le=100),
):
    """Private/admin view of common searches; not used by the public UI."""
    require_search_analytics_access(request)
    conditions = ["created_at >= NOW() - (:days * INTERVAL '1 day')"]
    bind: dict[str, Any] = {"days": days, "limit": limit}
    if corpus:
        conditions.append("corpus = :corpus")
        bind["corpus"] = corpus
    where = " AND ".join(conditions)
    rows = await database.fetch_all(
        text(f"""
            SELECT corpus, query, COUNT(*) AS search_count,
                   AVG(result_count)::numeric(12, 2) AS avg_results,
                   SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) AS zero_result_count,
                   MAX(created_at)::text AS last_seen
            FROM search_events
            WHERE {where}
            GROUP BY corpus, query
            ORDER BY search_count DESC, last_seen DESC
            LIMIT :limit
        """).bindparams(**bind)
    )
    return {"days": days, "results": [dict(row) for row in rows]}


@router.post("/api/search-analytics/click")
async def record_search_click(request: Request, data: dict):
    """Optional hook for later UI click tracking without exposing global analytics."""
    query = _clean_query(data.get("query", ""))
    corpus = data.get("corpus") or "unknown"
    if not query:
        return {"ok": False, "reason": "empty query"}
    await database.execute(
        text("""
            INSERT INTO search_events (
                corpus, query, filters, result_count, clicked_result_id, clicked_corpus,
                session_key, user_label, source_path
            ) VALUES (
                :corpus, :query, CAST(:filters AS jsonb), 0, :clicked_result_id, :clicked_corpus,
                :session_key, :user_label, :source_path
            )
        """).bindparams(
            corpus=corpus,
            query=query,
            filters=json.dumps(data.get("filters") or {}, sort_keys=True),
            clicked_result_id=data.get("result_id"),
            clicked_corpus=data.get("result_corpus") or corpus,
            session_key=request.headers.get("x-session-id"),
            user_label=request.headers.get("x-user-label"),
            source_path=str(request.url.path),
        )
    )
    return {"ok": True}

# ── Decision detail ───────────────────────────────────────────────────────────

@router.get("/api/decisions/{decision_id}")
async def get_decision(decision_id: int):
    row = await database.fetch_one(q("SELECT * FROM decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    regulations = await database.fetch_all(q("""
        SELECT r.id, r.citation, r.title, r.category, dr.context_snippet
        FROM decision_regulations dr JOIN regulations r ON r.id = dr.regulation_id
        WHERE dr.decision_id = :id ORDER BY r.citation""", id=decision_id))

    citations_made = await database.fetch_all(q("""
        SELECT c.id, c.cited_id, c.cited_raw, c.context_snippet,
               d2.case_number AS cited_case_number
        FROM citations c LEFT JOIN decisions d2 ON d2.id = c.cited_id
        WHERE c.citing_id = :id ORDER BY d2.case_number NULLS LAST""", id=decision_id))

    cited_by = await database.fetch_all(q("""
        SELECT c.id, c.citing_id, c.context_snippet,
               d2.case_number AS citing_case_number
        FROM citations c JOIN decisions d2 ON d2.id = c.citing_id
        WHERE c.cited_id = :id ORDER BY d2.decision_date DESC NULLS LAST""", id=decision_id))

    tags = await database.fetch_all(q("""
        SELECT t.id, t.name, t.color FROM decision_tags dt
        JOIN tags t ON t.id = dt.tag_id WHERE dt.decision_id = :id""", id=decision_id))

    notes = await database.fetch_all(q("""
        SELECT id, note, created_at::text FROM research_notes
        WHERE decision_id = :id ORDER BY created_at DESC""", id=decision_id))

    d = dict(row)
    d["decision_date"] = str(d["decision_date"]) if d["decision_date"] else None
    d["ingested_at"] = str(d["ingested_at"]) if d.get("ingested_at") else None
    d["search_vector"] = None
    d["regulations"] = [dict(r) for r in regulations]
    d["citations_made"] = [dict(r) for r in citations_made]
    d["cited_by"] = [dict(r) for r in cited_by]
    d["tags"] = [dict(r) for r in tags]
    d["notes"] = [dict(r) for r in notes]
    return d


@router.get("/api/decisions/{decision_id}/citation-map")
async def get_citation_map(decision_id: int):
    """
    Returns {case_number: id} for every resolved outbound citation from this decision.
    Used by the frontend to hyperlink case numbers inline in the opinion text.
    """
    rows = await database.fetch_all(q("""
        SELECT d.case_number, d.id
        FROM citations c
        JOIN decisions d ON d.id = c.cited_id
        WHERE c.citing_id = :id AND c.cited_id IS NOT NULL
    """, id=decision_id))
    return {row["case_number"]: row["id"] for row in rows}


@router.get("/api/decisions/{decision_id}/pdf")
async def serve_pdf(decision_id: int):
    row = await database.fetch_one(q("SELECT filename FROM decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_pdf_source(
        local_path=_balca_pdf_path(row["filename"]),
        gcs_object=_balca_gcs_object(row["filename"]),
        filename=row["filename"],
    )

# ── Regulations ───────────────────────────────────────────────────────────────

@router.get("/api/regulations")
async def list_regulations():
    rows = await database.fetch_all(q("""
        SELECT r.id, r.citation, r.title, r.category,
               COUNT(dr.decision_id) AS decision_count
        FROM regulations r LEFT JOIN decision_regulations dr ON dr.regulation_id = r.id
        GROUP BY r.id ORDER BY r.citation"""))
    return [dict(r) for r in rows]


@router.get("/api/regulations/{regulation_id}/decisions")
async def decisions_by_regulation(regulation_id: int, page: int = 1, page_size: int = 50):
    offset = (page - 1) * page_size
    rows = await database.fetch_all(q("""
        SELECT d.id, d.case_number, d.decision_date::text, d.employer_name,
               d.job_title, d.outcome, dr.context_snippet
        FROM decision_regulations dr JOIN decisions d ON d.id = dr.decision_id
        WHERE dr.regulation_id = :reg_id
        ORDER BY d.decision_date DESC NULLS LAST LIMIT :lim OFFSET :off""",
        reg_id=regulation_id, lim=page_size, off=offset))
    return [dict(r) for r in rows]


# ── Tags ──────────────────────────────────────────────────────────────────────

@router.get("/api/tags")
async def list_tags():
    rows = await database.fetch_all(q("""
        SELECT t.*, COUNT(dt.decision_id) AS decision_count
        FROM tags t LEFT JOIN decision_tags dt ON dt.tag_id = t.id
        GROUP BY t.id ORDER BY t.name"""))
    return [dict(r) for r in rows]

@router.post("/api/tags")
async def create_tag(data: dict):
    row = await database.fetch_one(q(
        "INSERT INTO tags (name, color) VALUES (:name, :color) ON CONFLICT (name) DO UPDATE SET color=EXCLUDED.color RETURNING *",
        name=data["name"], color=data.get("color", "#6366f1")))
    return dict(row)

@router.post("/api/decisions/{decision_id}/tags/{tag_id}")
async def add_tag(decision_id: int, tag_id: int):
    await database.execute(q("INSERT INTO decision_tags (decision_id, tag_id) VALUES (:did, :tid) ON CONFLICT DO NOTHING", did=decision_id, tid=tag_id))
    return {"ok": True}

@router.delete("/api/decisions/{decision_id}/tags/{tag_id}")
async def remove_tag(decision_id: int, tag_id: int):
    await database.execute(q("DELETE FROM decision_tags WHERE decision_id=:did AND tag_id=:tid", did=decision_id, tid=tag_id))
    return {"ok": True}


# ── Notes ─────────────────────────────────────────────────────────────────────

@router.post("/api/decisions/{decision_id}/notes")
async def add_note(decision_id: int, data: dict):
    row = await database.fetch_one(q(
        "INSERT INTO research_notes (decision_id, note) VALUES (:did, :note) RETURNING id, note, created_at::text",
        did=decision_id, note=data["note"]))
    return dict(row)

@router.delete("/api/notes/{note_id}")
async def delete_note(note_id: int):
    await database.execute(q("DELETE FROM research_notes WHERE id=:id", id=note_id))
    return {"ok": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/api/stats")
async def stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM decisions"))
    indexed = await database.fetch_val(q("SELECT COUNT(*) FROM decisions WHERE text_extracted=TRUE"))
    outcomes = await database.fetch_all(q("SELECT outcome, COUNT(*) AS cnt FROM decisions GROUP BY outcome ORDER BY cnt DESC"))
    top_regs = await database.fetch_all(q("""
        SELECT r.citation, r.category, COUNT(dr.decision_id) AS cnt
        FROM regulations r JOIN decision_regulations dr ON dr.regulation_id=r.id
        GROUP BY r.id ORDER BY cnt DESC LIMIT 10"""))
    return {
        "total_decisions": total,
        "indexed_decisions": indexed,
        "outcomes": [dict(r) for r in outcomes],
        "top_regulations": [dict(r) for r in top_regs],
    }


# ── Projects ──────────────────────────────────────────────────────────────────



@router.get("/api/search/citation-graph")
async def citation_graph(
    query: str = Query(alias="q"),
    limit: int = Query(default=40, ge=5, le=80),
):
    """
    Returns a citation network for a search query.
    Nodes: primary (matched search) + secondary (cited by primaries, not in search).
    Edges: citation links between any two nodes.
    """
    if not query.strip():
        return {"nodes": [], "edges": []}

    # Step 1: get top matching decisions
    primary_rows = await database.fetch_all(text("""
        SELECT id, case_number, decision_date::text AS date,
               employer_name, outcome,
               (ts_rank(search_vector, websearch_to_tsquery('english', :q)) * 0.7
                + log(1 + COALESCE((SELECT COUNT(*) FROM citations ci WHERE ci.cited_id = decisions.id), 0)) * 0.3) AS rank
        FROM decisions
        WHERE search_vector @@ websearch_to_tsquery('english', :q)
        ORDER BY rank DESC
        LIMIT :lim
    """).bindparams(q=query.strip(), lim=limit))

    if not primary_rows:
        return {"nodes": [], "edges": []}

    primary_ids = [r["id"] for r in primary_rows]

    # Step 2: get all citation edges between primaries
    edge_rows = await database.fetch_all(text("""
        SELECT citing_id, cited_id
        FROM citations
        WHERE citing_id = ANY(:ids) AND cited_id = ANY(:ids)
    """).bindparams(ids=primary_ids))

    # Step 3: get secondary nodes — cases cited by primaries but not in primaries
    secondary_cite_rows = await database.fetch_all(text("""
        SELECT c.citing_id, c.cited_id,
               d.id, d.case_number, d.decision_date::text AS date,
               d.employer_name, d.outcome
        FROM citations c
        JOIN decisions d ON d.id = c.cited_id
        WHERE c.citing_id = ANY(:ids)
          AND c.cited_id IS NOT NULL
          AND c.cited_id != ALL(:ids)
    """).bindparams(ids=primary_ids))

    # Aggregate secondary nodes, count how many primaries cite each
    secondary_map = {}
    secondary_edges = []
    for row in secondary_cite_rows:
        sid = row["cited_id"]
        if sid not in secondary_map:
            secondary_map[sid] = {
                "id": sid,
                "case_number": row["case_number"],
                "date": row["date"],
                "employer_name": row["employer_name"],
                "outcome": row["outcome"],
                "cited_by_count": 0,
            }
        secondary_map[sid]["cited_by_count"] += 1
        secondary_edges.append({"source": row["citing_id"], "target": sid})

    # Only keep secondaries cited by 2+ primaries (keeps graph clean)
    # But always keep at least top-10 by cited_by_count if < 2 threshold would leave nothing
    secondaries = sorted(secondary_map.values(), key=lambda x: -x["cited_by_count"])
    min_citations = 2 if len([s for s in secondaries if s["cited_by_count"] >= 2]) >= 3 else 1
    secondaries = [s for s in secondaries if s["cited_by_count"] >= min_citations][:30]
    secondary_ids = {s["id"] for s in secondaries}

    # Filter secondary edges to only kept secondaries
    secondary_edges = [e for e in secondary_edges if e["target"] in secondary_ids]

    # Build final node list
    nodes = []
    for r in primary_rows:
        nodes.append({
            "id": r["id"],
            "case_number": r["case_number"],
            "date": r["date"],
            "employer_name": r["employer_name"],
            "outcome": r["outcome"],
            "tier": "primary",
            "rank": float(r["rank"]),
        })
    for s in secondaries:
        nodes.append({**s, "tier": "secondary", "rank": 0.0})

    edges = [{"source": e["citing_id"], "target": e["cited_id"]} for e in edge_rows]
    edges += secondary_edges

    return {
        "query": query.strip(),
        "nodes": nodes,
        "edges": edges,
        "primary_count": len(primary_rows),
        "secondary_count": len(secondaries),
    }


