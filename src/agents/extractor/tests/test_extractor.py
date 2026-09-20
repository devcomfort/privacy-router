"""Tests for independent judgments, extraction safeguards and redacted metadata."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.extractor import (
    ConfidentialityJudgment,
    ExtractionRecord,
    NecessityJudgment,
    PrivacyAnalysisUnavailable,
    redact_extraction_records,
)
from agents.extractor.extractor_core import ExtractorCore, _validate_record
from agents.extractor.schemas import _ExtractedItem, _ExtractedOutput
from contracts.annotation import IntentAnnotation
from policy import HeuristicPolicy, RecommendedAction


def make_item(
    category="EMAIL_ADDRESS",
    span="synthetic@example.invalid",
    confidence=0.99,
    *,
    confidentiality="private",
    confidentiality_reason="Personal contact supplied in the source.",
    necessity=None,
    necessity_reason="The task does not establish necessity.",
):
    return _ExtractedItem(
        category=category,
        span=span,
        confidence=confidence,
        confidentiality=ConfidentialityJudgment(value=confidentiality, reason=confidentiality_reason),
        necessity=NecessityJudgment(value=necessity, reason=necessity_reason),
    )


def task_intent(text):
    return IntentAnnotation.for_text(
        text,
        goal="Prepare correspondence",
        action="Draft",
        completion_condition="Generic draft ready",
    )


class TestValidateRecord:
    def test_valid_record(self):
        text = "주민등록번호 901212-1234567 기재"
        item = make_item(category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567", confidence=0.98)
        record = _validate_record(item, text)
        assert record is not None
        assert record.category == "RESIDENT_REGISTRATION_NUMBER"
        assert text[record.start : record.end] == item.span

    @pytest.mark.parametrize(
        ("category", "span", "confidence"),
        [("has space", "text", 0.9), ("VALID_TAG", "text", 0.3), ("VALID_TAG", "nonexistent", 0.9)],
    )
    def test_rejects_invalid_records(self, category, span, confidence):
        assert _validate_record(make_item(category, span, confidence), "some text here") is None

    @pytest.mark.parametrize(
        ("category", "span", "expected"),
        [
            ("my_tag", "text", "MY_TAG"),
            ("mobile_phone_number", "010-1234-5678", "PERSONAL_IDENTIFIER_NUMBER"),
            ("PROJECT_AURORA_SECRET", "Aurora", "SENSITIVE_DATA"),
            ("ACMEINC_SECRET", "Acme, Inc.", "SENSITIVE_DATA"),
            ("CODENAME_X", "X", "SENSITIVE_DATA"),
            ("KIM_MINJUN_PHONE_NUMBER", "김민준 010-1234-5678", "PERSONAL_IDENTIFIER_NUMBER"),
            ("ACQUISITION_TARGET", "Apollo Labs", "ACQUISITION_TARGET"),
            ("ACQUISITION_TARGET", "acquisition target Apollo Labs", "ACQUISITION_TARGET"),
        ],
    )
    def test_categories_are_reusable_and_do_not_leak_values(self, category, span, expected):
        record = _validate_record(make_item(category, span), f"Value: {span}.")
        assert record is not None
        assert record.category == expected

    @pytest.mark.parametrize("missing", ["confidentiality", "necessity"])
    def test_fresh_items_require_each_independent_reason(self, missing):
        judgments = {
            "confidentiality": {"value": "public", "reason": "Published topic"},
            "necessity": {"value": "required", "reason": "The requested subject"},
        }
        judgments[missing]["reason"] = None
        with pytest.raises(ValidationError, match="Both confidentiality.reason and necessity.reason are required"):
            _ExtractedItem(category="PROGRAMMING_LANGUAGE", span="Python", confidence=1, **judgments)


class TestExtractorCore:
    def test_model_failure_is_not_reported_as_non_sensitive(self):
        def unavailable(*args, **kwargs):
            raise TimeoutError("upstream unavailable")

        with pytest.raises(PrivacyAnalysisUnavailable) as error:
            ExtractorCore(call_structured=unavailable, max_tokens=1536).extract("private acquisition target")
        assert isinstance(error.value.__cause__, TimeoutError)

    @pytest.mark.parametrize("consistency", [None, False, True])
    def test_missing_intent_clears_only_necessity(self, consistency):
        text = "Explain Python; contact synthetic@example.invalid."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=consistency,
                masking_preserves_task=True,
                masking_reason="Can be masked",
                records=[
                    make_item(necessity="optional"),
                    make_item("PROGRAMMING_LANGUAGE", "Python", confidentiality="public", necessity="required"),
                ],
            )

        result = ExtractorCore(call_structured=assessment).extract(text)
        assert [record.confidentiality.value for record in result.records] == ["private", "public"]
        assert all(record.necessity.status == "unassessed" for record in result.records)
        assert all(record.necessity.reason for record in result.records)
        assert all(
            record.confidentiality.reason == "Personal contact supplied in the source." for record in result.records
        )
        assert result.masking_preserves_task is None
        assert HeuristicPolicy().recommend([result]).action is None

    @pytest.mark.parametrize("consistency", [None, False])
    def test_unconfirmed_intent_cannot_declassify_contacts(self, consistency):
        text = "Email synthetic@example.invalid."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=consistency,
                masking_preserves_task=True,
                masking_reason="Only drafting",
                records=[make_item(necessity="optional")],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=task_intent(text))
        record = result.records[0]
        assert record.span == "synthetic@example.invalid"
        assert record.confidentiality.value == "private"
        assert record.confidentiality.reason == "Personal contact supplied in the source."
        assert record.necessity.status == "unassessed"
        assert record.necessity.reason
        assert result.masking_preserves_task is None
        assert HeuristicPolicy().recommend([result]).action is None

    @pytest.mark.parametrize("necessity", ["required", "optional"])
    def test_confirmed_intent_preserves_assessment_and_source_offsets(self, necessity):
        text = "\n  수신자: synthetic@example.invalid\n"
        required = necessity == "required"
        intent = IntentAnnotation.for_text(
            text,
            goal="Prepare correspondence",
            action="Send" if required else "Draft",
            completion_condition="Email delivered" if required else "Draft ready",
            channel="email",
        )

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=not required,
                masking_reason="Assessed against completion",
                records=[make_item(necessity=necessity, necessity_reason="Assessed against completion")],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=intent)
        record = result.records[0]
        assert record.necessity.value == necessity
        assert (record.start, record.end) == (8, 33)
        assert text[record.start : record.end] == "synthetic@example.invalid"
        expected = RecommendedAction.KEEP_LOCAL if required else RecommendedAction.MASK_THEN_SHARE
        assert HeuristicPolicy().recommend([result]).action == expected

    def test_mismatched_source_is_rejected_before_inference(self):
        calls = []

        def inference(*args, **kwargs):
            calls.append(args)
            raise RuntimeError("must not receive mismatched source")

        with pytest.raises(ValueError):
            ExtractorCore(call_structured=inference).extract("original ", intent=task_intent("original"))
        assert calls == []

    @pytest.mark.parametrize(
        ("preserves_task", "expected"),
        [(False, RecommendedAction.KEEP_LOCAL), (True, RecommendedAction.MASK_THEN_SHARE), (None, None)],
    )
    def test_joint_assessment_does_not_require_individual_certainty(self, preserves_task, expected):
        text = "Contacts: synthetic@example.invalid, 010-1234-5678."
        intent = IntentAnnotation.for_text(
            text,
            goal="Prepare correspondence" if preserves_task is True else "Contact the recipient",
            action="Draft" if preserves_task is True else "Deliver",
            completion_condition="Draft ready" if preserves_task is True else "Recipient contacted",
            unresolved=("Delivery channel not selected",),
        )
        explanation = "Joint masking assessed against the task, independently of channel selection."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=preserves_task,
                masking_reason=explanation,
                records=[make_item(), make_item("PERSONAL_IDENTIFIER_NUMBER", "010-1234-5678")],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=intent)
        assert all(record.necessity.status == "unassessed" for record in result.records)
        assert result.masking_reason == explanation
        assert HeuristicPolicy().recommend([result]).action == expected

    @pytest.mark.parametrize("discarded_confidentiality", ["private", None])
    def test_discarded_protected_item_cannot_turn_remaining_public_items_into_public_result(
        self, discarded_confidentiality
    ):
        text = "Explain Python; account code SECRET123."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=True,
                masking_reason="All protected values can be masked",
                records=[
                    make_item("PROGRAMMING_LANGUAGE", "Python", confidentiality="public", necessity="required"),
                    make_item("ACCOUNT_CODE", "SECRET123", confidence=0.4, confidentiality=discarded_confidentiality),
                ],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=task_intent(text))
        assert [record.span for record in result.records] == ["Python"]
        assert result.sensitivity.is_sensitive is True
        assert result.masking_preserves_task is None
        assert HeuristicPolicy().recommend([result]).action is None

    def test_discarded_record_invalidates_joint_masking_with_other_private_records_remaining(self):
        text = "Draft for synthetic@example.invalid; account code SECRET123."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=True,
                masking_reason="Generic draft",
                records=[make_item(necessity="optional"), make_item("ACCOUNT_CODE", "SECRET123", 0.4)],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=task_intent(text))
        assert [record.span for record in result.records] == ["synthetic@example.invalid"]
        assert result.masking_preserves_task is None
        assert HeuristicPolicy().recommend([result]).action is None

    def test_public_required_subject_survives_with_independent_reasons(self):
        text = "Explain Python."
        calls = []

        def assessment(*args, **kwargs):
            calls.append(args)
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=True,
                masking_reason="No protected values are removed",
                records=[
                    make_item(
                        "PROGRAMMING_LANGUAGE",
                        "Python",
                        confidentiality="public",
                        confidentiality_reason="A publicly documented programming language.",
                        necessity="required",
                        necessity_reason="The requested explanation is about this language.",
                    )
                ],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=task_intent(text))
        assert len(calls) == 1
        record = result.records[0]
        assert text[record.start : record.end] == "Python"
        assert record.confidentiality.value == "public"
        assert record.necessity.value == "required"
        assert record.confidentiality.reason == "A publicly documented programming language."
        assert record.necessity.reason == "The requested explanation is about this language."
        assert result.sensitivity.is_sensitive is False
        assert HeuristicPolicy().recommend([result]).action == RecommendedAction.SHARE_ORIGINAL

    def test_mixed_public_required_and_private_optional_items_remain_independent(self):
        text = "Explain Python for synthetic@example.invalid; do not send it."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=True,
                masking_reason="The public subject remains available after masking the unused contact.",
                records=[
                    make_item("PROGRAMMING_LANGUAGE", "Python", confidentiality="public", necessity="required"),
                    make_item(necessity="optional"),
                ],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=task_intent(text))
        assert [(record.confidentiality.value, record.necessity.value) for record in result.records] == [
            ("public", "required"),
            ("private", "optional"),
        ]
        assert result.sensitivity.is_sensitive is True
        assert HeuristicPolicy().recommend([result]).action == RecommendedAction.MASK_THEN_SHARE

    def test_unassessed_confidentiality_remains_separate_from_known_necessity(self):
        text = "Explain codename Orion."

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=False,
                records=[
                    make_item(
                        "PROJECT_NAME",
                        "Orion",
                        confidentiality=None,
                        confidentiality_reason="Cannot establish whether the codename is published.",
                        necessity="required",
                        necessity_reason="It identifies the requested subject.",
                    )
                ],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=task_intent(text))
        record = result.records[0]
        assert record.confidentiality.status == "unassessed"
        assert record.necessity.value == "required"
        assert result.sensitivity.is_sensitive is True
        assert HeuristicPolicy().recommend([result]).action is None

    def test_rejected_public_spans_are_incomplete_evidence_and_not_cached(self):
        from cachier import Cachier
        from contracts import ExtractionResult, Sensitivity

        text = "Explain Python."
        intent = task_intent(text)
        cache = Cachier()
        key = cache.make_key(
            namespace="rejected-public", message=text, history=(), detector_fingerprint="test", intent=intent
        )
        cache.put(
            key, ExtractionResult(sensitivity=Sensitivity(is_sensitive=False, rationale="Prior complete assessment"))
        )

        def assessment(*args, **kwargs):
            return _ExtractedOutput(
                intent_consistent=True,
                masking_preserves_task=True,
                records=[
                    make_item(
                        "PROGRAMMING_LANGUAGE", "Not present in source", confidentiality="public", necessity="required"
                    )
                ],
            )

        result = ExtractorCore(call_structured=assessment).extract(text, intent=intent)
        assert HeuristicPolicy().recommend([result]).action is None
        cache.put(key, result)
        assert cache.get(key) is None


def test_redacted_projection_retains_labels_without_values_or_judgment_reasons():
    record = ExtractionRecord(
        category="EMAIL_ADDRESS",
        span="synthetic@example.invalid",
        confidence=0.95,
        start=0,
        end=25,
        confidentiality=ConfidentialityJudgment(value="private", reason="SECRET_CONFIDENTIALITY_REASON"),
        necessity=NecessityJudgment(value="optional", reason="SECRET_NECESSITY_REASON"),
    )
    assert redact_extraction_records([record]) == [
        {
            "index": 0,
            "category": "EMAIL_ADDRESS",
            "span": "<redacted>",
            "confidence": 0.95,
            "confidentiality": {"value": "private", "status": "assessed"},
            "necessity": {"value": "optional", "status": "assessed"},
        }
    ]


def test_missing_model_records_cannot_become_a_public_assessment():
    def absent_analysis(*args, **kwargs):
        return _ExtractedOutput.model_validate({})

    with pytest.raises(PrivacyAnalysisUnavailable):
        ExtractorCore(call_structured=absent_analysis).extract("A private source with no valid model assessment.")
