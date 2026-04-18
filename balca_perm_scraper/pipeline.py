from __future__ import annotations

import random
import time
from pathlib import Path

import pandas as pd
from rich.console import Console

from .client import ScraperClient
from .config import SETTINGS
from .parser import parse_azure_response
from .storage import DecisionStore
from .urls import KEYWORD_SEARCH_URL

console = Console()


PERM_FILTER = "case_type eq 'PER'"
FACET_FIELDS = ["agency", "document_category", "program_area", "case_type", "document_type", "file_type"]

# All fiscal years with PERM decisions, largest first
FISCAL_YEARS = [
    "2012", "2013", "2011", "2014", "2010", "2016", "2015", "2023",
    "2024", "2009", "2025", "2022", "2018", "2019", "2026", "2020",
    "2017", "2008", "2021", "2007", "2006",
]


def build_search_body(
    query: str | None = None,
    docket_prefix: str | None = None,
    fiscal_year: str | None = None,
    page: int = 1,
):
    search_term = " ".join(filter(None, [query, docket_prefix])) or "*"
    filters = [PERM_FILTER]
    if fiscal_year:
        filters.append(f"fiscal_year eq '{fiscal_year}'")
    return {
        "search": search_term,
        "count": True,
        "highlight": "content",
        "top": SETTINGS.page_size,
        "queryType": "full",
        "skip": (page - 1) * SETTINGS.page_size,
        "facets": [f"{f},count:100" for f in FACET_FIELDS],
        "filter": " and ".join(filters),
    }


def collect_search_results(
    query: str | None = None,
    docket_prefix: str | None = None,
    max_pages: int = 5,
    db_path: Path = SETTINGS.database_path,
):
    store = DecisionStore(db_path)
    total = 0

    with ScraperClient() as client:
        for year in FISCAL_YEARS:
            console.print(f"[bold]Scraping fiscal year {year}[/bold]")
            for page_number in range(1, max_pages + 1):
                body = build_search_body(
                    query=query, docket_prefix=docket_prefix,
                    fiscal_year=year, page=page_number,
                )
                response = client.post_json(KEYWORD_SEARCH_URL, body, SETTINGS.azure_query_key)
                data = response.json()
                records = parse_azure_response(data)
                if not records:
                    break
                total += store.upsert_many(records)
                console.print(f"  page {page_number}: {len(records)} records (total {total})")

                if len(records) < SETTINGS.page_size:
                    break

    return total


def download_pdfs(csv_path: Path, output_dir: Path = SETTINGS.raw_dir / "pdfs", limit: int | None = None):
    df = pd.read_csv(csv_path)
    if limit is not None:
        df = df.head(limit)

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    with ScraperClient() as client:
        for _, row in df.iterrows():
            pdf_url = row.get("pdf_url")
            docket = row.get("docket_number") or f"unknown_{downloaded}"
            if not isinstance(pdf_url, str) or not pdf_url:
                continue
            destination = output_dir / f"{docket}.pdf"
            if destination.exists():
                continue
            if client.stream_to_file(pdf_url, destination):
                downloaded += 1
                console.print(f"Downloaded {destination.name}")
            else:
                console.print(f"[yellow]Skipped (403/404): {pdf_url}[/yellow]")
            delay = SETTINGS.pdf_sleep_seconds + random.uniform(0, SETTINGS.pdf_sleep_jitter)
            time.sleep(delay)

    return downloaded
