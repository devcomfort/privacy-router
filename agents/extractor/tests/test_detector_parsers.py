from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.extractor.parser import ParsedEntity
from agents.extractor.parsers import (
    DetectorParseError,
    LFMParser,
    LLMParser,
    OPFParser,
    PresidioParser,
)
from agents.extractor.schemas import Requiredness


TEXT = "문의: synthetic@example.invalid"
SPAN = "synthetic@example.invalid"


def test_llm_parser_preserves_reason_and_requiredness():
    raw = {
        "records": [
            {
                "tag": "EMAIL",
                "kind": "structural",
                "span": SPAN,
                "offsets": [4, 29],
                "reason": "개인 연락처 정보",
                "confidence": 0.97,
                "is_required": {"value": True, "reason": "응답에 실제 주소가 필요함"},
            }
        ]
    }

    [entity] = LLMParser().parse(raw, TEXT)

    assert isinstance(entity, ParsedEntity)
    assert entity.tag == "EMAIL"
    assert entity.offsets == (4, 29)
    assert entity.reason == "개인 연락처 정보"
    assert entity.is_required == Requiredness(value=True, reason="응답에 실제 주소가 필요함")


@dataclass
class FakePresidioResult:
    entity_type: str
    start: int
    end: int
    score: float
    analysis_explanation: object | None = None
    recognition_metadata: dict[str, str] | None = None


@dataclass
class FakeOPFSpan:
    label: str
    start: int
    end: int
    text: str
    placeholder: str


def test_opf_parser_accepts_typed_span_objects():
    raw = {"detected_spans": [FakeOPFSpan("private_email", 4, 29, SPAN, "<PRIVATE_EMAIL>")]}

    [entity] = OPFParser().parse(raw, TEXT)

    assert entity.tag == "EMAIL"
    assert entity.span == SPAN


def test_presidio_parser_maps_native_label_and_recognizer_metadata():
    raw = [
        FakePresidioResult(
            entity_type="EMAIL_ADDRESS",
            start=4,
            end=29,
            score=0.85,
            analysis_explanation={"textual_explanation": "Email recognizer match"},
            recognition_metadata={
                "recognizer_name": "EmailRecognizer",
                "recognizer_identifier": "email_recognizer",
            },
        )
    ]

    [entity] = PresidioParser().parse(raw, TEXT)

    assert entity.tag == "EMAIL"
    assert entity.native_label == "EMAIL_ADDRESS"
    assert entity.span == SPAN
    assert entity.confidence == 0.85
    assert entity.reason == "Email recognizer match"
    assert entity.native_metadata["recognizer_name"] == "EmailRecognizer"


def test_opf_parser_uses_typed_spans_and_ignores_redacted_text():
    raw = {
        "schema_version": 1,
        "text": TEXT,
        "detected_spans": [
            {
                "label": "private_email",
                "start": 4,
                "end": 29,
                "text": SPAN,
                "placeholder": "<PRIVATE_EMAIL>",
            }
        ],
        "redacted_text": "문의: <PRIVATE_EMAIL>",
    }

    [entity] = OPFParser().parse(raw, TEXT)

    assert entity.tag == "EMAIL"
    assert entity.native_label == "private_email"
    assert entity.span == SPAN
    assert entity.native_metadata["placeholder"] == "<PRIVATE_EMAIL>"
    assert "redacted_text" not in entity.native_metadata


def test_lfm_parser_maps_dotted_native_label():
    raw = [{"label": "contact.email", "start": 4, "end": 29, "score": 0.91}]

    [entity] = LFMParser().parse(raw, TEXT)

    assert entity.tag == "EMAIL"
    assert entity.native_label == "contact.email"
    assert entity.span == SPAN
    assert entity.confidence == 0.91


def test_parser_rejects_malformed_payload():
    with pytest.raises(DetectorParseError):
        OPFParser().parse({"detected_spans": [{"label": "private_email"}]}, TEXT)
