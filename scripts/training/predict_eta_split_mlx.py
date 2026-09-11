#!/usr/bin/env python3
"""Generate resumable ETA extraction predictions with a selected MLX adapter."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from PIL import Image, ImageOps

from evaluate_eta_adapters_mlx import load_candidate
from train_eta_qwen3_vl_mlx import DEFAULT_MODEL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--image-size", type=int, default=384)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def load_records(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def resized_images(record: dict, package_root: Path, image_size: int) -> list[Image.Image]:
    result = []
    for relative in record["images"]:
        path = (package_root / relative).resolve()
        if not path.is_relative_to(package_root):
            raise ValueError(f"Image escapes package root: {relative}")
        with Image.open(path) as image:
            rgb = ImageOps.contain(
                image.convert("RGB"),
                (image_size, image_size),
                method=Image.Resampling.LANCZOS,
            )
            result.append(rgb.copy())
    return result


def main() -> None:
    args = parse_args()
    args.jsonl = args.jsonl.expanduser().resolve()
    args.package_root = args.package_root.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    selection = json.loads(args.selection.expanduser().resolve().read_text(encoding="utf-8"))
    selected = selection["selected"]
    checkpoint = Path(selected["checkpoint"])
    records = load_records(args.jsonl)
    if args.limit is not None:
        records = records[: args.limit]

    completed = set()
    if args.output.exists():
        with args.output.open("r", encoding="utf-8") as stream:
            completed = {json.loads(line)["id"] for line in stream if line.strip()}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    print(f"Loading selected adapter {selected['name']}: {checkpoint}", flush=True)
    model, processor = load_candidate(args.model, checkpoint)
    config = model.config.__dict__
    with args.output.open("a", encoding="utf-8") as output:
        for index, record in enumerate(records, 1):
            if record["id"] in completed:
                continue
            messages = deepcopy(record["messages"][:-1])
            images = resized_images(record, args.package_root, args.image_size)
            prompt = apply_chat_template(
                processor,
                config,
                messages,
                add_generation_prompt=True,
                num_images=len(images),
            )
            response = generate(
                model,
                processor,
                prompt,
                image=images,
                max_tokens=args.max_tokens,
                temperature=0.0,
                prefill_step_size=512,
                skip_special_tokens=True,
            )
            row = {
                "id": record["id"],
                "task": record["task"],
                "prediction": response.text.strip(),
                "adapter": selected["name"],
                "prompt_tokens": response.prompt_tokens,
                "generation_tokens": response.generation_tokens,
                "finish_reason": response.finish_reason,
            }
            output.write(json.dumps(row, separators=(",", ":")) + "\n")
            output.flush()
            completed.add(record["id"])
            print(
                f"prediction {len(completed)}/{len(records)} id={record['id']} "
                f"tokens={response.generation_tokens}",
                flush=True,
            )


if __name__ == "__main__":
    main()
