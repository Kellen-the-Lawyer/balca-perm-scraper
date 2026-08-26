#!/usr/bin/env python3
"""Fine-tune Qwen3-VL on the portable ETA JSONL package with MLX.

This entry point is intentionally separate from the package's Unsloth trainer:
Unsloth targets CUDA, while this script uses MLX on Apple Silicon. Images are
opened lazily so the 24 GiB corpus is neither copied nor loaded into memory.
"""

from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


DEFAULT_MODEL = "mlx-community/Qwen3-VL-4B-Instruct-4bit"


class PortableETADataset:
    """Expose portable ETA JSONL records in MLX-VLM's dataset format."""

    def __init__(
        self,
        jsonl_path: Path,
        package_root: Path | None = None,
        limit: int | None = None,
        limit_per_task: int | None = None,
        image_size: int | None = None,
        tasks: set[str] | None = None,
        max_pages: int | None = None,
    ) -> None:
        self.jsonl_path = jsonl_path.expanduser().resolve()
        self.package_root = (
            package_root.expanduser().resolve()
            if package_root
            else self.jsonl_path.parents[1]
        )
        self.image_size = image_size
        self.max_pages = max_pages
        with self.jsonl_path.open("r", encoding="utf-8") as stream:
            self.records = [json.loads(line) for line in stream if line.strip()]
        if tasks:
            self.records = [record for record in self.records if record["task"] in tasks]
        if limit_per_task is not None:
            if limit_per_task < 1:
                raise ValueError("limit_per_task must be at least 1")
            counts: dict[str, int] = {}
            selected = []
            for record in self.records:
                task = record["task"]
                if counts.get(task, 0) < limit_per_task:
                    selected.append(record)
                    counts[task] = counts.get(task, 0) + 1
            self.records = selected
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be at least 1")
            self.records = self.records[:limit]
        if not self.records:
            raise ValueError(f"No examples found in {self.jsonl_path}")

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, Any]:
        record = self.records[index]
        image_paths = record["images"]
        if self.max_pages is not None:
            if self.max_pages < 1:
                raise ValueError("max_pages must be at least 1")
            image_paths = image_paths[: self.max_pages]
        images = []
        for relative_path in image_paths:
            image_path = (self.package_root / relative_path).resolve()
            if not image_path.is_relative_to(self.package_root):
                raise ValueError(f"Image escapes package root: {relative_path}")
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
                crop_fraction = record.get("crop_box_fraction")
                if crop_fraction is not None:
                    if len(image_paths) != 1 or len(crop_fraction) != 4:
                        raise ValueError(
                            "crop_box_fraction requires exactly one image and four values"
                        )
                    width, height = rgb.size
                    box = tuple(
                        round(value * size)
                        for value, size in zip(
                            crop_fraction, (width, height, width, height)
                        )
                    )
                    rgb = rgb.crop(box)
                if self.image_size is not None:
                    rgb = ImageOps.contain(
                        rgb,
                        (self.image_size, self.image_size),
                        method=Image.Resampling.LANCZOS,
                    )
                images.append(rgb.copy())

        # MLX-VLM uses the explicit image markers in messages to allocate the
        # separately supplied PIL images. Avoid mutating the source records.
        messages = deepcopy(record["messages"])
        if self.max_pages is not None:
            selected = set(image_paths)
            for message in messages:
                message["content"] = [
                    item
                    for item in message["content"]
                    if item.get("type") != "image" or item.get("image") in selected
                ]
        return {"images": images, "messages": messages}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LoRA/QLoRA fine-tuning for the Casebase ETA corpus on Apple Silicon"
    )
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--eval-jsonl", type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/eta-qwen3-vl-mlx")
    )
    parser.add_argument("--epochs", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--limit-train", type=int)
    parser.add_argument("--limit-eval", type=int)
    parser.add_argument("--limit-per-task", type=int)
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        help="Restrict training to a task; repeat to select multiple tasks",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--image-size", type=int, default=384)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=float, default=16)
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--logging-steps", type=int, default=1)
    parser.add_argument("--eval-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=10)
    parser.add_argument("--val-batches", type=int, default=1)
    parser.add_argument("--grad-clip", type=float, default=1.0)
    parser.add_argument("--no-grad-checkpoint", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.model.lower().endswith(".gguf"):
        raise SystemExit(
            "MLX training cannot use GGUF weights. Use an MLX safetensors "
            f"checkpoint such as {DEFAULT_MODEL}."
        )
    if args.batch_size < 1 or args.gradient_accumulation < 1:
        raise SystemExit("batch size and gradient accumulation must be at least 1")

    train_source = PortableETADataset(
        args.train_jsonl,
        args.package_root,
        limit=args.limit_train,
        limit_per_task=args.limit_per_task,
        image_size=args.image_size,
        tasks=set(args.tasks) if args.tasks else None,
        max_pages=args.max_pages,
    )
    eval_source = (
        PortableETADataset(
            args.eval_jsonl,
            args.package_root,
            limit=args.limit_eval,
            limit_per_task=args.limit_per_task,
            image_size=args.image_size,
            tasks=set(args.tasks) if args.tasks else None,
            max_pages=args.max_pages,
        )
        if args.eval_jsonl
        else None
    )
    if args.epochs is not None:
        if args.epochs <= 0:
            raise SystemExit("epochs must be greater than zero")
        steps = max(1, math.ceil(len(train_source) / args.batch_size * args.epochs))
    else:
        if args.max_steps < 1:
            raise SystemExit("max-steps must be at least 1")
        steps = args.max_steps

    # Delayed imports keep dataset inspection usable in non-Metal environments.
    import mlx.optimizers as optim
    from mlx_vlm.trainer.datasets import VisionDataset
    from mlx_vlm.trainer.sft_trainer import TrainingArgs, train
    from mlx_vlm.trainer.utils import (
        find_all_linear_names,
        get_peft_model,
        print_trainable_parameters,
    )
    from mlx_vlm.utils import load

    print(f"Loading {args.model}")
    model, processor = load(
        args.model, processor_config={"trust_remote_code": True}
    )
    config = model.config.__dict__
    train_dataset = VisionDataset(
        train_source,
        config,
        processor,
        image_resize_shape=None,
        train_on_completions=True,
    )
    eval_dataset = (
        VisionDataset(
            eval_source,
            config,
            processor,
            image_resize_shape=None,
            train_on_completions=True,
        )
        if eval_source
        else None
    )

    targets = find_all_linear_names(model.language_model)
    model = get_peft_model(
        model,
        targets,
        rank=args.rank,
        alpha=args.alpha,
        dropout=args.dropout,
        verbose=False,
    )
    print_trainable_parameters(model)

    accumulation_steps = min(args.gradient_accumulation, steps)
    output_dir = args.output_dir.expanduser().resolve()
    adapter_file = output_dir / "adapters.safetensors"
    optimizer = optim.AdamW(
        learning_rate=args.learning_rate, weight_decay=args.weight_decay
    )
    training_args = TrainingArgs(
        batch_size=args.batch_size,
        iters=steps,
        val_batches=args.val_batches,
        steps_per_report=args.logging_steps,
        steps_per_eval=args.eval_steps,
        steps_per_save=args.save_steps,
        max_seq_length=args.max_length,
        adapter_file=str(adapter_file),
        grad_checkpoint=not args.no_grad_checkpoint,
        learning_rate=args.learning_rate,
        grad_clip=args.grad_clip,
        warmup_steps=min(max(1, int(steps * 0.03)), max(1, steps - 1)),
        min_learning_rate=args.learning_rate * 0.1,
        gradient_accumulation_steps=accumulation_steps,
    )
    print(
        f"Training {len(train_source)} examples for {steps} micro-steps; "
        f"effective batch={args.batch_size * accumulation_steps}"
    )
    train(
        model=model,
        optimizer=optimizer,
        train_dataset=train_dataset,
        val_dataset=eval_dataset,
        args=training_args,
        train_on_completions=True,
    )
    print(f"Saved adapter to {adapter_file}")


if __name__ == "__main__":
    main()
