#!/usr/bin/env python3
"""Unified experiment runner for Privacy Router prompt + parameter tuning.

Generates prompt variants, runs Optuna tuning per model with N>=5 replication,
outputs standardized JSON only (HTML viewer is separate).

Usage:
    rye run python experiments/run_experiment.py --model gemma-4-E4B-it --trials 50 --n-per-config 10
    rye run python experiments/run_experiment.py --model gemma-4-E4B-it --no-vllm --trials 30 --concurrent 4
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import optuna

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

RESULTS_DIR = ROOT / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

from experiments.prompts import (  # noqa: E402
    generate_all_variants,
    get_variant_techniques,
)

# ── Local models ─────────────────────────────────────────────────────────────

LOCAL_MODELS = {
    "gemma-4-E2B-it": {"model_path": "google/gemma-4-E2B-it", "params": "2B", "size_gb": 10},
    "gemma-4-E4B-it": {"model_path": "google/gemma-4-E4B-it", "params": "4B", "size_gb": 15},
    "ministral-3b": {"model_path": "mistralai/Ministral-3-3B-Instruct-2512", "params": "3B", "size_gb": 9},
    "granite-4.1-8b": {"model_path": "ibm-granite/granite-4.1-8b", "params": "8B", "size_gb": 17},
    "gemma-4-26B-A4B-it": {"model_path": "google/gemma-4-26B-A4B-it", "params": "26B MoE", "size_gb": 49},
}


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


# ── vLLM management ──────────────────────────────────────────────────────────


def start_vllm(model_key: str, port: int = 8000, gpu_mem: float = 0.75) -> subprocess.Popen | None:
    """Start vLLM server if not already running."""
    import urllib.request

    try:
        urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2)
        return None
    except Exception:
        pass

    cfg = LOCAL_MODELS[model_key]
    print(f"  Starting vLLM: {model_key} on port {port}...")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            cfg["model_path"],
            "--port",
            str(port),
            "--dtype",
            "auto",
            "--max-model-len",
            "4096",
            "--gpu-memory-utilization",
            str(gpu_mem),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    for _ in range(120):
        time.sleep(2)
        try:
            urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2)
            print(f"  vLLM ready on port {port}")
            return proc
        except Exception:
            pass
    print("  WARNING: vLLM not ready after 240s")
    return proc


def stop_vllm(proc: subprocess.Popen | None):
    if proc:
        proc.terminate()
        proc.wait(timeout=10)


# ── Single evaluation ────────────────────────────────────────────────────────


def run_single(
    prompt_path: str, case: dict, temperature: float, top_p: float, max_tokens: int, port: int = 8000
) -> dict:
    """Run one evaluation with given parameters."""
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

        # Cap max_tokens to avoid context window exceeded
        safe_max_tokens = min(max_tokens, 2048)

        import litellm

        # Try with response_format first, fallback without it
        try:
            response = litellm.completion(
                model=model_id,
                messages=[{"role": "user", "content": rendered}],
                temperature=temperature,
                top_p=top_p,
                max_tokens=safe_max_tokens,
                api_base=api_base,
                timeout=60,
                response_format={"type": "json_object"},
            )
        except Exception:
            response = litellm.completion(
                model=model_id,
                messages=[{"role": "user", "content": rendered}],
                temperature=temperature,
                top_p=top_p,
                max_tokens=safe_max_tokens,
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


# ── Optuna objective with N>=5 replication ───────────────────────────────────


def create_objective(prompt_paths: dict[str, str], port: int = 8000, n_per_config: int = 10, concurrent: int = 4):
    """Create Optuna objective function with N>=5 replication per config."""

    def objective(trial: optuna.Trial) -> float:
        prompt_name = trial.suggest_categorical("prompt", list(prompt_paths.keys()))
        temperature = trial.suggest_float("temperature", 0.0, 1.0, step=0.1)
        top_p = trial.suggest_float("top_p", 0.7, 1.0, step=0.05)
        max_tokens = trial.suggest_categorical("max_tokens", [1024, 2048])

        prompt_path = prompt_paths[prompt_name]
        techniques = get_variant_techniques(prompt_name)
        tech_str = "+".join(techniques) if techniques else "zeroshot"

        print(
            f"\n  Trial {trial.number}: {prompt_name} [{tech_str}] temp={temperature} top_p={top_p} max_tok={max_tokens} (N={n_per_config})"
        )

        # Run ALL cases × N replications concurrently
        all_results = []
        with ThreadPoolExecutor(max_workers=concurrent * 2) as executor:
            futures = []
            for case in CASES:
                for _ in range(n_per_config):
                    futures.append(executor.submit(run_single, prompt_path, case, temperature, top_p, max_tokens, port))
            for future in as_completed(futures):
                all_results.append(future.result())

        total = len(all_results)
        if total == 0:
            return 0.0

        ok_count = sum(1 for r in all_results if r["ok"])
        overall = ok_count / total

        morph = [r for r in all_results if r["detection_type"] == "morphological"]
        ctx = [r for r in all_results if r["detection_type"] == "contextual"]
        morph_acc = sum(1 for r in morph if r["ok"]) / max(len(morph), 1)
        ctx_acc = sum(1 for r in ctx if r["ok"]) / max(len(ctx), 1)

        case_actions: dict[str, list[str]] = {}
        for r in all_results:
            case_actions.setdefault(r["case_name"], []).append(r.get("actual_action", "ERROR"))
        consistency = sum(1.0 if len(set(v)) == 1 else 0.0 for v in case_actions.values()) / max(len(case_actions), 1)
        avg_time = sum(r["time_s"] for r in all_results) / total
        errors = sum(1 for r in all_results if r.get("error"))

        score = (
            0.30 * overall + 0.25 * ctx_acc + 0.20 * morph_acc + 0.15 * consistency + 0.10 * max(0, 1 - avg_time / 10)
        )

        trial.set_user_attr("overall_pct", round(overall * 100, 1))
        trial.set_user_attr("morph_pct", round(morph_acc * 100, 1))
        trial.set_user_attr("ctx_pct", round(ctx_acc * 100, 1))
        trial.set_user_attr("consistency_pct", round(consistency * 100, 1))
        trial.set_user_attr("avg_time_s", round(avg_time, 1))
        trial.set_user_attr("techniques", tech_str)
        trial.set_user_attr("errors", errors)
        trial.set_user_attr("n_per_config", n_per_config)

        print(
            f"    -> {score:.3f} overall={overall:.1%} morph={morph_acc:.1%} ctx={ctx_acc:.1%} consist={consistency:.1%} time={avg_time:.1f}s errors={errors}"
        )

        return score

    return objective


# ── JSON output schema ───────────────────────────────────────────────────────


def build_output(model_key: str, study: optuna.Study, prompt_paths: dict[str, str]) -> dict:
    """Build standardized JSON output."""
    trials_data = []
    for t in study.trials:
        if t.value is None:
            continue
        trials_data.append(
            {
                "trial_id": t.number,
                "score": round(t.value, 4),
                "prompt": t.params.get("prompt", ""),
                "techniques": t.user_attrs.get("techniques", ""),
                "temperature": t.params.get("temperature", 0),
                "top_p": t.params.get("top_p", 0),
                "max_tokens": t.params.get("max_tokens", 0),
                "n_per_config": t.user_attrs.get("n_per_config", 1),
                "metrics": {
                    "overall_accuracy_pct": t.user_attrs.get("overall_pct", 0),
                    "morphological_accuracy_pct": t.user_attrs.get("morph_pct", 0),
                    "contextual_accuracy_pct": t.user_attrs.get("ctx_pct", 0),
                    "consistency_pct": t.user_attrs.get("consistency_pct", 0),
                    "avg_latency_s": t.user_attrs.get("avg_time_s", 0),
                    "errors": t.user_attrs.get("errors", 0),
                },
            }
        )

    best = study.best_trial
    sorted_trials = sorted(trials_data, key=lambda t: t["score"], reverse=True)

    return {
        "$schema": "privacy-router-experiment-v1",
        "version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment": {
            "model": model_key,
            "model_info": LOCAL_MODELS.get(model_key, {}),
            "total_trials": len(trials_data),
            "test_cases": len(CASES),
            "n_per_config": trials_data[0]["n_per_config"] if trials_data else 1,
            "detection_types": {
                "morphological": len([c for c in CASES if c["detection_type"] == "morphological"]),
                "contextual": len([c for c in CASES if c["detection_type"] == "contextual"]),
                "mixed": len([c for c in CASES if c["detection_type"] == "mixed"]),
                "none": len([c for c in CASES if c["detection_type"] == "none"]),
            },
        },
        "best": {
            "trial_id": best.number,
            "score": round(best.value, 4),
            "prompt": best.params.get("prompt", ""),
            "techniques": best.user_attrs.get("techniques", ""),
            "params": {
                "temperature": best.params.get("temperature", 0),
                "top_p": best.params.get("top_p", 0),
                "max_tokens": best.params.get("max_tokens", 0),
            },
            "metrics": {
                "overall_accuracy_pct": best.user_attrs.get("overall_pct", 0),
                "morphological_accuracy_pct": best.user_attrs.get("morph_pct", 0),
                "contextual_accuracy_pct": best.user_attrs.get("ctx_pct", 0),
                "consistency_pct": best.user_attrs.get("consistency_pct", 0),
                "avg_latency_s": best.user_attrs.get("avg_time_s", 0),
            },
        },
        "leaderboard": sorted_trials[:20],
        "trials": trials_data,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Privacy Router Experiment Runner")
    parser.add_argument("--model", default="gemma-4-E4B-it", choices=list(LOCAL_MODELS.keys()))
    parser.add_argument("--trials", type=int, default=50, help="Number of Optuna trials")
    parser.add_argument("--n-per-config", type=int, default=10, help="N>=5 evaluations per config")
    parser.add_argument("--concurrent", type=int, default=4, help="Concurrent LLM calls per case")
    parser.add_argument("--prompts", nargs="*", default=None, help="Subset of prompt variants")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--gpu-mem", type=float, default=0.75, help="GPU memory utilization")
    parser.add_argument("--no-vllm", action="store_true")
    args = parser.parse_args()

    # Validate N>=5
    if args.n_per_config < 5:
        print(f"WARNING: n_per_config={args.n_per_config} < 5, setting to 5")
        args.n_per_config = 5

    # Generate prompt variants
    print("Generating prompt variants...")
    all_paths = generate_all_variants()

    # Add standalone optimized prompts (not generated by build_prompt)
    standalone_prompts = {
        "fewshot_v2": str(ROOT / "experiments" / "prompt_variants" / "extract.fewshot_v2.prompt"),
    }
    all_paths.update(standalone_prompts)

    prompt_paths = {k: v for k, v in all_paths.items() if k in args.prompts} if args.prompts else all_paths
    print(f"  {len(prompt_paths)} variants selected")

    # Start vLLM
    vllm_proc = None
    if not args.no_vllm:
        vllm_proc = start_vllm(args.model, args.port, args.gpu_mem)

    try:
        # Run Optuna
        study_name = f"{args.model}-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"
        storage = f"sqlite:///{RESULTS_DIR / 'studies.db'}"

        print(f"\n{'=' * 60}")
        print(f"Model: {args.model} | Trials: {args.trials} | N per config: {args.n_per_config}")
        print(f"Concurrent: {args.concurrent} | Prompts: {len(prompt_paths)}")
        print(f"Study: {study_name}")
        print(f"{'=' * 60}")

        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="maximize",
            load_if_exists=True,
        )

        objective = create_objective(prompt_paths, args.port, args.n_per_config, args.concurrent)
        study.optimize(objective, n_trials=args.trials)

        # Build output
        output = build_output(args.model, study, prompt_paths)

        # Save JSON only
        json_path = RESULTS_DIR / f"{study_name}.json"
        with open(json_path, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # Print summary
        best = study.best_trial
        print(f"\n{'=' * 60}")
        print("COMPLETE")
        print(f"{'=' * 60}")
        print(f"  Best trial: #{best.number}")
        print(f"  Score: {best.value:.3f}")
        print(f"  Prompt: {best.params.get('prompt')} [{best.user_attrs.get('techniques')}]")
        print(
            f"  Params: temp={best.params.get('temperature')} top_p={best.params.get('top_p')} max_tok={best.params.get('max_tokens')}"
        )
        print(f"  Overall: {best.user_attrs.get('overall_pct')}%")
        print(f"  Morphological: {best.user_attrs.get('morph_pct')}%")
        print(f"  Contextual: {best.user_attrs.get('ctx_pct')}%")
        print(f"  Consistency: {best.user_attrs.get('consistency_pct')}%")
        print(f"  Latency: {best.user_attrs.get('avg_time_s')}s")
        print(f"\n  JSON: {json_path}")
        print("\n  View results: open experiments/results/viewer.html and drop the JSON file")

    finally:
        stop_vllm(vllm_proc)


if __name__ == "__main__":
    main()
