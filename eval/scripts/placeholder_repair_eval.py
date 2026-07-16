#!/usr/bin/env python3
"""Evaluate malformed-placeholder repair with a real configured LLM.

The dataset contains masked placeholders only; original sensitive values are never
sent to the repair model or written to the result file.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents import PlaceholderRepairer  # noqa: E402

DEFAULT_CASES = ROOT / "eval" / "dataset" / "placeholder_repair_cases.json"
DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"
_REQUIRED_FIELDS = {
    "id",
    "observed",
    "allowed",
    "masked_messages",
    "masked_output",
    "expected",
}


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load and validate masked repair cases."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("case file must contain a non-empty JSON array")

    cases: list[dict[str, Any]] = []
    for index, case in enumerate(payload):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be a JSON object")
        missing = _REQUIRED_FIELDS - case.keys()
        if missing:
            fields = ", ".join(sorted(missing))
            raise ValueError(f"case {index} missing required fields: {fields}")
        if not isinstance(case["allowed"], list) or not all(isinstance(item, str) for item in case["allowed"]):
            raise ValueError(f"case {index} allowed must be a string array")
        if case["expected"] is not None and case["expected"] not in case["allowed"]:
            raise ValueError(f"case {index} expected must be registered or null")
        cases.append(case)
    return cases


def summarize(
    rows: list[dict[str, Any]],
    *,
    model: str,
    case_count: int,
    trials: int,
) -> dict[str, Any]:
    """Compute exact-match accuracy and latency statistics."""
    if not rows:
        raise ValueError("cannot summarize an empty evaluation")

    mapping_rows = [row for row in rows if row["expected"] is not None]
    ambiguous_rows = [row for row in rows if row["expected"] is None]
    latencies = sorted(float(row["latency_s"]) for row in rows)
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1)

    def accuracy(selected: list[dict[str, Any]]) -> float | None:
        if not selected:
            return None
        return sum(bool(row["passed"]) for row in selected) / len(selected)

    return {
        "model": model,
        "cases": case_count,
        "trials": trials,
        "samples": len(rows),
        "accuracy": accuracy(rows),
        "mapping_accuracy": accuracy(mapping_rows),
        "ambiguous_null_accuracy": accuracy(ambiguous_rows),
        "latency_mean_s": statistics.mean(latencies),
        "latency_median_s": statistics.median(latencies),
        "latency_p95_s": latencies[p95_index],
    }


def run_evaluation(
    *,
    model: str,
    cases: list[dict[str, Any]],
    trials: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Run every masked case repeatedly against the real repair model."""
    if trials < 1:
        raise ValueError("trials must be at least 1")

    repairer = PlaceholderRepairer(model, max_attempts=max_attempts)
    rows: list[dict[str, Any]] = []
    for trial in range(1, trials + 1):
        for case in cases:
            started = time.perf_counter()
            actual = repairer.repair_sync(
                observed=case["observed"],
                allowed=case["allowed"],
                masked_messages=case["masked_messages"],
                masked_output=case["masked_output"],
            )
            rows.append(
                {
                    "trial": trial,
                    "case_id": case["id"],
                    "expected": case["expected"],
                    "actual": actual,
                    "passed": actual == case["expected"],
                    "latency_s": time.perf_counter() - started,
                }
            )

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "summary": summarize(
            rows,
            model=model,
            case_count=len(cases),
            trials=trials,
        ),
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate beta placeholder repair with a real LLM")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_evaluation(
        model=args.model,
        cases=load_cases(args.cases),
        trials=args.trials,
        max_attempts=args.max_attempts,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
