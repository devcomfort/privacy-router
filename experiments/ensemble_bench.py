#!/usr/bin/env python3
"""Ensemble evaluation: Gemma-12B + E4B + Gemma-26B."""

import json
from collections import Counter
from pathlib import Path

import requests

from agents.judge import Judge

MODELS = ["google/gemma-4-12B-it", "google/gemma-4-E4B-it", "google/gemma-4-26B-A4B-it"]
PORT = 8000
PROMPT = Path("experiments/prompt_variants/extract.hybrid_v5.prompt").read_text()
DATA = json.loads(Path("experiments/datasets/benchmark_v2.json").read_text())["cases"]


def run_case_model(case, model):
    rendered = PROMPT.replace("{{text}}", case["text"])
    try:
        r = requests.post(
            f"http://localhost:{PORT}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": rendered}],
                "temperature": 0.0,
                "max_tokens": 1024,
            },
            timeout=120,
        )
        if r.status_code != 200:
            return None
        from experiments.unified_benchmark import extract_json  # Reuse logic

        content = r.json()["choices"][0]["message"]["content"]
        ext = extract_json(content)
        j = Judge().classify(sensitivity=ext.get("sensitivity", {}), records=ext.get("records", []), text=case["text"])
        return j.policy_action
    except Exception:
        return None


def ensemble_bench():
    results = []
    for case in DATA:
        # Run 3 models
        preds = []
        for m in MODELS:
            preds.append(run_case_model(case, m))

        # Majority vote
        valid_preds = [p for p in preds if p]
        final_pred = "allow" if not valid_preds else Counter(valid_preds).most_common(1)[0][0]

        results.append(final_pred == case["expected_action"])
        print(
            f"Case {case['id']}: {final_pred} (Expected: {case['expected_action']}) - {'OK' if final_pred == case['expected_action'] else 'FAIL'}"
        )

    acc = sum(results) / len(results) * 100
    print(f"\nEnsemble Overall Accuracy: {acc:.1f}%")


if __name__ == "__main__":
    ensemble_bench()
