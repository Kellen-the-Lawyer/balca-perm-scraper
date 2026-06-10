"""
Kanban board API — Graphite / Casebase task tracking
"""
import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import text

# Import the shared database instance from api.py
import sys
sys.path.insert(0, os.path.dirname(__file__))

KANBAN_TOKEN = os.environ.get("KANBAN_TOKEN", "")

api_key_header = APIKeyHeader(name="x-kanban-token", auto_error=False)

def require_token(key: Optional[str] = Security(api_key_header)):
    if KANBAN_TOKEN and key != KANBAN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing x-kanban-token")
    return key

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


# ── Schema migration (called from api.py lifespan) ────────────────────────────

KANBAN_MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS kanban_cards (
        id          BIGSERIAL PRIMARY KEY,
        project     TEXT NOT NULL CHECK (project IN ('graphite', 'casebase')),
        col         TEXT NOT NULL CHECK (col IN ('todo', 'inprogress', 'review', 'done')),
        title       TEXT NOT NULL,
        priority    TEXT NOT NULL DEFAULT 'med' CHECK (priority IN ('high', 'med', 'low')),
        notes       TEXT NOT NULL DEFAULT '',
        assigned_to TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        position    INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kanban_project ON kanban_cards(project)",
    "CREATE INDEX IF NOT EXISTS idx_kanban_col     ON kanban_cards(col)",
    "ALTER TABLE IF EXISTS kanban_cards ADD COLUMN IF NOT EXISTS assigned_to TEXT",
    """
    CREATE TABLE IF NOT EXISTS kanban_boards (
        id         BIGSERIAL PRIMARY KEY,
        name       TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kanban_board_cards (
        id          BIGSERIAL PRIMARY KEY,
        board_id    BIGINT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
        col         TEXT NOT NULL CHECK (col IN ('todo', 'inprogress', 'review', 'done')),
        title       TEXT NOT NULL,
        priority    TEXT NOT NULL DEFAULT 'med' CHECK (priority IN ('high', 'med', 'low')),
        notes       TEXT NOT NULL DEFAULT '',
        assigned_to TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        position    INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_board_cards_board ON kanban_board_cards(board_id)",
]


async def ensure_kanban_schema(database) -> None:
    for stmt in KANBAN_MIGRATIONS:
        await database.execute(text(stmt))


# ── Routes ────────────────────────────────────────────────────────────────────

def _card_row(r) -> dict:
    d = dict(r)
    d["created_at"] = str(d["created_at"]) if d.get("created_at") else None
    d["updated_at"] = str(d["updated_at"]) if d.get("updated_at") else None
    return d


def register_routes(database):
    """Call this from api.py to wire up the router with the shared db instance."""

    @router.get("/cards")
    async def list_cards(
        project: Optional[str] = None,
        col: Optional[str] = None,
        assigned_to: Optional[str] = None,
        _: str = Depends(require_token),
    ):
        conditions = ["1=1"]
        bind = {}
        if project:
            conditions.append("project = :project")
            bind["project"] = project
        if col:
            conditions.append("col = :col")
            bind["col"] = col
        if assigned_to:
            conditions.append("assigned_to = :assigned_to")
            bind["assigned_to"] = assigned_to
        where = " AND ".join(conditions)
        rows = await database.fetch_all(
            text(f"SELECT * FROM kanban_cards WHERE {where} ORDER BY col, position, created_at").bindparams(**bind)
        )
        return [_card_row(r) for r in rows]

    @router.post("/cards")
    async def create_card(data: dict, _: str = Depends(require_token)):
        row = await database.fetch_one(
            text("""
                INSERT INTO kanban_cards (project, col, title, priority, notes, assigned_to, position)
                VALUES (:project, :col, :title, :priority, :notes, :assigned_to,
                    COALESCE((SELECT MAX(position)+1 FROM kanban_cards WHERE col=:col), 0))
                RETURNING *
            """).bindparams(
                project=data["project"],
                col=data.get("col", "todo"),
                title=data["title"],
                priority=data.get("priority", "med"),
                notes=data.get("notes", ""),
                assigned_to=data.get("assigned_to"),
            )
        )
        return _card_row(row)

    @router.patch("/cards/{card_id}")
    async def update_card(card_id: int, data: dict, _: str = Depends(require_token)):
        existing = await database.fetch_one(
            text("SELECT * FROM kanban_cards WHERE id = :id").bindparams(id=card_id)
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Card not found")
        merged = {**dict(existing), **data}
        row = await database.fetch_one(
            text("""
                UPDATE kanban_cards
                SET project=:project, col=:col, title=:title, priority=:priority,
                    notes=:notes, assigned_to=:assigned_to, position=:position,
                    updated_at=NOW()
                WHERE id=:id RETURNING *
            """).bindparams(
                id=card_id,
                project=merged["project"],
                col=merged["col"],
                title=merged["title"],
                priority=merged["priority"],
                notes=merged.get("notes", ""),
                assigned_to=merged.get("assigned_to"),
                position=merged.get("position", 0),
            )
        )
        return _card_row(row)

    @router.delete("/cards/{card_id}")
    async def delete_card(card_id: int, _: str = Depends(require_token)):
        await database.execute(
            text("DELETE FROM kanban_cards WHERE id = :id").bindparams(id=card_id)
        )
        return {"ok": True}

    @router.get("/stats")
    async def kanban_stats(_: str = Depends(require_token)):
        rows = await database.fetch_all(text("""
            SELECT project, col, priority, COUNT(*) AS cnt
            FROM kanban_cards
            GROUP BY project, col, priority
            ORDER BY project, col
        """))
        return [dict(r) for r in rows]

    # ── Board CRUD ────────────────────────────────────────────────────────────

    @router.get("/boards")
    async def list_boards(_: str = Depends(require_token)):
        rows = await database.fetch_all(text(
            "SELECT * FROM kanban_boards ORDER BY created_at ASC"
        ))
        return [dict(r) for r in rows]

    @router.post("/boards")
    async def create_board(data: dict, _: str = Depends(require_token)):
        row = await database.fetch_one(text("""
            INSERT INTO kanban_boards (name) VALUES (:name) RETURNING *
        """).bindparams(name=data["name"]))
        return dict(row)

    @router.patch("/boards/{board_id}")
    async def update_board(board_id: int, data: dict, _: str = Depends(require_token)):
        row = await database.fetch_one(text("""
            UPDATE kanban_boards SET name=:name, updated_at=NOW()
            WHERE id=:id RETURNING *
        """).bindparams(id=board_id, name=data["name"]))
        if not row:
            raise HTTPException(status_code=404, detail="Board not found")
        return dict(row)

    @router.delete("/boards/{board_id}")
    async def delete_board(board_id: int, _: str = Depends(require_token)):
        await database.execute(text(
            "DELETE FROM kanban_boards WHERE id = :id"
        ).bindparams(id=board_id))
        return {"ok": True}

    # ── Board card CRUD ───────────────────────────────────────────────────────

    @router.get("/boards/{board_id}/cards")
    async def list_board_cards(board_id: int, col: Optional[str] = None, _: str = Depends(require_token)):
        conditions = ["board_id = :board_id"]
        bind = {"board_id": board_id}
        if col:
            conditions.append("col = :col")
            bind["col"] = col
        where = " AND ".join(conditions)
        rows = await database.fetch_all(
            text(f"SELECT * FROM kanban_board_cards WHERE {where} ORDER BY col, position, created_at").bindparams(**bind)
        )
        return [_card_row(r) for r in rows]

    @router.post("/boards/{board_id}/cards")
    async def create_board_card(board_id: int, data: dict, _: str = Depends(require_token)):
        row = await database.fetch_one(text("""
            INSERT INTO kanban_board_cards (board_id, col, title, priority, notes, assigned_to, position)
            VALUES (:board_id, :col, :title, :priority, :notes, :assigned_to,
                COALESCE((SELECT MAX(position)+1 FROM kanban_board_cards WHERE board_id=:board_id AND col=:col), 0))
            RETURNING *
        """).bindparams(
            board_id=board_id,
            col=data.get("col", "todo"),
            title=data["title"],
            priority=data.get("priority", "med"),
            notes=data.get("notes", ""),
            assigned_to=data.get("assigned_to"),
        ))
        return _card_row(row)

    @router.patch("/boards/{board_id}/cards/{card_id}")
    async def update_board_card(board_id: int, card_id: int, data: dict, _: str = Depends(require_token)):
        existing = await database.fetch_one(
            text("SELECT * FROM kanban_board_cards WHERE id=:id AND board_id=:board_id").bindparams(id=card_id, board_id=board_id)
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Card not found")
        merged = {**dict(existing), **data}
        row = await database.fetch_one(text("""
            UPDATE kanban_board_cards
            SET col=:col, title=:title, priority=:priority, notes=:notes,
                assigned_to=:assigned_to, position=:position, updated_at=NOW()
            WHERE id=:id RETURNING *
        """).bindparams(
            id=card_id,
            col=merged["col"], title=merged["title"], priority=merged["priority"],
            notes=merged.get("notes", ""), assigned_to=merged.get("assigned_to"),
            position=merged.get("position", 0),
        ))
        return _card_row(row)

    @router.delete("/boards/{board_id}/cards/{card_id}")
    async def delete_board_card(board_id: int, card_id: int, _: str = Depends(require_token)):
        await database.execute(
            text("DELETE FROM kanban_board_cards WHERE id=:id AND board_id=:board_id").bindparams(id=card_id, board_id=board_id)
        )
        return {"ok": True}

    return router
