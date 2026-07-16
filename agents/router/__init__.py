"""Privacy Router — Router package.

Execution layer and top-level orchestrator.  :class:`PrivacyRouter`
is the main entry point that chains Extractor → Judge → Router.

:class:`MiddleManAgent` provides interactive extraction review.

Public API
----------
PrivacyRouter
    Top-level pipeline orchestrator.
Router
    Pure execution layer (no LLM calls).
MiddleManAgent
    Interactive extraction review agent.
RouteResult
    Concrete routing result.
process
    Module-level convenience function.
process_with_decision
    Process extraction with optional user decision.

Examples
--------
>>> from agents.router import PrivacyRouter
>>> pr = PrivacyRouter()
>>> result = pr.process("hello")
>>> result.route.endpoint
'external_api'

>>> from agents.router import MiddleManAgent, process_with_decision
>>> mm = MiddleManAgent()
>>> summary = mm.summarize(extraction)
>>> print(mm.format_for_user(summary))
"""

from .cache import SQLiteKVCache, get_cache
from .execution import (
    PrivacyRouteFailure,
    execute_fixed_route,
    execute_fixed_stream,
    log_privacy_failure,
    privacy_failure,
    public_error_fields,
)
from .middle_man import (
    MiddleManAgent,
    RecordOverride,
    RoutingStrategy,
    UserAction,
    UserDecision,
    format_extraction_for_user,
    process_with_decision,
    summarize_extraction,
)
from .placeholder_repair import PlaceholderRepairer, placeholder_repair_enabled
from .router import PrivacyRouter, Router, process
from .schemas import (
    ChatMessage,
    ChatRequest,
    PipelineResult,
    PlaceholderRepairDecision,
    RouteResult,
)

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "PrivacyRouter",
    "Router",
    "RouteResult",
    "PrivacyRouteFailure",
    "execute_fixed_route",
    "execute_fixed_stream",
    "log_privacy_failure",
    "privacy_failure",
    "public_error_fields",
    "PlaceholderRepairDecision",
    "PlaceholderRepairer",
    "placeholder_repair_enabled",
    "PipelineResult",
    "MiddleManAgent",
    "RecordOverride",
    "UserDecision",
    "UserAction",
    "RoutingStrategy",
    "SQLiteKVCache",
    "get_cache",
    "process",
    "process_with_decision",
    "summarize_extraction",
    "format_extraction_for_user",
]
