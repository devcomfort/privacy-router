#!/usr/bin/env python3
"""Optuna-based parameter tuning with baseline measurement and profile saving.

Workflow:
  1. Measure baseline (current parameters) on tuning cases
  2. Run Optuna to find optimal parameters
  3. Validate best params on full eval cases
  4. Save all parameter profiles with scores

Usage:
    scripts/tune_params.py --model ministral-3b-2512 --trials 20
    scripts/tune_params.py --all --trials 15
    scripts/tune_params.py --model gemma-4-26b-a4b-it --baseline-only
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import optuna
import litellm

optuna.logging.set_verbosity(optuna.logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.llm import load_prompt, render_prompt

# ── Tuning cases (10 subset for fast search) ─────────────────────────────────
TUNING_CASES = [
    {"text": "내 주민등록번호가 뭐야?", "expected_sensitive": True, "expected_essential": True},
    {"text": "GIST 도서관 스터디룸을 예약하고 싶습니다. 학번 20251197, 이름 김동현, 전화번호 010-1234-5678.", "expected_sensitive": True, "expected_essential": True},
    {"text": "새로운 Attention 대체 아이디어를 실험하고 싶어", "expected_sensitive": True, "expected_essential": True},
    {"text": "주민등록번호 포함한 이메일을 작성해줘", "expected_sensitive": True, "expected_essential": False},
    {"text": "오늘 날씨가 좋네요", "expected_sensitive": False, "expected_essential": False},
    {"text": "TSMC 3nm 공정을 채택하기로 결정했어", "expected_sensitive": True, "expected_essential": True},
    {"text": "프로젝트 예산은 850억원이야", "expected_sensitive": True, "expected_essential": True},
    {"text": "Python 기본 문법을 알려줘", "expected_sensitive": False, "expected_essential": False},
    {"text": "비밀로 해줘 — 아직 논문에 제출하지 않았어", "expected_sensitive": True, "expected_essential": True},
    {"text": "010-9876-5432로 연락해줘", "expected_sensitive": True, "expected_essential": False},
]

# ── Baseline profile (current default parameters) ────────────────────────────
BASELINE_PROFILE = {
    "temperature": 0.0,
    "max_tokens": 4096,
    "top_p": 1.0,
    "use_json_mode": False,
    "use_system_msg": False,
    "label": "baseline",
}

RESULTS_DIR = Path("docs/developments/results/tuning")


def call_with_params(
    model_id: str,
    api_base: str | None,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    top_p: float,
    use_json_mode: bool,
) -> str | None:
    """Call LLM with specific parameters, return content or None."""
    kwargs = dict(
        model=model_id,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
    )
    if api_base:
        kwargs["api_base"] = api_base
        kwargs["api_key"] = "dummy"
    else:
        kwargs["api_key"] = os.getenv("OPENROUTER_API_KEY", "")

    # EXAONE models require response_format=json_object for valid JSON
    if "EXAONE" in model_id.upper():
        kwargs["response_format"] = {"type": "json_object"}
        # Small models need reduced max_tokens (4096 ctx limit)
        if "1.2B" in model_id:
            kwargs["max_tokens"] = min(max_tokens, 512)
    elif use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = litellm.completion(**kwargs)
    return response.choices[0].message.content


def parse_response(content: str) -> dict | None:
    """Extract JSON from LLM response."""
    import re

    if not content:
        return None

    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    if "<think>" in content:
        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()

    if not content.startswith("{"):
        json_matches = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL))
        if json_matches:
            content = json_matches[-1].group(0)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def evaluate_params(
    model_id: str,
    api_base: str | None,
    params: dict,
    cases: list[dict],
) -> dict:
    """Evaluate a parameter configuration. Returns detailed results."""
    import time as _time

    # Use short prompt for small models (≤2B) due to context limit
    is_small = "1.2B" in model_id or "E2B" in model_id
    if is_small:
        with open("agents/extractor/extract.short.prompt") as f:
            template = f.read().strip()
    else:
        prompt_data = load_prompt(str(Path("agents/extractor/extract.prompt")))
        template = prompt_data["template"]
    results = []
    total_latency = 0.0

    for case in cases:
        start = _time.time()
        try:
            rendered = template.replace("{{text}}", case["text"]) if is_small else render_prompt(template, text=case["text"])

            if params.get("use_system_msg"):
                messages = [
                    {"role": "system", "content": "You are a privacy-sensitive information detector. Output ONLY valid JSON."},
                    {"role": "user", "content": rendered},
                ]
            else:
                messages = [{"role": "user", "content": rendered}]

            content = call_with_params(
                model_id=model_id,
                api_base=api_base,
                messages=messages,
                temperature=params["temperature"],
                max_tokens=params["max_tokens"],
                top_p=params["top_p"],
                use_json_mode=params.get("use_json_mode", False),
            )

            data = parse_response(content)
            latency = _time.time() - start
            total_latency += latency

            if data:
                is_sensitive = data.get("sensitivity", {}).get("is_sensitive", False)
                records = data.get("records", [])
                sensitivity_ok = is_sensitive == case["expected_sensitive"]

                essential_ok = True
                if case["expected_sensitive"] and records:
                    has_essential = any(r.get("is_essential", False) for r in records)
                    essential_ok = has_essential == case["expected_essential"]

                results.append({
                    "text": case["text"][:50],
                    "sensitivity_ok": sensitivity_ok,
                    "essential_ok": essential_ok,
                    "correct": sensitivity_ok and essential_ok,
                    "latency_s": round(latency, 2),
                    "parsed": True,
                })
            else:
                results.append({
                    "text": case["text"][:50],
                    "sensitivity_ok": False,
                    "essential_ok": False,
                    "correct": False,
                    "latency_s": round(latency, 2),
                    "parsed": False,
                })
        except Exception as e:
            latency = _time.time() - start
            results.append({
                "text": case["text"][:50],
                "sensitivity_ok": False,
                "essential_ok": False,
                "correct": False,
                "latency_s": round(latency, 2),
                "error": str(e)[:100],
            })

    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    avg_latency = total_latency / total if total else 0

    return {
        "score": correct / total if total else 0,
        "correct": correct,
        "total": total,
        "avg_latency_s": round(avg_latency, 2),
        "cases": results,
    }


def run_baseline(model_key: str, model_id: str, api_base: str | None) -> dict:
    """Run baseline measurement with current default parameters."""
    print(f"\n{'─'*50}")
    print(f"  BASELINE: {model_key}")
    print(f"  Params: temp={BASELINE_PROFILE['temperature']}, "
          f"max_tok={BASELINE_PROFILE['max_tokens']}, "
          f"top_p={BASELINE_PROFILE['top_p']}, "
          f"json={BASELINE_PROFILE['use_json_mode']}")
    print(f"{'─'*50}")

    result = evaluate_params(model_id, api_base, BASELINE_PROFILE, TUNING_CASES)
    print(f"  Score: {result['score']:.1%} ({result['correct']}/{result['total']})")
    print(f"  Avg latency: {result['avg_latency_s']:.2f}s")

    return {
        "profile": BASELINE_PROFILE.copy(),
        "result": result,
    }


def run_optuna_tuning(
    model_key: str,
    model_id: str,
    api_base: str | None,
    n_trials: int = 100,
    timeout: int | None = None,
    patience: int = 20,
    target_score: float = 1.0,
) -> dict:
    """Run Optuna tuning with early stopping.

    Early stopping gates (OR condition):
    1. Plateau: best score unchanged for `patience` consecutive trials
    2. Target: best score >= `target_score`
    """
    print(f"\n{'─'*50}")
    print(f"  OPTUNA TUNING: {model_key} (max {n_trials} trials)")
    print(f"  Early stopping: patience={patience}, target={target_score:.0%}")
    print(f"{'─'*50}")

    all_profiles = []
    best_score = -1.0
    best_trial = 0

    def objective(trial: optuna.Trial) -> float:
        nonlocal best_score, best_trial
        params = {
            "temperature": trial.suggest_float("temperature", 0.0, 0.7, step=0.05),
            "max_tokens": trial.suggest_categorical("max_tokens", [2048, 4096, 8192]),
            "top_p": trial.suggest_float("top_p", 0.7, 1.0, step=0.05),
            "use_json_mode": trial.suggest_categorical("use_json_mode", [True, False]),
            "use_system_msg": trial.suggest_categorical("use_system_msg", [True, False]),
        }

        result = evaluate_params(model_id, api_base, params, TUNING_CASES)

        profile = {
            "trial": trial.number,
            "params": params,
            "score": result["score"],
            "correct": result["correct"],
            "total": result["total"],
            "avg_latency_s": result["avg_latency_s"],
        }
        all_profiles.append(profile)

        # Track best
        if result["score"] > best_score:
            best_score = result["score"]
            best_trial = trial.number
            marker = " ★ NEW BEST"
        else:
            marker = ""

        print(f"    Trial {trial.number:2d}: {result['score']:.0%} "
              f"(temp={params['temperature']:.2f}, top_p={params['top_p']:.2f}, "
              f"json={params['use_json_mode']}, sys={params['use_system_msg']}){marker}")

        return result["score"]

    # Early stopping callback
    def early_stopping_callback(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        # Gate 1: Target score reached
        if trial.value is not None and trial.value >= target_score:
            print(f"\n  ✅ Target score {target_score:.0%} reached at trial {trial.number}. Stopping.")
            study.stop()
            return

        # Gate 2: Plateau — no improvement for `patience` trials
        trials_since_improvement = trial.number - best_trial
        if trials_since_improvement >= patience:
            print(f"\n  ⏹ Plateau: no improvement for {patience} trials "
                  f"(best={best_score:.0%} at trial {best_trial}). Stopping.")
            study.stop()
            return

    study = optuna.create_study(direction="maximize", study_name=model_key,
                                 sampler=optuna.samplers.TPESampler(seed=42))

    # Enqueue baseline as first trial
    study.enqueue_trial({
        "temperature": BASELINE_PROFILE["temperature"],
        "max_tokens": BASELINE_PROFILE["max_tokens"],
        "top_p": BASELINE_PROFILE["top_p"],
        "use_json_mode": BASELINE_PROFILE["use_json_mode"],
        "use_system_msg": BASELINE_PROFILE["use_system_msg"],
    })

    study.optimize(objective, n_trials=n_trials, timeout=timeout,
                   callbacks=[early_stopping_callback])

    best = study.best_params
    best_score = study.best_value

    print(f"\n  Best: {best_score:.1%} — {best}")
    print(f"  Completed: {len(study.trials)}/{n_trials} trials")

    return {
        "best_params": best,
        "best_score": best_score,
        "profiles": all_profiles,
        "n_trials": len(study.trials),
        "early_stopped": len(study.trials) < n_trials,
        "patience": patience,
        "target_score": target_score,
    }

def run_validation(
    model_id: str,
    api_base: str | None,
    params: dict,
    label: str = "tuned",
) -> dict:
    """Validate parameters on tuning cases (3 runs for variance)."""
    print(f"\n  Validating '{label}' (3 runs)...")

    scores = []
    for i in range(3):
        result = evaluate_params(model_id, api_base, params, TUNING_CASES)
        scores.append(result["score"])
        print(f"    Run {i+1}: {result['score']:.1%}")

    import statistics
    mean = statistics.mean(scores)
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0

    print(f"  Validation: {mean:.1%} ± {stdev:.1%}")

    return {
        "mean_score": round(mean, 4),
        "stdev": round(stdev, 4),
        "runs": [round(s, 4) for s in scores],
    }


def tune_model(
    model_key: str,
    n_trials: int = 100,
    timeout: int | None = None,
    patience: int = 20,
    target_score: float = 1.0,
    baseline_only: bool = False,
) -> dict:
    """Full tuning pipeline for one model."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from eval_all import MODELS

    if model_key not in MODELS:
        print(f"Unknown model: {model_key}")
        return {}

    cfg = MODELS[model_key]
    model_id = cfg["model"]
    api_base = cfg.get("api_base")

    print(f"\n{'='*60}")
    print(f"  MODEL: {model_key}")
    print(f"  ID:    {model_id}")
    print(f"  API:   {api_base or 'OpenRouter'}")
    print(f"{'='*60}")

    # Step 1: Baseline
    baseline = run_baseline(model_key, model_id, api_base)

    if baseline_only:
        return {
            "model_key": model_key,
            "model_id": model_id,
            "baseline": baseline,
            "tuning": None,
            "validation": None,
        }

    # Step 2: Optuna tuning
    tuning = run_optuna_tuning(model_key, model_id, api_base,
                               n_trials=n_trials, timeout=timeout,
                               patience=patience, target_score=target_score)

    # Step 3: Validate best params
    best_params = tuning["best_params"]
    validation = run_validation(model_id, api_base, best_params, label="best")

    # Step 4: Validate baseline for comparison
    baseline_validation = run_validation(model_id, api_base, BASELINE_PROFILE, label="baseline")

    # Compile result
    result = {
        "model_key": model_key,
        "model_id": model_id,
        "tuning": {
            "n_trials": tuning["n_trials"],
            "best_params": tuning["best_params"],
            "best_score": tuning["best_score"],
            "all_profiles": tuning["profiles"],
            "early_stopped": tuning.get("early_stopped", False),
            "patience": tuning.get("patience", 20),
            "target_score": tuning.get("target_score", 1.0),
        },
        "best": {
            "params": tuning["best_params"],
            "validation": validation,
        },
        "improvement": {
            "baseline_score": baseline_validation["mean_score"],
            "tuned_score": validation["mean_score"],
            "delta": round(validation["mean_score"] - baseline_validation["mean_score"], 4),
        },
    }

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = RESULTS_DIR / f"{model_key.replace('/', '_')}_tuning.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved: {output_file}")

    # Print summary
    imp = result["improvement"]
    print(f"\n  {'─'*40}")
    print(f"  SUMMARY: {model_key}")
    print(f"    Baseline: {imp['baseline_score']:.1%}")
    print(f"    Tuned:    {imp['tuned_score']:.1%}")
    print(f"    Delta:    {imp['delta']:+.1%}")
    print(f"    Best params: {json.dumps(tuning['best_params'])}")
    print(f"  {'─'*40}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Optuna parameter tuning with profile saving")
    parser.add_argument("--model", type=str, help="Model key to tune")
    parser.add_argument("--all", action="store_true", help="Tune all models")
    parser.add_argument("--trials", type=int, default=100, help="Max Optuna trials per model (default: 100)")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout per model (seconds)")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience (default: 20)")
    parser.add_argument("--target-score", type=float, default=1.0, help="Target score for early stopping (default: 1.0)")
    parser.add_argument("--baseline-only", action="store_true", help="Only run baseline, skip tuning")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from eval_all import MODELS

    if args.all:
        models = list(MODELS.keys())
    elif args.model:
        models = [args.model]
    else:
        parser.error("Specify --model or --all")

    all_results = []
    for model_key in models:
        result = tune_model(
            model_key,
            n_trials=args.trials,
            timeout=args.timeout,
            patience=args.patience,
            target_score=args.target_score,
            baseline_only=args.baseline_only,
        )
        if result:
            all_results.append(result)

    # Final summary
    if all_results:
        print(f"\n{'='*70}")
        print(f"  FINAL SUMMARY — {len(all_results)} models")
        print(f"{'='*70}")
        print(f"  {'Model':<35} {'Baseline':>10} {'Tuned':>10} {'Delta':>10}")
        print(f"  {'─'*65}")
        for r in all_results:
            key = r["model_key"]
            bl = r.get("improvement", {}).get("baseline_score", r.get("baseline", {}).get("score", 0))
            tn = r.get("improvement", {}).get("tuned_score", bl)
            delta = r.get("improvement", {}).get("delta", 0)
            print(f"  {key:<35} {bl:>9.1%} {tn:>9.1%} {delta:>+9.1%}")


if __name__ == "__main__":
    main()
