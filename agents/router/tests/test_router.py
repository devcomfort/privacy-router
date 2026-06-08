"""Tests for the Router — real SLM calls, no mocking.

These tests verify the full pipeline with actual SLM calls.
Requires: valid OPENROUTER_API_KEY in environment.
"""

from __future__ import annotations

import pytest

from agents.router import PrivacyRouter


class TestRouterPolicyActions:
    """Verify each routing path with real SLM."""

    def test_allow_when_not_sensitive(self):
        pr = PrivacyRouter()
        result = pr.process("오늘 서울 날씨는 맑고 기온은 25도입니다")

        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is False
        assert result.judgment.policy_action == "allow"
        assert result.mask_indices == []

    def test_mask_and_send_when_no_load_bearing(self):
        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘")

        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is True
        assert result.judgment.policy_action == "mask_and_send"
        assert len(result.mask_indices) == len(result.records)
        assert result.judgment.meaningful_after_masking.is_meaningful_after_masking is True

    def test_prompt_user_when_load_bearing(self):
        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.route.endpoint == "prompt"
        assert result.judgment.policy_action == "prompt_user"
        assert result.mask_indices == []
        assert result.judgment.meaningful_after_masking.is_meaningful_after_masking is False

    def test_mixed_records_with_load_bearing(self):
        pr = PrivacyRouter()
        result = pr.process("새로운 강화학습 알고리즘 아이디어를 조언해주세요. 주민등록번호 901212-1234567.")

        assert result.route.endpoint == "prompt"
        assert result.judgment.policy_action == "prompt_user"


class TestRouterPipelineResult:
    """Verify PipelineResult structure."""

    def test_result_has_all_fields(self):
        pr = PrivacyRouter()
        result = pr.process("테스트")

        assert hasattr(result, "sensitivity")
        assert hasattr(result, "judgment")
        assert hasattr(result, "route")
        assert hasattr(result, "records")
        assert hasattr(result, "mask_indices")

    def test_rationale_contains_load_bearing_info(self):
        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        if result.records:
            assert "load-bearing" in result.judgment.rationale or "load_bearing" in result.judgment.rationale

    def test_records_have_schema_fields(self):
        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        for r in result.records:
            assert hasattr(r, "category")
            assert hasattr(r, "span")
            assert hasattr(r, "confidence")
            assert hasattr(r, "is_load_bearing")
            assert hasattr(r, "reasoning")
