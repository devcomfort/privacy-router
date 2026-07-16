"""Contract tests for the lightweight MCP HTTP client."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from server.mcp import lightweight


@pytest.fixture(autouse=True)
def _configured_api_key(monkeypatch):
    monkeypatch.setattr(lightweight, "API_KEY", "pr-test")


class TestLightweightProcess:
    def test_auto_uses_one_protected_request_and_forwards_options(self, monkeypatch):
        response = MagicMock()
        response.json.return_value = {"action_taken": "generated"}
        post = MagicMock(return_value=response)
        monkeypatch.setattr(lightweight.httpx, "post", post)

        result = lightweight.process(
            "private input",
            model="provider/model",
            chat_id="chat-123",
        )

        assert result == {"action_taken": "generated"}
        post.assert_called_once()
        assert post.call_args.args[0].endswith("/api/v1/generate")
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer pr-test"
        assert post.call_args.kwargs["json"] == {
            "text": "private input",
            "model": "provider/model",
            "chat_id": "chat-123",
        }

    def test_classify_only_calls_classify_endpoint(self, monkeypatch):
        response = MagicMock()
        response.json.return_value = {"is_sensitive": False}
        post = MagicMock(return_value=response)
        monkeypatch.setattr(lightweight.httpx, "post", post)

        result = lightweight.process("safe input", action="classify")

        assert result == {"is_sensitive": False}
        assert post.call_args.args[0].endswith("/api/v1/classify")

    def test_hydrate_uses_chat_id_as_session_id(self, monkeypatch):
        response = MagicMock()
        response.json.return_value = {"hydrated": "restored"}
        post = MagicMock(return_value=response)
        monkeypatch.setattr(lightweight.httpx, "post", post)

        result = lightweight.process(
            "masked output",
            action="hydrate",
            chat_id="session-123",
        )

        assert result == {
            "action_taken": "hydrated",
            "content": "restored",
            "masking_session_id": "session-123",
        }
        assert post.call_args.args[0].endswith("/api/v1/masking/session-123/hydrate")
        assert post.call_args.kwargs["json"] == {"content": "masked output"}

    def test_hydrate_requires_chat_id(self):
        with pytest.raises(ValueError, match="chat_id"):
            lightweight.process("masked output", action="hydrate")

    def test_unsupported_action_is_rejected(self):
        with pytest.raises(ValueError, match="Unsupported action"):
            lightweight.process("raw input", action="allow")


def test_missing_api_key_is_rejected_before_http(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr(lightweight, "API_KEY", "")
    monkeypatch.setattr(lightweight.httpx, "post", post)

    with pytest.raises(RuntimeError, match="PRIVACY_ROUTER_API_KEY"):
        lightweight.process("safe input")

    post.assert_not_called()


@pytest.mark.asyncio
async def test_server_mcp_package_entrypoint_lists_tools():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.mcp"],
    )
    async with (
        stdio_client(parameters) as streams,
        ClientSession(*streams) as session,
    ):
        await session.initialize()
        result = await session.list_tools()

    assert {tool.name for tool in result.tools} >= {
        "process",
        "review",
        "apply_decision",
    }


def test_lightweight_module_import_does_not_load_full_server_stack():
    probe = (
        "import sys\n"
        "import server.mcp.lightweight\n"
        "loaded = {name for name in "
        "('agents', 'db', 'server.api', 'server.mcp.tools') "
        "if name in sys.modules}\n"
        "assert not loaded, sorted(loaded)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
