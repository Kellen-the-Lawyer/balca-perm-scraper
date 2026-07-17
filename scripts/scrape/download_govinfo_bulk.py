#!/usr/bin/env python3
"""
download_govinfo_bulk.py - Download GovInfo package files for Casebase.

This downloader is intentionally package-oriented. GovInfo's public package
content URLs do not require an API key, while API-based package discovery does.

Usage:
    # Discover packages modified since a date, then download XML when available.
    GOVINFO_API_KEY=... venv/bin/python3 scripts/scrape/download_govinfo_bulk.py \
        --collections BILLS,FR,PLAW,STATUTE,BILLSTATUS --date-from 2025-01-01

    # Download known packages without an API key.
    venv/bin/python3 scripts/scrape/download_govinfo_bulk.py \
        --package-id BILLS-118hr1ih --package-id FR-2024-01-02

    # Read package IDs from a file, one per line.
    venv/bin/python3 scripts/scrape/download_govinfo_bulk.py --package-file packages.txt

Environment:
    GOVINFO_API_KEY       Optional; required only for discovery.
    GOVINFO_OUT_DIR       Default: ~/casebase_govinfo
    GOVINFO_DELAY         Default: 0.25 seconds between requests.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

BASE_API = "https://api.govinfo.gov"
BASE_CONTENT = "https://www.govinfo.gov/content/pkg"
DEFAULT_OUT_DIR = Path(os.environ.get("GOVINFO_OUT_DIR", Path.home() / "casebase_govinfo"))
DEFAULT_DELAY = float(os.environ.get("GOVINFO_DELAY", "0.25"))

DEFAULT_COLLECTIONS = [
    "BILLS",
    "BILLSTATUS",
    "PLAW",
    "STATUTE",
    "FR",
    "USCODE",
    "CREC",
    "CRPT",
    "CHRG",
    "CPRT",
    "CDOC",
    "CDIR",
    "BUDGET",
    "ECONI",
    "ERP",
    "GOVMAN",
    "PPP",
]

HEADERS = {
    "User-Agent": "Casebase/1.0 (legal research; contact kellen@kellenpowell.com)",
    "Accept": "application/json,application/xml,text/plain,text/html;q=0.9,*/*;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def parse_collections(value: str | None) -> list[str]:
    if not value:
        return DEFAULT_COLLECTIONS
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def iso_start(date_value: str) -> str:
    if "T" in date_value:
        return date_value
    datetime.strptime(date_value, "%Y-%m-%d")
    return f"{date_value}T00:00:00Z"


def collection_from_package(package_id: str) -> str:
    return package_id.split("-", 1)[0].upper()


def candidate_content_urls(package_id: str, formats: Iterable[str]) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    for fmt in formats:
        fmt = fmt.lower().lstrip(".")
        if fmt == "xml":
            urls.append((fmt, f"{BASE_CONTENT}/{package_id}/xml/{package_id}.xml"))
        elif fmt in {"html", "htm"}:
            urls.append(("htm", f"{BASE_CONTENT}/{package_id}/html/{package_id}.htm"))
            urls.append(("html", f"{BASE_CONTENT}/{package_id}/html/{package_id}.html"))
        elif fmt == "txt":
            urls.append((fmt, f"{BASE_CONTENT}/{package_id}/txt/{package_id}.txt"))
        elif fmt == "pdf":
            urls.append((fmt, f"{BASE_CONTENT}/{package_id}/pdf/{package_id}.pdf"))
        else:
            urls.append((fmt, f"{BASE_CONTENT}/{package_id}/{fmt}/{package_id}.{fmt}"))
    return urls


def is_error_response(resp: requests.Response) -> bool:
    content_type = resp.headers.get("content-type", "").lower()
    if resp.status_code != 200:
        return True
    if "text/html" in content_type and "/error" in resp.url:
        return True
    return False


def download_package(
    session: requests.Session,
    package_id: str,
    out_dir: Path,
    formats: list[str],
    metadata: dict | None,
    dry_run: bool,
    skip_existing: bool,
) -> bool:
    collection = collection_from_package(package_id)
    package_dir = out_dir / collection / package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    if skip_existing:
        manifest = package_dir / "manifest.json"
        existing = sorted(
            path for path in package_dir.glob(f"{package_id}.*")
            if path.suffix != ".part" and path.stat().st_size > 0
        )
        if manifest.exists() and existing:
            log.info("skip existing %s", existing[0])
            return True

    for fmt, url in candidate_content_urls(package_id, formats):
        target = package_dir / f"{package_id}.{fmt}"
        partial = package_dir / f"{package_id}.{fmt}.part"
        if dry_run:
            log.info("would try %s", url)
            continue
        try:
            resp = session.get(url, timeout=90, stream=True)
        except requests.RequestException as exc:
            log.warning("%s request failed: %s", package_id, exc)
            continue
        if is_error_response(resp):
            continue
        try:
            with partial.open("wb") as handle:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
        except requests.RequestException as exc:
            partial.unlink(missing_ok=True)
            log.warning("%s download failed: %s", package_id, exc)
            continue
        except OSError as exc:
            partial.unlink(missing_ok=True)
            log.warning("%s write failed: %s", package_id, exc)
            continue
        partial.replace(target)
        if target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            continue
        write_manifest(package_dir, package_id, collection, url, target, metadata)
        log.info("downloaded %s -> %s", package_id, target)
        return True

    if dry_run:
        return True

    log.warning("no downloadable format found for %s", package_id)
    return False


def write_manifest(
    package_dir: Path,
    package_id: str,
    collection: str,
    source_url: str,
    target: Path,
    metadata: dict | None,
) -> None:
    payload = {
        "package_id": package_id,
        "collection": collection,
        "source_url": source_url,
        "file_path": str(target),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "api_metadata": metadata or {},
    }
    (package_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def iter_api_packages(
    session: requests.Session,
    api_key: str,
    collection: str,
    date_from: str,
    page_size: int,
    max_pages: int | None,
) -> Iterable[dict]:
    page = 0
    next_url = None
    start = iso_start(date_from)

    while True:
        if next_url:
            url = next_url
            params = {"api_key": api_key}
        else:
            params = {
                "api_key": api_key,
                "pageSize": page_size,
                "offsetMark": "*",
            }
            encoded_start = quote(start, safe="")
            url = f"{BASE_API}/collections/{collection}/{encoded_start}?{urlencode(params)}"
            params = None

        resp = None
        for attempt in range(5):
            try:
                resp = session.get(url, params=params, timeout=(10, 30))
                break
            except requests.RequestException as exc:
                if attempt == 4:
                    log.error(
                        "discovery request failed for %s after %s attempts: %s",
                        collection,
                        attempt + 1,
                        exc,
                    )
                    return
                delay = min(60, 2 ** attempt)
                log.warning(
                    "discovery request failed for %s (attempt %s/5): %s; retrying in %ss",
                    collection,
                    attempt + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
        if resp is None:
            return
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            status = resp.status_code
            body = resp.text[:500]
            raise RuntimeError(f"GovInfo discovery failed for {collection} ({status}): {body}") from None
        data = resp.json()
        packages = data.get("packages", [])
        ignored_collections: dict[str, int] = {}
        for package in packages:
            package_id = package_id_from_api(package)
            if package_id:
                package_collection = collection_from_package(package_id)
                if package_collection != collection.upper():
                    ignored_collections[package_collection] = ignored_collections.get(package_collection, 0) + 1
                    continue
            yield package
        if ignored_collections:
            ignored = ", ".join(
                f"{name}={count}" for name, count in sorted(ignored_collections.items())
            )
            log.warning(
                "ignored mixed-collection packages while discovering %s: %s",
                collection.upper(),
                ignored,
            )

        page += 1
        if max_pages and page >= max_pages:
            break
        next_url = data.get("nextPage")
        if not next_url:
            break


def load_package_ids(args: argparse.Namespace) -> list[dict]:
    packages: list[dict] = []
    for package_id in args.package_id or []:
        packages.append({"packageId": package_id.strip()})
    if args.package_file:
        for raw in Path(args.package_file).read_text(encoding="utf-8").splitlines():
            package_id = raw.strip()
            if not package_id or package_id.startswith("#"):
                continue
            packages.append({"packageId": package_id})
    return packages


def package_id_from_api(item: dict) -> str | None:
    for key in ("packageId", "package_id", "packageID"):
        value = item.get(key)
        if value:
            return str(value)
    details = item.get("detailsLink") or item.get("packageLink") or ""
    match = re.search(r"/packages/([^/?#]+)", details)
    return match.group(1) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Download GovInfo bulk/package data")
    parser.add_argument("--collections", default=None,
                        help="Comma-separated GovInfo collection codes; default is broad legal/government corpus excluding CFR")
    parser.add_argument("--date-from", default=None,
                        help="Discovery start date, YYYY-MM-DD or GovInfo timestamp. Required for API discovery.")
    parser.add_argument("--package-id", action="append",
                        help="Specific package ID to download; may be repeated.")
    parser.add_argument("--package-file",
                        help="File containing package IDs, one per line.")
    parser.add_argument("--formats", default="xml,txt,html,pdf",
                        help="Preferred formats in order. Default: xml,txt,html,pdf")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--api-key", default=os.environ.get("GOVINFO_API_KEY"))
    parser.add_argument("--page-size", type=int, default=100, choices=[10, 25, 50, 100, 250, 500, 1000])
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    args = parser.parse_args()

    formats = [part.strip().lower() for part in args.formats.split(",") if part.strip()]
    session = requests.Session()
    session.headers.update(HEADERS)

    explicit_packages = load_package_ids(args)
    if not explicit_packages and not args.date_from:
        parser.error("No packages to download. Use --package-id/--package-file or --date-from with GOVINFO_API_KEY.")

    ok = failed = 0
    processed = 0
    seen: set[str] = set()

    def process_item(item: dict) -> bool:
        nonlocal ok, failed, processed
        if args.limit and processed >= args.limit:
            return False
        package_id = package_id_from_api(item)
        if not package_id or package_id in seen:
            return True
        seen.add(package_id)
        if download_package(session, package_id, args.out_dir, formats, item, args.dry_run, args.skip_existing):
            ok += 1
        else:
            failed += 1
        processed += 1
        if args.delay and not args.dry_run:
            time.sleep(args.delay)
        return not args.limit or processed < args.limit

    for item in explicit_packages:
        if not process_item(item):
            break

    if args.date_from and (not args.limit or processed < args.limit):
        if not args.api_key:
            parser.error("--date-from discovery requires GOVINFO_API_KEY or --api-key")
        for collection in parse_collections(args.collections):
            log.info("discovering %s since %s", collection, args.date_from)
            for item in iter_api_packages(session, args.api_key, collection, args.date_from,
                                          args.page_size, args.max_pages):
                if not process_item(item):
                    break
            if args.limit and processed >= args.limit:
                break

    log.info("done: %s downloaded/skipped, %s failed", ok, failed)


if __name__ == "__main__":
    main()
