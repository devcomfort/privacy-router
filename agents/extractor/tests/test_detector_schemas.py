from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.extractor.schemas import DetectionResult, LLMDetectorRun, PrivacyEntity, Requiredness

RUN_ID = uuid4()


def make_run() -> LLMDetectorRun:
    return LLMDetectorRun(
        run_id=RUN_ID,
        detector_type="llm",
        detector_id="privacy-router-llm-extractor-v1-0-0",
        status="complete",
        external_opt_in=False,
        adapter_version="privacy-router-llm-adapter-v1-0-0",
        model_id="local/gemma",
    )


def make_entity(**overrides: object) -> PrivacyEntity:
    values: dict[str, object] = {
        "id": uuid4(),
        "kind": "structural",
        "tag": "EMAIL",
        "uid": "a" * 32,
        "span": "synthetic@example.invalid",
        "offsets": (0, 25),
        "reason": None,
        "confidence": 0.9,
        "native_label": None,
        "native_metadata": {},
        "detection_method": "regex",
        "run_id": RUN_ID,
        "is_required": Requiredness(value=None, reason="not assessed"),
    }
    values.update(overrides)
    return PrivacyEntity.model_validate(values)


def test_identifier_is_computed_from_tag_and_uid():
    entity = make_entity(uid="a" * 32)

    assert entity.identifier == "EMAIL#" + "a" * 32
    assert "identifier" not in entity.model_dump()


def test_requiredness_is_nested_and_confidence_is_nullable():
    entity = make_entity(confidence=None, is_required=Requiredness(value=None, reason="not assessed"))

    assert entity.is_required.value is None
    assert entity.confidence is None


def test_invalid_offsets_are_rejected():
    with pytest.raises(ValidationError):
        make_entity(offsets=(8, 2))


def test_token_map_is_derived_from_entities():
    first = make_entity(uid="a" * 32)
    second = make_entity(uid="b" * 32)
    result = DetectionResult(entities=[first, second], detector_runs=[make_run()])

    assert result.token_map() == {
        first.identifier: first.span,
        second.identifier: second.span,
    }


def test_duplicate_uid_is_rejected_by_result():
    with pytest.raises(ValidationError):
        DetectionResult(entities=[make_entity(), make_entity(id=uuid4())], detector_runs=[make_run()])


@pytest.mark.parametrize("value", [True, False, None])
def test_requiredness_requires_a_reason_for_every_state(value: bool | None):
    with pytest.raises(ValidationError, match="reason"):
        Requiredness(value=value)
