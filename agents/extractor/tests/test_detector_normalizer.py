from __future__ import annotations

from uuid import uuid4

import pytest

from agents.extractor.normalizer import EntityNormalizer, SpanReconciliationError
from agents.extractor.parser import ParsedEntity
from agents.extractor.schemas import LLMDetectorRun, Requiredness

TEXT = "send synthetic@example.invalid then synthetic@example.invalid"
SPAN = "synthetic@example.invalid"


def make_run() -> LLMDetectorRun:
    return LLMDetectorRun(
        run_id=uuid4(),
        detector_type="llm",
        detector_id="privacy-router-llm-extractor-v1-0-0",
        status="complete",
        external_opt_in=False,
        adapter_version="privacy-router-llm-adapter-v1-0-0",
        model_id="local/gemma",
    )


def candidate(span: str = SPAN, offsets: tuple[int, int] | None = None) -> ParsedEntity:
    return ParsedEntity(
        tag="EMAIL",
        kind="structural",
        native_label="EMAIL_ADDRESS",
        span=span,
        offsets=offsets,
        reason=None,
        confidence=0.9,
        detection_method="regex",
        native_metadata={},
        is_required=Requiredness(value=None, reason="not assessed"),
    )


def test_repeated_values_receive_distinct_offsets_and_uids():
    result = EntityNormalizer().normalize(TEXT, [candidate(), candidate()], make_run())

    assert [entity.offsets for entity in result.entities] == [(5, 30), (36, 61)]
    assert len({entity.uid for entity in result.entities}) == 2
    assert [entity.span for entity in result.entities] == [SPAN, SPAN]


def test_invalid_model_offset_is_reconciled_to_matching_occurrence():
    result = EntityNormalizer().normalize(
        "x secret y secret",
        [candidate("secret", offsets=(0, 1)), candidate("secret")],
        make_run(),
    )

    assert [entity.offsets for entity in result.entities] == [(2, 8), (11, 17)]


def test_span_not_found_raises_reconciliation_error():
    with pytest.raises(SpanReconciliationError):
        EntityNormalizer().normalize("abc", [candidate("wrong")], make_run())


def test_result_entities_reference_their_detector_run():
    result = EntityNormalizer().normalize(TEXT, [candidate()], make_run())

    assert result.entities[0].run_id == result.detector_runs[0].run_id
