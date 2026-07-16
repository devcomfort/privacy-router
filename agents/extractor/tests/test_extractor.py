"""Tests for agents.extractor — Extractor facade, ExtractorCore, Critic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.extractor import Critic, ExtractionRecord, PrivacyAnalysisUnavailable
from agents.extractor.extractor import Extractor, _validate_critic_records
from agents.extractor.extractor_core import ExtractorCore, _validate_record
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

    def test_normalizes_to_screaming_case(self):
        """Near-miss like my_tag is normalized to MY_TAG."""
        item = _ExtractedItem(category="my_tag", span="text", confidence=0.9)
        record = _validate_record(item, "some text")
        assert record is not None
        assert record.category == "MY_TAG"

    def test_canonicalizes_legacy_category_alias(self):
        item = _ExtractedItem(
            category="mobile_phone_number",
            span="010-1234-5678",
            confidence=0.9,
        )
        record = _validate_record(item, "전화번호는 010-1234-5678입니다")
        assert record is not None
        assert record.category == "PERSONAL_IDENTIFIER_NUMBER"

    def test_replaces_value_bearing_category_with_safe_fallback(self):
        item = _ExtractedItem(
            category="PROJECT_AURORA_SECRET",
            span="Aurora",
            confidence=0.9,
        )
        record = _validate_record(item, "코드명 Aurora는 아직 비공개입니다")
        assert record is not None
        assert record.category == "SENSITIVE_DATA"

    def test_replaces_punctuation_compacted_value_bearing_category(self):
        item = _ExtractedItem(
            category="ACMEINC_SECRET",
            span="Acme, Inc.",
            confidence=0.9,
        )
        record = _validate_record(item, "인수 대상은 Acme, Inc.입니다")
        assert record is not None
        assert record.category == "SENSITIVE_DATA"

    def test_replaces_short_value_bearing_category_with_safe_fallback(self):
        item = _ExtractedItem(
            category="CODENAME_X",
            span="X",
            confidence=0.9,
        )
        record = _validate_record(item, "비공개 코드명은 X입니다")
        assert record is not None
        assert record.category == "SENSITIVE_DATA"

    def test_canonicalizes_cross_script_value_prefix(self):
        item = _ExtractedItem(
            category="KIM_MINJUN_PHONE_NUMBER",
            span="김민준 010-1234-5678",
            confidence=0.9,
        )
        record = _validate_record(item, "연락처는 김민준 010-1234-5678입니다")
        assert record is not None
        assert record.category == "PERSONAL_IDENTIFIER_NUMBER"

    def test_keeps_reusable_open_vocabulary_category(self):
        item = _ExtractedItem(
            category="ACQUISITION_TARGET",
            span="Apollo Labs",
            confidence=0.9,
        )
        record = _validate_record(item, "인수 대상은 Apollo Labs입니다")
        assert record is not None
        assert record.category == "ACQUISITION_TARGET"

    def test_keeps_safe_category_when_semantic_words_overlap_span(self):
        item = _ExtractedItem(
            category="ACQUISITION_TARGET",
            span="acquisition target Apollo Labs",
            confidence=0.9,
        )
        record = _validate_record(item, "The acquisition target Apollo Labs is confidential")
        assert record is not None
        assert record.category == "ACQUISITION_TARGET"

    def test_rejects_invalid_format(self):
        """Truly invalid format (spaces) is rejected."""
        item = _ExtractedItem(category="has space", span="text", confidence=0.9)
        assert _validate_record(item, "some text here") is None


class TestExtractorCore:
    @patch("agents.extractor.extractor_core.load_prompt")
    @patch("agents.extractor.extractor_core.load_config")
    @patch("agents.extractor.extractor_core.resolve_local_api_base")
    def test_constructor_resolves_registry_api_base(
        self,
        mock_resolve_local_api_base,
        mock_load_config,
        mock_load_prompt,
    ):
        config = MagicMock()
        config.decision.model = "openai/local-decision"
        config.decision.api_base = None
        config.decision.config.max_tokens = 1536
        mock_load_config.return_value = config
        mock_resolve_local_api_base.return_value = "http://127.0.0.1:8010/v1"
        mock_load_prompt.return_value = _CRITIC_PROMPT_DICT

        core = ExtractorCore()

        mock_resolve_local_api_base.assert_called_once_with(config, "openai/local-decision", None)
        assert core._model == "openai/local-decision"
        assert core._api_base == "http://127.0.0.1:8010/v1"
        assert core._max_tokens == 1536

    @patch("agents.extractor.extractor_core.load_prompt")
    @patch("agents.extractor.extractor_core.load_config")
    @patch("agents.extractor.extractor_core.resolve_local_api_base")
    def test_explicit_model_uses_its_registry_api_base(
        self,
        mock_resolve_local_api_base,
        mock_load_config,
        mock_load_prompt,
    ):
        config = MagicMock()
        config.decision.api_base = "http://127.0.0.1:8999/v1"
        config.decision.config.max_tokens = 1536
        mock_load_config.return_value = config
        mock_resolve_local_api_base.return_value = "http://127.0.0.1:8011/v1"
        mock_load_prompt.return_value = _CRITIC_PROMPT_DICT

        core = ExtractorCore(model="openai/override")

        mock_resolve_local_api_base.assert_called_once_with(config, "openai/override", None)
        assert core._api_base == "http://127.0.0.1:8011/v1"
        assert core._max_tokens == 1536

    @patch(
        "agents.extractor.extractor_core.call_llm_structured",
        side_effect=TimeoutError("upstream unavailable"),
    )
    def test_model_failure_is_not_reported_as_non_sensitive(self, _mock_llm):
        core = object.__new__(ExtractorCore)
        core._prompt = {"template": "{{text}}"}
        core._model = "test/model"
        core._api_base = None
        core._max_tokens = 1536

        with pytest.raises(RuntimeError, match="analysis unavailable"):
            core.extract("private acquisition target")

        assert _mock_llm.call_args.kwargs["max_tokens"] == 1536


class TestExtractionRecord:
    def test_open_vocabulary_category_round_trip(self):
        record = ExtractionRecord(
            category="ACQUISITION_TARGET",
            span="Apollo Labs",
            confidence=0.9,
            start=0,
            end=11,
        )
        assert record.model_dump()["category"] == "ACQUISITION_TARGET"


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
        existing = [
            ExtractionRecord(
                category="PERSON_NAME",
                span="김동현",
                confidence=0.9,
                start=0,
                end=3,
            )
        ]
        item = _CriticItem(category="PERSON_NAME", span="김동현", confidence=0.9)
        result = _validate_critic_records([item], "김동현은 학생입니다.", existing)
        assert len(result) == 0

    def test_invalid_category_filtered(self):
        """Category with spaces is invalid."""
        item = _CriticItem(category="has space", span="text", confidence=0.9)
        result = _validate_critic_records([item], "some text here", [])
        assert len(result) == 0

    def test_critic_uses_same_category_canonicalization(self):
        item = _CriticItem(
            category="MOBILE_PHONE_NUMBER",
            span="010-1234-5678",
            confidence=0.9,
        )
        result = _validate_critic_records([item], "연락처는 010-1234-5678입니다", [])
        assert len(result) == 1
        assert result[0].category == "PERSONAL_IDENTIFIER_NUMBER"

    def test_low_confidence_filtered(self):
        item = _CriticItem(category="VALID_TAG", span="text", confidence=0.3)
        result = _validate_critic_records([item], "some text", [])
        assert len(result) == 0

    def test_span_not_in_text(self):
        item = _CriticItem(category="VALID_TAG", span="nonexistent", confidence=0.9)
        result = _validate_critic_records([item], "some text", [])
        assert len(result) == 0


class TestCritic:
    @patch("agents.extractor.critic.load_prompt")
    @patch("agents.extractor.critic.load_config")
    @patch("agents.extractor.critic.resolve_local_api_base")
    def test_constructor_resolves_registry_api_base(
        self,
        mock_resolve_local_api_base,
        mock_load_config,
        mock_load_prompt,
    ):
        config = MagicMock()
        config.decision.model = "openai/local-decision"
        config.decision.api_base = None
        config.decision.config.max_tokens = 1536
        mock_load_config.return_value = config
        mock_resolve_local_api_base.return_value = "http://127.0.0.1:8010/v1"
        mock_load_prompt.return_value = _CRITIC_PROMPT_DICT

        critic = Critic()

        mock_resolve_local_api_base.assert_called_once_with(config, "openai/local-decision", None)
        assert critic._model == "openai/local-decision"
        assert critic._api_base == "http://127.0.0.1:8010/v1"
        assert critic._max_tokens == 1536

    @patch("agents.extractor.critic.load_prompt")
    @patch("agents.extractor.critic.load_config")
    @patch("agents.extractor.critic.resolve_local_api_base")
    def test_explicit_model_uses_its_registry_api_base(
        self,
        mock_resolve_local_api_base,
        mock_load_config,
        mock_load_prompt,
    ):
        config = MagicMock()
        config.decision.api_base = "http://127.0.0.1:8999/v1"
        config.decision.config.max_tokens = 1536
        mock_load_config.return_value = config
        mock_resolve_local_api_base.return_value = "http://127.0.0.1:8011/v1"
        mock_load_prompt.return_value = _CRITIC_PROMPT_DICT

        critic = Critic(model="openai/override")

        mock_resolve_local_api_base.assert_called_once_with(config, "openai/override", None)
        assert critic._api_base == "http://127.0.0.1:8011/v1"
        assert critic._max_tokens == 1536

    @patch(
        "agents.extractor.critic.call_llm_structured",
        side_effect=ConnectionError("critic unavailable"),
    )
    def test_model_failure_is_not_reported_as_no_missed_spans(self, _mock_llm):
        critic = object.__new__(Critic)
        critic._template = "{{text}}\n{{tagged_spans}}"
        critic._model = "test/model"
        critic._api_base = None
        critic._max_tokens = 1536

        with pytest.raises(PrivacyAnalysisUnavailable):
            critic.review("private acquisition target", [])

        assert _mock_llm.call_args.kwargs["max_tokens"] == 1536


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

    @patch(
        "agents.extractor.critic.call_llm_structured",
        side_effect=ConnectionError("critic unavailable"),
    )
    def test_critic_model_failure_propagates(self, _mock_llm):
        core = MagicMock()
        core.extract.return_value = _make_result(records=[], is_sensitive=False)
        critic = object.__new__(Critic)
        critic._template = "{{text}}\n{{tagged_spans}}"
        critic._model = "test/model"
        critic._api_base = None
        critic._max_tokens = 1536
        ext = Extractor(core=core, critic=critic)

        with pytest.raises(PrivacyAnalysisUnavailable):
            ext.extract("private acquisition target")

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
