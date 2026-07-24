"""Administrative telemetry retention and export API contracts."""

from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from server.api import app

_ADMIN_HEADERS: dict[str, str] = {}


def _configure_auth(monkeypatch) -> None:
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("PRIVACY_ROUTER_MASTER_KEY", Fernet.generate_key().decode())


def _client(monkeypatch) -> TestClient:
    _configure_auth(monkeypatch)
    client = TestClient(app, base_url="https://testserver")
    login = client.post(
        "/api/admin/session",
        json={"password": "test-admin-password"},
    )
    assert login.status_code == 200
    _ADMIN_HEADERS.clear()
    _ADMIN_HEADERS["X-Privacy-Router-CSRF-Token"] = login.json()["csrf_token"]
    return client


def test_retention_policy_is_admin_only_and_redacted(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    with TestClient(app, base_url="https://testserver") as unauthenticated:
        assert unauthenticated.get("/api/v1/telemetry/retention").status_code == 401
    with _client(monkeypatch) as client:
        response = client.get("/api/v1/telemetry/retention", headers=_ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "raw_ttl_hours": 24,
        "automatic_purge_interval_seconds": 3600,
        "export_privacy_level": "redacted",
        "encrypted_payloads_exported": False,
    }


def test_json_export_never_exposes_encrypted_payload_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.api.routes.telemetry.export_request_telemetry",
        lambda **_: {
            "schema_version": "1.0",
            "privacy_level": "redacted",
            "exported_at": "2026-07-19T00:00:00+00:00",
            "requests": [{"id": "req-1", "input_redacted": {"input": "[REDACTED]"}}],
        },
    )
    with _client(monkeypatch) as client:
        response = client.get("/api/v1/telemetry/export?format=json", headers=_ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["privacy_level"] == "redacted"
    assert "attachment;" in response.headers["content-disposition"]
    assert "input_encrypted" not in response.text


def test_dashboard_data_uses_redacted_telemetry_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def export(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "1.0",
            "privacy_level": "redacted",
            "exported_at": "2026-07-19T00:00:00+00:00",
            "requests": [
                {
                    "id": "req-1",
                    "input_redacted": {"input": "[REDACTED]"},
                }
            ],
        }

    monkeypatch.setattr("telemetry.export_request_telemetry", export)
    _configure_auth(monkeypatch)
    with TestClient(app, base_url="https://testserver") as unauthenticated:
        assert unauthenticated.get("/api/v1/dashboard-data").status_code == 401
    with _client(monkeypatch) as client:
        response = client.get("/api/v1/dashboard-data", headers=_ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["privacy_level"] == "redacted"
    assert response.json()["requests"][0]["input_redacted"] == {"input": "[REDACTED]"}
    assert captured == {"limit": 500}
    assert "input_encrypted" not in response.text
    assert '"span"' not in response.text


def test_csv_export_flattens_safe_usage(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.api.routes.telemetry.export_request_telemetry",
        lambda **_: {
            "requests": [
                {
                    "id": "req-1",
                    "endpoint": "responses",
                    "input_redacted": {"input": "[REDACTED]"},
                    "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
                }
            ]
        },
    )
    with _client(monkeypatch) as client:
        response = client.get("/api/v1/telemetry/export?format=csv", headers=_ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "req-1,responses" in response.text
    assert "[REDACTED]" in response.text


def test_all_scope_purge_requires_confirmation(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.post(
            "/api/v1/telemetry/purge",
            headers=_ADMIN_HEADERS,
            json={"scope": "all"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "confirm=true is required when scope is 'all'"


def test_export_accepts_mixed_naive_and_offset_bounds(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.api.routes.telemetry.export_request_telemetry",
        lambda **_: {"privacy_level": "redacted", "requests": []},
    )
    with _client(monkeypatch) as client:
        response = client.get(
            "/api/v1/telemetry/export?since=2026-07-19T00:00:00&until=2026-07-19T09:00:00%2B09:00",
            headers=_ADMIN_HEADERS,
        )

    assert response.status_code == 200


def test_confirmed_purge_delegates_explicit_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def purge(**kwargs):
        captured.update(kwargs)
        return {"request_traces": 3, "model_invocations": 5}

    monkeypatch.setattr("server.api.routes.telemetry.purge_request_telemetry", purge)
    with _client(monkeypatch) as client:
        response = client.post(
            "/api/v1/telemetry/purge",
            headers=_ADMIN_HEADERS,
            json={"scope": "all", "confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["deleted"] == {"request_traces": 3, "model_invocations": 5}
    assert captured == {"scope": "all", "before": None}
