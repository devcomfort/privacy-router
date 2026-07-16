#!/usr/bin/env python3
"""Optuna parameter tuning for local_benchmark with benchmark_v2 dataset."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["HF_HUB_OFFLINE"] = "1"

import instructor
import optuna
from instructor.core.hooks import Hooks
from litellm import completion
from pydantic import BaseModel, Field

from agents.judge import Judge

optuna.logging.set_verbosity(optuna.logging.WARNING)

PORT = 8000
API_BASE = f"http://localhost:{PORT}/v1"
PROMPT_FILE = Path(__file__).resolve().parent / "prompt_variants" / "extract.fewshot_v3.prompt"
DATA_FILE = Path(__file__).resolve().parent / "datasets" / "benchmark_v2.json"


class ExtractionSensitivity(BaseModel):
    is_sensitive: bool = Field(description="Whether sensitive information was detected")
    rationale: str = Field(default="", description="Explanation")


class ExtractionRecord(BaseModel):
    category: str = Field(description="SCREAMING_SNAKE_CASE tag")
    span: str = Field(description="Exact substring detected")
    is_essential: bool = Field(default=False, description="True if essential")


class ExtractionResult(BaseModel):
    sensitivity: ExtractionSensitivity
    records: list[ExtractionRecord] = Field(default_factory=list)


def objective(trial):
    temp = trial.suggest_float("temperature", 0.0, 1.0, step=0.1)
    top_p = trial.suggest_float("top_p", 0.7, 1.0, step=0.05)
    max_tokens = trial.suggest_categorical("max_tokens", [512, 768, 1024])

    client = instructor.from_litellm(completion, mode=instructor.Mode.JSON)
    judge = Judge()
    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")

    with open(DATA_FILE) as f:
        bench = json.load(f)
    cases = bench["cases"][:30]

    correct = 0
    total = 0
    for c in cases:
        rendered = prompt_template.replace("{{text}}", c["text"])
        try:
            hooks = Hooks()
            resp = client.chat.completions.create(
                model="openai/google/gemma-4-E4B-it",
                messages=[{"role": "user", "content": rendered}],
                response_model=ExtractionResult,
                max_retries=1,
                temperature=temp,
                top_p=top_p,
                max_tokens=max_tokens,
                api_base=API_BASE,
                hooks=hooks,
            )
            sens = resp.sensitivity.model_dump()
            recs = [r.model_dump() for r in resp.records]
            judgment = judge.classify(sensitivity=sens, records=recs, text=c["text"])
            action_map = {
                "allow": "allow",
                "block": "block",
                "selective_mask": "selective_mask",
            }
            predicted = action_map.get(judgment.policy_action, judgment.policy_action)
            if predicted == c["expected_action"]:
                correct += 1
        except Exception:
            pass
        total += 1

    return correct / total if total > 0 else 0


def main():
    model_tag = sys.argv[1] if len(sys.argv) > 1 else "Gemma4-E4B"
    n_trials = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    print(f"Optuna tuning: {model_tag}, {n_trials} trials, 30-case subset")

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    print(f"\nBest: {study.best_trial.value:.1%}")
    print(f"Params: {study.best_trial.params}")

    results = {
        "model": model_tag,
        "n_trials": n_trials,
        "subset_size": 30,
        "best_accuracy": study.best_trial.value,
        "best_params": study.best_trial.params,
        "all_trials": [{"trial": t.number, "value": t.value, "params": t.params} for t in study.trials],
    }
    out = Path(__file__).resolve().parent / "results" / f"optuna_{model_tag}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
