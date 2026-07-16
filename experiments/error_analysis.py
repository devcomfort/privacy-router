#!/usr/bin/env python3
"""Detailed error analysis for best model. Identifies failure patterns."""

import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["HF_HUB_OFFLINE"] = "1"

MODEL = "google/gemma-4-12B-it"
MODEL_TAG = "Gemma-12B"
PORT = 8000
CONC = 16

PROMPT = Path("experiments/prompt_variants/extract.fewshot_v3.prompt").read_text()
DATA = json.loads(Path("experiments/datasets/benchmark_v2.json").read_text())["cases"]


def extract_json(content):
    stripped = content.strip()
    stripped = re.sub(r"<think>.*?</think>\s*", "", stripped, flags=re.DOTALL).strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        stripped = m.group(1)
    elif not stripped.startswith("{"):
        m = re.search(r"\{.*\}", stripped, re.DOTALL)
        if m:
            stripped = m.group(0)
    return json.loads(stripped)


def run_case(case):
    rendered = PROMPT.replace("{{text}}", case["text"])
    t0 = time.time()
    try:
        r = requests.post(
            f"http://localhost:{PORT}/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": rendered}],
                "temperature": 0.0,
                "max_tokens": 1024,
            },
            timeout=120,
        )
        lat = time.time() - t0
        if r.status_code != 200:
            return {"error": "api_error", "latency": lat}
        content = r.json()["choices"][0]["message"]["content"]
        ext = extract_json(content)
        from agents.judge import Judge

        j = Judge().classify(sensitivity=ext.get("sensitivity", {}), records=ext.get("records", []), text=case["text"])
        # Judge now outputs allow/block/selective_mask directly
        action = j.policy_action
        correct = action == case["expected_action"]
        return {
            "correct": correct,
            "predicted": action,
            "expected": case["expected_action"],
            "latency": lat,
            "raw_output": content[:500],
        }
    except Exception as e:
        return {"error": str(e), "latency": time.time() - t0}


print(f"Running detailed error analysis on {MODEL_TAG} ({len(DATA)} cases)...")

with ThreadPoolExecutor(max_workers=CONC) as ex:
    futs = [ex.submit(run_case, c) for c in DATA]
    results = [f.result() for f in futs]

# Analyze errors
errors = []
for _i, (case, result) in enumerate(zip(DATA, results, strict=False)):
    if not result.get("correct", False):
        errors.append(
            {
                "case_id": case["id"],
                "detection_type": case.get("detection_type"),
                "language": case.get("language"),
                "sensitivity_level": case.get("sensitivity_level"),
                "context": case.get("context"),
                "expected": result.get("expected"),
                "predicted": result.get("predicted"),
                "error_type": result.get("error"),
            }
        )

# Summary
total = len(DATA)
correct = sum(1 for r in results if r.get("correct"))
print(f"\n{'=' * 60}")
print(f"ERROR ANALYSIS: {MODEL_TAG}")
print(f"{'=' * 60}")
print(
    f"Total: {total}, Correct: {correct} ({correct / total * 100:.1f}%), Errors: {len(errors)} ({len(errors) / total * 100:.1f}%)"
)

# Error breakdown by detection_type
print("\n--- By Detection Type ---")
dt_errors = Counter(e["detection_type"] for e in errors)
for dt, count in dt_errors.most_common():
    total_dt = sum(1 for c in DATA if c.get("detection_type") == dt)
    print(f"  {dt}: {count}/{total_dt} errors ({count / total_dt * 100:.1f}%)")

# Error breakdown by language
print("\n--- By Language ---")
lang_errors = Counter(e["language"] for e in errors)
for lang, count in lang_errors.most_common():
    total_lang = sum(1 for c in DATA if c.get("language") == lang)
    print(f"  {lang}: {count}/{total_lang} errors ({count / total_lang * 100:.1f}%)")

# Error breakdown by expected action
print("\n--- By Expected Action ---")
action_errors = Counter(e["expected"] for e in errors)
for action, count in action_errors.most_common():
    print(f"  {action}: {count} errors")

# Error breakdown by predicted action
print("\n--- By Predicted Action ---")
pred_errors = Counter(e["predicted"] for e in errors)
for pred, count in pred_errors.most_common():
    print(f"  {pred}: {count} errors")

# Show sample errors
print("\n--- Sample Errors (first 10) ---")
for e in errors[:10]:
    print(f"  {e['case_id']}: {e['expected']} → {e['predicted']} ({e['detection_type']}, {e['language']})")

# Save detailed results
output = {
    "model": MODEL_TAG,
    "total": total,
    "correct": correct,
    "accuracy": round(correct / total * 100, 1),
    "errors": len(errors),
    "error_details": errors,
    "error_patterns": {
        "by_detection_type": dict(dt_errors),
        "by_language": dict(lang_errors),
        "by_expected_action": dict(action_errors),
        "by_predicted_action": dict(pred_errors),
    },
}

Path(f"experiments/results/error_analysis_{MODEL_TAG}.json").write_text(
    json.dumps(output, indent=2, ensure_ascii=False)
)
print(f"\nSaved: experiments/results/error_analysis_{MODEL_TAG}.json")
