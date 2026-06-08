#!/usr/bin/env bash
# ── Start vLLM server for local model inference ──────────────────────────────
# Usage:
#   scripts/start_vllm.sh                    # default: Qwen3-4B on port 8000
#   scripts/start_vllm.sh --model Qwen/Qwen2.5-7B-Instruct
#   scripts/start_vllm.sh --port 8001
#
# Requires: vllm (pip install vllm), NVIDIA GPU with CUDA
# The server exposes an OpenAI-compatible API at http://localhost:8000/v1
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

MODEL="${1:-Qwen/Qwen3-4B}"
PORT="${2:-8000}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "Error: venv python not found at $VENV_PYTHON"
    echo "Run 'rye sync' first."
    exit 1
fi

# Check if port is already in use
if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    echo "Port ${PORT} is already in use. Kill existing process or use --port."
    exit 1
fi

echo "Starting vLLM server..."
echo "  Model: ${MODEL}"
echo "  Port:  ${PORT}"
echo "  API:   http://localhost:${PORT}/v1"
echo ""

exec "$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --gpu-memory-utilization 0.5 \
    --max-model-len 32768 \
    --dtype auto \
    --trust-remote-code
