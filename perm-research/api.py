"""
PERM Appeal Decisions — Research API
"""
import os
from contextlib import asynccontextmanager
from typing import Optional

import databases
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    yield
    await database.disconnect()

app = FastAPI(title="PERM Decisions Research API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def q(sql, **params):
    """Bind params to a SQLAlchemy text() clause."""
    return text(sql).bindparams(**params) if params else text(sql)

# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
async def search_decisions(
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
    sort_by: str = Query(default="relevance"),   # relevance | date_desc | date_asc
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    bind = {}

    if query.strip():
        conditions.append("d.search_vector @@ plainto_tsquery('english', :qtext)")
        bind["qtext"] = query.strip()
    if regulation:
        conditions.append("d.id IN (SELECT dr.decision_id FROM decision_regulations dr JOIN regulations r ON r.id = dr.regulation_id WHERE r.citation ILIKE :reg)")
        bind["reg"] = f"%{regulation}%"
    if outcome:
        conditions.append("d.outcome = :outcome")
        bind["outcome"] = outcome
    if date_from:
        conditions.append("d.decision_date >= :date_from")
        bind["date_from"] = date_from
    if date_to:
        conditions.append("d.decision_date <= :date_to")
        bind["date_to"] = date_to
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
    elif query.strip():
        order = "ts_rank(d.search_vector, plainto_tsquery('english', :qtext)) DESC, d.decision_date DESC NULLS LAST"
    else:
        order = "d.decision_date DESC NULLS LAST"

    snippet = ""
    if query.strip():
        snippet = (", ts_headline('english', d.full_text, plainto_tsquery('english', :qtext),"
                   " 'MaxWords=30, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline")

    total = await database.fetch_val(text(f"SELECT COUNT(*) FROM decisions d WHERE {where}").bindparams(**bind))

    bind["limit"] = page_size
    bind["offset"] = offset
    rows = await database.fetch_all(
        text(f"""SELECT d.id, d.case_number, d.decision_date::text, d.employer_name,
               d.job_title, d.outcome, d.panel {snippet},
               (SELECT COUNT(*) FROM decision_regulations dr WHERE dr.decision_id = d.id) AS regulation_count
        FROM decisions d WHERE {where} ORDER BY {order} LIMIT :limit OFFSET :offset"""
        ).bindparams(**bind)
    )
    return {"total": total, "page": page, "page_size": page_size, "results": [dict(r) for r in rows]}

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

# Which projects contain a given decision?
@app.get("/api/decisions/{decision_id}/projects")
async def decision_projects(decision_id: int):
    rows = await database.fetch_all(q("""
        SELECT p.id, p.name, p.color
        FROM project_cases pc JOIN projects p ON p.id = pc.project_id
        WHERE pc.decision_id = :did""", did=decision_id))
    return [dict(r) for r in rows]
