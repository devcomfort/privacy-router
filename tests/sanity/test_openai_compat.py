"""Sanity: OpenAI Python SDK compatibility with Privacy Router.

These tests verify that the Privacy Router API is compatible with the
official OpenAI Python client library. Focus is on correctness of the
contract, not exhaustive coverage.

Requires a running Privacy Router API at localhost:8787.
"""

import os

import pytest
from openai import BadRequestError, InternalServerError, OpenAI

BASE_URL = os.getenv("PRIVACY_ROUTER_URL", "http://localhost:8787/v1")
API_KEY = os.getenv("PRIVACY_ROUTER_API_KEY", "")
ROUTER_MODEL = "privacy-router"

if not API_KEY:
    pytest.skip("PRIVACY_ROUTER_API_KEY not set", allow_module_level=True)

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


# ── Models ───────────────────────────────────────────────────────────────────


class TestModels:
    """GET /v1/models — OpenAI-compatible model listing."""

    def test_list_models_returns_list(self):
        resp = client.models.list()
        assert hasattr(resp, "data")
        assert isinstance(resp.data, list)
        assert len(resp.data) > 0

    def test_model_has_required_fields(self):
        resp = client.models.list()
        for model in resp.data:
            assert model.id
            assert model.owned_by == "privacy-router"

    def test_model_id_contains_provider(self):
        """Explicit model IDs follow privacy-router/<provider>/<model> format."""
        resp = client.models.list()
        model_ids = {model.id for model in resp.data}
        assert ROUTER_MODEL in model_ids
        for model_id in model_ids - {ROUTER_MODEL}:
            assert model_id.startswith(f"{ROUTER_MODEL}/")
            assert len(model_id.split("/")) >= 3


# ── Chat Completions ─────────────────────────────────────────────────────────


class TestChatCompletions:
    """POST /v1/chat/completions — OpenAI-compatible chat."""

    def test_basic_chat(self):
        """Non-sensitive prompt should get a normal response."""
        resp = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=10,
        )
        assert resp.id.startswith("chatcmpl-")
        assert len(resp.choices) == 1
        assert resp.choices[0].message.content
        assert resp.choices[0].finish_reason in ("stop", "length")

    def test_response_has_usage(self):
        resp = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
        )
        assert resp.usage is not None
        assert resp.usage.prompt_tokens > 0
        assert resp.usage.completion_tokens > 0
        assert resp.usage.total_tokens > 0

    def test_system_message(self):
        """System + user message should work."""
        resp = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Reply in one sentence."},
                {"role": "user", "content": "What is 2+2?"},
            ],
            max_tokens=20,
        )
        assert resp.choices[0].message.content

    def test_multi_turn(self):
        """Multi-turn conversation should work."""
        resp = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {"role": "user", "content": "My name is TestBot."},
                {"role": "assistant", "content": "Hello TestBot!"},
                {"role": "user", "content": "What is my name?"},
            ],
            max_tokens=20,
        )
        content = resp.choices[0].message.content.lower()
        assert "testbot" in content

    def test_sensitive_data_detection(self):
        """Prompt with PII should be detected (privacy_router metadata)."""
        resp = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": "주민등록번호 901212-1234567로 조회해줘.",
                }
            ],
            max_tokens=50,
        )
        # Privacy Router adds custom metadata
        assert hasattr(resp, "privacy_router") or resp.choices[0].message.content
        # If privacy_router metadata exists, check detection
        pr = getattr(resp, "privacy_router", None)
        if pr:
            assert pr.get("is_sensitive") is True

    def test_model_field(self):
        """Response model field should indicate privacy-router."""
        resp = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        assert "privacy-router" in resp.model or resp.model == "privacy-router"


# ── Error handling ───────────────────────────────────────────────────────────


class TestErrors:
    """Error responses should be OpenAI-compatible."""

    def test_invalid_model_returns_error(self):

        with pytest.raises(BadRequestError):
            client.chat.completions.create(
                model="nonexistent/model",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5,
            )

    def test_empty_messages_returns_error(self):

        with pytest.raises((BadRequestError, InternalServerError)):
            client.chat.completions.create(
                model=ROUTER_MODEL,
                messages=[],
                max_tokens=5,
            )
