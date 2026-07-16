"""Privacy Router Server — Unified MCP tool.

Single entry point for agent integration. Agents call `process` with
raw text; the tool extracts sensitive info, applies routing policy,
optionally masks and forwards to an LLM, and returns the result.

Configuration is read from .privacy-router.config.yaml at startup.
"""

from __future__ import annotations

import time

from mcp.server.fastmcp import FastMCP

from agents import (
    ContractStore,
    ExtractionRecord,
    ExtractionResult,
    Extractor,
    Masker,
    MiddleManAgent,
    PrivacyRouter,
    RecordOverride,
    RoutingStrategy,
    Sensitivity,
    UserAction,
    UserDecision,
    cache_fingerprint,
    call_llm,
    get_cache,
    redact_extraction_records,
)
from config import (
    PrivacyRouterConfig,
    load_config,
    resolve_generation_binding,
)
from db import UsageLog, get_session

mcp = FastMCP("privacy-router")


def _load_config() -> PrivacyRouterConfig:
    """Load the SQLite-first, validated runtime configuration."""
    return load_config()


def _analysis_unavailable_fields() -> dict[str, str]:
    """Return source-free fields for a failed privacy analysis."""
    return {
        "analysis_status": "unavailable",
        "error_code": "privacy_analysis_failed",
        "error": ("Sensitive-information analysis is unavailable; the input was not forwarded."),
    }


def _load_extraction(
    text: str,
    no_cache: bool,
    config: PrivacyRouterConfig | None = None,
) -> tuple[ExtractionResult, bool]:
    """Load a validated cached extraction or run and cache a fresh one."""
    cache = get_cache()
    cache_key = cache_fingerprint(f"mcp-text\0{text}")
    extraction = None
    cached = False
    if not no_cache:
        cached_data = cache.get_extraction(cache_key)
        if cached_data is not None:
            extraction = ExtractionResult(
                sensitivity=Sensitivity(**cached_data["sensitivity"]),
                records=[ExtractionRecord(**record) for record in cached_data["records"]],
            )
            cached = True

    if extraction is None:
        active_config = config or _load_config()
        extractor = Extractor(
            model=active_config.decision.model,
            api_base=active_config.decision.api_base,
        )
        extraction = extractor.extract(text)
        cache.put_extraction(
            cache_key,
            {
                "sensitivity": {
                    "is_sensitive": extraction.sensitivity.is_sensitive,
                    "rationale": extraction.sensitivity.rationale,
                },
                "records": [
                    {
                        "category": record.category,
                        "span": record.span,
                        "start": record.start,
                        "end": record.end,
                        "detection_type": record.detection_type,
                        "is_essential": record.is_essential,
                        "confidence": record.confidence,
                        "reasoning": record.reasoning,
                    }
                    for record in extraction.records
                ],
            },
        )
    return extraction, cached


@mcp.tool()
def process(
    text: str,
    action: str = "auto",
    model: str | None = None,
    chat_id: str | None = None,
) -> dict:
    """Process a prompt through the Privacy Router pipeline.

    This is the single entry point for all agent integrations.
    The pipeline: Extract → Judge → Route → (optional) Mask → (optional) LLM.

    Args:
        text: The raw prompt to process.
        action: Override routing action. One of:
            - "auto" (default): run full pipeline, decide automatically
            - "classify": extract + judge only, no LLM call
            - "generate": force LLM call (mask if needed)
            - "allow": skip privacy checks, forward directly
            - "hydrate": hydrate content using a stored masking contract (requires chat_id)
        model: Override the generator model from config.
        chat_id: Optional chat/conversation ID for masking session tracking.
            If provided, masking contract is persisted to DB and can be
            retrieved later for hydration.

    Returns:
        dict with keys:
            - action_taken: str — what happened
            - content: str | None — LLM response (if generation happened)
            - records: list[dict] — extracted sensitive information records
            - policy_action: str — routing decision
            - is_sensitive: bool — whether sensitive info was detected
            - requires_masking: bool — whether masking was applied
            - model_used: str | None — model that was called
            - latency_ms: float — total processing time
            - masking_session_id: str | None — DB session ID (when masking applied)
            - masking_records: list[dict] — per-record masking details with UIDs
    """
    config = _load_config()
    t0 = time.time()
    contract_store = ContractStore()

    # ── Step 0: Hydrate action (no pipeline, just contract lookup) ──────────
    if action == "hydrate":
        if not chat_id:
            return {
                "action_taken": "error",
                "content": None,
                "extraction_records": [],
                "policy_action": "hydrate",
                "is_sensitive": False,
                "requires_masking": False,
                "model_used": None,
                "latency_ms": 0.0,
                "masking_session_id": None,
                "placeholder_map": [],
                "error": "chat_id required for hydrate action",
            }
        contract = contract_store.load_contract(chat_id)
        if not contract:
            return {
                "action_taken": "error",
                "content": None,
                "extraction_records": [],
                "policy_action": "hydrate",
                "is_sensitive": False,
                "requires_masking": False,
                "model_used": None,
                "latency_ms": 0.0,
                "masking_session_id": None,
                "placeholder_map": [],
                "error": f"Masking session not found or expired: {chat_id}",
            }
        masker = Masker()
        hydrated = masker.hydrate(text, contract)
        latency_ms = (time.time() - t0) * 1000
        return {
            "action_taken": "hydrated",
            "content": hydrated.hydrated_text,
            "extraction_records": [],
            "policy_action": "hydrate",
            "is_sensitive": False,
            "requires_masking": False,
            "model_used": None,
            "latency_ms": latency_ms,
            "masking_session_id": chat_id,
            "placeholder_map": [],
            "records_restored": hydrated.placeholders_restored,
        }

    # ── Step 1: Extract + Judge (always runs unless action=allow) ──────────
    if action == "allow":
        try:
            gen_model, gen_cfg, api_base = resolve_generation_binding(
                config,
                "allow",
                model,
            )
        except (KeyError, ValueError):
            return _generation_unavailable_response(
                records=[],
                policy_action="allow",
                is_sensitive=False,
                requires_masking=False,
                model_used=None,
                latency_ms=(time.time() - t0) * 1000,
                masking_session_id=None,
                placeholder_map=[],
                error_code="generation_configuration_error",
                error_message="Generation model configuration is unavailable.",
            )
        try:
            content = call_llm(
                [{"role": "user", "content": text}],
                model=gen_model,
                api_base=api_base,
                **gen_cfg,
            )
        except Exception:
            return _generation_unavailable_response(
                records=[],
                policy_action="allow",
                is_sensitive=False,
                requires_masking=False,
                model_used=gen_model,
                latency_ms=(time.time() - t0) * 1000,
                masking_session_id=None,
                placeholder_map=[],
            )
        latency_ms = (time.time() - t0) * 1000
        _log_usage("process", False, 0, "allow", gen_model, latency_ms)
        return {
            "action_taken": "allowed",
            "content": content,
            "extraction_records": [],
            "policy_action": "allow",
            "is_sensitive": False,
            "requires_masking": False,
            "model_used": gen_model or None,
            "latency_ms": latency_ms,
            "masking_session_id": None,
            "placeholder_map": [],
        }

    # Run Extractor → Router pipeline
    try:
        pr = PrivacyRouter()
        pipeline = pr.process(text)
    except Exception:
        return {
            "action_taken": "error",
            **_analysis_unavailable_fields(),
            "content": None,
            "extraction_records": [],
            "policy_action": "block",
            "is_sensitive": None,
            "requires_masking": False,
            "model_used": None,
            "latency_ms": (time.time() - t0) * 1000,
            "masking_session_id": None,
            "placeholder_map": [],
        }

    is_sensitive = pipeline.sensitivity.is_sensitive

    internal_records = [record.model_dump() for record in pipeline.records]
    records = redact_extraction_records(pipeline.records)

    policy_action = pipeline.judgment.policy_action

    # ── Step 2: If classify-only, return here ─────────────────────────────
    if action == "classify":
        latency_ms = (time.time() - t0) * 1000
        _log_usage("process", is_sensitive, len(records), "classify", None, latency_ms)
        return {
            "action_taken": "classified",
            "content": None,
            "extraction_records": records,
            "policy_action": policy_action,
            "is_sensitive": is_sensitive,
            "requires_masking": False,
            "model_used": None,
            "latency_ms": latency_ms,
            "masking_session_id": None,
            "placeholder_map": [],
        }

    # ── Step 3: Apply routing decision ────────────────────────────────────
    effective_action = policy_action
    if action == "generate":
        effective_action = "selective_mask" if is_sensitive else "allow"

    # ── Step 4: Mask if needed ────────────────────────────────────────────
    masked_text = text
    masking_result = None
    masking_session_id = None
    masking_records_out = []
    requires_masking = effective_action == "selective_mask"

    if requires_masking and pipeline.records:
        masker = Masker()
        record_dicts = internal_records
        masking_result = masker.mask(text, record_dicts)
        masked_text = masking_result.masked_text

        # Persist to DB
        masking_session_id = contract_store.create_session(
            chat_id=chat_id,
            record_count=len(records),
            policy_action=effective_action,
        )
        contract_store.save_records(
            session_id=masking_session_id,
            records=internal_records,
            placeholder_map=masking_result.contract.placeholder_map,
        )

        # Build masking_records for response
        for placeholder, original in masking_result.contract.placeholder_map.items():
            uid = placeholder.strip("[]").partition("#")[2]
            matching = next((r for r in internal_records if r["span"] == original), None)
            masking_records_out.append(
                {
                    "uid": uid,
                    "category": matching["category"] if matching else "UNKNOWN",
                    "placeholder": placeholder,
                    "confidence": matching["confidence"] if matching else 0.0,
                    "is_essential": matching["is_essential"] if matching else False,
                }
            )

    # ── Step 5: Call LLM ──────────────────────────────────────────────────
    try:
        gen_model, gen_cfg, api_base = resolve_generation_binding(
            config,
            effective_action,
            model,
        )
    except (KeyError, ValueError):
        return _generation_unavailable_response(
            records=records,
            policy_action=effective_action,
            is_sensitive=is_sensitive,
            requires_masking=requires_masking,
            model_used=None,
            latency_ms=(time.time() - t0) * 1000,
            masking_session_id=masking_session_id,
            placeholder_map=masking_records_out,
            error_code="generation_configuration_error",
            error_message="Generation model configuration is unavailable.",
        )

    content = None
    if gen_model:
        try:
            content = call_llm(
                [{"role": "user", "content": masked_text}],
                model=gen_model,
                api_base=api_base,
                **gen_cfg,
            )
        except Exception:
            return _generation_unavailable_response(
                records=records,
                policy_action=effective_action,
                is_sensitive=is_sensitive,
                requires_masking=requires_masking,
                model_used=gen_model,
                latency_ms=(time.time() - t0) * 1000,
                masking_session_id=masking_session_id,
                placeholder_map=masking_records_out,
            )

    # ── Step 6: Hydrate response ──────────────────────────────────────────
    if content and requires_masking and masking_result:
        masker = Masker()
        hydrated = masker.hydrate(content, masking_result.contract)
        content = hydrated.hydrated_text

    latency_ms = (time.time() - t0) * 1000
    action_taken = "generated" if content else "masked_and_sent"
    _log_usage("process", is_sensitive, len(records), effective_action, gen_model, latency_ms)

    return {
        "action_taken": action_taken,
        "content": content,
        "extraction_records": records,
        "policy_action": effective_action,
        "is_sensitive": is_sensitive,
        "requires_masking": requires_masking,
        "model_used": gen_model or None,
        "latency_ms": latency_ms,
        "masking_session_id": masking_session_id,
        "placeholder_map": masking_records_out,
    }


# ── Middle-Man Agent Tools ──────────────────────────────────────────────────


@mcp.tool()
def review(
    text: str,
    no_cache: bool = False,
) -> dict:
    """Review extraction results before applying routing decision.

    This tool extracts sensitive information and returns a summary.
    Use the `decide` tool with the same text to apply user decisions.

    Args:
        text: The raw prompt to analyze.
        no_cache: If True, bypass cache and re-run extraction.

    Returns:
        dict with keys:
            - summary: dict — human-readable summary
            - records: list[dict] — extracted records with details
            - formatted: str — formatted text for user display
            - cached: bool — whether result was from cache
    """
    try:
        extraction, cached = _load_extraction(text, no_cache)
        middle_man = MiddleManAgent()
        summary = middle_man.summarize(extraction)
    except Exception:
        return {
            **_analysis_unavailable_fields(),
            "summary": {
                "is_sensitive": None,
                "record_count": 0,
                "essential_count": 0,
                "default_action": "block",
                "confidence_avg": 0.0,
                "low_confidence_records": [],
            },
            "extraction_records": [],
            "formatted": ("Sensitive-information analysis is unavailable. The input was not forwarded."),
            "cached": False,
        }

    return {
        "summary": {
            "is_sensitive": summary.is_sensitive,
            "record_count": summary.record_count,
            "essential_count": summary.essential_count,
            "default_action": summary.default_action,
            "confidence_avg": summary.confidence_avg,
            "low_confidence_records": summary.low_confidence_records,
        },
        "extraction_records": summary.records,
        "formatted": middle_man.format_for_user(summary),
        "cached": cached,
    }


@mcp.tool()
def apply_decision(
    text: str,
    action: str = "accept",
    strategy: str = "auto",
    overrides: list[dict] | None = None,
    model: str | None = None,
    no_cache: bool = False,
) -> dict:
    """Apply user decision on extraction results.

    Uses cached extraction from `review` if available.

    Args:
        text: The original raw prompt.
        action: User action — "accept", "override", "strategy", "cancel".
        strategy: Routing strategy — "auto", "mask_all", "block_all", "allow_all".
        overrides: List of record overrides, each with:
            - record_index: int
            - is_essential: bool (optional)
            - remove: bool (optional)
        model: Override the generator model.
        no_cache: If True, bypass cache and re-run extraction.

    Returns:
        dict with same keys as `process` tool.
    """
    t0 = time.time()
    try:
        config = _load_config()
        extraction, _cached = _load_extraction(text, no_cache, config)
    except Exception:
        return {
            "action_taken": "error",
            **_analysis_unavailable_fields(),
            "content": None,
            "extraction_records": [],
            "policy_action": "block",
            "is_sensitive": None,
            "requires_masking": False,
            "model_used": None,
            "latency_ms": (time.time() - t0) * 1000,
            "masking_session_id": None,
            "placeholder_map": [],
            "user_action": action,
            "user_strategy": strategy,
        }

    # Build user decision
    user_overrides = []
    if overrides:
        for o in overrides:
            user_overrides.append(
                RecordOverride(
                    record_index=o.get("record_index", 0),
                    is_essential=o.get("is_essential"),
                    remove=o.get("remove", False),
                )
            )

    decision = UserDecision(
        action=UserAction(action),
        strategy=RoutingStrategy(strategy),
        overrides=user_overrides,
    )

    # Apply decision
    middle_man = MiddleManAgent()
    pipeline = middle_man.process_with_decision(extraction, decision)

    # Build response
    is_sensitive = pipeline.sensitivity.is_sensitive
    internal_records = [record.model_dump() for record in pipeline.records]
    records = redact_extraction_records(pipeline.records)
    policy_action = pipeline.judgment.policy_action

    # Mask if needed
    masked_text = text
    masking_result = None
    masking_session_id = None
    masking_records_out = []
    requires_masking = policy_action == "selective_mask"

    if requires_masking and pipeline.records:
        masker = Masker()
        record_dicts = internal_records
        masking_result = masker.mask(text, record_dicts)
        masked_text = masking_result.masked_text

        contract_store = ContractStore()
        masking_session_id = contract_store.create_session(
            chat_id=None,
            record_count=len(records),
            policy_action=policy_action,
        )
        contract_store.save_records(
            session_id=masking_session_id,
            records=internal_records,
            placeholder_map=masking_result.contract.placeholder_map,
        )

        for placeholder, original in masking_result.contract.placeholder_map.items():
            uid = placeholder.strip("[]").partition("#")[2]
            matching = next((r for r in internal_records if r["span"] == original), None)
            masking_records_out.append(
                {
                    "uid": uid,
                    "category": matching["category"] if matching else "UNKNOWN",
                    "placeholder": placeholder,
                    "confidence": matching["confidence"] if matching else 0.0,
                    "is_essential": matching["is_essential"] if matching else False,
                }
            )

    # Call LLM
    try:
        gen_model, gen_cfg, api_base = resolve_generation_binding(
            config,
            policy_action,
            model,
        )
    except (KeyError, ValueError):
        return _generation_unavailable_response(
            records=records,
            policy_action=policy_action,
            is_sensitive=is_sensitive,
            requires_masking=requires_masking,
            model_used=None,
            latency_ms=(time.time() - t0) * 1000,
            masking_session_id=masking_session_id,
            placeholder_map=masking_records_out,
            error_code="generation_configuration_error",
            error_message="Generation model configuration is unavailable.",
            extra={
                "user_action": action,
                "user_strategy": strategy,
            },
        )
    content = None
    if gen_model:
        try:
            content = call_llm(
                [{"role": "user", "content": masked_text}],
                model=gen_model,
                api_base=api_base,
                **gen_cfg,
            )
        except Exception:
            return _generation_unavailable_response(
                records=records,
                policy_action=policy_action,
                is_sensitive=is_sensitive,
                requires_masking=requires_masking,
                model_used=gen_model,
                latency_ms=(time.time() - t0) * 1000,
                masking_session_id=masking_session_id,
                placeholder_map=masking_records_out,
                extra={
                    "user_action": action,
                    "user_strategy": strategy,
                },
            )

    # Hydrate
    if content and requires_masking and masking_result:
        masker = Masker()
        hydrated = masker.hydrate(content, masking_result.contract)
        content = hydrated.hydrated_text

    latency_ms = (time.time() - t0) * 1000
    action_taken = "generated" if content else "masked_and_sent"
    _log_usage("apply_decision", is_sensitive, len(records), policy_action, gen_model, latency_ms)

    return {
        "action_taken": action_taken,
        "content": content,
        "extraction_records": records,
        "policy_action": policy_action,
        "is_sensitive": is_sensitive,
        "requires_masking": requires_masking,
        "model_used": gen_model or None,
        "latency_ms": latency_ms,
        "masking_session_id": masking_session_id,
        "placeholder_map": masking_records_out,
        "user_action": action,
        "user_strategy": strategy,
    }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _generation_unavailable_response(
    *,
    records: list[dict],
    policy_action: str,
    is_sensitive: bool,
    requires_masking: bool,
    model_used: str | None,
    latency_ms: float,
    masking_session_id: str | None,
    placeholder_map: list[dict],
    extra: dict | None = None,
    error_code: str = "llm_request_failed",
    error_message: str = "Language model request failed.",
) -> dict:
    """Return a source-free MCP error when generation fails."""
    return {
        "action_taken": "error",
        "content": None,
        "extraction_records": records,
        "policy_action": policy_action,
        "is_sensitive": is_sensitive,
        "requires_masking": requires_masking,
        "model_used": model_used,
        "latency_ms": latency_ms,
        "masking_session_id": masking_session_id,
        "placeholder_map": placeholder_map,
        "error_code": error_code,
        "error_message": error_message,
        **(extra or {}),
    }


def _log_usage(
    event: str,
    is_sensitive: bool,
    records_count: int,
    policy_action: str,
    model_used: str | None,
    latency_ms: float,
) -> None:
    """Record a usage log entry."""
    try:
        session = get_session()
        try:
            entry = UsageLog(
                event=event,
                is_sensitive=is_sensitive,
                records_count=records_count,
                policy_action=policy_action,
                model_used=model_used,
                latency_ms=round(latency_ms, 1),
            )
            session.add(entry)
            session.commit()
        finally:
            session.close()
    except Exception:
        pass  # Never fail the request because of logging
