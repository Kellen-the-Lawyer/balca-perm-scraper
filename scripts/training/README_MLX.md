# ETA Qwen3-VL training on Apple Silicon

The existing GGUF is an inference file and is not used for training. This path
uses the compatible 4-bit MLX checkpoint
`mlx-community/Qwen3-VL-4B-Instruct-4bit`; Hugging Face downloads it into the
normal local cache on first use.

## Environment

```bash
cd /Users/kpowell/Documents/GitHub/balca-perm-scraper
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r scripts/training/requirements-mlx.txt
```

## One-step hardware smoke test

This starts with a seven-page ETA-9089 record at 384 px, rank 8, batch size 1,
completion-only loss, and gradient checkpointing for a 24 GB Mac. It writes only
a LoRA adapter.

```bash
.venv/bin/python scripts/training/train_eta_qwen3_vl_mlx.py \
  --train-jsonl '/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1/data/smoke_train_64.jsonl' \
  --package-root '/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1' \
  --output-dir outputs/eta-mlx-smoke \
  --task eta9089 \
  --limit-train 1 \
  --max-steps 1 \
  --gradient-accumulation 1 \
  --image-size 384 \
  --max-length 4096 \
  --save-steps 1
```

Do not launch the full corpus until the smoke step finishes with finite loss and
acceptable peak memory. Add the smoke validation file after the first successful
training step; validation runs before iteration 1 and roughly doubles first-step
work.

For a balanced smoke run, add `--limit-per-task 1` without `--task`; this selects
one record from each of the four document classes.

The balanced four-task run passed at 384 px and 4,096 tokens. Peak Metal memory
was 13.63 GB, baseline validation loss was 1.649, and validation loss after four
updates was 1.621. The resulting adapter is only a pipeline check, not a useful
trained model.

## Earlier 8B hardware result on the 24 GB M4

The 8B model completed an ETA-9141 addendum update at 256 px and 2,048 tokens
(12.29 GB peak Metal memory). A seven-page ETA-9089 update ran out of Metal
memory, even at 256 px. Therefore, do not run the combined corpus with the 8B
checkpoint on this machine. Use the 8B model for a task-specific addendum run,
but use the default 4B checkpoint for combined-corpus training.

## 4B combined-corpus starting point

```bash
.venv/bin/python scripts/training/train_eta_qwen3_vl_mlx.py \
  --train-jsonl '/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1/data/train.jsonl' \
  --eval-jsonl '/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1/data/validation.jsonl' \
  --package-root '/Users/kpowell/Desktop/Qwen Training Data/eta_pair_unsloth_v1' \
  --output-dir outputs/eta-mlx-4b-v1 \
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
  --save-steps 250
```

The smoke-run throughput suggests that one 17,737-example epoch will take roughly
three to four days on this Mac. Keep it connected to power and prevent system
sleep for an unattended run.

Keep `data/test.jsonl` untouched while choosing settings. The dataset card also
states that training approval is pending attorney review.
