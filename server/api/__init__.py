"""Privacy Router Server — API package.

Barrel pattern: import everything from ``server.api`` instead of submodules.

Public API
----------
app          — FastAPI application instance
STATIC_DIR   — Path to SvelteKit build output
require_auth — Bearer token auth dependency
create_api_key — API key generation
adapter_for  — LiteLLM adapter resolver
"""

from __future__ import annotations

from pathlib import Path

from server.api.adapter import adapter_for
from server.api.auth import create_api_key, require_admin_auth, require_auth
from server.api.masking import (
    ContextSegment,
    chat_context_segments,
    chat_context_text,
    contains_uninspected_media,
    mask_chat_messages,
    mask_responses_input,
    merge_context_segments,
    render_context_segments,
    responses_context_segments,
    responses_context_text,
    responses_input_to_messages,
    session_cache_key,
    without_uninspected_media,
)
from server.api.streaming import (
    StreamingHydrator,
    build_tool_argument_inspection,
    build_tool_call_inspection,
    flush_stream_hydrator,
    hydrate_masked_response,
    hydrate_stream_chunk,
    hydrate_tool_call_arguments,
    mask_sensitive_tool_call_arguments,
    merge_stream_tool_call_type,
    normalize_tool_call_arguments,
    reject_sensitive_tool_call_protocol_fields,
    sensitive_tool_arguments_allowed,
    validate_stream_tool_call_index,
    validate_stream_tool_call_indices,
    validate_tool_call_identifier_groups,
    validate_tool_call_protocol,
)

# Directory containing demo web UI
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "build"


def __getattr__(name: str):
    """Lazy import for ``app`` to break circular import chain.

    server.api.main imports route modules (side-effect), which in turn
    import from server.api. Using __getattr__ defers the import until
    ``app`` is first accessed, at which point the barrel is fully loaded.
    """
    if name == "app":
        from server.api.main import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "STATIC_DIR",
    "ContextSegment",
    "StreamingHydrator",
    "chat_context_segments",
    "chat_context_text",
    "contains_uninspected_media",
    "adapter_for",
    "app",
    "build_tool_argument_inspection",
    "build_tool_call_inspection",
    "create_api_key",
    "flush_stream_hydrator",
    "hydrate_masked_response",
    "hydrate_stream_chunk",
    "mask_chat_messages",
    "mask_sensitive_tool_call_arguments",
    "merge_stream_tool_call_type",
    "normalize_tool_call_arguments",
    "reject_sensitive_tool_call_protocol_fields",
    "mask_responses_input",
    "merge_context_segments",
    "responses_context_text",
    "render_context_segments",
    "responses_context_segments",
    "sensitive_tool_arguments_allowed",
    "validate_stream_tool_call_indices",
    "validate_stream_tool_call_index",
    "validate_tool_call_identifier_groups",
    "validate_tool_call_protocol",
    "session_cache_key",
    "responses_input_to_messages",
    "without_uninspected_media",
    "require_admin_auth",
    "require_auth",
    "hydrate_tool_call_arguments",
]
