#!/usr/bin/env python3
"""Train the guarded ETA-9089 native-section MLX pilot.

The full Qwen3-VL vision tower is trainable. The quantized language model stays
frozen except for LoRA layers. Native section crops are never downscaled.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from mlx.utils import tree_flatten

from train_eta_qwen3_vl_mlx import DEFAULT_MODEL, PortableETADataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--eval-jsonl", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=float, default=16.0)
    parser.add_argument("--vision-learning-rate", type=float, default=1e-6)
    parser.add_argument("--language-learning-rate", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--logging-steps", type=int, default=1)
    parser.add_argument("--eval-steps", type=int, default=500)
    parser.add_argument("--save-steps", type=int, default=500)
    parser.add_argument("--val-batches", type=int, default=44)
    return parser.parse_args()


def build_optimizer(vision_lr: float, language_lr: float, weight_decay: float):
    import mlx.optimizers as optim

    # Adafactor keeps only factored second moments for matrices, which makes
    # full-vision training feasible on a 24 GB unified-memory Mac. Language LoRA
    # remains on AdamW. The path filter sends every vision weight to Adafactor.
    vision = optim.Adafactor(
        learning_rate=vision_lr,
        relative_step=False,
        scale_parameter=False,
        weight_decay=weight_decay,
    )
    language = optim.AdamW(
        learning_rate=language_lr,
        weight_decay=weight_decay,
    )
    return optim.MultiOptimizer(
        [vision, language],
        filters=[lambda path, _: path.startswith("vision_tower.")],
    )


def main() -> None:
    args = parse_args()
    train_source = PortableETADataset(
        args.train_jsonl, args.package_root, image_size=None
    )
    eval_source = PortableETADataset(
        args.eval_jsonl, args.package_root, image_size=None
    )
    if not all(record.get("crop_box_fraction") for record in train_source.records):
        raise SystemExit("SAFETY CHECK FAILED: every training record must be a crop")
    if {record.get("task") for record in train_source.records} != {"eta9089_section"}:
        raise SystemExit("SAFETY CHECK FAILED: pilot accepts ETA-9089 sections only")

    import mlx.core as mx
    from mlx_vlm.trainer.datasets import VisionDataset
    from mlx_vlm.trainer.sft_trainer import TrainingArgs, train
    from mlx_vlm.trainer.utils import (
        find_all_linear_names,
        get_peft_model,
        grad_checkpoint,
        print_trainable_parameters,
    )
    from mlx_vlm.utils import load

    print(f"Loading {args.model}", flush=True)
    model, processor = load(args.model, processor_config={"trust_remote_code": True})
    train_dataset = VisionDataset(
        train_source,
        model.config.__dict__,
        processor,
        image_resize_shape=None,
        train_on_completions=True,
    )
    eval_dataset = VisionDataset(
        eval_source,
        model.config.__dict__,
        processor,
        image_resize_shape=None,
        train_on_completions=True,
    )

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
    grad_checkpoint(model.vision_tower.blocks[0])

    trainable = tree_flatten(model.trainable_parameters())
    vision_params = sum(v.size for name, v in trainable if name.startswith("vision_tower."))
    language_lora_params = sum(
        v.size
        for name, v in trainable
        if name.startswith("language_model.") and ("lora_a" in name or "lora_b" in name)
    )
    if vision_params == 0 or language_lora_params == 0:
        raise SystemExit(
            "SAFETY CHECK FAILED: both vision weights and language LoRA must be trainable"
        )
    print_trainable_parameters(model)
    print(
        f"vision_trainable={vision_params:,} language_lora_trainable={language_lora_params:,}",
        flush=True,
    )

    steps = (
        args.max_steps
        if args.max_steps is not None
        else math.ceil(len(train_source) * args.epochs)
    )
    if steps < 1:
        raise SystemExit("Training steps must be positive")
    output_dir = args.output_dir.expanduser().resolve()
    optimizer = build_optimizer(
        args.vision_learning_rate,
        args.language_learning_rate,
        args.weight_decay,
    )
    training_args = TrainingArgs(
        batch_size=1,
        iters=steps,
        val_batches=args.val_batches,
        steps_per_report=args.logging_steps,
        steps_per_eval=args.eval_steps,
        steps_per_save=args.save_steps,
        max_seq_length=args.max_length,
        adapter_file=str(output_dir / "adapters.safetensors"),
        grad_checkpoint=True,
        learning_rate=args.vision_learning_rate,
        grad_clip=1.0,
        gradient_accumulation_steps=1,
    )
    print(
        f"pilot_sections={len(train_source)} validation_sections={len(eval_source)} "
        f"steps={steps} native_pixels=true vision_frozen=false",
        flush=True,
    )
    print(
        f"metal_recommended_working_set={mx.device_info().get('max_recommended_working_set_size')}",
        flush=True,
    )
    train(
        model=model,
        optimizer=optimizer,
        train_dataset=train_dataset,
        val_dataset=eval_dataset,
        args=training_args,
        train_on_completions=True,
    )


if __name__ == "__main__":
    main()
