from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class DecisionRecord(BaseModel):
    case_name: Optional[str] = None
    docket_number: Optional[str] = None
    decision_date: Optional[date] = None
    document_type: Optional[str] = None
    program_area: Optional[str] = None
    case_type: Optional[str] = None
    source_url: Optional[HttpUrl] = None
    pdf_url: Optional[HttpUrl] = None
    snippet: Optional[str] = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def stable_id(self) -> str:
        docket = self.docket_number or "unknown-docket"
        doc_type = self.document_type or "unknown-doc"
        date_part = self.decision_date.isoformat() if self.decision_date else "unknown-date"
        return f"{docket}::{doc_type}::{date_part}"
