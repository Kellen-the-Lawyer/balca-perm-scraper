"""Research projects, project notes, and read-later queue."""
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

@router.get("/api/projects")
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

@router.post("/api/projects")
async def create_project(data: dict):
    row = await database.fetch_one(q("""
        INSERT INTO projects (name, description, color)
        VALUES (:name, :desc, :color) RETURNING id, name, description, color, created_at::text, updated_at::text""",
        name=data["name"], desc=data.get("description", ""), color=data.get("color", "#f59e0b")))
    return dict(row)

@router.patch("/api/projects/{project_id}")
async def update_project(project_id: int, data: dict):
    row = await database.fetch_one(q("""
        UPDATE projects SET name=:name, description=:desc, color=:color, updated_at=NOW()
        WHERE id=:id RETURNING id, name, description, color, updated_at::text""",
        id=project_id, name=data["name"], desc=data.get("description",""), color=data.get("color","#f59e0b")))
    return dict(row)

@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    await database.execute(q("DELETE FROM projects WHERE id=:id", id=project_id))
    return {"ok": True}

@router.get("/api/projects/{project_id}")
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

@router.post("/api/projects/{project_id}/cases")
async def add_case_to_project(project_id: int, data: dict):
    row = await database.fetch_one(q("""
        INSERT INTO project_cases (project_id, decision_id, search_query)
        VALUES (:pid, :did, :query)
        ON CONFLICT (project_id, decision_id) DO UPDATE SET search_query=EXCLUDED.search_query
        RETURNING id, added_at::text""",
        pid=project_id, did=data["decision_id"], query=data.get("search_query", "")))
    await database.execute(q("UPDATE projects SET updated_at=NOW() WHERE id=:id", id=project_id))
    return dict(row)

@router.delete("/api/projects/{project_id}/cases/{decision_id}")
async def remove_case_from_project(project_id: int, decision_id: int):
    await database.execute(q(
        "DELETE FROM project_cases WHERE project_id=:pid AND decision_id=:did",
        pid=project_id, did=decision_id))
    return {"ok": True}

@router.post("/api/projects/{project_id}/notes")
async def add_project_note(project_id: int, data: dict):
    row = await database.fetch_one(q("""
        INSERT INTO project_notes (project_id, decision_id, note)
        VALUES (:pid, :did, :note) RETURNING id, note, created_at::text""",
        pid=project_id, did=data.get("decision_id"), note=data["note"]))
    await database.execute(q("UPDATE projects SET updated_at=NOW() WHERE id=:id", id=project_id))
    return dict(row)

@router.delete("/api/project-notes/{note_id}")
async def delete_project_note(note_id: int):
    await database.execute(q("DELETE FROM project_notes WHERE id=:id", id=note_id))
    return {"ok": True}

# ── Read Later ────────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/read-later")
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


@router.get("/api/projects/{project_id}/read-later")
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


@router.delete("/api/projects/{project_id}/read-later/{pc_id}")
async def remove_read_later(project_id: int, pc_id: int):
    await database.execute(q(
        "DELETE FROM project_cases WHERE id=:id AND project_id=:pid AND section='read_later'",
        id=pc_id, pid=project_id))
    return {"ok": True}


# Which projects contain a given decision?
@router.get("/api/decisions/{decision_id}/projects")
async def decision_projects(decision_id: int):
    rows = await database.fetch_all(q("""
        SELECT p.id, p.name, p.color
        FROM project_cases pc JOIN projects p ON p.id = pc.project_id
        WHERE pc.decision_id = :did""", did=decision_id))
    return [dict(r) for r in rows]

# ── AAO Search & Decisions ────────────────────────────────────────────────────



# ── Ask AI Research (saved sources, cross-corpus) ────────────────────────────

_research_table_ready = False

async def _ensure_research_table():
    global _research_table_ready
    if _research_table_ready:
        return
    await database.execute(text("""
        CREATE TABLE IF NOT EXISTS project_research (
            id          SERIAL PRIMARY KEY,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            corpus      TEXT NOT NULL,
            source_id   TEXT,
            source_label TEXT NOT NULL,
            cfr_citation TEXT,
            excerpt     TEXT,
            question    TEXT,
            added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (project_id, corpus, source_id, excerpt)
        )
    """))
    _research_table_ready = True


@router.post("/api/projects/{project_id}/research")
async def save_research(project_id: int, data: dict):
    """Save an Ask AI source (any corpus) to a project."""
    await _ensure_research_table()
    row = await database.fetch_one(q("""
        INSERT INTO project_research
            (project_id, corpus, source_id, source_label, cfr_citation, excerpt, question)
        VALUES (:pid, :corpus, :sid, :label, :cfr, :excerpt, :question)
        ON CONFLICT (project_id, corpus, source_id, excerpt)
        DO UPDATE SET question = EXCLUDED.question
        RETURNING id, added_at::text""",
        pid=project_id,
        corpus=data["corpus"],
        sid=str(data.get("source_id") or ""),
        label=data.get("source_label") or data["corpus"],
        cfr=data.get("cfr_citation"),
        excerpt=(data.get("excerpt") or "")[:4000],
        question=(data.get("question") or "")[:1000]))
    await database.execute(q("UPDATE projects SET updated_at=NOW() WHERE id=:id", id=project_id))
    return dict(row)


@router.get("/api/projects/{project_id}/research")
async def list_research(project_id: int):
    await _ensure_research_table()
    rows = await database.fetch_all(q("""
        SELECT id, corpus, source_id, source_label, cfr_citation,
               excerpt, question, added_at::text
        FROM project_research WHERE project_id=:pid ORDER BY added_at DESC""",
        pid=project_id))
    return [dict(r) for r in rows]


@router.delete("/api/projects/{project_id}/research/{research_id}")
async def delete_research(project_id: int, research_id: int):
    await _ensure_research_table()
    await database.execute(q(
        "DELETE FROM project_research WHERE id=:rid AND project_id=:pid",
        rid=research_id, pid=project_id))
    return {"ok": True}
