"""Privacy Router Server — HTTP API routes.

Endpoints:
    ``GET  /v1/models``           — OpenAI-compatible model registry
    ``POST /v1/chat/completions``  — OpenAI-compatible chat (pipeline + forwarding)
    ``GET  /``                     — interactive web chat UI
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from agents.extractor import Extractor
from agents.masker import Masker
from agents.router import PrivacyRouter
from server.api import STATIC_DIR
from server.api.main import app
from server.api.adapter import adapter_for
from server.config import get_config
from server.api.auth import require_auth
from server.observability import timed_span, pii_detected, pii_masked
import hashlib


# ── Helpers ──────────────────────────────────────────────────────────────────


def _extract_records(text: str) -> list[dict[str, str]]:
    """Extract sensitive records from text."""
    ext = Extractor()
    result = ext.extract(text)
    return [{"category": r.category, "span": r.span} for r in result.records]


def _make_chat_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _resolve_api_base(model_id: str) -> str | None:
    """Resolve api_base for a model from config."""
    from config import resolve_model
    try:
        spec = resolve_model(get_config(), model_id)
        return spec.api_base
    except (KeyError, Exception):
        return None


def _log_usage(
    event: str,
    text: str,
    is_sensitive: bool,
    records_count: int,
    policy_action: str | None,
    model_used: str | None,
    latency_ms: float,
) -> None:
    """Record a usage log entry (never fails the request)."""
    try:
        from db.models import UsageLog
        from db.session import get_session

        session = get_session()
        try:
            log = UsageLog(
                event=event,
                input_hash=hashlib.sha256(text.encode()).hexdigest()[:16],
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


def _sensitivity_meta(pipeline: Any) -> dict[str, Any]:
    """Build privacy metadata from pipeline result."""
    sens = pipeline.sensitivity
    is_sensitive = (
        sens.get("is_sensitive", False)
        if isinstance(sens, dict)
        else getattr(sens, "is_sensitive", False)
    )
    return {
        "is_sensitive": is_sensitive,
        "records": [],
        "policy_action": pipeline.route.endpoint,
        "requires_masking": pipeline.route.requires_masking,
        "description": pipeline.route.description,
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
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }],
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


# ── GET /api/settings (public, for demo UI) ──────────────────────────────


@app.get("/api/settings")
async def get_settings():
    """Return agent config for the demo web UI (no auth required)."""
    cfg = get_config()
    return {
        "models": [
            {"id": m.id, "tier": m.tier, "cost_per_1m_tokens": m.cost_per_1m_tokens, "api_base": m.api_base}
            for m in cfg.models
        ],
        "extractor": {"model": cfg.extractor.model, "config": {"temperature": cfg.extractor.config.temperature, "max_tokens": cfg.extractor.config.max_tokens}},
        "judge": {"model": cfg.judge.model, "config": {"temperature": cfg.judge.config.temperature, "max_tokens": cfg.judge.config.max_tokens}},
        "generator": {"model": cfg.generator.model, "config": {"temperature": cfg.generator.config.temperature, "max_tokens": cfg.generator.config.max_tokens}},
        "local": {"model": cfg.local.model, "config": {"temperature": cfg.local.config.temperature, "max_tokens": cfg.local.config.max_tokens}},
    }

@app.post("/api/settings")
async def update_settings(request: Request, _auth: str = Depends(require_auth)):
    """Update agent config for the demo web UI. Persists to YAML."""
    import server.config as server_cfg
    body = await request.json()

    # Read the YAML file, update agent model fields, write back
    config_path = Path(".privacy-router.config.yaml")
    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    for agent_name in ("extractor", "judge", "generator", "local"):
        if agent_name in body:
            entry = body[agent_name]
            if agent_name not in raw:
                raw[agent_name] = {}
            if "model" in entry:
                raw[agent_name]["model"] = entry["model"]

    with open(config_path, "w") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # Invalidate the cached config so next read picks up changes
    server_cfg._config = None

    return {"status": "ok"}


# ── POST /v1/chat/completions ───────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, _auth: str = Depends(require_auth)):
    """OpenAI-compatible chat completions with privacy pipeline."""
    body = await request.json()
    cfg = get_config()
    messages: list[dict] = body.get("messages", [])
    temperature: float = body.get("temperature", 0.7)
    max_tokens: int = body.get("max_tokens", 256)
    stream: bool = body.get("stream", False)

    user_text = " ".join(m["content"] for m in messages if m.get("role") == "user") \
        or " ".join(m["content"] for m in messages)

    # ── Resolve model ───────────────────────────────────────────────────
    raw_model: str = body.get("model", "")
    if raw_model.startswith("privacy-router/"):
        raw_model = raw_model[len("privacy-router/"):]
    backend_model = raw_model if raw_model else cfg.generator.model

    registered_ids = [m.id for m in cfg.models]
    if backend_model not in registered_ids:
        return _error_response(400, f"Model {backend_model!r} not registered. Available: {registered_ids}", "invalid_model")

    try:
        adapter = adapter_for(backend_model)
    except ValueError as exc:
        return _error_response(502, str(exc), "unknown_backend")

    backend_model = adapter.resolve_backend_model(backend_model)
    # ── Run pipeline ────────────────────────────────────────────────────
    with timed_span("pipeline", {"model": backend_model}) as span:
        pipeline = PrivacyRouter().process(user_text)
        policy = pipeline.route
        meta = _sensitivity_meta(pipeline)

        # Record PII metrics
        n_records = len(pipeline.records)
        if n_records:
            pii_detected.add(n_records)
        if policy.requires_masking:
            pii_masked.add(n_records)

        span.set_attribute("policy_action", policy.endpoint)
        span.set_attribute("pii_count", n_records)

        # Record usage log
        _log_usage("chat_completions", user_text, bool(n_records), n_records, policy.endpoint, backend_model, 0)

    # ── prompt_user ─────────────────────────────────────────────────────
    if policy.endpoint == "prompt":
        confirm = request.headers.get("X-Privacy-Router-Confirm", "").lower()
        if confirm not in ("true", "1"):
            records = [
                {
                    "category": r.category,
                    "span": r.span,
                    "confidence": r.confidence,
                    "is_load_bearing": r.is_load_bearing,
                    "reasoning": r.reasoning,
                }
                for r in pipeline.records
            ]
            meta["records"] = records
            meta["action_required"] = "confirm"
            meta["confirm_message"] = (
                "이 요청에는 민감한 정보가 포함되어 있습니다:\n\n"
                + "\n".join(f"  • {r['span']}" for r in records)
                + "\n\n이 정보를 마스킹하면 AI가 질문의 맥락을 이해할 수 없어\n"
                "유의미한 답변을 제공하기 어렵습니다.\n\n"
                "원본 텍스트를 외부 AI 서비스로 전송하면,\n"
                "위 정보가 해당 서비스에 전달됩니다."
            )
            return _chat_response(policy.description, privacy_meta=meta, status_code=409)

    # ── block ───────────────────────────────────────────────────────────
    if policy.endpoint == "blocked":
        records = _extract_records(user_text)
        meta["records"] = records
        detected = "\n".join(f"  • {r['span']}" for r in records)
        content = (
            "🚫 이 요청은 차단되었습니다.\n\n"
            f"탐지된 민감 정보:\n{detected}\n\n"
            "주민등록번호, 비밀번호 등 극도로 민감한 정보를 직접 질의하는 요청은\n"
            "외부 AI 서비스로 전송할 수 없습니다.\n\n"
            f"판단 근거: {policy.description}"
        )
        return _chat_response(content, privacy_meta=meta)

    # ── process_locally ─────────────────────────────────────────────────
    if policy.endpoint == "process_locally":
        local_model = cfg.local.model
        local_adapter = adapter_for(local_model)
        local_resolved = local_adapter.resolve_backend_model(local_model)
        local_api_base = _resolve_api_base(local_model)

        try:
            local_resp = local_adapter.call(
                local_resolved, messages,
                cfg.local.config.temperature, cfg.local.config.max_tokens,
                api_base=local_api_base,
            )
            local_content = local_resp.choices[0].message.content or ""
            local_fmt = local_adapter.format_response(local_resp, local_content)
        except Exception as exc:
            return _error_response(502, f"Local model error: {exc}", "local_model_error")

        meta["model_used"] = local_model
        return _chat_response(local_content, local_fmt["finish_reason"], local_fmt["usage"], meta)

    # ── mask_and_send / allow — forward to backend ──────────────────────
    contract: Masker | None = None
    forward_messages = messages

    if policy.requires_masking:
        ext = Extractor()
        extraction = ext.extract(user_text)
        records_dict = [r.model_dump() for r in extraction.records]

        masker = Masker()
        mask_result = masker.mask(user_text, records_dict)
        contract = mask_result.contract

        meta["records"] = [{"category": r.category, "span": r.span} for r in extraction.records]
        meta["original_text"] = user_text
        meta["masked_text"] = mask_result.masked_text
        meta["placeholders"] = [
            {"placeholder": r.make_placeholder(i + 1), "category": r.category, "span": r.span}
            for i, r in enumerate(extraction.records)
        ]

        forward_messages = [
            {**m, "content": mask_result.masked_text} if m.get("role") == "user" else m
            for m in messages
        ]

    api_base = _resolve_api_base(backend_model)

    # ── Streaming ───────────────────────────────────────────────────────
    if stream:
        from server.api.streaming import StreamingHydrator

        hydrator = StreamingHydrator(contract)

        async def _stream():
            chunk_id = _make_chat_id()
            created = int(time.time())
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
                        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                for hydrated in hydrator.flush():
                    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {'content': hydrated}}]})}\n\n"
                yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'privacy-router', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'backend_error'}})}\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # ── Non-streaming ───────────────────────────────────────────────────
    try:
        response = adapter.call(backend_model, forward_messages, temperature, max_tokens, api_base=api_base)
        content: str = response.choices[0].message.content or ""
        formatted = adapter.format_response(response, content)
    except Exception as exc:
        return _error_response(502, f"Backend model error: {exc}", "backend_error")

    # Hydrate
    if policy.requires_masking and contract:
        try:
            hydrated = Masker().hydrate(content, contract)
            content = hydrated.hydrated_text
        except Exception:
            pass

    meta["model_used"] = backend_model
    return _chat_response(content, formatted["finish_reason"], formatted["usage"], meta)


# ── GET / — web chat UI ─────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def chat_ui():
    """Serve the interactive web chat UI."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Privacy Router</h1><p>Chat UI not found.</p>")
