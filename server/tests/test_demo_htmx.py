from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.api import app, require_auth
from server.api.routes.demo import DEMO_CASES


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        return None


@pytest.fixture
def demo_runtime(monkeypatch: pytest.MonkeyPatch):
    runtime = __import__("server.runtime", fromlist=["set_runtime_mode"])
    previous = runtime.get_runtime_mode()
    monkeypatch.setitem(app.dependency_overrides, require_auth, lambda: "demo-client")
    runtime.set_runtime_mode("dev")
    try:
        yield runtime
    finally:
        runtime.set_runtime_mode(previous)
        app.dependency_overrides.pop(require_auth, None)


def test_demo_page_is_htmx():
    response = TestClient(app).get("/demo")

    assert response.status_code == 200
    assert 'src="/demo-assets/htmx.min.js"' in response.text
    assert 'hx-post="/api/demo/router"' in response.text
    assert 'hx-post="/api/demo/run-all"' in response.text
    assert 'hx-target="#key-status"' in response.text
    assert 'id="key-status"' in response.text


def test_htmx_asset_is_served_locally():
    response = TestClient(app).get("/demo-assets/htmx.min.js")

    assert response.status_code == 200
    assert "htmx" in response.text[:500]


def test_demo_key_is_issued_to_loopback_dev_browser(
    demo_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    monkeypatch.setattr("server.api.routes.demo.get_session", lambda: session)

    response = TestClient(app, client=("127.0.0.1", 50000)).post("/api/demo/key", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'data-demo-api-key="pr-' in response.text
    assert len(session.added) == 1
    assert session.commits == 1


def test_demo_key_rejects_non_loopback_peer(demo_runtime):
    response = TestClient(app, client=("192.168.0.19", 50000)).post("/api/demo/key")

    assert response.status_code == 403


def _fake_pipeline(policy_action: str = "allow") -> SimpleNamespace:
    return SimpleNamespace(
        sensitivity=SimpleNamespace(is_sensitive=policy_action != "allow"),
        judgment=SimpleNamespace(policy_action=policy_action, strategy="demo", rationale="demo"),
        route=SimpleNamespace(endpoint="external_api", requires_masking=policy_action == "selective_mask"),
        records=[],
    )


def test_router_endpoint_returns_htmx_fragment(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    class FakeRouter:
        def process(self, text: str) -> SimpleNamespace:
            assert text == "demo input"
            return _fake_pipeline()

    monkeypatch.setattr("server.api.routes.demo.PrivacyRouter", FakeRouter)

    response = TestClient(app).post(
        "/api/demo/router",
        json={"text": "demo input"},
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert "external_api" in response.text
    assert "allow" in response.text


def test_router_endpoint_accepts_htmx_form_body(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    class FakeRouter:
        def process(self, text: str) -> SimpleNamespace:
            assert text == "form input"
            return _fake_pipeline()

    monkeypatch.setattr("server.api.routes.demo.PrivacyRouter", FakeRouter)

    response = TestClient(app).post(
        "/api/demo/router",
        data={"text": "form input"},
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert "external_api" in response.text


def test_run_all_reuses_one_router_instance(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    instances = 0
    calls: list[str] = []

    class FakeRouter:
        def __init__(self) -> None:
            nonlocal instances
            instances += 1

        def process(self, text: str) -> SimpleNamespace:
            calls.append(text)
            return _fake_pipeline()

    monkeypatch.setattr("server.api.routes.demo.PrivacyRouter", FakeRouter)

    response = TestClient(app).post(
        "/api/demo/run-all",
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert instances == 1
    assert len(calls) >= 3
    assert "Run all demos" not in response.text


def test_router_failure_returns_safe_htmx_error_fragment(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    class BrokenRouter:
        def process(self, text: str) -> SimpleNamespace:
            raise RuntimeError("provider secret must not leak")

    monkeypatch.setattr("server.api.routes.demo.PrivacyRouter", BrokenRouter)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/demo/router",
        data={"text": "demo input"},
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 503
    assert "Local router unavailable" in response.text
    assert "provider secret" not in response.text


def test_run_all_reports_each_failed_case_without_aborting(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    class BrokenRouter:
        def process(self, text: str) -> SimpleNamespace:
            raise RuntimeError("local model unavailable")

    monkeypatch.setattr("server.api.routes.demo.PrivacyRouter", BrokenRouter)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/demo/run-all",
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert len(DEMO_CASES) == 8
    assert response.text.count('class="demo-card"') == len(DEMO_CASES)
    assert response.text.count("Local router unavailable") == len(DEMO_CASES)
