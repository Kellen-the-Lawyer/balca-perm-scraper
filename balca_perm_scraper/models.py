from __future__ import annotations

from hashlib import sha256
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
        if self.docket_number:
            doc_type = self.document_type or "unknown-doc"
            date_part = self.decision_date.isoformat() if self.decision_date else "unknown-date"
            return f"{self.docket_number}::{doc_type}::{date_part}"

        source = self.pdf_url or self.source_url
        if source:
            return f"url::{source}"

        parts = [
            self.case_name or "",
            self.document_type or "",
            self.program_area or "",
            self.case_type or "",
            self.snippet or "",
        ]
        digest = sha256("::".join(parts).encode("utf-8")).hexdigest()[:16]
        return f"content::{digest}"
