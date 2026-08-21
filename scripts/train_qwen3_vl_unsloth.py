#!/usr/bin/env python3
"""Reference Qwen3-VL QLoRA training entry point for the Casebase ETA corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image
from torch.utils.data import Dataset


class PortableVisionDataset(Dataset):
    """Lazily resolve portable JSONL image paths to RGB PIL images."""

    def __init__(self, jsonl_path: Path, package_root: Path | None = None) -> None:
        self.jsonl_path = jsonl_path.resolve()
        self.package_root = (package_root or self.jsonl_path.parents[1]).resolve()
        with self.jsonl_path.open("r", encoding="utf-8") as stream:
            self.records = [json.loads(line) for line in stream if line.strip()]

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, Any]:
        record = self.records[index]
        messages = []
        for message in record["messages"]:
            content = []
            for item in message["content"]:
                copied = dict(item)
                if copied.get("type") == "image":
                    image_path = self.package_root / copied["image"]
                    with Image.open(image_path) as image:
                        copied["image"] = image.convert("RGB").copy()
                content.append(copied)
            messages.append({"role": message["role"], "content": content})
        return {"messages": messages}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--eval-jsonl", type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument(
        "--model",
        default="unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/casebase-qwen3-vl"))
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--warmup-ratio", type=float, default=0.03)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--save-steps", type=int, default=250)
    parser.add_argument("--eval-steps", type=int, default=0)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--no-vision-lora", action="store_true")
    args = parser.parse_args()

    from unsloth import FastVisionModel
    from unsloth.trainer import UnslothVisionDataCollator
    from trl import SFTConfig, SFTTrainer

    package_root = args.package_root
    train_dataset = PortableVisionDataset(args.train_jsonl, package_root)
    eval_dataset = (
        PortableVisionDataset(args.eval_jsonl, package_root)
        if args.eval_jsonl
        else None
    )

    model, tokenizer = FastVisionModel.from_pretrained(
        args.model,
        load_in_4bit=True,
        use_gradient_checkpointing="unsloth",
    )
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=not args.no_vision_lora,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0,
        bias="none",
        random_state=args.seed,
        use_rslora=False,
        loftq_config=None,
        use_gradient_checkpointing="unsloth",
    )
    FastVisionModel.for_training(model)

    config: dict[str, Any] = {
        "per_device_train_batch_size": args.batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation,
        "num_train_epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "warmup_ratio": args.warmup_ratio,
        "logging_steps": args.logging_steps,
        "optim": "adamw_8bit",
        "weight_decay": args.weight_decay,
        "lr_scheduler_type": "cosine",
        "seed": args.seed,
        "output_dir": str(args.output_dir),
        "report_to": "none",
        "save_strategy": "steps",
        "save_steps": args.save_steps,
        "save_total_limit": 2,
        "remove_unused_columns": False,
        "dataset_text_field": "",
        "dataset_kwargs": {"skip_prepare_dataset": True},
        "max_length": args.max_length,
    }
    if args.max_steps > 0:
        config["max_steps"] = args.max_steps
    if eval_dataset is not None and args.eval_steps > 0:
        config.update(
            {
                "eval_strategy": "steps",
                "eval_steps": args.eval_steps,
                "load_best_model_at_end": True,
                "metric_for_best_model": "eval_loss",
                "greater_is_better": False,
            }
        )
    else:
        config["eval_strategy"] = "no"

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        data_collator=UnslothVisionDataCollator(model, tokenizer),
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        args=SFTConfig(**config),
    )
    trainer.train()
    final_dir = args.output_dir / "final_adapter"
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    print(f"Saved adapter and tokenizer to {final_dir}")


if __name__ == "__main__":
    main()
