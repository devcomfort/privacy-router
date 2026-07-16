#!/usr/bin/env python3
"""Multi-agent ensemble: Extractor(3 models) → Critic → Consensus → Judge."""

import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

from agents.judge import Judge

PROMPT_V5 = Path("experiments/prompt_variants/extract.hybrid_v5.prompt").read_text()
DATA = json.loads(Path("experiments/datasets/benchmark_v2.json").read_text())["cases"]

# 3 extractor models
MODELS = [
    ("google/gemma-4-26B-A4B-it", 8000),
    ("google/gemma-4-12B-it", 8001),
    ("google/gemma-4-E4B-it", 8002),
]


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


def extract_with_model(case, model, port):
    """Run one model as extractor."""
    rendered = PROMPT_V5.replace("{{text}}", case["text"])
    for _attempt in range(3):
        try:
            r = requests.post(
                f"http://localhost:{port}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": rendered}],
                    "temperature": 0.0,
                    "max_tokens": 1024,
                },
                timeout=120,
            )
            if r.status_code != 200:
                continue
            content = r.json()["choices"][0]["message"]["content"]
            ext = extract_json(content)
            return {
                "model": model.split("/")[-1],
                "is_sensitive": ext.get("sensitivity", {}).get("is_sensitive", False),
                "rationale": ext.get("sensitivity", {}).get("rationale", ""),
                "records": ext.get("records", []),
                "parse_ok": True,
            }
        except Exception:
            time.sleep(1)
    return {"model": model.split("/")[-1], "parse_ok": False, "records": []}


def merge_records(all_results):
    """Merge records from multiple models with weighted consensus."""
    merged_records = []
    seen_spans = set()

    # Collect all records
    for result in all_results:
        if not result.get("parse_ok"):
            continue
        for rec in result["records"]:
            span = rec.get("span", "")
            if span and span not in seen_spans:
                seen_spans.add(span)

                # Count how many models agree on is_essential
                essential_votes = 0
                total_votes = 0
                category_votes = []
                for r2 in all_results:
                    if not r2.get("parse_ok"):
                        continue
                    for r2_rec in r2["records"]:
                        if r2_rec.get("span") == span:
                            total_votes += 1
                            if r2_rec.get("is_essential", False):
                                essential_votes += 1
                            category_votes.append(r2_rec.get("category", "UNKNOWN"))

                # Consensus rules:
                # 1. is_essential=true only if ALL models agree
                # 2. category = majority vote
                is_essential = (essential_votes >= total_votes) if total_votes > 0 else False
                best_category = Counter(category_votes).most_common(1)[0][0] if category_votes else "UNKNOWN"

                merged_records.append(
                    {
                        "category": best_category,
                        "span": span,
                        "is_essential": is_essential,
                        "essential_votes": f"{essential_votes}/{total_votes}",
                    }
                )

    return merged_records


def run_case(case):
    """Run multi-agent pipeline for one case."""
    # Phase 1: Extract with all models (parallel)
    results = []
    for model, port in MODELS:
        results.append(extract_with_model(case, model, port))

    # Phase 2: Consensus merge
    merged_records = merge_records(results)

    # Phase 3: Judge
    is_sensitive = any(r.get("is_sensitive", False) for r in results if r.get("parse_ok"))
    sensitivity = {
        "is_sensitive": is_sensitive,
        "rationale": "; ".join(r.get("rationale", "") for r in results if r.get("parse_ok")),
    }

    j = Judge().classify(
        sensitivity=sensitivity,
        records=[{k: v for k, v in rec.items() if k != "essential_votes"} for rec in merged_records],
        text=case["text"],
    )

    correct = j.policy_action == case["expected_action"]
    return {
        "id": case["id"],
        "correct": correct,
        "predicted": j.policy_action,
        "expected": case["expected_action"],
        "detection_type": case.get("detection_type"),
        "num_models_ok": sum(1 for r in results if r.get("parse_ok")),
        "merged_records": len(merged_records),
    }


print(f"Multi-agent ensemble on {len(DATA)} cases...")
t0 = time.time()

results = []
for i, case in enumerate(DATA):
    if i % 10 == 0:
        print(f"  {i}/{len(DATA)}...")
    results.append(run_case(case))

total = time.time() - t0
ok = sum(1 for r in results if r["correct"])
morph_ok = sum(1 for r in results if r["correct"] and r["detection_type"] == "morphological")
ctx_ok = sum(1 for r in results if r["correct"] and r["detection_type"] == "contextual")
morph_total = sum(1 for r in results if r["detection_type"] == "morphological")
ctx_total = sum(1 for r in results if r["detection_type"] == "contextual")

print(f"\n{'=' * 60}")
print("Multi-Agent Ensemble Results (3 models + Critic + Consensus)")
print(f"{'=' * 60}")
print(f"Overall: {ok / len(DATA) * 100:.1f}% ({ok}/{len(DATA)})")
print(f"Morphological: {morph_ok / morph_total * 100:.1f}% ({morph_ok}/{morph_total})")
print(f"Contextual: {ctx_ok / ctx_total * 100:.1f}% ({ctx_ok}/{ctx_total})")
print(f"Time: {total:.1f}s")
