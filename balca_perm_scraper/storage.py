from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import DecisionRecord

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    stable_id TEXT PRIMARY KEY,
    case_name TEXT,
    docket_number TEXT,
    decision_date TEXT,
    document_type TEXT,
    program_area TEXT,
    case_type TEXT,
    source_url TEXT,
    pdf_url TEXT,
    snippet TEXT,
    discovered_at TEXT
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    query TEXT,
    docket_prefix TEXT,
    max_pages INTEGER NOT NULL,
    page_size INTEGER NOT NULL,
    fiscal_years TEXT NOT NULL,
    search_url TEXT NOT NULL,
    total_pages INTEGER NOT NULL DEFAULT 0,
    total_records INTEGER NOT NULL DEFAULT 0,
    total_upserted INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS scrape_run_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    fiscal_year TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    requested_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    request_body TEXT NOT NULL,
    result_count INTEGER,
    upserted_count INTEGER,
    azure_count INTEGER,
    error TEXT,
    FOREIGN KEY (run_id) REFERENCES scrape_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_scrape_run_pages_run_id ON scrape_run_pages(run_id);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class DecisionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA_SQL)

    def start_run(
        self,
        *,
        query: str | None,
        docket_prefix: str | None,
        max_pages: int,
        page_size: int,
        fiscal_years: list[str],
        search_url: str,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO scrape_runs (
                    started_at, status, query, docket_prefix, max_pages, page_size,
                    fiscal_years, search_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    "running",
                    query,
                    docket_prefix,
                    max_pages,
                    page_size,
                    json.dumps(fiscal_years),
                    search_url,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def record_run_page(
        self,
        *,
        run_id: int,
        fiscal_year: str,
        page_number: int,
        request_body: dict[str, Any],
        status: str,
        result_count: int | None = None,
        upserted_count: int | None = None,
        azure_count: int | None = None,
        error: str | None = None,
        requested_at: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scrape_run_pages (
                    run_id, fiscal_year, page_number, requested_at, completed_at,
                    status, request_body, result_count, upserted_count, azure_count, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    fiscal_year,
                    page_number,
                    requested_at or _now_iso(),
                    _now_iso(),
                    status,
                    json.dumps(request_body, sort_keys=True),
                    result_count,
                    upserted_count,
                    azure_count,
                    error,
                ),
            )
            conn.commit()

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        total_pages: int,
        total_records: int,
        total_upserted: int,
        error: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE scrape_runs
                SET finished_at = ?, status = ?, total_pages = ?, total_records = ?,
                    total_upserted = ?, error = ?
                WHERE id = ?
                """,
                (
                    _now_iso(),
                    status,
                    total_pages,
                    total_records,
                    total_upserted,
                    error,
                    run_id,
                ),
            )
            conn.commit()

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, started_at, finished_at, status, query, docket_prefix,
                       max_pages, page_size, total_pages, total_records,
                       total_upserted, error
                FROM scrape_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_many(self, records: Iterable[DecisionRecord]) -> int:
        rows = 0
        with sqlite3.connect(self.db_path) as conn:
            for record in records:
                payload = record.model_dump()
                conn.execute(
                    """
                    INSERT INTO decisions (
                        stable_id, case_name, docket_number, decision_date, document_type,
                        program_area, case_type, source_url, pdf_url, snippet, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stable_id) DO UPDATE SET
                        case_name=excluded.case_name,
                        docket_number=excluded.docket_number,
                        decision_date=excluded.decision_date,
                        document_type=excluded.document_type,
                        program_area=excluded.program_area,
                        case_type=excluded.case_type,
                        source_url=excluded.source_url,
                        pdf_url=excluded.pdf_url,
                        snippet=excluded.snippet,
                        discovered_at=excluded.discovered_at
                    """,
                    (
                        record.stable_id,
                        payload.get("case_name"),
                        payload.get("docket_number"),
                        payload.get("decision_date").isoformat() if payload.get("decision_date") else None,
                        payload.get("document_type"),
                        payload.get("program_area"),
                        payload.get("case_type"),
                        str(payload.get("source_url")) if payload.get("source_url") else None,
                        str(payload.get("pdf_url")) if payload.get("pdf_url") else None,
                        payload.get("snippet"),
                        payload.get("discovered_at").isoformat(),
                    ),
                )
                rows += 1
            conn.commit()
        return rows

    def export_csv(self, out_path: Path):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("SELECT * FROM decisions ORDER BY decision_date DESC", conn)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        return out_path
