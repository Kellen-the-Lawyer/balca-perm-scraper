#!/usr/bin/env python3
"""Export the ETA pair corpus as a self-contained Unsloth vision dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import fitz


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.perm_verify.form_fill.eta9141_addendum import (  # noqa: E402
    eta9141_addendum_sections,
)


TASK_PROMPTS = {
    "eta9141": (
        "Extract this complete ETA-9141 prevailing wage application into the "
        "canonical JSON schema demonstrated by the training examples. Read every "
        "page, preserve exact names, identifiers, dates, addresses, requirements, "
        "checkbox answers, wage values, and addendum references. Return JSON only. "
        "Use empty strings for visibly blank optional text fields and do not infer "
        "facts that are not shown."
    ),
    "eta9141_addendum": (
        "Extract every continued ETA-9141 addendum section from these pages. Return "
        "a JSON array in page order. Each item must contain section, title, and "
        "content. Preserve the wording shown and return JSON only."
    ),
    "eta9089": (
        "Extract this complete ETA-9089 Application for Permanent Employment "
        "Certification into the canonical JSON schema demonstrated by the training "
        "examples. Read every page and preserve exact employer, contact, attorney, "
        "wage, worksite, job, recruitment, attestation, and preparer information. "
        "Return JSON only. Use empty strings for visibly blank optional text fields "
        "and do not infer facts that are not shown."
    ),
    "eta9089_appendix_a": (
        "Extract this complete ETA-9089 Appendix A into the canonical JSON schema "
        "demonstrated by the training examples. Read every page and preserve the "
        "foreign worker contact, education, training, skills, and the one employer "
        "experience record shown in this appendix. Return JSON only. Use empty "
        "strings for visibly blank optional text fields and do not infer facts that "
        "are not shown."
    ),
}


def _stable_score(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _clean(value: Any) -> Any:
    """Remove provenance/training keys which are not visible on the rendered form."""

    hidden = {
        "synthetic",
        "synthetic_fields",
        "evidence_pattern",
        "requirements",
        "required_experience_months",
        "credited_experience_months",
        "credited_months",
        "evidence_requirement_ids",
        "experience_index",
        "requirement_ids",
    }
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if key not in hidden}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _pwd_target(pair: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(pair["pwd"]["render_form_data"])
    data.pop("synthetic_fields", None)
    meta = dict(data.get("meta") or {})
    meta.pop("case_status", None)
    data["meta"] = meta
    return _clean(data)


def _perm_target(pair: Mapping[str, Any]) -> dict[str, Any]:
    data = pair["perm"]["form_data"]
    return _clean(
        {
            key: value
            for key, value in data.items()
            if key not in {"meta", "appendix_A", "appendix_B", "appendix_C", "appendix_D"}
        }
    )


def _appendix_target(pair: Mapping[str, Any], index: int) -> dict[str, Any]:
    source = pair["perm"]["form_data"]["appendix_A"]
    experiences = source.get("work_experience") or []
    experience = experiences[index] if index < len(experiences) else {}
    skills = [
        item
        for item in (source.get("skills") or [])
        if int(item.get("experience_index", 0) or 0) == index
    ]
    return _clean(
        {
            "contact": source.get("contact") or {},
            "education": source.get("education") or [],
            "training": source.get("training") or [],
            "skills": skills,
            "work_experience": [experience] if experience else [],
        }
    )


def _addendum_target(pair: Mapping[str, Any]) -> list[dict[str, str]]:
    return eta9141_addendum_sections(pair["pwd"]["form_data"])


def _document_specs(
    case: Mapping[str, Any], pair: Mapping[str, Any]
) -> list[dict[str, Any]]:
    artifacts = case["artifacts"]
    specs = [
        {
            "document_id": "eta9141",
            "task": "eta9141",
            "artifact": artifacts["eta9141"],
            "target": _pwd_target(pair),
        },
        {
            "document_id": "eta9089",
            "task": "eta9089",
            "artifact": artifacts["eta9089"],
            "target": _perm_target(pair),
        },
    ]
    if "eta9141_addendum" in artifacts:
        specs.append(
            {
                "document_id": "eta9141_addendum",
                "task": "eta9141_addendum",
                "artifact": artifacts["eta9141_addendum"],
                "target": _addendum_target(pair),
            }
        )
    appendix_keys = sorted(
        (key for key in artifacts if key.startswith("eta9089_appendix_a")),
        key=lambda key: 1 if key == "eta9089_appendix_a" else int(key.rsplit("_", 1)[1]),
    )
    for index, key in enumerate(appendix_keys):
        specs.append(
            {
                "document_id": "eta9089_appendix_a_1" if index == 0 else f"eta9089_appendix_a_{index + 1}",
                "task": "eta9089_appendix_a",
                "artifact": artifacts[key],
                "target": _appendix_target(pair, index),
                "employer_index": index,
            }
        )
    return specs


def _split_cases(cases: list[Mapping[str, Any]], seed: int) -> dict[str, str]:
    case_ids = [str(case["perm_case_number"]) for case in cases]
    rng = random.Random(seed)
    rng.shuffle(case_ids)
    train_end = round(len(case_ids) * 0.90)
    validation_end = train_end + round(len(case_ids) * 0.05)
    result = {}
    for index, case_id in enumerate(case_ids):
        result[case_id] = (
            "train"
            if index < train_end
            else "validation" if index < validation_end else "test"
        )
    return result


def _render_document(task: Mapping[str, Any]) -> dict[str, Any]:
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    source = Path(task["source_pdf"])
    package_root = Path(task["package_root"])
    image_dir = package_root / task["image_dir"]
    image_dir.mkdir(parents=True, exist_ok=True)
    expected_pages = int(task["page_count"])
    image_paths = [image_dir / f"page-{index:03d}.jpg" for index in range(1, expected_pages + 1)]
    if not all(path.exists() and path.stat().st_size > 0 for path in image_paths):
        document = fitz.open(source)
        try:
            if len(document) != expected_pages:
                raise ValueError(
                    f"{source} has {len(document)} pages; manifest says {expected_pages}"
                )
            matrix = fitz.Matrix(float(task["dpi"]) / 72.0, float(task["dpi"]) / 72.0)
            for index, page in enumerate(document, 1):
                output = image_paths[index - 1]
                if output.exists() and output.stat().st_size > 0:
                    continue
                pixmap = page.get_pixmap(
                    matrix=matrix,
                    colorspace=fitz.csRGB,
                    alpha=False,
                    annots=True,
                )
                payload = pixmap.tobytes("jpeg", jpg_quality=int(task["jpeg_quality"]))
                temporary = output.with_suffix(".jpg.incomplete")
                temporary.write_bytes(payload)
                temporary.replace(output)
        finally:
            document.close()
    relative_images = [str(path.relative_to(package_root)) for path in image_paths]
    target_text = _compact_json(task["target"])
    user_content = [{"type": "text", "text": TASK_PROMPTS[task["task"]]}]
    user_content.extend({"type": "image", "image": path} for path in relative_images)
    return {
        "id": task["example_id"],
        "split": task["split"],
        "task": task["task"],
        "case_id": task["case_id"],
        "pwd_case_number": task["pwd_case_number"],
        "document_id": task["document_id"],
        "images": relative_images,
        "target": task["target"],
        "messages": [
            {"role": "user", "content": user_content},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": target_text}],
            },
        ],
        "source": {
            "pdf": task["source_pdf"],
            "pdf_sha256": task["pdf_sha256"],
            "pdf_page_count": expected_pages,
        },
        "render": {
            "renderer": "PyMuPDF",
            "dpi": task["dpi"],
            "format": "jpeg",
            "quality": task["jpeg_quality"],
            "annotations": True,
        },
    }


def _write_jsonl(path: Path, records: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "output/json/eta_pair_full_5000/full-manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/training/eta_pair_unsloth_v1",
    )
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--jpeg-quality", type=int, default=88)
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-checksums", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    all_cases = list(manifest["cases"])
    splits = _split_cases(all_cases, args.seed)
    cases = all_cases
    if args.limit_cases:
        cases = sorted(cases, key=lambda case: _stable_score(case["perm_case_number"]))[
            : args.limit_cases
        ]

    args.output.mkdir(parents=True, exist_ok=True)
    tasks = []
    planned = {"train": 0, "validation": 0, "test": 0}
    planned_pages = 0
    task_counts: dict[str, int] = {}
    for case in cases:
        case_id = str(case["perm_case_number"])
        split = splits[case_id]
        pair = json.loads(Path(case["pair_json"]).read_text(encoding="utf-8"))
        for spec in _document_specs(case, pair):
            document_id = spec["document_id"]
            example_id = f"{case_id}:{document_id}"
            page_count = int(spec["artifact"]["page_count"])
            image_dir = Path("images") / split / case_id / document_id
            tasks.append(
                {
                    "example_id": example_id,
                    "case_id": case_id,
                    "pwd_case_number": case["pwd_case_number"],
                    "split": split,
                    "document_id": document_id,
                    "task": spec["task"],
                    "target": spec["target"],
                    "source_pdf": spec["artifact"]["path"],
                    "pdf_sha256": spec["artifact"]["sha256"],
                    "page_count": page_count,
                    "image_dir": str(image_dir),
                    "package_root": str(args.output),
                    "dpi": args.dpi,
                    "jpeg_quality": args.jpeg_quality,
                }
            )
            planned[split] += 1
            planned_pages += page_count
            task_counts[spec["task"]] = task_counts.get(spec["task"], 0) + 1

    plan = {
        "schema_version": "casebase.unsloth-export-plan.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_manifest": str(args.manifest),
        "case_count": len(cases),
        "split_case_counts": {
            split: sum(splits[case["perm_case_number"]] == split for case in cases)
            for split in ("train", "validation", "test")
        },
        "example_count": len(tasks),
        "split_example_counts": planned,
        "task_counts": task_counts,
        "image_count": planned_pages,
        "render": {"dpi": args.dpi, "format": "jpeg", "quality": args.jpeg_quality},
        "seed": args.seed,
    }
    plan_path = args.output / "export-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2), flush=True)
    if args.plan_only:
        return

    checkpoint_dir = args.output / ".records"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    pending = []
    for task in tasks:
        checkpoint = checkpoint_dir / f"{task['example_id'].replace(':', '__')}.json"
        if checkpoint.exists():
            try:
                record = json.loads(checkpoint.read_text(encoding="utf-8"))
                if all((args.output / image).exists() for image in record["images"]):
                    records.append(record)
                    continue
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
        pending.append((task, checkpoint))

    print(
        f"Rendering {len(pending):,} documents; {len(records):,} resumed from checkpoints",
        flush=True,
    )
    failures = []
    if pending:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_render_document, task): (task, checkpoint)
                for task, checkpoint in pending
            }
            for future in as_completed(futures):
                task, checkpoint = futures[future]
                try:
                    record = future.result()
                    checkpoint.write_text(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    records.append(record)
                except Exception as exc:
                    failures.append(
                        {"example_id": task["example_id"], "error": f"{type(exc).__name__}: {exc}"}
                    )
                finished = len(records) + len(failures)
                if finished % 100 == 0 or finished == len(tasks):
                    print(
                        f"Progress {finished:,}/{len(tasks):,}: "
                        f"{len(records):,} complete, {len(failures):,} failed",
                        flush=True,
                    )

    records.sort(key=lambda item: item["id"])
    for split in ("train", "validation", "test"):
        subset = [record for record in records if record["split"] == split]
        _write_jsonl(args.output / "data" / f"{split}.jsonl", subset)
        for task_name in TASK_PROMPTS:
            _write_jsonl(
                args.output / "data" / "by_task" / f"{task_name}_{split}.jsonl",
                [record for record in subset if record["task"] == task_name],
            )

    train_records = [record for record in records if record["split"] == "train"]
    validation_records = [record for record in records if record["split"] == "validation"]
    _write_jsonl(args.output / "data" / "smoke_train_64.jsonl", train_records[:64])
    _write_jsonl(args.output / "data" / "smoke_validation_16.jsonl", validation_records[:16])

    provenance_dir = args.output / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    for source in (
        args.manifest,
        args.manifest.with_name("qa-report.json"),
        args.manifest.with_name("README.md"),
    ):
        if source.exists():
            shutil.copy2(source, provenance_dir / source.name)

    image_files = sorted((args.output / "images").rglob("*.jpg"))
    jsonl_files = sorted((args.output / "data").rglob("*.jsonl"))
    output_files = [plan_path, *jsonl_files]
    checksum_path = args.output / "checksums.sha256"
    if not args.skip_checksums:
        with checksum_path.open("w", encoding="utf-8") as stream:
            for index, path in enumerate([*image_files, *output_files], 1):
                stream.write(f"{_sha256(path)}  {path.relative_to(args.output)}\n")
                if index % 5000 == 0:
                    print(f"Checksummed {index:,} files", flush=True)

    final = {
        "schema_version": "casebase.unsloth-dataset.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "status": "complete" if not failures and len(records) == len(tasks) else "incomplete",
        "source_manifest": str(args.manifest),
        "case_count": len(cases),
        "example_count": len(records),
        "image_count": len(image_files),
        "image_bytes": sum(path.stat().st_size for path in image_files),
        "split_example_counts": {
            split: sum(record["split"] == split for record in records)
            for split in ("train", "validation", "test")
        },
        "task_counts": {
            task: sum(record["task"] == task for record in records)
            for task in TASK_PROMPTS
        },
        "render": plan["render"],
        "failures": failures,
        "checksums": str(checksum_path.relative_to(args.output)) if not args.skip_checksums else None,
    }
    manifest_path = args.output / "dataset-manifest.json"
    manifest_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, indent=2), flush=True)
    if final["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
