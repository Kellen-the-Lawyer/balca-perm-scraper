#!/usr/bin/env python3
"""Regenerate the checked-in JSON Schema for paired PWD/PERM records."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.perm_verify.synthetic.models import PermPwdPair  # noqa: E402


OUTPUT = ROOT / "app/perm_verify/synthetic/schemas/perm_pwd_pair.v1.schema.json"


def main() -> None:
    OUTPUT.write_text(
        json.dumps(PermPwdPair.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
