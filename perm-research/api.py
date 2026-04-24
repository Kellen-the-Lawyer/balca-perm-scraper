"""
PERM Appeal Decisions — Research API
"""
import os
import re
import json
from contextlib import asynccontextmanager
from datetime import date as _date
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
from extract_pwd import extract_pwd_from_bytes
from extract_experience_letter import extract_letter_from_bytes
from typing import Any, Optional

import httpx
import databases
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"
)
PDF_BASE_PATH = os.environ.get(
    "PDF_BASE_PATH", "/Users/Dad/Documents/GitHub/balca-perm-scraper/data/raw/pdfs"
)

database = databases.Database(DATABASE_URL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await ensure_operational_schema()
    yield
    await database.disconnect()

app = FastAPI(title="PERM Decisions Research API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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


def _balca_pdf_path(filename: str | None) -> str | None:
    return os.path.join(PDF_BASE_PATH, filename) if filename else None

# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
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
            "+ CASE WHEN d.employer_name ILIKE :q_like THEN 0.8 ELSE 0 END "
            "+ CASE WHEN d.job_title ILIKE :q_like THEN 0.5 ELSE 0 END "
            "+ log(1 + COALESCE((SELECT COUNT(*) FROM citations c WHERE c.cited_id = d.id), 0)) * 0.25 "
            "+ COALESCE((SELECT COUNT(*) FROM decision_regulations dr WHERE dr.decision_id = d.id), 0) * 0.05) "
            "DESC, d.decision_date DESC NULLS LAST"
        )
    else:
        order = "d.decision_date DESC NULLS LAST"

    snippet = ""
    if q_text:
        snippet = (", ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),"
                   " 'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline")

    total = await database.fetch_val(text(f"SELECT COUNT(*) FROM decisions d WHERE {where}").bindparams(**bind))

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


@app.get("/api/search-analytics/common")
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


@app.post("/api/search-analytics/click")
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

@app.get("/api/decisions/{decision_id}")
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


@app.get("/api/decisions/{decision_id}/citation-map")
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


@app.get("/api/decisions/{decision_id}/pdf")
async def serve_pdf(decision_id: int):
    row = await database.fetch_one(q("SELECT filename FROM decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    path = os.path.join(PDF_BASE_PATH, row["filename"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"PDF not found: {path}")
    return FileResponse(path, media_type="application/pdf")

# ── Regulations ───────────────────────────────────────────────────────────────

@app.get("/api/regulations")
async def list_regulations():
    rows = await database.fetch_all(q("""
        SELECT r.id, r.citation, r.title, r.category,
               COUNT(dr.decision_id) AS decision_count
        FROM regulations r LEFT JOIN decision_regulations dr ON dr.regulation_id = r.id
        GROUP BY r.id ORDER BY r.citation"""))
    return [dict(r) for r in rows]


@app.get("/api/regulations/{regulation_id}/decisions")
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

@app.get("/api/tags")
async def list_tags():
    rows = await database.fetch_all(q("""
        SELECT t.*, COUNT(dt.decision_id) AS decision_count
        FROM tags t LEFT JOIN decision_tags dt ON dt.tag_id = t.id
        GROUP BY t.id ORDER BY t.name"""))
    return [dict(r) for r in rows]

@app.post("/api/tags")
async def create_tag(data: dict):
    row = await database.fetch_one(q(
        "INSERT INTO tags (name, color) VALUES (:name, :color) ON CONFLICT (name) DO UPDATE SET color=EXCLUDED.color RETURNING *",
        name=data["name"], color=data.get("color", "#6366f1")))
    return dict(row)

@app.post("/api/decisions/{decision_id}/tags/{tag_id}")
async def add_tag(decision_id: int, tag_id: int):
    await database.execute(q("INSERT INTO decision_tags (decision_id, tag_id) VALUES (:did, :tid) ON CONFLICT DO NOTHING", did=decision_id, tid=tag_id))
    return {"ok": True}

@app.delete("/api/decisions/{decision_id}/tags/{tag_id}")
async def remove_tag(decision_id: int, tag_id: int):
    await database.execute(q("DELETE FROM decision_tags WHERE decision_id=:did AND tag_id=:tid", did=decision_id, tid=tag_id))
    return {"ok": True}


# ── Notes ─────────────────────────────────────────────────────────────────────

@app.post("/api/decisions/{decision_id}/notes")
async def add_note(decision_id: int, data: dict):
    row = await database.fetch_one(q(
        "INSERT INTO research_notes (decision_id, note) VALUES (:did, :note) RETURNING id, note, created_at::text",
        did=decision_id, note=data["note"]))
    return dict(row)

@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: int):
    await database.execute(q("DELETE FROM research_notes WHERE id=:id", id=note_id))
    return {"ok": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
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

@app.get("/api/projects")
async def list_projects():
    rows = await database.fetch_all(q("""
        SELECT p.id, p.name, p.description, p.color,
               p.created_at::text, p.updated_at::text,
               COUNT(DISTINCT pc.id) AS case_count,
               COUNT(DISTINCT pn.id) AS note_count
        FROM projects p
        LEFT JOIN project_cases pc ON pc.project_id = p.id
        LEFT JOIN project_notes pn ON pn.project_id = p.id
        GROUP BY p.id ORDER BY p.updated_at DESC"""))
    return [dict(r) for r in rows]

@app.post("/api/projects")
async def create_project(data: dict):
    row = await database.fetch_one(q("""
        INSERT INTO projects (name, description, color)
        VALUES (:name, :desc, :color) RETURNING id, name, description, color, created_at::text, updated_at::text""",
        name=data["name"], desc=data.get("description", ""), color=data.get("color", "#f59e0b")))
    return dict(row)

@app.patch("/api/projects/{project_id}")
async def update_project(project_id: int, data: dict):
    row = await database.fetch_one(q("""
        UPDATE projects SET name=:name, description=:desc, color=:color, updated_at=NOW()
        WHERE id=:id RETURNING id, name, description, color, updated_at::text""",
        id=project_id, name=data["name"], desc=data.get("description",""), color=data.get("color","#f59e0b")))
    return dict(row)

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    await database.execute(q("DELETE FROM projects WHERE id=:id", id=project_id))
    return {"ok": True}

@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    project = await database.fetch_one(q(
        "SELECT id, name, description, color, created_at::text, updated_at::text FROM projects WHERE id=:id",
        id=project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Not found")

    cases = await database.fetch_all(q("""
        SELECT pc.id AS pc_id, pc.search_query, pc.added_at::text,
               d.id, d.case_number, d.decision_date::text, d.employer_name,
               d.job_title, d.outcome
        FROM project_cases pc JOIN decisions d ON d.id = pc.decision_id
        WHERE pc.project_id = :pid ORDER BY pc.added_at DESC""", pid=project_id))

    notes = await database.fetch_all(q("""
        SELECT pn.id, pn.note, pn.created_at::text,
               d.case_number, d.id AS decision_id, d.employer_name
        FROM project_notes pn
        LEFT JOIN decisions d ON d.id = pn.decision_id
        WHERE pn.project_id = :pid ORDER BY pn.created_at DESC""", pid=project_id))

    return {**dict(project), "cases": [dict(r) for r in cases], "notes": [dict(r) for r in notes]}

@app.post("/api/projects/{project_id}/cases")
async def add_case_to_project(project_id: int, data: dict):
    row = await database.fetch_one(q("""
        INSERT INTO project_cases (project_id, decision_id, search_query)
        VALUES (:pid, :did, :query)
        ON CONFLICT (project_id, decision_id) DO UPDATE SET search_query=EXCLUDED.search_query
        RETURNING id, added_at::text""",
        pid=project_id, did=data["decision_id"], query=data.get("search_query", "")))
    await database.execute(q("UPDATE projects SET updated_at=NOW() WHERE id=:id", id=project_id))
    return dict(row)

@app.delete("/api/projects/{project_id}/cases/{decision_id}")
async def remove_case_from_project(project_id: int, decision_id: int):
    await database.execute(q(
        "DELETE FROM project_cases WHERE project_id=:pid AND decision_id=:did",
        pid=project_id, did=decision_id))
    return {"ok": True}

@app.post("/api/projects/{project_id}/notes")
async def add_project_note(project_id: int, data: dict):
    row = await database.fetch_one(q("""
        INSERT INTO project_notes (project_id, decision_id, note)
        VALUES (:pid, :did, :note) RETURNING id, note, created_at::text""",
        pid=project_id, did=data.get("decision_id"), note=data["note"]))
    await database.execute(q("UPDATE projects SET updated_at=NOW() WHERE id=:id", id=project_id))
    return dict(row)

@app.delete("/api/project-notes/{note_id}")
async def delete_project_note(note_id: int):
    await database.execute(q("DELETE FROM project_notes WHERE id=:id", id=note_id))
    return {"ok": True}

# ── Read Later ────────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/read-later")
async def save_to_read_later(project_id: int, data: dict):
    """
    Save a case to the 'read_later' section of a project.
    data: { source, decision_id?, aao_decision_id?,
            saved_from_case_number, saved_from_source }
    """
    source = data.get("source", "balca")
    did = data.get("decision_id")
    aao_id = data.get("aao_decision_id")
    from_num = data.get("saved_from_case_number", "")
    from_src = data.get("saved_from_source", "")

    # Resolve case_number / title for the item being saved (for display)
    if source == "balca" and did:
        row = await database.fetch_one(q(
            "SELECT case_number FROM decisions WHERE id=:id", id=did))
        label = row["case_number"] if row else str(did)
    elif source == "aao" and aao_id:
        row = await database.fetch_one(q(
            "SELECT COALESCE(title, form_type, filename) AS label FROM aao_decisions WHERE id=:id",
            id=aao_id))
        label = row["label"] if row else str(aao_id)
    else:
        label = ""

    row = await database.fetch_one(q("""
        INSERT INTO project_cases
            (project_id, decision_id, aao_decision_id, source, section,
             saved_from_case_number, saved_from_source, search_query)
        VALUES (:pid, :did, :aao_id, :source, 'read_later',
                :from_num, :from_src, :label)
        ON CONFLICT DO NOTHING
        RETURNING id, added_at::text
    """, pid=project_id, did=did, aao_id=aao_id, source=source,
         from_num=from_num, from_src=from_src, label=label))

    await database.execute(q(
        "UPDATE projects SET updated_at=NOW() WHERE id=:id", id=project_id))
    return dict(row) if row else {"ok": True, "duplicate": True}


@app.get("/api/projects/{project_id}/read-later")
async def list_read_later(project_id: int):
    rows = await database.fetch_all(q("""
        SELECT
            pc.id AS pc_id, pc.added_at::text, pc.source,
            pc.saved_from_case_number, pc.saved_from_source,
            -- BALCA fields
            d.id          AS decision_id,
            d.case_number, d.employer_name, d.job_title,
            d.decision_date::text AS decision_date, d.outcome,
            -- AAO fields
            a.id          AS aao_decision_id,
            a.title       AS aao_title, a.form_type, a.outcome AS aao_outcome,
            a.decision_date::text AS aao_decision_date
        FROM project_cases pc
        LEFT JOIN decisions      d ON d.id = pc.decision_id
        LEFT JOIN aao_decisions  a ON a.id = pc.aao_decision_id
        WHERE pc.project_id = :pid AND pc.section = 'read_later'
        ORDER BY pc.added_at DESC
    """, pid=project_id))
    return [dict(r) for r in rows]


@app.delete("/api/projects/{project_id}/read-later/{pc_id}")
async def remove_read_later(project_id: int, pc_id: int):
    await database.execute(q(
        "DELETE FROM project_cases WHERE id=:id AND project_id=:pid AND section='read_later'",
        id=pc_id, pid=project_id))
    return {"ok": True}


# Which projects contain a given decision?
@app.get("/api/decisions/{decision_id}/projects")
async def decision_projects(decision_id: int):
    rows = await database.fetch_all(q("""
        SELECT p.id, p.name, p.color
        FROM project_cases pc JOIN projects p ON p.id = pc.project_id
        WHERE pc.decision_id = :did""", did=decision_id))
    return [dict(r) for r in rows]

# ── AAO Search & Decisions ────────────────────────────────────────────────────

@app.get("/api/aao/search")
async def aao_search(
    request: Request,
    query: str = Query(default="", alias="q"),
    outcome: Optional[str] = Query(default=None),
    form_type: Optional[str] = Query(default=None),
    regulation: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    sort_by: str = Query(default="relevance"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q_text = _clean_query(query)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {}

    if q_text:
        conditions.append("""(
            d.search_vector @@ websearch_to_tsquery('english', :qtext)
            OR d.title ILIKE :q_like
            OR d.filename ILIKE :q_like
            OR d.form_type ILIKE :q_like
            OR d.regulation ILIKE :q_like
        )""")
        bind["qtext"] = q_text
        bind["q_like"] = _like(q_text)
    if outcome:
        conditions.append("d.outcome = :outcome")
        bind["outcome"] = outcome
    if form_type:
        conditions.append("d.form_type = :form_type")
        bind["form_type"] = form_type
    if regulation:
        conditions.append("d.regulation ILIKE :regulation")
        bind["regulation"] = f"%{regulation}%"
    if date_from:
        conditions.append("d.decision_date >= :date_from")
        bind["date_from"] = _date.fromisoformat(date_from)
    if date_to:
        conditions.append("d.decision_date <= :date_to")
        bind["date_to"] = _date.fromisoformat(date_to)

    where = " AND ".join(conditions)

    if sort_by == "date_asc":
        order = "d.decision_date ASC NULLS LAST"
    elif sort_by == "date_desc":
        order = "d.decision_date DESC NULLS LAST"
    elif q_text:
        order = (
            "(ts_rank(d.search_vector, websearch_to_tsquery('english', :qtext)) * 0.65 "
            "+ CASE WHEN d.title ILIKE :q_like THEN 1.5 ELSE 0 END "
            "+ CASE WHEN d.filename ILIKE :q_like THEN 1.0 ELSE 0 END "
            "+ CASE WHEN d.form_type ILIKE :q_like THEN 0.8 ELSE 0 END "
            "+ CASE WHEN d.regulation ILIKE :q_like THEN 0.7 ELSE 0 END) "
            "DESC, d.decision_date DESC NULLS LAST"
        )
    else:
        order = "d.decision_date DESC NULLS LAST"

    snippet = ""
    if q_text:
        snippet = (", ts_headline('english', d.full_text, websearch_to_tsquery('english', :qtext),"
                   " 'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline")

    total = await database.fetch_val(
        text(f"SELECT COUNT(*) FROM aao_decisions d WHERE {where}").bindparams(**bind))

    bind["limit"] = page_size
    bind["offset"] = offset
    rows = await database.fetch_all(
        text(f"""SELECT d.id, d.filename, d.title, d.decision_date::text,
               d.form_type, d.regulation, d.outcome, d.extraction_status,
               d.citation_quality_status, d.regulation_quality_status {snippet}
        FROM aao_decisions d WHERE {where}
        ORDER BY {order} LIMIT :limit OFFSET :offset""").bindparams(**bind))

    await log_search_event(
        request,
        corpus="aao",
        query=q_text,
        filters=_search_filters(
            outcome=outcome,
            form_type=form_type,
            regulation=regulation,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
        ),
        result_count=total,
    )
    return {"total": total, "page": page, "page_size": page_size,
            "results": [dict(r) for r in rows]}


@app.get("/api/aao/decisions/{decision_id}")
async def get_aao_decision(decision_id: int):
    row = await database.fetch_one(
        q("SELECT * FROM aao_decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    d["decision_date"] = str(d["decision_date"]) if d["decision_date"] else None
    d["ingested_at"] = str(d["ingested_at"]) if d.get("ingested_at") else None
    d["search_vector"] = None
    return d


@app.get("/api/precedents/map")
async def get_precedent_map():
    """
    Returns the full lookup map used for inline citation linking.
    Two keys per entry:
      - "25 I&N Dec. 369"  -> {id, citation, party_name, type}   (I&N Dec. citations)
      - "Adopted 2017-02"  -> {id, citation, party_name, type}   (Adopted decisions)
    Cached at startup; small enough to send to every decision detail load.
    """
    rows = await database.fetch_all("""
        SELECT id, citation, party_name, decision_type, adopted_num
        FROM precedent_decisions
        WHERE full_text != '' OR decision_type = 'adopted'
    """)
    result = {}
    for row in rows:
        entry = {
            "id":         row["id"],
            "citation":   row["citation"],
            "party_name": row["party_name"],
            "type":       row["decision_type"],
        }
        # Key by full I&N Dec. citation string, e.g. "25 I&N Dec. 369"
        m = re.search(r'(\d+ I&N Dec\. \d+)', row["citation"])
        if m:
            result[m.group(1)] = entry
            # Also key by "l&N Dec." variant (OCR artifact in some PDFs)
            result[m.group(1).replace("I&N", "l&N")] = entry

        # Key adopted decisions by their adopted number
        if row["decision_type"] == "adopted" and row["adopted_num"]:
            result[f"Adopted Decision {row['adopted_num']}"] = entry
            result[f"Adopted Decision {row['adopted_num']}".replace(" ", "\xa0")] = entry

    return result


@app.get("/api/precedents/{precedent_id}")
async def get_precedent(precedent_id: int):
    row = await database.fetch_one(q("""
        SELECT id, citation, party_name, year, body, decision_type,
               pm_number, adopted_num, pdf_path, pdf_url, full_text
        FROM precedent_decisions WHERE id = :id
    """, id=precedent_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(row)


@app.get("/api/precedents/{precedent_id}/pdf")
async def serve_precedent_pdf(precedent_id: int):
    row = await database.fetch_one(q(
        "SELECT pdf_path FROM precedent_decisions WHERE id = :id", id=precedent_id))
    if not row or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="PDF not available")
    path = row["pdf_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f"inline; filename=\"{os.path.basename(path)}\""})


@app.get("/api/aao/decisions/{decision_id}/pdf")
async def serve_aao_pdf(decision_id: int):
    row = await database.fetch_one(
        q("SELECT pdf_path FROM aao_decisions WHERE id = :id", id=decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if not os.path.exists(row["pdf_path"]):
        raise HTTPException(status_code=404, detail=f"PDF not found: {row['pdf_path']}")
    return FileResponse(row["pdf_path"], media_type="application/pdf")


@app.get("/api/aao/stats")
async def aao_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM aao_decisions"))
    indexed = await database.fetch_val(
        q("SELECT COUNT(*) FROM aao_decisions WHERE text_extracted = TRUE"))
    outcomes = await database.fetch_all(q(
        "SELECT outcome, COUNT(*) AS cnt FROM aao_decisions GROUP BY outcome ORDER BY cnt DESC"))
    top_forms = await database.fetch_all(q("""
        SELECT form_type, COUNT(*) AS cnt FROM aao_decisions
        WHERE form_type IS NOT NULL
        GROUP BY form_type ORDER BY cnt DESC LIMIT 10"""))
    return {
        "total_decisions": total,
        "indexed_decisions": indexed,
        "outcomes": [dict(r) for r in outcomes],
        "top_forms": [dict(r) for r in top_forms],
    }


# ── Regulations ───────────────────────────────────────────────────────────────

@app.get("/api/regulations-docs")
async def list_regulations_docs():
    rows = await database.fetch_all(q("""
        SELECT id, title, cfr_title, cfr_part, part_name, agency,
               as_of_date::text, page_count,
               jsonb_array_length(sections) AS section_count
        FROM regulations_docs
        ORDER BY cfr_title NULLS LAST, cfr_part"""))
    return [dict(r) for r in rows]


@app.get("/api/regulations-docs/search")
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


@app.get("/api/regulations-docs/{doc_id}")
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


@app.get("/api/regulations-docs/{doc_id}/pdf")
async def serve_regulation_pdf(doc_id: int):
    row = await database.fetch_one(
        q("SELECT pdf_path FROM regulations_docs WHERE id = :id", id=doc_id))
    if not row or not os.path.exists(row["pdf_path"]):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(row["pdf_path"], media_type="application/pdf")


@app.get("/api/regulations-docs/stats/summary")
async def regulations_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM regulations_docs"))
    pages = await database.fetch_val(q("SELECT COALESCE(SUM(page_count),0) FROM regulations_docs"))
    by_agency = await database.fetch_all(q("""
        SELECT agency, COUNT(*) as parts, SUM(page_count) as pages
        FROM regulations_docs GROUP BY agency ORDER BY parts DESC"""))
    return {"total_parts": total, "total_pages": pages,
            "by_agency": [dict(r) for r in by_agency]}


# ── Policy Manuals ────────────────────────────────────────────────────────────

@app.get("/api/policy-docs")
async def list_policy_docs():
    rows = await database.fetch_all(q("""
        SELECT id, source, title, section, subject, as_of_date::text, page_count
        FROM policy_docs ORDER BY source, section"""))
    return [dict(r) for r in rows]

@app.get("/api/policy-docs/search")
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

@app.get("/api/policy-docs/{doc_id}")
async def get_policy_doc(doc_id: int):
    row = await database.fetch_one(q("SELECT * FROM policy_docs WHERE id = :id", id=doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    d["as_of_date"] = str(d["as_of_date"]) if d["as_of_date"] else None
    d["ingested_at"] = str(d["ingested_at"]) if d["ingested_at"] else None
    d["search_vector"] = None
    return d

@app.get("/api/policy-docs/{doc_id}/pdf")
async def serve_policy_pdf(doc_id: int):
    row = await database.fetch_one(q("SELECT pdf_path, source FROM policy_docs WHERE id = :id", id=doc_id))
    if not row or not os.path.exists(row["pdf_path"]):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(row["pdf_path"], media_type="application/pdf")

@app.get("/api/policy-docs/stats/summary")
async def policy_stats():
    total = await database.fetch_val(q("SELECT COUNT(*) FROM policy_docs"))
    pages = await database.fetch_val(q("SELECT COALESCE(SUM(page_count),0) FROM policy_docs"))
    by_source = await database.fetch_all(q("""
        SELECT source, COUNT(*) as sections, SUM(page_count) as pages
        FROM policy_docs GROUP BY source ORDER BY source"""))
    return {"total_sections": total, "total_pages": pages,
            "by_source": [dict(r) for r in by_source]}


# ── Cross-corpus Search ───────────────────────────────────────────────────────

@app.get("/api/search-all")
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
	                 + CASE WHEN d.employer_name ILIKE :q_like THEN 0.8 ELSE 0 END
	                 + log(1 + COALESCE((SELECT COUNT(*) FROM citations c WHERE c.cited_id = d.id), 0)) * 0.25)
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

@app.get("/api/search/citation-graph")
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


# ── ETA-9141 PWD extraction ───────────────────────────────────────────────────

@app.post("/api/extract-pwd")
async def extract_pwd_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        result = extract_pwd_from_bytes(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    return result


@app.post("/api/extract-pwd-debug")
async def extract_pwd_debug(file: UploadFile = File(...)):
    """Returns parsed fields + raw page text for diagnosing extraction failures."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        result = extract_pwd_from_bytes(pdf_bytes)
        return {
            "parsed": result,
            "page_count": len(pages),
            "pages": {f"page_{i+1}": pages[i][:2000] for i in range(min(len(pages), 8))}
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Debug extraction failed: {e}")


# ── Generic PDF text extraction (no AI) ──────────────────────────────────────

@app.post("/api/extract-text")
async def extract_text_endpoint(file: UploadFile = File(...)):
    """Extract all text from a PDF using pdfplumber. No AI involved."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n\n".join(p for p in pages if p.strip())
        if not text.strip():
            raise HTTPException(status_code=422, detail="No text could be extracted from this PDF.")
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")


async def _mark_extraction_failure(corpus: str, decision_id: int, error: str) -> None:
    table = "decisions" if corpus == "balca" else "aao_decisions"
    await database.execute(
        text(f"""
            UPDATE {table}
            SET extraction_status = 'failed',
                extraction_error = :error,
                extraction_attempts = COALESCE(extraction_attempts, 0) + 1,
                extracted_at = NOW(),
                text_extracted = FALSE
            WHERE id = :id
        """).bindparams(id=decision_id, error=error[:2000])
    )


async def _update_extracted_text(corpus: str, decision_id: int, extracted: dict[str, Any]) -> None:
    table = "decisions" if corpus == "balca" else "aao_decisions"
    await database.execute(
        text(f"""
            UPDATE {table}
            SET full_text = :full_text,
                text_extracted = TRUE,
                extraction_status = :status,
                extraction_error = NULL,
                extraction_attempts = COALESCE(extraction_attempts, 0) + 1,
                extracted_at = NOW(),
                extraction_page_count = :page_count,
                extraction_char_count = :char_count,
                extraction_quality = :quality
            WHERE id = :id
        """).bindparams(
            id=decision_id,
            full_text=extracted["full_text"],
            status="extracted" if extracted["full_text"].strip() else "empty",
            page_count=extracted["page_count"],
            char_count=extracted["char_count"],
            quality=extracted["quality"],
        )
    )


async def _extraction_targets(corpus: str, status_filter: str, limit: int, ids: list[int] | None):
    if corpus == "balca":
        table = "decisions"
        path_expr = "filename"
    elif corpus == "aao":
        table = "aao_decisions"
        path_expr = "pdf_path"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")

    bind: dict[str, Any] = {"limit": limit}
    conditions = []
    if ids:
        conditions.append("id = ANY(:ids)")
        bind["ids"] = ids
    elif status_filter == "repairable":
        conditions.append("""(
            extraction_status IN ('unknown', 'failed', 'empty', 'low_text', 'not_found')
            OR text_extracted IS NOT TRUE
            OR full_text IS NULL
            OR full_text = ''
        )""")
    elif status_filter != "all":
        conditions.append("extraction_status = :status")
        bind["status"] = status_filter

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return await database.fetch_all(
        text(f"""
            SELECT id, {path_expr} AS pdf_ref, extraction_status, extraction_attempts
            FROM {table}
            {where}
            ORDER BY COALESCE(extraction_attempts, 0), id
            LIMIT :limit
        """).bindparams(**bind)
    )


@app.get("/api/extraction/status")
async def extraction_status(corpus: str = Query(default="balca")):
    if corpus == "balca":
        table = "decisions"
    elif corpus == "aao":
        table = "aao_decisions"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    rows = await database.fetch_all(text(f"""
        SELECT COALESCE(extraction_status, 'unknown') AS status,
               COUNT(*) AS count,
               SUM(CASE WHEN text_extracted IS TRUE THEN 1 ELSE 0 END) AS extracted_count,
               SUM(CASE WHEN full_text IS NULL OR full_text = '' THEN 1 ELSE 0 END) AS empty_text_count
        FROM {table}
        GROUP BY COALESCE(extraction_status, 'unknown')
        ORDER BY count DESC
    """))
    return {"corpus": corpus, "statuses": [dict(row) for row in rows]}


@app.get("/api/extraction/failures")
async def extraction_failures(
    corpus: str = Query(default="balca"),
    limit: int = Query(default=50, ge=1, le=500),
):
    if corpus == "balca":
        table = "decisions"
        label = "case_number"
    elif corpus == "aao":
        table = "aao_decisions"
        label = "COALESCE(title, filename)"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    rows = await database.fetch_all(text(f"""
        SELECT id, {label} AS label, extraction_status, extraction_error,
               extraction_attempts, extracted_at::text, extraction_char_count,
               extraction_page_count, extraction_quality
        FROM {table}
        WHERE extraction_status IN ('failed', 'empty', 'low_text', 'not_found')
           OR text_extracted IS NOT TRUE
           OR full_text IS NULL
           OR full_text = ''
        ORDER BY extracted_at DESC NULLS LAST, id
        LIMIT :limit
    """).bindparams(limit=limit))
    return {"corpus": corpus, "results": [dict(row) for row in rows]}


@app.post("/api/extraction/retry")
async def retry_extraction(data: dict):
    corpus = data.get("corpus", "balca")
    status_filter = data.get("status", "repairable")
    limit = min(int(data.get("limit", 25)), 200)
    ids = data.get("ids")
    ids = [int(i) for i in ids] if isinstance(ids, list) else None
    targets = await _extraction_targets(corpus, status_filter, limit, ids)
    results = []
    for row in targets:
        decision_id = row["id"]
        pdf_ref = row["pdf_ref"]
        path = _balca_pdf_path(pdf_ref) if corpus == "balca" else pdf_ref
        if not path or not os.path.exists(path):
            error = f"PDF not found: {path or pdf_ref or 'missing path'}"
            await _mark_extraction_failure(corpus, decision_id, error)
            results.append({"id": decision_id, "status": "not_found", "error": error})
            continue
        try:
            extracted = _extract_pdf_text(path)
            await _update_extracted_text(corpus, decision_id, extracted)
            results.append({
                "id": decision_id,
                "status": "extracted" if extracted["full_text"].strip() else "empty",
                "char_count": extracted["char_count"],
                "page_count": extracted["page_count"],
                "quality": extracted["quality"],
            })
        except Exception as exc:
            await _mark_extraction_failure(corpus, decision_id, str(exc))
            results.append({"id": decision_id, "status": "failed", "error": str(exc)})
    return {"corpus": corpus, "processed": len(results), "results": results}


@app.post("/api/extraction/mark")
async def mark_extraction_status(data: dict):
    corpus = data.get("corpus", "balca")
    decision_id = int(data["id"])
    status = data.get("status")
    note = data.get("note")
    if status not in {"needs_manual_review", "ignored", "not_found", "failed", "extracted"}:
        raise HTTPException(status_code=400, detail="Unsupported extraction status")
    table = "decisions" if corpus == "balca" else "aao_decisions" if corpus == "aao" else None
    if not table:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    await database.execute(
        text(f"""
            UPDATE {table}
            SET extraction_status = :status,
                extraction_error = :note,
                extracted_at = NOW()
            WHERE id = :id
        """).bindparams(id=decision_id, status=status, note=note)
    )
    return {"ok": True}


@app.post("/api/quality/refresh")
async def refresh_quality_signals(corpus: str = Query(default="balca")):
    if corpus == "balca":
        await database.execute(text("""
            UPDATE decisions d
            SET citation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    WHEN EXISTS (
                        SELECT 1 FROM citations c
                        WHERE c.citing_id = d.id AND c.cited_id IS NULL
                    ) THEN 'needs_review'
                    WHEN EXISTS (SELECT 1 FROM citations c WHERE c.citing_id = d.id) THEN 'ok'
                    ELSE 'no_citations'
                END,
                regulation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    WHEN EXISTS (
                        SELECT 1 FROM decision_regulations dr WHERE dr.decision_id = d.id
                    ) THEN 'ok'
                    ELSE 'no_regulations'
                END,
                search_quality_notes = CONCAT_WS('; ',
                    CASE
                        WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = ''
                        THEN 'missing extracted text'
                    END,
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM citations c
                            WHERE c.citing_id = d.id AND c.cited_id IS NULL
                        )
                        THEN 'has unresolved citations'
                    END,
                    CASE
                        WHEN NOT EXISTS (
                            SELECT 1 FROM decision_regulations dr WHERE dr.decision_id = d.id
                        )
                        THEN 'no linked regulations'
                    END
                )
        """))
        return await quality_summary(corpus=corpus)
    if corpus == "aao":
        await database.execute(text("""
            UPDATE aao_decisions d
            SET citation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    ELSE 'not_applicable'
                END,
                regulation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    WHEN COALESCE(d.regulation, '') != '' THEN 'ok'
                    ELSE 'no_regulation'
                END,
                search_quality_notes = CONCAT_WS('; ',
                    CASE
                        WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = ''
                        THEN 'missing extracted text'
                    END,
                    CASE WHEN COALESCE(d.regulation, '') = '' THEN 'no regulation label' END
                )
        """))
        return await quality_summary(corpus=corpus)
    raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")


@app.get("/api/quality/summary")
async def quality_summary(corpus: str = Query(default="balca")):
    if corpus == "balca":
        table = "decisions"
    elif corpus == "aao":
        table = "aao_decisions"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    citation_rows = await database.fetch_all(text(f"""
        SELECT COALESCE(citation_quality_status, 'unknown') AS status, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE(citation_quality_status, 'unknown')
        ORDER BY count DESC
    """))
    regulation_rows = await database.fetch_all(text(f"""
        SELECT COALESCE(regulation_quality_status, 'unknown') AS status, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE(regulation_quality_status, 'unknown')
        ORDER BY count DESC
    """))
    extraction_rows = await database.fetch_all(text(f"""
        SELECT COALESCE(extraction_status, 'unknown') AS status, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE(extraction_status, 'unknown')
        ORDER BY count DESC
    """))
    return {
        "corpus": corpus,
        "citation_quality": [dict(row) for row in citation_rows],
        "regulation_quality": [dict(row) for row in regulation_rows],
        "extraction_quality": [dict(row) for row in extraction_rows],
    }


@app.get("/api/quality/issues")
async def quality_issues(
    corpus: str = Query(default="balca"),
    limit: int = Query(default=50, ge=1, le=500),
):
    if corpus == "balca":
        table = "decisions"
        label = "case_number"
    elif corpus == "aao":
        table = "aao_decisions"
        label = "COALESCE(title, filename)"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    rows = await database.fetch_all(text(f"""
        SELECT id, {label} AS label, extraction_status, citation_quality_status,
               regulation_quality_status, search_quality_notes
        FROM {table}
        WHERE COALESCE(extraction_status, 'unknown') NOT IN ('extracted', 'ignored')
           OR COALESCE(citation_quality_status, 'unknown') IN ('unknown', 'not_ready', 'needs_review')
           OR COALESCE(regulation_quality_status, 'unknown') IN ('unknown', 'not_ready')
        ORDER BY id
        LIMIT :limit
    """).bindparams(limit=limit))
    return {"corpus": corpus, "results": [dict(row) for row in rows]}


# ── Experience verification letter extraction (no AI) ────────────────────────

@app.post("/api/extract-experience-letter")
async def extract_experience_letter_endpoint(file: UploadFile = File(...)):
    """Parse an experience verification letter PDF using pdfplumber + regex."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        result = extract_letter_from_bytes(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    return result


# ── INA — Immigration and Nationality Act ────────────────────────────────────

@app.get("/api/ina/sections")
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


@app.get("/api/ina/sections/{section_id}")
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


@app.get("/api/ina/search")
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


# ── Anthropic API proxy ───────────────────────────────────────────────────────
# Keeps the API key server-side; frontend posts to /api/claude instead of
# calling Anthropic directly.

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

@app.post("/api/claude")
async def claude_proxy(request: Request):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured on server")
    body = await request.json()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
    return resp.json()


# ── RAG / Ask endpoint ────────────────────────────────────────────────────────

import json as _json

OLLAMA_URL     = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:latest")
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

@app.post("/api/ask")
async def ask(request: Request):
    """
    RAG Q&A endpoint. Streams a cited answer using top-k retrieved chunks.

    Request body:
      {
        "question": "...",
        "corpus_filter": ["balca","aao","regulation","policy"],  // optional
        "top_k": 12,   // optional, default 12
        "stream": true // optional, default true
      }

    Response (streaming): newline-delimited JSON tokens:
      {"type": "sources", "sources": [...]}   // first message: retrieved sources
      {"type": "token",   "text": "..."}      // streamed answer tokens
      {"type": "done"}                        // final message
    """
    body       = await request.json()
    question   = body.get("question", "").strip()
    corpus_filter = body.get("corpus_filter", [])  # empty = all corpora
    top_k      = min(int(body.get("top_k", 12)).bindparams(**20))
    do_stream  = body.get("stream", True)

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # 1. Embed the question via Ollama
    try:
        q_vec = await embed_query(question)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Embedding failed (is Ollama running?): {e}")
    q_vec_str = "[" + ",".join(f"{v:.6f}" for v in q_vec) + "]"

    # 2. Retrieve top-k chunks by cosine similarity
    corpus_where = ""
    bind = {"vec": q_vec_str, "k": top_k}
    if corpus_filter:
        placeholders = ", ".join(f":c{i}" for i in range(len(corpus_filter)))
        corpus_where = f"WHERE corpus IN ({placeholders})"
        for i, c in enumerate(corpus_filter):
            bind[f"c{i}"] = c

    chunks = await database.fetch_all(
        text(f"""
            SELECT id, corpus, source_id, source_label, source_date,
                   source_outcome, chunk_index, chunk_text, cfr_citation, form_type,
                   1 - (embedding <=> :vec::vector) AS similarity
            FROM rag_chunks
            {corpus_where}
            ORDER BY embedding <=> :vec::vector
            LIMIT :k
        """).bindparams(**bind)
    )

    if not chunks:
        async def no_results():
            yield json.dumps({"type": "sources", "sources": []}) + "\n"
            yield json.dumps({"type": "token", "text": "I could not find relevant material in the database for that question."}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        return StreamingResponse(no_results(), media_type="text/plain")

    # 3. Build context block for the LLM
    sources = []
    context_parts = []
    seen = set()

    for i, chunk in enumerate(chunks):
        src_key = (chunk["corpus"], chunk["source_id"])
        is_new_source = src_key not in seen
        seen.add(src_key)

        label = CORPUS_LABELS.get(chunk["corpus"], chunk["corpus"])
        ref_num = i + 1

        # Build source object for the frontend
        source = {
            "ref":          ref_num,
            "corpus":       chunk["corpus"],
            "source_id":    chunk["source_id"],
            "source_label": chunk["source_label"],
            "source_date":  chunk["source_date"],
            "outcome":      chunk["source_outcome"],
            "cfr_citation": chunk["cfr_citation"],
            "form_type":    chunk["form_type"],
            "similarity":   round(float(chunk["similarity"]), 3),
            "is_new_source": is_new_source,
        }
        sources.append(source)

        # Build context snippet for the prompt
        meta_parts = [f"[{ref_num}] {label}: {chunk['source_label']}"]
        if chunk["source_date"]:
            meta_parts.append(f"Date: {chunk['source_date']}")
        if chunk["source_outcome"]:
            meta_parts.append(f"Outcome: {chunk['source_outcome']}")
        if chunk["cfr_citation"]:
            meta_parts.append(f"Citation: {chunk['cfr_citation']}")

        context_parts.append("\n".join(meta_parts) + "\n" + chunk["chunk_text"])

    context_block = "\n\n---\n\n".join(context_parts)

    # 4. Call Claude to synthesize a cited answer
    system_prompt = """You are a legal research assistant specializing in U.S. immigration law.
You are given retrieved excerpts from BALCA decisions, AAO decisions, federal regulations (CFR), and USCIS/FAM policy manuals.
Answer the question accurately and concisely using ONLY the provided sources.

Rules:
- Cite every factual claim with the source reference number in brackets, e.g. [3] or [1][4].
- When citing a regulation, include the CFR citation if available (e.g., 20 CFR § 656.17).
- When citing a case decision, include the case label and outcome where relevant.
- If sources conflict, note the conflict and explain which is more authoritative (regulations > policy > case decisions).
- If the sources do not contain enough information to answer, say so clearly — do not speculate.
- Write in plain legal English. Be precise but readable.
- Structure longer answers with short paragraphs. Do not use bullet points unless listing distinct requirements."""

    user_prompt = f"""Sources:

{context_block}

---

Question: {question}

Answer (cite sources with [N] notation):"""

    # 5. Stream the response
    async def generate():
        # First, emit the sources metadata
        yield json.dumps({"type": "sources", "sources": sources}) + "\n"

        # Then stream the answer tokens
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            async with http_client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1500,
                    "stream": True,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]" or not data_str:
                        continue
                    try:
                        event = json.loads(data_str)
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield json.dumps({"type": "token", "text": delta["text"]}) + "\n"
                    except Exception:
                        continue

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(generate(), media_type="text/plain")


@app.get("/api/ask/stats")
async def ask_stats():
    """Returns stats about the RAG corpus for the UI."""
    rows = await database.fetch_all(text("""
        SELECT corpus,
               COUNT(*) AS chunks,
               COUNT(DISTINCT source_id) AS sources,
               COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
        FROM rag_chunks
        GROUP BY corpus ORDER BY corpus
    """))
    total_chunks   = sum(r["chunks"] for r in rows)
    total_embedded = sum(r["embedded"] for r in rows)
    return {
        "total_chunks":   total_chunks,
        "total_embedded": total_embedded,
        "ready":          total_embedded > 0,
        "by_corpus": [dict(r) for r in rows],
    }


# ══════════════════════════════════════════════════════════════════════════════
# OFLC Disclosure Data Endpoints
# PERM, LCA (H-1B/H-1B1/E-3), and Prevailing Wage — FY2020–FY2026
# ══════════════════════════════════════════════════════════════════════════════

def _oflc_where(clauses, params, col, val, op="="):
    """Append a filter clause and bind its param."""
    if val is None:
        return
    key = col.replace(".", "_").replace(" ", "_")
    if op == "ilike":
        clauses.append(f"{col} ILIKE :{key}")
        params[key] = f"%{val}%"
    else:
        clauses.append(f"{col} {op} :{key}")
        params[key] = val


# ── PERM ──────────────────────────────────────────────────────────────────────

@app.get("/api/oflc/perm")
async def oflc_perm(
    case_number:    Optional[str]   = Query(None),
    case_status:    Optional[str]   = Query(None, description="Certified, Denied, Withdrawn…"),
    employer_name:  Optional[str]   = Query(None, description="Partial match"),
    employer_fein:  Optional[str]   = Query(None),
    employer_state: Optional[str]   = Query(None, description="2-letter state code"),
    atty_law_firm:  Optional[str]   = Query(None, description="Partial match"),
    soc_code:       Optional[str]   = Query(None, description="e.g. 15-1252"),
    naics:          Optional[str]   = Query(None, description="NAICS prefix"),
    fiscal_year:    Optional[str]   = Query(None, description="e.g. FY2024"),
    decision_from:  Optional[str]   = Query(None, description="YYYY-MM-DD"),
    decision_to:    Optional[str]   = Query(None, description="YYYY-MM-DD"),
    wage_min:       Optional[float] = Query(None),
    limit:          int = Query(50, le=500),
    offset:         int = Query(0),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "case_number",    case_number)
    _oflc_where(clauses, params, "case_status",    case_status)
    _oflc_where(clauses, params, "employer_name",  employer_name,  "ilike")
    _oflc_where(clauses, params, "employer_fein",  employer_fein)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "atty_law_firm",  atty_law_firm,  "ilike")
    _oflc_where(clauses, params, "soc_code",       soc_code)
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    if naics:
        clauses.append("employer_naics LIKE :naics")
        params["naics"] = f"{naics}%"
    if decision_from:
        clauses.append("decision_date >= :decision_from")
        params["decision_from"] = decision_from
    if decision_to:
        clauses.append("decision_date <= :decision_to")
        params["decision_to"] = decision_to
    if wage_min is not None:
        clauses.append("wage_from >= :wage_min")
        params["wage_min"] = wage_min
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update({"limit": limit, "offset": offset})
    sql = f"""
        SELECT case_number, case_status, fiscal_year,
               received_date, decision_date, occupation_type,
               employer_name, employer_state, employer_city, employer_fein,
               employer_naics, atty_law_firm,
               job_title, soc_code, soc_title,
               wage_from, wage_to, wage_per,
               worksite_city, worksite_state
        FROM oflc_perm {where}
        ORDER BY decision_date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]

@app.get("/api/oflc/perm/{case_number}")
async def oflc_perm_detail(case_number: str):
    rows = await database.fetch_all(
        text("SELECT * FROM oflc_perm WHERE case_number = :cn ORDER BY fiscal_year DESC").bindparams(cn=case_number)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found")
    return [dict(r) for r in rows]


@app.get("/api/oflc/perm/stats/summary")
async def oflc_perm_stats(
    fiscal_year:    Optional[str] = Query(None),
    employer_state: Optional[str] = Query(None),
    soc_code:       Optional[str] = Query(None),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "soc_code",       soc_code)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT fiscal_year, case_status,
               COUNT(*)                                              AS total,
               AVG(wage_from)                                        AS avg_wage_from,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY wage_from) AS median_wage,
               COUNT(DISTINCT employer_fein)                         AS unique_employers,
               COUNT(DISTINCT atty_law_firm)                         AS unique_firms,
               COUNT(DISTINCT soc_code)                              AS unique_soc_codes
        FROM oflc_perm {where}
        GROUP BY fiscal_year, case_status
        ORDER BY fiscal_year DESC, total DESC
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]


# ── LCA ───────────────────────────────────────────────────────────────────────

@app.get("/api/oflc/lca")
async def oflc_lca(
    case_number:    Optional[str]   = Query(None),
    case_status:    Optional[str]   = Query(None),
    visa_class:     Optional[str]   = Query(None, description="H-1B, H-1B1, E-3"),
    employer_name:  Optional[str]   = Query(None, description="Partial match"),
    employer_fein:  Optional[str]   = Query(None),
    employer_state: Optional[str]   = Query(None),
    law_firm_name:  Optional[str]   = Query(None, description="Partial match"),
    soc_code:       Optional[str]   = Query(None),
    naics:          Optional[str]   = Query(None),
    fiscal_year:    Optional[str]   = Query(None),
    pw_wage_level:  Optional[str]   = Query(None, description="I, II, III, IV"),
    h1b_dependent:  Optional[str]   = Query(None, description="Y or N"),
    decision_from:  Optional[str]   = Query(None),
    decision_to:    Optional[str]   = Query(None),
    wage_min:       Optional[float] = Query(None),
    limit:          int = Query(50, le=500),
    offset:         int = Query(0),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "case_number",    case_number)
    _oflc_where(clauses, params, "case_status",    case_status)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_name",  employer_name,  "ilike")
    _oflc_where(clauses, params, "employer_fein",  employer_fein)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "law_firm_name",  law_firm_name,  "ilike")
    _oflc_where(clauses, params, "soc_code",       soc_code)
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    _oflc_where(clauses, params, "h1b_dependent",  h1b_dependent)
    if naics:
        clauses.append("naics_code LIKE :naics")
        params["naics"] = f"{naics}%"
    if decision_from:
        clauses.append("decision_date >= :decision_from")
        params["decision_from"] = decision_from
    if decision_to:
        clauses.append("decision_date <= :decision_to")
        params["decision_to"] = decision_to
    if wage_min is not None:
        clauses.append("wage_from >= :wage_min")
        params["wage_min"] = wage_min
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update({"limit": limit, "offset": offset})
    sql = f"""
        SELECT case_number, case_status, visa_class, fiscal_year,
               received_date, decision_date, begin_date, end_date,
               employer_name, employer_state, employer_city, employer_fein,
               naics_code, law_firm_name,
               job_title, soc_code, soc_title,
               wage_from, wage_to, wage_unit,
               prevailing_wage, pw_unit, pw_wage_level,
               worksite_city, worksite_state,
               h1b_dependent, willful_violator, total_worker_positions
        FROM oflc_lca {where}
        ORDER BY decision_date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]

@app.get("/api/oflc/lca/{case_number}")
async def oflc_lca_detail(case_number: str):
    rows = await database.fetch_all(
        text("SELECT * FROM oflc_lca WHERE case_number = :cn ORDER BY fiscal_year DESC").bindparams(cn=case_number)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found")
    return [dict(r) for r in rows]


@app.get("/api/oflc/lca/stats/summary")
async def oflc_lca_stats(
    fiscal_year:    Optional[str] = Query(None),
    visa_class:     Optional[str] = Query(None),
    employer_state: Optional[str] = Query(None),
    pw_wage_level:  Optional[str] = Query(None),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT fiscal_year, visa_class, case_status, pw_wage_level,
               COUNT(*)                                              AS total,
               SUM(total_worker_positions)                           AS total_positions,
               AVG(wage_from)                                        AS avg_wage,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY wage_from) AS median_wage,
               AVG(prevailing_wage)                                  AS avg_prevailing_wage,
               COUNT(DISTINCT employer_fein)                         AS unique_employers,
               COUNT(DISTINCT soc_code)                              AS unique_soc_codes
        FROM oflc_lca {where}
        GROUP BY fiscal_year, visa_class, case_status, pw_wage_level
        ORDER BY fiscal_year DESC, total DESC
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]


# ── PW ────────────────────────────────────────────────────────────────────────

@app.get("/api/oflc/pw")
async def oflc_pw(
    case_number:       Optional[str]   = Query(None),
    case_status:       Optional[str]   = Query(None),
    visa_class:        Optional[str]   = Query(None),
    employer_name:     Optional[str]   = Query(None, description="Partial match"),
    employer_fein:     Optional[str]   = Query(None),
    employer_state:    Optional[str]   = Query(None),
    law_firm_name:     Optional[str]   = Query(None, description="Partial match"),
    soc_code:          Optional[str]   = Query(None),
    naics:             Optional[str]   = Query(None),
    fiscal_year:       Optional[str]   = Query(None),
    pw_wage_level:     Optional[str]   = Query(None),
    bls_area:          Optional[str]   = Query(None, description="Partial match"),
    wage_source:       Optional[str]   = Query(None),
    determination_from: Optional[str]  = Query(None),
    determination_to:   Optional[str]  = Query(None),
    limit:             int = Query(50, le=500),
    offset:            int = Query(0),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "case_number",    case_number)
    _oflc_where(clauses, params, "case_status",    case_status)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_name",  employer_name,  "ilike")
    _oflc_where(clauses, params, "employer_fein",  employer_fein)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "law_firm_name",  law_firm_name,  "ilike")
    _oflc_where(clauses, params, "soc_code",       soc_code)
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    _oflc_where(clauses, params, "bls_area",       bls_area,       "ilike")
    _oflc_where(clauses, params, "wage_source",    wage_source)
    if naics:
        clauses.append("naics_code LIKE :naics")
        params["naics"] = f"{naics}%"
    if determination_from:
        clauses.append("determination_date >= :determination_from")
        params["determination_from"] = determination_from
    if determination_to:
        clauses.append("determination_date <= :determination_to")
        params["determination_to"] = determination_to
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update({"limit": limit, "offset": offset})
    sql = f"""
        SELECT case_number, case_status, visa_class, fiscal_year,
               received_date, determination_date,
               employer_name, employer_state, employer_city, employer_fein,
               naics_code, law_firm_name,
               job_title, soc_code, soc_title,
               pwd_wage_rate, pwd_unit, pw_wage_level,
               wage_source, bls_area, pwd_wage_expiration_date,
               worksite_city, worksite_state
        FROM oflc_pw {where}
        ORDER BY determination_date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]

@app.get("/api/oflc/pw/{case_number}")
async def oflc_pw_detail(case_number: str):
    rows = await database.fetch_all(
        text("SELECT * FROM oflc_pw WHERE case_number = :cn ORDER BY fiscal_year DESC").bindparams(cn=case_number)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found")
    return [dict(r) for r in rows]


@app.get("/api/oflc/pw/stats/summary")
async def oflc_pw_stats(
    fiscal_year:    Optional[str] = Query(None),
    visa_class:     Optional[str] = Query(None),
    employer_state: Optional[str] = Query(None),
    pw_wage_level:  Optional[str] = Query(None),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT fiscal_year, visa_class, case_status, pw_wage_level, wage_source,
               COUNT(*)                                                   AS total,
               AVG(pwd_wage_rate)                                         AS avg_pwd_wage,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pwd_wage_rate) AS median_pwd_wage,
               COUNT(DISTINCT employer_fein)                              AS unique_employers,
               COUNT(DISTINCT soc_code)                                   AS unique_soc_codes,
               COUNT(DISTINCT bls_area)                                   AS unique_bls_areas
        FROM oflc_pw {where}
        GROUP BY fiscal_year, visa_class, case_status, pw_wage_level, wage_source
        ORDER BY fiscal_year DESC, total DESC
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]


# ── Cross-program employer lookup ─────────────────────────────────────────────

@app.get("/api/oflc/employer/{fein}")
async def oflc_employer(fein: str):
    """Cross-program lookup by FEIN — PERM, LCA, and PW activity."""
    p = {"fein": fein}
    perm_rows = await database.fetch_all(text("""
        SELECT 'perm' AS program, case_number, case_status, fiscal_year,
               decision_date AS date, job_title, soc_code,
               wage_from AS wage, wage_per AS wage_unit,
               worksite_state, atty_law_firm AS firm
        FROM oflc_perm WHERE employer_fein = :fein
        ORDER BY decision_date DESC NULLS LAST LIMIT 100
    """).bindparams(**p))
    lca_rows = await database.fetch_all(text("""
        SELECT 'lca' AS program, case_number, case_status, fiscal_year,
               decision_date AS date, job_title, soc_code,
               wage_from AS wage, wage_unit,
               worksite_state, law_firm_name AS firm
        FROM oflc_lca WHERE employer_fein = :fein
        ORDER BY decision_date DESC NULLS LAST LIMIT 100
    """).bindparams(**p))
    pw_rows = await database.fetch_all(text("""
        SELECT 'pw' AS program, case_number, case_status, fiscal_year,
               determination_date AS date, job_title, soc_code,
               pwd_wage_rate AS wage, pwd_unit AS wage_unit,
               worksite_state, law_firm_name AS firm
        FROM oflc_pw WHERE employer_fein = :fein
        ORDER BY determination_date DESC NULLS LAST LIMIT 100
    """).bindparams(**p))
    if not perm_rows and not lca_rows and not pw_rows:
        raise HTTPException(status_code=404, detail="No records found for FEIN")
    name_row = await database.fetch_one(text("""
        SELECT employer_name FROM (
            SELECT employer_name FROM oflc_perm WHERE employer_fein = :fein AND employer_name IS NOT NULL
            UNION ALL
            SELECT employer_name FROM oflc_lca  WHERE employer_fein = :fein AND employer_name IS NOT NULL
            UNION ALL
            SELECT employer_name FROM oflc_pw   WHERE employer_fein = :fein AND employer_name IS NOT NULL
        ) t LIMIT 1
    """).bindparams(**p))
    return {
        "fein":          fein,
        "employer_name": name_row["employer_name"] if name_row else None,
        "summary":       {"perm_total": len(perm_rows), "lca_total": len(lca_rows), "pw_total": len(pw_rows)},
        "perm":          [dict(r) for r in perm_rows],
        "lca":           [dict(r) for r in lca_rows],
        "pw":            [dict(r) for r in pw_rows],
    }


# ── Cross-program firm lookup ─────────────────────────────────────────────────

@app.get("/api/oflc/firm")
async def oflc_firm(
    name:        str           = Query(..., description="Law firm name — partial match"),
    fiscal_year: Optional[str] = Query(None),
    program:     Optional[str] = Query(None, description="perm, lca, or pw"),
):
    params = {"name": f"%{name}%"}
    fy_clause = "AND fiscal_year = :fy" if fiscal_year else ""
    if fiscal_year:
        params["fy"] = fiscal_year
    results = {}
    if program in (None, "perm"):
        results["perm"] = [dict(r) for r in await database.fetch_all(text(f"""
            SELECT fiscal_year, case_status, COUNT(*) AS total, AVG(wage_from) AS avg_wage
            FROM oflc_perm WHERE atty_law_firm ILIKE :name {fy_clause}
            GROUP BY fiscal_year, case_status ORDER BY fiscal_year DESC
        """).bindparams(**params))]
    if program in (None, "lca"):
        results["lca"] = [dict(r) for r in await database.fetch_all(text(f"""
            SELECT fiscal_year, visa_class, case_status,
                   COUNT(*) AS total, SUM(total_worker_positions) AS total_positions,
                   AVG(wage_from) AS avg_wage
            FROM oflc_lca WHERE law_firm_name ILIKE :name {fy_clause}
            GROUP BY fiscal_year, visa_class, case_status ORDER BY fiscal_year DESC
        """).bindparams(**params))]
    if program in (None, "pw"):
        results["pw"] = [dict(r) for r in await database.fetch_all(text(f"""
            SELECT fiscal_year, visa_class, case_status,
                   COUNT(*) AS total, AVG(pwd_wage_rate) AS avg_pwd_wage
            FROM oflc_pw WHERE law_firm_name ILIKE :name {fy_clause}
            GROUP BY fiscal_year, visa_class, case_status ORDER BY fiscal_year DESC
        """).bindparams(**params))]
    return results


# ── Overall OFLC stats ────────────────────────────────────────────────────────

@app.get("/api/oflc/stats")
async def oflc_stats():
    """Row counts and coverage for all three OFLC tables."""
    rows = await database.fetch_all(text("""
        SELECT 'perm' AS program, COUNT(*) AS total_rows,
               COUNT(DISTINCT employer_fein) AS unique_employers,
               MIN(fiscal_year) AS earliest_fy, MAX(fiscal_year) AS latest_fy,
               COUNT(DISTINCT atty_law_firm) AS unique_firms
        FROM oflc_perm
        UNION ALL
        SELECT 'lca', COUNT(*), COUNT(DISTINCT employer_fein),
               MIN(fiscal_year), MAX(fiscal_year), COUNT(DISTINCT law_firm_name)
        FROM oflc_lca
        UNION ALL
        SELECT 'pw', COUNT(*), COUNT(DISTINCT employer_fein),
               MIN(fiscal_year), MAX(fiscal_year), COUNT(DISTINCT law_firm_name)
        FROM oflc_pw
    """))
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Visa Bulletin Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/visa-bulletin/latest")
async def visa_bulletin_latest(
    category_type: Optional[str] = Query(None, description="employment or family"),
    date_type:     Optional[str] = Query(None, description="final_action or dates_for_filing"),
):
    """Most recent bulletin's priority dates."""
    clauses, params = ["bulletin_date = (SELECT MAX(bulletin_date) FROM visa_bulletin)"], {}
    if category_type:
        clauses.append("category_type = :category_type")
        params["category_type"] = category_type
    if date_type:
        clauses.append("date_type = :date_type")
        params["date_type"] = date_type
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title, category_type, date_type,
               preference, chargeability, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin {where}
        ORDER BY category_type, date_type, preference, chargeability
    """).bindparams(**params))
    return [dict(r) for r in rows]


@app.get("/api/visa-bulletin/{year}/{month}")
async def visa_bulletin_month(
    year:          int,
    month:         int,
    category_type: Optional[str] = Query(None),
    date_type:     Optional[str] = Query(None),
):
    """Priority dates for a specific bulletin month."""
    try:
        bdate = _date(year, month, 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year/month")
    clauses = ["bulletin_date = :bdate"]
    params: dict = {"bdate": bdate}
    if category_type:
        clauses.append("category_type = :category_type")
        params["category_type"] = category_type
    if date_type:
        clauses.append("date_type = :date_type")
        params["date_type"] = date_type
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title, category_type, date_type,
               preference, chargeability, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin {where}
        ORDER BY category_type, date_type, preference, chargeability
    """).bindparams(**params))
    if not rows:
        raise HTTPException(status_code=404, detail=f"No bulletin found for {year}-{month:02d}")
    return [dict(r) for r in rows]


@app.get("/api/visa-bulletin/history")
async def visa_bulletin_history(
    preference:    str            = Query(..., description="e.g. EB2, EB3, F1"),
    chargeability: str            = Query(..., description="ALL, CHINA, INDIA, MEXICO, PHILIPPINES"),
    date_type:     Optional[str]  = Query("final_action", description="final_action or dates_for_filing"),
    category_type: Optional[str]  = Query(None),
    from_year:     Optional[int]  = Query(None),
    to_year:       Optional[int]  = Query(None),
):
    """
    Priority date history for a preference/chargeability combination over time.
    Useful for charting movement trends.
    """
    clauses = ["preference = :preference", "chargeability = :chargeability"]
    params: dict = {"preference": preference.upper(), "chargeability": chargeability.upper()}
    if date_type:
        clauses.append("date_type = :date_type")
        params["date_type"] = date_type
    if category_type:
        clauses.append("category_type = :category_type")
        params["category_type"] = category_type
    if from_year:
        clauses.append("bulletin_date >= :from_date")
        params["from_date"] = date(from_year, 1, 1)
    if to_year:
        clauses.append("bulletin_date <= :to_date")
        params["to_date"] = date(to_year, 12, 31)
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title, preference, chargeability,
               date_type, category_type,
               priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin {where}
        ORDER BY bulletin_date ASC
    """).bindparams(**params))
    if not rows:
        raise HTTPException(status_code=404, detail="No history found for given parameters")

    # Compute month-over-month movement in days
    result = []
    prev_pd = None
    for r in rows:
        d = dict(r)
        movement_days = None
        if d["priority_date"] and prev_pd:
            movement_days = (d["priority_date"] - prev_pd).days
        d["movement_days"] = movement_days
        prev_pd = d["priority_date"] if not d["is_current"] else prev_pd
        result.append(d)
    return result


@app.get("/api/visa-bulletin/backlog")
async def visa_bulletin_backlog(
    preference:    str           = Query(..., description="e.g. EB2, EB3"),
    chargeability: str           = Query(..., description="INDIA, CHINA, ALL etc."),
    date_type:     Optional[str] = Query("final_action"),
):
    """
    Current backlog estimate: how far back the current priority date is
    from today, and average monthly advancement over the past 12 months.
    """
    params = {
        "preference":    preference.upper(),
        "chargeability": chargeability.upper(),
        "date_type":     date_type or "final_action",
    }

    # Latest entry
    current = await database.fetch_one(text("""
        SELECT bulletin_date, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin
        WHERE preference = :preference
          AND chargeability = :chargeability
          AND date_type = :date_type
        ORDER BY bulletin_date DESC LIMIT 1
    """).bindparams(**params))

    if not current:
        raise HTTPException(status_code=404, detail="No data found")

    # Last 13 months for advancement calc
    history = await database.fetch_all(text("""
        SELECT bulletin_date, priority_date, is_current, is_unavailable
        FROM visa_bulletin
        WHERE preference = :preference
          AND chargeability = :chargeability
          AND date_type = :date_type
          AND priority_date IS NOT NULL
          AND is_current = FALSE
        ORDER BY bulletin_date DESC LIMIT 13
    """).bindparams(**params))

    avg_monthly_days = None
    if len(history) >= 2:
        movements = []
        for i in range(len(history) - 1):
            delta = (history[i]["priority_date"] - history[i+1]["priority_date"]).days
            movements.append(delta)
        avg_monthly_days = sum(movements) / len(movements) if movements else None

    backlog_days = None
    years_to_wait = None
    if current["priority_date"]:
        backlog_days = (_date.today() - current["priority_date"]).days
        if avg_monthly_days and avg_monthly_days > 0:
            months_to_wait = backlog_days / avg_monthly_days
            years_to_wait  = round(months_to_wait / 12, 1)

    return {
        "preference":         preference.upper(),
        "chargeability":      chargeability.upper(),
        "date_type":          date_type,
        "latest_bulletin":    current["bulletin_date"],
        "current_cut_off":    current["priority_date"],
        "is_current":         current["is_current"],
        "is_unavailable":     current["is_unavailable"],
        "raw_value":          current["raw_value"],
        "backlog_days":       backlog_days,
        "backlog_years":      round(backlog_days / 365.25, 1) if backlog_days else None,
        "avg_monthly_advance_days": round(avg_monthly_days, 1) if avg_monthly_days else None,
        "est_years_to_current":     years_to_wait,
    }


@app.get("/api/visa-bulletin/compare")
async def visa_bulletin_compare(
    preference:    str            = Query(..., description="e.g. EB3"),
    date_type:     Optional[str]  = Query("final_action"),
    bulletin_date: Optional[str]  = Query(None, description="YYYY-MM-DD, defaults to latest"),
):
    """
    Compare all chargeability countries for a given preference in one bulletin.
    """
    if bulletin_date:
        bdate = bulletin_date
    else:
        row = await database.fetch_one(
            text("SELECT MAX(bulletin_date) AS d FROM visa_bulletin"))
        bdate = row["d"]

    rows = await database.fetch_all(text("""
        SELECT bulletin_date, bulletin_title, preference, chargeability,
               date_type, category_type,
               priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin
        WHERE preference    = :preference
          AND date_type     = :date_type
          AND bulletin_date = :bdate
        ORDER BY chargeability
    """), {
        "preference": preference.upper(),
        "date_type":  date_type or "final_action",
        "bdate":      bdate,
    })
    if not rows:
        raise HTTPException(status_code=404, detail="No data found")
    return [dict(r) for r in rows]


@app.get("/api/visa-bulletin/index")
async def visa_bulletin_index():
    """List all available bulletin months in the DB."""
    rows = await database.fetch_all(text("""
        SELECT bulletin_date, bulletin_title,
               COUNT(*) AS total_rows,
               COUNT(DISTINCT preference) AS preferences,
               COUNT(DISTINCT date_type) AS date_types
        FROM visa_bulletin
        GROUP BY bulletin_date, bulletin_title
        ORDER BY bulletin_date DESC
    """))
    return [dict(r) for r in rows]


@app.get("/api/visa-bulletin/stats")
async def visa_bulletin_stats():
    """Coverage summary for the visa bulletin table."""
    rows = await database.fetch_all(text("""
        SELECT category_type, date_type,
               COUNT(DISTINCT bulletin_date) AS bulletins,
               COUNT(DISTINCT preference)    AS preferences,
               MIN(bulletin_date)            AS earliest,
               MAX(bulletin_date)            AS latest,
               COUNT(*)                      AS total_rows
        FROM visa_bulletin
        GROUP BY category_type, date_type
        ORDER BY category_type, date_type
    """))
    return [dict(r) for r in rows]
# ══════════════════════════════════════════════════════════════════════════════
# OFLC Query Engine — append to api.py
# Supports pivot table mode and raw record mode with dynamic filters
# ══════════════════════════════════════════════════════════════════════════════

OFLC_TABLES = {
    "oflc_perm": {
        "text_cols": {
            "case_number","case_status","fiscal_year","source_file","occupation_type",
            "employer_name","employer_state","employer_city","employer_postal_code",
            "employer_fein","employer_naics","atty_law_firm","atty_last_name",
            "atty_first_name","atty_state","job_title","soc_code","soc_title",
            "wage_per","worksite_city","worksite_state","worksite_postal_code",
            "worksite_bls_area","pwd_number","fw_currently_employed",
            "is_multiple_locations","employer_layoff",
        },
        "numeric_cols": {"wage_from","wage_to","employer_num_payroll","employer_year_commenced"},
        "date_cols":    {"received_date","decision_date","ingested_at"},
    },
    "oflc_lca": {
        "text_cols": {
            "case_number","case_status","fiscal_year","visa_class","source_file",
            "employer_name","employer_state","employer_city","employer_postal_code",
            "employer_fein","naics_code","law_firm_name","agent_last_name",
            "agent_first_name","agent_state","job_title","soc_code","soc_title",
            "full_time_position","wage_unit","pw_unit","pw_wage_level","pw_oes_year",
            "worksite_city","worksite_state","worksite_postal_code",
            "h1b_dependent","willful_violator",
        },
        "numeric_cols": {"wage_from","wage_to","prevailing_wage","total_worker_positions"},
        "date_cols":    {"received_date","decision_date","begin_date","end_date","ingested_at"},
    },
    "oflc_pw": {
        "text_cols": {
            "case_number","case_status","fiscal_year","visa_class","source_file",
            "employer_name","employer_state","employer_city","employer_postal_code",
            "employer_fein","naics_code","law_firm_name","agent_last_name",
            "agent_first_name","job_title","soc_code","soc_title",
            "suggested_soc_code","suggested_soc_title",
            "pwd_soc_code","pwd_soc_title",
            "emp_soc_codes","emp_soc_titles",
            "o_net_code","o_net_title",
            "pwd_unit","pw_wage_level","wage_source","wage_source_requested",
            "survey_name","bls_area",
            "alt_pwd_unit","alt_pwd_wage_level","alt_pwd_wage_source",
            "worksite_city","worksite_state","worksite_postal_code",
        },
        "numeric_cols": {"pwd_wage_rate", "alt_pwd_wage_rate"},
        "date_cols":    {"received_date","determination_date","pwd_wage_expiration_date","ingested_at"},
    },
}

def _safe_col(table: str, col: str) -> str:
    if table not in OFLC_TABLES:
        raise ValueError(f"Unknown table: {table}")
    cfg = OFLC_TABLES[table]
    all_cols = cfg["text_cols"] | cfg["numeric_cols"] | cfg["date_cols"] | {"id"}
    if col not in all_cols:
        raise ValueError(f"Unknown column '{col}' for table '{table}'")
    return f'"{col}"'


def _build_agg_expr(agg: str, field: str | None, table: str) -> str:
    if agg == "count":
        return "COUNT(*)"
    if agg == "pct_of_total":
        return "ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)"
    if not field:
        if agg == "count_distinct":
            return "COUNT(*)"  # fallback: no field selected yet
        raise ValueError(f"Aggregation '{agg}' requires a field")
    col = _safe_col(table, field)
    if agg == "count_distinct": return f"COUNT(DISTINCT {col})"
    if agg == "sum":            return f"SUM({col})"
    if agg == "avg":            return f"ROUND(AVG({col})::numeric, 2)"
    if agg == "min":            return f"MIN({col})"
    if agg == "max":            return f"MAX({col})"
    raise ValueError(f"Unknown aggregation: {agg}")


def _build_where(table: str, filter_params: list) -> tuple:
    clauses, params = [], {}
    for i, f in enumerate(filter_params):
        field, op, val = f.get("field"), f.get("op"), f.get("val", "")
        if not field: continue
        col = _safe_col(table, field)
        key = f"fv_{i}"
        if op == "IS NULL":      clauses.append(f"{col} IS NULL")
        elif op == "IS NOT NULL": clauses.append(f"{col} IS NOT NULL")
        elif op == "ILIKE":      clauses.append(f"{col} ILIKE :{key}"); params[key] = f"%{val}%"
        elif op == "NOT ILIKE":  clauses.append(f"{col} NOT ILIKE :{key}"); params[key] = f"%{val}%"
        elif op in ("=","!=",">",">=","<","<="):
            clauses.append(f"{col} {op} :{key}"); params[key] = val
        else:
            raise ValueError(f"Unknown operator: {op}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params

@app.get("/api/oflc/query")
async def oflc_query(request: Request):
    from urllib.parse import parse_qs
    p = request.query_params
    raw_qs = str(request.url).split("?", 1)[1] if "?" in str(request.url) else ""
    parsed_qs = parse_qs(raw_qs)

    table  = p.get("table", "oflc_perm")
    mode   = p.get("mode", "pivot")
    limit  = min(int(p.get("limit", 500)), 5000)

    if table not in OFLC_TABLES:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")

    # Parse filters
    filter_list, i = [], 0
    while f"f_field_{i}" in p:
        filter_list.append({"field": p[f"f_field_{i}"], "op": p[f"f_op_{i}"], "val": p.get(f"f_val_{i}", "")})
        i += 1

    try:
        where, params = _build_where(table, filter_list)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Raw mode ──────────────────────────────────────────────────────────────
    if mode == "raw":
        q = f"SELECT * FROM {table} {where} ORDER BY id LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q).bindparams(**params))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        count_q = f"SELECT COUNT(*) as cnt FROM {table} {where}"
        nlp = {k: v for k, v in params.items() if k != "limit"}
        total_row = await database.fetch_one(text(count_q).bindparams(**nlp) if nlp else text(count_q))
        columns = list(rows[0].keys()) if rows else []
        return {"mode": "raw", "columns": columns, "rows": [dict(r) for r in rows],
                "total_rows": total_row["cnt"] if total_row else 0, "limited": (total_row["cnt"] if total_row else 0) > limit}

    # ── Pivot mode ────────────────────────────────────────────────────────────
    row_fields = parsed_qs.get("rows", [])
    col_field  = parsed_qs.get("cols", [None])[0]
    if not row_fields:
        raise HTTPException(status_code=400, detail="At least one row field required for pivot mode")

    # Parse value metrics
    value_metrics, j = [], 0
    while f"vm_agg_{j}" in p:
        value_metrics.append({"agg": p[f"vm_agg_{j}"], "field": p.get(f"vm_field_{j}") or None, "label": p.get(f"vm_label_{j}") or f"Metric {j}"})
        j += 1
    if not value_metrics:
        value_metrics = [{"agg": "count", "field": None, "label": "Count"}]

    try:
        safe_rows = [_safe_col(table, f) for f in row_fields]
        safe_col  = _safe_col(table, col_field) if col_field else None
        agg_exprs = [_build_agg_expr(vm["agg"], vm["field"], table) for vm in value_metrics]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    group_cols  = safe_rows  # col field is pivoted via FILTER, NOT added to GROUP BY
    group_by    = ", ".join(safe_rows)
    select_cols = ", ".join(safe_rows)

    if col_field:
        col_vals_q   = f"SELECT DISTINCT {safe_col} FROM {table} {where} ORDER BY {safe_col} LIMIT 50"
        col_val_rows = await database.fetch_all(text(col_vals_q).bindparams(**params) if params else text(col_vals_q))
        col_values   = [r[0] for r in col_val_rows]

        pivot_selects = []
        for cv in col_values:
            cv_safe   = str(cv).replace("'", "''") if cv is not None else None
            cv_filter = f"{safe_col} = '{cv_safe}'" if cv is not None else f"{safe_col} IS NULL"
            for vm in value_metrics:
                agg = vm["agg"]
                if agg in ("count", "pct_of_total"):
                    expr = f"COUNT(*) FILTER (WHERE {cv_filter})"
                    if agg == "pct_of_total":
                        expr = f"ROUND(COUNT(*) FILTER (WHERE {cv_filter}) * 100.0 / NULLIF(COUNT(*), 0), 2)"
                elif agg == "count_distinct":
                    if vm["field"]:
                        expr = f"COUNT(DISTINCT {_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                    else:
                        expr = f"COUNT(*) FILTER (WHERE {cv_filter})"
                elif agg == "sum":  expr = f"SUM({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                elif agg == "avg":  expr = f"ROUND(AVG({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})::numeric, 2)"
                elif agg == "min":  expr = f"MIN({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                elif agg == "max":  expr = f"MAX({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                else: expr = "NULL"
                pivot_selects.append(f"{expr} AS \"{cv}__{vm['label']}\"")
        for vm, ae in zip(value_metrics, agg_exprs):
            pivot_selects.append(f"{ae} AS \"__row_total__{vm['label']}\"")

        q = f"SELECT {select_cols}, {', '.join(pivot_selects)} FROM {table} {where} GROUP BY {group_by} ORDER BY {safe_rows[0]} LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q).bindparams(**params))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        gt_selects = []
        no_limit_params = {k: v for k, v in params.items() if k != "limit"}
        for cv in col_values:
            cv_safe   = str(cv).replace("'", "''") if cv is not None else None
            cv_filter = f"{safe_col} = '{cv_safe}'" if cv is not None else f"{safe_col} IS NULL"
            for vm in value_metrics:
                gt_selects.append(f"COUNT(*) FILTER (WHERE {cv_filter}) AS \"{cv}__{vm['label']}\"")
        for vm, ae in zip(value_metrics, agg_exprs):
            gt_selects.append(f"{ae} AS \"__row_total__{vm['label']}\"")
        gt_sql = f"SELECT {', '.join(gt_selects)} FROM {table} {where}"
        gt_row = await database.fetch_one(text(gt_sql).bindparams(**no_limit_params) if no_limit_params else text(gt_sql))
        cnt_sql = f"SELECT COUNT(*) as cnt FROM (SELECT {group_by} FROM {table} {where} GROUP BY {group_by}) sub"
        cnt_row = await database.fetch_one(text(cnt_sql).bindparams(**no_limit_params) if no_limit_params else text(cnt_sql))
        total_rows = cnt_row["cnt"] if cnt_row else 0

        return {"mode": "pivot", "rows": [dict(r) for r in rows], "grand_total": dict(gt_row) if gt_row else None,
                "col_values": col_values, "total_rows": total_rows, "limited": total_rows > limit}

    else:
        # No column pivot — simple group by
        agg_select = ", ".join(f"{ae} AS \"{vm['label']}\"" for ae, vm in zip(agg_exprs, value_metrics))
        q = f"SELECT {select_cols}, {agg_select} FROM {table} {where} GROUP BY {group_by} ORDER BY {safe_rows[0]} LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q).bindparams(**params))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        no_limit_params = {k: v for k, v in params.items() if k != "limit"}
        gt_agg  = ", ".join(f"{_build_agg_expr(vm['agg'], vm['field'], table)} AS \"{vm['label']}\"" for vm in value_metrics)
        gt_sql  = f"SELECT {gt_agg} FROM {table} {where}"
        cnt_sql = f"SELECT COUNT(*) as cnt FROM (SELECT {group_by} FROM {table} {where} GROUP BY {group_by}) sub"
        gt_row  = await database.fetch_one(text(gt_sql).bindparams(**no_limit_params) if no_limit_params else text(gt_sql))
        cnt_row = await database.fetch_one(text(cnt_sql).bindparams(**no_limit_params) if no_limit_params else text(cnt_sql))

        return {"mode": "pivot", "rows": [dict(r) for r in rows], "grand_total": dict(gt_row) if gt_row else None,
                "col_values": [], "total_rows": cnt_row["cnt"] if cnt_row else 0, "limited": (cnt_row["cnt"] if cnt_row else 0) > limit}


@app.get("/api/oflc/field-values/{table}")
async def oflc_field_values(table: str, field: str, q: str = "", limit: int = 12):
    """Typeahead: return distinct values for a field matching query string."""
    table_map  = {"perm": "oflc_perm", "lca": "oflc_lca", "pw": "oflc_pw"}
    full_table = table_map.get(table, table)
    if full_table not in OFLC_TABLES:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")
    try:
        col = _safe_col(full_table, field)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sql  = f"SELECT DISTINCT {col} AS val FROM {full_table} WHERE {col} IS NOT NULL AND {col} ILIKE :q ORDER BY {col} LIMIT :limit"
    rows = await database.fetch_all(text(sql).bindparams(q=f"%{q}%", limit=min(limit, 50)))
    return {"values": [r["val"] for r in rows]}


@app.get("/api/oflc/landing-stats")
async def oflc_landing_stats():
    """Quick counts and cert rate for the landing page stats bar."""
    perm = await database.fetch_one(text("""
        SELECT
            COUNT(*) AS total,
            ROUND(SUM(CASE WHEN case_status = 'Certified' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*),0), 1) AS cert_rate
        FROM oflc_perm
    """))
    lca = await database.fetch_one(text("SELECT COUNT(*) AS total FROM oflc_lca"))
    pw  = await database.fetch_one(text("SELECT COUNT(*) AS total FROM oflc_pw"))
    return {
        "perm_total":     perm["total"]     if perm else 0,
        "perm_cert_rate": perm["cert_rate"] if perm else None,
        "lca_total":      lca["total"]      if lca  else 0,
        "pw_total":       pw["total"]       if pw   else 0,
    }


FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """Serve the Vite app in production while preserving API 404s."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        requested_file = FRONTEND_DIST / full_path
        if full_path and requested_file.is_file():
            return FileResponse(requested_file)

        return FileResponse(FRONTEND_DIST / "index.html")
