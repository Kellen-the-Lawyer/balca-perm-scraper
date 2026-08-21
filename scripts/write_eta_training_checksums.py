#!/usr/bin/env python3
"""Write deterministic SHA-256 checksums for a portable ETA training package."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    root = args.package.resolve()
    output = root / "checksums.sha256"
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path != output
        and path.name != "verification-report.json"
        and ".records" not in path.relative_to(root).parts
        and "__pycache__" not in path.relative_to(root).parts
    )
    with output.open("w", encoding="utf-8") as stream:
        for index, path in enumerate(files, 1):
            stream.write(f"{_sha256(path)}  {path.relative_to(root)}\n")
            if index % 5000 == 0:
                print(f"Checksummed {index:,}/{len(files):,}", flush=True)
    print(f"Wrote {len(files):,} checksums to {output}")


if __name__ == "__main__":
    main()
