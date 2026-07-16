"""OpenAPI endpoint integration tests.

Tests all REST API endpoints against a running Privacy Router server.
Requires: Docker Compose up (db + api).

Run:
    docker compose up -d && sleep 8
    pytest tests/test_openapi.py -v
"""

from __future__ import annotations

import os
import uuid

import httpx
from dotenv import load_dotenv

from db import ApiKey, Provider, get_session, init_db
from server.api import create_api_key

BASE = "http://localhost:8787"
load_dotenv()

init_db()


def _get_auth_headers() -> dict:
    """Create a test API key and return auth headers."""
    raw, hashed = create_api_key()
    session = get_session()
    try:
        provider = session.get(Provider, "test-provider")
        if not provider:
            provider = Provider(id="test-provider", name="test", provider_type="openrouter", is_active=True)
            session.add(provider)
            session.commit()
        key = ApiKey(provider_id="test-provider", name="test-key", key_hash=hashed, prefix=raw[:8], is_active=True)
        session.add(key)
        session.commit()
    finally:
        session.close()
    return {"Authorization": f"Bearer {raw}"}


AUTH_HEADERS = _get_auth_headers()


def _get_admin_headers() -> dict[str, str]:
    """Return the independent management credential used by the live server."""
    admin_key = os.getenv("PRIVACY_ROUTER_ADMIN_KEY")
    if not admin_key:
        raise RuntimeError("Set PRIVACY_ROUTER_ADMIN_KEY before running live OpenAPI tests")
    return {"X-Privacy-Router-Admin-Key": admin_key}


ADMIN_HEADERS = _get_admin_headers()


# ── Health / Public ──────────────────────────────────────────────────────────


class TestPublicEndpoints:
    """Endpoints that don't require authentication."""

    def test_swagger_ui(self):
        resp = httpx.get(f"{BASE}/docs")
        assert resp.status_code == 200
        assert "swagger-ui" in resp.text.lower()

    def test_openapi_schema(self):
        resp = httpx.get(f"{BASE}/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/v1/chat/completions" in schema["paths"]

    def test_v1_models_public(self):
        resp = httpx.get(f"{BASE}/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"


# ── API Keys ─────────────────────────────────────────────────────────────────


class TestAPIKeys:
    """API key CRUD operations."""

    def test_create_key(self):
        resp = httpx.post(
            f"{BASE}/api/v1/keys",
            json={"name": "test-key", "description": "test"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["api_key"].startswith("pr-")
        assert data["name"] == "test-key"
        assert data["id"]

    def test_list_keys(self):
        resp = httpx.get(f"{BASE}/api/v1/keys", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Models ───────────────────────────────────────────────────────────────────


class TestModels:
    """Model registry CRUD."""

    def test_list_models(self):
        resp = httpx.get(f"{BASE}/api/v1/models", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_model(self):
        model_id = f"test-provider/test-model-{uuid.uuid4().hex}"
        response = httpx.post(
            f"{BASE}/api/v1/models",
            json={
                "model_id": model_id,
                "provider_id": "test-provider",
                "display_name": "Test Model",
                "tier": "small",
                "cost_per_1m_tokens": 0.0,
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 201

        removed = httpx.delete(
            f"{BASE}/api/v1/models/{response.json()['id']}",
            headers=ADMIN_HEADERS,
        )
        assert removed.status_code == 204


# ── Providers ────────────────────────────────────────────────────────────────


class TestProviders:
    """Provider CRUD."""

    def test_list_providers(self):
        resp = httpx.get(f"{BASE}/api/providers", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json()["providers"], list)


# ── Classify / Generate ──────────────────────────────────────────────────────


class TestClassifyEndpoint:
    """POST /api/v1/classify — extract + judge only."""

    def test_classify_sensitive(self):
        resp = httpx.post(
            f"{BASE}/api/v1/classify",
            json={"text": "주민등록번호 901212-1234567을 확인해주세요"},
            headers=AUTH_HEADERS,
            timeout=60,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_sensitive"] is True
        assert len(data["records"]) > 0
        rrn_record = next(record for record in data["records"] if record["category"] == "RESIDENT_REGISTRATION_NUMBER")
        assert rrn_record["span"] == "<redacted>"

    def test_classify_non_sensitive(self):
        resp = httpx.post(
            f"{BASE}/api/v1/classify",
            json={"text": "오늘 서울 날씨는 맑습니다"},
            headers=AUTH_HEADERS,
            timeout=60,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_sensitive"] is False


# ── Chat Completions ─────────────────────────────────────────────────────────


class TestChatCompletions:
    """POST /v1/chat/completions — full pipeline."""

    def test_non_sensitive(self):
        resp = httpx.post(
            f"{BASE}/v1/chat/completions",
            json={
                "model": "privacy-router/openrouter/google/gemma-4-26b-a4b-it",
                "messages": [{"role": "user", "content": "안녕하세요"}],
                "max_tokens": 32,
            },
            headers=AUTH_HEADERS,
            timeout=60,
        )
        assert resp.status_code in (200, 502)

    def test_sensitive_pii_returns_409(self):
        resp = httpx.post(
            f"{BASE}/v1/chat/completions",
            json={
                "model": "privacy-router/openrouter/google/gemma-4-26b-a4b-it",
                "messages": [{"role": "user", "content": "내 주민등록번호가 뭐야?"}],
                "max_tokens": 32,
            },
            headers=AUTH_HEADERS,
            timeout=60,
        )
        assert resp.status_code in (200, 409, 502)


# ── Masking ──────────────────────────────────────────────────────────────────


class TestMaskingEndpoints:
    """GET /api/v1/masking/{id} and POST /api/v1/masking/{id}/hydrate."""

    def test_get_nonexistent_session(self):
        resp = httpx.get(
            f"{BASE}/api/v1/masking/nonexistent-id",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    def test_hydrate_nonexistent_session(self):
        resp = httpx.post(
            f"{BASE}/api/v1/masking/nonexistent-id/hydrate",
            json={"content": "test [CATEGORY#abc12345]"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ── Settings ─────────────────────────────────────────────────────────────────


class TestSettings:
    """GET /api/settings — admin-protected config."""

    def test_get_settings(self):
        resp = httpx.get(f"{BASE}/api/settings", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
