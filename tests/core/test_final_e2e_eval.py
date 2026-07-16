"""Contract tests for the final end-to-end evaluation harness."""

from __future__ import annotations

from eval.final_e2e import (
    AcceptanceThresholds,
    aggregate_checks,
    cumulative_expectations,
    evaluate_response,
    normalize_action,
)


def _selective_mask_response(*, content: str = "작성했습니다.") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "privacy_router": {
            "is_sensitive": True,
            "policy_action": "selective_mask",
            "route": "external_api",
            "model_used": "openrouter/google/gemma-4-26b-it",
            "extraction_records": [
                {
                    "category": "PERSONAL_IDENTIFIER_NUMBER",
                    "span": "901212-1234567",
                    "confidence": 0.99,
                    "is_essential": False,
                    "reasoning": "Background data can be masked.",
                }
            ],
        },
    }


def test_normalize_action_maps_legacy_dataset_labels() -> None:
    assert normalize_action("mask_and_send") == "selective_mask"
    assert normalize_action("prompt_user") == "block"
    assert normalize_action("route_to_local") == "block"
    assert normalize_action("allow") == "allow"


def test_cumulative_expectations_keep_prior_sensitive_context_protected() -> None:
    conversation = {
        "turns": [
            {"role": "user", "content": "safe"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "maskable secret"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "essential secret"},
        ],
        "expected_sensitive_turns": [2, 4],
        "expected_actions": ["allow", "allow", "mask_and_send", "allow", "route_to_local"],
    }

    expectations = cumulative_expectations(conversation)

    assert [(item.turn_index, item.is_sensitive, item.action) for item in expectations] == [
        (0, False, "allow"),
        (2, True, "selective_mask"),
        (4, True, "block"),
    ]


def test_selective_mask_response_passes_privacy_and_boundary_contracts() -> None:
    check = evaluate_response(
        case_id="pii_rrn_mask",
        expected_sensitive=True,
        expected_action="selective_mask",
        expected_records=[{"span": "901212-1234567"}],
        messages=[
            {
                "role": "user",
                "content": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
            }
        ],
        status_code=200,
        response=_selective_mask_response(),
        latency_s=0.25,
        local_model="openai/google/gemma-4-26b-local",
        external_model="openrouter/google/gemma-4-26b-it",
        scope="single_turn",
    )

    assert check.request_success
    assert check.sensitivity_correct
    assert check.action_correct
    assert check.route_boundary_correct
    assert check.masking_safe
    assert check.no_placeholder_leak
    assert check.utility_success
    assert check.passed


def test_placeholder_leak_and_wrong_model_fail_the_contract() -> None:
    response = _selective_mask_response(content="PERSONAL_IDENTIFIER_NUMBER#deadbeef")
    response["privacy_router"]["model_used"] = "openai/google/gemma-4-26b-local"

    check = evaluate_response(
        case_id="pii_rrn_mask",
        expected_sensitive=True,
        expected_action="selective_mask",
        expected_records=[{"span": "901212-1234567"}],
        messages=[{"role": "user", "content": "901212-1234567"}],
        status_code=200,
        response=response,
        latency_s=0.25,
        local_model="openai/google/gemma-4-26b-local",
        external_model="openrouter/google/gemma-4-26b-it",
        scope="single_turn",
    )

    assert not check.route_boundary_correct
    assert not check.no_placeholder_leak
    assert not check.passed


def test_hydrated_sensitive_text_is_allowed_in_the_client_response() -> None:
    response = _selective_mask_response(content="확인한 값은 901212-1234567입니다.")

    check = evaluate_response(
        case_id="pii_rrn_mask",
        expected_sensitive=True,
        expected_action="selective_mask",
        expected_records=[{"span": "901212-1234567"}],
        messages=[{"role": "user", "content": "901212-1234567"}],
        status_code=200,
        response=response,
        latency_s=0.25,
        local_model="openai/google/gemma-4-26b-local",
        external_model="openrouter/google/gemma-4-26b-it",
        scope="single_turn",
    )

    assert check.privacy_safe
    assert check.passed


def test_aggregate_checks_enforces_zero_leak_and_perfect_block_recall() -> None:
    passing = evaluate_response(
        case_id="pii_rrn_mask",
        expected_sensitive=True,
        expected_action="selective_mask",
        expected_records=[{"span": "901212-1234567"}],
        messages=[{"role": "user", "content": "901212-1234567"}],
        status_code=200,
        response=_selective_mask_response(),
        latency_s=0.25,
        local_model="openai/google/gemma-4-26b-local",
        external_model="openrouter/google/gemma-4-26b-it",
        scope="single_turn",
    )
    summary = aggregate_checks([passing], AcceptanceThresholds())

    assert summary["verdict"] == "PASS"
    assert summary["metrics"]["privacy_leak_rate"] == 0.0
    assert summary["gates"]["block_recall"]["passed"]


def test_each_scope_must_pass_instead_of_hiding_behind_overall_average() -> None:
    passing = evaluate_response(
        case_id="safe",
        expected_sensitive=False,
        expected_action="allow",
        expected_records=[],
        messages=[{"role": "user", "content": "안녕하세요"}],
        status_code=200,
        response={
            "choices": [{"message": {"role": "assistant", "content": "안녕하세요"}}],
            "privacy_router": {
                "is_sensitive": False,
                "policy_action": "allow",
                "route": "external_api",
                "model_used": "external",
            },
        },
        latency_s=0.1,
        local_model="local",
        external_model="external",
        scope="single_turn",
    )
    failing_scope = evaluate_response(
        case_id="multi-sensitive",
        expected_sensitive=True,
        expected_action="selective_mask",
        expected_records=[{"span": "secret"}],
        messages=[{"role": "user", "content": "secret"}],
        status_code=200,
        response={
            "choices": [{"message": {"role": "assistant", "content": "처리했습니다"}}],
            "privacy_router": {
                "is_sensitive": False,
                "policy_action": "selective_mask",
                "route": "external_api",
                "model_used": "external",
                "extraction_records": [
                    {
                        "category": "SECRET",
                        "span": "secret",
                        "confidence": 1.0,
                        "is_essential": False,
                    }
                ],
            },
        },
        latency_s=0.1,
        local_model="local",
        external_model="external",
        scope="multi_turn_cumulative",
    )

    summary = aggregate_checks(
        [passing] * 20 + [failing_scope],
        AcceptanceThresholds(),
    )

    assert summary["metrics"]["sensitivity_accuracy"] >= 0.95
    assert summary["scope_gates"]["multi_turn_cumulative"]["sensitivity_accuracy"]["passed"] is False
    assert summary["verdict"] == "FAIL"
