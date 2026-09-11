#!/bin/bash
set -euo pipefail

REPO_ROOT="/Users/kpowell/Documents/GitHub/balca-perm-scraper"
DATA_ROOT="/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1"
TRAIN_OUTPUT="$REPO_ROOT/outputs/eta-mlx-4b-v1"
EVAL_OUTPUT="$TRAIN_OUTPUT/evaluation"

cd "$REPO_ROOT"
mkdir -p "$EVAL_OUTPUT"
exec >> "$EVAL_OUTPUT/evaluation.log" 2>&1

/usr/bin/caffeinate -dis "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/scripts/training/evaluate_eta_adapters_mlx.py" \
  --jsonl "$DATA_ROOT/data/validation.jsonl" \
  --package-root "$DATA_ROOT" \
  --candidate "final=$TRAIN_OUTPUT/adapters.safetensors" \
  --candidate "step_17500=$TRAIN_OUTPUT/0017500_adapters.safetensors" \
  --output-dir "$EVAL_OUTPUT" \
  --image-size 384 \
  --max-length 4096

/usr/bin/caffeinate -dis "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/scripts/training/predict_eta_split_mlx.py" \
  --jsonl "$DATA_ROOT/data/test.jsonl" \
  --package-root "$DATA_ROOT" \
  --selection "$EVAL_OUTPUT/selection.json" \
  --output "$EVAL_OUTPUT/test_predictions.jsonl" \
  --image-size 384 \
  --max-tokens 4096

"$REPO_ROOT/.venv/bin/python" \
  "$DATA_ROOT/score_eta_extraction_predictions.py" \
  --gold "$DATA_ROOT/data/test.jsonl" \
  --predictions "$EVAL_OUTPUT/test_predictions.jsonl" \
  --output "$EVAL_OUTPUT/test_score.json"
