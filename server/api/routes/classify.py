"""Custom API — classify and generate."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from agents import (
    ContractStore,
    Masker,
    PipelineResult,
    PrivacyAnalysisUnavailable,
    PrivacyRouter,
    RouteResult,
    call_llm,
    redact_extraction_records,
)
from config import resolve_generation_binding
from db import UsageLog, get_session
from server.api import app, require_auth
from server.config import get_config


class ClassifyRequest(BaseModel):
    text: str = Field(...)


class ClassificationResponse(BaseModel):
    records: list[dict[str, str | float | bool | int]] = Field(default_factory=list)
    is_sensitive: bool
    policy_action: str
    route: RouteResult
    model: str = Field(..., description="Model recommended for the chosen route.")
    strategy: str = ""
    rationale: str = ""


class GenerateRequest(BaseModel):
    text: str = Field(...)
    stream: bool = Field(default=False)
    model: str | None = Field(default=None)


class GenerateResponse(BaseModel):
    content: str
    is_sensitive: bool
    policy_action: str
    model_used: str
    records: list[dict] = Field(default_factory=list)
    masking_session_id: str | None = None


def _analyze(text: str) -> PipelineResult:
    """Normalize every privacy-analysis failure to the public safe error."""
    try:
        return PrivacyRouter().process(text)
    except PrivacyAnalysisUnavailable:
        raise
    except Exception as exc:
        raise PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.") from exc


@app.post("/api/v1/classify", response_model=ClassificationResponse)
def classify_endpoint(body: ClassifyRequest, _auth: str = Depends(require_auth)):
    """Analyse text through the privacy pipeline (no LLM call)."""
    config = get_config()
    result = _analyze(body.text)

    recommended_model = config.local.model if result.route.endpoint == "local_api" else config.external.model

    _log_classify_usage(
        result.sensitivity.is_sensitive,
        len(result.records),
        result.judgment.policy_action,
    )
    return ClassificationResponse(
        records=redact_extraction_records(result.records),
        is_sensitive=result.sensitivity.is_sensitive,
        policy_action=result.judgment.policy_action,
        route=result.route,
        model=recommended_model,
        strategy=result.judgment.strategy,
        rationale=result.judgment.rationale,
    )


@app.post("/api/v1/generate", response_model=GenerateResponse)
def generate_endpoint(body: GenerateRequest, _auth: str = Depends(require_auth)):
    """Analyse text + forward to LLM."""
    config = get_config()
    result = _analyze(body.text)

    records = redact_extraction_records(result.records)
    record_payloads = [record.model_dump() for record in result.records]
    is_sensitive = result.sensitivity.is_sensitive
    policy_action = result.judgment.policy_action
    try:
        model_used, generation_config, api_base = resolve_generation_binding(
            config,
            policy_action,
            body.model,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid generator model",
        ) from exc

    forward_text = body.text
    masking_result = None
    masking_session_id = None
    if result.route.requires_masking:
        masker = Masker()
        masking_result = masker.mask(body.text, record_payloads)
        forward_text = masking_result.masked_text

    content = call_llm(
        [{"role": "user", "content": forward_text}],
        model=model_used,
        api_base=api_base,
        **generation_config,
    )
    if masking_result is not None:
        content = (
            Masker()
            .hydrate(
                content,
                masking_result.contract,
            )
            .hydrated_text
        )
        store = ContractStore()
        masking_session_id = store.create_session(
            chat_id=None,
            record_count=len(record_payloads),
            policy_action=policy_action,
            owner_id=_auth,
        )
        store.save_records(
            masking_session_id,
            record_payloads,
            masking_result.contract.placeholder_map,
        )

    # Record usage
    _log_classify_usage(is_sensitive, len(records), policy_action)
    return GenerateResponse(
        content=content,
        is_sensitive=is_sensitive,
        policy_action=policy_action,
        model_used=model_used,
        records=records,
        masking_session_id=masking_session_id,
    )


def _log_classify_usage(
    is_sensitive: bool,
    records_count: int,
    policy_action: str | None,
) -> None:
    """Record a usage log entry (never fails the request)."""
    try:
        session = get_session()
        try:
            log = UsageLog(
                event="classify",
                is_sensitive=is_sensitive,
                records_count=records_count,
                policy_action=policy_action,
            )
            session.add(log)
            session.commit()
        finally:
            session.close()
    except Exception:
        pass
