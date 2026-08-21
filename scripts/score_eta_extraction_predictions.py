#!/usr/bin/env python3
"""Score JSON predictions against an ETA Unsloth split at document and field level."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, path))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}[{index}]"))
        if not value:
            result[prefix] = []
        return result
    return {prefix: value}


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.strip().split()).casefold()
    return value


def _prediction_value(record: dict[str, Any]) -> Any:
    value = record.get("prediction", record.get("output"))
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with args.gold.open("r", encoding="utf-8") as stream:
        gold = {record["id"]: record for line in stream if line.strip() for record in [json.loads(line)]}
    predictions = {}
    parse_errors = []
    with args.predictions.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                predictions[record["id"]] = _prediction_value(record)
            except Exception as exc:
                parse_errors.append({"line": number, "id": record.get("id"), "error": str(exc)})

    totals = Counter()
    by_task: dict[str, Counter] = {}
    per_document = []
    for example_id, record in gold.items():
        task = record["task"]
        task_totals = by_task.setdefault(task, Counter())
        target = record["target"]
        prediction = predictions.get(example_id)
        exact = prediction == target
        gold_fields = _flatten(target)
        predicted_fields = _flatten(prediction) if prediction is not None else {}
        correct = sum(
            path in predicted_fields
            and _normalize(predicted_fields[path]) == _normalize(value)
            for path, value in gold_fields.items()
        )
        missing = sum(path not in predicted_fields for path in gold_fields)
        extra = sum(path not in gold_fields for path in predicted_fields)
        for counter in (totals, task_totals):
            counter["documents"] += 1
            counter["documents_exact"] += exact
            counter["gold_fields"] += len(gold_fields)
            counter["fields_correct"] += correct
            counter["fields_missing"] += missing
            counter["fields_extra"] += extra
        per_document.append(
            {
                "id": example_id,
                "task": task,
                "json_present": prediction is not None,
                "exact": exact,
                "gold_fields": len(gold_fields),
                "fields_correct": correct,
                "fields_missing": missing,
                "fields_extra": extra,
                "field_accuracy": correct / len(gold_fields) if gold_fields else 1.0,
            }
        )

    def summarize(counter: Counter) -> dict[str, Any]:
        return {
            **dict(counter),
            "document_exact_match": counter["documents_exact"] / counter["documents"] if counter["documents"] else 0,
            "field_accuracy": counter["fields_correct"] / counter["gold_fields"] if counter["gold_fields"] else 0,
        }

    report = {
        "gold_file": str(args.gold),
        "predictions_file": str(args.predictions),
        "prediction_json_parse_errors": parse_errors,
        "overall": summarize(totals),
        "by_task": {task: summarize(counter) for task, counter in by_task.items()},
        "documents": per_document,
    }
    output = args.output or args.predictions.with_suffix(".score.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "documents"}, indent=2))


if __name__ == "__main__":
    main()
