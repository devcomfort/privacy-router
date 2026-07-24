"""Request telemetry and LiteLLM callback regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlmodel import Session, create_engine, select

from agents import decrypt_field, encrypt_field
from db import ModelInvocation, RequestTrace, init_db
from telemetry import (
    LiteLLMUsageCallback,
    activate_request_trace,
    annotate_request_trace,
    build_litellm_metadata,
    export_request_telemetry,
    finish_request_trace,
    purge_request_telemetry,
    start_request_trace,
)


def _usage_response(prompt_tokens: int = 13, completion_tokens: int = 8):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(usage=usage, _hidden_params={"response_cost": 0.0012})


def test_callback_persists_metadata_after_request_context_closes(tmp_path, monkeypatch):
    """Callback correlation comes from LiteLLM metadata, not live ContextVar state."""
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'telemetry.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()

    trace = start_request_trace(
        request_id="req-1",
        endpoint="chat_completions",
        input_encrypted=encrypt_field("민감한 원문"),
    )
    with activate_request_trace(trace):
        metadata = build_litellm_metadata("extractor")

    started = datetime.now(UTC)
    ended = started + timedelta(milliseconds=125)
    callback = LiteLLMUsageCallback()
    callback.log_success_event(
        {
            "model": "openrouter/google/gemma-4-26b-it",
            "litellm_params": {"metadata": metadata},
        },
        _usage_response(),
        started,
        ended,
    )

    with Session(telemetry_engine) as session:
        invocation = session.exec(select(ModelInvocation)).one()
        request_trace = session.get(RequestTrace, "req-1")

    assert invocation.request_id == "req-1"
    assert invocation.component == "extractor"
    assert invocation.model == "openrouter/google/gemma-4-26b-it"
    assert invocation.provider == "openrouter"
    assert invocation.prompt_tokens == 13
    assert invocation.completion_tokens == 8
    assert invocation.total_tokens == 21
    assert invocation.cost_usd == 0.0012
    assert invocation.latency_ms == 125
    assert invocation.success is True
    assert request_trace is not None
    assert "민감한 원문" not in request_trace.input_encrypted
    assert decrypt_field(request_trace.input_encrypted) == "민감한 원문"


def test_callback_ignores_calls_without_privacy_router_metadata(tmp_path, monkeypatch):
    """Unrelated process-wide LiteLLM calls must not create orphan rows."""
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'untraced.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()

    LiteLLMUsageCallback().log_success_event(
        {"model": "openrouter/example", "litellm_params": {}},
        _usage_response(),
        datetime.now(UTC),
        datetime.now(UTC),
    )

    with Session(telemetry_engine) as session:
        assert session.exec(select(ModelInvocation)).all() == []


def test_callback_rejects_late_invocation_for_expired_trace(tmp_path, monkeypatch):
    """A delayed callback cannot recreate telemetry after its trace expires."""
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'expired.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()

    trace = start_request_trace(
        request_id="req-expired",
        endpoint="responses",
        input_encrypted=encrypt_field("expired"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with activate_request_trace(trace):
        metadata = build_litellm_metadata("generator")

    LiteLLMUsageCallback().log_success_event(
        {"model": "openrouter/example", "litellm_params": {"metadata": metadata}},
        _usage_response(),
        datetime.now(UTC),
        datetime.now(UTC),
    )

    with Session(telemetry_engine) as session:
        assert session.exec(select(ModelInvocation)).all() == []


def test_finish_request_trace_records_route_decision_and_latency(tmp_path, monkeypatch):
    """Request-level telemetry stores encrypted evidence and safe aggregates."""
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'request.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()

    trace = start_request_trace(
        request_id="req-2",
        endpoint="responses",
        input_encrypted=encrypt_field("original"),
    )
    finish_request_trace(
        trace,
        status_code=200,
        is_sensitive=True,
        records_count=2,
        policy_action="selective_mask",
        route="external_api",
        model_used="openrouter/model",
        extraction_encrypted=encrypt_field('[{"category":"PERSONAL_EMAIL"}]'),
        judgment_encrypted=encrypt_field('{"policy_action":"selective_mask"}'),
    )

    with Session(telemetry_engine) as session:
        stored = session.get(RequestTrace, "req-2")

    assert stored is not None
    assert stored.status == "completed"
    assert stored.status_code == 200
    assert stored.is_sensitive is True
    assert stored.records_count == 2
    assert stored.policy_action == "selective_mask"
    assert stored.route == "external_api"
    assert stored.model_used == "openrouter/model"
    assert stored.latency_ms >= 0
    assert decrypt_field(stored.extraction_encrypted or "") == '[{"category":"PERSONAL_EMAIL"}]'


def test_active_trace_annotations_are_applied_when_request_finishes(tmp_path, monkeypatch):
    """Route code can attach policy evidence before an ASGI boundary finalizes it."""
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'annotated.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()
    trace = start_request_trace(
        request_id="req-annotated",
        endpoint="chat_completions",
        input_encrypted=encrypt_field("original"),
    )

    with activate_request_trace(trace):
        annotate_request_trace(
            is_sensitive=True,
            records_count=3,
            policy_action="block",
            route="local_api",
            model_used="openai/local",
        )
    finish_request_trace(trace, status_code=200)

    with Session(telemetry_engine) as session:
        stored = session.get(RequestTrace, "req-annotated")

    assert stored is not None
    assert stored.is_sensitive is True
    assert stored.records_count == 3
    assert stored.policy_action == "block"
    assert stored.route == "local_api"
    assert stored.model_used == "openai/local"


def test_purge_request_telemetry_deletes_expired_trace_and_invocations(tmp_path, monkeypatch):
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'purge.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()
    now = datetime.now(UTC).replace(tzinfo=None)

    with Session(telemetry_engine) as session:
        session.add(
            RequestTrace(
                id="expired",
                endpoint="responses",
                input_encrypted=encrypt_field("expired secret"),
                input_redacted='{"input":"[REDACTED]"}',
                expires_at=now - timedelta(seconds=1),
            )
        )
        session.add(
            RequestTrace(
                id="live",
                endpoint="responses",
                input_encrypted=encrypt_field("live secret"),
                input_redacted='{"input":"[REDACTED]"}',
                expires_at=now + timedelta(hours=1),
            )
        )
        session.add(ModelInvocation(id="expired-call", request_id="expired", component="generator", model="m"))
        session.add(ModelInvocation(id="live-call", request_id="live", component="generator", model="m"))
        session.commit()

    result = purge_request_telemetry(scope="expired", now=now)

    assert result == {"request_traces": 1, "model_invocations": 1}
    with Session(telemetry_engine) as session:
        assert session.get(RequestTrace, "expired") is None
        assert session.get(ModelInvocation, "expired-call") is None
        assert session.get(RequestTrace, "live") is not None
        assert session.get(ModelInvocation, "live-call") is not None


def test_export_request_telemetry_is_redacted_and_aggregates_invocations(tmp_path, monkeypatch):
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'export.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()
    now = datetime.now(UTC).replace(tzinfo=None)

    with Session(telemetry_engine) as session:
        session.add(
            RequestTrace(
                id="req-export",
                endpoint="chat_completions",
                input_encrypted=encrypt_field("private input"),
                input_redacted='{"messages":[{"content":"[REDACTED]","role":"[REDACTED]"}]}',
                extraction_encrypted=encrypt_field("private extraction"),
                is_sensitive=True,
                records_count=1,
                policy_action="selective_mask",
                route="external_api",
                model_used="openrouter/example",
                latency_ms=18.5,
                status="completed",
                status_code=200,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        session.add(
            ModelInvocation(
                id="call-export",
                request_id="req-export",
                component="generator",
                model="openrouter/example",
                provider="openrouter",
                prompt_tokens=12,
                completion_tokens=5,
                total_tokens=17,
                cost_usd=0.002,
                latency_ms=11.0,
            )
        )
        session.commit()

    exported = export_request_telemetry()
    serialized = repr(exported)

    assert exported["privacy_level"] == "redacted"
    assert exported["requests"][0]["input_redacted"] == {"messages": [{"content": "[REDACTED]", "role": "[REDACTED]"}]}
    assert exported["requests"][0]["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
        "cost_usd": 0.002,
        "model_calls": 1,
    }
    assert exported["requests"][0]["created_at"].endswith("+00:00")
    assert exported["requests"][0]["expires_at"].endswith("+00:00")
    assert exported["requests"][0]["invocations"][0]["created_at"].endswith("+00:00")
    assert "private input" not in serialized
    assert "private extraction" not in serialized
    assert "input_encrypted" not in serialized


def test_export_normalizes_offset_filters_to_naive_utc(tmp_path, monkeypatch):
    telemetry_engine = create_engine(f"sqlite:///{tmp_path / 'offset.db'}")
    monkeypatch.setattr("db.session.engine", telemetry_engine)
    init_db()
    with Session(telemetry_engine) as session:
        session.add(
            RequestTrace(
                id="inside-window",
                endpoint="responses",
                input_encrypted=encrypt_field("secret"),
                created_at=datetime(2026, 7, 19, 0, 30),
                expires_at=datetime(2026, 7, 20, 0, 30),
            )
        )
        session.add(
            RequestTrace(
                id="before-window",
                endpoint="responses",
                input_encrypted=encrypt_field("secret"),
                created_at=datetime(2026, 7, 18, 23, 59),
                expires_at=datetime(2026, 7, 20, 0, 30),
            )
        )
        session.commit()

    exported = export_request_telemetry(since=datetime(2026, 7, 19, 9, 0, tzinfo=timezone(timedelta(hours=9))))

    assert [request["id"] for request in exported["requests"]] == ["inside-window"]
