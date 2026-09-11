#!/usr/bin/env python3
"""Run every crop of one ETA-9089 through a full-vision backward pass."""

from __future__ import annotations

import argparse
import json
import time
from functools import partial
from pathlib import Path

from mlx.utils import tree_flatten

from train_eta_qwen3_vl_mlx import DEFAULT_MODEL, PortableETADataset
from train_eta9089_sections_fullvision_mlx import build_optimizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=float, default=16)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--vision-learning-rate", type=float, default=1e-6)
    parser.add_argument("--language-learning-rate", type=float, default=2e-5)
    return parser.parse_args()


class FirstFormView:
    def __init__(self, source: PortableETADataset) -> None:
        first_parent = source.records[0]["parent_id"]
        self.source = source
        self.indices = [
            index
            for index, record in enumerate(source.records)
            if record["parent_id"] == first_parent
        ]
        self.config = None

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int):
        return self.source[self.indices[index]]


def main() -> None:
    args = parse_args()
    args.jsonl = args.jsonl.expanduser().resolve()
    args.package_root = args.package_root.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Native pixels: image_size=None is deliberate and is part of qualification.
    source = PortableETADataset(args.jsonl, args.package_root, image_size=None)
    first_parent = source.records[0]["parent_id"]
    selected = [row for row in source.records if row["parent_id"] == first_parent]
    if len(selected) < 10:
        raise SystemExit(f"Expected a complete sectionized form; found {len(selected)} crops")

    import mlx.core as mx
    import mlx.nn as nn
    from mlx_vlm.trainer.datasets import VisionDataset
    from mlx_vlm.trainer.sft_trainer import iterate_batches, vision_language_loss_fn
    from mlx_vlm.trainer.utils import (
        find_all_linear_names,
        get_peft_model,
        grad_checkpoint,
        print_trainable_parameters,
    )
    from mlx_vlm.utils import load

    print(f"Loading {args.model}", flush=True)
    model, processor = load(args.model, processor_config={"trust_remote_code": True})
    targets = find_all_linear_names(model.language_model)
    model = get_peft_model(
        model,
        targets,
        rank=args.rank,
        alpha=args.alpha,
        dropout=0.0,
        freeze=True,
        verbose=False,
    )
    model.vision_tower.unfreeze()

    # MLX-VLM's generic checkpoint hook covers decoder `layers`, not Qwen3-VL's
    # vision `blocks`, so checkpoint both explicitly for the memory qualification.
    grad_checkpoint(model.language_model.model.layers[0])
    grad_checkpoint(model.vision_tower.blocks[0])

    trainable = tree_flatten(model.trainable_parameters())
    vision_params = sum(value.size for name, value in trainable if name.startswith("vision_tower."))
    language_lora_params = sum(
        value.size
        for name, value in trainable
        if name.startswith("language_model.") and ("lora_a" in name or "lora_b" in name)
    )
    if vision_params == 0:
        raise SystemExit("SAFETY CHECK FAILED: the vision tower has zero trainable parameters")
    if language_lora_params == 0:
        raise SystemExit("SAFETY CHECK FAILED: language LoRA has zero trainable parameters")
    print_trainable_parameters(model)
    print(
        f"qualification parent={first_parent} crops={len(selected)} "
        f"vision_trainable={vision_params:,} language_lora_trainable={language_lora_params:,}",
        flush=True,
    )

    view = FirstFormView(source)
    dataset = VisionDataset(
        view,
        model.config.__dict__,
        processor,
        image_resize_shape=None,
        train_on_completions=True,
    )
    view.config = model.config.__dict__
    loss_fn = partial(vision_language_loss_fn, train_on_completions=True)
    value_and_grad = nn.value_and_grad(model, loss_fn)
    optimizer = build_optimizer(
        args.vision_learning_rate, args.language_learning_rate, 0.01
    )
    model.train()

    rows = []
    args.output.write_text("", encoding="utf-8")
    for position, batch in enumerate(
        iterate_batches(dataset, batch_size=1, max_seq_length=args.max_length),
    ):
        record = selected[position]
        mx.reset_peak_memory()
        started = time.perf_counter()
        loss, gradients = value_and_grad(model, batch)
        token_count = batch["attention_mask"].sum()

        gradient_leaves = tree_flatten(gradients)
        vision_samples = [
            (name, value)
            for name, value in gradient_leaves
            if name in {
                "vision_tower.patch_embed.proj.weight",
                "vision_tower.blocks.0.attn.qkv.weight",
                "vision_tower.merger.linear_fc2.weight",
            }
        ]
        lora_samples = [
            (name, value)
            for name, value in gradient_leaves
            if name.startswith("language_model.") and "lora_b" in name
        ][:1]
        reductions = {
            name: mx.max(mx.abs(value.astype(mx.float32)))
            for name, value in vision_samples + lora_samples
        }
        mx.eval(loss, token_count, reductions, gradients)
        optimizer.update(model, gradients)
        mx.eval(model.state, optimizer.state)
        gradient_max_abs = {name: float(value.item()) for name, value in reductions.items()}
        if not any(value > 0 for name, value in gradient_max_abs.items() if name.startswith("vision_tower.")):
            raise SystemExit(
                f"SAFETY CHECK FAILED: no sampled vision gradient on section {record['section']}"
            )

        crop = source[position]["images"][0]
        row = {
            "parent_id": first_parent,
            "section": record["section"],
            "crop_pixels": [crop.width, crop.height],
            "tokens": int(token_count.item()),
            "loss": float(loss.item()),
            "peak_memory_gb": mx.get_peak_memory() / 1e9,
            "elapsed_seconds": time.perf_counter() - started,
            "sample_gradient_max_abs": gradient_max_abs,
        }
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        rows.append(row)
        print(json.dumps(row, separators=(",", ":")), flush=True)
        del gradients, gradient_leaves, reductions, loss, batch
        mx.clear_cache()

    summary = {
        "status": "pass",
        "parent_id": first_parent,
        "sections": len(rows),
        "vision_trainable_parameters": vision_params,
        "language_lora_trainable_parameters": language_lora_params,
        "max_peak_memory_gb": max(row["peak_memory_gb"] for row in rows),
        "max_tokens": max(row["tokens"] for row in rows),
        "output": str(args.output),
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
