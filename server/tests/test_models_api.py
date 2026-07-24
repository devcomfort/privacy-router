"""Administrative model registry API contracts."""

from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from db import Model, Profile, ProfileAgent, Provider, Workspace, init_db
from server.api import app

_ADMIN_HEADERS: dict[str, str] = {}


def _client(tmp_path, monkeypatch) -> tuple[TestClient, object]:
    model_engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
    monkeypatch.setattr("db.session.engine", model_engine)
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("PRIVACY_ROUTER_MASTER_KEY", Fernet.generate_key().decode())
    init_db()
    with Session(model_engine) as session:
        session.add(
            Provider(
                id="openrouter",
                name="OpenRouter",
                api_base="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
            )
        )
        session.add(Workspace(id="default", name="Default", active_profile="default"))
        session.add(Profile(id="default", workspace_id="default", name="Default", is_active=True))
        session.commit()
    client = TestClient(app, base_url="https://testserver")
    login = client.post(
        "/api/admin/session",
        json={"password": "test-admin-password"},
    )
    assert login.status_code == 200
    _ADMIN_HEADERS.clear()
    _ADMIN_HEADERS["X-Privacy-Router-CSRF-Token"] = login.json()["csrf_token"]
    return client, model_engine


def _register(client: TestClient, model_id: str = "openrouter/example/model-a") -> dict[str, object]:
    response = client.post(
        "/api/v1/models",
        headers=_ADMIN_HEADERS,
        json={
            "model_id": model_id,
            "provider_id": "openrouter",
            "display_name": "Model A",
            "location": "external",
            "tier": "middle",
            "cost_per_1m_tokens": 0.25,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_validate_model_configuration_without_persisting(tmp_path, monkeypatch) -> None:
    client, model_engine = _client(tmp_path, monkeypatch)

    with client:
        response = client.post(
            "/api/v1/models/validate",
            headers=_ADMIN_HEADERS,
            json={
                "model_id": "openrouter/example/model-a",
                "provider_id": "openrouter",
                "location": "external",
                "tier": "middle",
                "cost_per_1m_tokens": 0.25,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "model_id": "openrouter/example/model-a",
        "provider_id": "openrouter",
        "location": "external",
        "tier": "middle",
        "api_base": "https://openrouter.ai/api/v1",
    }
    with Session(model_engine) as session:
        assert session.exec(select(Model)).all() == []


def test_validate_model_rejects_provider_prefix_mismatch(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    with client:
        response = client.post(
            "/api/v1/models/validate",
            headers=_ADMIN_HEADERS,
            json={
                "model_id": "anthropic/claude-sonnet",
                "provider_id": "openrouter",
                "location": "external",
                "tier": "large",
                "cost_per_1m_tokens": 3.0,
            },
        )

    assert response.status_code == 422
    assert "model_id prefix" in response.json()["detail"]


def test_update_model_metadata_is_immediately_visible(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    with client:
        created = _register(client)
        response = client.patch(
            f"/api/v1/models/{created['id']}",
            headers=_ADMIN_HEADERS,
            json={"display_name": "Model A Updated", "tier": "large", "cost_per_1m_tokens": 0.5},
        )
        listed = client.get("/api/v1/models", headers=_ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["display_name"] == "Model A Updated"
    assert response.json()["tier"] == "large"
    assert response.json()["cost_per_1m_tokens"] == 0.5
    assert listed.json() == [response.json()]


def test_deactivate_and_reactivate_unbound_model(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    with client:
        created = _register(client)
        deleted = client.delete(f"/api/v1/models/{created['id']}", headers=_ADMIN_HEADERS)
        active = client.get("/api/v1/models", headers=_ADMIN_HEADERS)
        all_models = client.get("/api/v1/models?include_inactive=true", headers=_ADMIN_HEADERS)
        rejected_selection = client.post(
            "/api/settings",
            headers=_ADMIN_HEADERS,
            json={"external": {"model": "openrouter/example/model-a"}},
        )
        activated = client.post(
            f"/api/v1/models/{created['id']}/activate",
            headers=_ADMIN_HEADERS,
        )

    assert deleted.status_code == 204
    assert active.json() == []
    assert all_models.json()[0]["is_active"] is False
    assert rejected_selection.status_code == 400
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True


def test_bound_model_cannot_be_deactivated_or_moved(tmp_path, monkeypatch) -> None:
    client, model_engine = _client(tmp_path, monkeypatch)

    with client:
        created = _register(client)
        with Session(model_engine) as session:
            session.add(
                ProfileAgent(
                    profile_id="default",
                    agent_name="external",
                    model_id="openrouter/example/model-a",
                )
            )
            session.commit()

        deleted = client.delete(f"/api/v1/models/{created['id']}", headers=_ADMIN_HEADERS)
        moved = client.patch(
            f"/api/v1/models/{created['id']}",
            headers=_ADMIN_HEADERS,
            json={
                "provider_id": "openrouter",
                "location": "local",
                "api_base_override": "http://localhost:8000/v1",
            },
        )

    assert deleted.status_code == 409
    assert "still bound" in deleted.json()["detail"]
    assert moved.status_code == 409
    assert "external" in moved.json()["detail"]


def test_new_model_can_be_selected_without_process_restart(tmp_path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    model_id = "openrouter/example/model-a"

    with client:
        warmed = client.get("/api/settings", headers=_ADMIN_HEADERS)
        assert warmed.status_code == 200
        _register(client, model_id)
        selected = client.post(
            "/api/settings",
            headers=_ADMIN_HEADERS,
            json={"external": {"model": model_id}},
        )
        refreshed = client.get("/api/settings", headers=_ADMIN_HEADERS)

    assert selected.status_code == 200
    assert refreshed.status_code == 200
    assert refreshed.json()["external"]["model"] == model_id
    assert any(model["model_id"] == model_id for model in refreshed.json()["models"])
