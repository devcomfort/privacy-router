"""Tests for route-immutable adapter retries and safe failures."""

from __future__ import annotations

import logging

import pytest

from agents import (
    PrivacyRouteFailure,
    RouteResult,
    execute_fixed_route,
    execute_fixed_stream,
    public_error_fields,
)


def _route(endpoint: str = "local_api") -> RouteResult:
    return RouteResult(endpoint=endpoint, requires_masking=False, description="test")


def test_retries_same_invocation_three_times_without_payload_rebuild(caplog):
    payload = [{"role": "user", "content": "PAYLOAD_SENTINEL"}]
    seen: list[object] = []
    delays: list[float] = []

    def invoke() -> str:
        seen.append(payload)
        if len(seen) < 3:
            raise TimeoutError("PAYLOAD_SENTINEL must never be logged")
        return "ok"

    with caplog.at_level(logging.WARNING):
        result = execute_fixed_route(_route(), invoke, request_id="req-local", sleep=delays.append)

    assert result == "ok"
    assert seen == [payload, payload, payload]
    assert all(item is payload for item in seen)
    assert delays == [1.0, 2.0]
    assert [record.message for record in caplog.records] == [
        "privacy_route_retry",
        "privacy_route_retry",
    ]
    assert [(record.route, record.attempt, record.reason) for record in caplog.records] == [
        ("local_api", 2, "timeout"),
        ("local_api", 3, "timeout"),
    ]
    assert "PAYLOAD_SENTINEL" not in caplog.text


def test_transient_failure_exhaustion_returns_safe_route_failure(caplog):
    calls = 0

    def invoke() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("PAYLOAD_SENTINEL")

    with caplog.at_level(logging.WARNING), pytest.raises(PrivacyRouteFailure) as raised:
        execute_fixed_route(
            _route("external_api"),
            invoke,
            request_id="req-external",
            sleep=lambda _: None,
        )

    failure = raised.value
    assert calls == 3
    assert (
        failure.route,
        failure.reason,
        failure.retryable,
        failure.attempts,
        failure.status_code,
    ) == ("external_api", "timeout", True, 3, 503)
    assert public_error_fields(failure, "req-external") == {
        "code": "privacy_route_unavailable",
        "reason": "timeout",
        "message": "선택된 개인정보 보호 처리 경로가 3회 시도 후 응답하지 않았습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "retryable": True,
        "attempts": 3,
        "request_id": "req-external",
    }
    assert caplog.records[-1].message == "privacy_route_failed"
    assert caplog.records[-1].route == "external_api"
    assert "PAYLOAD_SENTINEL" not in caplog.text


def test_non_retryable_adapter_failure_stops_after_one_call():
    calls = 0

    def invoke() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("invalid backend response")

    with pytest.raises(PrivacyRouteFailure) as raised:
        execute_fixed_route(_route(), invoke, request_id="req-once", sleep=lambda _: None)

    assert calls == 1
    assert (
        raised.value.reason,
        raised.value.retryable,
        raised.value.attempts,
        raised.value.status_code,
    ) == ("adapter_error", False, 1, 502)


def test_stream_retries_before_first_backend_item_only():
    attempts = 0

    def open_stream():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("not emitted")
        return iter(["first", "last"])

    assert list(execute_fixed_stream(_route(), open_stream, request_id="req-stream", sleep=lambda _: None)) == [
        "first",
        "last",
    ]
    assert attempts == 3


def test_stream_does_not_retry_after_first_item():
    attempts = 0

    def open_stream():
        nonlocal attempts
        attempts += 1

        def parts():
            yield "first"
            raise TimeoutError("after output")

        return parts()

    stream = execute_fixed_stream(_route(), open_stream, request_id="req-stream", sleep=lambda _: None)
    assert next(stream) == "first"
    with pytest.raises(PrivacyRouteFailure) as raised:
        next(stream)
    assert attempts == 1
    assert (
        raised.value.reason,
        raised.value.retryable,
        raised.value.attempts,
    ) == ("timeout", False, 1)
