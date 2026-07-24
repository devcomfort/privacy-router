"""Regression tests for primary evaluator artifact storage boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_eval_runner():
    spec = importlib.util.spec_from_file_location("eval_runner_under_test", ROOT / "scripts" / "eval_runner.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_runner_writes_raw_artifacts_outside_public_docs() -> None:
    module = _load_eval_runner()

    assert module.RESULTS_DIR == ROOT / "var" / "evaluations" / "runner"
    assert ROOT / "docs" not in module.RESULTS_DIR.parents
