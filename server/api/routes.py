"""Privacy Router Server — HTTP API routes.

OpenAI-compatible endpoints:
    ``GET  /v1/models``          — model registry
    ``POST /v1/chat/completions`` — pipeline + backend forwarding
    ``GET  /``                    — interactive web chat UI
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from server.api import STATIC_DIR, app
from server.api.adapter import adapter_for
from server.config import get_config


# ── GET /v1/models ───────────────────────────────────────────────────────────


@app.get("/v1/models")
async def list_models():
    """List available models from the config registry."""
    cfg = get_config()
    return {
        "object": "list",
        "data": [
            {
                "id": f"privacy-router/{m.id}",
                "object": "model",
                "created": 0,
                "owned_by": "privacy-router",
            }
            for m in cfg.models
        ],
    }


# ── POST /v1/chat/completions ───────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint.

    Intercepts the request through the Extractor → Judge → Router
    pipeline before forwarding to the backend model.
    """
    from agents.masker import Masker
    from agents.router import PrivacyRouter

    body = await request.json()

    # ── Extract model and select adapter ─────────────────────────────────
    raw_model: str = body.get("model", "privacy-router/auto")
    backend_model = raw_model
    if raw_model.startswith("privacy-router/"):
        backend_model = raw_model[len("privacy-router/"):]

    if backend_model == "auto":
        cfg = get_config()
        backend_model = cfg.judge.model

    try:
        adapter = adapter_for(backend_model)
    except ValueError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": str(exc),
                    "type": "unknown_backend",
                }
            },
        )
    backend_model = adapter.resolve_backend_model(raw_model)

    messages: list[dict] = body.get("messages", [])
    temperature: float = body.get("temperature", 0.7)
    max_tokens: int = body.get("max_tokens", 256)
    stream: bool = body.get("stream", False)

    user_text = " ".join(
        m["content"] for m in messages if m.get("role") == "user"
    ) or " ".join(m["content"] for m in messages)

    # ── Run Privacy Router pipeline ───────────────────────────────────────
    pr = PrivacyRouter()
    pipeline = pr.process(user_text)
    policy = pipeline.route

    # ── Build privacy metadata ────────────────────────────────────────────
    privacy_meta: dict[str, Any] = {
        "is_sensitive": (
            pipeline.sensitivity.get("is_sensitive", False)
            if isinstance(pipeline.sensitivity, dict)
            else getattr(pipeline.sensitivity, "is_sensitive", False)
        ),
        "records": [],
        "policy_action": policy.endpoint,
        "requires_masking": policy.requires_masking,
        "description": policy.description,
    }

    # ── prompt_user → return 409 with confirmation request ─────────────
    if policy.endpoint == "prompt":
        confirm = request.headers.get("X-Privacy-Router-Confirm", "").lower()
        if confirm not in ("true", "1"):
            from agents.extractor import Extractor as _Ex
            _ext = _Ex()
            _extraction = _ext.extract(user_text)
            privacy_meta["records"] = [
                {"category": r.category, "span": r.span}
                for r in _extraction.records
            ]

            # Build human-readable summary of what was detected
            detected_items = [
                f"  • {r.span}"
                for r in _extraction.records
            ]
            detected_summary = "\n".join(detected_items)

            privacy_meta["action_required"] = "confirm"
            privacy_meta["confirm_message"] = (
                f"이 요청에는 민감한 정보가 포함되어 있습니다:\n\n"
                f"{detected_summary}\n\n"
                f"이 정보를 마스킹하면 AI가 질문의 맥락을 이해할 수 없어\n"
                f"유의미한 답변을 제공하기 어렵습니다.\n\n"
                f"원본 텍스트를 외부 AI 서비스로 전송하면,\n"
                f"위 정보가 해당 서비스에 전달됩니다."
            )
            return JSONResponse(
                status_code=409,
                content={
                    "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": "privacy-router",
                    "error": {
                        "message": policy.description,
                        "type": "privacy_confirmation_required",
                    },
                    "privacy_router": privacy_meta,
                },
            )
        # User confirmed — fall through to send original text to backend

    # ── block → hard block, never forward ────────────────────────────────
    if policy.endpoint == "blocked":
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "privacy-router",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "🚫 이 요청은 완전 차단되었습니다.\n"
                        "민감 정보(주민번호, 비밀번호 등)를 직접 질의하는 요청은\n"
                        "외부 API로 전송할 수 없습니다.\n\n"
                        f"판단 근거: {policy.description}"
                    ),
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "privacy_router": privacy_meta,
        })

    # ── process_locally → local only ─────────────────────────────────────
    if policy.endpoint == "process_locally":
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "privacy-router",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "⚠️ 이 요청은 민감 정보를 직접 질의하고 있어 "
                        "외부 API로 전송되지 않았습니다. "
                        "로컬에서 처리해야 합니다.\n\n"
                        f"판단 근거: {policy.description}"
                    ),
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "privacy_router": privacy_meta,
        })

    # ── mask_and_send or allow — forward to backend ───────────────────────
    forward_messages: list[dict]
    masker: Masker | None = None
    contract: dict[str, Any] = {}

    if policy.requires_masking:
        from agents.extractor import Extractor

        extractor = Extractor()
        extraction = extractor.extract(user_text)
        records_dict = [r.model_dump() for r in extraction.records]

        masker = Masker()
        mask_result = masker.mask(user_text, records_dict)
        masked_text = mask_result.masked_text
        contract = mask_result.contract

        privacy_meta["records"] = [
            {"category": r.category, "span": r.span}
            for r in extraction.records
        ]
        privacy_meta["original_text"] = user_text
        privacy_meta["masked_text"] = masked_text
        privacy_meta["placeholders"] = [
            {"placeholder": r.make_placeholder(i + 1), "category": r.category, "span": r.span}
            for i, r in enumerate(extraction.records)
        ]

        forward_messages = []
        for m in messages:
            if m.get("role") == "user":
                forward_messages.append({**m, "content": masked_text})
            else:
                forward_messages.append(m)
    else:
        forward_messages = messages

    # ── Resolve api_base from config ──────────────────────────────────────
    api_base: str | None = None
    try:
        from config import resolve_model as _resolve
        cfg = get_config()
        spec = _resolve(cfg, backend_model)
        api_base = spec.api_base
    except (KeyError, Exception):
        pass

    # ── Streaming path ────────────────────────────────────────────────────
    if stream:
        from server.api.streaming import StreamingHydrator

        hydrator = StreamingHydrator(contract if policy.requires_masking else None)

        async def _stream():
            chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(time.time())
            try:
                response = adapter.call(
                    backend_model, forward_messages,
                    temperature, max_tokens,
                    api_base=api_base,
                    stream=True,
                )
                for part in response:
                    delta = part.choices[0].delta.content or ""
                    if not delta:
                        continue
                    for hydrated in hydrator.feed(delta):
                        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                for hydrated in hydrator.flush():
                    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'backend_error'}})}\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # ── Non-streaming path ───────────────────────────────────────────────
    try:
        response = adapter.call(
            backend_model, forward_messages,
            temperature, max_tokens,
            api_base=api_base,
        )
        content: str = response.choices[0].message.content or ""
        formatted = adapter.format_response(response, content)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Backend model error: {exc}",
                    "type": "backend_error",
                }
            },
        )

    # Hydrate the response if masking was applied
    if policy.requires_masking and masker is not None and contract:
        try:
            hydrated = masker.hydrate(content, contract)
            content = hydrated.hydrated_text
        except Exception:
            pass

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "privacy-router",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": formatted["finish_reason"],
        }],
        "usage": formatted["usage"],
        "privacy_router": privacy_meta,
    })


# ── GET / — web chat UI ─────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def chat_ui():
    """Serve the interactive web chat UI."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Privacy Router</h1><p>Chat UI not found.</p>")
