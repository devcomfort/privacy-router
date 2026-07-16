#!/usr/bin/env bash
# ── Start the local models used by the default Privacy Router profile ─────────
# Usage:
#   scripts/start_vllm.sh all                 # EXAONE decision + Gemma generation
#   scripts/start_vllm.sh exaone              # EXAONE 4.0 1.2B (port 8010)
#   scripts/start_vllm.sh gemma4              # Gemma 4 26B A4B (port 8011)
#   scripts/start_vllm.sh --model <hf_id> [port]  # Direct mode
#
# Docker mode (default): uses docker-compose.vllm.yml
#   - Proper signal handling → no orphan processes
#   - Profiles prevent simultaneous OOM
#   - HF cache mounted read-only from host
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILES="-f ${PROJECT_DIR}/docker-compose.yml -f ${PROJECT_DIR}/docker-compose.vllm.yml"

usage() {
    echo "Usage:"
    echo "  $0 all                     Start the complete local profile"
    echo "  $0 exaone                  Start EXAONE 4.0 1.2B (port 8010)"
    echo "  $0 gemma4                  Start Gemma 4 26B A4B (port 8011)"
    echo "  $0 --model <hf_id> [port]  Direct vLLM mode"
    echo ""
    echo "Stop: docker compose $COMPOSE_FILES --profile exaone --profile gemma4 down"
    exit 1
}

case "${1:-}" in
    all)
        echo "Starting the complete local Privacy Router profile..."
        echo "  Decision: http://localhost:8010/v1 (EXAONE 4.0 1.2B)"
        echo "  Local:    http://localhost:8011/v1 (Gemma 4 26B A4B)"
        echo ""
        exec docker compose $COMPOSE_FILES \
            --profile exaone --profile gemma4 \
            up vllm-exaone vllm-gemma4
        ;;
    gemma4)
        echo "Starting Gemma 4 26B A4B local generation..."
        echo "  API: http://localhost:8011/v1"
        echo "  Stop: docker compose $COMPOSE_FILES --profile gemma4 down"
        echo ""
        exec docker compose $COMPOSE_FILES --profile gemma4 up vllm-gemma4
        ;;
    exaone)
        echo "Starting EXAONE 4.0 1.2B decision extraction..."
        echo "  API: http://localhost:8010/v1"
        echo "  Stop: docker compose $COMPOSE_FILES --profile exaone down"
        echo ""
        exec docker compose $COMPOSE_FILES --profile exaone up vllm-exaone
        ;;
    --model)
        # Legacy direct mode
        MODEL="${2:-google/gemma-4-E4B-it}"
        PORT="${3:-8000}"
        VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
        if [ ! -x "$VENV_PYTHON" ]; then
            echo "Error: venv python not found at $VENV_PYTHON"
            echo "Run 'rye sync' first."
            exit 1
        fi
        if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
            echo "Port ${PORT} is already in use. Kill existing process or use --port."
            exit 1
        fi
        echo "Starting vLLM server (direct mode)..."
        echo "  Model: ${MODEL}"
        echo "  Port:  ${PORT}"
        exec "$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
            --model "$MODEL" \
            --host 0.0.0.0 \
            --port "$PORT" \
            --gpu-memory-utilization 0.5 \
            --max-model-len 32768 \
            --dtype auto \
            --trust-remote-code
        ;;
    -h|help|"")
        usage
        ;;
    *)
        echo "Unknown model: $1"
        usage
        ;;
esac
