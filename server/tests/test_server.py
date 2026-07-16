"""Integration tests for the Privacy Router server."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

import server
import server.config as server_config
from agents import ContractStore, key_fingerprint
from db import Model, ProfileAgent, Provider, get_session
from server.adapters import LiteLLMAdapter
from server.api import app, require_admin_auth, require_auth


async def _mock_auth() -> str:
    return "test-provider"


@pytest.fixture(autouse=True)
def _override_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep this module's integration requests independent of auth boundary tests."""
    monkeypatch.setitem(app.dependency_overrides, require_auth, _mock_auth)
    monkeypatch.setitem(app.dependency_overrides, require_admin_auth, _mock_auth)


client = TestClient(app)


def test_cli_help_exits_without_starting_server(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = False

    def start_server() -> None:
        nonlocal started
        started = True

    monkeypatch.setattr(server, "_start_server", start_server)
    with pytest.raises(SystemExit) as exc_info:
        server.main(["--help"])

    assert exc_info.value.code == 0
    assert "usage: privacy-router" in capsys.readouterr().out
    assert started is False


def test_cli_without_arguments_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    starts = 0

    def start_server() -> None:
        nonlocal starts
        starts += 1

    monkeypatch.setattr(server, "_start_server", start_server)
    assert server.main([]) is None
    assert starts == 1


def test_config_cache_discards_a_load_started_before_invalidation(
    monkeypatch: pytest.MonkeyPatch,
):
    stale_config = object()
    fresh_config = object()
    first_load_started = Event()
    release_first_load = Event()
    load_count = 0
    original_config = server_config._config

    def load_config():
        nonlocal load_count
        load_count += 1
        if load_count == 1:
            first_load_started.set()
            assert release_first_load.wait(5)
            return stale_config
        return fresh_config

    monkeypatch.setattr(server_config, "load_config", load_config)
    server_config._config = None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            loading = executor.submit(server_config.get_config)
            assert first_load_started.wait(2)
            server_config.invalidate_config_cache()
            release_first_load.set()
            resolved = loading.result()

        assert resolved is fresh_config
        assert server_config.get_config() is fresh_config
        assert load_count == 2
    finally:
        release_first_load.set()
        server_config._config = original_config


class TestModelsEndpoint:
    """GET /v1/models — should return the model registry."""

    def test_returns_model_list(self):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        ids = {model["id"] for model in data["data"]}
        assert "privacy-router" in ids
        for model in data["data"]:
            assert model["id"] == "privacy-router" or model["id"].startswith("privacy-router/")
            assert model["object"] == "model"

    def test_settings_exposes_provider_for_each_registered_model(self):
        resp = client.get("/api/settings")

        assert resp.status_code == 200
        for model in resp.json()["models"]:
            assert model["provider_id"] == model["model_id"].split("/", 1)[0]

    def test_registered_model_can_be_deactivated(self):
        model_id = f"openrouter/test-model-{uuid.uuid4().hex}"
        created = client.post(
            "/api/v1/models",
            json={"model_id": model_id, "provider_id": "openrouter"},
        )
        assert created.status_code == 201

        removed = client.delete(f"/api/v1/models/{created.json()['id']}")
        assert removed.status_code == 204

        listed_ids = {model["model_id"] for model in client.get("/api/v1/models").json()}
        assert model_id not in listed_ids

    def test_concurrent_duplicate_registration_is_serialized(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        model_id = f"openrouter/concurrent-model-{uuid.uuid4().hex}"
        original_exec = Session.exec
        counter_lock = Lock()
        first_query_entered = Event()
        release_first_query = Event()
        second_query_entered = Event()
        query_count = 0

        def delay_model_lookup(session, statement, *args, **kwargs):
            nonlocal query_count
            statement_text = str(statement)
            if "FROM models" in statement_text and "models.model_id" in statement_text:
                with counter_lock:
                    query_count += 1
                    current_query = query_count
                if current_query == 1:
                    first_query_entered.set()
                    assert release_first_query.wait(5)
                elif current_query == 2:
                    second_query_entered.set()
            return original_exec(session, statement, *args, **kwargs)

        monkeypatch.setattr(Session, "exec", delay_model_lookup)
        payload = {"model_id": model_id, "provider_id": "openrouter"}

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(client.post, "/api/v1/models", json=payload)
                assert first_query_entered.wait(2)
                second = executor.submit(client.post, "/api/v1/models", json=payload)
                second_query_entered.wait(0.5)
                release_first_query.set()
                responses = [first.result(), second.result()]
            session = get_session()
            try:
                rows = session.exec(select(Model).where(Model.model_id == model_id)).all()
                assert len(rows) == 1
            finally:
                session.close()
            assert sorted(response.status_code for response in responses) == [201, 409]
        finally:
            release_first_query.set()
            session = get_session()
            try:
                model = session.exec(select(Model).where(Model.model_id == model_id)).first()
                if model is not None:
                    session.delete(model)
                    session.commit()
            finally:
                session.close()

    def test_model_registration_maps_unique_constraint_to_conflict(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        model_id = f"openrouter/constraint-conflict-{uuid.uuid4().hex}"
        original_commit = Session.commit

        def reject_model_insert(session):
            if any(isinstance(item, Model) and item.model_id == model_id for item in session.new):
                raise IntegrityError("forced duplicate", {}, Exception("duplicate"))
            return original_commit(session)

        monkeypatch.setattr(Session, "commit", reject_model_insert)

        response = client.post(
            "/api/v1/models",
            json={"model_id": model_id, "provider_id": "openrouter"},
        )

        assert response.status_code == 409
        assert "already registered" in response.text

    def test_model_registration_schema_lists_valid_tiers(self):
        tier_schema = app.openapi()["components"]["schemas"]["ModelCreate"]["properties"]["tier"]

        assert tier_schema["enum"] == ["small", "middle", "large"]

    def test_model_registration_rejects_invalid_tier(self):
        response = client.post(
            "/api/v1/models",
            json={
                "model_id": f"openrouter/invalid-tier-{uuid.uuid4().hex}",
                "provider_id": "openrouter",
                "tier": "edge",
            },
        )

        assert response.status_code == 422

    def test_local_model_registration_uses_provider_endpoint_and_invalidates_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        provider_id = f"local-{uuid.uuid4().hex}"
        model_id = f"{provider_id}/test-model"
        session = get_session()
        try:
            session.add(
                Provider(
                    id=provider_id,
                    name="Local Test Provider",
                    api_base="http://127.0.0.1:8999/v1",
                )
            )
            session.commit()
        finally:
            session.close()

        monkeypatch.setattr(server_config, "_config", object())
        try:
            created = client.post(
                "/api/v1/models",
                json={
                    "model_id": model_id,
                    "provider_id": provider_id,
                    "location": "local",
                },
            )
            assert created.status_code == 201
            assert server_config._config is None

            server_config._config = object()
            removed = client.delete(f"/api/v1/models/{created.json()['id']}")
            assert removed.status_code == 204
            assert server_config._config is None
        finally:
            session = get_session()
            try:
                model = session.exec(select(Model).where(Model.model_id == model_id)).first()
                if model is not None:
                    session.delete(model)
                provider = session.get(Provider, provider_id)
                if provider is not None:
                    session.delete(provider)
                session.commit()
            finally:
                session.close()

    def test_local_model_registration_rejects_remote_endpoint(self):
        model_id = f"openrouter/local-test-{uuid.uuid4().hex}"

        try:
            response = client.post(
                "/api/v1/models",
                json={
                    "model_id": model_id,
                    "provider_id": "openrouter",
                    "location": "local",
                    "api_base_override": "https://models.example.com/v1",
                },
            )

            assert response.status_code == 422
            assert "loopback" in response.text
        finally:
            session = get_session()
            try:
                model = session.exec(select(Model).where(Model.model_id == model_id)).first()
                if model is not None:
                    session.delete(model)
                    session.commit()
            finally:
                session.close()

    def test_profile_bound_model_cannot_be_deactivated(self):
        session = get_session()
        try:
            binding = session.exec(select(ProfileAgent)).first()
            assert binding is not None
            model = session.exec(select(Model).where(Model.model_id == binding.model_id)).first()
            assert model is not None
            model_record_id = model.id
        finally:
            session.close()

        try:
            response = client.delete(f"/api/v1/models/{model_record_id}")

            assert response.status_code == 409
            assert "profile" in response.text.lower()
        finally:
            session = get_session()
            try:
                model = session.get(Model, model_record_id)
                if model is not None and not model.is_active:
                    model.is_active = True
                    session.add(model)
                    session.commit()
            finally:
                session.close()


class TestProviderKeyEndpoints:
    """Provider keys can be managed without returning plaintext."""

    def test_provider_key_can_be_stored_and_removed(self):
        provider_id = f"test-provider-{uuid.uuid4().hex}"
        api_key = "test-provider-api-key"
        session = get_session()
        try:
            session.add(
                Provider(
                    id=provider_id,
                    name="Test Provider",
                )
            )
            session.commit()
        finally:
            session.close()

        try:
            stored = client.post(
                f"/api/providers/{provider_id}/key",
                json={"api_key": api_key},
            )
            assert stored.status_code == 200
            assert api_key not in stored.text
            expected_fingerprint = key_fingerprint(api_key)
            assert stored.json()["key_fingerprint"] == expected_fingerprint
            assert len(expected_fingerprint) == 16
            assert api_key[:8] not in expected_fingerprint
            assert api_key[-4:] not in expected_fingerprint

            providers = client.get("/api/providers")
            assert providers.status_code == 200
            provider = next(item for item in providers.json()["providers"] if item["id"] == provider_id)
            assert provider["has_key"] is True
            assert api_key not in providers.text
            assert provider["key_fingerprint"] == expected_fingerprint

            removed = client.delete(f"/api/providers/{provider_id}/key")
            assert removed.status_code == 200
        finally:
            session = get_session()
            try:
                provider = session.get(Provider, provider_id)
                if provider is not None:
                    session.delete(provider)
                    session.commit()
            finally:
                session.close()

    def test_stored_provider_key_is_used_by_remote_adapter(self, monkeypatch: pytest.MonkeyPatch):
        provider_id = f"test-provider-{uuid.uuid4().hex}"
        model_id = f"openrouter/test-model-{uuid.uuid4().hex}"
        api_key = "test-provider-api-key-db-path"
        session = get_session()
        try:
            session.add(
                Provider(
                    id=provider_id,
                    name="Test Provider",
                )
            )
            session.add(
                Model(
                    model_id=model_id,
                    provider_id=provider_id,
                    location="external",
                    tier="small",
                )
            )
            session.commit()
        finally:
            session.close()

        captured: dict[str, object] = {}

        def capture_completion(**kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr("server.adapters.base.litellm.completion", capture_completion)

        try:
            stored = client.post(
                f"/api/providers/{provider_id}/key",
                json={"api_key": api_key},
            )
            assert stored.status_code == 200

            LiteLLMAdapter().call(
                model_id,
                [{"role": "user", "content": "test"}],
                api_base="https://api.example.test/v1",
            )

            assert captured["api_key"] == api_key
        finally:
            session = get_session()
            try:
                model = session.exec(select(Model).where(Model.model_id == model_id)).first()
                if model is not None:
                    session.delete(model)
                provider = session.get(Provider, provider_id)
                if provider is not None:
                    session.delete(provider)
                session.commit()
            finally:
                session.close()


class TestChatUI:
    """GET / — should serve the web chat UI."""

    def test_serves_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "<!doctype html>" in resp.text.lower()
        assert "Privacy Router" in resp.text


class TestRoutePrecedence:
    """API routes must take precedence over the static SPA fallback."""

    def test_api_route_is_not_shadowed_by_static_fallback(self):
        resp = client.get("/v1/responses/nonexistent-response")

        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")


class TestMaskingOwnership:
    """Masking contracts are visible only to their API-key owner."""

    def test_get_and_hydrate_reject_another_owner(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="owned-route-test",
            record_count=1,
            policy_action="selective_mask",
            owner_id="test-provider",
        )
        store.save_records(
            session_id,
            [{"category": "SECRET", "span": "private", "confidence": 0.9}],
            {"SECRET#deadbeef": "private"},
        )

        own_get = client.get(f"/api/v1/masking/{session_id}")
        own_hydrate = client.post(
            f"/api/v1/masking/{session_id}/hydrate",
            json={"content": "value=SECRET#deadbeef"},
        )

        async def other_auth() -> str:
            return "other-provider"

        app.dependency_overrides[require_auth] = other_auth
        try:
            other_get = client.get(f"/api/v1/masking/{session_id}")
            other_hydrate = client.post(
                f"/api/v1/masking/{session_id}/hydrate",
                json={"content": "value=SECRET#deadbeef"},
            )
        finally:
            app.dependency_overrides[require_auth] = _mock_auth
            store.deactivate_session(session_id)

        assert own_get.status_code == 200
        assert own_hydrate.status_code == 200
        assert own_hydrate.json()["hydrated"] == "value=private"
        assert other_get.status_code == 404
        assert other_hydrate.status_code == 404


class TestChatCompletions:
    """POST /v1/chat/completions — pipeline integration tests."""

    def test_non_sensitive_prompt(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "privacy-router",
                "messages": [{"role": "user", "content": "오늘 서울 날씨는 맑고 기온은 25도입니다."}],
                "max_tokens": 64,
            },
        )
        assert resp.status_code in (200, 502, 503)
        if resp.status_code == 200:
            pr = resp.json().get("privacy_router", {})
            assert pr.get("is_sensitive") is False
        elif resp.status_code == 503:
            error = resp.json()["error"]
            assert error["code"] == "privacy_analysis_failed"
            assert error["retryable"] is False

    def test_sensitive_pii_direct_query(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "privacy-router",
                "messages": [{"role": "user", "content": "내 주민등록번호가 뭐야?"}],
                "max_tokens": 64,
            },
        )
        assert resp.status_code in (200, 409, 502, 503)
        if resp.status_code == 503:
            error = resp.json()["error"]
            assert error["code"] == "privacy_analysis_failed"
            assert error["retryable"] is False

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
