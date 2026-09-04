from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agents.extractor.schemas import (
    DetectionResult,
    LLMDetectorRun,
    PresidioDetectorRun,
    PrivacyEntity,
    Requiredness,
)


def make_llm_run(**overrides: object) -> LLMDetectorRun:
    values: dict[str, object] = {
        "run_id": uuid4(),
        "detector_type": "llm",
        "detector_id": "privacy-router-llm-extractor-v1-0-0",
        "status": "complete",
        "external_opt_in": False,
        "adapter_version": "privacy-router-llm-adapter-v1-0-0",
        "model_id": "local/gemma",
        "model_revision": "model-revision",
        "prompt_version": "extract-v1",
    }
    values.update(overrides)
    return LLMDetectorRun.model_validate(values)


def test_presidio_run_preserves_configured_recognizers():
    run = PresidioDetectorRun(
        run_id=uuid4(),
        detector_type="presidio",
        detector_id="microsoft-presidio-analyzer-v2-2-358",
        status="complete",
        external_opt_in=False,
        adapter_version="privacy-router-presidio-adapter-v1-0-0",
        configured_recognizers=[{"name": "EmailRecognizer", "identifier": "email_recognizer"}],
    )

    assert run.configured_recognizers[0].name == "EmailRecognizer"
    assert run.configured_recognizers[0].identifier == "email_recognizer"


def test_detector_id_requires_versioned_kebab_case():
    with pytest.raises(ValidationError):
        make_llm_run(detector_id="LLMExtractor")


def test_detection_result_parses_discriminated_run_union():
    run = make_llm_run()
    result = DetectionResult.model_validate({"detector_runs": [run.model_dump()]})

    assert isinstance(result.detector_runs[0], LLMDetectorRun)
    assert result.detector_runs[0].run_id == run.run_id


def test_failed_run_can_be_recorded_without_entities():
    run = make_llm_run(status="failed", error_code="EXTRACTOR_UNAVAILABLE")
    result = DetectionResult.model_validate({"status": "failed", "detector_runs": [run.model_dump()]})

    assert result.status == "failed"
    assert result.entities == []
    assert result.detector_runs[0].status == "failed"


def test_entity_run_id_must_reference_a_recorded_detector_run():
    run = make_llm_run()
    entity = PrivacyEntity(
        id=uuid4(),
        kind="structural",
        tag="EMAIL",
        uid="a" * 32,
        span="synthetic@example.invalid",
        offsets=(0, 25),
        detection_method="regex",
        run_id=uuid4(),
        is_required=Requiredness(value=None, reason="not assessed"),
    )

    with pytest.raises(ValidationError, match="run_id"):
        DetectionResult(entities=[entity], detector_runs=[run])


def test_entity_run_id_is_a_uuid_reference():
    run_id = uuid4()
    entity = PrivacyEntity(
        id=uuid4(),
        kind="structural",
        tag="EMAIL",
        uid="a" * 32,
        span="synthetic@example.invalid",
        offsets=(0, 25),
        detection_method="regex",
        run_id=run_id,
        is_required=Requiredness(value=None, reason="not assessed"),
    )

    assert isinstance(entity.run_id, UUID)
    assert entity.run_id == run_id
