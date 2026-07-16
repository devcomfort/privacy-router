#!/usr/bin/env python3
"""Analyze model responses for all 17 test cases using the current best prompt.

Runs each case, saves raw responses, and produces a detailed failure analysis.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import litellm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents import Judge  # noqa: E402
from experiments.run_experiment import CASES, POLICY_NORMALIZE, SENSITIVE_CASES  # noqa: E402

PROMPT_PATH = Path(__file__).parent / "prompt_variants" / "extract.fewshot.prompt"
RESPONSES_DIR = Path(__file__).parent / "responses"
RESPONSES_DIR.mkdir(exist_ok=True)

MODEL = "openai/google/gemma-4-E4B-it"
API_BASE = "http://localhost:8000/v1"

# Best params from Optuna experiment
TEMPERATURE = 0.4
TOP_P = 0.7
MAX_TOKENS = 2048


def normalize_policy(action: str) -> str:
    return POLICY_NORMALIZE.get(action, action)


def run_case(case: dict, judge: Judge) -> dict:
    """Run a single test case and return detailed results."""
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    rendered = prompt_text.replace("{{text}}", case["text"])

    result = {
        "case_name": case["name"],
        "detection_type": case.get("detection_type", "unknown"),
        "input_text": case["text"],
        "expected_action": case["action"],
        "actual_action": None,
        "is_sensitive": None,
        "ok": False,
        "target_ok": False,
        "context_ok": False,
        "error": None,
        "raw_response": None,
        "parsed_json": None,
        "time_s": 0,
        "failure_reason": None,
    }

    t0 = time.time()

    try:
        response = litellm.completion(
            model=MODEL,
            messages=[{"role": "user", "content": rendered}],
            temperature=TEMPERATURE,
            top_p=TOP_P,
            max_tokens=MAX_TOKENS,
            api_base=API_BASE,
            timeout=60,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content.strip()
        result["raw_response"] = content

        # Extract JSON from markdown blocks
        json_content = content
        if "```json" in content:
            json_content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(json_content)
        result["parsed_json"] = data

        records = []
        for rec in data.get("records", []):
            records.append(
                {
                    "category": rec.get("category", ""),
                    "span": rec.get("span", ""),
                    "confidence": rec.get("confidence", 0),
                    "is_essential": rec.get("is_essential", False),
                }
            )

        sensitivity = data.get("sensitivity", {})
        is_sensitive = sensitivity.get("is_sensitive", False) or len(records) > 0
        result["is_sensitive"] = is_sensitive

        records_dict = [
            {"category": r["category"], "span": r["span"], "is_essential": r["is_essential"]} for r in records
        ]
        judgment = judge.classify(
            sensitivity={"is_sensitive": is_sensitive, "rationale": sensitivity.get("rationale", "")},
            records=records_dict,
            text=case["text"],
        )

        actual_action = normalize_policy(judgment.policy_action)
        result["actual_action"] = actual_action

        expected_sensitive = case["name"] in SENSITIVE_CASES
        result["target_ok"] = expected_sensitive == is_sensitive
        result["context_ok"] = actual_action == case["action"] or (
            judgment.policy_action == "block" and case["action"] == "block"
        )
        result["ok"] = result["target_ok"] and result["context_ok"]

        # Determine failure reason
        if not result["ok"]:
            reasons = []
            if not result["target_ok"]:
                if expected_sensitive and not is_sensitive:
                    reasons.append("FALSE_NEGATIVE: Expected sensitive but model said not sensitive")
                elif not expected_sensitive and is_sensitive:
                    reasons.append("FALSE_POSITIVE: Expected not sensitive but model said sensitive")
            if not result["context_ok"]:
                reasons.append(f"WRONG_ACTION: Expected '{case['action']}', got '{actual_action}'")
            result["failure_reason"] = "; ".join(reasons)

    except json.JSONDecodeError as e:
        result["error"] = f"JSON_PARSE_ERROR: {e}"
        result["failure_reason"] = f"JSON parse failed: {e}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["failure_reason"] = f"Request failed: {e}"

    result["time_s"] = round(time.time() - t0, 1)
    return result


def main():
    judge = Judge()
    results = []

    print(f"Running {len(CASES)} test cases with prompt: {PROMPT_PATH.name}")
    print(f"Model: {MODEL}")
    print(f"Params: temperature={TEMPERATURE}, top_p={TOP_P}, max_tokens={MAX_TOKENS}")
    print("=" * 80)

    for i, case in enumerate(CASES, 1):
        print(
            f"\n[{i}/{len(CASES)}] {case['name']} (expected: {case['action']}, type: {case.get('detection_type', '?')})"
        )
        result = run_case(case, judge)
        results.append(result)

        status = "PASS" if result["ok"] else "FAIL"
        print(
            f"  → {status} | actual={result['actual_action']} | sensitive={result['is_sensitive']} | {result['time_s']}s"
        )
        if result["failure_reason"]:
            print(f"    Reason: {result['failure_reason']}")

        # Save raw response
        safe_name = case["name"].replace("/", "_").replace("(", "").replace(")", "")
        response_file = RESPONSES_DIR / f"{safe_name}.json"
        with open(response_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "case_name": case["name"],
                    "input_text": case["text"],
                    "expected": {"action": case["action"], "sensitive": case["name"] in SENSITIVE_CASES},
                    "raw_response": result["raw_response"],
                    "parsed_json": result["parsed_json"],
                    "actual": {"action": result["actual_action"], "sensitive": result["is_sensitive"]},
                    "passed": result["ok"],
                    "failure_reason": result["failure_reason"],
                    "error": result["error"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed

    morph = [r for r in results if r["detection_type"] == "morphological"]
    ctx = [r for r in results if r["detection_type"] == "contextual"]
    mixed = [r for r in results if r["detection_type"] == "mixed"]
    none_ = [r for r in results if r["detection_type"] == "none"]

    morph_ok = sum(1 for r in morph if r["ok"])
    ctx_ok = sum(1 for r in ctx if r["ok"])
    mixed_ok = sum(1 for r in mixed if r["ok"])
    none_ok = sum(1 for r in none_ if r["ok"])

    print(f"\nOverall: {passed}/{total} ({100 * passed / total:.1f}%)")
    print(f"  Morphological: {morph_ok}/{len(morph)} ({100 * morph_ok / len(morph):.1f}%)")
    print(f"  Contextual:    {ctx_ok}/{len(ctx)} ({100 * ctx_ok / len(ctx):.1f}%)")
    print(f"  Mixed:         {mixed_ok}/{len(mixed)} ({100 * mixed_ok / max(1, len(mixed)):.1f}%)")
    print(f"  None:          {none_ok}/{len(none_)} ({100 * none_ok / max(1, len(none_)):.1f}%)")

    # ── Failure Analysis ─────────────────────────────────────────────────────
    failures = [r for r in results if not r["ok"]]
    if failures:
        print("\n" + "=" * 80)
        print(f"FAILURE ANALYSIS ({len(failures)} failures)")
        print("=" * 80)

        fn = [r for r in failures if r.get("failure_reason", "").startswith("FALSE_NEGATIVE")]
        fp = [r for r in failures if r.get("failure_reason", "").startswith("FALSE_POSITIVE")]
        wa = [r for r in failures if r.get("failure_reason", "").startswith("WRONG_ACTION")]
        err = [r for r in failures if r["error"]]

        print("\nFailure Types:")
        if fn:
            print(f"  FALSE NEGATIVES ({len(fn)}): Model missed sensitive content")
            for r in fn:
                print(
                    f"    - {r['case_name']}: is_sensitive={r['is_sensitive']}, expected_action={r['expected_action']}"
                )
        if fp:
            print(f"  FALSE POSITIVES ({len(fp)}): Model flagged non-sensitive content")
            for r in fp:
                print(f"    - {r['case_name']}: is_sensitive={r['is_sensitive']}")
        if wa:
            print(f"  WRONG ACTIONS ({len(wa)}): Correct sensitivity, wrong policy")
            for r in wa:
                print(f"    - {r['case_name']}: expected={r['expected_action']}, got={r['actual_action']}")
        if err:
            print(f"  ERRORS ({len(err)}): Parse/API failures")
            for r in err:
                print(f"    - {r['case_name']}: {r['error']}")

        print("\n" + "-" * 80)
        print("RAW RESPONSES FOR FAILING CASES")
        print("-" * 80)
        for r in failures:
            print(f"\n{'=' * 60}")
            print(f"Case: {r['case_name']}")
            print(f"Type: {r['detection_type']} | Expected: {r['expected_action']} | Got: {r['actual_action']}")
            print(f"{'=' * 60}")
            print(f"Input: {r['input_text']}")
            print("\nRaw Response:")
            print(r["raw_response"][:500] if r["raw_response"] else f"[ERROR: {r['error']}]")
            if r["parsed_json"]:
                print("\nParsed JSON:")
                print(json.dumps(r["parsed_json"], ensure_ascii=False, indent=2)[:500])

    # ── Pattern Analysis ─────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("PATTERN ANALYSIS")
    print("=" * 80)

    # Analyze contextual failures
    ctx_failures = [r for r in failures if r["detection_type"] == "contextual"]
    if ctx_failures:
        print("\nContextual Detection Failures:")
        for r in ctx_failures:
            if r.get("failure_reason", "").startswith("FALSE_NEGATIVE"):
                print(f"\n  Case: {r['case_name']}")
                print(f"  Text: {r['input_text']}")
                print("  Model classified as NOT sensitive (but should be sensitive)")
                if r["parsed_json"]:
                    recs = r["parsed_json"].get("records", [])
                    if recs:
                        print(f"  Found {len(recs)} records but sensitivity was wrong:")
                        for rec in recs:
                            print(
                                f"    - {rec.get('category')}: '{rec.get('span')}' (essential={rec.get('is_essential')})"
                            )
                    else:
                        print("  No records detected at all")

    # Analyze false positives
    fp_cases = [r for r in failures if r.get("failure_reason", "").startswith("FALSE_POSITIVE")]
    if fp_cases:
        print("\nFalse Positive Cases:")
        for r in fp_cases:
            print(f"\n  Case: {r['case_name']}")
            print(f"  Text: {r['input_text']}")
            if r["parsed_json"]:
                recs = r["parsed_json"].get("records", [])
                print(f"  Model found {len(recs)} records:")
                for rec in recs:
                    print(f"    - {rec.get('category')}: '{rec.get('span')}'")

    # ── Save summary ─────────────────────────────────────────────────────────
    summary = {
        "prompt": PROMPT_PATH.name,
        "model": MODEL,
        "params": {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": MAX_TOKENS},
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "accuracy_pct": round(100 * passed / total, 1),
        "by_type": {
            "morphological": {"total": len(morph), "passed": morph_ok, "pct": round(100 * morph_ok / len(morph), 1)},
            "contextual": {"total": len(ctx), "passed": ctx_ok, "pct": round(100 * ctx_ok / len(ctx), 1)},
            "mixed": {"total": len(mixed), "passed": mixed_ok, "pct": round(100 * mixed_ok / max(1, len(mixed)), 1)},
            "none": {"total": len(none_), "passed": none_ok, "pct": round(100 * none_ok / max(1, len(none_)), 1)},
        },
        "failures": [
            {
                "case_name": r["case_name"],
                "detection_type": r["detection_type"],
                "expected": r["expected_action"],
                "actual": r["actual_action"],
                "reason": r["failure_reason"],
                "error": r["error"],
            }
            for r in failures
        ],
    }

    summary_path = RESPONSES_DIR / "analysis_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nSummary saved to: {summary_path}")
    print(f"Individual responses saved to: {RESPONSES_DIR}/")


if __name__ == "__main__":
    main()
