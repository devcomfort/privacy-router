#!/usr/bin/env python3
"""
Ablation Study: Fixed Categories vs Socratic Category Derivation

Compares two prompt approaches:
- Prompt A (Fixed): 11 predefined categories
- Prompt B (Socratic): AI derives category names dynamically

For each model:
1. Baseline measurement (default parameters)
2. Parameter tuning (Optuna)
3. Compare results
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

from scripts.eval_all import CASES, MODELS, aggregate_model, run_single  # noqa: E402
from scripts.tune_params import BASELINE_PROFILE, run_optuna_tuning  # noqa: E402

# Configuration
PROMPTS = {
    "fixed": {
        "name": "Fixed Categories (11 categories)",
        "path": str(ROOT / "agents" / "extractor" / "extract.fixed.prompt"),
        "description": "Predefined 11 categories, no Socratic reasoning",
    },
    "socratic": {
        "name": "Socratic Category Derivation",
        "path": str(ROOT / "agents" / "extractor" / "extract.prompt"),
        "description": "AI derives category names via Socratic questions",
    },
}

MODELS_TO_TEST = [
    "ministral-3b-2512",
    "granite-4.1-8b",
    "qwen3.5-9b",
    "deepseek-v4-flash",
    "gemma-4-26b-a4b-it",
    "gemini-3.1-flash-lite",
    "exaone-4.5-33b-openrouter",
]

ABLATION_DIR = ROOT / "docs" / "developments" / "results" / "ablation_study"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def run_baseline_for_prompt(model_key: str, prompt_key: str, n_trials: int = 3) -> dict:
    """Run baseline measurement with default parameters for a specific prompt."""
    print(f"\n{'=' * 60}")
    print(f"BASELINE: {model_key} + {prompt_key} ({n_trials} trials)")
    print(f"{'=' * 60}")

    prompt_path = PROMPTS[prompt_key]["path"]

    # Temporarily override prompt path in extract.prompt
    original_prompt = (ROOT / "agents" / "extractor" / "extract.prompt").read_text()
    new_prompt = Path(prompt_path).read_text()

    # Write the prompt we want to test
    (ROOT / "agents" / "extractor" / "extract.prompt").write_text(new_prompt)

    try:
        # Run evaluation for each case
        case_results = []
        for case in CASES:
            for trial in range(1, n_trials + 1):
                result = run_single(model_key, case, trial)
                case_results.append(result)

        # Aggregate results
        agg = aggregate_model(model_key, n_trials)

        return {
            "model": model_key,
            "prompt": prompt_key,
            "type": "baseline",
            "params": BASELINE_PROFILE,
            "n_trials": n_trials,
            "aggregated": agg,
            "case_results": case_results,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        # Restore original prompt
        (ROOT / "agents" / "extractor" / "extract.prompt").write_text(original_prompt)


def run_tuning_for_prompt(model_key: str, prompt_key: str, n_trials: int = 50) -> dict:
    """Run parameter tuning with Optuna for a specific prompt."""
    print(f"\n{'=' * 60}")
    print(f"TUNING: {model_key} + {prompt_key} ({n_trials} trials)")
    print(f"{'=' * 60}")

    model_info = MODELS[model_key]
    prompt_path = PROMPTS[prompt_key]["path"]

    # Temporarily override prompt path
    original_prompt = (ROOT / "agents" / "extractor" / "extract.prompt").read_text()
    new_prompt = Path(prompt_path).read_text()
    (ROOT / "agents" / "extractor" / "extract.prompt").write_text(new_prompt)

    try:
        # Run Optuna tuning
        tuning_result = run_optuna_tuning(
            model_key=f"{model_key}_{prompt_key}",
            model_id=model_info["id"],
            api_base=model_info.get("api_base"),
            n_trials=n_trials,
            timeout=3600,
            patience=20,
            target_score=1.0,
        )

        return {
            "model": model_key,
            "prompt": prompt_key,
            "type": "tuning",
            "tuning": tuning_result,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        # Restore original prompt
        (ROOT / "agents" / "extractor" / "extract.prompt").write_text(original_prompt)


def run_ablation_study(n_trials: int = 50, n_baseline_trials: int = 3):
    """Run complete ablation study."""
    ensure_dir(ABLATION_DIR)

    all_results = []
    summary = {
        "study": "ablation_fixed_vs_socratic",
        "prompts": {k: v["name"] for k, v in PROMPTS.items()},
        "models": MODELS_TO_TEST,
        "n_trials": n_trials,
        "n_baseline_trials": n_baseline_trials,
        "start_time": datetime.now().isoformat(),
        "results": [],
    }

    for model_key in MODELS_TO_TEST:
        for prompt_key in PROMPTS:
            # Run baseline
            baseline = run_baseline_for_prompt(model_key, prompt_key, n_baseline_trials)
            all_results.append(baseline)

            # Save baseline immediately
            baseline_path = ABLATION_DIR / f"{model_key}_{prompt_key}_baseline.json"
            with open(baseline_path, "w") as f:
                json.dump(baseline, f, indent=2, ensure_ascii=False)
            print(f"Saved: {baseline_path}")

            # Run tuning
            tuning = run_tuning_for_prompt(model_key, prompt_key, n_trials)
            all_results.append(tuning)

            # Save tuning immediately
            tuning_path = ABLATION_DIR / f"{model_key}_{prompt_key}_tuning.json"
            with open(tuning_path, "w") as f:
                json.dump(tuning, f, indent=2, ensure_ascii=False)
            print(f"Saved: {tuning_path}")

    # Save summary
    summary["end_time"] = datetime.now().isoformat()
    summary["results"] = all_results

    summary_path = ABLATION_DIR / "ablation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nSaved summary: {summary_path}")

    return summary


def generate_report(summary: dict) -> dict:
    """Generate comparison report."""
    report = {
        "title": "Ablation Study: Fixed Categories vs Socratic Derivation",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "models": {},
        "overall_comparison": {},
    }

    for model_key in MODELS_TO_TEST:
        model_results = {}

        for prompt_key in PROMPTS:
            # Find baseline and tuning results
            baseline = None
            tuning = None

            for r in summary["results"]:
                if r["model"] == model_key and r["prompt"] == prompt_key:
                    if r["type"] == "baseline":
                        baseline = r
                    elif r["type"] == "tuning":
                        tuning = r

            if baseline and tuning:
                baseline_score = baseline["aggregated"]["accuracy_pct"] / 100.0
                tuned_score = tuning["tuning"]["best_score"]

                model_results[prompt_key] = {
                    "baseline_score": baseline_score,
                    "tuned_score": tuned_score,
                    "improvement": tuned_score - baseline_score,
                    "n_trials": tuning["tuning"]["n_trials"],
                    "best_params": tuning["tuning"]["best_params"],
                }

        if len(model_results) == 2:
            fixed = model_results["fixed"]
            socratic = model_results["socratic"]

            report["models"][model_key] = {
                "fixed": fixed,
                "socratic": socratic,
                "winner": "socratic" if socratic["tuned_score"] > fixed["tuned_score"] else "fixed",
                "score_diff": socratic["tuned_score"] - fixed["tuned_score"],
            }

    # Overall comparison
    if report["models"]:
        fixed_scores = [report["models"][m]["fixed"]["tuned_score"] for m in report["models"]]
        socratic_scores = [report["models"][m]["socratic"]["tuned_score"] for m in report["models"]]

        report["overall_comparison"] = {
            "fixed_mean": sum(fixed_scores) / len(fixed_scores),
            "socratic_mean": sum(socratic_scores) / len(socratic_scores),
            "socratic_wins": sum(1 for m in report["models"] if report["models"][m]["winner"] == "socratic"),
            "fixed_wins": sum(1 for m in report["models"] if report["models"][m]["winner"] == "fixed"),
        }

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ablation Study: Fixed vs Socratic Categories")
    parser.add_argument("--trials", type=int, default=50, help="Number of Optuna trials per model")
    parser.add_argument("--baseline-trials", type=int, default=3, help="Number of baseline trials per case")
    parser.add_argument("--models", nargs="*", default=None, help="Models to test (default: all)")
    parser.add_argument("--skip-tuning", action="store_true", help="Skip tuning, only run baselines")

    args = parser.parse_args()

    if args.models:
        MODELS_TO_TEST[:] = args.models

    print("Starting ablation study")
    print(f"Models: {MODELS_TO_TEST}")
    print("=" * 60)
    print(f"Baseline trials: {args.baseline_trials}")
    print(f"Skip tuning: {args.skip_tuning}")

    summary = run_ablation_study(n_trials=args.trials, n_baseline_trials=args.baseline_trials)
    report = generate_report(summary)

    # Save report
    report_path = ABLATION_DIR / "ablation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nSaved report: {report_path}")

    # Print summary
    print(f"\n{'=' * 60}")
    print("ABLATION STUDY RESULTS")
    print(f"{'=' * 60}")
    if report["overall_comparison"]:
        print(f"Fixed categories mean: {report['overall_comparison']['fixed_mean']:.1%}")
        print(f"Socratic mean: {report['overall_comparison']['socratic_mean']:.1%}")
        print(f"Socratic wins: {report['overall_comparison']['socratic_wins']}/{len(report['models'])}")
        print(f"Fixed wins: {report['overall_comparison']['fixed_wins']}/{len(report['models'])}")
    else:
        print("No results to display")
