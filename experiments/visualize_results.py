#!/usr/bin/env python3
"""Visualize Optuna tuning results.

Usage:
    rye run python experiments/visualize_results.py --study-name <name>
    rye run python experiments/visualize_results.py --latest
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import optuna

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "experiments" / "optuna_results"
STORAGE = f"sqlite:///{RESULTS_DIR / 'optuna_studies.db'}"


def list_studies():
    """List all studies."""
    studies = optuna.study.get_all_study_names(storage=STORAGE)
    print(f"\nAvailable studies ({len(studies)}):")
    for name in studies:
        study = optuna.load_study(study_name=name, storage=STORAGE)
        best = study.best_trial
        print(f"  {name}")
        print(f"    Best score: {best.value:.3f}")
        print(f"    Best params: {best.params}")
        print(f"    Trials: {len(study.trials)}")


def show_study(study_name: str):
    """Show detailed study results."""
    study = optuna.load_study(study_name=study_name, storage=STORAGE)

    print(f"\n{'=' * 70}")
    print(f"Study: {study_name}")
    print(f"{'=' * 70}")
    print(f"Total trials: {len(study.trials)}")

    # Best trial
    best = study.best_trial
    print(f"\nBest Trial (#{best.number}):")
    print(f"  Score: {best.value:.3f}")
    print(f"  Params: {best.params}")
    print(f"  Overall Accuracy: {best.user_attrs.get('overall_accuracy', '-')}%")
    print(f"  Morphological: {best.user_attrs.get('morphological_accuracy', '-')}%")
    print(f"  Contextual: {best.user_attrs.get('contextual_accuracy', '-')}%")
    print(f"  Consistency: {best.user_attrs.get('consistency', '-')}%")
    print(f"  Avg Time: {best.user_attrs.get('avg_time', '-')}s")

    # Top 10 trials
    print("\nTop 10 Trials:")
    print(
        f"{'Trial':<6} {'Score':<8} {'Prompt':<12} {'Temp':<6} {'TopP':<6} {'Overall':<10} {'Morph':<10} {'Ctx':<10} {'Consist':<10}"
    )
    print("-" * 80)
    sorted_trials = sorted(study.trials, key=lambda t: t.value if t.value else 0, reverse=True)
    for t in sorted_trials[:10]:
        print(
            f"  #{t.number:<4} {t.value:.3f}    {t.params.get('prompt', '-'):<12} {t.params.get('temperature', '-'):<6} {t.params.get('top_p', '-'):<6} {t.user_attrs.get('overall_accuracy', '-')}%{'':>4} {t.user_attrs.get('morphological_accuracy', '-')}%{'':>4} {t.user_attrs.get('contextual_accuracy', '-')}%{'':>4} {t.user_attrs.get('consistency', '-')}%"
        )

    # Parameter importance
    print("\nParameter Importance:")
    try:
        importance = optuna.importance.get_param_importances(study)
        for param, imp in sorted(importance.items(), key=lambda x: x[1], reverse=True):
            bar = "#" * int(imp * 50)
            print(f"  {param:<20} {imp:.3f} {bar}")
    except Exception as e:
        print(f"  Could not calculate: {e}")

    # Prompt comparison
    print("\nPrompt Comparison:")
    prompt_results: dict[str, list[float]] = {}
    for t in study.trials:
        if t.value is not None:
            prompt = t.params.get("prompt", "unknown")
            prompt_results.setdefault(prompt, []).append(t.value)
    for prompt, scores in sorted(prompt_results.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
        avg = sum(scores) / len(scores)
        print(f"  {prompt:<12} avg={avg:.3f} n={len(scores)}")


def export_study(study_name: str):
    """Export study results to JSON."""
    study = optuna.load_study(study_name=study_name, storage=STORAGE)

    data = {
        "study_name": study_name,
        "best_trial": {
            "number": study.best_trial.number,
            "value": study.best_trial.value,
            "params": study.best_trial.params,
            "user_attrs": study.best_trial.user_attrs,
        },
        "trials": [],
    }

    for t in study.trials:
        data["trials"].append(
            {
                "number": t.number,
                "value": t.value,
                "params": t.params,
                "user_attrs": t.user_attrs,
                "state": str(t.state),
            }
        )

    out_path = RESULTS_DIR / f"{study_name}.json"
    with open(out_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Exported to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Visualize Optuna results")
    parser.add_argument("--study-name", help="Study name to visualize")
    parser.add_argument("--latest", action="store_true", help="Show latest study")
    parser.add_argument("--list", action="store_true", help="List all studies")
    parser.add_argument("--export", action="store_true", help="Export study to JSON")
    args = parser.parse_args()

    if args.list:
        list_studies()
        return

    if args.latest:
        studies = optuna.study.get_all_study_names(storage=STORAGE)
        if not studies:
            print("No studies found")
            return
        args.study_name = studies[-1]

    if not args.study_name:
        print("Please specify --study-name or --latest")
        return

    if args.export:
        export_study(args.study_name)
    else:
        show_study(args.study_name)


if __name__ == "__main__":
    main()
