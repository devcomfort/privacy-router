#!/usr/bin/env python3
"""Optuna-based prompt + parameter tuning for Privacy Router Extractor.

Uses local models via vLLM to minimize costs.
Tunes: prompt variant, temperature, top_p, max_tokens, presence_penalty.
Evaluates: overall accuracy, morphological accuracy, contextual accuracy, consistency.

Usage:
    rye run python experiments/optuna_tuning.py --trials 50
    rye run python experiments/optuna_tuning.py --model gemma-4-E4B-it --trials 30
    rye run python experiments/optuna_tuning.py --study-name my-study --trials 100
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import optuna

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

RESULTS_DIR = ROOT / "experiments" / "optuna_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Local model configs ─────────────────────────────────────────────────────

LOCAL_MODELS = {
    "gemma-4-E4B-it": {
        "model_path": "google/gemma-4-E4B-it",
        "params": "4B",
        "size_gb": 15,
        "port": 8000,
    },
    "gemma-4-E2B-it": {
        "model_path": "google/gemma-4-E2B-it",
        "params": "2B",
        "size_gb": 10,
        "port": 8000,
    },
    "ministral-3b": {
        "model_path": "mistralai/Ministral-3-3B-Instruct-2512",
        "params": "3B",
        "size_gb": 9,
        "port": 8000,
    },
    "granite-4.1-8b": {
        "model_path": "ibm-granite/granite-4.1-8b",
        "params": "8B",
        "size_gb": 17,
        "port": 8000,
    },
    "gemma-4-26B-A4B-it": {
        "model_path": "google/gemma-4-26B-A4B-it",
        "params": "26B MoE",
        "size_gb": 49,
        "port": 8000,
    },
}


# ── Prompt variants ─────────────────────────────────────────────────────────

PROMPT_VARIANTS = {
    "baseline": str(ROOT / "eval" / "prompts" / "extract.baseline.prompt"),
    "threeharm": str(ROOT / "eval" / "prompts" / "extract.threeharm.prompt"),
    "twostep": str(ROOT / "eval" / "prompts" / "extract.twostep.prompt"),
    "hybrid": str(ROOT / "eval" / "prompts" / "extract.hybrid.prompt"),
}


# ── Test cases ───────────────────────────────────────────────────────────────

CASES = [
    # morphological
    {
        "name": "PII 포함(creation)",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "action": "selective_mask",
        "tags": ["identity", "creation"],
        "detection_type": "morphological",
    },
    {
        "name": "PII 직접(interrogation)",
        "text": "내 주민등록번호가 뭐야?",
        "action": "block",
        "tags": ["identity", "interrogation"],
        "detection_type": "morphological",
    },
    {
        "name": "전화번호포함(creation)",
        "text": "연락처: hong@example.com, 010-1234-5678. 위 연락처를 포함한 안내 메일을 작성해줘.",
        "action": "selective_mask",
        "tags": ["identity", "creation"],
        "detection_type": "morphological",
    },
    {
        "name": "내부URL",
        "text": "https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.",
        "action": "block",
        "tags": ["safety", "access"],
        "detection_type": "morphological",
    },
    # contextual
    {
        "name": "이름+소속",
        "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.",
        "action": "selective_mask",
        "tags": ["identity", "competitive"],
        "detection_type": "contextual",
    },
    {
        "name": "사업비밀(creation)",
        "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.",
        "action": "selective_mask",
        "tags": ["competitive", "creation"],
        "detection_type": "contextual",
    },
    {
        "name": "연구아이디어(consultation)",
        "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.",
        "action": "block",
        "tags": ["competitive", "consultation"],
        "detection_type": "contextual",
    },
    {
        "name": "전략근거(statement)",
        "text": "경영진 회의에서 TSMC 대신 삼성 파운드리를 선택하기로 결정했어. 이유는 단가가 15% 저렴해서야.",
        "action": "block",
        "tags": ["competitive", "statement"],
        "detection_type": "contextual",
    },
    {
        "name": "모호한실험결과(creation)",
        "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘.",
        "action": "selective_mask",
        "tags": ["competitive", "creation"],
        "detection_type": "contextual",
    },
    {
        "name": "연구방법론(consultation)",
        "text": "안녕, 나는 광주과학기술원 김동현이야. contextual distillation 연구 중인데, 긴 문서를 청킹해서 유의미한 정보만 추출하는 파이프라인을 만들고 있어. 청킹 방법 조언해줘.",
        "action": "block",
        "tags": ["identity", "competitive", "consultation"],
        "detection_type": "contextual",
    },
    {
        "name": "미공개상태",
        "text": "아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.",
        "action": "selective_mask",
        "tags": ["competitive", "creation"],
        "detection_type": "contextual",
    },
    {
        "name": "프로젝트예산(statement)",
        "text": "프로젝트 블루스카이 예산은 1,200억원이고 인건비는 350억원이야.",
        "action": "block",
        "tags": ["competitive", "statement"],
        "detection_type": "contextual",
    },
    {
        "name": "비밀유지마커",
        "text": "우리가 개발한 새로운 배터리 소재는 비밀로 해줘. 다음 주에 출원할 예정이야.",
        "action": "block",
        "tags": ["competitive", "statement"],
        "detection_type": "contextual",
    },
    # mixed
    {
        "name": "다중span+혼합동사",
        "text": "김철수 과장이 010-1234-5678로 연락해서 TSMC 3nm 공정 결정을 알려달라고 했어.",
        "action": "block",
        "tags": ["identity", "competitive", "interrogation"],
        "detection_type": "mixed",
    },
    # none
    {
        "name": "일반날씨",
        "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.",
        "action": "allow",
        "tags": ["none"],
        "detection_type": "none",
    },
    {
        "name": "일반지식",
        "text": "Python에서 리스트를 정렬하는 방법을 알려줘.",
        "action": "allow",
        "tags": ["none"],
        "detection_type": "none",
    },
    {
        "name": "일반창업조언",
        "text": "스타트업을 창업하려고 하는데, 사업계획서 작성을 도와줄 수 있어?",
        "action": "allow",
        "tags": ["none"],
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


# ── vLLM server management ──────────────────────────────────────────────────


def start_vllm_server(model_key: str) -> subprocess.Popen | None:
    """Start vLLM server for the given model. Returns Popen or None if already running."""
    cfg = LOCAL_MODELS[model_key]
    port = cfg["port"]

    # Check if server is already running
    try:
        import urllib.request

        urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2)
        print(f"  vLLM server already running on port {port}")
        return None
    except Exception:
        pass

    print(f"  Starting vLLM server for {model_key} on port {port}...")
    cmd = [
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
        "0.9",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait for server to be ready
    for _ in range(60):
        time.sleep(2)
        try:
            urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2)
            print(f"  vLLM server ready on port {port}")
            return proc
        except Exception:
            pass

    print("  WARNING: vLLM server not ready after 120s")
    return proc


def stop_vllm_server(proc: subprocess.Popen | None):
    """Stop vLLM server."""
    if proc:
        proc.terminate()
        proc.wait(timeout=10)
        print("  vLLM server stopped")


# ── Single evaluation ────────────────────────────────────────────────────────


def run_single(
    prompt_path: str,
    model_key: str,
    case: dict,
    temperature: float,
    top_p: float,
    max_tokens: int,
    port: int = 8000,
) -> dict:
    """Run one evaluation with given parameters."""
    from agents.judge import Judge
    from agents.llm import load_prompt, render_prompt

    cfg = LOCAL_MODELS[model_key]
    model_id = f"openai/{cfg['model_path']}"
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
        # Load and render prompt
        prompt_data = load_prompt(prompt_path)
        rendered = render_prompt(prompt_data["template"], text=case["text"])

        # Call LLM directly with custom parameters
        import litellm

        response = litellm.completion(
            model=model_id,
            messages=[{"role": "user", "content": rendered}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            api_base=api_base,
            timeout=60,
        )
        content = response.choices[0].message.content.strip()

        # Parse JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        # Extract records
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

        # Judge
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
        result["error"] = f"JSON parse error: {e}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    result["time_s"] = round(time.time() - t0, 1)
    return result


# ── Optuna objective ─────────────────────────────────────────────────────────


def create_objective(model_key: str, n_trials_per_case: int = 1):
    """Create Optuna objective function for the given model."""

    def objective(trial: optuna.Trial) -> float:
        # Sample hyperparameters
        prompt_name = trial.suggest_categorical("prompt", list(PROMPT_VARIANTS.keys()))
        temperature = trial.suggest_float("temperature", 0.0, 1.0, step=0.1)
        top_p = trial.suggest_float("top_p", 0.7, 1.0, step=0.05)
        max_tokens = trial.suggest_categorical("max_tokens", [1024, 2048, 4096])
        presence_penalty = trial.suggest_float("presence_penalty", 0.0, 0.5, step=0.1)

        prompt_path = PROMPT_VARIANTS[prompt_name]

        print(
            f"\n  Trial {trial.number}: prompt={prompt_name}, temp={temperature}, top_p={top_p}, max_tokens={max_tokens}, pp={presence_penalty}"
        )

        # Evaluate on all cases
        all_results = []
        for case in CASES:
            for _ in range(n_trials_per_case):
                r = run_single(
                    prompt_path=prompt_path,
                    model_key=model_key,
                    case=case,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                )
                all_results.append(r)

        # Calculate metrics
        total = len(all_results)
        if total == 0:
            return 0.0

        ok_count = sum(1 for r in all_results if r["ok"])
        overall_accuracy = ok_count / total

        # Per detection_type
        morph_results = [r for r in all_results if r["detection_type"] == "morphological"]
        ctx_results = [r for r in all_results if r["detection_type"] == "contextual"]

        morph_accuracy = sum(1 for r in morph_results if r["ok"]) / max(len(morph_results), 1)
        ctx_accuracy = sum(1 for r in ctx_results if r["ok"]) / max(len(ctx_results), 1)

        # Consistency (same case → same action)
        case_actions: dict[str, list[str]] = {}
        for r in all_results:
            case_actions.setdefault(r["case_name"], []).append(r.get("actual_action", "ERROR"))
        consistency_scores = []
        for actions in case_actions.values():
            consistency_scores.append(1.0 if len(set(actions)) == 1 else 0.0)
        avg_consistency = sum(consistency_scores) / max(len(consistency_scores), 1)

        # Weighted score
        score = (
            0.30 * overall_accuracy
            + 0.25 * ctx_accuracy
            + 0.20 * morph_accuracy
            + 0.15 * avg_consistency
            + 0.10 * (1.0 - min(sum(r["time_s"] for r in all_results) / total / 10, 1.0))
        )

        # Store detailed results in trial user attributes
        trial.set_user_attr("overall_accuracy", round(overall_accuracy * 100, 1))
        trial.set_user_attr("morphological_accuracy", round(morph_accuracy * 100, 1))
        trial.set_user_attr("contextual_accuracy", round(ctx_accuracy * 100, 1))
        trial.set_user_attr("consistency", round(avg_consistency * 100, 1))
        trial.set_user_attr("avg_time", round(sum(r["time_s"] for r in all_results) / total, 1))

        print(
            f"    -> score={score:.3f} overall={overall_accuracy:.1%} morph={morph_accuracy:.1%} ctx={ctx_accuracy:.1%} consistency={avg_consistency:.1%}"
        )

        return score

    return objective


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Optuna prompt + parameter tuning")
    parser.add_argument(
        "--model", default="gemma-4-E4B-it", choices=list(LOCAL_MODELS.keys()), help="Local model to use"
    )
    parser.add_argument("--trials", type=int, default=30, help="Number of Optuna trials")
    parser.add_argument("--n-per-case", type=int, default=1, help="Evaluations per test case per trial")
    parser.add_argument("--study-name", default=None, help="Optuna study name")
    parser.add_argument("--no-vllm", action="store_true", help="Assume vLLM is already running")
    args = parser.parse_args()

    study_name = args.study_name or f"privacy-router-{args.model}-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"
    storage = f"sqlite:///{RESULTS_DIR / 'optuna_studies.db'}"

    print("=" * 60)
    print("Optuna Prompt + Parameter Tuning")
    print("=" * 60)
    print(f"Model: {args.model} ({LOCAL_MODELS[args.model]['params']})")
    print(f"Trials: {args.trials}")
    print(f"Evals per case: {args.n_per_case}")
    print(f"Study: {study_name}")
    print(f"Storage: {storage}")
    print("=" * 60)

    # Start vLLM server
    vllm_proc = None
    if not args.no_vllm:
        vllm_proc = start_vllm_server(args.model)

    try:
        # Create Optuna study
        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="maximize",
            load_if_exists=True,
        )

        # Run optimization
        objective = create_objective(args.model, args.n_per_case)
        study.optimize(objective, n_trials=args.trials)

        # Print results
        print(f"\n{'=' * 60}")
        print("BEST TRIAL")
        print(f"{'=' * 60}")
        best = study.best_trial
        print(f"  Score: {best.value:.3f}")
        print(f"  Params: {best.params}")
        print(f"  Overall Accuracy: {best.user_attrs.get('overall_accuracy', '-')}%")
        print(f"  Morphological: {best.user_attrs.get('morphological_accuracy', '-')}%")
        print(f"  Contextual: {best.user_attrs.get('contextual_accuracy', '-')}%")
        print(f"  Consistency: {best.user_attrs.get('consistency', '-')}%")
        print(f"  Avg Time: {best.user_attrs.get('avg_time', '-')}s")

        # Save all trials
        trials_path = RESULTS_DIR / f"{study_name}.json"
        trials_data = []
        for t in study.trials:
            trials_data.append(
                {
                    "number": t.number,
                    "value": t.value,
                    "params": t.params,
                    "user_attrs": t.user_attrs,
                    "state": str(t.state),
                }
            )
        with open(trials_path, "w") as f:
            json.dump(
                {
                    "study_name": study_name,
                    "model": args.model,
                    "best_trial": best.number,
                    "best_score": best.value,
                    "best_params": best.params,
                    "trials": trials_data,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\n  Results saved to: {trials_path}")

        # Print top 5 trials
        print(f"\n{'=' * 60}")
        print("TOP 5 TRIALS")
        print(f"{'=' * 60}")
        sorted_trials = sorted(study.trials, key=lambda t: t.value if t.value else 0, reverse=True)
        for t in sorted_trials[:5]:
            print(
                f"  #{t.number}: score={t.value:.3f} prompt={t.params.get('prompt')} temp={t.params.get('temperature')} overall={t.user_attrs.get('overall_accuracy', '-')}% ctx={t.user_attrs.get('contextual_accuracy', '-')}%"
            )

    finally:
        stop_vllm_server(vllm_proc)


if __name__ == "__main__":
    main()
