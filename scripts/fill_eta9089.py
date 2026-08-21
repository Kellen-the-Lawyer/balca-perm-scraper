#!/usr/bin/env python3
"""Fill the official ETA-9089 PDFs from canonical Casebase JSON.

This is the stable command-line entry point intended for reuse by a future
Casebase or Antigravity/Graphite form-filling service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.perm_verify.form_fill import fill_eta9089_package  # noqa: E402


def _form_data(payload: dict) -> dict:
    if "perm" in payload and isinstance(payload["perm"], dict):
        return payload["perm"].get("form_data", payload["perm"])
    return payload.get("form_data", payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill and verify the official ETA-9089 application and appendices."
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--templates-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--watermark",
        help="Optional visible watermark, e.g. 'TRAINING EXAMPLE - NOT FOR FILING'.",
    )
    args = parser.parse_args()

    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    result = fill_eta9089_package(
        _form_data(payload),
        args.templates_dir,
        args.output_dir,
        watermark=args.watermark,
    )
    manifest = args.output_dir / "fill-manifest.json"
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(manifest)


if __name__ == "__main__":
    main()
