#!/usr/bin/env python3
"""Build case-isolated, native-resolution ETA-9089 section pilot data.

The generated JSONL keeps references to the original page JPEGs and records a
crop box.  Pixels are cropped at load time; they are not resized.  This avoids
duplicating the source corpus and, more importantly, prevents the unreadable
384-pixel whole-page inputs used by the first experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class SectionSpec:
    name: str
    page: int
    # Fractions of page width/height: left, top, right, bottom.
    box: tuple[float, float, float, float]
    paths: tuple[tuple[str, ...], ...]


def fields(root: str, *names: str) -> tuple[tuple[str, ...], ...]:
    return tuple((root, name) for name in names)


SECTION_SPECS = (
    SectionSpec(
        "A_identity",
        1,
        (0.075, 0.190, 0.930, 0.490),
        fields(
            "A_employer", "legal_business_name", "dba", "address1", "address2",
            "city", "state", "postal_code", "country", "province",
        ),
    ),
    SectionSpec(
        "A_numbers",
        1,
        (0.075, 0.455, 0.930, 0.625),
        fields(
            "A_employer", "phone", "extension", "fein", "naics_code",
            "num_employees_in_area", "year_commenced_business",
            "closely_held_ownership_interest", "familial_relationship",
        ),
    ),
    SectionSpec(
        "B_identity",
        1,
        (0.075, 0.610, 0.930, 0.795),
        fields(
            "B_poc", "last_name", "first_name", "middle_name", "job_title",
            "address1", "address2",
        ),
    ),
    SectionSpec(
        "B_contact",
        1,
        (0.075, 0.755, 0.930, 0.935),
        fields(
            "B_poc", "city", "state", "postal_code", "country", "province",
            "phone", "extension", "email",
        ),
    ),
    SectionSpec(
        "C_identity",
        2,
        (0.075, 0.115, 0.930, 0.350),
        fields(
            "C_attorney_agent", "representation_type", "last_name", "first_name",
            "middle_name", "address1", "address2",
        ),
    ),
    SectionSpec(
        "C_contact",
        2,
        (0.075, 0.315, 0.930, 0.545),
        fields(
            "C_attorney_agent", "city", "state", "postal_code", "country",
            "province", "phone", "extension", "email", "law_firm_name",
            "law_firm_fein", "state_bar_number", "state_of_good_standing",
            "highest_court_name",
        ),
    ),
    SectionSpec("D", 2, (0.075, 0.525, 0.930, 0.665), (("D_foreign_worker_flags",),)),
    SectionSpec(
        "E",
        2,
        (0.075, 0.645, 0.930, 0.950),
        (("E_job_wage",),),
    ),
    SectionSpec(
        "F_address",
        3,
        (0.075, 0.115, 0.930, 0.350),
        fields(
            "F_worksite", "worksite_type", "address1", "address2",
        ),
    ),
    SectionSpec(
        "F_geography",
        3,
        (0.075, 0.315, 0.930, 0.475),
        fields(
            "F_worksite", "city", "county", "state", "postal_code",
            "msa_oes_area_code", "msa_oes_area_title",
        ),
    ),
    SectionSpec(
        "F_additional",
        3,
        (0.075, 0.440, 0.930, 0.575),
        fields("F_worksite", "additional_worksites", "appendix_b_attached"),
    ),
    SectionSpec(
        "G_1_4",
        4,
        (0.075, 0.115, 0.930, 0.390),
        fields(
            "G_job_info", "full_time_35hrs", "live_in_domestic",
            "live_in_1yr_experience", "live_in_contract_executed",
            "live_in_contract_copy_provided", "accept_foreign_degree_equivalent",
            "fw_currently_employed",
        ),
    ),
    SectionSpec(
        "G_4_5",
        4,
        (0.075, 0.340, 0.930, 0.640),
        fields(
            "G_job_info", "fw_qualifies_only_by_alternative_reqs",
            "kellogg_suitable_combination", "relying_solely_on_experience_with_employer",
            "experience_substantially_comparable", "employer_paid_training",
        ),
    ),
    SectionSpec(
        "G_6_12",
        4,
        (0.075, 0.585, 0.930, 0.885),
        fields(
            "G_job_info",
            "live_on_premises",
            "combination_of_occupations",
            "foreign_language",
            "exceeds_svp",
            "credentialing_service",
            "employer_received_payment",
            "layoff_6mo",
        ),
    ),
    SectionSpec(
        "H_a_b",
        5,
        (0.075, 0.115, 0.930, 0.435),
        fields(
            "H_recruitment", "supervised_recruitment", "occupation_type",
        ),
    ),
    SectionSpec(
        "H_c",
        5,
        (0.075, 0.395, 0.930, 0.675),
        fields(
            "H_recruitment", "swa_job_order_start", "swa_job_order_end",
            "sunday_edition_exists", "ad1_newspaper_name", "ad1_date", "ad2_type",
            "ad2_name", "ad2_date",
        ),
    ),
    SectionSpec(
        "H_d_1_5",
        5,
        (0.075, 0.625, 0.930, 0.855),
        tuple(
            ("H_recruitment", "additional_steps", name)
            for name in (
                "job_fair",
                "employer_website",
                "job_search_website",
                "on_campus",
                "trade_org",
            )
        ),
    ),
    SectionSpec(
        "H_d_6_9",
        5,
        (0.075, 0.815, 0.930, 0.945),
        tuple(
            ("H_recruitment", "additional_steps", name)
            for name in (
                "private_firm",
                "employee_referral",
                "campus_placement",
                "local_ethnic_newspaper",
            )
        ),
    ),
    SectionSpec(
        "H_d10",
        6,
        (0.075, 0.115, 0.930, 0.205),
        (("H_recruitment", "additional_steps", "radio_tv"),),
    ),
    SectionSpec(
        "H_e",
        6,
        (0.075, 0.170, 0.930, 0.520),
        (("H_recruitment", "notice_of_posting"),),
    ),
    SectionSpec("I", 6, (0.075, 0.805, 0.930, 0.930), (("I_attestations",),)),
    SectionSpec("J", 7, (0.075, 0.115, 0.930, 0.335), (("J_preparer",),)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pilot-train-forms", type=int, default=250)
    parser.add_argument("--development-forms", type=int, default=20)
    parser.add_argument("--sealed-holdout-forms", type=int, default=250)
    parser.add_argument("--qa-forms", type=int, default=10)
    parser.add_argument("--seed", type=int, default=9089)
    return parser.parse_args()


def load_eta9089(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    return [record for record in records if record["task"] == "eta9089"]


def has_mojibake(record: dict[str, Any]) -> bool:
    serialized = json.dumps(record["target"], ensure_ascii=False)
    return any(marker in serialized for marker in ("â", "Ã", "Â", "ðŸ"))


def get_path(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        value = value[key]
    return value


def set_path(result: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = result
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


def section_target(target: dict[str, Any], spec: SectionSpec) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in spec.paths:
        set_path(result, path, get_path(target, path))
    return result


def section_record(record: dict[str, Any], spec: SectionSpec) -> dict[str, Any]:
    target = section_target(record["target"], spec)
    image = record["images"][spec.page - 1]
    prompt = (
        f"Read the native-resolution ETA-9089 crop for section {spec.name}. "
        "Transcribe the visible values and selections into exactly the JSON "
        "keys demonstrated by the answer. Return JSON only; use null for "
        "visibly blank optional fields and do not infer unseen information."
    )
    return {
        "id": f"{record['id']}:{spec.name}",
        "parent_id": record["id"],
        "case_id": record["case_id"],
        "task": "eta9089_section",
        "section": spec.name,
        "source_page": spec.page,
        "images": [image],
        "crop_box_fraction": list(spec.box),
        "target": target,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "image": image},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(target, separators=(",", ":")),
                    }
                ],
            },
        ],
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")


def crop_pixels(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    return image.crop(
        tuple(round(value * size) for value, size in zip(box, (width, height, width, height)))
    )


def write_contact_sheet(case_dir: Path) -> None:
    """Write a compact human-review sheet; source crops remain full resolution."""
    thumb_width = 360
    label_height = 26
    gap = 12
    tiles = []
    for spec in SECTION_SPECS:
        with Image.open(case_dir / f"{spec.name}.jpg") as image:
            thumb_height = round(image.height * thumb_width / image.width)
            thumb = image.convert("RGB").resize(
                (thumb_width, thumb_height), Image.Resampling.LANCZOS
            )
            tile = Image.new("RGB", (thumb_width, label_height + thumb_height), "white")
            ImageDraw.Draw(tile).text((6, 5), spec.name, fill="black")
            tile.paste(thumb, (0, label_height))
            tiles.append(tile)
    columns = 3
    rows = (len(tiles) + columns - 1) // columns
    row_heights = [
        max(tile.height for tile in tiles[row * columns : (row + 1) * columns])
        for row in range(rows)
    ]
    sheet = Image.new(
        "RGB",
        (columns * thumb_width + (columns - 1) * gap, sum(row_heights) + (rows - 1) * gap),
        "#dddddd",
    )
    y = 0
    for row, row_height in enumerate(row_heights):
        for column, tile in enumerate(tiles[row * columns : (row + 1) * columns]):
            sheet.paste(tile, (column * (thumb_width + gap), y))
        y += row_height + gap
    sheet.save(case_dir / "contact-sheet.jpg", quality=92)


def sha256_ids(ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode()).hexdigest()


def main() -> None:
    args = parse_args()
    package_root = args.package_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_train = load_eta9089(package_root / "data/train.jsonl")
    raw_validation = load_eta9089(package_root / "data/validation.jsonl")
    excluded_mojibake = {
        "train": [row["id"] for row in raw_train if has_mojibake(row)],
        "validation": [row["id"] for row in raw_validation if has_mojibake(row)],
    }
    train = [row for row in raw_train if not has_mojibake(row)]
    validation = [row for row in raw_validation if not has_mojibake(row)]
    rng = random.Random(args.seed)
    rng.shuffle(train)
    rng.shuffle(validation)

    needed_train = args.pilot_train_forms + args.sealed_holdout_forms
    if needed_train > len(train):
        raise SystemExit(f"Requested {needed_train} train forms; only {len(train)} exist")
    if args.development_forms > len(validation):
        raise SystemExit("Not enough ETA-9089 validation forms")

    pilot_forms = train[: args.pilot_train_forms]
    sealed_forms = train[
        args.pilot_train_forms : args.pilot_train_forms + args.sealed_holdout_forms
    ]
    development_forms = validation[: args.development_forms]
    groups = {
        "pilot_train": pilot_forms,
        "development": development_forms,
        "sealed_holdout": sealed_forms,
    }
    case_sets = {name: {row["case_id"] for row in rows} for name, rows in groups.items()}
    for left, right in (("pilot_train", "development"), ("pilot_train", "sealed_holdout"), ("development", "sealed_holdout")):
        overlap = case_sets[left] & case_sets[right]
        if overlap:
            raise SystemExit(f"Case leakage between {left} and {right}: {sorted(overlap)[:3]}")

    pilot_sections = [
        section_record(record, spec) for record in pilot_forms for spec in SECTION_SPECS
    ]
    development_sections = [
        section_record(record, spec)
        for record in development_forms
        for spec in SECTION_SPECS
    ]
    write_jsonl(output_dir / "pilot_train.sections.jsonl", pilot_sections)
    write_jsonl(output_dir / "development.sections.jsonl", development_sections)
    write_jsonl(output_dir / "development.full_forms.jsonl", development_forms)

    # The sealed set is intentionally represented only by IDs. Its labels and
    # section records are not emitted, making accidental tuning on it harder.
    manifest = {
        "seed": args.seed,
        "section_count_per_form": len(SECTION_SPECS),
        "excluded_mojibake": excluded_mojibake,
        "groups": {
            name: {
                "forms": len(rows),
                "case_ids": [row["case_id"] for row in rows],
                "case_ids_sha256": sha256_ids([row["case_id"] for row in rows]),
            }
            for name, rows in groups.items()
        },
    }
    (output_dir / "split_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    qa_root = output_dir / "qa_crops"
    for record in development_forms[: args.qa_forms]:
        case_dir = qa_root / record["case_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        for spec in SECTION_SPECS:
            source = (package_root / record["images"][spec.page - 1]).resolve()
            if not source.is_relative_to(package_root):
                raise ValueError(f"Image escapes package root: {source}")
            with Image.open(source) as image:
                crop = crop_pixels(image.convert("RGB"), spec.box)
                crop.save(case_dir / f"{spec.name}.jpg", quality=95)
        write_contact_sheet(case_dir)

    print(
        json.dumps(
            {
                "pilot_train_forms": len(pilot_forms),
                "pilot_train_sections": len(pilot_sections),
                "development_forms": len(development_forms),
                "development_sections": len(development_sections),
                "sealed_holdout_forms": len(sealed_forms),
                "qa_forms_rendered": min(args.qa_forms, len(development_forms)),
                "output_dir": str(output_dir),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
