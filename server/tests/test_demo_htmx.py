from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.extractor import ExtractionRecord, Requiredness
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
    assert 'id="demo-results"' in response.text
    assert "setLinked" in response.text
    assert "focusin" in response.text
    assert "run-all)(?:\\/|$)" in response.text


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


def test_demo_key_is_issued_to_non_loopback_dev_browser(
    demo_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    monkeypatch.setattr("server.api.routes.demo.get_session", lambda: session)

    response = TestClient(app, client=("100.69.181.62", 50000)).post("/api/demo/key")

    assert response.status_code == 200
    assert 'data-demo-api-key="pr-' in response.text
    assert len(session.added) == 1
    assert session.commits == 1


def test_demo_key_remains_disabled_in_serve_mode(demo_runtime):
    demo_runtime.set_runtime_mode("serve")

    response = TestClient(app, client=("100.69.181.62", 50000)).post("/api/demo/key")

    assert response.status_code == 404


def _fake_pipeline(policy_action: str = "allow") -> SimpleNamespace:
    return SimpleNamespace(
        sensitivity=SimpleNamespace(is_sensitive=policy_action != "allow"),
        judgment=SimpleNamespace(policy_action=policy_action, strategy="demo", rationale="demo"),
        route=SimpleNamespace(endpoint="external_api", requires_masking=policy_action == "selective_mask"),
        records=[],
    )


def _pipeline_with_maskable_record(text: str) -> SimpleNamespace:
    record = ExtractionRecord(
        category="EMAIL_ADDRESS",
        span=text[3:28],
        confidence=0.95,
        start=3,
        end=28,
        is_required=Requiredness(value=False, reason="주소를 가려도 요청 의미 유지"),
    )
    return SimpleNamespace(
        sensitivity=SimpleNamespace(is_sensitive=True, rationale="테스트 탐지"),
        judgment=SimpleNamespace(policy_action="selective_mask", strategy="demo", rationale="마스킹 가능"),
        route=SimpleNamespace(endpoint="external_api", requires_masking=True),
        records=[record],
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


def test_run_all_returns_initial_payload_shell(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    monkeypatch.setattr("server.api.routes.demo._submit_demo_batch", lambda batch_id: None, raising=False)

    response = TestClient(app).post(
        "/api/demo/run-all",
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert 'hx-get="/api/demo/run-all/' in response.text
    assert 'value="0"' in response.text
    assert response.text.count('class="demo-card') == len(DEMO_CASES)
    assert "synthetic@example.invalid" in response.text


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


def test_run_all_status_reports_terminal_failure_cases(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    monkeypatch.setattr("server.api.routes.demo._submit_demo_batch", lambda batch_id: None, raising=False)

    response = TestClient(app).post(
        "/api/demo/run-all",
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert response.text.count('class="demo-card') == len(DEMO_CASES)


def test_router_json_uses_requiredness_without_exposing_reason(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    text = "문의 synthetic@example.invalid"
    pipeline = _pipeline_with_maskable_record(text)
    monkeypatch.setattr(
        "server.api.routes.demo.PrivacyRouter",
        lambda: SimpleNamespace(process=lambda value: pipeline),
    )

    response = TestClient(app).post(
        "/api/demo/router",
        json={"text": text},
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert text.split(" ", 1)[1] not in response.text
    assert response.json()["records"][0]["is_required"] == {"value": False}
    assert "주소를 가려도 요청 의미 유지" not in response.text


def test_router_htmx_links_maskable_span_to_record(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    text = "문의 synthetic@example.invalid"
    pipeline = _pipeline_with_maskable_record(text)
    monkeypatch.setattr(
        "server.api.routes.demo.PrivacyRouter",
        lambda: SimpleNamespace(process=lambda value: pipeline),
    )

    response = TestClient(app).post(
        "/api/demo/router",
        data={"text": text},
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert response.text.count('data-record-id="record-0"') == 2
    assert '<mark class="mask-span"' in response.text
    assert 'class="record-block' in response.text


def test_run_demo_batch_reuses_router_and_isolates_failure(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    from server.api.demo_jobs import DemoBatchStore
    from server.api.routes import demo as demo_route

    instances = 0

    class FlakyRouter:
        def __init__(self) -> None:
            nonlocal instances
            instances += 1

        def process(self, text: str) -> SimpleNamespace:
            if text == DEMO_CASES[0][1]:
                raise RuntimeError("local backend unavailable")
            return _fake_pipeline()

    store = DemoBatchStore(ttl_seconds=60)
    monkeypatch.setattr(demo_route, "_demo_batches", store)
    monkeypatch.setattr(demo_route, "PrivacyRouter", FlakyRouter)
    batch = store.create(DEMO_CASES)

    demo_route._run_demo_batch(batch.batch_id)

    snapshot = store.snapshot(batch.batch_id)
    assert snapshot is not None
    assert snapshot.status == "failed"
    assert snapshot.completed == len(DEMO_CASES)
    assert snapshot.cases[0].status == "failed"
    assert snapshot.cases[1].status == "completed"
    assert instances == 1


def test_run_all_json_returns_only_batch_metadata(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    monkeypatch.setattr("server.api.routes.demo._submit_demo_batch", lambda batch_id: None)

    response = TestClient(app).post(
        "/api/demo/run-all",
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert response.json()["case_count"] == len(DEMO_CASES)
    assert response.json()["status"] == "queued"
    assert "synthetic@example.invalid" not in response.text


def test_run_all_status_fragment_stops_polling_after_failure(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    from server.api.demo_jobs import DemoBatchStore
    from server.api.routes import demo as demo_route

    store = DemoBatchStore(ttl_seconds=60)
    monkeypatch.setattr(demo_route, "_demo_batches", store)
    batch = store.create(DEMO_CASES)
    for index, (_name, _text) in enumerate(DEMO_CASES):
        assert store.mark_running(batch.batch_id, index) is True
        store.finish_case(
            batch.batch_id,
            index,
            "failed" if index == 0 else "completed",
            {"is_sensitive": None, "policy_action": "unavailable", "route": "blocked", "record_count": 0},
        )

    response = TestClient(app).get(
        f"/api/demo/run-all/{batch.batch_id}",
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert "completed with failures" in response.text
    assert "hx-get=" not in response.text
    assert "synthetic@example.invalid" in response.text


def test_failed_batch_card_shows_explicit_safe_message(monkeypatch: pytest.MonkeyPatch, demo_runtime):
    from server.api.demo_jobs import DemoBatchStore
    from server.api.routes import demo as demo_route

    store = DemoBatchStore(ttl_seconds=60)
    monkeypatch.setattr(demo_route, "_demo_batches", store)
    batch = store.create(DEMO_CASES)
    for index, (_name, _text) in enumerate(DEMO_CASES):
        assert store.mark_running(batch.batch_id, index) is True
        status = "failed" if index == 0 else "completed"
        result = {
            "is_sensitive": None,
            "policy_action": "unavailable" if status == "failed" else "allow",
            "route": "blocked" if status == "failed" else "external_api",
            "record_count": 0,
            "rationale": "Local router unavailable. Start the configured local model and retry.",
        }
        store.finish_case(batch.batch_id, index, status, result)

    response = TestClient(app).get(
        f"/api/demo/run-all/{batch.batch_id}",
        headers={"HX-Request": "true", "Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    assert "Failed" in response.text
    assert "Local router unavailable" in response.text


def test_failed_batch_card_without_result_uses_safe_message():
    from server.api.routes.demo import _batch_card

    card = _batch_card(
        SimpleNamespace(
            name="failed-case",
            status="failed",
            text="",
            result=None,
        )
    )

    assert "Failed" in card
    assert "Local router unavailable" in card
