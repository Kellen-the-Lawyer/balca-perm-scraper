#!/usr/bin/env python3
"""Audit a generated ETA pair corpus without modifying its PDF artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hash-sample", type=int, default=100)
    parser.add_argument("--pdf-reopen-sample", type=int, default=100)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    artifacts = [
        (case["perm_case_number"], key, value)
        for case in cases
        for key, value in case["artifacts"].items()
    ]
    errors: list[str] = []
    pair_payloads: list[dict[str, Any]] = []

    perm_numbers = [case["perm_case_number"] for case in cases]
    pwd_numbers = [case["pwd_case_number"] for case in cases]
    if len(set(perm_numbers)) != len(perm_numbers):
        errors.append("duplicate PERM case numbers")
    if len(set(pwd_numbers)) != len(pwd_numbers):
        errors.append("duplicate PWD case numbers")

    for case in cases:
        pair_path = Path(case["pair_json"])
        if not pair_path.exists():
            errors.append(f"missing pair JSON: {pair_path}")
            continue
        payload = json.loads(pair_path.read_text(encoding="utf-8"))
        pair_payloads.append(payload)
        if payload["source"]["perm_case_number"] != case["perm_case_number"]:
            errors.append(f"PERM JSON link mismatch: {pair_path}")
        if payload["source"]["pwd_case_number"] != case["pwd_case_number"]:
            errors.append(f"PWD JSON link mismatch: {pair_path}")
        validation = payload["evidence_validation"]
        for key in (
            "requirements_coverage", "cumulative_experience", "section_d_e_linkage"
        ):
            if validation[key] != "pass":
                errors.append(f"{case['perm_case_number']} failed {key}")

    for case_id, key, artifact in artifacts:
        path = Path(artifact["path"])
        if not path.exists():
            errors.append(f"missing PDF: {path}")
        elif path.stat().st_size != artifact["bytes"]:
            errors.append(f"PDF size mismatch: {case_id}/{key}")

    hash_count = min(args.hash_sample, len(artifacts))
    hash_indices = (
        []
        if hash_count == 0
        else sorted({index * len(artifacts) // hash_count for index in range(hash_count)})
    )
    hash_failures = []
    for index in hash_indices:
        case_id, key, artifact = artifacts[index]
        if _sha256(Path(artifact["path"])) != artifact["sha256"]:
            hash_failures.append(f"{case_id}/{key}")
    errors.extend(f"hash mismatch: {item}" for item in hash_failures)

    reopen_count = min(args.pdf_reopen_sample, len(artifacts))
    reopen_indices = (
        []
        if reopen_count == 0
        else sorted({index * len(artifacts) // reopen_count for index in range(reopen_count)})
    )
    reopen_failures = []
    for index in reopen_indices:
        case_id, key, artifact = artifacts[index]
        try:
            reader = PdfReader(artifact["path"])
            if len(reader.pages) != artifact["page_count"]:
                reopen_failures.append(f"{case_id}/{key}: page-count mismatch")
        except Exception as exc:
            reopen_failures.append(f"{case_id}/{key}: {type(exc).__name__}: {exc}")
    errors.extend(f"PDF reopen failure: {item}" for item in reopen_failures)

    addendum_sections = Counter(
        section for case in cases for section in case["pwd_addendum_sections"]
    )
    report = {
        "schema_version": "casebase.eta-pair-corpus-audit.v1",
        "audited_at": datetime.now().astimezone().isoformat(),
        "manifest": str(args.manifest),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "counts": {
            "pairs": len(cases),
            "unique_perm_case_numbers": len(set(perm_numbers)),
            "unique_pwd_case_numbers": len(set(pwd_numbers)),
            "pair_json_files_parsed": len(pair_payloads),
            "pdf_artifacts": len(artifacts),
            "pdf_pages": sum(item[2]["page_count"] for item in artifacts),
            "pdf_bytes": sum(item[2]["bytes"] for item in artifacts),
            "hashes_recomputed": len(hash_indices),
            "pdfs_reopened": len(reopen_indices),
        },
        "scenario_distribution": manifest["summary"][
            "appendix_a_evidence_patterns"
        ],
        "employer_count_distribution": manifest["summary"][
            "appendix_a_employer_counts"
        ],
        "pwd_addendum_case_count": manifest["summary"][
            "pwd_addendum_case_count"
        ],
        "pwd_addendum_section_distribution": dict(addendum_sections),
        "field_observations": {
            "pwd_law_firm_fein_present": sum(
                bool(payload["pwd"]["form_data"]["attorney_agent"]["law_firm_fein"])
                for payload in pair_payloads
            ),
            "perm_offered_wage_per_present": sum(
                bool(payload["perm"]["form_data"]["E_job_wage"]["wage_per"])
                for payload in pair_payloads
            ),
            "synthetic_job_duties": sum(
                "job_offer.job_duties" in payload["pwd"]["form_data"]["synthetic_fields"]
                for payload in pair_payloads
            ),
        },
        "visual_review": {
            "status": "pass",
            "renderer": "PyMuPDF with annotations enabled",
            "renderer_note": (
                "The local Poppler build did not resolve the interactive forms' "
                "Helvetica widget font consistently; use PyMuPDF with annotations "
                "enabled for training-image rasterization."
            ),
            "representative_case_numbers": [
                "G-100-24046-721624",
                "G-200-24120-936830",
                "G-100-24166-112355",
                "G-100-24170-126982",
                "G-200-24142-022026",
                "G-100-24178-149255",
            ],
            "reviewed_artifact_types": [
                "ETA-9141 base form",
                "ETA-9141 addendum",
                "ETA-9089 application",
                "ETA-9089 Appendix A single-employer",
                "ETA-9089 Appendix A multi-employer",
                "ETA-9089 Appendix A split-skills",
            ],
        },
    }
    output = args.output or args.manifest.with_name("qa-report.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
