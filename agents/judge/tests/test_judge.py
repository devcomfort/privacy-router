"""Tests for agents.judge — policy decision engine.

Tests the Judge class with various sensitivity/record combinations.
No external dependencies — LLM calls are tested via full pipeline tests.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.judge import Judge, Judgment, MeaningfulnessAssessment


class TestJudge:
    """Judge with empty records returns allow."""

    def test_no_records_not_sensitive(self):
        judge = Judge()
        sensitivity = {"is_sensitive": False, "rationale": "test"}
        judgment = judge.classify(sensitivity, [], "hello world")
        assert judgment.policy_action == "allow"
        assert judgment.meaningful_after_masking.is_meaningful_after_masking is True

    def test_no_records_default_sensitivity(self):
        """When is_sensitive key missing and no records, defaults to not sensitive."""
        judge = Judge()
        judgment = judge.classify({}, [], "hello")
        assert judgment.policy_action == "allow"

    def test_allow_judgment_has_rationale(self):
        judge = Judge()
        judgment = judge.classify({"is_sensitive": False, "rationale": "no PII"}, [], "test")
        assert judgment.rationale == "no PII"

    def test_allow_strategy_mentions_external(self):
        judge = Judge()
        judgment = judge.classify({"is_sensitive": False, "rationale": "clean"}, [], "test")
        assert "외부" in judgment.strategy


class TestMeaningfulnessAssessment:
    """MeaningfulnessAssessment schema tests."""

    def test_create_true(self):
        m = MeaningfulnessAssessment(is_meaningful_after_masking=True, rationale="의미 유지")
        assert m.is_meaningful_after_masking is True
        assert m.rationale == "의미 유지"

    def test_create_false(self):
        m = MeaningfulnessAssessment(is_meaningful_after_masking=False, rationale="의미 상실")
        assert m.is_meaningful_after_masking is False

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            MeaningfulnessAssessment(is_meaningful_after_masking=True)

    def test_missing_rationale_raises(self):
        with pytest.raises(ValidationError):
            MeaningfulnessAssessment(rationale="test")


class TestJudgment:
    """Judgment schema and to_dict tests."""

    def test_judgment_to_dict(self):
        judgment = Judgment(
            meaningful_after_masking=MeaningfulnessAssessment(is_meaningful_after_masking=True, rationale="test"),
            policy_action="selective_mask",
            strategy="테스트",
            rationale="테스트",
        )
        d = judgment.to_dict()
        assert "policy_action" in d
        assert "meaningful_after_masking" in d
        assert d["policy_action"] == "selective_mask"

    def test_judgment_to_dict_contains_all_fields(self):
        judgment = Judgment(
            meaningful_after_masking=MeaningfulnessAssessment(is_meaningful_after_masking=False, rationale="의미 상실"),
            policy_action="block",
            strategy="로컬 처리",
            rationale="마스킹 시 질문 의미 상실",
        )
        d = judgment.to_dict()
        assert d["meaningful_after_masking"]["is_meaningful_after_masking"] is False
        assert d["meaningful_after_masking"]["rationale"] == "의미 상실"
        assert d["strategy"] == "로컬 처리"
        assert d["rationale"] == "마스킹 시 질문 의미 상실"

    def test_judgment_missing_policy_action_raises(self):
        with pytest.raises(ValidationError):
            Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(is_meaningful_after_masking=True, rationale="test"),
                strategy="test",
                rationale="test",
            )

    def test_judgment_roundtrip_dict(self):
        """to_dict → model_validate round-trip."""
        original = Judgment(
            meaningful_after_masking=MeaningfulnessAssessment(is_meaningful_after_masking=True, rationale="유지"),
            policy_action="allow",
            strategy="전송",
            rationale="민감 정보 없음",
        )
        d = original.to_dict()
        restored = Judgment.model_validate(d)
        assert restored.policy_action == original.policy_action
        assert restored.meaningful_after_masking.is_meaningful_after_masking is True


class TestJudgeFallback:
    """Test Judge fallback behavior when LLM call fails."""

    def test_sensitive_records_default_to_selective_mask(self):
        """Non-essential sensitive records are masked without an LLM fallback."""
        judge = Judge()
        records = [{"category": "RRN", "span": "901212-1234567"}]
        judgment = judge.classify(
            {"is_sensitive": True},
            records,
            "주민등록번호 901212-1234567 확인",
        )
        assert judgment.policy_action == "selective_mask"
        assert judgment.meaningful_after_masking.is_meaningful_after_masking is True

    def test_records_override_not_sensitive_flag(self):
        """Validated records are sensitive evidence even when the flag disagrees."""
        judge = Judge()
        records = [{"category": "RRN", "span": "901212-1234567"}]
        judgment = judge.classify({"is_sensitive": False, "rationale": "context"}, records, "test")
        assert judgment.policy_action == "selective_mask"

    def test_sensitive_without_records_blocks_local(self):
        """Sensitive text without spans cannot be safely sent or masked."""
        judge = Judge()
        judgment = judge.classify(
            {"is_sensitive": True, "rationale": "sensitive but unextractable"},
            [],
            "test",
        )
        assert judgment.policy_action == "block"
        assert judgment.meaningful_after_masking.is_meaningful_after_masking is False
