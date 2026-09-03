"""Security-boundary regression tests for management APIs and public metadata."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from agents import ExtractionRecord, Requiredness, redact_extraction_records
from db import ApiKey, init_db
from server.api import app, bootstrap_api_key_from_env, require_admin_auth, require_auth


@pytest.fixture
def runtime_mode():
    runtime = importlib.import_module("server.runtime")
    previous = runtime.get_runtime_mode()
    try:
        yield runtime
    finally:
        runtime.set_runtime_mode(previous)


def _loopback_client() -> TestClient:
    return TestClient(app, client=("127.0.0.1", 50000))


def _route_dependencies(path: str, method: str) -> set[Callable[..., object]]:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return {dependency.call for dependency in route.dependant.dependencies}
    raise AssertionError(f"Route not found: {method} {path}")


def test_admin_login_is_fail_closed_and_sets_scoped_session_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.delenv("PRIVACY_ROUTER_ADMIN_PASSWORD", raising=False)
    client = TestClient(app, base_url="https://testserver")

    missing = client.post("/api/admin/session", json={"password": "anything"})
    assert missing.status_code == 503

    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")
    wrong = client.post("/api/admin/session", json={"password": "wrong-admin-secret"})
    assert wrong.status_code == 401
    assert "set-cookie" not in wrong.headers

    logged_in = client.post(
        "/api/admin/session",
        json={"password": "expected-admin-secret"},
    )
    assert logged_in.status_code == 200
    assert logged_in.headers["cache-control"] == "no-store"
    login_payload = logged_in.json()
    assert login_payload["authenticated"] is True
    assert login_payload["expires_in"] == 1800
    assert isinstance(login_payload["csrf_token"], str)
    assert len(login_payload["csrf_token"]) >= 32
    set_cookie = logged_in.headers["set-cookie"]
    assert "pr_admin_session=" in set_cookie
    assert "pr_admin_csrf=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api" in set_cookie
    assert "Secure" in set_cookie

    status = client.get("/api/admin/session")
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json() == {
        "authenticated": True,
        "csrf_token": login_payload["csrf_token"],
    }


def test_admin_logout_revokes_browser_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")
    client = TestClient(app, base_url="https://testserver")
    login = client.post(
        "/api/admin/session",
        json={"password": "expected-admin-secret"},
    )
    csrf_token = login.json()["csrf_token"]

    assert client.delete("/api/admin/session").status_code == 403
    assert (
        client.delete(
            "/api/admin/session",
            headers={"X-Privacy-Router-CSRF-Token": "wrong-token"},
        ).status_code
        == 403
    )

    logged_out = client.delete(
        "/api/admin/session",
        headers={"X-Privacy-Router-CSRF-Token": csrf_token},
    )

    assert logged_out.status_code == 200
    assert logged_out.headers["cache-control"] == "no-store"
    assert logged_out.json() == {"authenticated": False}
    assert client.get("/api/admin/session").status_code == 401


def test_admin_session_rejects_csrf_cookie_from_another_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")
    first = TestClient(app, base_url="https://testserver")
    second = TestClient(app, base_url="https://testserver")
    first_login = first.post(
        "/api/admin/session",
        json={"password": "expected-admin-secret"},
    )
    second_login = second.post(
        "/api/admin/session",
        json={"password": "expected-admin-secret"},
    )

    mixed = TestClient(
        app,
        base_url="https://testserver",
        cookies={
            "pr_admin_session": first.cookies.get("pr_admin_session"),
            "pr_admin_csrf": second_login.json()["csrf_token"],
        },
    )

    assert first_login.json()["csrf_token"] != second_login.json()["csrf_token"]
    assert mixed.get("/api/admin/session").status_code == 401


def test_admin_login_rejects_plain_http_off_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")

    response = TestClient(
        app,
        base_url="http://localhost",
        client=("203.0.113.10", 50000),
    ).post(
        "/api/admin/session",
        headers={"Host": "localhost"},
        json={"password": "expected-admin-secret"},
    )

    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_admin_login_allows_explicit_loopback_publish_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")
    monkeypatch.setenv("PRIVACY_ROUTER_ALLOW_INSECURE_ADMIN", "1")

    response = TestClient(
        app,
        base_url="http://localhost",
        client=("172.18.0.1", 50000),
    ).post(
        "/api/admin/session",
        json={"password": "expected-admin-secret"},
    )

    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]


def test_admin_login_allows_plain_http_from_actual_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")

    response = TestClient(
        app,
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    ).post(
        "/api/admin/session",
        json={"password": "expected-admin-secret"},
    )

    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]


def test_admin_login_handles_unicode_passwords_without_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "관리자-암호-✓")
    client = TestClient(app, base_url="https://testserver")

    assert (
        client.post(
            "/api/admin/session",
            json={"password": "틀린-암호-✓"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/admin/session",
            json={"password": "관리자-암호-✓"},
        ).status_code
        == 200
    )


def test_admin_login_rejects_oversized_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")

    response = TestClient(app, base_url="https://testserver").post(
        "/api/admin/session",
        json={"password": "x" * 257},
    )

    assert response.status_code == 422


def test_admin_login_rate_limits_repeated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")
    client = TestClient(
        app,
        base_url="https://testserver",
        client=("198.51.100.42", 50000),
    )

    statuses = [
        client.post(
            "/api/admin/session",
            json={"password": f"wrong-{attempt}"},
        ).status_code
        for attempt in range(6)
    ]

    assert statuses == [401, 401, 401, 401, 401, 429]


def test_admin_login_failure_cache_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "expected-admin-secret")
    sessions = importlib.import_module("server.api.routes.admin_session")
    monkeypatch.setattr(sessions, "_MAX_TRACKED_PEERS", 2, raising=False)
    with sessions._failed_logins_lock:
        sessions._failed_logins.clear()
    try:
        for index in range(3):
            response = TestClient(
                app,
                base_url="https://testserver",
                client=(f"198.51.100.{index + 1}", 50000),
            ).post(
                "/api/admin/session",
                json={"password": "wrong"},
            )
            assert response.status_code == 401

        assert len(sessions._failed_logins) <= 2
    finally:
        with sessions._failed_logins_lock:
            sessions._failed_logins.clear()


def test_legacy_admin_header_does_not_bypass_session_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_KEY", "legacy-admin-secret")
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "configured-admin-password")

    response = TestClient(app).get(
        "/api/v1/keys",
        headers={"X-Privacy-Router-Admin-Key": "legacy-admin-secret"},
    )

    assert response.status_code == 401


def test_runtime_capabilities_report_secure_serve_mode(runtime_mode, monkeypatch) -> None:
    runtime_mode.set_runtime_mode("serve")
    monkeypatch.setattr(
        "server.api.routes.runtime.load_config",
        lambda: SimpleNamespace(
            decision=SimpleNamespace(model="openai/google/gemma-4-26b-local"),
            local=SimpleNamespace(model="openai/google/gemma-4-26b-local"),
            external=SimpleNamespace(model="openrouter/google/gemma-4-26b-a4b-it"),
            models=[
                SimpleNamespace(id="openai/google/gemma-4-26b-local", cost_per_1m_tokens=0.0),
                SimpleNamespace(id="openrouter/google/gemma-4-26b-a4b-it", cost_per_1m_tokens=0.06),
            ],
        ),
    )

    response = TestClient(app).get("/api/runtime")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "mode": "serve",
        "default_model": "privacy-router",
        "model_roles": {
            "decision": "openai/google/gemma-4-26b-local",
            "local": "openai/google/gemma-4-26b-local",
            "external": "openrouter/google/gemma-4-26b-a4b-it",
        },
        "model_costs": {
            "openai/google/gemma-4-26b-local": 0.0,
            "openrouter/google/gemma-4-26b-a4b-it": 0.06,
        },
    }


def test_environment_api_key_bootstrap_is_idempotent_and_redacted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "environment-key.db"
    auth_engine = create_engine(f"sqlite:///{database_path}")
    monkeypatch.setattr("db.session.engine", auth_engine)
    monkeypatch.setenv("PRIVACY_ROUTER_API_KEY", "pr-environment-bootstrap-secret")
    init_db()

    bootstrap_api_key_from_env()
    bootstrap_api_key_from_env()

    with Session(auth_engine) as session:
        keys = session.exec(select(ApiKey)).all()

    assert len(keys) == 1
    assert keys[0].name == "environment"
    assert keys[0].key_hash != "pr-environment-bootstrap-secret"
    assert b"pr-environment-bootstrap-secret" not in database_path.read_bytes()
    previous_hash = keys[0].key_hash
    monkeypatch.setenv("PRIVACY_ROUTER_API_KEY", "pr-environment-rotated-secret")
    bootstrap_api_key_from_env()

    with Session(auth_engine) as session:
        rotated_keys = session.exec(select(ApiKey)).all()

    assert len(rotated_keys) == 1
    assert rotated_keys[0].key_hash != previous_hash
    database_bytes = database_path.read_bytes()
    assert b"pr-environment-bootstrap-secret" not in database_bytes
    assert b"pr-environment-rotated-secret" not in database_bytes


def test_environment_api_key_rotation_deactivates_hash_collisions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_engine = create_engine(f"sqlite:///{tmp_path / 'environment-key-collision.db'}")
    monkeypatch.setattr("db.session.engine", auth_engine)
    first_key = "pr-environment-first-secret"
    colliding_key = "pr-environment-collision-secret"
    latest_key = "pr-environment-latest-secret"
    monkeypatch.setenv("PRIVACY_ROUTER_API_KEY", first_key)
    init_db()
    bootstrap_api_key_from_env()

    collision_hash = hashlib.sha256(colliding_key.encode()).hexdigest()
    with Session(auth_engine) as session:
        session.add(
            ApiKey(
                id="manual-collision",
                name="manual collision",
                key_hash=collision_hash,
                prefix=colliding_key[:11],
                is_active=True,
            )
        )
        session.commit()

    monkeypatch.setenv("PRIVACY_ROUTER_API_KEY", colliding_key)
    bootstrap_api_key_from_env()
    monkeypatch.setenv("PRIVACY_ROUTER_API_KEY", latest_key)
    bootstrap_api_key_from_env()

    with Session(auth_engine) as session:
        keys = {key.id: key for key in session.exec(select(ApiKey)).all()}

    assert keys["environment"].is_active is True
    assert keys["environment"].key_hash == hashlib.sha256(latest_key.encode()).hexdigest()
    assert keys["manual-collision"].is_active is False
    assert not any(key.is_active and key.key_hash == collision_hash for key in keys.values())


@pytest.mark.parametrize("invalid_key", ["short", "pr-short"])
def test_environment_api_key_bootstrap_rejects_unsafe_key_format(
    invalid_key: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_engine = create_engine(f"sqlite:///{tmp_path / 'invalid-environment-key.db'}")
    monkeypatch.setattr("db.session.engine", auth_engine)
    monkeypatch.setenv("PRIVACY_ROUTER_API_KEY", invalid_key)
    init_db()

    with pytest.raises(RuntimeError, match="PRIVACY_ROUTER_API_KEY"):
        bootstrap_api_key_from_env()

    with Session(auth_engine) as session:
        assert session.exec(select(ApiKey)).all() == []


def test_environment_api_key_bootstrap_is_disabled_when_unset(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_engine = create_engine(f"sqlite:///{tmp_path / 'no-environment-key.db'}")
    monkeypatch.setattr("db.session.engine", auth_engine)
    monkeypatch.delenv("PRIVACY_ROUTER_API_KEY", raising=False)
    init_db()

    bootstrap_api_key_from_env()

    with Session(auth_engine) as session:
        assert session.exec(select(ApiKey)).all() == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/settings"),
        ("POST", "/api/settings"),
        ("GET", "/api/providers"),
        ("GET", "/api/profiles"),
        ("POST", "/api/profiles/activate"),
        ("GET", "/api/v1/keys"),
        ("POST", "/api/v1/keys"),
        ("POST", "/api/v1/keys/bulk-delete"),
        ("POST", "/api/v1/keys/bulk-toggle"),
        ("PATCH", "/api/v1/keys/{key_id}"),
        ("DELETE", "/api/v1/keys/{key_id}"),
        ("POST", "/api/v1/keys/{key_id}/renew"),
        ("GET", "/api/v1/models"),
        ("POST", "/api/v1/models"),
        ("POST", "/api/v1/models/validate"),
        ("PATCH", "/api/v1/models/{model_record_id}"),
        ("POST", "/api/v1/models/{model_record_id}/activate"),
        ("DELETE", "/api/v1/models/{model_record_id}"),
        ("GET", "/api/v1/dashboard-data"),
        ("GET", "/api/v1/telemetry/retention"),
        ("GET", "/api/v1/telemetry/export"),
        ("POST", "/api/v1/telemetry/purge"),
    ],
)
def test_management_routes_require_admin_auth(method: str, path: str) -> None:
    dependencies = _route_dependencies(path, method)
    assert require_admin_auth in dependencies
    assert require_auth not in dependencies


def test_public_extraction_records_never_echo_raw_span_or_reasoning() -> None:
    secret = "SOURCE_SENTINEL_VALUE"
    reasoning = "Internal analysis containing SOURCE_SENTINEL_VALUE"
    records = [
        ExtractionRecord(
            category="INTERNAL_PROJECT_NAME",
            span=secret,
            confidence=0.93,
            start=8,
            end=8 + len(secret),
            is_required=Requiredness(value=True, reason=reasoning),
            reasoning=reasoning,
        )
    ]

    public = redact_extraction_records(records)

    assert public == [
        {
            "index": 0,
            "category": "INTERNAL_PROJECT_NAME",
            "span": "<redacted>",
            "confidence": 0.93,
            "is_required": {"value": True},
        }
    ]
    assert secret not in repr(public)
    assert reasoning not in repr(public)
