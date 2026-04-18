from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

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
"""


class DecisionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(SCHEMA_SQL)

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
