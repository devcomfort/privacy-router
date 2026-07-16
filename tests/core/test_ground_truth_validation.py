"""Contract tests for the benchmark ground-truth artifacts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from eval.dataset import compute_ground_truth_statistics, validate_ground_truth

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "experiments" / "ground-truth.json"
RUNTIME_COPY = ROOT / "eval" / "dataset" / "ground_truth.json"
WEB_COPY = ROOT / "web" / "static" / "docs" / "ground_truth.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _label_signature(case: dict) -> tuple:
    gt = case["gt"]
    return (
        case["id"],
        gt["is_sensitive"],
        gt["expected_action"],
        tuple((record["category"], record["is_essential"]) for record in gt["records"]),
    )


def test_ground_truth_satisfies_policy_and_span_invariants() -> None:
    document = _load(SOURCE)

    assert validate_ground_truth(document) == []


def test_ground_truth_statistics_are_derived_from_cases() -> None:
    document = _load(SOURCE)

    assert document["statistics"] == compute_ground_truth_statistics(document["cases"])


def test_annotation_status_does_not_overclaim_unverified_agreement() -> None:
    annotation = _load(SOURCE)["annotation_status"]

    assert annotation["independent_annotation"] is False
    assert annotation["agreement_metric"] is None
    assert annotation["review_method"] == "single_policy_audit"
    assert annotation["review_actor"] == "coding_agent_policy_audit"


def test_validator_rejects_unverified_agreement_claim() -> None:
    document = deepcopy(_load(SOURCE))
    document["annotation_status"]["agreement_metric"] = {"cohens_kappa": 0.91}

    errors = validate_ground_truth(document)

    assert "annotation_status.agreement_metric must be null without independent annotation" in errors


def test_validator_rejects_value_bearing_category_names() -> None:
    document = deepcopy(_load(SOURCE))
    case = next(case for case in document["cases"] if case["id"] == "competitive_business_report")
    record = case["gt"]["records"][0]
    record["category"] = f"{record['category']}_TSMC"

    errors = validate_ground_truth(document)

    assert any(
        "category must be canonical and value-independent; use FABRICATION_PROCESS_DECISION" in error
        for error in errors
    )


def test_runtime_and_web_copies_match_source_labels() -> None:
    source = _load(SOURCE)
    runtime = _load(RUNTIME_COPY)
    web = _load(WEB_COPY)

    assert runtime["version"] == source["version"]
    assert runtime["cases"] == source["cases"]
    assert runtime["statistics"] == source["statistics"]
    assert runtime["annotation_status"] == source["annotation_status"]
    assert web["version"] == source["version"]
    assert [_label_signature(case) for case in web["cases"]] == [_label_signature(case) for case in source["cases"]]
    assert web["statistics"] == source["statistics"]
    assert web["annotation_status"] == source["annotation_status"]
