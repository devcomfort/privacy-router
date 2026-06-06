"""Custom API — classify and generate."""

from __future__ import annotations

import os

import litellm
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlmodel import select

from agents.extractor import Extractor
from agents.masker import Masker
from agents.router import PrivacyRouter
from db.models import AgentConfig
from db.session import get_session
from server.api.auth import require_auth
from server.api.main import app


class ClassifyRequest(BaseModel):
    text: str = Field(...)


class ClassifyResponse(BaseModel):
    is_sensitive: bool
    records: list[dict] = Field(default_factory=list)
    policy_action: str
    recommended_model: str
    strategy: str = ""
    rationale: str = ""


class GenerateRequest(BaseModel):
    text: str = Field(...)
    stream: bool = Field(default=False)


class GenerateResponse(BaseModel):
    content: str
    is_sensitive: bool
    policy_action: str
    model_used: str
    records: list[dict] = Field(default_factory=list)


def _load_agent_models(session) -> dict[str, str]:
    configs = session.exec(select(AgentConfig)).all()
    return {c.agent_name: c.model_id for c in configs}


@app.post("/api/v1/classify", response_model=ClassifyResponse)
def classify_endpoint(body: ClassifyRequest, _auth: str = Depends(require_auth)):
    """Analyse text through the privacy pipeline (no LLM call)."""
    session = get_session()
    try:
        agent_models = _load_agent_models(session)
    finally:
        session.close()

    extractor = agent_models.get("extractor", "openrouter/mistralai/ministral-3b-2512")
    judge = agent_models.get("judge", "openrouter/google/gemini-3.1-flash-lite")
    generator = agent_models.get("generator", extractor)
    local = agent_models.get("local", extractor)

    pr = PrivacyRouter(extractor_model=extractor, judge_model=judge)
    result = pr.process(body.text)

    records = [
        {"category": r.category, "span": r.span, "confidence": r.confidence}
        for r in result.sensitivity.records
    ] if hasattr(result.sensitivity, "records") else []

    if result.route.endpoint == "local_api":
        recommended_model = local
    elif result.route.endpoint in ("blocked", "prompt"):
        recommended_model = "none"
    else:
        recommended_model = generator

    return ClassifyResponse(
        is_sensitive=(
            result.sensitivity.is_sensitive
            if hasattr(result.sensitivity, "is_sensitive")
            else bool(records)
        ),
        records=records,
        policy_action=(
            result.judgment.policy_action
            if hasattr(result.judgment, "policy_action")
            else result.route.endpoint
        ),
        recommended_model=recommended_model,
        strategy=getattr(result.judgment, "strategy", ""),
        rationale=getattr(result.judgment, "rationale", ""),
    )


@app.post("/api/v1/generate", response_model=GenerateResponse)
def generate_endpoint(body: GenerateRequest, _auth: str = Depends(require_auth)):
    """Analyse text + forward to LLM."""
    session = get_session()
    try:
        agent_models = _load_agent_models(session)
    finally:
        session.close()

    extractor = agent_models.get("extractor", "openrouter/mistralai/ministral-3b-2512")
    judge = agent_models.get("judge", "openrouter/google/gemini-3.1-flash-lite")
    generator = agent_models.get("generator", extractor)
    local = agent_models.get("local", extractor)

    pr = PrivacyRouter(extractor_model=extractor, judge_model=judge)
    result = pr.process(body.text)

    records = [
        {"category": r.category, "span": r.span, "confidence": r.confidence}
        for r in result.sensitivity.records
    ] if hasattr(result.sensitivity, "records") else []
    is_sensitive = (
        result.sensitivity.is_sensitive
        if hasattr(result.sensitivity, "is_sensitive")
        else bool(records)
    )
    policy_action = (
        result.judgment.policy_action
        if hasattr(result.judgment, "policy_action")
        else result.route.endpoint
    )

    # ── Route ────────────────────────────────────────────────────────────
    if result.route.endpoint == "blocked":
        content = "🚫 요청이 차단되었습니다."
        model_used = "none"
    elif result.route.endpoint == "prompt":
        content = "⚠️ 확인이 필요합니다. X-Privacy-Router-Confirm: true 헤더로 재요청하세요."
        model_used = "none"
    elif result.route.endpoint == "external_api":
        forward_text = body.text
        if result.route.requires_masking:
            ext = Extractor()
            extraction = ext.extract(body.text)
            masker = Masker()
            mask_result = masker.mask(body.text, [r.model_dump() for r in extraction.records])
            forward_text = mask_result.masked_text
        try:
            resp = litellm.completion(
                model=generator,
                messages=[{"role": "user", "content": forward_text}],
                max_tokens=512,
                api_key=os.getenv("OPENROUTER_API_KEY", ""),
            )
            content = resp.choices[0].message.content or ""
            model_used = generator
        except Exception as exc:
            content = f"Error: {exc}"
            model_used = "error"
    else:
        content = "⚠️ 로컬에서 처리해야 합니다."
        model_used = local

    return GenerateResponse(
        content=content,
        is_sensitive=is_sensitive,
        policy_action=policy_action,
        model_used=model_used,
        records=records,
    )
