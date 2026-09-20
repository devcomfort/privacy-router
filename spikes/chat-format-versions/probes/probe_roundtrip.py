from __future__ import annotations

import argparse
import json
import math
import sys
from importlib.metadata import version
from typing import Any

from pydantic import BaseModel

from probe_common import load_messages


def snapshot(value: Any, *, presence: bool = False) -> Any:
    """Inspect original values, not their potentially lossy model_dump output."""
    kind = f"{type(value).__module__}.{type(value).__qualname__}"
    if isinstance(value, BaseModel):
        fields = {key: item for key, item in vars(value).items() if not key.startswith("_")}
        fields.update(value.model_extra or {})
        result = {
            "type": kind,
            "fields": {key: snapshot(item, presence=presence) for key, item in fields.items()},
        }
        if presence:
            result["fields_set"] = sorted(value.model_fields_set)
        return result
    if isinstance(value, dict):
        items = [
            [snapshot(key, presence=presence), snapshot(item, presence=presence)]
            for key, item in value.items()
        ]
        return {"type": kind, "items": sorted(items, key=lambda pair: repr(pair[0]))}
    if isinstance(value, (tuple, list)):
        return {"type": kind, "items": [snapshot(item, presence=presence) for item in value]}
    if value is None or isinstance(value, (str, int, bool)):
        return {"type": kind, "value": value}
    if isinstance(value, float) and math.isfinite(value):
        return {"type": kind, "value": value.hex()}
    return {"type": kind, "repr": repr(value)}


def differences(before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(before) is not type(after):
        return [{"path": path, "before": before, "after": after}]
    if isinstance(before, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                result.append({"path": f"{path}.{key}", "before": before.get(key, "<absent>"), "after": after.get(key, "<absent>")})
            else:
                result.extend(differences(before[key], after[key], f"{path}.{key}"))
        return result
    if isinstance(before, list):
        if len(before) != len(after):
            return [{"path": path, "before": before, "after": after}]
        return [difference for index, (left, right) in enumerate(zip(before, after)) for difference in differences(left, right, f"{path}[{index}]")]
    return [] if before == after else [{"path": path, "before": before, "after": after}]


def roundtrip(name: str, original: Any, export, restore, route: str) -> dict[str, Any]:
    before = snapshot(original)
    before_presence = snapshot(original, presence=True)
    stage = "export"
    try:
        exported = export(original)
        stage = "JSON encoding"
        wire = json.dumps(exported, ensure_ascii=False, allow_nan=False).encode("utf-8")
        stage = "JSON decoding and restoration"
        restored = restore(json.loads(wire.decode("utf-8")))
        changed = differences(before, snapshot(restored))
        presence_changed = differences(before_presence, snapshot(restored, presence=True))
        return {
            "case": name,
            "route": route,
            "status": "lossless" if not presence_changed else "lossy",
            "values_and_types_equal": not changed,
            "including_field_presence_equal": not presence_changed,
            "differences": presence_changed,
            "utf8_bytes": len(wire),
        }
    except Exception as exc:
        return {"case": name, "route": route, "status": "unsupported", "stage": stage, "error": f"{type(exc).__name__}: {exc}"}


def metadata() -> dict[str, Any]:
    return {"tags": ["한글", "e\u0301"], "nullable": None, "enabled": False, "nested": {"count": 0}, "large_integer": 2**60 + 1}


def openai_request() -> dict[str, Any]:
    messages = load_messages()
    messages.extend([
        {"role": "user", "content": [{"type": "text", "text": "이미지 설명"}, {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png", "detail": "low"}}]},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "weather", "arguments": '{"city":"Seoul"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"},
    ])
    return {"model": "spike-model", "messages": messages, "metadata": {"purpose": "roundtrip"}, "tools": [{"type": "function", "function": {"name": "weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}], "extra_payload": metadata()}


def response_cases(original: BaseModel) -> list[dict[str, Any]]:
    cls = type(original)
    return [
        roundtrip(
            "response_default_export", original,
            lambda value: value.model_dump(mode="json"), cls.model_validate,
            "model_dump(mode='json') -> JSON UTF-8 -> model_validate",
        ),
        roundtrip(
            "response_preserving_unset", original,
            lambda value: value.model_dump(mode="json", exclude_unset=True), cls.model_validate,
            "model_dump(mode='json', exclude_unset=True) -> JSON UTF-8 -> model_validate",
        ),
    ]


def probe_openai() -> list[dict[str, Any]]:
    from openai.types.chat import ChatCompletion

    request = openai_request()
    response = ChatCompletion.model_validate({
        "id": "chatcmpl-roundtrip", "object": "chat.completion", "created": 0, "model": "spike-model",
        "choices": [
            {"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": request["messages"][-2]["tool_calls"]}},
            {"index": 1, "finish_reason": "stop", "message": {"role": "assistant", "content": "한글 응답", "annotations": []}},
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        "extra_payload": metadata(),
    })
    non_json = response.model_copy(update={"extra_payload": {"pair": ("x", 1), "keyed": {7: "seven"}}})
    return [
        roundtrip("request_dict", request, lambda value: value, lambda value: value, "JSON-compatible request dict -> JSON UTF-8 -> dict"),
        *response_cases(response),
        roundtrip("non_json_python_metadata", non_json, lambda value: value.model_dump(mode="json", exclude_unset=True), ChatCompletion.model_validate, "tuple / integer dict key in extra -> model_dump(mode='json', exclude_unset=True) -> JSON UTF-8 -> model_validate"),
    ]


def probe_anthropic() -> list[dict[str, Any]]:
    from anthropic.types import Message

    fixture = load_messages()
    request = {
        "model": "spike-model", "max_tokens": 64,
        "system": [{"type": "text", "text": fixture[0]["content"], "cache_control": {"type": "ephemeral"}}],
        "messages": [
            fixture[1], fixture[2],
            {"role": "user", "content": [{"type": "text", "text": "이미지 설명"}, {"type": "image", "source": {"type": "url", "url": "https://example.invalid/image.png"}}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"city": "Seoul"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny", "is_error": False}]},
        ],
        "tools": [{"name": "weather", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}],
        "extra_payload": metadata(),
    }
    response = Message.model_validate({
        "id": "msg_roundtrip", "type": "message", "role": "assistant", "model": "spike-model",
        "content": [
            {"type": "thinking", "thinking": "synthetic reasoning", "signature": "synthetic-signature"},
            {"type": "text", "text": "한글 응답", "citations": None},
            {"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"city": "Seoul"}},
        ],
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 5}, "extra_payload": metadata(),
    })
    non_json = response.model_copy(update={"extra_payload": {"pair": ("x", 1), "keyed": {7: "seven"}}})
    return [
        roundtrip("request_dict", request, lambda value: value, lambda value: value, "JSON-compatible request dict (including top-level system) -> JSON UTF-8 -> dict"),
        *response_cases(response),
        roundtrip("non_json_python_metadata", non_json, lambda value: value.model_dump(mode="json", exclude_unset=True), Message.model_validate, "tuple / integer dict key in extra -> model_dump(mode='json', exclude_unset=True) -> JSON UTF-8 -> model_validate"),
    ]


def probe_litellm() -> list[dict[str, Any]]:
    from litellm.types.utils import Message

    request = openai_request()
    response = Message(
        role="assistant", content=None, tool_calls=request["messages"][-2]["tool_calls"],
        reasoning_content="synthetic reasoning", provider_specific_fields=metadata(),
        extra_payload={"unknown_field": [1, None, "한글"]},
    )
    non_json = Message(role="assistant", content="boundary", provider_specific_fields={"pair": ("x", 1), "keyed": {7: "seven"}})
    return [
        roundtrip("request_dict", request, lambda value: value, lambda value: value, "JSON-compatible completion request dict -> JSON UTF-8 -> dict"),
        *response_cases(response),
        roundtrip("response_to_dict", response, lambda value: value.to_dict(), Message.model_validate, "to_dict() -> JSON UTF-8 -> model_validate"),
        roundtrip("non_json_python_metadata", non_json, lambda value: value.model_dump(mode="json", exclude_unset=True), Message.model_validate, "tuple / integer dict key in provider_specific_fields -> model_dump(mode='json', exclude_unset=True) -> JSON UTF-8 -> model_validate"),
    ]


def probe_langchain() -> list[dict[str, Any]]:
    from langchain_core.messages import AIMessage, ChatMessage, FunctionMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.messages.base import messages_to_dict
    from langchain_core.messages.utils import messages_from_dict

    fixture = load_messages()
    messages = [
        SystemMessage(content=fixture[0]["content"], id="system-1"),
        HumanMessage(content=[{"type": "text", "text": fixture[1]["content"]}, {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}}], name="speaker", id="human-1", additional_kwargs=metadata(), extra_payload={"unknown_field": [None, 1]}),
        AIMessage(content=fixture[2]["content"], tool_calls=[{"name": "weather", "args": {"city": "Seoul"}, "id": "call_1", "type": "tool_call"}], usage_metadata={"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}, response_metadata=metadata()),
        ToolMessage(content="Sunny", tool_call_id="call_1", artifact={"readings": [1, 2], "unit": "C"}, status="success"),
        FunctionMessage(content="legacy result", name="weather"),
        ChatMessage(content="custom role", role="reviewer"),
    ]
    non_json = [ToolMessage(content="boundary", tool_call_id="call_1", artifact={"pair": ("x", 1), "keyed": {7: "seven"}})]
    binary = [ToolMessage(content="binary boundary", tool_call_id="call_1", artifact=b"binary")]
    return [
        roundtrip("messages_official_helpers", messages, messages_to_dict, messages_from_dict, "messages_to_dict -> JSON UTF-8 -> messages_from_dict"),
        roundtrip(
            "messages_preserving_unset", messages,
            lambda values: [{"type": value.type, "data": value.model_dump(mode="json", exclude_unset=True)} for value in values],
            messages_from_dict,
            "explicit type/data envelope using model_dump(mode='json', exclude_unset=True) -> JSON UTF-8 -> messages_from_dict",
        ),
        roundtrip("non_json_python_metadata", non_json, messages_to_dict, messages_from_dict, "tuple / integer dict key in artifact -> messages_to_dict -> JSON UTF-8 -> messages_from_dict"),
        roundtrip("binary_artifact", binary, messages_to_dict, messages_from_dict, "bytes artifact -> messages_to_dict -> JSON UTF-8 -> messages_from_dict"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", choices=["openai", "anthropic", "litellm", "langchain-core"])
    args = parser.parse_args()
    probes = {"openai": probe_openai, "anthropic": probe_anthropic, "litellm": probe_litellm, "langchain-core": probe_langchain}
    report = {
        "library": args.library,
        "version": version(args.library),
        "python": sys.version.split()[0],
        "pydantic": version("pydantic"),
        "scope": "Same-version Python message/history data roundtrip via actual JSON UTF-8 bytes; not cross-provider conversion or HTTP API acceptance.",
        "comparison": "Public values, nested concrete types, unknown fields, array order, and separately model_fields_set. JSON object key order and private/runtime/client state excluded.",
        "cases": probes[args.library](),
    }
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
