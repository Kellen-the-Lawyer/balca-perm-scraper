from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from .config import SETTINGS
from .pipeline import collect_search_results, download_pdfs
from .storage import DecisionStore
from .urls import KEYWORD_SEARCH_URL

console = Console()


@click.group()
def cli():
    """BALCA PERM scraper CLI."""


@cli.command("inspect-homepage")
def inspect_homepage():
    console.print(f"Keyword search URL: {KEYWORD_SEARCH_URL}")
    console.print("Use your browser dev tools to confirm request parameters and selectors.")


@cli.command("search")
@click.option("--query", default=None, help="Free-text query, e.g. PERM")
@click.option("--docket-prefix", default=None, help="Docket prefix, e.g. 2024-PER-")
@click.option("--max-pages", default=5, type=int, show_default=True)
@click.option("--db", "db_path", default=str(SETTINGS.database_path), show_default=True)
def search(query: str | None, docket_prefix: str | None, max_pages: int, db_path: str):
    total = collect_search_results(
        query=query,
        docket_prefix=docket_prefix,
        max_pages=max_pages,
        db_path=Path(db_path),
    )
    console.print(f"Finished. Upserted {total} records.")


@cli.command("export-csv")
@click.option("--db", "db_path", default=str(SETTINGS.database_path), show_default=True)
@click.option(
    "--out",
    "out_path",
    default=str(SETTINGS.processed_dir / "results.csv"),
    show_default=True,
)
def export_csv(db_path: str, out_path: str):
    store = DecisionStore(Path(db_path))
    destination = store.export_csv(Path(out_path))
    console.print(f"Wrote {destination}")


@cli.command("download-pdfs")
@click.option("--input", "input_csv", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--out-dir", default=str(SETTINGS.raw_dir / "pdfs"), show_default=True)
@click.option("--limit", default=None, type=int)
def download_pdfs_cmd(input_csv: Path, out_dir: str, limit: int | None):
    count = download_pdfs(csv_path=input_csv, output_dir=Path(out_dir), limit=limit)
    console.print(f"Downloaded {count} PDFs.")


if __name__ == "__main__":
    cli()
