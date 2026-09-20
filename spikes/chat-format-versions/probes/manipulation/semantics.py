"""Conservative leaf semantics over original objects, not normalized payloads.

These are spike rules, not complete provider schemas. Unknown leaves remain
visible. Attachment classification means locating an attachment, not inspecting
its bytes, performing OCR, fetching a URL, or decoding base64.
"""

from __future__ import annotations

from typing import Any

from .core import Path

Meaning = tuple[str, bool, str]
Context = list[tuple[Any, str | int]]
_UNKNOWN: Meaning = ("unknown", True, "unrecognized field; not semantically examined")
_CONTROL: Meaning = ("control", False, "protocol or linkage field")


def _get(node: Any, key: str, default: Any = None) -> Any:
    return node.get(key, default) if isinstance(node, dict) else getattr(node, key, default)


def _context(root: Any, path: Path) -> Context:
    result: Context = []
    node = root
    for step in path:
        # Native Pydantic storage is not a provider field. Keep the real extra
        # keys in the semantic context (LiteLLM stores tool-call fields here).
        if not (step.kind == "attr" and step.key == "__pydantic_extra__"):
            result.append((node, step.key))
        node = node[step.key] if step.kind == "item" else getattr(node, step.key)
    return result


def _under(context: Context, *names: str) -> bool:
    return any(key in names for _, key in context)


def _block(context: Context, *kinds: str) -> bool:
    return any(_get(node, "type") in kinds for node, _ in context)


def _role(context: Context, *roles: str) -> bool:
    return any(_get(node, "role") in roles or _get(node, "type") in roles for node, _ in context)


def _signed(context: Context) -> Meaning | None:
    for node, key in context:
        kind = _get(node, "type")
        if kind in ("thinking", "redacted_thinking"):
            # Even synthetic signatures stand in for a signed provider block.
            # Redacted thinking is opaque, and unsigned thinking is conservative.
            if key == "thinking" and kind == "thinking":
                return "text", False, "signed thinking; preserve the entire block and signature"
            return "control", False, "signed or redacted thinking; preserve the entire block"
        if key in ("signature", "encrypted_content", "reasoning_signature"):
            return "control", False, "signature or encrypted reasoning; not inspected"
    return None


def _extension(context: Context, fields: frozenset[str], data: frozenset[str]) -> bool:
    # Stop at native data containers; their arbitrary keys are not protocol
    # fields. Else an unrecognized ancestor makes its entire subtree unknown.
    for node, key in context:
        if isinstance(node, (list, tuple)):
            continue
        if key not in fields:
            return True
        if key in data:
            return False
    return False


_OPENAI_FIELDS = frozenset(
    {
        "messages",
        "choices",
        "message",
        "delta",
        "content",
        "text",
        "refusal",
        "input",
        "output",
        "instructions",
        "tool_calls",
        "function_call",
        "function",
        "arguments",
        "tools",
        "parameters",
        "description",
        "strict",
        "metadata",
        "image_url",
        "input_audio",
        "audio",
        "file",
        "url",
        "data",
        "file_data",
        "file_id",
        "file_url",
        "detail",
        "format",
        "filename",
        "expires_at",
        "id",
        "call_id",
        "tool_call_id",
        "role",
        "type",
        "model",
        "object",
        "created",
        "created_at",
        "index",
        "finish_reason",
        "status",
        "stream",
        "name",
        "tool_choice",
        "parallel_tool_calls",
        "temperature",
        "top_p",
        "max_tokens",
        "max_output_tokens",
        "previous_response_id",
        "service_tier",
        "system_fingerprint",
        "seed",
        "store",
        "usage",
        "cache_control",
    }
)
_OPENAI_DATA = frozenset({"metadata", "parameters", "arguments", "usage", "cache_control"})
_ANTHROPIC_FIELDS = frozenset(
    {
        "messages",
        "content",
        "system",
        "text",
        "thinking",
        "signature",
        "input",
        "tools",
        "input_schema",
        "description",
        "metadata",
        "source",
        "url",
        "data",
        "media_type",
        "id",
        "tool_use_id",
        "role",
        "type",
        "model",
        "name",
        "max_tokens",
        "stop_reason",
        "stop_sequence",
        "is_error",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "cache_control",
        "usage",
    }
)
_ANTHROPIC_DATA = frozenset({"input", "input_schema", "metadata", "cache_control", "usage"})
_LITELLM_FIELDS = _OPENAI_FIELDS | {"provider_specific_fields", "reasoning_content", "thinking_blocks"}
_LITELLM_DATA = _OPENAI_DATA | {"provider_specific_fields"}
_LANGCHAIN_FIELDS = frozenset(
    {
        "messages",
        "content",
        "text",
        "type",
        "role",
        "id",
        "name",
        "status",
        "tool_calls",
        "args",
        "tool_call_id",
        "index",
        "artifact",
        "additional_kwargs",
        "response_metadata",
        "metadata",
        "usage_metadata",
        "tools",
        "function",
        "parameters",
        "description",
        "strict",
        "image_url",
        "url",
        "data",
        "source",
        "media_type",
        "file",
        "file_id",
        "file_data",
        "filename",
    }
)
_LANGCHAIN_DATA = frozenset(
    {
        "args",
        "artifact",
        "additional_kwargs",
        "response_metadata",
        "metadata",
        "usage_metadata",
        "parameters",
    }
)


def _attachment(context: Context, value: Any) -> Meaning | None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "attachment", True, "opaque bytes; whole-value replacement only; no OCR or content inspection"
    if not context:
        return None
    key = context[-1][1]
    if _under(context, "image_url", "input_audio", "audio", "file") or _block(
        context,
        "image",
        "image_url",
        "input_image",
        "image_file",
        "document",
        "file",
        "input_file",
        "input_audio",
        "audio",
    ):
        if key in ("file_id", "id"):
            return "attachment", False, "file reference; bytes are not fetched or inspected"
        if key in ("url", "image_url", "file_url"):
            return "attachment", True, "URL/reference only; bytes are not fetched or inspected"
        if key in ("data", "file_data", "base64", "base64_data"):
            return "attachment", True, "encoded attachment; bytes are not decoded or inspected"
        if key in ("type", "detail", "media_type", "mime_type", "format", "filename", "expires_at"):
            return _CONTROL
    return None


def _data(category: str, value: Any, note: str = "") -> Meaning:
    if value is None:
        return category, False, "explicit null or absent-field default; not textual content"
    return category, True, note


def _tools(context: Context, value: Any) -> Meaning | None:
    if not _under(context, "tools"):
        return None
    key = context[-1][1]
    # Descriptions/defaults/examples may carry private data; schema structure,
    # field names, required lists and enums are not safe automatic text edits.
    if _under(context, "parameters", "input_schema"):
        return (
            "tool_definition",
            _under(context, "description", "title", "default", "examples"),
            "tool schema; structural fields protected",
        )
    if key == "description":
        return _data("tool_definition", value)
    return "tool_definition", False, "tool name or invocation/schema control"


def _openai(context: Context, value: Any) -> Meaning:
    if _extension(context, _OPENAI_FIELDS, _OPENAI_DATA):
        return _UNKNOWN
    tools = _tools(context, value)
    if tools is not None:
        return tools
    if _under(context, "metadata"):
        return _attachment(context, value) or _data("metadata", value)
    key = context[-1][1] if context else None
    # Argument data wins over field names such as id/model inside native inputs.
    if _under(context, "arguments") and (
        _under(context, "tool_calls", "function_call") or _block(context, "function_call")
    ):
        return _data("tool_request", value, "json_text" if isinstance(value, str) else "native argument value")
    attachment = _attachment(context, value)
    if attachment is not None:
        return attachment
    if key in {
        "id",
        "call_id",
        "tool_call_id",
        "role",
        "type",
        "model",
        "object",
        "created",
        "created_at",
        "index",
        "finish_reason",
        "status",
        "stream",
        "name",
        "tool_choice",
        "parallel_tool_calls",
        "temperature",
        "top_p",
        "max_tokens",
        "max_output_tokens",
        "previous_response_id",
        "service_tier",
        "system_fingerprint",
        "seed",
        "store",
    } or _under(context, "usage", "cache_control"):
        return _CONTROL
    if _block(context, "function_call_output") and _under(context, "output"):
        return _data("tool_result", value)
    if _role(context, "tool", "function") and _under(context, "content"):
        return _data("tool_result", value)
    parent = context[-1][0] if context else None
    if key in ("text", "refusal") and _get(parent, "type") in ("text", "input_text", "output_text", "refusal"):
        return _data("text", value)
    if key == "content" and (_role(context, "assistant", "user", "system", "developer") or _under(context, "delta")):
        return _data("text", value)
    if key == "instructions" and len(context) == 1:
        return _data("text", value)
    return _UNKNOWN


def _anthropic(context: Context, value: Any) -> Meaning:
    if _extension(context, _ANTHROPIC_FIELDS, _ANTHROPIC_DATA):
        return _UNKNOWN
    tools = _tools(context, value)
    if tools is not None:
        return tools
    if _under(context, "metadata"):
        return _attachment(context, value) or _data("metadata", value)
    if _block(context, "tool_use", "server_tool_use") and _under(context, "input"):
        return _data("tool_request", value, "native argument value")
    attachment = _attachment(context, value)
    if attachment is not None:
        return attachment
    key = context[-1][1] if context else None
    if key in {
        "id",
        "tool_use_id",
        "role",
        "type",
        "model",
        "name",
        "max_tokens",
        "stop_reason",
        "stop_sequence",
        "is_error",
        "stream",
        "temperature",
        "top_p",
        "top_k",
    } or _under(context, "cache_control", "usage"):
        return _CONTROL
    if _block(context, "tool_result") and _under(context, "content"):
        return _data("tool_result", value)
    parent = context[-1][0] if context else None
    if key == "text" and _get(parent, "type") == "text":
        return _data("text", value)
    if key == "content" and _role(context, "assistant", "user"):
        return _data("text", value)
    if key == "system" and len(context) == 1:
        return _data("text", value)
    return _UNKNOWN


def _litellm(context: Context, value: Any) -> Meaning:
    if _extension(context, _LITELLM_FIELDS, _LITELLM_DATA):
        return _UNKNOWN
    if _under(context, "provider_specific_fields"):
        if context[-1][1] in ("cache_hit", "cache_control", "cache_creation_input_tokens", "cache_read_input_tokens"):
            return _CONTROL
        return _attachment(context, value) or _data(
            "metadata", value, "provider metadata; no provider-specific interpretation"
        )
    if context and context[-1][1] == "reasoning_content" and _role(context, "assistant"):
        return _data("text", value, "unsigned reasoning text; provider-specific semantics may vary")
    # LiteLLM deliberately exposes the OpenAI completion request/message shape.
    return _openai(context, value)


def _langchain(context: Context, value: Any) -> Meaning:
    if _extension(context, _LANGCHAIN_FIELDS, _LANGCHAIN_DATA):
        return _UNKNOWN
    tools = _tools(context, value)
    if tools is not None:
        return tools
    if _under(context, "tool_calls") and _under(context, "args"):
        return _data("tool_request", value, "native argument value")
    if _under(context, "additional_kwargs", "response_metadata", "metadata"):
        if context[-1][1] in ("cache_hit", "cache_control") or _under(context, "cache_control"):
            return _CONTROL
        return _attachment(context, value) or _data("metadata", value, "native metadata; not normalized")
    if _under(context, "artifact"):
        return _attachment(context, value) or _data(
            "tool_result", value, "local artifact; not necessarily sent to model"
        )
    attachment = _attachment(context, value)
    if attachment is not None:
        return attachment
    key = context[-1][1] if context else None
    if key in {"id", "tool_call_id", "type", "role", "name", "status", "index"} or _under(context, "usage_metadata"):
        return _CONTROL
    if _role(context, "tool", "function") and _under(context, "content"):
        return _data("tool_result", value)
    parent = context[-1][0] if context else None
    if key == "text" and _get(parent, "type") == "text":
        return _data("text", value)
    if key == "content" and _role(
        context, "system", "human", "ai", "SystemMessageChunk", "HumanMessageChunk", "AIMessageChunk"
    ):
        return _data("text", value)
    return _UNKNOWN


_RULES = {"openai": _openai, "anthropic": _anthropic, "litellm": _litellm, "langchain-core": _langchain}


def classify(provider: str, root: Any, path: Path, value: Any) -> Meaning:
    """Return (category, editable, note) without changing the native payload.

    Signed blocks and unknown opaque objects are exposed but cannot be edited.
    Path resolution obeys item/attribute distinctions supplied by the traversal.
    """
    try:
        rule = _RULES[provider]
    except KeyError:
        raise ValueError(f"Unsupported semantic provider: {provider}") from None
    context = _context(root, path)
    signed = _signed(context)
    if signed is not None:
        return signed
    if not isinstance(value, (str, bytes, bytearray, memoryview, int, float, bool, type(None), dict, list, tuple)):
        return "unknown", False, "opaque native value; not inspected or editable"
    return rule(context, value)
