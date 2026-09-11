#!/bin/bash
set -euo pipefail

REPO_ROOT="/Users/kpowell/Documents/GitHub/balca-perm-scraper"
DATA_ROOT="/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1"
OUTPUT_DIR="$REPO_ROOT/outputs/eta-mlx-4b-v1"

cd "$REPO_ROOT"
mkdir -p "$OUTPUT_DIR"

exec caffeinate -dis \
  "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/scripts/training/train_eta_qwen3_vl_mlx.py" \
  --train-jsonl "$DATA_ROOT/data/train.jsonl" \
  --eval-jsonl "$DATA_ROOT/data/validation.jsonl" \
  --package-root "$DATA_ROOT" \
  --output-dir "$OUTPUT_DIR" \
  --epochs 1 \
  --batch-size 1 \
  --gradient-accumulation 8 \
  --image-size 384 \
  --max-length 4096 \
  --rank 8 \
  --alpha 16 \
  --learning-rate 0.00002 \
  --eval-steps 250 \
  --val-batches 8 \
  --save-steps 250 \
  >> "$OUTPUT_DIR/training.log" 2>&1
