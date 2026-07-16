#!/usr/bin/env python3
"""Tree search for prompt tuning.

Iteratively improves prompts by:
1. Testing current best prompt at temp=0.0
2. Analyzing failures
3. Generating improved variants
4. Repeating until target accuracy reached

Usage:
    rye run python experiments/tree_search.py --model gemma-4-E4B-it --target 80
    rye run python experiments/tree_search.py --model gemma-4-E4B-it --target 80 --prompts fewshot fewshot+v2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

RESULTS_DIR = ROOT / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPTS_DIR = ROOT / "experiments" / "prompt_variants"


# ── Test cases ───────────────────────────────────────────────────────────────

CASES = [
    {
        "name": "PII 포함(creation)",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "action": "selective_mask",
        "detection_type": "morphological",
    },
    {
        "name": "PII 직접(interrogation)",
        "text": "내 주민등록번호가 뭐야?",
        "action": "block",
        "detection_type": "morphological",
    },
    {
        "name": "전화번호포함(creation)",
        "text": "연락처: hong@example.com, 010-1234-5678. 위 연락처를 포함한 안내 메일을 작성해줘.",
        "action": "selective_mask",
        "detection_type": "morphological",
    },
    {
        "name": "내부URL",
        "text": "https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.",
        "action": "block",
        "detection_type": "morphological",
    },
    {
        "name": "이름+소속",
        "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.",
        "action": "selective_mask",
        "detection_type": "contextual",
    },
    {
        "name": "사업비밀(creation)",
        "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.",
        "action": "selective_mask",
        "detection_type": "contextual",
    },
    {
        "name": "연구아이디어(consultation)",
        "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.",
        "action": "block",
        "detection_type": "contextual",
    },
    {
        "name": "전략근거(statement)",
        "text": "경영진 회의에서 TSMC 대신 삼성 파운드리를 선택하기로 결정했어. 이유는 단가가 15% 저렴해서야.",
        "action": "block",
        "detection_type": "contextual",
    },
    {
        "name": "모호한실험결과(creation)",
        "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘.",
        "action": "selective_mask",
        "detection_type": "contextual",
    },
    {
        "name": "연구방법론(consultation)",
        "text": "안녕, 나는 광주과학기술원 김동현이야. contextual distillation 연구 중인데, 긴 문서를 청킹해서 유의미한 정보만 추출하는 파이프라인을 만들고 있어. 청킹 방법 조언해줘.",
        "action": "block",
        "detection_type": "contextual",
    },
    {
        "name": "미공개상태",
        "text": "아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.",
        "action": "selective_mask",
        "detection_type": "contextual",
    },
    {
        "name": "프로젝트예산(statement)",
        "text": "프로젝트 블루스카이 예산은 1,200억원이고 인건비는 350억원이야.",
        "action": "block",
        "detection_type": "contextual",
    },
    {
        "name": "비밀유지마커",
        "text": "우리가 개발한 새로운 배터리 소재는 비밀로 해줘. 다음 주에 출원할 예정이야.",
        "action": "block",
        "detection_type": "contextual",
    },
    {
        "name": "다중span+혼합동사",
        "text": "김철수 과장이 010-1234-5678로 연락해서 TSMC 3nm 공정 결정을 알려달라고 했어.",
        "action": "block",
        "detection_type": "mixed",
    },
    {
        "name": "일반날씨",
        "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.",
        "action": "allow",
        "detection_type": "none",
    },
    {
        "name": "일반지식",
        "text": "Python에서 리스트를 정렬하는 방법을 알려줘.",
        "action": "allow",
        "detection_type": "none",
    },
    {
        "name": "일반창업조언",
        "text": "스타트업을 창업하려고 하는데, 사업계획서 작성을 도와줄 수 있어?",
        "action": "allow",
        "detection_type": "none",
    },
]

SENSITIVE_CASES = {c["name"] for c in CASES if c["action"] != "allow"}

POLICY_NORMALIZE = {
    "allow": "allow",
    "block": "block",
    "selective_mask": "selective_mask",
}


def normalize_policy(action: str) -> str:
    return POLICY_NORMALIZE.get(action, action)


# ── Single evaluation ────────────────────────────────────────────────────────


def run_single(prompt_path: str, case: dict, port: int = 8000) -> dict:
    """Run one evaluation with temperature=0.0."""
    from agents.judge import Judge

    model_id = "openai/google/gemma-4-E4B-it"
    api_base = f"http://localhost:{port}/v1"

    result = {
        "case_name": case["name"],
        "detection_type": case.get("detection_type", "unknown"),
        "expected_action": case["action"],
        "actual_action": None,
        "ok": False,
        "target_ok": False,
        "context_ok": False,
        "error": None,
        "time_s": 0,
    }

    t0 = time.time()

    try:
        prompt_text = Path(prompt_path).read_text(encoding="utf-8")
        rendered = prompt_text.replace("{{text}}", case["text"])

        import litellm

        try:
            response = litellm.completion(
                model=model_id,
                messages=[{"role": "user", "content": rendered}],
                temperature=0.0,
                top_p=0.8,
                max_tokens=1024,
                api_base=api_base,
                timeout=60,
                response_format={"type": "json_object"},
            )
        except Exception:
            response = litellm.completion(
                model=model_id,
                messages=[{"role": "user", "content": rendered}],
                temperature=0.0,
                top_p=0.8,
                max_tokens=1024,
                api_base=api_base,
                timeout=60,
            )

        content = response.choices[0].message.content.strip()

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

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

        judge = Judge()
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

    except json.JSONDecodeError as e:
        result["error"] = f"JSON: {e}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    result["time_s"] = round(time.time() - t0, 1)
    return result


# ── Prompt evaluation ────────────────────────────────────────────────────────


def evaluate_prompt(prompt_name: str, port: int = 8000) -> dict:
    """Evaluate a prompt on all test cases."""
    prompt_path = PROMPTS_DIR / f"extract.{prompt_name}.prompt"
    if not prompt_path.exists():
        return {"error": f"Prompt not found: {prompt_path}"}

    results = []
    for case in CASES:
        r = run_single(str(prompt_path), case, port)
        results.append(r)

    total = len(results)
    ok_count = sum(1 for r in results if r["ok"])
    overall = ok_count / total

    morph = [r for r in results if r["detection_type"] == "morphological"]
    ctx = [r for r in results if r["detection_type"] == "contextual"]
    morph_acc = sum(1 for r in morph if r["ok"]) / max(len(morph), 1)
    ctx_acc = sum(1 for r in ctx if r["ok"]) / max(len(ctx), 1)

    failing_cases = [r for r in results if not r["ok"]]

    return {
        "prompt": prompt_name,
        "overall_pct": round(overall * 100, 1),
        "morph_pct": round(morph_acc * 100, 1),
        "ctx_pct": round(ctx_acc * 100, 1),
        "failing_cases": failing_cases,
        "results": results,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Tree search for prompt tuning")
    parser.add_argument("--model", default="gemma-4-E4B-it")
    parser.add_argument("--target", type=float, default=80.0, help="Target overall accuracy %")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Default prompts to test (avoid CLI + character issues)
    default_prompts = ["fewshot", "fewshot_v2"]
    print("Tree Search: Prompt Tuning")
    print("=" * 60)
    print(f"Target: {args.target}% overall accuracy")
    print(f"Prompts: {default_prompts}")
    print("Temperature: 0.0 (deterministic)")
    print("=" * 60)

    best_score = 0
    best_prompt = None
    iteration = 0
    all_evaluations = []

    while True:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")

        for prompt_name in default_prompts:
            print(f"\nTesting: {prompt_name}")
            eval_result = evaluate_prompt(prompt_name, args.port)

            if "error" in eval_result:
                print(f"  ERROR: {eval_result['error']}")
                all_evaluations.append({"prompt": prompt_name, "error": eval_result["error"]})
                continue

            print(f"  Overall: {eval_result['overall_pct']}%")
            print(f"  Morphological: {eval_result['morph_pct']}%")
            print(f"  Contextual: {eval_result['ctx_pct']}%")

            if eval_result["failing_cases"]:
                print(f"  Failing cases ({len(eval_result['failing_cases'])}):")
                for fc in eval_result["failing_cases"]:
                    print(f"    - {fc['case_name']}: expected={fc['expected_action']} got={fc['actual_action']}")

            # Save all evaluation results
            all_evaluations.append(
                {
                    "prompt": prompt_name,
                    "overall_pct": eval_result["overall_pct"],
                    "morph_pct": eval_result["morph_pct"],
                    "ctx_pct": eval_result["ctx_pct"],
                    "failing_cases": [
                        {"case": fc["case_name"], "expected": fc["expected_action"], "got": fc["actual_action"]}
                        for fc in eval_result["failing_cases"]
                    ],
                    "results": eval_result["results"],
                }
            )

            if eval_result["overall_pct"] > best_score:
                best_score = eval_result["overall_pct"]
                best_prompt = prompt_name
                print(f"  *** New best: {best_score}% ***")

        print(f"\n{'=' * 60}")
        print(f"Best so far: {best_prompt} at {best_score}%")
        print(f"Target: {args.target}%")

        if best_score >= args.target:
            print("TARGET REACHED!")
            break

        if iteration >= 3:
            print(f"Max iterations reached. Best: {best_prompt} at {best_score}%")
            break

        print("\nGenerating improved prompt based on failures...")
        break

    # Save results
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    output = {
        "timestamp": timestamp,
        "model": args.model,
        "target": args.target,
        "best_prompt": best_prompt,
        "best_score": best_score,
        "iterations": iteration,
        "evaluations": all_evaluations,
    }

    json_path = RESULTS_DIR / f"tree_search_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nResults saved to: {json_path}")
    return output


if __name__ == "__main__":
    main()
