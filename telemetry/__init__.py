"""Encrypted request tracing and correlated LiteLLM usage telemetry."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import litellm
from litellm.integrations.custom_logger import CustomLogger
from sqlalchemy import delete
from sqlmodel import select

from db import ModelInvocation, RequestTrace, get_session

_TRACE_TTL = timedelta(hours=24)
_TRACE_METADATA_KEY = "privacy_router"


@dataclass(frozen=True)
class RequestTraceHandle:
    """In-process request correlation without sensitive request content."""

    request_id: str
    endpoint: str
    started_at: float
    outcome: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


_active_trace: ContextVar[RequestTraceHandle | None] = ContextVar(
    "privacy_router_request_trace",
    default=None,
)


def start_request_trace(
    *,
    request_id: str,
    endpoint: str,
    input_encrypted: str,
    input_redacted: str = "{}",
    expires_at: datetime | None = None,
) -> RequestTraceHandle:
    """Create an encrypted request trace; telemetry failures never fail traffic."""
    handle = RequestTraceHandle(
        request_id=request_id,
        endpoint=endpoint,
        started_at=time.perf_counter(),
    )
    expiry = (expires_at or datetime.now(UTC) + _TRACE_TTL).replace(tzinfo=None)
    session = get_session()
    try:
        session.add(
            RequestTrace(
                id=request_id,
                endpoint=endpoint,
                input_encrypted=input_encrypted,
                input_redacted=input_redacted,
                expires_at=expiry,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
    return handle


@contextmanager
def activate_request_trace(handle: RequestTraceHandle) -> Iterator[RequestTraceHandle]:
    """Bind a request trace while synchronous or asynchronous work is scheduled."""
    token = _active_trace.set(handle)
    try:
        yield handle
    finally:
        _active_trace.reset(token)


def annotate_request_trace(
    *,
    is_sensitive: bool | None = None,
    records_count: int | None = None,
    policy_action: str | None = None,
    route: str | None = None,
    model_used: str | None = None,
    extraction_encrypted: str | None = None,
    judgment_encrypted: str | None = None,
) -> None:
    """Attach route results to the active request without exposing raw values."""
    trace = _active_trace.get()
    if trace is None:
        return
    values = {
        "is_sensitive": is_sensitive,
        "records_count": records_count,
        "policy_action": policy_action,
        "route": route,
        "model_used": model_used,
        "extraction_encrypted": extraction_encrypted,
        "judgment_encrypted": judgment_encrypted,
    }
    trace.outcome.update({key: value for key, value in values.items() if value is not None})


def build_litellm_metadata(
    component: str,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach durable request correlation to a LiteLLM call's metadata."""
    metadata = dict(existing or {})
    trace = _active_trace.get()
    if trace is not None:
        metadata[_TRACE_METADATA_KEY] = {
            "request_id": trace.request_id,
            "component": component,
        }
    return metadata


def finish_request_trace(
    handle: RequestTraceHandle,
    *,
    status_code: int,
    is_sensitive: bool | None = None,
    records_count: int | None = None,
    policy_action: str | None = None,
    route: str | None = None,
    model_used: str | None = None,
    extraction_encrypted: str | None = None,
    judgment_encrypted: str | None = None,
) -> None:
    """Finalize request-level decision, route, and encrypted analysis evidence."""
    outcome = dict(handle.outcome)
    explicit = {
        "is_sensitive": is_sensitive,
        "records_count": records_count,
        "policy_action": policy_action,
        "route": route,
        "model_used": model_used,
        "extraction_encrypted": extraction_encrypted,
        "judgment_encrypted": judgment_encrypted,
    }
    outcome.update({key: value for key, value in explicit.items() if value is not None})
    session = get_session()
    try:
        trace = session.get(RequestTrace, handle.request_id)
        if trace is None:
            return
        trace.status = "completed" if status_code < 400 else "failed"
        trace.status_code = status_code
        trace.is_sensitive = bool(outcome.get("is_sensitive", False))
        trace.records_count = int(outcome.get("records_count", 0))
        trace.policy_action = outcome.get("policy_action")
        trace.route = outcome.get("route")
        trace.model_used = outcome.get("model_used")
        trace.extraction_encrypted = outcome.get("extraction_encrypted")
        trace.judgment_encrypted = outcome.get("judgment_encrypted")
        trace.latency_ms = max(0.0, (time.perf_counter() - handle.started_at) * 1000)
        session.add(trace)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _metadata_trace(kwargs: Mapping[str, Any]) -> tuple[str, str] | None:
    litellm_params = kwargs.get("litellm_params")
    metadata = litellm_params.get("metadata") if isinstance(litellm_params, Mapping) else None
    if not isinstance(metadata, Mapping):
        metadata = kwargs.get("metadata")
    trace = metadata.get(_TRACE_METADATA_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(trace, Mapping):
        return None
    request_id = trace.get("request_id")
    component = trace.get("component")
    if not isinstance(request_id, str) or not request_id:
        return None
    if not isinstance(component, str) or not component:
        return None
    return request_id, component


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _usage(response_obj: Any) -> tuple[int, int, int]:
    usage = _value(response_obj, "usage")
    prompt_tokens = int(_value(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(_value(usage, "completion_tokens", 0) or 0)
    total_tokens = int(_value(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return prompt_tokens, completion_tokens, total_tokens


def _response_cost(kwargs: Mapping[str, Any], response_obj: Any) -> float:
    hidden = _value(response_obj, "_hidden_params", {})
    litellm_params = kwargs.get("litellm_params")
    candidates = (
        kwargs.get("response_cost"),
        litellm_params.get("response_cost") if isinstance(litellm_params, Mapping) else None,
        hidden.get("response_cost") if isinstance(hidden, Mapping) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return max(0.0, float(candidate))
    return 0.0


def _latency_ms(start_time: Any, end_time: Any) -> float:
    try:
        return max(0.0, float((end_time - start_time).total_seconds() * 1000))
    except (AttributeError, TypeError, ValueError):
        try:
            return max(0.0, (float(end_time) - float(start_time)) * 1000)
        except (TypeError, ValueError):
            return 0.0


def _provider(kwargs: Mapping[str, Any], model: str) -> str | None:
    litellm_params = kwargs.get("litellm_params")
    if isinstance(litellm_params, Mapping):
        provider = litellm_params.get("custom_llm_provider")
        if isinstance(provider, str) and provider:
            return provider
    if "/" in model:
        return model.split("/", 1)[0]
    return None


class LiteLLMUsageCallback(CustomLogger):
    """Persist token, cost, latency, and failure data for traced model calls."""

    _privacy_router_usage_callback = True

    def _record(
        self,
        kwargs: Mapping[str, Any],
        response_obj: Any,
        start_time: Any,
        end_time: Any,
        *,
        success: bool,
    ) -> None:
        correlation = _metadata_trace(kwargs)
        if correlation is None:
            return
        request_id, component = correlation
        model = str(kwargs.get("model") or _value(response_obj, "model", "unknown"))
        prompt_tokens, completion_tokens, total_tokens = _usage(response_obj)
        exception = kwargs.get("exception")
        invocation_id = str(kwargs.get("litellm_call_id") or uuid.uuid4())
        session = get_session()
        try:
            trace = session.get(RequestTrace, request_id)
            now = datetime.now(UTC).replace(tzinfo=None)
            if trace is None or trace.expires_at <= now:
                return
            session.add(
                ModelInvocation(
                    id=invocation_id,
                    request_id=request_id,
                    component=component,
                    model=model,
                    provider=_provider(kwargs, model),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=_response_cost(kwargs, response_obj),
                    latency_ms=_latency_ms(start_time, end_time),
                    success=success,
                    error_type=type(exception).__name__ if exception is not None else None,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, success=True)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, success=False)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, success=True)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, success=False)


def normalize_utc(value: datetime) -> datetime:
    """Normalize aware or naive input to the database's naive UTC convention."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_isoformat(value: datetime) -> str:
    """Serialize database timestamps with an explicit UTC offset."""
    return normalize_utc(value).replace(tzinfo=UTC).isoformat()


def purge_request_telemetry(
    *,
    scope: Literal["expired", "before", "all"] = "expired",
    before: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete request traces and their model calls in one committed unit."""
    current = normalize_utc(now or datetime.now(UTC))
    if scope == "expired":
        condition = RequestTrace.expires_at <= current
    elif scope == "before":
        if before is None:
            raise ValueError("before is required when scope='before'")
        condition = RequestTrace.created_at < normalize_utc(before)
    elif scope == "all":
        condition = RequestTrace.id.is_not(None)
    else:
        raise ValueError(f"Unsupported purge scope: {scope}")

    session = get_session()
    try:
        trace_ids = list(session.exec(select(RequestTrace.id).where(condition)).all())
        if not trace_ids:
            return {"request_traces": 0, "model_invocations": 0}
        invocation_result = session.exec(delete(ModelInvocation).where(ModelInvocation.request_id.in_(trace_ids)))
        trace_result = session.exec(delete(RequestTrace).where(RequestTrace.id.in_(trace_ids)))
        session.commit()
        return {
            "request_traces": trace_result.rowcount or 0,
            "model_invocations": invocation_result.rowcount or 0,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _redacted_input(value: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"body": "[REDACTED]"}


def export_request_telemetry(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Export safe request and model-call telemetry without encrypted payloads."""
    statement = select(RequestTrace).order_by(RequestTrace.created_at.desc())
    if since is not None:
        statement = statement.where(RequestTrace.created_at >= normalize_utc(since))
    if until is not None:
        statement = statement.where(RequestTrace.created_at <= normalize_utc(until))
    if limit is not None:
        statement = statement.limit(limit)

    session = get_session()
    try:
        traces = list(session.exec(statement).all())
        trace_ids = [trace.id for trace in traces]
        invocations = (
            list(
                session.exec(
                    select(ModelInvocation)
                    .where(ModelInvocation.request_id.in_(trace_ids))
                    .order_by(ModelInvocation.created_at)
                ).all()
            )
            if trace_ids
            else []
        )
    finally:
        session.close()

    calls_by_request: dict[str, list[ModelInvocation]] = {}
    for invocation in invocations:
        calls_by_request.setdefault(invocation.request_id, []).append(invocation)

    requests: list[dict[str, Any]] = []
    for trace in traces:
        calls = calls_by_request.get(trace.id, [])
        requests.append(
            {
                "id": trace.id,
                "endpoint": trace.endpoint,
                "input_redacted": _redacted_input(trace.input_redacted),
                "is_sensitive": trace.is_sensitive,
                "records_count": trace.records_count,
                "policy_action": trace.policy_action,
                "route": trace.route,
                "model_used": trace.model_used,
                "latency_ms": trace.latency_ms,
                "status": trace.status,
                "status_code": trace.status_code,
                "created_at": _utc_isoformat(trace.created_at),
                "expires_at": _utc_isoformat(trace.expires_at),
                "usage": {
                    "prompt_tokens": sum(call.prompt_tokens for call in calls),
                    "completion_tokens": sum(call.completion_tokens for call in calls),
                    "total_tokens": sum(call.total_tokens for call in calls),
                    "cost_usd": sum(call.cost_usd for call in calls),
                    "model_calls": len(calls),
                },
                "invocations": [
                    {
                        "id": call.id,
                        "component": call.component,
                        "model": call.model,
                        "provider": call.provider,
                        "prompt_tokens": call.prompt_tokens,
                        "completion_tokens": call.completion_tokens,
                        "total_tokens": call.total_tokens,
                        "cost_usd": call.cost_usd,
                        "latency_ms": call.latency_ms,
                        "success": call.success,
                        "error_type": call.error_type,
                        "created_at": _utc_isoformat(call.created_at),
                    }
                    for call in calls
                ],
            }
        )

    return {
        "schema_version": "1.0",
        "privacy_level": "redacted",
        "exported_at": datetime.now(UTC).isoformat(),
        "requests": requests,
    }


_USAGE_CALLBACK = LiteLLMUsageCallback()


def install_litellm_usage_callback() -> LiteLLMUsageCallback:
    """Register exactly one callback without replacing existing callbacks."""
    for callback in litellm.callbacks:
        if getattr(callback, "_privacy_router_usage_callback", False):
            return callback
    litellm.logging_callback_manager.add_litellm_callback(_USAGE_CALLBACK)
    return _USAGE_CALLBACK
