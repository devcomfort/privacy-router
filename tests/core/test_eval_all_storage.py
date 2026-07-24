"""Regression tests for evaluation artifact storage boundaries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_eval_all():
    spec = importlib.util.spec_from_file_location("eval_all_under_test", ROOT / "scripts" / "eval_all.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_all_writes_raw_artifacts_outside_public_docs() -> None:
    module = _load_eval_all()

    assert module.RESULTS_DIR == ROOT / "var" / "evaluations"
    assert ROOT / "docs" not in module.RESULTS_DIR.parents


def test_report_only_mode_creates_private_results_dir(tmp_path, monkeypatch) -> None:
    module = _load_eval_all()
    results_dir = tmp_path / "private-evaluations"
    module.RESULTS_DIR = results_dir
    monkeypatch.setattr(sys, "argv", ["eval_all.py", "--models", "unknown", "--report"])

    module.main()

    assert (results_dir / "eval_aggregated.json").is_file()
    assert (results_dir / "eval_report.html").is_file()
