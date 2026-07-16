"""Privacy Router Server — HTTP API routes.

Endpoints:
    ``GET  /v1/models``           — OpenAI-compatible model registry
    ``POST /v1/chat/completions``  — OpenAI-compatible chat (pipeline + forwarding)
    ``GET  /``                     — interactive web chat UI
"""

from __future__ import annotations

import datetime
import json
import os
import time
import uuid
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select, text
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

import server.config as server_cfg
from agents import (
    ContractStore,
    PipelineResult,
    PlaceholderRepairer,
    PrivacyRouteFailure,
    PrivacyRouter,
    encrypt_field,
    execute_fixed_route,
    execute_fixed_stream,
    get_cache,
    key_fingerprint,
    log_privacy_failure,
    placeholder_repair_enabled,
    privacy_failure,
    public_error_fields,
    redact_extraction_records,
)
from config import resolve_api_base, resolve_local_api_base, resolve_model
from db import (
    Model,
    Profile,
    ProfileAgent,
    Provider,
    UsageLog,
    Workspace,
    engine,
    get_session,
)
from server.api import (
    STATIC_DIR,
    StreamingHydrator,
    adapter_for,
    app,
    build_tool_call_inspection,
    chat_context_segments,
    chat_context_text,
    contains_uninspected_media,
    flush_stream_hydrator,
    hydrate_masked_response,
    hydrate_stream_chunk,
    hydrate_tool_call_arguments,
    mask_chat_messages,
    mask_sensitive_tool_call_arguments,
    merge_context_segments,
    merge_stream_tool_call_type,
    reject_sensitive_tool_call_protocol_fields,
    render_context_segments,
    require_admin_auth,
    require_auth,
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


def _make_chat_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _log_usage(
    event: str,
    is_sensitive: bool,
    records_count: int,
    policy_action: str | None,
    model_used: str | None,
    latency_ms: float,
) -> None:
    """Record a usage log entry (never fails the request)."""
    try:
        session = get_session()
        try:
            log = UsageLog(
                event=event,
                is_sensitive=is_sensitive,
                records_count=records_count,
                policy_action=policy_action,
                model_used=model_used,
                latency_ms=latency_ms,
            )
            session.add(log)
            session.commit()
        finally:
            session.close()
    except Exception:
        pass


def _sensitivity_meta(
    pipeline: PipelineResult,
    visible_records: list[Any],
) -> dict[str, Any]:
    """Build response metadata without echoing prior-only session values."""
    records = redact_extraction_records(visible_records)
    return {
        "is_sensitive": pipeline.sensitivity.is_sensitive,
        "extraction_records": records,
        "policy_action": pipeline.judgment.policy_action,
        "route": pipeline.route.endpoint,
    }


def _chat_response(
    content: str,
    finish_reason: str = "stop",
    usage: dict[str, int] | None = None,
    privacy_meta: dict[str, Any] | None = None,
    status_code: int = 200,
) -> JSONResponse:
    """Build a standard chat completion JSON response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "id": _make_chat_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "privacy-router",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "privacy_router": privacy_meta or {},
        },
    )


def _error_response(status_code: int, message: str, error_type: str) -> JSONResponse:
    """Build a standard error JSON response."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
    )


def _privacy_error_response(failure: PrivacyRouteFailure, request_id: str) -> JSONResponse:
    """Build a raw-free error for an already protected request."""
    return JSONResponse(
        status_code=failure.status_code,
        content={"error": public_error_fields(failure, request_id)},
    )


# ── GET /v1/models ───────────────────────────────────────────────────────────


@app.get("/v1/models")
async def list_models():
    """List available models from the config registry."""
    cfg = get_config()
    external_models = [model for model in cfg.models if model.location == "external"]
    return {
        "object": "list",
        "data": [
            {
                "id": "privacy-router" if model is None else f"privacy-router/{model.id}",
                "object": "model",
                "created": 0,
                "owned_by": "privacy-router",
            }
            for model in [None, *external_models]
        ],
    }


# ── GET /api/settings (public, for demo UI) ──────────────────────────────


@app.get("/api/settings")
async def get_settings(_admin: str = Depends(require_admin_auth)):
    """Return agent config for the demo web UI (no auth required).

    Returns resolved config (post-profile-override) with profile metadata.
    """
    cfg = get_config()
    return {
        "models": [
            {
                "model_id": m.id,
                "display_name": m.id,
                "provider_id": m.id.split("/", 1)[0],
                "location": m.location,
                "tier": m.tier,
                "cost_per_1m_tokens": m.cost_per_1m_tokens,
                "api_base": m.api_base,
            }
            for m in cfg.models
        ],
        "decision": cfg.decision.model_dump(),
        "local": cfg.local.model_dump(),
        "external": cfg.external.model_dump(),
        "profiles": {
            "active": cfg.active_profile,
            "available": {name: {"description": p.description} for name, p in cfg.profiles.items()},
        },
    }


# ── GET /api/providers ─────────────────────────────────────────────────────


@app.get("/api/providers")
async def list_providers(_admin: str = Depends(require_admin_auth)):
    """List available model providers (key values masked)."""
    session = get_session()
    try:
        providers = session.exec(select(Provider)).all()
        result = []
        for p in providers:
            has_key = bool(p.encrypted_api_key)
            has_env = bool(p.api_key_env) and os.environ.get(p.api_key_env)
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "api_base": p.api_base,
                    "has_key": has_key or has_env,
                    "key_fingerprint": p.key_fingerprint,
                    "source": "db" if has_key else ("env" if has_env else "none"),
                    "api_key_env": p.api_key_env,
                }
            )
        return {"providers": result}
    finally:
        session.close()


# ── POST /api/providers/{provider_id}/key ──────────────────────────────────


class ProviderKeySet(BaseModel):
    api_key: str = Field(..., min_length=8)


@app.post("/api/providers/{provider_id}/key")
def set_provider_key(
    provider_id: str,
    body: ProviderKeySet,
    _admin: str = Depends(require_admin_auth),
):
    """Encrypt and store an API key for a provider."""
    with server_cfg.config_write_lock():
        session = get_session()
        try:
            provider = session.get(Provider, provider_id)
            if not provider:
                raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

            provider.encrypted_api_key = encrypt_field(body.api_key)
            provider.key_fingerprint = key_fingerprint(body.api_key)
            provider.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            session.add(provider)
            session.commit()
            session.refresh(provider)

            return {
                "status": "ok",
                "provider_id": provider_id,
                "key_fingerprint": provider.key_fingerprint,
            }
        finally:
            session.close()


# ── DELETE /api/providers/{provider_id}/key ─────────────────────────────────


@app.delete("/api/providers/{provider_id}/key")
def delete_provider_key(
    provider_id: str,
    _admin: str = Depends(require_admin_auth),
):
    """Remove the stored API key for a provider."""
    with server_cfg.config_write_lock():
        session = get_session()
        try:
            provider = session.get(Provider, provider_id)
            if not provider:
                raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

            provider.encrypted_api_key = None
            provider.key_fingerprint = None
            provider.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            session.add(provider)
            session.commit()

            return {"status": "ok", "provider_id": provider_id}
        finally:
            session.close()


@app.post("/api/settings")
def update_settings(
    body: dict[str, Any],
    _admin: str = Depends(require_admin_auth),
):
    """Update agent config. Persists to SQLite."""

    with server_cfg.config_write_lock():
        session = get_session()
        try:
            ws = session.exec(select(Workspace).where(Workspace.id == "default")).first()
            profile_id = (ws.active_profile if ws else None) or "default"

            for agent_name in ("decision", "local", "external"):
                if agent_name not in body:
                    continue
                entry = body[agent_name]
                model_id = entry.get("model")
                if model_id:
                    model_row = session.get(Model, model_id)
                    if model_row is None:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Model '{model_id}' is not registered",
                        )
                    expected_location = "external" if agent_name == "external" else "local"
                    if model_row.location != expected_location:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"{agent_name} model must be {expected_location}, got {model_row.location}: {model_id}"
                            ),
                        )

                pa = session.exec(
                    select(ProfileAgent)
                    .where(ProfileAgent.profile_id == profile_id)
                    .where(ProfileAgent.agent_name == agent_name)
                ).first()

                if pa is None:
                    pa = ProfileAgent(
                        profile_id=profile_id,
                        agent_name=agent_name,
                        model_id=entry.get("model", ""),
                    )
                    session.add(pa)

                if "model" in entry:
                    pa.model_id = entry["model"]
                if "temperature" in entry:
                    pa.temperature = entry["temperature"]
                if "max_tokens" in entry:
                    pa.max_tokens = entry["max_tokens"]

            session.commit()
        finally:
            session.close()

        server_cfg.invalidate_config_cache()
        return {"status": "ok"}


# ── GET /api/profiles ──────────────────────────────────────────────────────


@app.get("/api/profiles")
async def list_profiles(_admin: str = Depends(require_admin_auth)):
    """List available profiles and the currently active one."""
    cfg = get_config()
    return {
        "active": cfg.active_profile,
        "available": {
            name: {
                "description": p.description,
                "decision": p.decision.model if p.decision else None,
                "local": p.local.model if p.local else None,
                "external": p.external.model if p.external else None,
            }
            for name, p in cfg.profiles.items()
        },
    }


# ── POST /api/profiles/activate ────────────────────────────────────────────


@app.post("/api/profiles/activate")
def activate_profile(
    body: dict[str, Any],
    _admin: str = Depends(require_admin_auth),
):
    """Activate a profile. Persists to SQLite."""
    profile_name = body.get("profile")

    if not profile_name:
        raise HTTPException(status_code=400, detail="Missing 'profile' field")

    with server_cfg.config_write_lock():
        cfg = get_config()
        if profile_name not in cfg.profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Profile '{profile_name}' not found. Available: {list(cfg.profiles.keys())}",
            )

        session = get_session()
        try:
            ws = session.exec(select(Workspace).where(Workspace.id == "default")).first()
            if ws:
                ws.active_profile = profile_name
                session.add(ws)

            profiles = session.exec(select(Profile)).all()
            for profile in profiles:
                profile.is_active = profile.id == profile_name
                session.add(profile)

            session.commit()
        finally:
            session.close()

        os.environ["PRIVACY_ROUTER_PROFILE"] = profile_name
        server_cfg.invalidate_config_cache()

        cfg = get_config()
        return {
            "status": "ok",
            "active_profile": profile_name,
            "decision": cfg.decision.model_dump(),
            "local": cfg.local.model_dump(),
            "external": cfg.external.model_dump(),
        }


# ── POST /v1/chat/completions ───────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, _auth: str = Depends(require_auth)):
    """OpenAI-compatible chat completions with a fail-closed privacy route."""
    body = await request.json()
    allow_sensitive_tool_arguments = sensitive_tool_arguments_allowed(body)
    cfg = get_config()
    messages: list[dict] = body.get("messages", [])
    temperature: float = body.get("temperature", 0.7)
    max_tokens: int = body.get("max_tokens", 256)
    stream: bool = body.get("stream", False)
    tools: list | None = body.get("tools")
    tool_choice: str | dict | None = body.get("tool_choice")
    request_id = _make_chat_id()
    try:
        chat_id = session_cache_key(_auth, request.headers.get("x-chat-id"))
    except ValueError as exc:
        return _error_response(400, str(exc), "invalid_request")
    current_context = chat_context_segments(
        messages,
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
        log_privacy_failure(failure, request_id)
        return _privacy_error_response(failure, request_id)

    raw_model: str = body.get("model", "")
    if raw_model.startswith("privacy-router/"):
        raw_model = raw_model[len("privacy-router/") :]
    backend_model = cfg.external.model if raw_model == "privacy-router" or not raw_model else raw_model

    registered_ids = [model.id for model in cfg.models]
    if backend_model not in registered_ids:
        return _error_response(
            400,
            f"Model {backend_model!r} not registered. Available: {registered_ids}",
            "invalid_model",
        )
    if resolve_model(cfg, backend_model).location != "external":
        return _error_response(
            400,
            f"Model {backend_model!r} is reserved for on-device processing",
            "invalid_model_location",
        )

    registered_model_id = backend_model
    try:
        adapter = adapter_for(backend_model)
        backend_model = adapter.resolve_backend_model(backend_model)
    except Exception:
        failure = PrivacyRouteFailure("unresolved", "adapter_error", False, 1, 502)
        log_privacy_failure(failure, request_id)
        return _privacy_error_response(failure, request_id)

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
        log_privacy_failure(failure, request_id)
        return _privacy_error_response(failure, request_id)

    policy = pipeline.route
    if policy.endpoint not in ("local_api", "external_api"):
        failure = privacy_failure("route_invariant_failed")
        log_privacy_failure(failure, request_id)
        return _privacy_error_response(failure, request_id)

    has_uninspected_media = contains_uninspected_media(messages)
    media_forced_local = has_uninspected_media and policy.endpoint != "local_api"
    if media_forced_local:
        policy = policy.model_copy(
            update={
                "endpoint": "local_api",
                "requires_masking": False,
                "description": "검사할 수 없는 미디어가 포함되어 로컬 처리",
            }
        )

    current_records = [
        record
        for record in pipeline.records
        if record.span and any(record.span in segment.text for segment in current_context)
    ]
    meta = _sensitivity_meta(pipeline, current_records)
    effective_policy_action = pipeline.judgment.policy_action
    if media_forced_local:
        effective_policy_action = "block"
        meta["policy_action"] = "block"
        meta["route"] = "local_api"
    n_records = len(pipeline.records)
    _log_usage(
        "chat_completions",
        bool(n_records),
        n_records,
        effective_policy_action,
        backend_model,
        0,
    )

    selected_adapter = adapter
    selected_model = backend_model
    selected_temperature = temperature
    selected_max_tokens = max_tokens
    api_base: str | None
    forward_messages = messages
    contract = None
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
            log_privacy_failure(failure, request_id)
            return _privacy_error_response(failure, request_id)
        selected_temperature = cfg.local.config.temperature
        selected_max_tokens = cfg.local.config.max_tokens
    else:
        configured_api_base = cfg.external.api_base if registered_model_id == cfg.external.model else None
        try:
            api_base = resolve_api_base(cfg, registered_model_id, configured_api_base)
        except Exception:
            failure = PrivacyRouteFailure("external_api", "adapter_error", False, 1, 502)
            log_privacy_failure(failure, request_id)
            return _privacy_error_response(failure, request_id)
        if policy.requires_masking:
            mask_records = current_records
            try:
                records_dict = [record.model_dump() for record in mask_records]
                masked_payload = mask_chat_messages(
                    messages,
                    mask_records,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                contract = masked_payload.contract
                store = ContractStore()
                masking_session_id = store.create_session(
                    chat_id=chat_id,
                    record_count=len(mask_records),
                    policy_action=pipeline.judgment.policy_action,
                    owner_id=_auth,
                )
                store.save_records(
                    session_id=masking_session_id,
                    records=records_dict,
                    placeholder_map=contract.placeholder_map,
                )
            except Exception:
                failure = privacy_failure("masking_failed", route="external_api")
                log_privacy_failure(failure, request_id)
                return _privacy_error_response(failure, request_id)

            masking_records_out = []
            for placeholder, original in contract.placeholder_map.items():
                matching = next(
                    (record for record in mask_records if record.span == original),
                    None,
                )
                masking_records_out.append(
                    {
                        "uid": placeholder.strip("[]").partition("#")[2],
                        "category": matching.category if matching else "UNKNOWN",
                        "confidence": matching.confidence if matching else 0.0,
                        "is_essential": (matching.is_essential if matching else False),
                    }
                )
            meta["masked_text"] = chat_context_text(
                masked_payload.value,
                tools=masked_payload.tools,
                tool_choice=masked_payload.tool_choice,
            )
            meta["masking_session_id"] = masking_session_id
            meta["placeholder_map"] = masking_records_out
            forward_messages = masked_payload.value
            forward_tools = masked_payload.tools
            forward_tool_choice = masked_payload.tool_choice

    call_kwargs: dict[str, Any] = {}
    if forward_tools:
        call_kwargs["tools"] = forward_tools
    if forward_tool_choice:
        call_kwargs["tool_choice"] = forward_tool_choice

    media_fallback_messages = without_uninspected_media(forward_messages) if has_uninspected_media else forward_messages

    def call_selected(*, streaming: bool = False):
        selected_kwargs = dict(call_kwargs)
        if streaming:
            selected_kwargs["stream"] = True
        try:
            return selected_adapter.call(
                selected_model,
                forward_messages,
                selected_temperature,
                selected_max_tokens,
                api_base=api_base,
                **selected_kwargs,
            )
        except Exception:
            if policy.endpoint != "local_api" or not has_uninspected_media:
                raise
            return selected_adapter.call(
                selected_model,
                media_fallback_messages,
                selected_temperature,
                selected_max_tokens,
                api_base=api_base,
                **selected_kwargs,
            )

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
            log_privacy_failure(failure, request_id)
            return _privacy_error_response(failure, request_id)

    output_placeholder_registry: dict[str, str] = {}

    async def finalize_tool_call(
        *,
        call_id: str,
        call_type: str,
        name: str,
        arguments: str,
    ) -> str:
        validate_tool_call_protocol(
            identifiers=[call_id],
            name=name,
            call_type=call_type,
            tools=forward_tools,
        )
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
            identifiers={"id": call_id},
            name=name,
        )
        output_pipeline = await run_in_threadpool(router.process, inspection.text)
        reject_sensitive_tool_call_protocol_fields(
            output_pipeline.records,
            is_sensitive=output_pipeline.sensitivity.is_sensitive,
            identifiers=[call_id],
            name=name,
        )
        if allow_sensitive_tool_arguments:
            return protected
        return mask_sensitive_tool_call_arguments(
            protected,
            output_pipeline.records,
            is_sensitive=output_pipeline.sensitivity.is_sensitive,
            placeholder_registry=output_placeholder_registry,
        )

    if stream:
        hydrator = StreamingHydrator(contract)

        def open_stream():
            return call_selected(streaming=True)

        async def response_stream():
            chunk_id = request_id
            created = int(time.time())
            masked_output_parts: list[str] = []
            stream_tool_calls: dict[int, dict[str, Any]] = {}
            buffer_content = policy.endpoint == "local_api" or bool(forward_tools) or contract is not None
            buffered_content_parts: list[str] = []
            try:
                stream_parts = execute_fixed_stream(
                    policy,
                    open_stream,
                    request_id=request_id,
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
                            if buffer_content:
                                buffered_content_parts.append(hydrated)
                            else:
                                yield (
                                    f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                                )
                    for tool_delta in getattr(delta_obj, "tool_calls", None) or []:
                        index = validate_stream_tool_call_index(getattr(tool_delta, "index", 0))
                        tool_call = stream_tool_calls.setdefault(
                            index,
                            {
                                "id": "",
                                "type": "",
                                "name": "",
                                "arguments": "",
                            },
                        )
                        if getattr(tool_delta, "id", None):
                            tool_call["id"] += tool_delta.id
                        raw_type = getattr(tool_delta, "type", None)
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
                    if buffer_content:
                        buffered_content_parts.append(hydrated)
                    else:
                        yield (
                            f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                        )
                hydrated_tool_calls = []
                tool_call_indices = validate_stream_tool_call_indices(stream_tool_calls)
                validate_tool_call_identifier_groups([stream_tool_calls[index]["id"]] for index in tool_call_indices)
                for index in tool_call_indices:
                    tool_call = stream_tool_calls[index]
                    hydrated_tool_calls.append(
                        {
                            "index": index,
                            "id": tool_call["id"],
                            "type": "function",
                            "function": {
                                "name": tool_call["name"],
                                "arguments": await finalize_tool_call(
                                    call_id=tool_call["id"],
                                    call_type=tool_call["type"],
                                    name=tool_call["name"],
                                    arguments=tool_call["arguments"],
                                ),
                            },
                        }
                    )
                for hydrated in buffered_content_parts:
                    yield (
                        f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                    )
                if hydrated_tool_calls:
                    yield (
                        f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'tool_calls': hydrated_tool_calls}, 'finish_reason': None}]})}\n\n"
                    )
                yield (
                    f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if stream_tool_calls else 'stop'}]})}\n\n"
                )
            except PrivacyRouteFailure as failure:
                yield f"data: {json.dumps({'error': public_error_fields(failure, request_id)})}\n\n"
            except Exception:
                failure = privacy_failure("hydration_failed", route=policy.endpoint)
                log_privacy_failure(failure, request_id)
                yield f"data: {json.dumps({'error': public_error_fields(failure, request_id)})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(response_stream(), media_type="text/event-stream")

    def invoke():
        return call_selected()

    try:
        response = execute_fixed_route(policy, invoke, request_id=request_id)
        message = response.choices[0].message
        raw_content = message.content
        content: str = raw_content or ""
        tool_calls = getattr(message, "tool_calls", None)
        formatted = selected_adapter.format_response(response, content)
    except PrivacyRouteFailure as failure:
        return _privacy_error_response(failure, request_id)
    except Exception:
        failure = PrivacyRouteFailure(policy.endpoint, "adapter_error", False, 1, 502)
        log_privacy_failure(failure, request_id)
        return _privacy_error_response(failure, request_id)

    if policy.requires_masking and contract and raw_content is not None:
        try:
            content = await hydrate_masked_response(
                content,
                contract,
                repairer=repairer,
                masked_messages=forward_messages,
            )
        except Exception:
            failure = privacy_failure("hydration_failed", route="external_api")
            log_privacy_failure(failure, request_id)
            return _privacy_error_response(failure, request_id)

    meta["model_used"] = selected_model
    if tool_calls:
        try:
            validate_tool_call_identifier_groups([tool_call.id] for tool_call in tool_calls)
            tool_call_items = []
            for tool_call in tool_calls:
                tool_call_items.append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": await finalize_tool_call(
                                call_id=tool_call.id,
                                call_type=tool_call.type,
                                name=tool_call.function.name,
                                arguments=tool_call.function.arguments,
                            ),
                        },
                    }
                )
        except Exception:
            failure = privacy_failure("hydration_failed", route=policy.endpoint)
            log_privacy_failure(failure, request_id)
            return _privacy_error_response(failure, request_id)
        return JSONResponse(
            status_code=200,
            content={
                "id": request_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "privacy-router",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content if raw_content is not None else None,
                            "tool_calls": tool_call_items,
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": formatted["usage"],
                "privacy_router": meta,
            },
        )

    return _chat_response(content, formatted["finish_reason"], formatted["usage"], meta)


# ── GET / — landing page ─────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def landing_page():
    """Serve the landing page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Privacy Router</h1><p>Landing page not found.</p>")


# ── GET /demo — web chat UI ──────────────────────────────────────────────────


@app.get("/demo", response_class=HTMLResponse)
async def chat_ui():
    """Serve the interactive web chat UI."""
    html_path = STATIC_DIR / "demo.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Privacy Router</h1><p>Chat UI not found.</p>")


@app.get("/admin", response_class=HTMLResponse)
async def admin_ui():
    """Serve the admin dashboard."""
    html_path = STATIC_DIR / "admin.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Privacy Router Admin</h1><p>Admin UI not found.</p>")


# ── Dashboard Data API ─────────────────────────────────────────────────────


@app.get("/api/v1/dashboard-data")
async def dashboard_data(_admin: str = Depends(require_admin_auth)):
    """Return all data needed for the usage log dashboard.

    Reads from the database and returns:
    - usage_logs: all log entries
    - masking_records: all masking records linked to sessions
    - masking_sessions: all masking sessions
    - summary: aggregated stats
    """
    with Session(engine) as s:
        # Usage logs
        logs = (
            s.exec(
                text(
                    "SELECT id, event, is_sensitive, records_count, policy_action, "
                    "model_used, latency_ms, status_code, "
                    "to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at "
                    "FROM usage_logs ORDER BY created_at"
                )
            )
            .mappings()
            .all()
        )

        # Masking sessions with records
        sessions = (
            s.exec(
                text(
                    "SELECT ms.id, ms.record_count, ms.policy_action, "
                    "to_char(ms.created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at "
                    "FROM masking_sessions ms ORDER BY ms.created_at"
                )
            )
            .mappings()
            .all()
        )

        # Masking records
        records = (
            s.exec(
                text(
                    "SELECT mr.id, mr.session_id, mr.category, mr.span, mr.placeholder, "
                    "mr.confidence, mr.is_essential "
                    "FROM masking_records mr ORDER BY mr.confidence DESC"
                )
            )
            .mappings()
            .all()
        )

        # Summary stats
        summary = (
            s.exec(
                text(
                    "SELECT "
                    "COUNT(*) as total, "
                    "SUM(CASE WHEN is_sensitive THEN 1 ELSE 0 END) as sensitive, "
                    "SUM(CASE WHEN NOT is_sensitive THEN 1 ELSE 0 END) as safe, "
                    "SUM(CASE WHEN policy_action = 'block' THEN 1 ELSE 0 END) as routed_local, "
                    "SUM(CASE WHEN policy_action = 'selective_mask' THEN 1 ELSE 0 END) as masked_sent, "
                    "SUM(CASE WHEN policy_action = 'allow' THEN 1 ELSE 0 END) as allowed "
                    "FROM usage_logs"
                )
            )
            .mappings()
            .one()
        )

        # Daily breakdown
        daily = (
            s.exec(
                text(
                    "SELECT "
                    "to_char(created_at, 'MM-DD') as date, "
                    "COUNT(*) as total, "
                    "SUM(CASE WHEN is_sensitive THEN 1 ELSE 0 END) as sensitive, "
                    "SUM(CASE WHEN NOT is_sensitive THEN 1 ELSE 0 END) as safe, "
                    "SUM(CASE WHEN policy_action = 'block' THEN 1 ELSE 0 END) as routed_local, "
                    "SUM(CASE WHEN policy_action = 'selective_mask' THEN 1 ELSE 0 END) as masked_sent, "
                    "SUM(CASE WHEN policy_action = 'allow' THEN 1 ELSE 0 END) as allowed "
                    "FROM usage_logs "
                    "GROUP BY to_char(created_at, 'MM-DD') "
                    "ORDER BY to_char(created_at, 'MM-DD')"
                )
            )
            .mappings()
            .all()
        )

    # Group records by session_id
    records_by_session = {}
    for r in records:
        sid = r["session_id"]
        if sid not in records_by_session:
            records_by_session[sid] = []
        records_by_session[sid].append(dict(r))

    return JSONResponse(
        {
            "summary": dict(summary),
            "daily": [dict(d) for d in daily],
            "logs": [dict(log) for log in logs],
            "sessions": [dict(s) for s in sessions],
            "records_by_session": records_by_session,
        }
    )
