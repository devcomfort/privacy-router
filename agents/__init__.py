"""Privacy Router agents package.

Barrel pattern: import from ``agents`` or ``agents.<subpkg>`` instead
of deep submodule paths.

Public API (convenience re-exports)
------------------------------------
From agents.extractor: Critic, Extractor, ExtractorCore, ExtractionResult, ExtractionRecord, Sensitivity, extract
From agents.masker:    Masker, ContractStore, MaskingContract, encrypt_field, decrypt_field
From agents.router:    PrivacyRouter, PipelineResult, RouteResult, MiddleManAgent, RecordOverride, RoutingStrategy, UserAction, UserDecision
From agents.judge:     Judge, Judgment
From agents.llm:       call_llm, call_llm_structured, load_prompt, render_prompt
"""

from agents.extractor import (
    Critic,
    ExtractionRecord,
    ExtractionResult,
    Extractor,
    ExtractorCore,
    PrivacyAnalysisUnavailable,
    Sensitivity,
    extract,
    redact_extraction_records,
)
from agents.judge import Judge, Judgment
from agents.llm import call_llm, call_llm_structured, load_prompt, render_prompt
from agents.masker import (
    ContractStore,
    HydrationError,
    Masker,
    MaskingContract,
    cache_fingerprint,
    decrypt_field,
    encrypt_field,
    key_fingerprint,
    resolve_provider_key,
)
from agents.router import (
    MiddleManAgent,
    PipelineResult,
    PlaceholderRepairDecision,
    PlaceholderRepairer,
    PrivacyRouteFailure,
    PrivacyRouter,
    RecordOverride,
    RouteResult,
    RoutingStrategy,
    UserAction,
    UserDecision,
    execute_fixed_route,
    execute_fixed_stream,
    get_cache,
    log_privacy_failure,
    placeholder_repair_enabled,
    privacy_failure,
    public_error_fields,
)

__all__ = [
    # extractor
    "Critic",
    "ExtractorCore",
    "PrivacyAnalysisUnavailable",
    "Extractor",
    "ExtractionRecord",
    "ExtractionResult",
    "Sensitivity",
    "redact_extraction_records",
    "extract",
    # judge
    "Judge",
    "Judgment",
    # llm
    "call_llm",
    "call_llm_structured",
    "load_prompt",
    "render_prompt",
    # masker
    "ContractStore",
    "HydrationError",
    "Masker",
    "MaskingContract",
    "cache_fingerprint",
    "decrypt_field",
    "encrypt_field",
    "key_fingerprint",
    "resolve_provider_key",
    # router
    "MiddleManAgent",
    "PipelineResult",
    "PlaceholderRepairDecision",
    "PlaceholderRepairer",
    "placeholder_repair_enabled",
    "PrivacyRouter",
    "RecordOverride",
    "RouteResult",
    "PrivacyRouteFailure",
    "execute_fixed_route",
    "execute_fixed_stream",
    "log_privacy_failure",
    "get_cache",
    "privacy_failure",
    "public_error_fields",
    "RoutingStrategy",
    "UserAction",
    "UserDecision",
]
