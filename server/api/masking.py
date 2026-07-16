"""Message-local masking helpers for OpenAI-compatible request shapes."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agents import ExtractionRecord, Masker, MaskingContract, cache_fingerprint


@dataclass(frozen=True)
class MaskedPayload[T]:
    """A shape-preserving masked request and its merged contract."""

    value: T
    contract: MaskingContract
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None


@dataclass(frozen=True)
class ContextSegment:
    """One labeled text field supplied to privacy analysis."""

    label: str
    text: str


@dataclass(frozen=True)
class _TextSlot:
    container: dict[str, Any] | list[Any]
    key: str | int
    text: str
    label: str


def chat_context_segments(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> list[ContextSegment]:
    """Return all text-bearing chat fields as labeled context segments."""
    return _context_segments(
        [
            *_chat_context_slots(messages, include_protocol_fields=True),
            *_tool_context_slots(tools, tool_choice, include_protocol_fields=True),
        ]
    )


def chat_context_text(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> str:
    return render_context_segments(
        chat_context_segments(
            messages,
            tools=tools,
            tool_choice=tool_choice,
        )
    )


def mask_chat_messages(
    messages: list[dict[str, Any]],
    records: list[ExtractionRecord],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> MaskedPayload[list[dict[str, Any]]]:
    """Mask every text-bearing chat and tool field without changing shape."""
    masked = deepcopy(messages)
    masked_tools = deepcopy(tools)
    choice_holder = {"tool_choice": deepcopy(tool_choice)}
    _reject_sensitive_protocol_fields(
        records,
        [
            *_protocol_field_slots(masked, "messages"),
            *_tool_protocol_field_slots(
                masked_tools,
                choice_holder["tool_choice"],
                choice_holder,
            ),
        ],
    )
    slots = [
        *_chat_context_slots(masked),
        *_tool_context_slots(masked_tools, choice_holder["tool_choice"], choice_holder),
    ]
    contract = _mask_slots(slots, records)
    return MaskedPayload(
        value=masked,
        contract=contract,
        tools=masked_tools,
        tool_choice=choice_holder["tool_choice"],
    )


def mask_responses_input(
    input_data: str | list[Any],
    records: list[ExtractionRecord],
    *,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> MaskedPayload[str | list[Any]]:
    """Mask all OpenResponses context while preserving its request shape."""
    if isinstance(input_data, str) and instructions is None and not tools and tool_choice is None:
        result = Masker().mask(input_data, [_record_dict(record) for record in records])
        return MaskedPayload(value=result.masked_text, contract=result.contract)

    instruction_holder = {"instructions": instructions}
    if isinstance(input_data, str):
        input_holder = {"input": input_data}
        slots = [_TextSlot(input_holder, "input", input_data, "input")]
        masked: str | list[Any] = input_data
    else:
        masked = deepcopy(input_data)
        input_holder = None
        slots = _responses_context_slots(masked)
    masked_tools = deepcopy(tools)
    choice_holder = {"tool_choice": deepcopy(tool_choice)}
    _reject_sensitive_protocol_fields(
        records,
        [
            *(_protocol_field_slots(masked, "input") if isinstance(masked, list) else []),
            *_tool_protocol_field_slots(
                masked_tools,
                choice_holder["tool_choice"],
                choice_holder,
            ),
        ],
    )
    slots.extend(_tool_context_slots(masked_tools, choice_holder["tool_choice"], choice_holder))
    if instructions is not None:
        slots.insert(
            0,
            _TextSlot(
                instruction_holder,
                "instructions",
                instructions,
                "instructions",
            ),
        )
    contract = _mask_slots(slots, records)
    if input_holder is not None:
        masked = input_holder["input"]
    return MaskedPayload(
        value=masked,
        contract=contract,
        instructions=instruction_holder["instructions"],
        tools=masked_tools,
        tool_choice=choice_holder["tool_choice"],
    )


def responses_context_segments(
    input_data: str | list[Any],
    *,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> list[ContextSegment]:
    """Return all text-bearing Responses fields as labeled context segments."""
    slots: list[_TextSlot] = []
    instruction_holder = {"instructions": instructions}
    if instructions is not None:
        slots.append(
            _TextSlot(
                instruction_holder,
                "instructions",
                instructions,
                "instructions",
            )
        )
    if isinstance(input_data, str):
        input_holder = {"input": input_data}
        slots.append(_TextSlot(input_holder, "input", input_data, "input"))
    else:
        slots.extend(
            _responses_context_slots(
                input_data,
                include_protocol_fields=True,
            )
        )
    slots.extend(
        _tool_context_slots(
            tools,
            tool_choice,
            include_protocol_fields=True,
        )
    )
    return _context_segments(slots)


def responses_context_text(
    input_data: str | list[Any],
    *,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> str:
    return render_context_segments(
        responses_context_segments(
            input_data,
            instructions=instructions,
            tools=tools,
            tool_choice=tool_choice,
        )
    )


def responses_input_to_messages(
    input_data: str | list[Any],
    *,
    instructions: str | None = None,
) -> list[dict[str, Any]]:
    """Translate complete OpenResponses context to chat messages."""
    messages: list[dict[str, Any]] = []
    if instructions is not None:
        messages.append({"role": "system", "content": instructions})
    if isinstance(input_data, str):
        messages.append({"role": "user", "content": input_data})
        return messages

    for item in input_data:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")
        if item_type in {"function_call", "tool_call"}:
            call_id = item.get("call_id") or item.get("id") or ""
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": item.get("name", ""),
                                "arguments": item.get("arguments", ""),
                            },
                        }
                    ],
                }
            )
            continue
        if item_type in {"function_call_output", "tool_call_output"}:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.get("call_id") or item.get("id") or "",
                    "content": deepcopy(item.get("output", "")),
                }
            )
            continue
        if "content" not in item:
            continue

        content = deepcopy(item["content"])
        if isinstance(content, list):
            normalized_content: list[Any] = []
            for part in content:
                if not isinstance(part, dict):
                    normalized_content.append(part)
                    continue
                part_type = part.get("type")
                if part_type in {"input_text", "output_text"}:
                    normalized_content.append({**part, "type": "text"})
                    continue
                if part_type == "input_image":
                    image_url = part.get("image_url")
                    if isinstance(image_url, str) and image_url:
                        image: dict[str, Any] = {"url": image_url}
                        if isinstance(part.get("detail"), str):
                            image["detail"] = part["detail"]
                        normalized_content.append({"type": "image_url", "image_url": image})
                    continue
                normalized_content.append(part)
            content = normalized_content
        message: dict[str, Any] = {
            "role": item.get("role", "user"),
            "content": content,
        }
        if isinstance(item.get("name"), str):
            message["name"] = item["name"]
        if isinstance(item.get("tool_call_id"), str):
            message["tool_call_id"] = item["tool_call_id"]
        messages.append(message)
    return messages


def _mask_slots(
    slots: list[_TextSlot],
    records: list[ExtractionRecord],
) -> MaskingContract:
    records_by_span: dict[str, ExtractionRecord] = {}
    for record in records:
        previous = records_by_span.get(record.span)
        if previous is not None and previous.category != record.category:
            raise ValueError("One sensitive span was assigned conflicting categories.")
        records_by_span.setdefault(record.span, record)

    segment_records: list[list[dict[str, Any]]] = [[] for _ in slots]
    for record in records_by_span.values():
        locations = _all_record_locations(record.span, slots)
        if not locations:
            raise ValueError(f"Extracted sensitive span is not present in request context: {record.category}")
        for slot_index, local_start in locations:
            local_record = _record_dict(record)
            local_record["start"] = local_start
            local_record["end"] = local_start + len(record.span)
            segment_records[slot_index].append(local_record)

    placeholder_map: dict[str, str] = {}
    placeholder_registry: dict[str, str] = {}
    masker = Masker()
    for slot, local_records in zip(slots, segment_records, strict=True):
        _reject_overlapping_records(local_records)
        result = masker.mask(
            slot.text,
            local_records,
            placeholder_registry=placeholder_registry,
        )
        slot.container[slot.key] = result.masked_text
        for placeholder, original in result.contract.placeholder_map.items():
            previous = placeholder_map.get(placeholder)
            if previous is not None and previous != original:
                raise ValueError("Masking placeholder collision detected.")
            placeholder_map[placeholder] = original

    return MaskingContract(
        placeholder_map=placeholder_map,
        count=len(placeholder_map),
    )


_PROTOCOL_FIELD_KEYS = frozenset({"id", "call_id", "tool_call_id", "name"})


def _protocol_field_slots(value: object, label: str) -> list[_TextSlot]:
    """Collect correlation identifiers and callable names without masking them."""
    slots: list[_TextSlot] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            slots.extend(_protocol_field_slots(item, f"{label}[{index}]"))
        return slots
    if not isinstance(value, dict):
        return slots
    for key, item in value.items():
        child_label = f"{label}.{key}"
        if key in _PROTOCOL_FIELD_KEYS and isinstance(item, str):
            slots.append(_TextSlot(value, key, item, child_label))
        if isinstance(item, (dict, list)):
            slots.extend(_protocol_field_slots(item, child_label))
    return slots


def _tool_protocol_field_slots(
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] | None,
    choice_holder: dict[str, Any] | None = None,
) -> list[_TextSlot]:
    slots: list[_TextSlot] = []
    if tools:
        slots.extend(_protocol_field_slots(tools, "tools"))
    if choice_holder is None:
        choice_holder = {"tool_choice": tool_choice}
    if isinstance(tool_choice, str) and tool_choice not in {"auto", "none", "required"}:
        slots.append(_TextSlot(choice_holder, "tool_choice", tool_choice, "tool_choice"))
    elif isinstance(tool_choice, dict):
        slots.extend(_protocol_field_slots(choice_holder, "tool_choice"))
    return slots


def _reject_sensitive_protocol_fields(
    records: list[ExtractionRecord],
    slots: list[_TextSlot],
) -> None:
    """Fail closed when sensitive data occupies an unmaskable protocol field."""
    for slot in slots:
        if any(record.span and record.span in slot.text for record in records):
            raise ValueError("Sensitive protocol fields cannot be masked safely.")


def _chat_context_slots(
    messages: list[dict[str, Any]],
    *,
    include_protocol_fields: bool = False,
) -> list[_TextSlot]:
    slots: list[_TextSlot] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        role_label = role if isinstance(role, str) else "unknown"
        base = f"message[{message_index}].{role_label}"
        slots.extend(_value_slots(message, "content", f"{base}.content"))
        slots.extend(_value_slots(message, "refusal", f"{base}.refusal"))
        if include_protocol_fields:
            slots.extend(_protocol_field_slots(message, base))

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_index, tool_call in enumerate(tool_calls):
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if isinstance(function, dict):
                    slots.extend(
                        _value_slots(
                            function,
                            "arguments",
                            f"{base}.tool_calls[{tool_index}].function.arguments",
                        )
                    )

        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            slots.extend(
                _value_slots(
                    function_call,
                    "arguments",
                    f"{base}.function_call.arguments",
                )
            )
    return slots


def _responses_context_slots(
    input_data: list[Any],
    *,
    include_protocol_fields: bool = False,
) -> list[_TextSlot]:
    slots: list[_TextSlot] = []
    for index, item in enumerate(input_data):
        if isinstance(item, str):
            slots.append(_TextSlot(input_data, index, item, f"input[{index}].user.content"))
            continue
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")
        role = item.get("role")
        if isinstance(role, str):
            base = f"input[{index}].{role}"
        elif isinstance(item_type, str):
            base = f"input[{index}].{item_type}"
        else:
            base = f"input[{index}].user"
        if include_protocol_fields:
            slots.extend(_protocol_field_slots(item, base))
        slots.extend(_value_slots(item, "content", f"{base}.content"))
        slots.extend(_value_slots(item, "arguments", f"{base}.arguments"))
        slots.extend(_value_slots(item, "output", f"{base}.output"))
        slots.extend(_value_slots(item, "refusal", f"{base}.refusal"))
    return slots


def _tool_context_slots(
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] | None,
    choice_holder: dict[str, Any] | None = None,
    *,
    include_protocol_fields: bool = False,
) -> list[_TextSlot]:
    """Collect maskable tool metadata plus inspect-only protocol fields."""
    slots: list[_TextSlot] = []
    if tools:
        tools_holder = {"tools": tools}
        slots.extend(_value_slots(tools_holder, "tools", "tools"))
    if choice_holder is None:
        choice_holder = {"tool_choice": tool_choice}
    if isinstance(tool_choice, dict):
        slots.extend(_value_slots(choice_holder, "tool_choice", "tool_choice"))
    if include_protocol_fields:
        slots.extend(_tool_protocol_field_slots(tools, tool_choice, choice_holder))
    return slots


_UNINSPECTED_MEDIA_PART_TYPES = frozenset({"image_url", "input_audio", "input_file", "input_image", "input_video"})
_MEDIA_PAYLOAD_KEYS_BY_TYPE = {
    "image_url": frozenset({"image_url"}),
    "input_audio": frozenset({"input_audio", "data", "audio_url"}),
    "input_file": frozenset({"file_data", "file_id", "file_url"}),
    "input_image": frozenset({"image_url"}),
    "input_video": frozenset({"data", "video_url"}),
}
_MEDIA_FALLBACK_NOTICE = (
    "A media attachment was withheld because the configured on-device "
    "model could not inspect it. Explain that the attachment could not "
    "be analyzed, and do not infer its contents."
)


def _media_payload_keys(value: dict[str, Any]) -> frozenset[str]:
    part_type = value.get("type")
    if isinstance(part_type, str):
        return _MEDIA_PAYLOAD_KEYS_BY_TYPE.get(part_type, frozenset())
    return frozenset()


def _is_uninspected_media_part(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    part_type = value.get("type")
    if part_type in _UNINSPECTED_MEDIA_PART_TYPES:
        return True
    return "image_url" in value or "input_audio" in value


def contains_uninspected_media(messages: list[dict[str, Any]]) -> bool:
    """Return whether a direct message content part contains opaque media."""
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            if any(_is_uninspected_media_part(part) for part in content):
                return True
        elif _is_uninspected_media_part(content):
            return True
    return False


def without_uninspected_media(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace direct opaque media parts with a text-only fallback notice."""
    sanitized = deepcopy(messages)
    for message in sanitized:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            safe_content = [part for part in content if not _is_uninspected_media_part(part)]
            if len(safe_content) != len(content):
                safe_content.append({"type": "text", "text": _MEDIA_FALLBACK_NOTICE})
                message["content"] = safe_content
        elif _is_uninspected_media_part(content):
            message["content"] = _MEDIA_FALLBACK_NOTICE
    return sanitized


_STRUCTURAL_CONTEXT_KEYS = {
    "type",
    "role",
    "id",
    "call_id",
    "tool_call_id",
    "name",
    "status",
    "detail",
}


def _value_slots(
    container: dict[str, Any] | list[Any],
    key: str | int,
    label: str,
) -> list[_TextSlot]:
    value = container[key] if isinstance(container, list) else container.get(key)
    if isinstance(value, str):
        return [_TextSlot(container, key, value, label)]
    if isinstance(value, list):
        slots: list[_TextSlot] = []
        for index in range(len(value)):
            slots.extend(_value_slots(value, index, f"{label}[{index}]"))
        return slots
    if isinstance(value, dict):
        slots = []
        media_payload_keys = _media_payload_keys(value)
        for child_key in value:
            if child_key in _STRUCTURAL_CONTEXT_KEYS or child_key in media_payload_keys:
                continue
            slots.extend(_value_slots(value, child_key, f"{label}.{child_key}"))
        return slots
    return []


def session_cache_key(authenticated_key_id: str, client_chat_id: str | None) -> str | None:
    """Return a tenant-scoped opaque key for persisted conversation context."""
    if client_chat_id is None:
        return None
    if not client_chat_id or len(client_chat_id.encode("utf-8")) > 512:
        raise ValueError("x-chat-id must contain between 1 and 512 UTF-8 bytes")
    material = f"api-chat\0{authenticated_key_id}\0{client_chat_id}"
    return f"context-{cache_fingerprint(material)}"


def merge_context_segments(
    previous: list[ContextSegment | dict[str, str]],
    current: list[ContextSegment | dict[str, str]],
) -> list[ContextSegment]:
    """Merge a session snapshot or delta without duplicating known fields.

    Current fields replace matching prior fields and move into current request
    order. Prior-only fields remain available as historical privacy context.
    Numeric collection indexes are ignored when identifying the same semantic
    field because clients may resend a longer conversation snapshot.
    """
    merged: dict[tuple[str, str], ContextSegment] = {}
    for segment in [*previous, *current]:
        normalized = _coerce_context_segment(segment)
        signature = (_normalize_context_label(normalized.label), normalized.text)
        merged.pop(signature, None)
        merged[signature] = normalized
    return list(merged.values())


def render_context_segments(
    segments: list[ContextSegment | dict[str, str]],
) -> str:
    """Render persistent context segments for the privacy pipeline."""
    normalized = [_coerce_context_segment(segment) for segment in segments]
    return "\n\n".join(f"[{segment.label}]\n{segment.text}" for segment in normalized)


def _context_segments(slots: list[_TextSlot]) -> list[ContextSegment]:
    return [ContextSegment(label=slot.label, text=slot.text) for slot in slots]


def _coerce_context_segment(
    segment: ContextSegment | dict[str, str],
) -> ContextSegment:
    if isinstance(segment, ContextSegment):
        return segment
    if isinstance(segment, dict) and isinstance(segment.get("label"), str) and isinstance(segment.get("text"), str):
        return ContextSegment(label=segment["label"], text=segment["text"])
    raise TypeError("Invalid persisted privacy context segment")


def _normalize_context_label(label: str) -> str:
    return re.sub(r"\[\d+\]", "[]", label)


def _all_record_locations(
    span: str,
    slots: list[_TextSlot],
) -> list[tuple[int, int]]:
    locations: list[tuple[int, int]] = []
    for index, slot in enumerate(slots):
        search_from = 0
        while True:
            local_start = slot.text.find(span, search_from)
            if local_start < 0:
                break
            locations.append((index, local_start))
            search_from = local_start + len(span)
    return locations


def _reject_overlapping_records(records: list[dict[str, Any]]) -> None:
    ordered = sorted(records, key=lambda record: (record["start"], record["end"]))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current["start"] < previous["end"]:
            raise ValueError("Overlapping sensitive spans cannot be masked safely.")


def _record_dict(record: ExtractionRecord) -> dict[str, Any]:
    return {
        "category": record.category,
        "span": record.span,
        "confidence": record.confidence,
        "start": record.start,
        "end": record.end,
        "is_essential": record.is_essential,
    }
