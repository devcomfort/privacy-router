#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Evaluation Runner for Privacy Router
# ═══════════════════════════════════════════════════════════════════
#
# Usage:
#   bash eval/run_eval.sh                           # Run all models
#   bash eval/run_eval.sh --model gemma4-e4b-vllm   # Single model
#   bash eval/run_eval.sh --trials 10               # 10 trials
#   bash eval/run_eval.sh --report                  # Show report only
#
# Prerequisites:
#   1. Model weights downloaded (bash eval/download_models.sh)
#   2. Engine running (docker compose -f docker-compose.engines.yml --profile <name> up -d)
#   3. Python deps installed (pip install litellm optuna)
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

export OPENAI_API_KEY="${OPENAI_API_KEY:-dummy}"
export HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface/hub}"

python3 scripts/eval_runner.py "$@"
