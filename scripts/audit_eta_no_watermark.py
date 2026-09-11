#!/usr/bin/env python3
"""Scan generated PDFs and metadata for watermark contamination."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import fitz


DEFAULT_PHRASES = ("training example", "not for filing")


def _pdfs_from_manifest(manifest: dict) -> list[Path]:
    return sorted(
        {
            Path(artifact["path"])
            for case in manifest.get("cases", [])
            for artifact in case.get("artifacts", {}).values()
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--phrase",
        action="append",
        dest="phrases",
        help="Case-insensitive phrase to reject; may be supplied more than once.",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    phrases = tuple(phrase.casefold() for phrase in (args.phrases or DEFAULT_PHRASES))
    pdfs = _pdfs_from_manifest(manifest)
    errors: list[str] = []
    matches: list[dict[str, object]] = []
    scanned_pages = 0

    if manifest.get("watermark"):
        errors.append(f"manifest watermark is not empty: {manifest['watermark']!r}")

    for pdf_path in pdfs:
        if not pdf_path.exists():
            errors.append(f"missing PDF: {pdf_path}")
            continue
        try:
            with fitz.open(pdf_path) as document:
                for page_number, page in enumerate(document, 1):
                    scanned_pages += 1
                    text = page.get_text("text").casefold()
                    found = [phrase for phrase in phrases if phrase in text]
                    if found:
                        matches.append(
                            {
                                "path": str(pdf_path),
                                "page": page_number,
                                "phrases": found,
                            }
                        )
        except Exception as exc:
            errors.append(f"{pdf_path}: {type(exc).__name__}: {exc}")

    if matches:
        errors.append(f"watermark phrases found on {len(matches):,} PDF pages")

    report = {
        "schema_version": "casebase.eta-no-watermark-audit.v1",
        "audited_at": datetime.now().astimezone().isoformat(),
        "manifest": str(args.manifest),
        "status": "pass" if not errors else "fail",
        "phrases_rejected": list(phrases),
        "manifest_watermark": manifest.get("watermark"),
        "pdfs_scanned": len(pdfs),
        "pages_scanned": scanned_pages,
        "matches": matches,
        "errors": errors,
    }
    output = args.output or args.manifest.with_name("watermark-audit.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
