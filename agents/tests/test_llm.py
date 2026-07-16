"""Tests for agents/llm.py — call_llm() and call_llm_structured().

All external dependencies (litellm, instructor) are mocked.
No real LLM calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import BaseModel

# ── call_llm() ──────────────────────────────────────────────────────────────


class TestCallLlm:
    """Tests for the call_llm() function (lines 66-90)."""

    def _make_mock_response(self, content="  hello world  "):
        """Create a mock litellm response."""
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    @patch("agents.llm.litellm.completion")
    def test_default_external_model(self, mock_completion, monkeypatch):
        """Uses the current external model when no model or env override is specified."""
        from agents.llm import call_llm

        monkeypatch.delenv("LLM_MODEL", raising=False)
        mock_completion.return_value = self._make_mock_response("result")
        call_llm([{"role": "user", "content": "hi"}])

        _, kwargs = mock_completion.call_args
        assert kwargs["model"] == "openrouter/google/gemma-4-26b-it"

    @patch("agents.llm.litellm.completion")
    def test_custom_model_passed_through(self, mock_completion):
        """Custom model is forwarded to litellm."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("ok")
        call_llm([{"role": "user", "content": "hi"}], model="my-custom-model")

        _, kwargs = mock_completion.call_args
        assert kwargs["model"] == "my-custom-model"

    @patch("agents.llm.litellm.completion")
    def test_returns_stripped_content(self, mock_completion):
        """Return value is stripped of whitespace."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("  spaced  ")
        result = call_llm([{"role": "user", "content": "hi"}])

        assert result == "spaced"

    @patch("agents.llm.litellm.completion")
    def test_api_base_included_when_provided(self, mock_completion):
        """api_base is passed to litellm when non-empty."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("ok")
        call_llm([{"role": "user", "content": "hi"}], api_base="http://localhost:8000/v1")

        _, kwargs = mock_completion.call_args
        assert kwargs["api_base"] == "http://localhost:8000/v1"

    @patch("agents.llm.litellm.completion")
    def test_api_base_excluded_when_none(self, mock_completion):
        """api_base is not in kwargs when not provided."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("ok")
        call_llm([{"role": "user", "content": "hi"}])

        _, kwargs = mock_completion.call_args
        assert "api_base" not in kwargs

    @patch("agents.llm.litellm.completion")
    def test_temperature_and_max_tokens_passed(self, mock_completion):
        """Temperature and max_tokens are forwarded."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("ok")
        call_llm(
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=1024,
        )

        _, kwargs = mock_completion.call_args
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 1024

    @patch("agents.llm.litellm.completion")
    def test_custom_api_key_passed(self, mock_completion):
        """Custom api_key is forwarded to litellm."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("ok")
        call_llm([{"role": "user", "content": "hi"}], api_key="sk-test-key")

        _, kwargs = mock_completion.call_args
        assert kwargs["api_key"] == "sk-test-key"

    @patch("agents.llm.litellm.completion")
    def test_messages_forwarded(self, mock_completion):
        """Messages list is passed through correctly."""
        from agents.llm import call_llm

        mock_completion.return_value = self._make_mock_response("ok")
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hello"},
        ]
        call_llm(msgs)

        _, kwargs = mock_completion.call_args
        assert kwargs["messages"] == msgs


# ── call_llm_structured() ───────────────────────────────────────────────────


class _TestResponse(BaseModel):
    """Simple Pydantic model for structured output tests."""

    answer: str


class TestCallLlmStructured:
    """Tests for call_llm_structured() (lines 93-142)."""

    @patch("agents.llm.instructor.from_litellm")
    def test_default_external_model(self, mock_from_litellm, monkeypatch):
        """Uses the current external model when no model or env override is specified."""
        from agents.llm import call_llm_structured

        monkeypatch.delenv("LLM_MODEL", raising=False)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="42")
        mock_from_litellm.return_value = mock_client

        result = call_llm_structured(
            [{"role": "user", "content": "what is 6*7?"}],
            _TestResponse,
        )

        assert isinstance(result, _TestResponse)
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == "openrouter/google/gemma-4-26b-it"

    @patch("agents.llm.instructor.from_litellm")
    def test_custom_model_passed_through(self, mock_from_litellm):
        """Custom model is forwarded."""
        from agents.llm import call_llm_structured

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="yes")
        mock_from_litellm.return_value = mock_client

        call_llm_structured(
            [{"role": "user", "content": "confirm"}],
            _TestResponse,
            model="my-model",
        )

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == "my-model"

    @patch("agents.llm.instructor.from_litellm")
    def test_returns_parsed_response(self, mock_from_litellm):
        """Returns the Pydantic model instance."""
        from agents.llm import call_llm_structured

        expected = _TestResponse(answer="parsed")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = expected
        mock_from_litellm.return_value = mock_client

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
        )

        assert result == expected
        assert result.answer == "parsed"

    @patch("agents.llm.instructor.from_litellm")
    def test_api_base_triggers_json_mode(self, mock_from_litellm):
        """When api_base is provided, instructor.Mode.JSON is used."""
        import instructor

        from agents.llm import call_llm_structured

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="local")
        mock_from_litellm.return_value = mock_client

        call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            api_base="http://localhost:8000/v1",
        )

        mock_from_litellm.assert_called_once()
        _, kwargs = mock_from_litellm.call_args
        assert kwargs.get("mode") == instructor.Mode.JSON

    @patch("agents.llm.instructor.from_litellm")
    def test_no_api_base_uses_default_mode(self, mock_from_litellm):
        """Without api_base, instructor is called without mode kwarg."""
        from agents.llm import call_llm_structured

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="cloud")
        mock_from_litellm.return_value = mock_client

        call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
        )

        mock_from_litellm.assert_called_once()
        _, kwargs = mock_from_litellm.call_args
        assert "mode" not in kwargs

    @patch("agents.llm.instructor.from_litellm")
    def test_api_base_in_kwargs(self, mock_from_litellm):
        """api_base is forwarded to the create() call."""
        from agents.llm import call_llm_structured

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="ok")
        mock_from_litellm.return_value = mock_client

        call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            api_base="http://localhost:8000/v1",
        )

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["api_base"] == "http://localhost:8000/v1"

    @patch("agents.llm.instructor.from_litellm")
    def test_no_api_base_not_in_kwargs(self, mock_from_litellm):
        """api_base is not in create() kwargs when not provided."""
        from agents.llm import call_llm_structured

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="ok")
        mock_from_litellm.return_value = mock_client

        call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
        )

        _, kwargs = mock_client.chat.completions.create.call_args
        assert "api_base" not in kwargs

    @patch("agents.llm.litellm.completion")
    def test_gemini_model_uses_raw_json(self, mock_completion):
        """Gemini models bypass instructor and use _call_raw_json."""
        from agents.llm import call_llm_structured

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"answer": "gemini"}'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            model="google/gemini-3.1-flash-lite",
        )

        assert isinstance(result, _TestResponse)
        assert result.answer == "gemini"

    @patch("agents.llm.litellm.completion")
    def test_exaone_model_uses_raw_json(self, mock_completion):
        """EXAONE models bypass instructor and use _call_raw_json."""
        from agents.llm import call_llm_structured

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"answer": "exaone"}'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            model="LGAI-EXAONE/EXAONE-4.0-32B",
        )

        assert isinstance(result, _TestResponse)
        assert result.answer == "exaone"

    @patch("agents.llm.litellm.completion")
    def test_raw_json_strips_markdown_blocks(self, mock_completion):
        """_call_raw_json strips ```json ... ``` wrappers."""
        from agents.llm import call_llm_structured

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '```json\n{"answer": "stripped"}\n```'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            model="google/gemini-3.1-flash-lite",
        )

        assert result.answer == "stripped"

    @patch("agents.llm.litellm.completion")
    def test_raw_json_strips_thinking_tags(self, mock_completion):
        """_call_raw_json strips <think>...</think> tags."""
        from agents.llm import call_llm_structured

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '<think>reasoning</think>\n{"answer": "clean"}'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            model="google/gemini-3.1-flash-lite",
        )

        assert result.answer == "clean"

    @patch("agents.llm.litellm.completion")
    def test_raw_json_strips_plain_markdown_blocks(self, mock_completion):
        """_call_raw_json strips bare ``` ... ``` wrappers (no json tag)."""
        from agents.llm import call_llm_structured

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '```\n{"answer": "plain"}\n```'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            model="google/gemini-3.1-flash-lite",
        )

        assert result.answer == "plain"

    @patch("agents.llm.instructor.from_litellm")
    def test_dummy_api_key_for_local_without_key(self, mock_from_litellm, monkeypatch):
        """Uses 'dummy' api_key for local endpoints when no key provided."""
        from agents.llm import call_llm_structured

        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _TestResponse(answer="ok")
        mock_from_litellm.return_value = mock_client

        call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            api_base="http://localhost:8000/v1",
        )

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["api_key"] == "dummy"

    @patch("agents.llm.litellm.completion")
    def test_raw_json_with_api_base(self, mock_completion):
        """_call_raw_json passes api_base to litellm."""
        from agents.llm import call_llm_structured

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"answer": "with_base"}'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _TestResponse,
            model="google/gemini-3.1-flash-lite",
            api_base="http://localhost:8000/v1",
        )

        assert result.answer == "with_base"
        _, kwargs = mock_completion.call_args
        assert kwargs["api_base"] == "http://localhost:8000/v1"

    @patch("agents.llm.litellm.completion")
    def test_raw_json_handles_array_response(self, mock_completion):
        """_call_raw_json wraps array responses for models with list fields."""
        from pydantic import Field

        from agents.llm import call_llm_structured

        class _ListResponse(BaseModel):
            items: list[str] = Field(default_factory=list)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '["a", "b", "c"]'
        mock_completion.return_value = mock_resp

        result = call_llm_structured(
            [{"role": "user", "content": "test"}],
            _ListResponse,
            model="google/gemini-3.1-flash-lite",
        )

        assert result.items == ["a", "b", "c"]
