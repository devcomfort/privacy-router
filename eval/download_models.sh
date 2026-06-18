#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Model Weight Downloader for Privacy Router Evaluation
# ═══════════════════════════════════════════════════════════════════
#
# Usage:
#   bash eval/download_models.sh                    # Download all
#   bash eval/download_models.sh --model exaone-1.2b # Single model
#   bash eval/download_models.sh --path /custom/cache # Custom cache dir
#
# Models:
#   exaone-1.2b   — LGAI-EXAONE/EXAONE-4.0-1.2B (safetensors + GGUF)
#   ministral-3b  — mistralai/Ministral-3-3B-Instruct-2512
#   gemma4-e4b    — google/gemma-4-E4B-it
#   gemma4-e2b    — google/gemma-4-E2B-it
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface/hub}"
MODEL=""
PATH_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="$2"; shift 2 ;;
        --path)  PATH_ARG="$2"; shift 2 ;;
        *)       echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -n "$PATH_ARG" ]]; then
    HF_CACHE="$PATH_ARG"
fi

mkdir -p "$HF_CACHE"

echo "Cache dir: $HF_CACHE"
echo ""

download() {
    local repo="$1"
    local label="$2"
    echo "── Downloading: $label ($repo) ──"
    python3 -c "
from huggingface_hub import snapshot_download
import os
os.environ['HF_HUB_CACHE'] = '$HF_CACHE'
path = snapshot_download('$repo')
print(f'  ✅ {path}')
" 2>&1 | grep -v "WARNING\|UserWarning"
    echo ""
}

download_exaone() {
    echo "── EXAONE 4.0 1.2B ──"
    python3 -c "
from huggingface_hub import snapshot_download
import os
os.environ['HF_HUB_CACHE'] = '$HF_CACHE'

# Safetensors (for vLLM/SGLang)
print('  Downloading safetensors...')
p1 = snapshot_download('LGAI-EXAONE/EXAONE-4.0-1.2B')
print(f'  ✅ safetensors: {p1}')

# GGUF (for llama-server)
print('  Downloading GGUF...')
p2 = snapshot_download('LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF')
print(f'  ✅ GGUF: {p2}')
" 2>&1 | grep -v "WARNING\|UserWarning"
    echo ""
}

download_all() {
    download_exaone
    download "mistralai/Ministral-3-3B-Instruct-2512" "Ministral 3B"
    download "google/gemma-4-E4B-it" "Gemma4 E4B"
    download "google/gemma-4-E2B-it" "Gemma4 E2B"
}

copy_gguf() {
    echo "── Copying GGUF to models/ ──"
    mkdir -p models
    local src="$HF_CACHE/models--LGAI-EXAONE--EXAONE-4.0-1.2B-GGUF"
    if [[ -d "$src" ]]; then
        local gguf=$(find "$src" -name "*Q4_K_M.gguf" | head -1)
        if [[ -n "$gguf" ]]; then
            cp -L "$gguf" models/EXAONE-4.0-1.2B-Q4_K_M.gguf
            echo "  ✅ models/EXAONE-4.0-1.2B-Q4_K_M.gguf"
        fi
    fi
}

if [[ -z "$MODEL" ]]; then
    echo "Downloading all models..."
    download_all
    copy_gguf
else
    case "$MODEL" in
        exaone-1.2b)   download_exaone; copy_gguf ;;
        ministral-3b)  download "mistralai/Ministral-3-3B-Instruct-2512" "Ministral 3B" ;;
        gemma4-e4b)    download "google/gemma-4-E4B-it" "Gemma4 E4B" ;;
        gemma4-e2b)    download "google/gemma-4-E2B-it" "Gemma4 E2B" ;;
        *)             echo "Unknown model: $MODEL"; exit 1 ;;
    esac
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  Download complete"
echo "═══════════════════════════════════════════════════════════════"
