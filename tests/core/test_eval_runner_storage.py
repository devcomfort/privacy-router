"""Regression tests for primary evaluator artifact storage boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_eval_runner(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_runner_writes_raw_artifacts_outside_public_docs() -> None:
    module = _load_eval_runner(ROOT / "scripts" / "eval_runner.py", "eval_runner_under_test")
    assert module.RESULTS_DIR == ROOT / "var" / "evaluations" / "runner"
    assert ROOT / "docs" not in module.RESULTS_DIR.parents


def test_legacy_eval_runner_writes_raw_artifacts_outside_public_docs() -> None:
    module = _load_eval_runner(
        ROOT / "eval" / "scripts" / "eval_runner.py",
        "legacy_eval_runner_under_test",
    )

    assert module.RESULTS_DIR == ROOT / "var" / "evaluations" / "legacy-runner"
    assert ROOT / "docs" not in module.RESULTS_DIR.parents
