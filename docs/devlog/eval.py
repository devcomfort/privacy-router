"""Model evaluation script - runs N trials per model and reports consistency."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.extractor import Extractor
from agents.judge import Judge


MODELS = [
    # Edge
    "openrouter/mistralai/ministral-3b-2512",
    "openrouter/ibm-granite/granite-4.1-8b",
    # Performant
    "openrouter/qwen/qwen3.5-9b",
    "openrouter/qwen/qwen3.6-35b-a3b",
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemma-4-26b-a4b-it",
    # Frontier
    "openrouter/google/gemini-3.1-flash-lite",
    "openrouter/google/gemini-3.5-flash",
    "openrouter/anthropic/claude-haiku-4.5",
]

EXAMPLES = [
    {"name": "PII 포함", "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."},
    {"name": "PII 직접", "text": "내 주민등록번호가 뭐야?"},
    {"name": "사업비밀", "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘."},
    {"name": "연구비밀", "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘."},
    {"name": "민감없음", "text": "오늘 서울 날씨는 맑고 기온은 25도입니다."},
]

N_TRIALS = 5


def run_trial(model: str) -> dict:
    """Run one trial with a given model, return detection results."""
    extractor = Extractor(model=model)
    judge = Judge(model=model)
    results = {}

    for example in EXAMPLES:
        name = example["name"]
        try:
            records = extractor.extract(example["text"])
        except Exception:
            records = []

        try:
            records_dict = [r.model_dump() for r in records]
            judgment = judge.classify(records_dict, example["text"])
        except Exception:
            judgment = None

        results[name] = {
            "detected": [r.category for r in records],
            "needs_masking": judgment.needs_masking if judgment else None,
            "endpoint": judgment.recommended_endpoint if judgment else None,
        }

    return results


def evaluate_model(model: str) -> dict:
    """Run N trials and aggregate results."""
    trial_results = []
    for i in range(N_TRIALS):
        print(f"  Trial {i+1}/{N_TRIALS}...", flush=True)
        trial_results.append(run_trial(model))

    # Aggregate
    agg = {}
    for example in EXAMPLES:
        name = example["name"]
        detected_counts = Counter()
        masking_counts = Counter()
        endpoint_counts = Counter()

        for t in trial_results:
            r = t[name]
            for cat in r["detected"]:
                detected_counts[cat] += 1
            masking_counts[str(r["needs_masking"])] += 1
            endpoint_counts[str(r["endpoint"])] += 1

        agg[name] = {
            "detected": dict(detected_counts.most_common()),
            "needs_masking": dict(masking_counts),
            "endpoint": dict(endpoint_counts),
        }

    return agg


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else None

    models_to_test = [model_name] if model_name else MODELS

    for model in models_to_test:
        print(f"\n{'='*60}")
        print(f"Model: {model}")
        print(f"{'='*60}")
        try:
            agg = evaluate_model(model)
            print(json.dumps(agg, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    main()
