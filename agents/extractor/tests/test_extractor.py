"""Tests for agents.extractor — Extractor facade, ExtractorCore, Critic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.extractor import ExtractionRecord
from agents.extractor.extractor import Extractor, _validate_critic_records
from agents.extractor.extractor_core import _validate_record
from agents.extractor.schemas import (
    CriticOutput,
    ExtractionResult,
    Sensitivity,
    _CriticItem,
    _ExtractedItem,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_result(records=None, is_sensitive=True, rationale="탐지됨") -> ExtractionResult:
    return ExtractionResult(
        sensitivity=Sensitivity(is_sensitive=is_sensitive, rationale=rationale),
        records=records or [],
    )


_RECORD = ExtractionRecord(
    category="RESIDENT_REGISTRATION_NUMBER",
    span="901212-1234567",
    confidence=0.98,
    reasoning="주민등록번호",
    is_essential=False,
    start=5,
    end=20,
)

_CRITIC_PROMPT_DICT = {
    "model": "test/model",
    "template": "Review: {{text}}\nTagged: {{tagged_spans}}",
}


# ═════════════════════════════════════════════════════════════════════════════
# _validate_record (ExtractorCore)
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateRecord:
    def test_valid_record(self):
        text = "주민등록번호 901212-1234567 기재"
        item = _ExtractedItem(
            category="RESIDENT_REGISTRATION_NUMBER",
            span="901212-1234567",
            confidence=0.98,
        )
        record = _validate_record(item, text)
        assert record is not None
        assert record.category == "RESIDENT_REGISTRATION_NUMBER"

    def test_invalid_tag_format(self):
        """Category with spaces is invalid even after .upper()."""
        item = _ExtractedItem(category="has space", span="text", confidence=0.9)
        assert _validate_record(item, "some text here") is None

    def test_low_confidence(self):
        item = _ExtractedItem(category="VALID_TAG", span="text", confidence=0.3)
        assert _validate_record(item, "some text") is None

    def test_span_not_found(self):
        item = _ExtractedItem(category="VALID_TAG", span="nonexistent", confidence=0.9)
        assert _validate_record(item, "some text") is None

    def test_valid_screaming_case(self):
        """Valid SCREAMING_SNAKE_CASE passes and is preserved."""
        item = _ExtractedItem(category="MY_TAG", span="text", confidence=0.9)
        record = _validate_record(item, "some text")
        assert record is not None
        assert record.category == "MY_TAG"

    def test_lowercase_rejected(self):
        """Lowercase category is rejected (not SCREAMING_SNAKE_CASE)."""
        item = _ExtractedItem(category="my_tag", span="text", confidence=0.9)
        assert _validate_record(item, "some text") is None

# ═════════════════════════════════════════════════════════════════════════════
# ExtractionRecord
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractionRecord:
    def test_make_placeholder(self):
        record = ExtractionRecord(
            category="RESIDENT_REGISTRATION_NUMBER",
            span="901212-1234567",
            confidence=0.9,
            start=0,
            end=15,
        )
        assert record.make_placeholder(1) == "[RESIDENT_REGISTRATION_NUMBER#1]"


# ═════════════════════════════════════════════════════════════════════════════
# _validate_critic_records
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateCriticRecords:
    def test_valid_critic_item(self):
        item = _CriticItem(category="PERSON_NAME", span="김동현", confidence=0.9)
        result = _validate_critic_records([item], "김동현은 학생입니다.", [])
        assert len(result) == 1
        assert result[0].category == "PERSON_NAME"
        assert result[0].start == 0
        assert result[0].detection_type == "contextual"

    def test_dedup_against_existing(self):
        existing = [ExtractionRecord(
            category="PERSON_NAME", span="김동현",
            confidence=0.9, start=0, end=3,
        )]
        item = _CriticItem(category="PERSON_NAME", span="김동현", confidence=0.9)
        result = _validate_critic_records([item], "김동현은 학생입니다.", existing)
        assert len(result) == 0

    def test_invalid_category_filtered(self):
        """Category with spaces is invalid."""
        item = _CriticItem(category="has space", span="text", confidence=0.9)
        result = _validate_critic_records([item], "some text here", [])
        assert len(result) == 0

    def test_low_confidence_filtered(self):
        item = _CriticItem(category="VALID_TAG", span="text", confidence=0.3)
        result = _validate_critic_records([item], "some text", [])
        assert len(result) == 0

    def test_span_not_in_text(self):
        item = _CriticItem(category="VALID_TAG", span="nonexistent", confidence=0.9)
        result = _validate_critic_records([item], "some text", [])
        assert len(result) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Extractor facade
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractorFacade:
    def test_default_precision(self):
        ext = Extractor()
        assert ext.precision == "default"
        assert ext._critic is None

    def test_high_precision(self):
        ext = Extractor(precision="high")
        assert ext.precision == "high"
        assert ext._critic is not None

    def test_inject_core_and_critic(self):
        core = MagicMock()
        critic = MagicMock()
        ext = Extractor(core=core, critic=critic)
        assert ext._core is core
        assert ext._critic is critic


class TestExtractorCriticPath:
    """Test that Critic runs correctly in the Extractor facade."""

    @patch("agents.extractor.extractor_core.load_prompt")
    @patch("agents.extractor.extractor_core.call_llm_structured")
    def test_critic_runs_when_phase1_finds_nothing(self, mock_llm, mock_load):
        """Critic must run even when Phase 1 returns zero records."""
        mock_load.return_value = _CRITIC_PROMPT_DICT
        mock_llm.return_value = _make_result(records=[], is_sensitive=False)

        core = MagicMock()
        core.extract.return_value = _make_result(records=[], is_sensitive=False)
        critic = MagicMock()
        critic.review.return_value = CriticOutput(found_missed=False, missed_records=[])

        ext = Extractor(core=core, critic=critic)
        ext.extract("주민등록번호 901212-1234567 기재")

        critic.review.assert_called_once()

    @patch("agents.extractor.extractor_core.load_prompt")
    @patch("agents.extractor.extractor_core.call_llm_structured")
    def test_critic_skipped_on_empty_text(self, mock_llm, mock_load):
        """Critic must NOT run on empty/whitespace text."""
        mock_load.return_value = _CRITIC_PROMPT_DICT

        core = MagicMock()
        core.extract.return_value = _make_result(records=[], is_sensitive=False)
        critic = MagicMock()

        ext = Extractor(core=core, critic=critic)
        ext.extract("")

        critic.review.assert_not_called()

    @patch("agents.extractor.extractor_core.load_prompt")
    @patch("agents.extractor.extractor_core.call_llm_structured")
    def test_critic_merges_records(self, mock_llm, mock_load):
        """Critic-found records should be merged into the result."""
        mock_load.return_value = _CRITIC_PROMPT_DICT
        mock_llm.return_value = _make_result(records=[_RECORD], is_sensitive=True)

        core = MagicMock()
        core.extract.return_value = _make_result(records=[_RECORD], is_sensitive=True)
        critic = MagicMock()
        critic.review.return_value = CriticOutput(
            found_missed=True,
            missed_records=[
                _CriticItem(
                    category="EMAIL_ADDRESS",
                    span="test@co.kr",
                    confidence=0.9,
                    reasoning="이메일 주소",
                )
            ],
        )

        ext = Extractor(core=core, critic=critic)
        result = ext.extract("주민등록번호 901212-1234567 기재, 연락처 test@co.kr")

        assert len(result.records) == 2
        spans = {r.span for r in result.records}
        assert "901212-1234567" in spans
        assert "test@co.kr" in spans
