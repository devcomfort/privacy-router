"""ASGI boundary for encrypted, request-scoped telemetry."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agents import PipelineResult, encrypt_field
from telemetry import (
    activate_request_trace,
    annotate_request_trace,
    finish_request_trace,
    start_request_trace,
)

_TRACED_ENDPOINTS = {
    "/api/v1/classify": "classify",
    "/api/v1/generate": "generate",
    "/api/v1/guardrail": "guardrail",
    "/v1/chat/completions": "chat_completions",
    "/v1/responses": "responses",
    "/v1/responses/compact": "responses_compact",
}
_REQUEST_ID_HEADER = b"x-privacy-router-request-id"
_SAFE_REQUEST_KEYS = frozenset(
    {
        "content",
        "frequency_penalty",
        "function",
        "input",
        "input_type",
        "instructions",
        "max_output_tokens",
        "max_tokens",
        "messages",
        "metadata",
        "model",
        "name",
        "parallel_tool_calls",
        "presence_penalty",
        "previous_response_id",
        "request_data",
        "response_format",
        "role",
        "store",
        "stream",
        "structured_messages",
        "temperature",
        "text",
        "texts",
        "tool_choice",
        "tools",
        "top_logprobs",
        "top_p",
        "type",
        "user",
    }
)


class RequestTraceMiddleware:
    """Persist encrypted request traces through complete ASGI response delivery.

    This is a direct ASGI middleware rather than ``BaseHTTPMiddleware`` so the
    active context remains bound while streaming response iterators execute.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        endpoint = _trace_endpoint(scope)
        if endpoint is None:
            await self.app(scope, receive, send)
            return

        body, replay = await _buffer_request_body(receive)
        request_id = uuid4().hex
        try:
            input_encrypted = encrypt_field(body.decode("utf-8", errors="replace"))
            input_redacted = _redacted_request_body(body)
            trace = start_request_trace(
                request_id=request_id,
                endpoint=endpoint,
                input_encrypted=input_encrypted,
                input_redacted=input_redacted,
            )
        except Exception:
            await self.app(scope, replay, send)
            return

        status_code = 500

        async def traced_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (name, value) for name, value in message.get("headers", []) if name.lower() != _REQUEST_ID_HEADER
                ]
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            with activate_request_trace(trace):
                await self.app(scope, replay, traced_send)
        except BaseException:
            status_code = 500
            raise
        finally:
            finish_request_trace(trace, status_code=status_code)


def _trace_endpoint(scope: Scope) -> str | None:
    if scope["type"] != "http" or scope.get("method") != "POST":
        return None
    path = str(scope.get("path", ""))
    return _TRACED_ENDPOINTS.get(path)


def _redacted_request_body(body: bytes) -> str:
    """Preserve JSON structure while redacting every request value."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"body": "[REDACTED]"}
    return json.dumps(
        _redact_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            (str(key) if str(key) in _SAFE_REQUEST_KEYS else f"[REDACTED_KEY_{index}]"): _redact_value(item)
            for index, (key, item) in enumerate(value.items())
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if value is None:
        return None
    return "[REDACTED]"


async def _buffer_request_body(receive: Receive) -> tuple[bytes, Receive]:
    """Buffer the incoming ASGI body once and replay it unchanged to FastAPI."""
    messages: deque[Message] = deque()
    chunks: list[bytes] = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break

    async def replay() -> Message:
        if messages:
            return messages.popleft()
        return await receive()

    return b"".join(chunks), replay


def annotate_pipeline_traces(
    pipelines: Iterable[PipelineResult],
    *,
    model_used: str | None = None,
    policy_action: str | None = None,
    route: str | None = None,
) -> None:
    """Attach aggregate policy data and encrypted analysis evidence."""
    results = list(pipelines)
    if not results:
        return
    action_priority = {"allow": 0, "selective_mask": 1, "block": 2}
    effective_action = policy_action or max(
        (result.judgment.policy_action for result in results),
        key=lambda action: action_priority.get(action, 3),
    )
    effective_route = route or (
        "local_api" if any(result.route.endpoint == "local_api" for result in results) else "external_api"
    )
    annotations: dict[str, object] = {
        "is_sensitive": any(result.sensitivity.is_sensitive for result in results),
        "records_count": sum(len(result.records) for result in results),
        "policy_action": effective_action,
        "route": effective_route,
        "model_used": model_used,
    }
    try:
        extraction = [
            {
                "sensitivity": result.sensitivity.model_dump(mode="json"),
                "records": [record.model_dump(mode="json") for record in result.records],
            }
            for result in results
        ]
        judgments = [result.judgment.model_dump(mode="json") for result in results]
        annotations["extraction_encrypted"] = encrypt_field(json.dumps(extraction, ensure_ascii=False, sort_keys=True))
        annotations["judgment_encrypted"] = encrypt_field(json.dumps(judgments, ensure_ascii=False, sort_keys=True))
    except Exception:
        pass
    annotate_request_trace(**annotations)


def traced_endpoint_names() -> dict[str, str]:
    """Return a copy for diagnostics and documentation tests."""
    return dict(_TRACED_ENDPOINTS)
