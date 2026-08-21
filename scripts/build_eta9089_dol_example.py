#!/usr/bin/env python3
"""Create canonical ETA-9089 JSON from one matched raw DOL disclosure pair."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.perm_verify.form_fill.dol_eta9089 import build_eta9089_form_data  # noqa: E402


def _row(path: Path, case_number: str) -> dict:
    frame = pd.read_excel(path, dtype=object)
    selected = frame[frame["CASE_NUMBER"].astype(str).eq(case_number)]
    if len(selected) != 1:
        raise ValueError(f"expected one {case_number} row in {path}, found {len(selected)}")
    out = {}
    for key, value in selected.iloc[0].items():
        if pd.isna(value):
            out[key] = None
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif hasattr(value, "item"):
            out[key] = value.item()
        else:
            out[key] = value
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perm-file", type=Path, required=True)
    parser.add_argument("--perm-case", required=True)
    parser.add_argument("--pwd-file", type=Path, required=True)
    parser.add_argument("--pwd-case", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    perm = _row(args.perm_file, args.perm_case)
    pwd = _row(args.pwd_file, args.pwd_case)
    payload = {
        "schema_version": "casebase.eta9089-fill.v1",
        "case_id": args.perm_case,
        "source": {
            "perm_file": str(args.perm_file),
            "perm_case_number": args.perm_case,
            "pwd_file": str(args.pwd_file),
            "pwd_case_number": args.pwd_case,
        },
        "privacy": {
            "dol_disclosure_data": True,
            "foreign_national": "synthetic training identity",
            "not_for_filing": True,
        },
        "form_data": build_eta9089_form_data(perm, pwd),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
