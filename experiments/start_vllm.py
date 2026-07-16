#!/usr/bin/env python3
"""Start vLLM server for local model inference.

Usage:
    rye run python experiments/start_vllm.py --model gemma-4-E4B-it
    rye run python experiments/start_vllm.py --model gemma-4-26B-A4B-it --port 8001
"""

from __future__ import annotations

import argparse
import subprocess
import sys

MODELS = {
    "gemma-4-E2B-it": "google/gemma-4-E2B-it",
    "gemma-4-E4B-it": "google/gemma-4-E4B-it",
    "ministral-3b": "mistralai/Ministral-3-3B-Instruct-2512",
    "granite-4.1-8b": "ibm-granite/granite-4.1-8b",
    "gemma-4-26B-A4B-it": "google/gemma-4-26B-A4B-it",
}


def main():
    parser = argparse.ArgumentParser(description="Start vLLM server")
    parser.add_argument("--model", required=True, choices=list(MODELS.keys()), help="Model to serve")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--gpu-mem", type=float, default=0.75, help="GPU memory utilization")
    parser.add_argument("--max-model-len", type=int, default=4096, help="Max model length")
    args = parser.parse_args()

    model_path = MODELS[args.model]
    print(f"Starting vLLM server for {args.model} ({model_path})")
    print(f"  Port: {args.port}")
    print(f"  GPU memory: {args.gpu_mem}")
    print(f"  Max model length: {args.max_model_len}")

    cmd = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        model_path,
        "--port",
        str(args.port),
        "--dtype",
        "auto",
        "--max-model-len",
        str(args.max_model_len),
        "--gpu-memory-utilization",
        str(args.gpu_mem),
    ]

    print(f"\n  Command: {' '.join(cmd)}")
    print("\n  Waiting for server to start...")

    proc = subprocess.Popen(cmd)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n  Stopping server...")
        proc.terminate()
        proc.wait(timeout=10)
        print("  Server stopped")


if __name__ == "__main__":
    main()
