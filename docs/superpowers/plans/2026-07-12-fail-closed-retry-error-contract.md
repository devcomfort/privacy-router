# Fail-Closed Route Retry and Error Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the route selected for every Privacy Router request, retry only the same adapter up to three total attempts, and return raw-free, explainable errors when processing cannot safely complete.

**Architecture:** A pure `agents.router.execution` module owns the bounded retry state machine, safe failure type, structured event logging, and public error fields. The chat-completions and OpenResponses handlers each prepare their route payload exactly once, call this shared executor, and only translate the resulting safe failure to their protocol-specific response or SSE event. The Router remains the policy decision boundary; the execution module cannot select or alter a route.

**Tech Stack:** Python 3.13, FastAPI, LiteLLM exception types, Pydantic/SQLModel project conventions, pytest, FastAPI TestClient, `caplog`.

## Global Constraints

- A `RouteResult.endpoint` of `local_api` or `external_api` is immutable after policy selection; local-to-external and external-to-local fallback are forbidden.
- `max_attempts = 3`: one initial call and at most two retries, after 1 second and 2 seconds respectively.
- Retry only `TimeoutError`, `ConnectionError`, `litellm.Timeout`, `litellm.CompletionTimeout`, `litellm.APIConnectionError`, and `litellm.ServiceUnavailableError`.
- Do not retry extraction, structured-output parsing, schema or route validation, masking, hydration, rate-limit, invalid-request, or invalid-model-response failures.
- Retries reuse the exact prepared payload object. They never invoke Extractor, Judge, Router policy selection, or Masker a second time.
- Server logs and client/SSE errors must exclude prompts, spans, placeholder restoration values, API keys, provider URLs, `str(exception)`, and `exc_info`.
- Expose only stable `code`, `reason`, `message`, `retryable`, `attempts`, and `request_id` fields to clients.
- Streaming may retry only before the first backend item reaches the route handler. After any item is yielded, emit one safe failure event and stop.
- Use package barrels for new imports. Do not add inline imports.
- Do not add configuration, persistence, a worker, a queue, or fallback models for retry behavior.
- Keep the user’s existing uncommitted changes untouched. Do not make task-level commits; create one squashed feature commit only after the focused suite passes.

---

## File Structure

- Create: `agents/router/execution.py` — route-immutable sync and stream retry state machine, safe failure data, raw-free structured logging, and shared public-error fields.
- Modify: `agents/router/__init__.py` and `agents/__init__.py` — barrel-export the execution API through both supported package boundaries.
- Create: `agents/router/tests/test_execution.py` — pure no-network tests for retry counts, payload identity, backoff, failure classification, logs, and stream cutoff.
- Modify: `server/api/__init__.py` — barrel-export `StreamingHydrator` so route handlers need no new submodule import.
- Modify: `server/api/routes/proxy.py` — prepare payload once from `PipelineResult.records`; remove local-to-external fallback; use the shared executor and safe errors for sync and SSE paths; fail closed on hydration failure.
- Modify: `server/api/routes/responses.py` — apply the same selected-route execution and safe failure mapping to OpenResponses sync and SSE paths; fail closed on hydration failure.
- Create: `server/tests/test_fail_closed_retry.py` — mocked FastAPI endpoint regression tests for chat and OpenResponses route immutability, error shape, raw-free errors, and streaming behavior.

## Task 1: Shared Fixed-Route Execution Boundary

- Create: `agents/router/execution.py`
- Modify: `agents/router/__init__.py`, `agents/__init__.py`
- Test: `agents/router/tests/test_execution.py`

**Interfaces:**
- Consumes: `agents.router.RouteResult`, an `invoke: Callable[[], T]`, a request ID, and an optional sleeper.
- Produces: `PrivacyRouteFailure`, `execute_fixed_route()`, `execute_fixed_stream()`, `log_privacy_failure()`, `privacy_failure()`, and `public_error_fields()` for both API handlers.

- [ ] **Step 1: Write the failing pure retry tests**

Create `agents/router/tests/test_execution.py` with deterministic fake callbacks. The test file must cover these exact contracts:

```python
import logging

import pytest

from agents.router import (
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
        assert execute_fixed_route(_route(), invoke, request_id="req-local", sleep=delays.append) == "ok"

    assert seen == [payload, payload, payload]
    assert all(item is payload for item in seen)
    assert delays == [1.0, 2.0]
    assert [record.message for record in caplog.records] == [
        "privacy_route_retry", "privacy_route_retry",
    ]
    assert [(record.route, record.attempt, record.reason) for record in caplog.records] == [
        ("local_api", 2, "timeout"),
        ("local_api", 3, "timeout"),
    ]
    assert "PAYLOAD_SENTINEL" not in caplog.text


def test_transient_failure_exhaustion_is_safe_and_logged(caplog):
    calls = 0

    def invoke() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("PAYLOAD_SENTINEL")

    with caplog.at_level(logging.WARNING), pytest.raises(PrivacyRouteFailure) as raised:
        execute_fixed_route(_route("external_api"), invoke, request_id="req-external", sleep=lambda _: None)

    failure = raised.value
    assert calls == 3
    assert (failure.route, failure.reason, failure.retryable, failure.attempts, failure.status_code) == (
        "external_api", "timeout", True, 3, 503,
    )
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
    assert (raised.value.reason, raised.value.retryable, raised.value.attempts, raised.value.status_code) == (
        "adapter_error", False, 1, 502,
    )


def test_stream_retries_before_first_backend_item_only():
    attempts = 0

    def open_stream():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("not emitted")
        return iter(["first", "last"])

    assert list(execute_fixed_stream(_route(), open_stream, request_id="req-stream", sleep=lambda _: None)) == ["first", "last"]
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
    assert (raised.value.reason, raised.value.retryable, raised.value.attempts) == ("timeout", False, 1)
```

- [ ] **Step 2: Run the new tests to verify failure**

Run:

```bash
python -m pytest agents/router/tests/test_execution.py -q
```

Expected: collection failure because `agents.router.execution` and its barrel exports do not yet exist.

- [ ] **Step 3: Implement the shared executor**

Create `agents/router/execution.py` with the following complete public surface. Use `raise failure from None` so the original exception is not chained into an accidental traceback or log.

```python
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Literal, TypeVar

import litellm

from .schemas import RouteResult

T = TypeVar("T")
RouteName = Literal["local_api", "external_api", "unresolved"]
FailureReason = Literal[
    "timeout",
    "connection",
    "service_unavailable",
    "adapter_error",
    "extraction_failed",
    "route_invariant_failed",
    "masking_failed",
    "hydration_failed",
]

MAX_ATTEMPTS = 3
_RETRY_DELAYS = (1.0, 2.0)
_ROUTABLE_ENDPOINTS = frozenset({"local_api", "external_api"})
_TRANSPORT_REASONS = frozenset({"timeout", "connection", "service_unavailable"})
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrivacyRouteFailure(Exception):
    route: RouteName
    reason: FailureReason
    retryable: bool
    attempts: int
    status_code: int


def public_error_fields(
    failure: PrivacyRouteFailure, request_id: str
) -> dict[str, object]:
    messages = {
        "timeout": "선택된 개인정보 보호 처리 경로가 일시적으로 응답하지 않았습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "connection": "선택된 개인정보 보호 처리 경로와 연결할 수 없습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "service_unavailable": "선택된 개인정보 보호 처리 경로를 일시적으로 사용할 수 없습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "adapter_error": "선택된 개인정보 보호 처리 경로가 요청을 처리하지 못했습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
        "extraction_failed": "개인정보 보호 분석을 안전하게 완료하지 못했습니다. 요청은 처리 경로로 전송되지 않았습니다.",
        "route_invariant_failed": "개인정보 보호 경로를 안전하게 확정하지 못했습니다. 요청은 처리 경로로 전송되지 않았습니다.",
        "masking_failed": "민감 정보를 안전하게 마스킹하지 못했습니다. 요청은 외부 처리 경로로 전송되지 않았습니다.",
        "hydration_failed": "응답을 안전하게 복원하지 못했습니다. 부분 응답은 반환되지 않았습니다.",
    }
    if failure.retryable and failure.attempts == MAX_ATTEMPTS:
        messages["timeout"] = "선택된 개인정보 보호 처리 경로가 3회 시도 후 응답하지 않았습니다. 요청은 다른 처리 경로로 전환되지 않았습니다."
    codes = {
        "adapter_error": "privacy_route_unavailable",
        "timeout": "privacy_route_unavailable",
        "connection": "privacy_route_unavailable",
        "service_unavailable": "privacy_route_unavailable",
        "extraction_failed": "privacy_analysis_failed",
        "route_invariant_failed": "privacy_route_rejected",
        "masking_failed": "privacy_contract_failed",
        "hydration_failed": "privacy_contract_failed",
    }
    return {
        "code": codes[failure.reason],
        "reason": failure.reason,
        "message": messages[failure.reason],
        "retryable": failure.retryable,
        "attempts": failure.attempts,
        "request_id": request_id,
    }


def privacy_failure(
    reason: Literal[
        "extraction_failed",
        "route_invariant_failed",
        "masking_failed",
        "hydration_failed",
    ],
) -> PrivacyRouteFailure:
    statuses = {
        "extraction_failed": 503,
        "route_invariant_failed": 409,
        "masking_failed": 502,
        "hydration_failed": 502,
    }
    return PrivacyRouteFailure("unresolved", reason, False, 1, statuses[reason])


def log_privacy_failure(failure: PrivacyRouteFailure, request_id: str) -> None:
    _LOGGER.error(
        "privacy_route_failed",
        extra={
            "request_id": request_id,
            "route": failure.route,
            "attempts": failure.attempts,
            "reason": failure.reason,
            "retryable": failure.retryable,
        },
    )


def _reason_for(error: BaseException) -> FailureReason:
    if isinstance(error, (TimeoutError, litellm.Timeout, litellm.CompletionTimeout)):
        return "timeout"
    if isinstance(error, (ConnectionError, litellm.APIConnectionError)):
        return "connection"
    if isinstance(error, litellm.ServiceUnavailableError):
        return "service_unavailable"
    return "adapter_error"


def _validate_route(
    route: RouteResult, request_id: str
) -> Literal["local_api", "external_api"]:
    if route.endpoint not in _ROUTABLE_ENDPOINTS:
        failure = privacy_failure("route_invariant_failed")
        log_privacy_failure(failure, request_id)
        raise failure
    return route.endpoint  # type: ignore[return-value]


def _handle_adapter_error(
    route: Literal["local_api", "external_api"],
    error: BaseException,
    attempt: int,
    request_id: str,
    sleep: Callable[[float], None],
    *,
    may_retry: bool,
) -> None:
    reason = _reason_for(error)
    is_transport_failure = reason in _TRANSPORT_REASONS
    if is_transport_failure and may_retry and attempt < MAX_ATTEMPTS:
        _LOGGER.warning(
            "privacy_route_retry",
            extra={
                "request_id": request_id,
                "route": route,
                "attempt": attempt + 1,
                "max_attempts": MAX_ATTEMPTS,
                "reason": reason,
            },
        )
        sleep(_RETRY_DELAYS[attempt - 1])
        return
    failure = PrivacyRouteFailure(
        route=route,
        reason=reason,
        retryable=is_transport_failure and may_retry,
        attempts=attempt,
        status_code=503 if is_transport_failure else 502,
    )
    log_privacy_failure(failure, request_id)
    raise failure from None


def execute_fixed_route(
    route: RouteResult,
    invoke: Callable[[], T],
    *,
    request_id: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    endpoint = _validate_route(route, request_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return invoke()
        except PrivacyRouteFailure:
            raise
        except Exception as error:
            _handle_adapter_error(
                endpoint, error, attempt, request_id, sleep, may_retry=True
            )
    raise AssertionError("retry loop must return or raise")


def execute_fixed_stream(
    route: RouteResult,
    open_stream: Callable[[], Iterable[T]],
    *,
    request_id: str,
    sleep: Callable[[float], None] = time.sleep,
) -> Generator[T, None, None]:
    endpoint = _validate_route(route, request_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            iterator = iter(open_stream())
            first = next(iterator)
        except StopIteration:
            return
        except PrivacyRouteFailure:
            raise
        except Exception as error:
            _handle_adapter_error(
                endpoint, error, attempt, request_id, sleep, may_retry=True
            )
            continue
        yield first
        try:
            yield from iterator
            return
        except PrivacyRouteFailure:
            raise
        except Exception as error:
            _handle_adapter_error(
                endpoint, error, attempt, request_id, sleep, may_retry=False
            )
    raise AssertionError("stream retry loop must return or raise")
```

Update `agents/router/__init__.py` to import `PrivacyRouteFailure`, `execute_fixed_route`, `execute_fixed_stream`, `log_privacy_failure`, `privacy_failure`, and `public_error_fields` from `.execution`, then add those six names to `__all__`. Update `agents/__init__.py` to re-export those same six names from `agents.router` and add them to its Router section in `__all__`. Update `server/api/__init__.py` to import `StreamingHydrator` from `.streaming` and add it to `__all__`.

- [ ] **Step 4: Run the executor tests to verify success**

Run:

```bash
python -m pytest agents/router/tests/test_execution.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Run existing Router tests for regression**

Run:

```bash
python -m pytest agents/router/tests/test_router.py -q
```

Expected: all mock-only Router tests pass; record any pre-existing real-LLM-dependent skip or failure separately rather than weakening assertions.

## Task 2: Make Chat Completions Fail Closed

**Files:**
- Modify: `server/api/routes/proxy.py`
- Test: `server/tests/test_fail_closed_retry.py`

**Interfaces:**
- Consumes: `PrivacyRouteFailure`, `execute_fixed_route`, `execute_fixed_stream`, `privacy_failure`, and `public_error_fields` from `agents.router`.
- Produces: chat JSON errors and chat SSE errors with the common public error fields; no local-to-external fallback.

- [ ] **Step 1: Write failing chat endpoint tests**

Create the chat portion of `server/tests/test_fail_closed_retry.py`. Follow the existing `server/tests/test_guardrail.py` pattern: override `require_auth`, use `TestClient(app)`, and patch route-module names, not library globals.

Add these deterministic helpers before the endpoint tests:

```python
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agents import PipelineResult, RouteResult
from server.api import app, require_auth


async def _mock_auth() -> str:
    return "test-provider"


app.dependency_overrides[require_auth] = _mock_auth
client = TestClient(app)


def _pipeline(endpoint: str, requires_masking: bool = False) -> PipelineResult:
    return SimpleNamespace(
        route=RouteResult(
            endpoint=endpoint,
            requires_masking=requires_masking,
            description="test route",
        ),
        sensitivity=SimpleNamespace(is_sensitive=requires_masking),
        judgment=SimpleNamespace(
            policy_action="block" if endpoint == "local_api" else "allow"
        ),
        records=[],
    )


def _completion(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ]
    )


def _delta(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


class CountingAdapter:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        failures: int = 0,
        stream_parts: list[object] | None = None,
    ) -> None:
        self.error = error
        self.failures = failures
        self.stream_parts = stream_parts
        self.calls: list[object] = []

    def resolve_backend_model(self, model: str) -> str:
        return model

    def format_response(self, response: object, content: str) -> dict[str, object]:
        return {
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        }

    def call(self, model: str, messages: object, *args: object, **kwargs: object) -> object:
        self.calls.append(messages)
        if len(self.calls) <= self.failures:
            assert self.error is not None
            raise self.error
        if kwargs.get("stream"):
            def parts():
                for part in self.stream_parts or [_delta("ok")]:
                    if isinstance(part, BaseException):
                        raise part
                    yield part
            return parts()
        return _completion()


def _config() -> SimpleNamespace:
    generation = SimpleNamespace(temperature=0.0, max_tokens=32)
    return SimpleNamespace(
        models=[SimpleNamespace(id="external-model")],
        generator=SimpleNamespace(model="external-model", config=generation),
        local=SimpleNamespace(model="local-model", config=generation),
    )


def _adapter_for(local: CountingAdapter, external: CountingAdapter):
    return lambda model: local if model == "local-model" else external


@contextmanager
def _chat_dependencies(
    *,
    route: str,
    local: CountingAdapter,
    external: CountingAdapter,
    requires_masking: bool = False,
    masker_hydrate_error: BaseException | None = None,
):
    router = MagicMock()
    router.process.return_value = _pipeline(route, requires_masking)
    masker = MagicMock()
    masker.mask.return_value = SimpleNamespace(
        masked_text="MASKED_REQUEST",
        contract=SimpleNamespace(placeholder_map={}),
    )
    masker.hydrate.side_effect = masker_hydrate_error
    with (
        patch("server.api.routes.proxy.PrivacyRouter", return_value=router),
        patch("server.api.routes.proxy.get_config", return_value=_config()),
        patch("server.api.routes.proxy.adapter_for", side_effect=_adapter_for(local, external)),
        patch("server.api.routes.proxy._resolve_api_base", return_value=None),
        patch("server.api.routes.proxy.ContractStore"),
        patch("server.api.routes.proxy.Masker", return_value=masker),
    ):
        yield


@contextmanager
def _responses_dependencies(
    *,
    route: str,
    local: CountingAdapter,
    external: CountingAdapter,
    requires_masking: bool = False,
    masker_hydrate_error: BaseException | None = None,
):
    router = MagicMock()
    router.process.return_value = _pipeline(route, requires_masking)
    masker = MagicMock()
    masker.mask.return_value = SimpleNamespace(
        masked_text="MASKED_REQUEST",
        contract=SimpleNamespace(placeholder_map={}),
    )
    masker.hydrate.side_effect = masker_hydrate_error
    with (
        patch("server.api.routes.responses.PrivacyRouter", return_value=router),
        patch("server.api.routes.responses.get_config", return_value=_config()),
        patch("server.api.routes.responses.adapter_for", side_effect=_adapter_for(local, external)),
        patch("server.api.routes.responses._resolve_api_base", return_value=None),
        patch("server.api.routes.responses.Masker", return_value=masker),
    ):
        yield


def _chat_request() -> dict[str, object]:
    return {
        "model": "privacy-router/external-model",
        "messages": [{"role": "user", "content": "test input"}],
        "max_tokens": 32,
    }


def _responses_request() -> dict[str, object]:
    return {"model": "privacy-router/external-model", "input": "test input"}
```

Add these exact tests:

```python
def test_chat_local_timeout_retries_only_local_and_returns_safe_503(caplog):
    local = CountingAdapter(error=TimeoutError("CHAT_SECRET_SENTINEL"), failures=3)
    external = CountingAdapter()
    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=_chat_request())
    body = response.json()["error"]
    assert response.status_code == 503
    assert len(local.calls) == 3
    assert external.calls == []
    assert body["code"] == "privacy_route_unavailable"
    assert body["reason"] == "timeout"
    assert body["attempts"] == 3
    assert body["retryable"] is True
    assert body["request_id"]
    assert "전환되지 않았습니다" in body["message"]
    assert "CHAT_SECRET_SENTINEL" not in response.text
    assert "CHAT_SECRET_SENTINEL" not in caplog.text


def test_chat_external_timeout_retries_only_external_with_same_payload():
    local = CountingAdapter()
    external = CountingAdapter(error=ConnectionError("unused"), failures=2)
    with _chat_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=_chat_request())
    assert response.status_code == 200
    assert local.calls == []
    assert len(external.calls) == 3
    assert external.calls[0] is external.calls[1] is external.calls[2]


def test_chat_hydration_failure_returns_safe_error_without_success_body():
    with _chat_dependencies(route="external_api", requires_masking=True, masker_hydrate_error=ValueError("HYDRATION_SENTINEL")):
        response = client.post("/v1/chat/completions", json=_chat_request())
    assert response.status_code == 502
    assert response.json()["error"]["reason"] == "hydration_failed"
    assert "choices" not in response.json()
    assert "HYDRATION_SENTINEL" not in response.text
```

- [ ] **Step 2: Run the chat tests to verify failure**

Run:

```bash
python -m pytest server/tests/test_fail_closed_retry.py -q -k chat
```

Expected: FAIL because the legacy handler falls through from `local_api` to `external_api`, exposes adapter error text, and ignores hydration errors.

- [ ] **Step 3: Refactor the chat route around one selected adapter and one prepared payload**

In `server/api/routes/proxy.py`:

1. Import `ContractStore`, `PrivacyRouteFailure`, `execute_fixed_route`, `execute_fixed_stream`, `log_privacy_failure`, `privacy_failure`, and `public_error_fields` from the `agents` barrel at module scope. Import `StreamingHydrator` from the `server.api` barrel at module scope. Remove the inline `ContractStore`, `hashlib`, debug-`sys`, and `StreamingHydrator` imports as part of the touched code; use existing top-level `hashlib`.
2. Create `_privacy_error_response(failure: PrivacyRouteFailure, request_id: str) -> JSONResponse`. It must call `public_error_fields(failure, request_id)` and return `JSONResponse(status_code=failure.status_code, content={"error": fields})`.
3. Generate `request_id = _make_chat_id()` before calling `PrivacyRouter().process()`. Wrap pipeline construction in `try/except Exception`; on failure create `failure = privacy_failure("extraction_failed")`, call `log_privacy_failure(failure, request_id)`, and return `_privacy_error_response(failure, request_id)`.
4. Delete lines that replace a local `RouteResult` with `external_api`. A `local_api` request remains local for sync and streaming calls.
5. Replace both second Extractor calls with `pipeline.records`. Build the local or external `forward_messages` once before execution. Do not call Extractor after `PrivacyRouter().process()` returns.
6. Select `(adapter, resolved_model, api_base, temperature, max_tokens)` once from `policy.endpoint`; preserve the currently chosen local model for `local_api` and requested backend model for `external_api`.
7. For non-streaming requests, create a zero-argument `invoke()` closure that captures that exact adapter/model/messages/kwargs. Call `execute_fixed_route(policy, invoke, request_id=request_id)`. Catch `PrivacyRouteFailure` and return `_privacy_error_response`.
8. For streaming requests, create an `open_stream()` closure with the same captured adapter/model/messages/kwargs and `stream=True`. Iterate `execute_fixed_stream(policy, open_stream, request_id=request_id)`. Catch `PrivacyRouteFailure`, emit one `data: {"error": <public_error_fields>}` event, then `data: [DONE]`, and return. Do not retry after any yielded backend part.
9. Replace every hydration `except: pass` in this endpoint with `privacy_failure("hydration_failed")`, safe failure logging, and either the JSON error or the single SSE failure event. Do not construct a partial chat success response.
10. Delete the three `DEBUG PROXY` prints and never interpolate a backend exception into an API response.

- [ ] **Step 4: Run chat tests to verify success**

Run:

```bash
python -m pytest server/tests/test_fail_closed_retry.py -q -k chat
```

Expected: every chat test passes. The local timeout test reports three local calls and zero external calls.

## Task 3: Apply the Same Contract to OpenResponses

**Files:**
- Modify: `server/api/routes/responses.py`
- Modify: `server/tests/test_fail_closed_retry.py`

**Interfaces:**
- Consumes: the Task 1 execution module and the same fake adapter helpers from the test file.
- Produces: OpenResponses JSON failures and `response.failed` SSE events with the common public error fields.

- [ ] **Step 1: Write failing OpenResponses tests**

Add these tests to `server/tests/test_fail_closed_retry.py` using the same fake `PipelineResult`, fake config, and `CountingAdapter`:

```python
def test_responses_local_timeout_retries_only_local_and_returns_safe_error(caplog):
    local = CountingAdapter(error=TimeoutError("RESPONSES_SECRET_SENTINEL"), failures=3)
    external = CountingAdapter()
    with _responses_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/responses", json=_responses_request())
    body = response.json()["error"]
    assert response.status_code == 503
    assert len(local.calls) == 3
    assert external.calls == []
    assert body["reason"] == "timeout"
    assert body["attempts"] == 3
    assert body["retryable"] is True
    assert body["request_id"] == response.json()["id"]
    assert "RESPONSES_SECRET_SENTINEL" not in response.text
    assert "RESPONSES_SECRET_SENTINEL" not in caplog.text


def test_responses_external_non_retryable_error_stops_after_one_attempt():
    local = CountingAdapter()
    external = CountingAdapter(error=ValueError("provider detail"), failures=1)
    with _responses_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/responses", json=_responses_request())
    assert response.status_code == 502
    assert local.calls == []
    assert len(external.calls) == 1
    assert response.json()["error"]["reason"] == "adapter_error"
    assert response.json()["error"]["retryable"] is False


def test_responses_stream_failure_after_first_item_does_not_retry():
    external = CountingAdapter(stream_parts=[_delta("first"), TimeoutError("late failure")])
    with _responses_dependencies(route="external_api", local=CountingAdapter(), external=external):
        response = client.post("/v1/responses", json={**_responses_request(), "stream": True})
    assert response.status_code == 200
    assert len(external.calls) == 1
    assert "event: response.output_text.delta" in response.text
    assert "event: response.failed" in response.text
    assert "late failure" not in response.text
    assert response.text.rstrip().endswith("data: [DONE]")
```

- [ ] **Step 2: Run the OpenResponses tests to verify failure**

Run:

```bash
python -m pytest server/tests/test_fail_closed_retry.py -q -k responses
```

Expected: FAIL because current errors include raw exception text, local calls do not retry, and the streaming route exposes the late exception.

- [ ] **Step 3: Refactor OpenResponses route execution**

In `server/api/routes/responses.py`:

1. Import `PrivacyRouteFailure`, `execute_fixed_route`, `execute_fixed_stream`, `log_privacy_failure`, `privacy_failure`, and `public_error_fields` through `agents` at module scope. Import `StreamingHydrator` from the `server.api` barrel. Add `_response_error_body(response_id, failure)` that preserves existing OpenResponses envelope fields and sets `error` to `public_error_fields(failure, response_id)`.
2. Wrap `PrivacyRouter().process(user_text)` in the same fail-closed `extraction_failed` handling as chat: call `log_privacy_failure` before returning `_response_error_body` with HTTP 503.
3. Replace the separate local and external adapter blocks with one route-selection block that chooses the endpoint’s adapter/model/settings once and constructs `forward_messages` once. For `policy.requires_masking`, mask exactly once using `pipeline.records`; do not construct a new `Extractor`.
4. Use `execute_fixed_route` for the non-streaming adapter call. Catch `PrivacyRouteFailure` and return `JSONResponse(status_code=failure.status_code, content=_response_error_body(response_id, failure))`.
5. Use `execute_fixed_stream` for the streaming adapter call. On `PrivacyRouteFailure`, emit one `response.failed` event containing `{"error": public_error_fields(failure, response_id)}`, then `[DONE]`, and return.
6. Replace both hydration `except: pass` branches with a safe `hydration_failed` error. Non-streaming returns a failed envelope; streaming emits `response.failed` and does not send `response.completed` or a partial final response.
7. Delete every `str(exc)` use in adapter, stream, and hydration error responses.

- [ ] **Step 4: Run OpenResponses tests to verify success**

Run:

```bash
python -m pytest server/tests/test_fail_closed_retry.py -q -k responses
```

Expected: all OpenResponses tests pass, including the one-attempt late-stream failure contract.

## Task 4: Cross-Route Regression Verification and Final Cleanup

**Files:**
- Modify only if required by Task 1–3 test failures: `agents/router/execution.py`, `server/api/routes/proxy.py`, `server/api/routes/responses.py`, or their focused tests.

**Interfaces:**
- Consumes: completed Task 1–3 behavior.
- Produces: one fully verified, squashed feature change; no documentation or configuration changes are required beyond the approved design and implementation-plan records.

- [ ] **Step 1: Add the missing stream-start retry assertions**

Add these exact tests:

```python
def test_chat_stream_retries_local_before_any_output():
    local = CountingAdapter(error=TimeoutError("not emitted"), failures=2)
    external = CountingAdapter()
    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post(
            "/v1/chat/completions",
            json={**_chat_request(), "stream": True},
        )
    assert response.status_code == 200
    assert len(local.calls) == 3
    assert external.calls == []
    assert "data: [DONE]" in response.text
    assert '"error"' not in response.text


def test_responses_stream_retries_external_before_any_output():
    local = CountingAdapter()
    external = CountingAdapter(error=TimeoutError("not emitted"), failures=2)
    with _responses_dependencies(route="external_api", local=local, external=external):
        response = client.post(
            "/v1/responses",
            json={**_responses_request(), "stream": True},
        )
    assert response.status_code == 200
    assert local.calls == []
    assert len(external.calls) == 3
    assert "event: response.completed" in response.text
    assert "event: response.failed" not in response.text
```

- [ ] **Step 2: Run all focused retry and API tests**

Run:

```bash
python -m pytest agents/router/tests/test_execution.py server/tests/test_fail_closed_retry.py server/tests/test_server.py server/tests/test_guardrail.py -q
```

Expected: all focused tests pass. Do not mask a failure by broadening accepted status codes or weakening call-count assertions.

- [ ] **Step 3: Audit forbidden execution patterns**

Use the built-in `grep` tool over `agents/router/execution.py`, `server/api/routes/proxy.py`, and `server/api/routes/responses.py` with this regular expression:

```text
local model unavailable|masked fallback|str\(exc\)|DEBUG PROXY
```

Expected: no matches. Then search for `except Exception` in the same files. Every remaining occurrence must immediately convert to `PrivacyRouteFailure` or pass the caught error only to `_handle_adapter_error`; none may return, stream, or log a raw exception.

- [ ] **Step 4: Create one squashed feature commit**

Stage only the implementation and focused test files:

```bash
git add agents/router/execution.py agents/router/__init__.py agents/__init__.py agents/router/tests/test_execution.py server/api/__init__.py server/api/routes/proxy.py server/api/routes/responses.py server/tests/test_fail_closed_retry.py
git commit -m "fix: preserve route across backend retries"
```

Expected: one commit contains the complete feature and tests. Do not stage unrelated user changes.

## Plan Review

### Spec coverage

- Route immutability and three total attempts: Tasks 1–3.
- Exact retryable exception boundary and 1/2 second backoff: Task 1.
- Same prepared payload, no repeated extraction/masking: Tasks 1–3.
- No local/external fallback: Tasks 2–4.
- Raw-free structured logs and stable client error fields: Tasks 1–3.
- Safe extraction, masking, hydration, and route-invariant failures: Tasks 1–3.
- Streaming retry cutoff and safe `response.failed`: Tasks 1, 2, 3, and 4.
- Focused behavioral proof: Task 4.

### Placeholder scan

The plan contains no TBD markers, deferred implementation phrases, unspecified validation, or implicit test instructions. All new public function names, error fields, test names, commands, and payload assertions are defined in earlier tasks.

### Type consistency

Both API routes consume `PrivacyRouteFailure`, `execute_fixed_route`, `execute_fixed_stream`, `log_privacy_failure`, `privacy_failure`, and `public_error_fields` defined in Task 1. The common public payload is always `{code, reason, message, retryable, attempts, request_id}`. `route` is server-log-only.
