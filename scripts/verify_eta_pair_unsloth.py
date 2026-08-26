#!/usr/bin/env python3
"""Verify Casebase's portable Unsloth vision dataset after generation or transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--verify-all-images", action="store_true")
    parser.add_argument("--verify-checksums", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = args.package.resolve()

    records = []
    split_cases: dict[str, set[str]] = {}
    errors = []
    for split in ("train", "validation", "test"):
        path = root / "data" / f"{split}.jsonl"
        split_cases[split] = set()
        with path.open("r", encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                    records.append(record)
                    split_cases[split].add(record["case_id"])
                    if record["split"] != split:
                        errors.append(f"{path}:{number}: split mismatch")
                    expected = json.dumps(
                        record["target"], ensure_ascii=False, separators=(",", ":")
                    )
                    actual = record["messages"][-1]["content"][0]["text"]
                    if actual != expected:
                        errors.append(f"{path}:{number}: assistant target mismatch")
                    for image in record["images"]:
                        image_path = root / image
                        if not image_path.exists() or image_path.stat().st_size == 0:
                            errors.append(f"{path}:{number}: missing image {image}")
                except Exception as exc:
                    errors.append(f"{path}:{number}: {type(exc).__name__}: {exc}")

    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        overlap = split_cases[left] & split_cases[right]
        if overlap:
            errors.append(f"case leakage between {left} and {right}: {len(overlap)}")

    image_paths = sorted((root / "images").rglob("*.jpg"))
    inspect_paths = image_paths if args.verify_all_images else image_paths[:: max(1, len(image_paths) // 200)]
    image_errors = []
    for path in inspect_paths:
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            image_errors.append(f"{path.relative_to(root)}: {type(exc).__name__}: {exc}")
    errors.extend(image_errors)

    checksum_count = 0
    if args.verify_checksums:
        checksum_path = root / "checksums.sha256"
        with checksum_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                expected, relative = line.rstrip("\n").split("  ", 1)
                checksum_count += 1
                if _sha256(root / relative) != expected:
                    errors.append(f"checksum mismatch: {relative}")

    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "record_count": len(records),
        "case_counts": {key: len(value) for key, value in split_cases.items()},
        "task_counts": dict(Counter(record["task"] for record in records)),
        "image_count": len(image_paths),
        "images_opened": len(inspect_paths),
        "checksums_verified": checksum_count,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
