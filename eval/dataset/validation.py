"""Mechanical validation for Privacy Router ground-truth datasets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from agents.extractor import normalize_category

_ACTIONS = ("allow", "selective_mask", "block")
_DIFFICULTIES = ("easy", "medium", "hard")


def derive_expected_action(records: list[dict[str, Any]]) -> str:
    """Derive the router action from extraction-record essentiality."""
    if not records:
        return "allow"
    if any(record.get("is_essential") is True for record in records):
        return "block"
    return "selective_mask"


def compute_ground_truth_statistics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute canonical corpus counts from cases instead of hand-maintained totals."""
    action_counts = Counter(case.get("gt", {}).get("expected_action") for case in cases)
    category_counts = Counter(case.get("category") for case in cases)
    difficulty_counts = Counter(case.get("difficulty") for case in cases)
    category_order = tuple(dict.fromkeys(case.get("category") for case in cases))

    return {
        "total_cases": len(cases),
        "by_action": {action: action_counts[action] for action in _ACTIONS if action_counts[action]},
        "by_category": {category: category_counts[category] for category in category_order if category},
        "by_difficulty": {
            difficulty: difficulty_counts[difficulty] for difficulty in _DIFFICULTIES if difficulty_counts[difficulty]
        },
    }


def validate_ground_truth(document: dict[str, Any]) -> list[str]:
    """Return every structural, policy, span, and statistics violation."""
    errors: list[str] = []
    annotation = document.get("annotation_status")
    if not isinstance(annotation, dict):
        errors.append("annotation_status must be an object")
    else:
        independent = annotation.get("independent_annotation")
        if not isinstance(independent, bool):
            errors.append("annotation_status.independent_annotation must be boolean")
        if independent is False and annotation.get("agreement_metric") is not None:
            errors.append("annotation_status.agreement_metric must be null without independent annotation")
        if not isinstance(annotation.get("review_method"), str) or not annotation["review_method"]:
            errors.append("annotation_status.review_method must be a non-empty string")

    cases = document.get("cases")
    if not isinstance(cases, list):
        return ["cases must be a list"]

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        case_id = case.get("id")
        label = case_id if isinstance(case_id, str) and case_id else f"cases[{index}]"
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{label}: id must be a non-empty string")
        elif case_id in seen_ids:
            errors.append(f"{label}: duplicate id")
        else:
            seen_ids.add(case_id)

        text = case.get("text")
        if not isinstance(text, str) or not text:
            errors.append(f"{label}: text must be a non-empty string")
            continue
        if case.get("difficulty") not in _DIFFICULTIES:
            errors.append(f"{label}: invalid difficulty {case.get('difficulty')!r}")

        gt = case.get("gt")
        if not isinstance(gt, dict):
            errors.append(f"{label}: gt must be an object")
            continue
        sensitive = gt.get("is_sensitive")
        if not isinstance(sensitive, bool):
            errors.append(f"{label}: is_sensitive must be boolean")
        action = gt.get("expected_action")
        if action not in _ACTIONS:
            errors.append(f"{label}: invalid expected_action {action!r}")
        records = gt.get("records")
        if not isinstance(records, list):
            errors.append(f"{label}: records must be a list")
            continue

        derived_action = derive_expected_action(records)
        if action != derived_action:
            errors.append(f"{label}: expected_action {action!r} must be {derived_action!r} from records")
        if sensitive is False and records:
            errors.append(f"{label}: non-sensitive case must not contain records")
        if sensitive is False and action != "allow":
            errors.append(f"{label}: non-sensitive case must allow")
        if sensitive is True and not records:
            errors.append(f"{label}: sensitive case must contain at least one record")

        occupied: list[tuple[int, int, int]] = []
        seen_records: set[tuple[str, str]] = set()
        for record_index, record in enumerate(records):
            record_label = f"{label}.records[{record_index}]"
            if not isinstance(record, dict):
                errors.append(f"{record_label}: record must be an object")
                continue
            category = record.get("category")
            span = record.get("span")
            if not isinstance(span, str) or not span:
                errors.append(f"{record_label}: span must be a non-empty string")
                continue
            if not isinstance(category, str):
                errors.append(f"{record_label}: category must be SCREAMING_SNAKE_CASE")
            else:
                canonical_category = normalize_category(category, span)
                if canonical_category is None:
                    errors.append(f"{record_label}: category must be SCREAMING_SNAKE_CASE")
                elif canonical_category != category:
                    errors.append(
                        f"{record_label}: category must be canonical and value-independent; use {canonical_category}"
                    )
            if not isinstance(record.get("is_essential"), bool):
                errors.append(f"{record_label}: is_essential must be boolean")
            identity = (str(category), span)
            if identity in seen_records:
                errors.append(f"{record_label}: duplicate category/span record")
            seen_records.add(identity)

            occurrences = text.count(span)
            if occurrences != 1:
                errors.append(f"{record_label}: span must occur exactly once in text; found {occurrences}")
                continue
            start = text.index(span)
            end = start + len(span)
            for other_start, other_end, other_index in occupied:
                if start < other_end and other_start < end:
                    errors.append(f"{record_label}: span overlaps records[{other_index}]")
            occupied.append((start, end, record_index))

    computed_statistics = compute_ground_truth_statistics(cases)
    if document.get("statistics") != computed_statistics:
        errors.append("statistics do not match cases")
    return errors


def main() -> int:
    """Validate one ground-truth JSON file from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    document = json.loads(args.path.read_text(encoding="utf-8"))
    errors = validate_ground_truth(document)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"valid: {args.path} ({len(document['cases'])} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
