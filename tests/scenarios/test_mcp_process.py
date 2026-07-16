"""Scenario: MCP process tool testing.

Tests the unified `process` MCP tool with various actions.
Environment: Docker Compose up (db + api).

Run:
    docker compose up -d && sleep 8
    pytest tests/scenarios/test_mcp_process.py -v
"""

from __future__ import annotations

from db import init_db
from server.mcp import process

init_db()


class TestProcessAuto:
    """process(text, action='auto') — full pipeline."""

    def test_non_sensitive(self):
        result = process("오늘 서울 날씨는 맑습니다")
        assert result["action_taken"] in ("allowed", "generated")
        assert result["is_sensitive"] is False
        assert result["extraction_records"] == []

    def test_sensitive_pii(self):
        result = process("주민등록번호 901212-1234567을 확인해주세요")
        assert result["is_sensitive"] is True
        assert len(result["extraction_records"]) > 0
        rrn_record = next(
            record for record in result["extraction_records"] if record["category"] == "RESIDENT_REGISTRATION_NUMBER"
        )
        assert rrn_record["span"] == "<redacted>"


class TestProcessClassify:
    """process(text, action='classify') — extract only."""

    def test_classify_returns_records(self):
        result = process("주민등록번호 901212-1234567을 확인해주세요", action="classify")
        assert result["action_taken"] == "classified"
        assert result["content"] is None
        assert result["is_sensitive"] is True
        assert len(result["extraction_records"]) > 0

    def test_classify_non_sensitive(self):
        result = process("안녕하세요", action="classify")
        assert result["action_taken"] == "classified"
        assert result["is_sensitive"] is False


class TestProcessGenerate:
    """process(text, action='generate') — force LLM call."""

    def test_generate_masks_and_calls_llm(self):
        result = process(
            "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘",
            action="generate",
        )
        assert result["action_taken"] == "generated"
        assert result["content"] is not None
        assert result["requires_masking"] is True
        assert result["masking_session_id"] is not None


class TestProcessHydrate:
    """process(text, action='hydrate', chat_id=...) — hydrate from DB."""

    def test_hydrate_missing_session(self):
        result = process("test", action="hydrate", chat_id="nonexistent")
        assert result["action_taken"] == "error"
        assert "not found" in result["error"].lower()


class TestProcessWithChatId:
    """process(text, chat_id=...) — masking session persistence."""

    def test_returns_masking_session_id(self):
        result = process(
            "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘",
            chat_id="test-session-1",
        )
        if result["requires_masking"]:
            assert result["masking_session_id"] is not None
            assert len(result["placeholder_map"]) > 0
            assert "uid" in result["placeholder_map"][0]
