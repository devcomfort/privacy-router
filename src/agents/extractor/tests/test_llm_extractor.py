from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agents.extractor.llm import LLMExtractor, LLMRecord

TEXT = "문의: synthetic@example.invalid"
SPAN = "synthetic@example.invalid"
LOCAL_BASE = "http://127.0.0.1:8000/v1"
REMOTE_BASE = "https://api.example.invalid/v1"


def llm_output(*_: Any, **__: Any) -> dict[str, object]:
    return {
        "records": [
            {
                "tag": "EMAIL",
                "kind": "structural",
                "span": SPAN,
                "offsets": [4, 29],
                "confidentiality": {"value": "private", "reason": "개인 연락처 정보"},
                "confidence": 0.97,
                "necessity": {"value": "required", "reason": "응답에 실제 주소가 필요함"},
            }
        ]
    }


def test_llm_extractor_normalizes_structured_output_and_records_provenance():
    extractor = LLMExtractor(
        model="local/gemma",
        api_base=LOCAL_BASE,
        call_structured=llm_output,
    )

    result = extractor.extract(TEXT)

    assert result.status == "complete"
    assert result.entities[0].tag == "EMAIL"
    assert result.entities[0].offsets == (4, 29)
    assert result.entities[0].confidentiality.value == "private"
    assert result.entities[0].necessity.value == "required"
    assert result.entities[0].run_id == result.detector_runs[0].run_id
    assert result.detector_runs[0].detector_type == "llm"
    assert result.detector_runs[0].external_opt_in is False


def test_llm_extractor_rejects_external_raw_input_without_opt_in():
    def should_not_call(*_: Any, **__: Any) -> None:
        raise AssertionError("external backend must be rejected before invocation")

    result = LLMExtractor(
        model="openai/gpt-4o-mini",
        api_base=REMOTE_BASE,
        call_structured=should_not_call,
    ).extract("synthetic@example.invalid")

    assert result.status == "failed"
    assert result.entities == []
    assert result.detector_runs[0].external_opt_in is False
    assert result.detector_runs[0].status == "failed"


def test_llm_extractor_allows_external_raw_input_only_with_request_opt_in():
    result = LLMExtractor(
        model="openai/gpt-4o-mini",
        api_base=REMOTE_BASE,
        call_structured=llm_output,
    ).extract(TEXT, allow_external=True)

    assert result.status == "complete"
    assert result.detector_runs[0].external_opt_in is True


def test_external_opt_in_does_not_persist_between_requests():
    calls: list[int] = []

    def record_call(*_: Any, **__: Any) -> dict[str, object]:
        calls.append(1)
        return llm_output()

    extractor = LLMExtractor(
        model="openai/gpt-4o-mini",
        api_base=REMOTE_BASE,
        call_structured=record_call,
    )

    allowed = extractor.extract(TEXT, allow_external=True)
    denied = extractor.extract(TEXT)

    assert allowed.status == "complete"
    assert denied.status == "failed"
    assert denied.detector_runs[0].external_opt_in is False
    assert calls == [1]


def test_llm_extractor_records_backend_failure():
    def fail(*_: Any, **__: Any) -> None:
        raise RuntimeError("backend unavailable")

    result = LLMExtractor(
        model="local/gemma",
        api_base=LOCAL_BASE,
        call_structured=fail,
    ).extract(TEXT)

    assert result.status == "failed"
    assert result.detector_runs[0].status == "failed"
    assert result.detector_runs[0].error_code == "EXTRACTOR_BACKEND_ERROR"


def test_llm_extractor_preserves_public_required_information():
    def public_output(*_: Any, **__: Any) -> dict[str, object]:
        return {
            "records": [
                {
                    "tag": "EMAIL",
                    "kind": "structural",
                    "span": SPAN,
                    "confidentiality": {"value": "public", "reason": "Published support destination."},
                    "necessity": {"value": "required", "reason": "User requests sending to this destination."},
                }
            ],
        }

    result = LLMExtractor(
        model="local/gemma",
        api_base=LOCAL_BASE,
        call_structured=public_output,
    ).extract(TEXT)

    assert result.status == "complete"
    [entity] = result.entities
    assert entity.confidentiality.value == "public"
    assert entity.necessity.value == "required"
    assert entity.offsets == (4, 29)


@pytest.mark.parametrize("field", ["confidentiality", "necessity"])
def test_llm_response_model_requires_reasons_for_unassessed_items(field):
    record = {
        "tag": "EMAIL",
        "kind": "structural",
        "span": SPAN,
        "confidentiality": {"value": None, "reason": "Insufficient context."},
        "necessity": {"value": None, "reason": "No task."},
    }
    record[field].pop("reason")

    with pytest.raises(ValidationError, match="reason"):
        LLMRecord.model_validate(record)


def test_missing_native_model_records_is_a_failed_analysis():
    extractor = LLMExtractor(model="local/gemma", api_base=LOCAL_BASE, call_structured=lambda *args, **kwargs: {})
    result = extractor.extract(TEXT)
    assert result.status == "failed"
