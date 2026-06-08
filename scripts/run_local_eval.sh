#!/usr/bin/env bash
# ── Run eval for local vLLM GPU models ───────────────────────────────────────
# Usage:
#   scripts/run_local_eval.sh                    # all GPU models, 5 trials
#   scripts/run_local_eval.sh --trials 3         # 3 trials
#   scripts/run_local_eval.sh --models gemma-4-e4b-bf16
#
# Each model requires its own vLLM server. This script:
#   1. Starts vLLM with the appropriate model
#   2. Waits for health check
#   3. Runs eval_all.py for that model
#   4. Stops the server before moving to the next model
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
LOG_DIR="/tmp"

export PATH="${PROJECT_DIR}/.venv/bin:$PATH"
export OPENAI_API_KEY="${OPENAI_API_KEY:-dummy}"

PORT=8000
TRIALS=5
SELECTED_MODELS=""

# ── Parse args ───────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case $1 in
        --trials) TRIALS="$2"; shift 2 ;;
        --models) SELECTED_MODELS="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Model → vLLM args mapping ────────────────────────────────────────────────
# Format: model_key|huggingface_model_id|extra_vllm_args

GPU_MODELS=(
    "gemma-4-e2b-bf16|google/gemma-4-E2B-it|--gpu-memory-utilization 0.3"
    "gemma-4-e4b-bf16|google/gemma-4-E4B-it|--gpu-memory-utilization 0.4"
    "exaone-4.5-33b-fp8|LGAI-EXAONE/EXAONE-4.5-33B-FP8|--gpu-memory-utilization 0.6"
)

# ── Functions ────────────────────────────────────────────────────────────────

kill_vllm() {
    pkill -f "vllm.entrypoints.openai" 2>/dev/null || true
    sleep 3
}

wait_for_server() {
    local max_wait=600
    local elapsed=0
    echo -n "  Waiting for server"
    while [ $elapsed -lt $max_wait ]; do
        if curl -sf http://localhost:${PORT}/health > /dev/null 2>&1; then
            echo " ready (${elapsed}s)"
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        echo -n "."
    done
    echo " TIMEOUT (${max_wait}s)"
    return 1
}

run_one_model() {
    local model_key="$1"
    local hf_model="$2"
    local extra_args="$3"

    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "  Model: ${model_key} (${hf_model})"
    echo "════════════════════════════════════════════════════════════════"

    # Start vLLM
    echo "  Starting vLLM server..."
    nohup ${VENV_PYTHON} -m vllm.entrypoints.openai.api_server \
        --model "${hf_model}" \
        --host 0.0.0.0 \
        --port "${PORT}" \
        --max-model-len 32768 \
        --dtype auto \
        --trust-remote-code \
        ${extra_args} \
        > "${LOG_DIR}/vllm-${model_key}.log" 2>&1 &
    local vllm_pid=$!

    if ! wait_for_server; then
        echo "  FAILED to start server for ${model_key}"
        tail -20 "${LOG_DIR}/vllm-${model_key}.log"
        kill $vllm_pid 2>/dev/null || true
        return 1
    fi

    # Run eval
    echo "  Running eval (trials=${TRIALS})..."
    cd "${PROJECT_DIR}"
    ${VENV_PYTHON} scripts/eval_all.py \
        --models "${model_key}" \
        --trials "${TRIALS}" \
        2>&1 | tail -20

    # Stop server
    echo "  Stopping server..."
    kill $vllm_pid 2>/dev/null || true
    kill_vllm
}

# ── Main ─────────────────────────────────────────────────────────────────────

echo "Local GPU Eval Runner"
echo "  Trials: ${TRIALS}"
echo "  Port: ${PORT}"
echo ""

for entry in "${GPU_MODELS[@]}"; do
    IFS='|' read -r model_key hf_model extra_args <<< "$entry"

    # Filter if --models specified
    if [ -n "${SELECTED_MODELS}" ] && [ "${model_key}" != "${SELECTED_MODELS}" ]; then
        continue
    fi

    run_one_model "$model_key" "$hf_model" "$extra_args" || true
done

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  All local evals complete!"
echo "════════════════════════════════════════════════════════════════"
