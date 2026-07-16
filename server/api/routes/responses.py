"""Privacy Router Server — OpenResponses-compatible endpoint.

Implements the ``/v1/responses`` API compatible with the OpenResponses spec.
The request passes through the same privacy pipeline
(Extractor → Judge → Router → Masker/Hydrator) as ``/v1/chat/completions``.

Endpoints:
    ``POST /v1/responses``              — create a response
    ``GET  /v1/responses/{response_id}`` — retrieve a response (stub)
"""

from __future__ import annotations

import hmac
import json
import math
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from agents import (
    PipelineResult,
    PlaceholderRepairer,
    PrivacyRouteFailure,
    PrivacyRouter,
    decrypt_field,
    encrypt_field,
    execute_fixed_route,
    execute_fixed_stream,
    get_cache,
    log_privacy_failure,
    placeholder_repair_enabled,
    privacy_failure,
    public_error_fields,
    redact_extraction_records,
)
from config import resolve_api_base, resolve_local_api_base, resolve_model
from db import Response as ResponseModel
from db import get_session
from server.api import (
    StreamingHydrator,
    adapter_for,
    app,
    build_tool_call_inspection,
    contains_uninspected_media,
    flush_stream_hydrator,
    hydrate_masked_response,
    hydrate_stream_chunk,
    hydrate_tool_call_arguments,
    mask_responses_input,
    mask_sensitive_tool_call_arguments,
    merge_context_segments,
    merge_stream_tool_call_type,
    reject_sensitive_tool_call_protocol_fields,
    render_context_segments,
    require_auth,
    responses_context_segments,
    responses_input_to_messages,
    sensitive_tool_arguments_allowed,
    session_cache_key,
    validate_stream_tool_call_index,
    validate_stream_tool_call_indices,
    validate_tool_call_identifier_groups,
    validate_tool_call_protocol,
    without_uninspected_media,
)
from server.config import get_config

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _privacy_metadata(
    pipeline: PipelineResult,
    visible_records: list[Any],
) -> dict[str, Any]:
    """Build response metadata without echoing prior-only session values."""
    is_sensitive = pipeline.sensitivity.is_sensitive
    records = redact_extraction_records(visible_records)
    return {
        "is_sensitive": is_sensitive,
        "policy_action": pipeline.judgment.policy_action,
        "extraction_records": records,
        "route": pipeline.route.endpoint,
    }


def _openai_usage(litellm_usage: dict[str, int] | None) -> dict[str, Any]:
    """Translate LiteLLM usage keys to the complete OpenResponses shape."""
    usage = litellm_usage or {}
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def _build_output_message(text: str) -> dict[str, Any]:
    """Build one completed OpenResponses assistant message."""
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
                "annotations": [],
                "logprobs": [],
            }
        ],
        "status": "completed",
    }


def _responses_tools_to_chat(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Translate supported OpenResponses function tools to Chat Completions tools."""
    normalized = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type", "function") != "function":
            raise ValueError("Only function tools are supported by this Responses endpoint")
        if "function" in tool:
            normalized.append(tool)
            continue
        function = {key: value for key, value in tool.items() if key in {"name", "description", "parameters", "strict"}}
        normalized.append({"type": "function", "function": function})
    return normalized


def _responses_tool_choice_to_chat(
    tool_choice: str | dict[str, Any] | None,
) -> str | dict[str, Any] | None:
    """Translate a forced OpenResponses function choice to Chat Completions."""
    if not isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice.get("type") != "function":
        raise ValueError("Only function tool choices are supported by this Responses endpoint")
    if isinstance(tool_choice.get("function"), dict):
        return tool_choice
    name = tool_choice.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("A forced function tool choice requires a name")
    return {"type": "function", "function": {"name": name}}


def _response_tool_calls(response: object) -> list[dict[str, str]]:
    """Normalize tool calls from Responses or Chat-shaped provider results."""
    normalized: list[dict[str, str]] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) not in {"function_call", "tool_call"}:
            continue
        normalized.append(
            {
                "id": getattr(item, "id", "") or "",
                "call_id": getattr(item, "call_id", "") or "",
                "type": getattr(item, "type", "") or "",
                "allowed_type": "function_call",
                "name": getattr(item, "name", "") or "",
                "arguments": getattr(item, "arguments", "") or "",
            }
        )
    if normalized:
        return normalized
    choices = getattr(response, "choices", None) or []
    if not choices:
        return normalized
    for tool_call in getattr(choices[0].message, "tool_calls", None) or []:
        normalized.append(
            {
                "id": getattr(tool_call, "id", "") or "",
                "call_id": getattr(tool_call, "id", "") or "",
                "type": getattr(tool_call, "type", "") or "",
                "allowed_type": "function",
                "name": getattr(tool_call.function, "name", "") or "",
                "arguments": getattr(tool_call.function, "arguments", "") or "",
            }
        )
    return normalized


def _build_function_call(tool_call: dict[str, str]) -> dict[str, Any]:
    """Build one completed OpenResponses function-call output item."""
    return {
        "type": "function_call",
        "id": tool_call["id"],
        "call_id": tool_call["call_id"],
        "name": tool_call["name"],
        "arguments": tool_call["arguments"],
        "status": "completed",
    }


def _response_tools(request_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return schema-complete function tool definitions without mutating input."""
    tools = request_body.get("tools")
    if not isinstance(tools, list):
        return []
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        response_tool = dict(tool)
        if response_tool.get("type", "function") == "function":
            response_tool.setdefault("type", "function")
            response_tool.setdefault("description", None)
            response_tool.setdefault("parameters", None)
            response_tool.setdefault("strict", False)
        normalized.append(response_tool)
    return normalized


def _request_value(
    request_body: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    """Treat an explicit JSON null like an omitted optional request field."""
    value = request_body.get(key)
    return default if value is None else value


def _response_number(
    request_body: dict[str, Any],
    key: str,
    default: int | float,
    *,
    integer: bool = False,
) -> int | float:
    """Return a schema-safe number even while reporting malformed requests."""
    value = _request_value(request_body, key, default)
    expected = int if integer else (int, float)
    if (
        isinstance(value, bool)
        or not isinstance(value, expected)
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        return default
    try:
        return int(value) if integer else float(value)
    except (OverflowError, ValueError):
        return default


def _validated_generation_options(
    request_body: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize Responses generation options."""
    options: dict[str, Any] = {}

    def number(
        key: str,
        default: int | float,
        *,
        minimum: int | float,
        maximum: int | float | None = None,
        integer: bool = False,
    ) -> int | float:
        value = request_body.get(key)
        if value is None:
            return default
        expected = int if integer else (int, float)
        if (
            isinstance(value, bool)
            or not isinstance(value, expected)
            or (isinstance(value, float) and not math.isfinite(value))
            or value < minimum
            or (maximum is not None and value > maximum)
        ):
            upper = f" and {maximum}" if maximum is not None else ""
            kind = "an integer" if integer else "a number"
            raise ValueError(f"{key} must be {kind} between {minimum}{upper}")
        return int(value) if integer else float(value)

    options["temperature"] = number("temperature", 1.0, minimum=0.0, maximum=2.0)
    options["top_p"] = number("top_p", 1.0, minimum=0.0, maximum=1.0)
    options["presence_penalty"] = number("presence_penalty", 0.0, minimum=-2.0, maximum=2.0)
    options["frequency_penalty"] = number("frequency_penalty", 0.0, minimum=-2.0, maximum=2.0)
    options["top_logprobs"] = number("top_logprobs", 0, minimum=0, maximum=20, integer=True)
    options["max_output_tokens"] = number("max_output_tokens", 4096, minimum=1, integer=True)
    options["max_tool_calls"] = number("max_tool_calls", 1, minimum=1, integer=True)
    for key, default in (
        ("stream", False),
        ("store", True),
        ("background", False),
    ):
        value = request_body.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        options[key] = value
    parallel_tool_calls = request_body.get("parallel_tool_calls")
    if parallel_tool_calls is None:
        parallel_tool_calls = True
    if not isinstance(parallel_tool_calls, bool):
        raise ValueError("parallel_tool_calls must be a boolean or null")
    options["parallel_tool_calls"] = parallel_tool_calls
    truncation = _request_value(request_body, "truncation", "disabled")
    if truncation not in {"auto", "disabled"}:
        raise ValueError("truncation must be 'auto' or 'disabled'")
    options["truncation"] = truncation
    return options


def _build_response(
    response_id: str,
    model: str,
    input_data: Any,
    text: str,
    usage: dict[str, int] | None,
    privacy_meta: dict[str, Any],
    *,
    request_body: dict[str, Any] | None = None,
    created_at: int | None = None,
    status: str = "completed",
    output_items: list[dict[str, Any]] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a schema-complete OpenResponses response resource."""
    request_body = request_body or {}
    now = int(time.time())
    created = created_at if created_at is not None else now
    metadata = request_body.get("metadata")
    response_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    response_metadata["privacy_router"] = privacy_meta
    tool_choice = request_body.get("tool_choice", "auto")
    if tool_choice is None:
        tool_choice = "auto"
    response_usage = None if status == "in_progress" else _openai_usage(usage)
    response_tools = _response_tools(request_body)
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "completed_at": None if status == "in_progress" else now,
        "status": status,
        "incomplete_details": None,
        "model": model,
        "previous_response_id": request_body.get("previous_response_id"),
        "instructions": request_body.get("instructions"),
        "input": input_data if isinstance(input_data, list) else [input_data],
        "output": (output_items if output_items is not None else ([_build_output_message(text)] if text else [])),
        "error": error,
        "tools": response_tools,
        "tool_choice": tool_choice,
        "truncation": (
            request_body.get("truncation") if request_body.get("truncation") in {"auto", "disabled"} else "disabled"
        ),
        "parallel_tool_calls": (
            request_body.get("parallel_tool_calls")
            if isinstance(request_body.get("parallel_tool_calls"), bool)
            else True
        ),
        "text": request_body.get("text") or {"format": {"type": "text"}},
        "top_p": _response_number(request_body, "top_p", 1.0),
        "presence_penalty": _response_number(request_body, "presence_penalty", 0.0),
        "frequency_penalty": _response_number(request_body, "frequency_penalty", 0.0),
        "top_logprobs": _response_number(request_body, "top_logprobs", 0, integer=True),
        "temperature": _response_number(request_body, "temperature", 1.0),
        "reasoning": request_body.get("reasoning"),
        "usage": response_usage,
        "max_output_tokens": request_body.get("max_output_tokens"),
        "max_tool_calls": request_body.get("max_tool_calls"),
        "store": bool(request_body.get("store", True)),
        "background": bool(request_body.get("background", False)),
        "service_tier": request_body.get("service_tier", "default"),
        "metadata": response_metadata,
        "safety_identifier": request_body.get("safety_identifier"),
        "prompt_cache_key": request_body.get("prompt_cache_key"),
    }


def _error_body(
    response_id: str,
    message: str,
    *,
    code: str = "invalid_request",
    request_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a schema-complete failed OpenResponses response."""
    return _build_response(
        response_id,
        "",
        [],
        "",
        None,
        {},
        request_body=request_body,
        status="failed",
        output_items=[],
        error={"code": code, "message": message},
    )


def _privacy_error_body(
    response_id: str,
    failure: PrivacyRouteFailure,
    *,
    request_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a failed response without exposing route or provider internals."""
    error = public_error_fields(failure, response_id)
    body = _error_body(
        response_id,
        error["message"],
        code=error["code"],
        request_body=request_body,
    )
    body["error"] = error
    return body


_COMPACTION_VERSION = 1
_MAX_COMPACTION_DEPTH = 4
_MAX_EXPANDED_ITEMS = 10_000


def _invalid_media_input(value: Any) -> str | None:
    """Return malformed direct media content without recursing into metadata."""
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, dict):
            continue
        candidates: list[Any] = [item]
        content = item.get("content")
        if isinstance(content, list):
            candidates.extend(content)
        elif isinstance(content, dict):
            candidates.append(content)
        for part in candidates:
            if not isinstance(part, dict) or part.get("type") != "input_image":
                continue
            image_url = part.get("image_url")
            if not isinstance(image_url, str) or not image_url:
                return "input_image.image_url must be a non-empty string"
    return None


def _encode_compaction(input_data: str | list[Any], owner_id: str) -> str:
    """Encrypt replayable input and bind it to one authenticated API-key owner."""
    normalized = input_data if isinstance(input_data, list) else [input_data]
    payload = {
        "version": _COMPACTION_VERSION,
        "owner_id": owner_id,
        "input": normalized,
    }
    return encrypt_field(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _decode_compaction(encrypted_content: str, owner_id: str) -> list[Any]:
    """Decrypt one owner-bound compaction item without exposing failure details."""
    try:
        payload = json.loads(decrypt_field(encrypted_content))
        stored_owner = payload["owner_id"]
        compacted_input = payload["input"]
        if (
            payload.get("version") != _COMPACTION_VERSION
            or not isinstance(stored_owner, str)
            or not hmac.compare_digest(stored_owner, owner_id)
            or not isinstance(compacted_input, list)
        ):
            raise ValueError
        return compacted_input
    except Exception as exc:
        raise ValueError("Invalid compaction item") from exc


def _expand_compaction_input(
    input_data: str | list[Any],
    owner_id: str,
) -> str | list[Any]:
    """Expand encrypted compaction items before privacy analysis and forwarding."""
    if isinstance(input_data, str):
        return input_data
    if not isinstance(input_data, list):
        raise ValueError("Input must be a string or a list")

    def expand(items: list[Any], depth: int) -> list[Any]:
        if depth > _MAX_COMPACTION_DEPTH:
            raise ValueError("Invalid compaction item")
        expanded: list[Any] = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "compaction":
                encrypted_content = item.get("encrypted_content")
                if not isinstance(encrypted_content, str) or not encrypted_content:
                    raise ValueError("Invalid compaction item")
                expanded.extend(
                    expand(
                        _decode_compaction(encrypted_content, owner_id),
                        depth + 1,
                    )
                )
            else:
                expanded.append(item)
            if len(expanded) > _MAX_EXPANDED_ITEMS:
                raise ValueError("Invalid compaction item")
        return expanded

    return expand(input_data, 0)


def _load_previous_context(
    response_id: str,
    owner_id: str,
    *,
    seen: set[str] | None = None,
    volatile_responses: dict[str, dict[str, Any]] | None = None,
) -> list[Any] | None:
    """Load an owner-bound response chain as input/output conversation items."""
    visited = seen or set()
    if response_id in visited or len(visited) >= 100:
        return None
    visited.add(response_id)
    body = volatile_responses.get(response_id) if volatile_responses is not None else None
    if body is None:
        session = get_session()
        try:
            now = datetime.now(UTC).replace(tzinfo=None)
            stored = session.exec(
                select(ResponseModel).where(
                    ResponseModel.id == response_id,
                    ResponseModel.owner_id == owner_id,
                    ResponseModel.storage_encrypted.is_(True),
                    ResponseModel.expires_at.is_not(None),
                    ResponseModel.expires_at > now,
                )
            ).first()
            if stored is None:
                return None
            body = json.loads(decrypt_field(stored.output_json))
        except Exception:
            return None
        finally:
            session.close()

    context: list[Any] = []
    previous_id = body.get("previous_response_id")
    if isinstance(previous_id, str) and previous_id:
        earlier = _load_previous_context(
            previous_id,
            owner_id,
            seen=visited,
            volatile_responses=volatile_responses,
        )
        if earlier is None:
            return None
        context.extend(earlier)
    prior_input = body.get("input")
    if isinstance(prior_input, list):
        context.extend(prior_input)
    prior_output = body.get("output")
    if isinstance(prior_output, list):
        context.extend(prior_output)
    return context


def _unmatched_function_call_output(
    current_items: list[Any],
    previous_context: list[Any],
) -> str | None:
    """Return the first tool output whose call_id is not pending."""
    pending_call_ids: set[str] = set()
    for item in [*previous_context, *current_items]:
        if not isinstance(item, dict):
            continue
        call_id = item.get("call_id")
        if item.get("type") == "function_call":
            if isinstance(call_id, str) and call_id:
                pending_call_ids.add(call_id)
            continue
        if item.get("type") != "function_call_output":
            continue
        if not isinstance(call_id, str) or not call_id or call_id not in pending_call_ids:
            return call_id if isinstance(call_id, str) and call_id else "<missing>"
        pending_call_ids.remove(call_id)
    return None


def _store_response_resource(
    response_body: dict[str, Any],
    owner_id: str,
) -> bool:
    """Persist an encrypted response for at most 24 hours."""
    now = datetime.now(UTC).replace(tzinfo=None)
    session = get_session()
    try:
        session.add(
            ResponseModel(
                id=response_body["id"],
                owner_id=owner_id,
                model=response_body["model"],
                output_json=encrypt_field(json.dumps(response_body, ensure_ascii=False, separators=(",", ":"))),
                status=response_body["status"],
                created_at=now,
                expires_at=now + timedelta(hours=24),
                storage_encrypted=True,
            )
        )
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


@app.post("/v1/responses/compact")
async def compact_response(
    request: Request,
    _auth: str = Depends(require_auth),
):
    """Create an opaque, owner-bound OpenResponses compaction resource."""
    response_id = f"comp_{uuid.uuid4().hex[:24]}"
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                "Request body must be valid JSON",
                code="invalid_request",
            ),
        )
    model = body.get("model") if isinstance(body, dict) else None
    if not isinstance(model, str) or not model:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                "A model is required",
                code="invalid_request",
                request_body=body if isinstance(body, dict) else None,
            ),
        )
    input_data = body.get("input", [])
    if not isinstance(input_data, (str, list)):
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                "Input must be a string or a list",
                code="invalid_request",
                request_body=body,
            ),
        )
    item = {
        "type": "compaction",
        "id": f"cmp_{uuid.uuid4().hex[:24]}",
        "encrypted_content": _encode_compaction(input_data, _auth),
    }
    return JSONResponse(
        content={
            "id": response_id,
            "object": "response.compaction",
            "output": [item],
            "created_at": int(time.time()),
            "usage": _openai_usage(None),
        }
    )


# ── POST /v1/responses ───────────────────────────────────────────────────────


async def _create_response(
    body: dict[str, Any],
    _auth: str,
    client_chat_id: str | None,
    volatile_responses: dict[str, dict[str, Any]] | None = None,
) -> JSONResponse | AsyncIterator[str]:
    """Run one Responses request and return JSON or structured stream events."""
    cfg = get_config()
    allow_sensitive_tool_arguments = sensitive_tool_arguments_allowed(body)

    raw_model: str = body.get("model", "")
    request_input_data: str | list[Any] = body.get("input", "")
    instructions: str | None = body.get("instructions")
    raw_tools = body.get("tools")
    raw_tool_choice = body.get("tool_choice")
    response_id = _make_response_id()
    try:
        generation_options = _validated_generation_options(body)
        stream = generation_options["stream"]
        input_data = _expand_compaction_input(request_input_data, _auth)
        resource_input_data = input_data
        previous_response_id = body.get("previous_response_id")
        previous_context: list[Any] = []
        if previous_response_id is not None:
            if not isinstance(previous_response_id, str) or not previous_response_id:
                raise ValueError("previous_response_id must be a non-empty string")
            loaded_context = _load_previous_context(
                previous_response_id,
                _auth,
                volatile_responses=volatile_responses,
            )
            if loaded_context is None:
                return JSONResponse(
                    status_code=400,
                    content=_error_body(
                        response_id,
                        "The previous response was not found",
                        code="previous_response_not_found",
                        request_body=body,
                    ),
                )
            previous_context = loaded_context
        current_items = input_data if isinstance(input_data, list) else [input_data]
        unmatched_call_id = _unmatched_function_call_output(
            current_items,
            previous_context,
        )
        if unmatched_call_id is not None:
            return JSONResponse(
                status_code=400,
                content=_error_body(
                    response_id,
                    f"No pending function call found for call_id {unmatched_call_id!r}",
                    code="invalid_function_call_output",
                    request_body=body,
                ),
            )
        if previous_context:
            input_data = [*previous_context, *current_items]
        invalid_media = _invalid_media_input(input_data)
        if invalid_media is not None:
            raise ValueError(invalid_media)
        tools = _responses_tools_to_chat(raw_tools)
        tool_choice = _responses_tool_choice_to_chat(raw_tool_choice)
        chat_id = session_cache_key(_auth, client_chat_id)
    except ValueError as exc:
        code = "invalid_compaction" if str(exc) == "Invalid compaction item" else "invalid_request"
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                str(exc),
                code=code,
                request_body=body,
            ),
        )
    current_context = responses_context_segments(
        input_data,
        instructions=instructions,
        tools=tools,
        tool_choice=tool_choice,
    )
    context_cache = get_cache() if chat_id else None
    try:
        previous_context = (
            context_cache.get_context(chat_id) if context_cache is not None and chat_id is not None else []
        )
        complete_context = merge_context_segments(
            previous_context,
            current_context,
        )
        context_text = render_context_segments(complete_context)
    except Exception:
        failure = privacy_failure("extraction_failed")
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )

    if raw_model.startswith("privacy-router/"):
        raw_model = raw_model[len("privacy-router/") :]
    backend_model = cfg.external.model if raw_model == "privacy-router" or not raw_model else raw_model

    registered_ids = [model.id for model in cfg.models]
    if backend_model not in registered_ids:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                f"Model {backend_model!r} not registered. Available: {registered_ids}",
            ),
        )
    if resolve_model(cfg, backend_model).location != "external":
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                f"Model {backend_model!r} is reserved for on-device processing",
            ),
        )

    registered_model_id = backend_model
    try:
        adapter = adapter_for(backend_model)
        backend_model = adapter.resolve_backend_model(backend_model)
    except Exception:
        failure = PrivacyRouteFailure("unresolved", "adapter_error", False, 1, 502)
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )

    try:
        router = PrivacyRouter()
        pipeline = await run_in_threadpool(router.process, context_text)
        if context_cache is not None and chat_id is not None:
            context_cache.merge_context(
                chat_id,
                [{"label": segment.label, "text": segment.text} for segment in current_context],
                merge_context_segments,
            )
    except Exception:
        failure = privacy_failure("extraction_failed")
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )

    policy = pipeline.route
    has_uninspected_media = contains_uninspected_media(responses_input_to_messages(input_data))
    media_forced_local = has_uninspected_media and policy.endpoint != "local_api"
    if media_forced_local:
        policy = policy.model_copy(
            update={
                "endpoint": "local_api",
                "requires_masking": False,
                "description": "Uninspected media requires on-device processing",
            }
        )
    current_records = [
        record
        for record in pipeline.records
        if record.span and any(record.span in segment.text for segment in current_context)
    ]
    privacy_meta = _privacy_metadata(pipeline, current_records)
    if media_forced_local:
        privacy_meta["policy_action"] = "block"
        privacy_meta["route"] = "local_api"

    contract = None
    selected_model = backend_model
    selected_adapter = adapter
    configured_api_base = cfg.external.api_base if registered_model_id == cfg.external.model else None
    try:
        api_base = resolve_api_base(cfg, registered_model_id, configured_api_base)
    except Exception:
        failure = PrivacyRouteFailure("external_api", "adapter_error", False, 1, 502)
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )
    forward_messages = responses_input_to_messages(
        input_data,
        instructions=instructions,
    )
    forward_tools = tools
    forward_tool_choice = tool_choice

    if policy.endpoint == "local_api":
        local_model = cfg.local.model
        try:
            selected_adapter = adapter_for(local_model)
            selected_model = selected_adapter.resolve_backend_model(local_model)
            api_base = resolve_local_api_base(cfg, local_model, cfg.local.api_base)
        except Exception:
            failure = PrivacyRouteFailure("local_api", "adapter_error", False, 1, 502)
            log_privacy_failure(failure, response_id)
            return JSONResponse(
                status_code=failure.status_code,
                content=_privacy_error_body(response_id, failure),
            )
    elif policy.requires_masking:
        mask_records = current_records
        try:
            masked_payload = mask_responses_input(
                input_data,
                mask_records,
                instructions=instructions,
                tools=tools,
                tool_choice=tool_choice,
            )
        except Exception:
            failure = privacy_failure("masking_failed", route=policy.endpoint)
            log_privacy_failure(failure, response_id)
            return JSONResponse(
                status_code=failure.status_code,
                content=_privacy_error_body(response_id, failure),
            )

        contract = masked_payload.contract
        forward_messages = responses_input_to_messages(
            masked_payload.value,
            instructions=masked_payload.instructions,
        )
        forward_tools = masked_payload.tools
        forward_tool_choice = masked_payload.tool_choice
    media_fallback_messages = without_uninspected_media(forward_messages) if has_uninspected_media else forward_messages

    temperature = generation_options["temperature"]
    max_tokens = generation_options["max_output_tokens"]
    repairer = None
    if contract is not None and placeholder_repair_enabled():
        try:
            repair_api_base = resolve_local_api_base(
                cfg,
                cfg.local.model,
                cfg.local.api_base,
            )
            repairer = PlaceholderRepairer(cfg.local.model, api_base=repair_api_base)
        except Exception:
            failure = PrivacyRouteFailure("local_api", "adapter_error", False, 1, 502)
            log_privacy_failure(failure, response_id)
            return JSONResponse(
                status_code=failure.status_code,
                content=_privacy_error_body(response_id, failure),
            )

    output_placeholder_registry: dict[str, str] = {}

    async def finalize_tool_call(tool_call: dict[str, str]) -> str:
        validate_tool_call_protocol(
            identifiers=[tool_call["id"], tool_call["call_id"]],
            name=tool_call["name"],
            call_type=tool_call["type"],
            tools=forward_tools,
            allowed_call_types=frozenset({tool_call["allowed_type"]}),
        )
        arguments = tool_call["arguments"]
        protected = await hydrate_tool_call_arguments(
            arguments,
            contract,
            allow_sensitive=allow_sensitive_tool_arguments,
            repairer=repairer,
            masked_messages=forward_messages,
        )
        if policy.endpoint != "local_api":
            return protected
        inspection = build_tool_call_inspection(
            protected,
            identifiers={"id": tool_call["id"], "call_id": tool_call["call_id"]},
            name=tool_call["name"],
        )
        output_pipeline = await run_in_threadpool(router.process, inspection.text)
        reject_sensitive_tool_call_protocol_fields(
            output_pipeline.records,
            is_sensitive=output_pipeline.sensitivity.is_sensitive,
            identifiers=[tool_call["id"], tool_call["call_id"]],
            name=tool_call["name"],
        )
        if allow_sensitive_tool_arguments:
            return protected
        return mask_sensitive_tool_call_arguments(
            protected,
            output_pipeline.records,
            is_sensitive=output_pipeline.sensitivity.is_sensitive,
            placeholder_registry=output_placeholder_registry,
        )

    call_kwargs: dict[str, Any] = {}
    for option in ("top_p", "presence_penalty", "frequency_penalty"):
        if body.get(option) is not None:
            call_kwargs[option] = generation_options[option]
    if body.get("parallel_tool_calls") is not None:
        call_kwargs["parallel_tool_calls"] = generation_options["parallel_tool_calls"]
    if body.get("top_logprobs") is not None:
        call_kwargs["top_logprobs"] = generation_options["top_logprobs"]
        call_kwargs["logprobs"] = True
    if forward_tools:
        call_kwargs["tools"] = forward_tools
    if forward_tool_choice:
        call_kwargs["tool_choice"] = forward_tool_choice

    if stream:
        hydrator = StreamingHydrator(contract)
        created = int(time.time())

        async def _stream_events():
            sequence_number = 0

            def _event(event: str, data: dict[str, Any]) -> str:
                nonlocal sequence_number
                payload = {
                    "type": event,
                    "sequence_number": sequence_number,
                    **data,
                }
                sequence_number += 1
                return _sse_event(event, payload)

            created_response = _build_response(
                response_id,
                raw_model,
                resource_input_data,
                "",
                None,
                privacy_meta,
                request_body=body,
                created_at=created,
                status="in_progress",
                output_items=[],
            )
            yield _event(
                "response.created",
                {"response": created_response},
            )
            yield _event(
                "response.in_progress",
                {"response": created_response},
            )

            def _stream_failure(failure: PrivacyRouteFailure):
                if previous_response_id and volatile_responses is not None:
                    volatile_responses.pop(previous_response_id, None)
                log_privacy_failure(failure, response_id)
                error = public_error_fields(failure, response_id)
                failed_response = _build_response(
                    response_id,
                    raw_model,
                    resource_input_data,
                    "",
                    None,
                    privacy_meta,
                    request_body=body,
                    created_at=created,
                    status="failed",
                    output_items=[],
                    error={
                        "code": error["code"],
                        "message": error["message"],
                        "reason": error["reason"],
                    },
                )
                return _event(
                    "response.failed",
                    {"response": failed_response},
                )

            def _open_stream():
                if not has_uninspected_media:
                    return selected_adapter.call(
                        selected_model,
                        forward_messages,
                        temperature,
                        max_tokens,
                        api_base=api_base,
                        stream=True,
                        **call_kwargs,
                    )

                def _media_fallback_stream():
                    emitted = False
                    try:
                        for part in selected_adapter.call(
                            selected_model,
                            forward_messages,
                            temperature,
                            max_tokens,
                            api_base=api_base,
                            stream=True,
                            **call_kwargs,
                        ):
                            emitted = True
                            yield part
                    except Exception:
                        if emitted:
                            raise
                        yield from selected_adapter.call(
                            selected_model,
                            media_fallback_messages,
                            temperature,
                            max_tokens,
                            api_base=api_base,
                            stream=True,
                            **call_kwargs,
                        )

                return _media_fallback_stream()

            message_id = f"msg_{uuid.uuid4().hex[:24]}"
            message_started = False

            def _message_start_events() -> list[str]:
                nonlocal message_started
                if message_started:
                    return []
                message_started = True
                return [
                    _event(
                        "response.output_item.added",
                        {
                            "output_index": 0,
                            "item": {
                                "id": message_id,
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "status": "in_progress",
                            },
                        },
                    ),
                    _event(
                        "response.content_part.added",
                        {
                            "item_id": message_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                                "logprobs": [],
                            },
                        },
                    ),
                ]

            accumulated = ""
            masked_output_parts: list[str] = []
            stream_tool_calls: dict[int, dict[str, str]] = {}
            explicit_call_id_indices: set[int] = set()
            buffer_content = policy.endpoint == "local_api" or bool(forward_tools) or contract is not None
            buffered_content_parts: list[str] = []
            try:
                stream_parts = execute_fixed_stream(
                    policy,
                    _open_stream,
                    request_id=response_id,
                )
                async for part in iterate_in_threadpool(iter(stream_parts)):
                    delta_obj = part.choices[0].delta
                    delta = getattr(delta_obj, "content", None) or ""
                    if delta:
                        masked_output_parts.append(delta)
                        hydrated_parts = await hydrate_stream_chunk(
                            hydrator,
                            delta,
                            repairer=repairer,
                            masked_messages=forward_messages,
                            masked_output="".join(masked_output_parts),
                        )
                        for hydrated in hydrated_parts:
                            accumulated += hydrated
                            if buffer_content:
                                buffered_content_parts.append(hydrated)
                            else:
                                for event in _message_start_events():
                                    yield event
                                yield _event(
                                    "response.output_text.delta",
                                    {
                                        "item_id": message_id,
                                        "output_index": 0,
                                        "content_index": 0,
                                        "delta": hydrated,
                                    },
                                )
                    for tool_delta in getattr(delta_obj, "tool_calls", None) or []:
                        index = validate_stream_tool_call_index(getattr(tool_delta, "index", 0))
                        tool_call = stream_tool_calls.setdefault(
                            index,
                            {
                                "id": "",
                                "call_id": "",
                                "type": "",
                                "allowed_type": "function",
                                "name": "",
                                "arguments": "",
                            },
                        )
                        raw_id = getattr(tool_delta, "id", None)
                        raw_call_id = getattr(tool_delta, "call_id", None)
                        raw_type = getattr(tool_delta, "type", None)
                        if raw_id:
                            tool_call["id"] += raw_id
                        if raw_call_id:
                            if index not in explicit_call_id_indices:
                                tool_call["call_id"] = ""
                                explicit_call_id_indices.add(index)
                            tool_call["call_id"] += raw_call_id
                        elif raw_id and index not in explicit_call_id_indices:
                            tool_call["call_id"] += raw_id
                        if raw_type is not None:
                            tool_call["type"] = merge_stream_tool_call_type(
                                tool_call["type"],
                                raw_type,
                            )
                        function = getattr(tool_delta, "function", None)
                        if function is not None:
                            tool_call["name"] += getattr(function, "name", None) or ""
                            tool_call["arguments"] += getattr(function, "arguments", None) or ""
                hydrated_parts = await flush_stream_hydrator(
                    hydrator,
                    repairer=repairer,
                    masked_messages=forward_messages,
                    masked_output="".join(masked_output_parts),
                )
                for hydrated in hydrated_parts:
                    accumulated += hydrated
                    if buffer_content:
                        buffered_content_parts.append(hydrated)
                    else:
                        for event in _message_start_events():
                            yield event
                        yield _event(
                            "response.output_text.delta",
                            {
                                "item_id": message_id,
                                "output_index": 0,
                                "content_index": 0,
                                "delta": hydrated,
                            },
                        )
                hydrated_tool_calls = []
                tool_call_indices = validate_stream_tool_call_indices(stream_tool_calls)
                validate_tool_call_identifier_groups(
                    [stream_tool_calls[index]["id"], stream_tool_calls[index]["call_id"]] for index in tool_call_indices
                )
                for index in tool_call_indices:
                    tool_call = stream_tool_calls[index]
                    tool_call["arguments"] = await finalize_tool_call(tool_call)
                    hydrated_tool_calls.append(tool_call)
            except PrivacyRouteFailure as failure:
                yield _stream_failure(failure)
                yield "data: [DONE]\n\n"
                return
            except Exception:
                failure = privacy_failure("hydration_failed", route=policy.endpoint)
                yield _stream_failure(failure)
                yield "data: [DONE]\n\n"
                return
            for hydrated in buffered_content_parts:
                for event in _message_start_events():
                    yield event
                yield _event(
                    "response.output_text.delta",
                    {
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": hydrated,
                    },
                )

            privacy_meta["model_used"] = selected_model
            output_items = []
            if accumulated:
                message_item = _build_output_message(accumulated)
                message_item["id"] = message_id
                output_items.append(message_item)
                yield _event(
                    "response.output_text.done",
                    {
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": accumulated,
                    },
                )
                yield _event(
                    "response.content_part.done",
                    {
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": accumulated,
                            "annotations": [],
                            "logprobs": [],
                        },
                    },
                )
                yield _event(
                    "response.output_item.done",
                    {
                        "output_index": 0,
                        "item": message_item,
                    },
                )
            for tool_call in hydrated_tool_calls:
                output_index = len(output_items)
                item = _build_function_call(tool_call)
                output_items.append(item)
                yield _event(
                    "response.output_item.added",
                    {
                        "output_index": output_index,
                        "item": {
                            **item,
                            "arguments": "",
                            "status": "in_progress",
                        },
                    },
                )
                if tool_call["arguments"]:
                    yield _event(
                        "response.function_call_arguments.delta",
                        {
                            "item_id": item["id"],
                            "output_index": output_index,
                            "delta": tool_call["arguments"],
                        },
                    )
                yield _event(
                    "response.function_call_arguments.done",
                    {
                        "item_id": item["id"],
                        "output_index": output_index,
                        "arguments": tool_call["arguments"],
                    },
                )
                yield _event(
                    "response.output_item.done",
                    {
                        "output_index": output_index,
                        "item": item,
                    },
                )
            completed_response = _build_response(
                response_id,
                raw_model,
                resource_input_data,
                accumulated,
                None,
                privacy_meta,
                request_body=body,
                created_at=created,
                output_items=output_items,
            )
            if body.get("store", True):
                _store_response_resource(completed_response, _auth)
            if volatile_responses is not None:
                volatile_responses[response_id] = completed_response
            yield _event(
                "response.completed",
                {"response": completed_response},
            )
            yield "data: [DONE]\n\n"

        return _stream_events()

    def _invoke():
        try:
            return selected_adapter.call(
                selected_model,
                forward_messages,
                temperature,
                max_tokens,
                api_base=api_base,
                **call_kwargs,
            )
        except Exception:
            if not has_uninspected_media:
                raise
            return selected_adapter.call(
                selected_model,
                media_fallback_messages,
                temperature,
                max_tokens,
                api_base=api_base,
                **call_kwargs,
            )

    try:
        response = await run_in_threadpool(
            execute_fixed_route,
            policy,
            _invoke,
            request_id=response_id,
        )
        content: str = response.choices[0].message.content or ""
        tool_calls = _response_tool_calls(response)
        formatted = selected_adapter.format_response(response, content)
    except PrivacyRouteFailure as failure:
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )
    except Exception:
        failure = PrivacyRouteFailure(policy.endpoint, "adapter_error", False, 1, 502)
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )

    try:
        validate_tool_call_identifier_groups([tool_call["id"], tool_call["call_id"]] for tool_call in tool_calls)
        if contract:
            content = await hydrate_masked_response(
                content,
                contract,
                repairer=repairer,
                masked_messages=forward_messages,
            )
        for tool_call in tool_calls:
            tool_call["arguments"] = await finalize_tool_call(tool_call)
    except Exception:
        failure = privacy_failure("hydration_failed", route=policy.endpoint)
        log_privacy_failure(failure, response_id)
        return JSONResponse(
            status_code=failure.status_code,
            content=_privacy_error_body(response_id, failure),
        )

    privacy_meta["model_used"] = selected_model
    output_items = ([_build_output_message(content)] if content else []) + [
        _build_function_call(tool_call) for tool_call in tool_calls
    ]
    response_body = _build_response(
        response_id,
        raw_model,
        resource_input_data,
        content,
        formatted["usage"],
        privacy_meta,
        request_body=body,
        output_items=output_items,
    )

    if body.get("store", True):
        _store_response_resource(response_body, _auth)
    if volatile_responses is not None:
        volatile_responses[response_id] = response_body

    return JSONResponse(content=response_body)


@app.post("/v1/responses")
async def create_response(
    request: Request,
    _auth: str = Depends(require_auth),
):
    """Create an OpenResponses response over JSON or SSE."""
    response_id = _make_response_id()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                "Request body must be valid JSON",
                code="invalid_request",
            ),
        )
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                "Request body must be a JSON object",
                code="invalid_request",
            ),
        )
    result = await _create_response(
        body,
        _auth,
        request.headers.get("x-chat-id"),
    )
    if isinstance(result, JSONResponse):
        return result
    return StreamingResponse(result, media_type="text/event-stream")


def _sse_payload(frame: str) -> dict[str, Any] | None:
    """Decode one internally generated SSE frame for WebSocket reuse."""
    if frame == "data: [DONE]\n\n":
        return None
    for line in frame.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            return payload if isinstance(payload, dict) else None
    return None


def _websocket_error_event(
    code: str,
    message: str,
    *,
    status: int,
    param: str | None = None,
) -> dict[str, Any]:
    """Build a schema-complete OpenResponses WebSocket error event."""
    return {
        "type": "error",
        "status": status,
        "error": {
            "type": "invalid_request_error",
            "code": code,
            "message": message,
            "param": param,
        },
    }


@app.websocket("/v1/responses")
async def responses_websocket(
    websocket: WebSocket,
    owner_id: str = Depends(require_auth),
):
    """Serve sequential OpenResponses turns over one authenticated WebSocket."""
    await websocket.accept()

    volatile_responses: dict[str, dict[str, Any]] = {}
    try:
        while True:
            try:
                body = json.loads(await websocket.receive_text())
                if not isinstance(body, dict) or body.pop("type", None) != "response.create":
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json(
                    _websocket_error_event(
                        "invalid_request",
                        "Expected a response.create object",
                        status=400,
                    )
                )
                continue

            body["stream"] = True
            result = await _create_response(
                body,
                owner_id,
                websocket.headers.get("x-chat-id"),
                volatile_responses,
            )
            if isinstance(result, JSONResponse):
                previous_response_id = body.get("previous_response_id")
                if isinstance(previous_response_id, str) and previous_response_id:
                    volatile_responses.pop(previous_response_id, None)
                failed = json.loads(result.body)
                error = failed.get("error") or {}
                code = error.get("code", "request_failed")
                param = "previous_response_id" if code == "previous_response_not_found" else error.get("param")
                await websocket.send_json(
                    _websocket_error_event(
                        code,
                        error.get("message", "Request failed"),
                        status=result.status_code,
                        param=param,
                    )
                )
                continue
            async for frame in result:
                payload = _sse_payload(frame)
                if payload is not None:
                    await websocket.send_json(payload)
    except WebSocketDisconnect:
        return


# ── SSE helper ───────────────────────────────────────────────────────────────


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a server-sent event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── GET /v1/responses/{response_id} ──────────────────────────────────────────


@app.get("/v1/responses/{response_id}")
async def get_response(response_id: str, _auth: str = Depends(require_auth)):
    """Retrieve a previously created response."""
    session = get_session()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        stored = session.exec(
            select(ResponseModel).where(
                ResponseModel.id == response_id,
                ResponseModel.owner_id == _auth,
                ResponseModel.storage_encrypted.is_(True),
                ResponseModel.expires_at.is_not(None),
                ResponseModel.expires_at > now,
            )
        ).first()
        if not stored:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "message": f"Response {response_id} not found",
                        "type": "not_found",
                    }
                },
            )
        return JSONResponse(content=json.loads(decrypt_field(stored.output_json)))
    finally:
        session.close()
