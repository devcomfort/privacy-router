"""Synthetic offline SDK-native cases; no model calls or transport execution.

Constructors establish the initial native state once. No export/import editing is
used. File tuples live in local metadata/artifacts, not purported wire fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import Path, Step

SDK_SOURCES = {
    "openai": (
        "https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion.py",
        "https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_chunk.py",
        "https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response.py",
        "https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_function_tool_call.py",
        "https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_input_item_param.py",
    ),
    "anthropic": (
        "https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message.py",
        "https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/thinking_block.py",
        "https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/tool_result_block_param.py",
    ),
    "litellm": (
        "https://github.com/BerriAI/litellm/blob/main/litellm/types/utils.py",
        "https://docs.litellm.ai/docs/completion/input",
    ),
    "langchain-core": (
        "https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/base.py",
        "https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/ai.py",
        "https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/messages/tool.py",
    ),
}


@dataclass
class Case:
    name: str
    payload: Any
    edits: dict[Path, Any]
    required_categories: dict[Path, str]
    protected_paths: tuple[Path, ...] = ()


def item(key: str | int) -> Step:
    return Step("item", key)


def A(key: str) -> Step:
    return Step("attr", key)


def _case(
    name: str,
    payload: Any,
    edits: list[tuple[Path, Any, str]],
    required: dict[Path, str] | None = None,
    protected: tuple[Path, ...] = (),
) -> Case:
    # Expectations are authored here, independent of the classifier.
    categories = {path: category for path, _, category in edits}
    categories.update(required or {})
    return Case(name, payload, {path: value for path, value, _ in edits}, categories, protected)


RAW_ARGS = '{ "city" : "서울", "scale":1e+03, "other":"e\\u0301" }'
MASKED_ARGS = RAW_ARGS.replace('"서울"', '"[CITY]"', 1)
TEXT = "연락: alice@example.invalid; cafe\u0301"
IMAGE = "data:image/png;base64,AAECAw=="


def _metadata() -> dict[Any, Any]:
    return {
        "pair": ("e\u0301", 2**60 + 1),
        7: "integer key",
        "a.b": "literal dotted key",
        "nullable": None,
        "enabled": False,
        "upload": ("secret.bin", b"\x00\xffprivate\x80", "application/octet-stream"),
    }


def _chat_request(provider: str) -> Case:
    payload = {
        "model": "offline-spike-model",
        "stream": False,
        "messages": [
            {"role": "system", "content": "Keep the original formatting."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TEXT},
                    {"type": "image_url", "image_url": {"url": IMAGE, "detail": "low"}},
                    {"type": "image_url", "image_url": {"url": "https://example.invalid/private.png"}},
                    {"type": "file", "file": {"file_id": "file-untouched"}},
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "weather", "arguments": RAW_ARGS}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "서울: sunny"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Ask Alice about city weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string", "description": "City where Alice lives"}},
                        "required": ["city"],
                    },
                    "strict": False,
                },
            }
        ],
        "metadata": _metadata(),
        "unknown_extension": {"text": "not a known text field", "null": None},
    }
    return _case(
        f"{provider}_request",
        payload,
        [
            ((item("messages"), item(1), item("content"), item(0), item("text")), "연락: [EMAIL]; cafe\u0301", "text"),
            (
                (item("messages"), item(2), item("tool_calls"), item(0), item("function"), item("arguments")),
                MASKED_ARGS,
                "tool_request",
            ),
            ((item("messages"), item(3), item("content")), "[CITY]: sunny", "tool_result"),
            (
                (item("tools"), item(0), item("function"), item("description")),
                "Ask [PERSON] about city weather",
                "tool_definition",
            ),
            ((item("metadata"), item("upload"), item(1)), b"\x00[REDACTED]\x80", "attachment"),
        ],
        {
            (item("messages"), item(1), item("content"), item(1), item("image_url"), item("url")): "attachment",
            (item("messages"), item(1), item("content"), item(2), item("image_url"), item("url")): "attachment",
            (
                item("tools"),
                item(0),
                item("function"),
                item("parameters"),
                item("properties"),
                item("city"),
                item("description"),
            ): "tool_definition",
            (item("metadata"), item(7)): "metadata",
            (item("unknown_extension"), item("text")): "unknown",
        },
        (
            (item("model"),),
            (item("messages"), item(2), item("tool_calls"), item(0), item("id")),
            (item("messages"), item(3), item("tool_call_id")),
            (item("messages"), item(1), item("content"), item(3), item("file"), item("file_id")),
        ),
    )


def _openai() -> list[Case]:
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
    from openai.types.responses import Response

    chat = ChatCompletion(
        id="chatcmpl_offline",
        object="chat.completion",
        created=0,
        model="offline-spike-model",
        choices=[
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "weather", "arguments": RAW_ARGS}}
                    ],
                },
            },
            {"index": 1, "finish_reason": "stop", "message": {"role": "assistant", "content": TEXT}},
        ],
        extra_payload=_metadata(),
        unknown_extension={"future": "preserve me"},
    )
    response = Response(
        id="resp_offline",
        object="response",
        created_at=0.0,
        model="offline-spike-model",
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        error=None,
        output=[
            {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": TEXT, "annotations": []}],
            },
            {
                "id": "fc_offline",
                "type": "function_call",
                "call_id": "call_2",
                "name": "weather",
                "arguments": RAW_ARGS,
            },
        ],
        extra_payload=_metadata(),
    )
    request = {
        "model": "offline-spike-model",
        "input": [
            {"type": "function_call", "call_id": "call_2", "name": "weather", "arguments": RAW_ARGS},
            {"type": "function_call_output", "call_id": "call_2", "output": "서울: sunny"},
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "file_data": "data:application/pdf;base64,AAEC", "filename": "private.pdf"}
                ],
            },
        ],
        "instructions": TEXT,
        "metadata": {"local": "offline"},
    }
    chunk = ChatCompletionChunk(
        id="chatcmpl_chunk",
        object="chat.completion.chunk",
        created=0,
        model="offline-spike-model",
        choices=[
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": TEXT,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_chunk",
                            "type": "function",
                            "function": {"name": "weather", "arguments": RAW_ARGS},
                        }
                    ],
                },
                "finish_reason": None,
            }
        ],
    )
    return [
        _chat_request("openai"),
        _case(
            "openai_chat_completion",
            chat,
            [
                ((A("choices"), item(1), A("message"), A("content")), "[EMAIL]; cafe\u0301", "text"),
                (
                    (A("choices"), item(0), A("message"), A("tool_calls"), item(0), A("function"), A("arguments")),
                    MASKED_ARGS,
                    "tool_request",
                ),
                ((A("__pydantic_extra__"), item("extra_payload"), item("a.b")), "edited literal key", "unknown"),
            ],
            {(A("__pydantic_extra__"), item("extra_payload"), item("pair"), item(1)): "unknown"},
            ((A("id"),),),
        ),
        _case(
            "openai_responses_native_output",
            response,
            [
                ((A("output"), item(0), A("content"), item(0), A("text")), "[EMAIL]; cafe\u0301", "text"),
                ((A("output"), item(1), A("arguments")), MASKED_ARGS, "tool_request"),
            ],
            protected=((A("output"), item(1), A("call_id")), (A("output"), item(0), A("id"))),
        ),
        _case(
            "openai_responses_function_output_request",
            request,
            [
                ((item("input"), item(0), item("arguments")), MASKED_ARGS, "tool_request"),
                ((item("input"), item(1), item("output")), "[CITY]: sunny", "tool_result"),
                ((item("instructions"),), "[EMAIL]; cafe\u0301", "text"),
            ],
            {(item("input"), item(2), item("content"), item(0), item("file_data")): "attachment"},
            ((item("input"), item(1), item("call_id")),),
        ),
        _case(
            "openai_chunk_transport_not_tested",
            chunk,
            [
                ((A("choices"), item(0), A("delta"), A("content")), "[EMAIL]; cafe\u0301", "text"),
                (
                    (A("choices"), item(0), A("delta"), A("tool_calls"), item(0), A("function"), A("arguments")),
                    MASKED_ARGS,
                    "tool_request",
                ),
            ],
            protected=((A("id"),), (A("choices"), item(0), A("delta"), A("role"))),
        ),
    ]


def _anthropic() -> list[Case]:
    from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage

    message = Message(
        id="msg_offline",
        type="message",
        role="assistant",
        model="offline-spike-model",
        content=[
            ThinkingBlock(type="thinking", thinking="Alice's signed reasoning", signature="synthetic-signature"),
            TextBlock(type="text", text=TEXT, citations=None),
            ToolUseBlock(
                type="tool_use", id="toolu_1", name="weather", input={"city": "서울", "scale": 1000.0, "nullable": None}
            ),
        ],
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=7, output_tokens=4),
        extra_payload=_metadata(),
        unknown_extension={"future": "preserve me"},
    )
    request = {
        "model": "offline-spike-model",
        "max_tokens": 64,
        "system": [{"type": "text", "text": TEXT, "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"city": "서울"}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "is_error": False,
                        "content": [
                            {"type": "text", "text": "서울: sunny"},
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": "image/png", "data": "AAECAw=="},
                            },
                        ],
                    },
                    {"type": "document", "source": {"type": "url", "url": "https://example.invalid/private.pdf"}},
                ],
            },
        ],
        "tools": [
            {
                "name": "weather",
                "description": "Alice's weather tool",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "Alice's city"}},
                },
            }
        ],
        "metadata": {"user_id": "offline-user"},
        "extra_payload": _metadata(),
    }
    return [
        _case(
            "anthropic_message_signed_thinking",
            message,
            [
                ((A("content"), item(1), A("text")), "[EMAIL]; cafe\u0301", "text"),
                ((A("content"), item(2), A("input"), item("city")), "[CITY]", "tool_request"),
                ((A("__pydantic_extra__"), item("extra_payload"), item(7)), "edited integer key", "unknown"),
            ],
            {(A("content"), item(0), A("thinking")): "text"},
            (
                (A("content"), item(0), A("thinking")),
                (A("content"), item(0), A("signature")),
                (A("content"), item(2), A("id")),
                (A("role"),),
            ),
        ),
        _case(
            "anthropic_native_tool_result_request",
            request,
            [
                ((item("system"), item(0), item("text")), "[EMAIL]; cafe\u0301", "text"),
                (
                    (item("messages"), item(0), item("content"), item(0), item("input"), item("city")),
                    "[CITY]",
                    "tool_request",
                ),
                (
                    (item("messages"), item(1), item("content"), item(0), item("content"), item(0), item("text")),
                    "[CITY]: sunny",
                    "tool_result",
                ),
                ((item("tools"), item(0), item("description")), "[PERSON]'s weather tool", "tool_definition"),
            ],
            {
                (
                    item("messages"),
                    item(1),
                    item("content"),
                    item(0),
                    item("content"),
                    item(1),
                    item("source"),
                    item("data"),
                ): "attachment",
                (item("messages"), item(1), item("content"), item(1), item("source"), item("url")): "attachment",
            },
            (
                (item("system"), item(0), item("cache_control"), item("type")),
                (item("messages"), item(1), item("content"), item(0), item("tool_use_id")),
            ),
        ),
    ]


def _litellm() -> list[Case]:
    from litellm.types.utils import Message

    payload = Message(
        role="assistant",
        content=TEXT,
        reasoning_content="Unsigned Alice reasoning",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "weather", "arguments": RAW_ARGS}}],
        provider_specific_fields=_metadata(),
        unknown_extension={"future": "preserve me"},
    )
    return [
        _chat_request("litellm"),
        _case(
            "litellm_native_message",
            payload,
            [
                ((A("content"),), "[EMAIL]; cafe\u0301", "text"),
                (
                    (A("tool_calls"), item(0), A("__pydantic_extra__"), item("function"), A("arguments")),
                    MASKED_ARGS,
                    "tool_request",
                ),
                ((A("provider_specific_fields"), item("a.b")), "edited literal key", "metadata"),
                ((A("provider_specific_fields"), item("upload"), item(1)), b"[REDACTED]", "attachment"),
            ],
            {(A("__pydantic_extra__"), item("unknown_extension"), item("future")): "unknown"},
            ((A("role"),), (A("tool_calls"), item(0), A("__pydantic_extra__"), item("id"))),
        ),
    ]


def _langchain() -> list[Case]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    messages = [
        SystemMessage(content="System for Alice", id="system_1"),
        HumanMessage(
            content=[{"type": "text", "text": TEXT}, {"type": "image_url", "image_url": {"url": IMAGE}}],
            id="human_1",
            name=None,
            additional_kwargs=_metadata(),
            unknown_extension={"future": "preserve me"},
        ),
        AIMessage(
            content="Calling Alice's tool",
            id="ai_1",
            tool_calls=[
                {"name": "weather", "args": {"city": "서울", "nullable": None}, "id": "call_1", "type": "tool_call"}
            ],
            response_metadata={"cache_hit": True},
        ),
        ToolMessage(content="서울: sunny", tool_call_id="call_1", id="tool_1", status="success", artifact=_metadata()),
    ]
    # Runnable-style native input dict, not a claimed universal LangChain wire API.
    request = {
        "messages": [HumanMessage(content=TEXT, id="request_human")],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Alice's tool",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ],
        "metadata": _metadata(),
    }
    return [
        _case(
            "langchain_native_message_list",
            messages,
            [
                ((item(1), A("content"), item(0), item("text")), "[EMAIL]; cafe\u0301", "text"),
                ((item(2), A("tool_calls"), item(0), item("args"), item("city")), "[CITY]", "tool_request"),
                ((item(3), A("content")), "[CITY]: sunny", "tool_result"),
                ((item(3), A("artifact"), item("upload"), item(1)), b"[REDACTED]", "attachment"),
                ((item(1), A("additional_kwargs"), item("a.b")), "edited literal key", "metadata"),
            ],
            {
                (item(1), A("__pydantic_extra__"), item("unknown_extension"), item("future")): "unknown",
                (item(1), A("content"), item(1), item("image_url"), item("url")): "attachment",
                (item(3), A("artifact"), item(7)): "tool_result",
            },
            (
                (item(3), A("tool_call_id")),
                (item(2), A("tool_calls"), item(0), item("id")),
                (item(2), A("response_metadata"), item("cache_hit")),
            ),
        ),
        _case(
            "langchain_runnable_input_dict",
            request,
            [
                ((item("messages"), item(0), A("content")), "[EMAIL]; cafe\u0301", "text"),
                ((item("tools"), item(0), item("function"), item("description")), "[PERSON]'s tool", "tool_definition"),
                ((item("metadata"), item("upload"), item(1)), b"[REDACTED]", "attachment"),
            ],
            protected=((item("messages"), item(0), A("id")),),
        ),
    ]


def build_cases(provider: str) -> list[Case]:
    """Construct only the selected provider's offline native objects."""
    builders = {"openai": _openai, "anthropic": _anthropic, "litellm": _litellm, "langchain-core": _langchain}
    try:
        builder = builders[provider]
    except KeyError:
        raise ValueError(f"Unsupported fixture provider: {provider}") from None
    return builder()
