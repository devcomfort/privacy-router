"""Tests for MCP tools — real API calls, no mocking.

These tests verify the full pipeline with actual SLM calls.
Requires: valid OPENROUTER_API_KEY in environment.
"""

from __future__ import annotations

import os

import pytest

from db.session import init_db

init_db()

from server.mcp.tools import classify, route, list_models, set_model, list_providers, generate


# ── classify / route — real SLM calls ────────────────────────────────────────


class TestClassify:
    """Test classify MCP tool with real SLM."""

    def test_classify_non_sensitive(self):
        result = classify("오늘 서울 날씨는 맑고 기온은 25도입니다")
        assert result["is_sensitive"] is False
        assert result["policy_action"] == "allow"
        assert result["records"] == []
        assert result["requires_masking"] is False

    def test_classify_sensitive_pii(self):
        result = classify("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘")
        assert result["is_sensitive"] is True
        assert result["policy_action"] in ("mask_and_send", "prompt_user")
        assert len(result["records"]) >= 1
        assert any("RESIDENT" in r["category"].upper() or "REGISTRATION" in r["category"].upper()
                    for r in result["records"])

    def test_classify_records_have_all_fields(self):
        result = classify("주민등록번호 901212-1234567을 확인해주세요")
        assert result["is_sensitive"] is True
        for r in result["records"]:
            assert "category" in r
            assert "span" in r
            assert "confidence" in r
            assert "is_load_bearing" in r
            assert "reasoning" in r

    def test_classify_prompt_user_for_load_bearing(self):
        result = classify("주민등록번호 901212-1234567을 확인해주세요")
        assert result["is_sensitive"] is True
        assert result["policy_action"] == "prompt_user"
        assert result["requires_masking"] is False

    def test_classify_mask_and_send_for_creation(self):
        result = classify("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘")
        assert result["is_sensitive"] is True
        assert result["policy_action"] == "mask_and_send"
        assert result["requires_masking"] is True


class TestRoute:
    """Test route MCP tool (alias for classify)."""

    def test_route_returns_same_structure(self):
        result = route("오늘 날씨가 좋습니다")
        assert "is_sensitive" in result
        assert "records" in result
        assert "policy_action" in result
        assert "requires_masking" in result
        assert "description" in result


# ── generate — real LLM call ────────────────────────────────────────────────


class TestGenerate:
    """Test generate MCP tool with real LLM."""

    @pytest.mark.skipif(
        not os.getenv("OPENROUTER_API_KEY"),
        reason="OPENROUTER_API_KEY not set"
    )
    def test_generate_non_sensitive(self):
        result = generate("오늘 서울 날씨는 맑고 기온은 25도입니다. 간단한 인사만 해주세요.")
        assert "content" in result
        assert result["is_sensitive"] is False
        assert result["policy_action"] == "allow"
        assert result["model_used"] != "none"
        assert result["latency_ms"] > 0

    @pytest.mark.skipif(
        not os.getenv("OPENROUTER_API_KEY"),
        reason="OPENROUTER_API_KEY not set"
    )
    def test_generate_sensitive_prompt_user(self):
        result = generate("주민등록번호 901212-1234567을 확인해주세요")
        assert result["is_sensitive"] is True
        assert result["policy_action"] == "prompt_user"
        assert result["model_used"] == "none"
        assert "확인" in result["content"] or "확인이 필요" in result["content"]

    @pytest.mark.skipif(
        not os.getenv("OPENROUTER_API_KEY"),
        reason="OPENROUTER_API_KEY not set"
    )
    def test_generate_sensitive_mask_and_send(self):
        result = generate("주민등록번호 901212-1234567을 포함한 간단한 인사 이메일을 작성해줘. 1문장만.")
        assert result["is_sensitive"] is True
        assert result["policy_action"] == "mask_and_send"
        assert result["model_used"] != "none"
        assert "content" in result
        assert len(result["content"]) > 0


# ── DB tools — real database ────────────────────────────────────────────────


class TestListModels:
    """Test list_models MCP tool."""

    def test_list_models_returns_list(self):
        result = list_models()
        assert isinstance(result, list)

    def test_list_models_with_tier_filter(self):
        result = list_models(tier="external")
        assert isinstance(result, list)
        for m in result:
            assert m["tier"] == "external"


class TestSetModel:
    """Test set_model MCP tool."""

    def test_set_model_creates_config(self):
        result = set_model("test_agent_real", "openrouter/mistralai/ministral-3b-2512")
        assert result["status"] == "ok"
        assert result["agent_name"] == "test_agent_real"
        assert result["model_id"] == "openrouter/mistralai/ministral-3b-2512"

    def test_set_model_updates_existing(self):
        set_model("test_update_real", "openrouter/model1")
        result = set_model("test_update_real", "openrouter/model2")
        assert result["status"] == "ok"
        assert result["model_id"] == "openrouter/model2"

    def test_set_model_with_custom_params(self):
        result = set_model("test_custom_real", "openrouter/test/model", temperature=0.5, max_tokens=2048)
        assert result["status"] == "ok"
        assert result["temperature"] == 0.5
        assert result["max_tokens"] == 2048


class TestListProviders:
    """Test list_providers MCP tool."""

    def test_list_providers_returns_list(self):
        result = list_providers()
        assert isinstance(result, list)


class TestUsageLogging:
    """Test that UsageLog entries are created."""

    def test_classify_creates_usage_log(self):
        classify("테스트 메시지 입니다")

        from db.models import UsageLog
        from db.session import get_session
        from sqlmodel import select

        session = get_session()
        try:
            logs = session.exec(select(UsageLog).where(UsageLog.event == "classify")).all()
            assert len(logs) >= 1
            latest = logs[-1]
            assert latest.event == "classify"
            assert latest.input_hash is not None
        finally:
            session.close()
