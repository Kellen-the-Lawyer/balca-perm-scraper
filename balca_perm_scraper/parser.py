from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from .models import DecisionRecord
from .normalize import clean_text, extract_docket, parse_decision_date
from .selectors import SELECTORS
from .urls import absolute_url


def parse_azure_response(data: dict[str, Any]) -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    for doc in data.get("value", []):
        parsed_title = clean_text(doc.get("parsed_title") or "") or ""
        file_path = doc.get("file_path") or ""
        highlights = doc.get("@search.highlights") or {}
        snippet_parts = highlights.get("content", [])
        snippet = clean_text(" … ".join(snippet_parts)) if snippet_parts else None

        docket = extract_docket(parsed_title)
        decision_date = parse_decision_date(doc.get("issued_date"))

        # Case name = everything in parsed_title before the docket token
        case_name = parsed_title
        if docket and parsed_title:
            raw_docket = docket.replace("-", "")  # e.g. 2006PER00039
            idx = parsed_title.upper().find(raw_docket)
            if idx > 0:
                case_name = clean_text(parsed_title[:idx])

        resolved = absolute_url(file_path) if file_path else None
        pdf_url = resolved if file_path.lower().endswith(".pdf") else None
        source_url = resolved if not pdf_url else None

        records.append(
            DecisionRecord(
                case_name=case_name,
                docket_number=docket,
                decision_date=decision_date,
                document_type=doc.get("document_type"),
                program_area=doc.get("program_area"),
                case_type=doc.get("case_type"),
                source_url=source_url,
                pdf_url=pdf_url,
                snippet=snippet,
            )
        )
    return _dedupe(records)


def parse_search_results(html: str) -> list[DecisionRecord]:
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(SELECTORS.result_item)
    records: list[DecisionRecord] = []

    for item in items:
        link = item.select_one(SELECTORS.title_link)
        if not link:
            continue

        title_text = clean_text(link.get_text(" ", strip=True))
        href = link.get("href")
        snippet_el = item.select_one(SELECTORS.snippet)
        snippet = clean_text(snippet_el.get_text(" ", strip=True) if snippet_el else None)
        pdf_el = item.select_one(SELECTORS.pdf_link)
        pdf_href = pdf_el.get("href") if pdf_el else None

        combined_text = " ".join(filter(None, [title_text, snippet, item.get_text(" ", strip=True)]))
        docket = extract_docket(combined_text)
        decision_date = parse_decision_date(combined_text)

        records.append(
            DecisionRecord(
                case_name=title_text,
                docket_number=docket,
                decision_date=decision_date,
                source_url=absolute_url(href) if href else None,
                pdf_url=absolute_url(pdf_href) if pdf_href else None,
                snippet=snippet,
            )
        )

    return _dedupe(records)


def find_next_page(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    next_link = soup.select_one(SELECTORS.next_link)
    if not next_link:
        return None
    href = next_link.get("href")
    return absolute_url(href) if href else None


def _dedupe(records: list[DecisionRecord]) -> list[DecisionRecord]:
    seen: set[str] = set()
    deduped: list[DecisionRecord] = []
    for record in records:
        key = record.stable_id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
