"""Tests for the real-model placeholder repair evaluation harness."""

from __future__ import annotations

import json

import pytest

from eval.scripts.placeholder_repair_eval import load_cases, summarize


def test_summarize_reports_mapping_and_ambiguity_accuracy():
    rows = [
        {
            "expected": "PHONE#11111111",
            "actual": "PHONE#11111111",
            "passed": True,
            "latency_s": 0.5,
        },
        {
            "expected": None,
            "actual": None,
            "passed": True,
            "latency_s": 1.5,
        },
        {
            "expected": "EMAIL#22222222",
            "actual": None,
            "passed": False,
            "latency_s": 1.0,
        },
    ]

    result = summarize(rows, model="openrouter/test", case_count=3, trials=1)

    assert result["samples"] == 3
    assert result["accuracy"] == pytest.approx(2 / 3)
    assert result["mapping_accuracy"] == pytest.approx(1 / 2)
    assert result["ambiguous_null_accuracy"] == 1.0
    assert result["latency_mean_s"] == 1.0
    assert result["latency_median_s"] == 1.0
    assert result["latency_p95_s"] == 1.5


def test_load_cases_rejects_missing_required_field(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"id": "incomplete"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        load_cases(path)
