#!/usr/bin/env python3
"""Evaluate one or more MLX LoRA checkpoints on a complete ETA split."""

from __future__ import annotations

import argparse
import gc
import json
from collections import defaultdict
from pathlib import Path

from train_eta_qwen3_vl_mlx import DEFAULT_MODEL, PortableETADataset


class DatasetView:
    """Present a suffix of an MLX-VLM dataset without copying it."""

    def __init__(self, dataset, offset: int) -> None:
        self.dataset = dataset
        self.offset = offset
        self.config = dataset.config

    def __len__(self) -> int:
        return len(self.dataset) - self.offset

    def __getitem__(self, index: int):
        return self.dataset[self.offset + index]


def parse_candidate(value: str) -> tuple[str, Path]:
    try:
        name, path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("candidate must be NAME=/path/to/checkpoint") from exc
    checkpoint = Path(path).expanduser().resolve()
    if not name or not checkpoint.is_file():
        raise argparse.ArgumentTypeError(f"invalid candidate: {value}")
    return name, checkpoint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--candidate", type=parse_candidate, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--image-size", type=int, default=384)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def load_candidate(model_name: str, checkpoint: Path):
    from mlx_vlm.trainer.utils import _apply_lora_layers
    from mlx_vlm.utils import load

    config_path = checkpoint.parent / "adapter_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model, processor = load(
        model_name, processor_config={"trust_remote_code": True}
    )
    model = _apply_lora_layers(model, config)
    model.load_weights(str(checkpoint), strict=False)
    model.eval()
    return model, processor


def summarize(rows: list[dict]) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets["overall"].append(row)
        buckets[row["task"]].append(row)

    result = {}
    for name, items in buckets.items():
        tokens = sum(item["tokens"] for item in items)
        result[name] = {
            "examples": len(items),
            "tokens": tokens,
            "loss": (
                sum(item["loss"] * item["tokens"] for item in items) / tokens
                if tokens
                else None
            ),
        }
    return result


def evaluate_candidate(args, name: str, checkpoint: Path, source) -> dict:
    import mlx.core as mx
    from mlx_vlm.trainer.datasets import VisionDataset
    from mlx_vlm.trainer.sft_trainer import iterate_batches, vision_language_loss_fn

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = args.output_dir / f"{name}.validation.jsonl"
    rows = []
    if rows_path.exists():
        with rows_path.open("r", encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
    if len(rows) > len(source):
        raise ValueError(f"{rows_path} has more rows than the source split")

    print(f"Loading candidate {name}: {checkpoint}", flush=True)
    model, processor = load_candidate(args.model, checkpoint)
    dataset = VisionDataset(
        source,
        model.config.__dict__,
        processor,
        image_resize_shape=None,
        train_on_completions=True,
    )

    offset = len(rows)
    view = DatasetView(dataset, offset)
    with rows_path.open("a", encoding="utf-8") as output:
        for position, batch in enumerate(
            iterate_batches(view, batch_size=1, max_seq_length=args.max_length),
            start=offset,
        ):
            loss = vision_language_loss_fn(
                model, batch, train_on_completions=True
            )
            tokens = batch["attention_mask"].sum()
            mx.eval(loss, tokens)
            row = {
                "id": source.records[position]["id"],
                "task": source.records[position]["task"],
                "loss": float(loss.item()),
                "tokens": int(tokens.item()),
            }
            output.write(json.dumps(row, separators=(",", ":")) + "\n")
            output.flush()
            rows.append(row)
            if len(rows) % 25 == 0 or len(rows) == len(source):
                current = summarize(rows)["overall"]["loss"]
                print(
                    f"{name}: {len(rows)}/{len(source)} loss={current:.6f}",
                    flush=True,
                )
            mx.clear_cache()

    summary = {
        "name": name,
        "checkpoint": str(checkpoint),
        "split": str(args.jsonl.expanduser().resolve()),
        "metrics": summarize(rows),
    }
    (args.output_dir / f"{name}.validation.summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    del dataset, processor, model
    gc.collect()
    mx.clear_cache()
    return summary


def main() -> None:
    args = parse_args()
    args.jsonl = args.jsonl.expanduser().resolve()
    args.package_root = args.package_root.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    source = PortableETADataset(
        args.jsonl,
        args.package_root,
        limit=args.limit,
        image_size=args.image_size,
    )
    summaries = [
        evaluate_candidate(args, name, checkpoint, source)
        for name, checkpoint in args.candidate
    ]
    winner = min(summaries, key=lambda item: item["metrics"]["overall"]["loss"])
    selection = {"selected": winner, "candidates": summaries}
    (args.output_dir / "selection.json").write_text(
        json.dumps(selection, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(selection, indent=2), flush=True)


if __name__ == "__main__":
    main()
