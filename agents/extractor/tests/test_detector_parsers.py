from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.extractor.lfm import LFMParser
from agents.extractor.llm import LLMParser
from agents.extractor.opf import OPFParser
from agents.extractor.parser import DetectorParseError, ParsedEntity
from agents.extractor.presidio import PresidioParser
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



def test_llm_parser_rejects_unknown_kind():
    with pytest.raises(DetectorParseError, match="kind"):
        LLMParser().parse(
            {"records": [{"tag": "EMAIL", "kind": "unknown", "span": SPAN}]},
            TEXT,
        )

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


def test_lfm_parser_accepts_official_decoder_type_field():
    raw = [{"start": 4, "end": 24, "type": "contact.email", "text": "alex@example.invalid"}]

    [entity] = LFMParser().parse(raw, "문의: alex@example.invalid")

    assert entity.tag == "EMAIL"
    assert entity.native_label == "contact.email"
    assert entity.span == "alex@example.invalid"
    assert entity.confidence is None


def test_parser_rejects_malformed_payload():
    with pytest.raises(DetectorParseError):
        OPFParser().parse({"detected_spans": [{"label": "private_email"}]}, TEXT)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("private_address", "ADDRESS"),
        ("private_phone", "PHONE"),
        ("private_url", "URL"),
        ("private_date", "DATE"),
        ("account_number", "ACCOUNT_NUMBER"),
        ("credential.private_key", "PRIVATE_KEY"),
        ("identity.national_id", "NATIONAL_ID"),
        ("contact.address", "ADDRESS"),
        ("financial.credit_card", "CREDIT_CARD"),
        ("healthcare.condition", "HEALTH_CONDITION"),
        ("org.company_name", "COMPANY_NAME"),
        ("legal.case_number", "CASE_NUMBER"),
    ],
)
def test_backend_labels_map_to_shared_tags(label: str, expected: str):
    [entity] = LFMParser().parse([{"label": label, "start": 0, "end": len(SPAN)}], SPAN)

    assert entity.tag == expected
