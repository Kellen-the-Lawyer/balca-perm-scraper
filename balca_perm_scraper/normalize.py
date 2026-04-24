from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

DOCKET_RE = re.compile(r"\b(\d{4})-?(PER|INA|TLN)-?(\d{3,6})\b", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
DATE_CANDIDATE_RE = re.compile(
    r"\b("
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r")\b",
    re.IGNORECASE,
)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = WHITESPACE_RE.sub(" ", value).strip()
    return value or None


def extract_docket(value: str | None) -> Optional[str]:
    if not value:
        return None
    match = DOCKET_RE.search(value)
    if not match:
        return None
    year, code, num = match.group(1), match.group(2).upper(), match.group(3)
    return f"{year}-{code}-{num.zfill(5)}"


def parse_decision_date(value: str | None):
    if not value:
        return None
    value = value.strip()
    # ISO datetime from Azure Search (e.g. "2006-08-30T09:14:10Z")
    if "T" in value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    candidates = [value]
    candidates.extend(match.group(1) for match in DATE_CANDIDATE_RE.finditer(value))
    for candidate in candidates:
        candidate = candidate.replace("Sept.", "Sep.").replace("Sept ", "Sep ")
        for fmt in ("%b. %d, %Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None
