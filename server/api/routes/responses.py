"""Privacy Router Server — OpenResponses-compatible endpoint.

Implements the ``/v1/responses`` API compatible with the OpenResponses spec.
The request passes through the same privacy pipeline
(Extractor → Judge → Router → Masker/Hydrator) as ``/v1/chat/completions``.

Endpoints:
    ``POST /v1/responses``              — create a response
    ``GET  /v1/responses/{response_id}`` — retrieve a response (stub)
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agents.extractor import Extractor
from agents.masker import Masker
from agents.router import PrivacyRouter
from server.api.auth import require_auth
from server.api.main import app
from server.api.adapter import adapter_for
from server.config import get_config


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _extract_text_from_input(input_data: str | list[Any]) -> str:
    """Pull plain text from OpenResponses ``input`` field.

    ``input`` may be a bare string or a list of message/content items.
    """
    if isinstance(input_data, str):
        return input_data

    parts: list[str] = []
    for item in input_data:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            # message item → extract content
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "input_text":
                        parts.append(c.get("text", ""))
                    elif isinstance(c, dict) and c.get("type") == "text":
                        parts.append(c.get("text", ""))
                    elif isinstance(c, str):
                        parts.append(c)
            # role="user" items without explicit content — skip
    return " ".join(parts)


def _privacy_metadata(pipeline: Any) -> dict[str, Any]:
    """Build the ``privacy_router`` metadata block from a pipeline result."""
    sens = pipeline.sensitivity
    is_sensitive = (
        sens.get("is_sensitive", False)
        if isinstance(sens, dict)
        else getattr(sens, "is_sensitive", False)
    )
    records_raw = pipeline.records or []
    records = [
        {"category": r.category, "span": r.span}
        for r in records_raw
    ]
    return {
        "is_sensitive": is_sensitive,
        "records": records,
        "policy_action": pipeline.route.endpoint,
    }


def _openai_usage(litellm_usage: dict[str, int] | None) -> dict[str, int]:
    """Translate litellm usage keys to OpenResponses keys."""
    u = litellm_usage or {}
    input_tokens = u.get("prompt_tokens", 0)
    output_tokens = u.get("completion_tokens", 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _build_output_message(text: str) -> dict[str, Any]:
    """Build the single output message item."""
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
        "status": "completed",
    }


def _build_response(
    response_id: str,
    model: str,
    input_data: Any,
    text: str,
    usage: dict[str, int] | None,
    privacy_meta: dict[str, Any],
    *,
    status: str = "completed",
) -> dict[str, Any]:
    """Build an OpenResponses response body."""
    now = int(time.time())
    return {
        "id": response_id,
        "object": "response",
        "created_at": now,
        "completed_at": now,
        "status": status,
        "model": model,
        "input": input_data if isinstance(input_data, list) else [input_data],
        "output": [_build_output_message(text)],
        "metadata": {"privacy_router": privacy_meta},
        "usage": _openai_usage(usage),
    }


def _error_body(response_id: str, message: str) -> dict[str, Any]:
    """Build a failed OpenResponses response."""
    now = int(time.time())
    return {
        "id": response_id,
        "object": "response",
        "created_at": now,
        "completed_at": now,
        "status": "failed",
        "model": "",
        "input": [],
        "output": [],
        "metadata": {},
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "error": {"message": message},
    }


def _resolve_api_base(model_id: str) -> str | None:
    """Resolve api_base for a model from config."""
    from config import resolve_model
    try:
        spec = resolve_model(get_config(), model_id)
        return spec.api_base
    except (KeyError, Exception):
        return None


# ── POST /v1/responses ───────────────────────────────────────────────────────


@app.post("/v1/responses")
async def create_response(request: Request, _auth: str = Depends(require_auth)):
    """OpenResponses-compatible endpoint with privacy pipeline."""
    body = await request.json()
    cfg = get_config()

    raw_model: str = body.get("model", "")
    input_data: str | list = body.get("input", "")
    stream: bool = body.get("stream", False)
    # metadata from caller (unused internally, but round-tripped in response)
    caller_metadata: dict = body.get("metadata", {})

    response_id = _make_response_id()
    user_text = _extract_text_from_input(input_data)

    # ── Resolve model ───────────────────────────────────────────────────
    if raw_model.startswith("privacy-router/"):
        raw_model = raw_model[len("privacy-router/"):]
    backend_model = raw_model if raw_model else cfg.generator.model

    registered_ids = [m.id for m in cfg.models]
    if backend_model not in registered_ids:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                response_id,
                f"Model {backend_model!r} not registered. Available: {registered_ids}",
            ),
        )

    try:
        adapter = adapter_for(backend_model)
    except ValueError as exc:
        return JSONResponse(
            status_code=502,
            content=_error_body(response_id, str(exc)),
        )

    backend_model = adapter.resolve_backend_model(backend_model)

    # ── Run privacy pipeline ────────────────────────────────────────────
    pipeline = PrivacyRouter().process(user_text)
    policy = pipeline.route
    privacy_meta = _privacy_metadata(pipeline)

    # ── block ───────────────────────────────────────────────────────────
    if policy.endpoint == "blocked":
        records = [
            {"category": r.category, "span": r.span}
            for r in (pipeline.records or [])
        ]
        privacy_meta["records"] = records
        detected = "\n".join(f"  • {r['span']}" for r in records)
        text = (
            "🚫 이 요청은 차단되었습니다.\n\n"
            f"탐지된 민감 정보:\n{detected}\n\n"
            f"판단 근거: {policy.description}"
        )
        return JSONResponse(
            content=_build_response(
                response_id, raw_model, input_data, text, None, privacy_meta,
            ),
        )

    # ── prompt_user ─────────────────────────────────────────────────────
    if policy.endpoint == "prompt":
        confirm = request.headers.get("X-Privacy-Router-Confirm", "").lower()
        if confirm not in ("true", "1"):
            records = [
                {"category": r.category, "span": r.span}
                for r in (pipeline.records or [])
            ]
            privacy_meta["records"] = records
            privacy_meta["action_required"] = "confirm"
            text = policy.description
            return JSONResponse(
                status_code=409,
                content=_build_response(
                    response_id, raw_model, input_data, text, None, privacy_meta,
                    status="incomplete",
                ),
            )

    # ── process_locally ─────────────────────────────────────────────────
    if policy.endpoint == "local_api":
        local_model = cfg.local.model
        local_adapter = adapter_for(local_model)
        local_resolved = local_adapter.resolve_backend_model(local_model)
        local_api_base = _resolve_api_base(local_model)

        messages = [{"role": "user", "content": user_text}]

        try:
            local_resp = local_adapter.call(
                local_resolved, messages,
                cfg.local.config.temperature, cfg.local.config.max_tokens,
                api_base=local_api_base,
            )
            local_content = local_resp.choices[0].message.content or ""
            local_fmt = local_adapter.format_response(local_resp, local_content)
        except Exception as exc:
            return JSONResponse(
                status_code=502,
                content=_error_body(response_id, f"Local model error: {exc}"),
            )

        privacy_meta["model_used"] = local_model
        return JSONResponse(
            content=_build_response(
                response_id, raw_model, input_data,
                local_content, local_fmt["usage"], privacy_meta,
            ),
        )

    # ── mask_and_send / allow — forward to backend ──────────────────────
    contract = None
    forward_messages: list[dict[str, str]] = [{"role": "user", "content": user_text}]

    if policy.requires_masking:
        ext = Extractor()
        extraction = ext.extract(user_text)
        records_dict = [r.model_dump() for r in extraction.records]

        masker = Masker()
        mask_result = masker.mask(user_text, records_dict)
        contract = mask_result.contract

        privacy_meta["records"] = [
            {"category": r.category, "span": r.span} for r in extraction.records
        ]
        privacy_meta["original_text"] = user_text
        privacy_meta["masked_text"] = mask_result.masked_text

        forward_messages = [{"role": "user", "content": mask_result.masked_text}]

    api_base = _resolve_api_base(backend_model)
    temperature = 0.7
    max_tokens = 4096

    # ── Streaming ───────────────────────────────────────────────────────
    if stream:
        from server.api.streaming import StreamingHydrator

        hydrator = StreamingHydrator(contract)
        created = int(time.time())

        async def _stream_events():
            # response.created
            yield _sse_event("response.created", {
                "id": response_id,
                "object": "response",
                "created_at": created,
                "status": "in_progress",
                "model": raw_model,
            })

            # response.output_item.added
            yield _sse_event("response.output_item.added", {
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
            })

            # response.content_part.added
            yield _sse_event("response.content_part.added", {
                "type": "output_text",
                "text": "",
            })

            accumulated = ""

            try:
                response = adapter.call(
                    backend_model, forward_messages,
                    temperature, max_tokens, api_base=api_base, stream=True,
                )
                for part in response:
                    delta = part.choices[0].delta.content or ""
                    if not delta:
                        continue
                    for hydrated in hydrator.feed(delta):
                        accumulated += hydrated
                        yield _sse_event("response.output_text.delta", {
                            "delta": hydrated,
                        })

                for hydrated in hydrator.flush():
                    accumulated += hydrated
                    yield _sse_event("response.output_text.delta", {
                        "delta": hydrated,
                    })

                # Hydrate accumulated text for metadata
                final_text = accumulated
                if contract:
                    try:
                        final_text = Masker().hydrate(accumulated, contract).hydrated_text
                    except Exception:
                        pass

            except Exception as exc:
                yield _sse_event("response.failed", {
                    "error": {"message": str(exc)},
                })
                yield "data: [DONE]\n\n"
                return

            # response.output_text.done
            yield _sse_event("response.output_text.done", {
                "text": final_text,
            })

            # response.content_part.done
            yield _sse_event("response.content_part.done", {
                "type": "output_text",
                "text": final_text,
            })

            # response.output_item.done
            yield _sse_event("response.output_item.done", {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": final_text}],
                "status": "completed",
            })

            # response.completed
            privacy_meta["model_used"] = backend_model
            yield _sse_event("response.completed", {
                "id": response_id,
                "object": "response",
                "created_at": created,
                "completed_at": int(time.time()),
                "status": "completed",
                "model": raw_model,
                "output": [_build_output_message(final_text)],
                "metadata": {"privacy_router": privacy_meta},
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            })

            yield "data: [DONE]\n\n"

        return StreamingResponse(_stream_events(), media_type="text/event-stream")

    # ── Non-streaming ───────────────────────────────────────────────────
    try:
        response = adapter.call(
            backend_model, forward_messages,
            temperature, max_tokens, api_base=api_base,
        )
        content: str = response.choices[0].message.content or ""
        formatted = adapter.format_response(response, content)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content=_error_body(response_id, f"Backend model error: {exc}"),
        )

    # Hydrate masked response
    if policy.requires_masking and contract:
        try:
            hydrated = Masker().hydrate(content, contract)
            content = hydrated.hydrated_text
        except Exception:
            pass

    privacy_meta["model_used"] = backend_model

    # Store response in DB
    try:
        from db.models import Response
        from db.session import get_session
        resp_data = _build_response(
            response_id, raw_model, input_data,
            content, formatted["usage"], privacy_meta,
        )
        session = get_session()
        try:
            stored = Response(
                id=response_id,
                model=raw_model,
                output_text=content,
                output_json=json.dumps(resp_data),
                status="completed",
            )
            session.add(stored)
            session.commit()
        finally:
            session.close()
    except Exception:
        pass
    return JSONResponse(
        content=_build_response(
            response_id, raw_model, input_data,
            content, formatted["usage"], privacy_meta,
        ),
    )


# ── SSE helper ───────────────────────────────────────────────────────────────


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a server-sent event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── GET /v1/responses/{response_id} ──────────────────────────────────────────


@app.get("/v1/responses/{response_id}")
async def get_response(response_id: str, _auth: str = Depends(require_auth)):
    """Retrieve a previously created response."""
    from db.models import Response as ResponseModel
    from db.session import get_session
    from sqlmodel import select

    session = get_session()
    try:
        stored = session.exec(
            select(ResponseModel).where(ResponseModel.id == response_id)
        ).first()
        if not stored:
            return JSONResponse(
                status_code=404,
                content={"error": {"message": f"Response {response_id} not found", "type": "not_found"}},
            )
        import json as _json
        return JSONResponse(content=_json.loads(stored.output_json))
    finally:
        session.close()