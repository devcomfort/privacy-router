"""Privacy Router Server — MCP tools.

FastMCP server exposing privacy pipeline and model management tools
for agent integration.

Tools:
    classify   — Classify a prompt for sensitive information
    route      — Full pipeline: classify + routing decision
    generate   — Classify + forward to LLM with masking
    list_models — List available models from DB
    set_model  — Assign a model to an agent (extractor/judge/generator/local)
    list_providers — List configured providers
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("privacy-router")


# ── Privacy pipeline tools ──────────────────────────────────────────────────


@mcp.tool()
def classify(text: str) -> dict:
    """Classify a prompt for sensitive information.

    Runs the Extractor → Router pipeline and returns sensitivity
    assessment, extracted records, and routing decision.

    When policy_action is "prompt_user", the caller should present
    the records to the user and ask for confirmation before sending.

    Args:
        text: The raw prompt text to classify.

    Returns:
        dict with keys: is_sensitive, records, policy_action,
        requires_masking, description
    """
    from agents.router import PrivacyRouter

    pr = PrivacyRouter()
    t0 = time.time()
    pipeline = pr.process(text)
    latency_ms = (time.time() - t0) * 1000

    is_sensitive = (
        pipeline.sensitivity.get("is_sensitive", False)
        if isinstance(pipeline.sensitivity, dict)
        else getattr(pipeline.sensitivity, "is_sensitive", False)
    )

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

    policy_action = (
        pipeline.judgment.policy_action
        if hasattr(pipeline.judgment, "policy_action")
        else pipeline.route.endpoint
    )

    # Record usage
    _log_usage("classify", text, is_sensitive, len(records), policy_action, None, latency_ms)

    return {
        "is_sensitive": is_sensitive,
        "records": records,
        "policy_action": policy_action,
        "requires_masking": (
            pipeline.route.requires_masking
            if hasattr(pipeline.route, "requires_masking")
            else False
        ),
        "description": (
            pipeline.route.description
            if hasattr(pipeline.route, "description")
            else ""
        ),
    }


@mcp.tool()
def route(text: str) -> dict:
    """Full pipeline: classify + routing decision in one call.

    Args:
        text: The raw prompt text to process.

    Returns:
        dict with full pipeline result including endpoint and masking decision.
    """
    return classify(text)


@mcp.tool()
def generate(text: str, model: str | None = None) -> dict:
    """Classify a prompt, apply privacy policy, and call an LLM.

    Runs the full privacy pipeline (Extractor → Router → Masker → LLM).
    If the prompt contains sensitive information, it is masked before
    being sent to the LLM, and the response is hydrated back.

    Args:
        text: The raw prompt text.
        model: Optional model override (e.g. "openrouter/mistralai/ministral-3b-2512").
               If not provided, uses the generator model from DB or config.

    Returns:
        dict with keys: content, is_sensitive, policy_action,
        model_used, records, latency_ms
    """
    import litellm
    from agents.extractor import Extractor
    from agents.masker import Masker
    from agents.router import PrivacyRouter
    from db.models import AgentConfig
    from db.session import get_session
    from sqlmodel import select

    t0 = time.time()

    # Resolve model from DB or parameter
    generator_model = model
    if not generator_model:
        session = get_session()
        try:
            configs = session.exec(select(AgentConfig)).all()
            agent_models = {c.agent_name: c.model_id for c in configs}
            generator_model = agent_models.get("generator", "openrouter/mistralai/ministral-3b-2512")
        finally:
            session.close()

    # Run pipeline
    pr = PrivacyRouter()
    pipeline = pr.process(text)

    is_sensitive = (
        pipeline.sensitivity.get("is_sensitive", False)
        if isinstance(pipeline.sensitivity, dict)
        else getattr(pipeline.sensitivity, "is_sensitive", False)
    )

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

    policy_action = (
        pipeline.judgment.policy_action
        if hasattr(pipeline.judgment, "policy_action")
        else pipeline.route.endpoint
    )

    # Route
    if pipeline.route.endpoint == "blocked":
        content = "🚫 요청이 차단되었습니다."
        model_used = "none"
    elif pipeline.route.endpoint == "prompt":
        content = "⚠️ 확인이 필요합니다. policy_action=prompt_user."
        model_used = "none"
    elif pipeline.route.endpoint == "external_api":
        forward_text = text
        if pipeline.route.requires_masking:
            ext = Extractor()
            extraction = ext.extract(text)
            masker = Masker()
            mask_result = masker.mask(text, [r.model_dump() for r in extraction.records])
            forward_text = mask_result.masked_text

        try:
            resp = litellm.completion(
                model=generator_model,
                messages=[{"role": "user", "content": forward_text}],
                max_tokens=512,
                api_key=os.getenv("OPENROUTER_API_KEY", ""),
            )
            content = resp.choices[0].message.content or ""
            model_used = generator_model

            # Hydrate masked placeholders back
            if pipeline.route.requires_masking and content:
                hydrated = masker.hydrate(content, mask_result.contract)
                content = hydrated.hydrated_text
        except Exception as exc:
            content = f"Error: {exc}"
            model_used = "error"
    else:
        content = "⚠️ 로컬에서 처리해야 합니다."
        model_used = "local"

    latency_ms = (time.time() - t0) * 1000

    # Record usage
    _log_usage("generate", text, is_sensitive, len(records), policy_action, model_used, latency_ms)

    return {
        "content": content,
        "is_sensitive": is_sensitive,
        "policy_action": policy_action,
        "model_used": model_used,
        "records": records,
        "latency_ms": round(latency_ms, 1),
    }


# ── Model management tools ──────────────────────────────────────────────────


@mcp.tool()
def list_models(tier: str | None = None) -> list[dict]:
    """List registered models from the database.

    Args:
        tier: Optional filter by tier ("local" or "external").

    Returns:
        List of dicts with keys: id, model_id, display_name, tier,
        cost_per_1m_tokens, provider_id, is_active
    """
    from db.models import Model
    from db.session import get_session
    from sqlmodel import select

    session = get_session()
    try:
        stmt = select(Model)
        if tier:
            stmt = stmt.where(Model.tier == tier)
        models = session.exec(stmt).all()
        return [
            {
                "id": m.id,
                "model_id": m.model_id,
                "display_name": m.display_name,
                "tier": m.tier,
                "cost_per_1m_tokens": m.cost_per_1m_tokens,
                "provider_id": m.provider_id,
                "is_active": m.is_active,
            }
            for m in models
        ]
    finally:
        session.close()


@mcp.tool()
def set_model(agent_name: str, model_id: str, temperature: float = 0.0, max_tokens: int = 4096) -> dict:
    """Assign a model to an agent (extractor, judge, generator, local).

    Creates or updates the agent_configs table entry.

    Args:
        agent_name: Agent to configure ("extractor", "judge", "generator", "local").
        model_id: Model identifier (e.g. "openrouter/mistralai/ministral-3b-2512").
        temperature: Sampling temperature (0.0-2.0).
        max_tokens: Maximum output tokens.

    Returns:
        dict with keys: agent_name, model_id, temperature, max_tokens, status
    """
    from db.models import AgentConfig
    from db.session import get_session
    from sqlmodel import select

    session = get_session()
    try:
        existing = session.exec(
            select(AgentConfig).where(AgentConfig.agent_name == agent_name)
        ).first()

        if existing:
            existing.model_id = model_id
            existing.temperature = temperature
            existing.max_tokens = max_tokens
            session.add(existing)
        else:
            config = AgentConfig(
                agent_name=agent_name,
                model_id=model_id,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            session.add(config)

        session.commit()
        return {
            "agent_name": agent_name,
            "model_id": model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "status": "ok",
        }
    finally:
        session.close()


@mcp.tool()
def list_providers() -> list[dict]:
    """List configured providers from the database.

    Returns:
        List of dicts with keys: id, name, provider_type, api_base, is_active
    """
    from db.models import Provider
    from db.session import get_session
    from sqlmodel import select

    session = get_session()
    try:
        providers = session.exec(select(Provider)).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "provider_type": p.provider_type,
                "api_base": p.api_base,
                "is_active": p.is_active,
            }
            for p in providers
        ]
    finally:
        session.close()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _log_usage(
    event: str,
    text: str,
    is_sensitive: bool,
    records_count: int,
    policy_action: str | None,
    model_used: str | None,
    latency_ms: float,
) -> None:
    """Record a usage log entry."""
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
        pass  # Never fail the request because of logging
