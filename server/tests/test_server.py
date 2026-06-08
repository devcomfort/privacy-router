"""Integration tests for the Privacy Router server."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.api.main import app
from server.api.auth import require_auth


# Override auth for tests — return a dummy provider_id
async def _mock_auth() -> str:
    return "test-provider"


app.dependency_overrides[require_auth] = _mock_auth
client = TestClient(app)


class TestModelsEndpoint:
    """GET /v1/models — should return the model registry."""

    def test_returns_model_list(self):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        for m in data["data"]:
            assert m["id"].startswith("privacy-router/")
            assert m["object"] == "model"


class TestChatUI:
    """GET / — should serve the web chat UI."""

    def test_serves_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text
        assert "Privacy Router" in resp.text


class TestChatCompletions:
    """POST /v1/chat/completions — pipeline integration tests."""

    def test_non_sensitive_prompt(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "privacy-router/openrouter/mistralai/ministral-3b-2512",
                "messages": [{"role": "user", "content": "오늘 서울 날씨는 맑고 기온은 25도입니다."}],
                "max_tokens": 64,
            },
        )
        assert resp.status_code in (200, 502)
        if resp.status_code == 200:
            pr = resp.json().get("privacy_router", {})
            assert pr.get("is_sensitive") is False

    def test_sensitive_pii_direct_query(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "privacy-router/openrouter/mistralai/ministral-3b-2512",
                "messages": [{"role": "user", "content": "내 주민등록번호가 뭐야?"}],
                "max_tokens": 64,
            },
        )
        assert resp.status_code in (200, 409, 502)

    def test_invalid_backend_returns_400(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "privacy-router/nonexistent/model",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 64,
            },
        )
        assert resp.status_code == 400
        assert "error" in resp.json()
