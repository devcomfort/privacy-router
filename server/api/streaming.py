"""Fail-closed hydration for placeholders split across streamed chunks.

The hydrator emits ordinary text immediately, buffers only a possible
placeholder suffix, and validates every complete placeholder against the
request's immutable masking contract before it can reach the client.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from agents import HydrationError, Masker, MaskingContract

_PARTIAL_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<token>\[?[A-Za-z][A-Za-z0-9_]{1,63}#[A-Za-z0-9_-]*)$"
)
_MAX_REPAIRS_PER_CHUNK = 16


class PlaceholderRepairProtocol(Protocol):
    """Masked-context repair interface used by the beta recovery path."""

    async def repair(
        self,
        *,
        observed: str,
        allowed: list[str],
        masked_messages: list[dict[str, object]],
        masked_output: str,
    ) -> str | None: ...


class StreamingHydrator:
    """Incrementally validate and hydrate one request's model output."""

    def __init__(self, contract: MaskingContract | None) -> None:
        self._contract = contract
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        """Add ``chunk`` and return text that is safe to emit now."""
        if self._contract is None:
            return [chunk] if chunk else []
        self._buffer += chunk
        return self._drain(final=False)

    def flush(self) -> list[str]:
        """Validate and hydrate all remaining text, or fail closed."""
        if self._contract is None:
            return []
        return self._drain(final=True)

    def apply_repair(self, observed: str, replacement: str) -> bool:
        """Replace one buffered malformed token with a registered token."""
        if self._contract is None:
            return False
        if replacement not in self._contract.registered_placeholders:
            return False
        if observed not in self._buffer:
            return False
        self._buffer = self._buffer.replace(observed, replacement, 1)
        return True

    def _drain(self, *, final: bool) -> list[str]:
        assert self._contract is not None
        pending_start = self._pending_start(self._buffer)

        if final:
            safe = self._buffer
            if pending_start is not None:
                pending = self._buffer[pending_start:]
                canonical = pending.strip("[]")
                if "#" in pending and canonical not in self._contract.canonical_placeholder_map:
                    raise HydrationError([pending])
        elif pending_start is None:
            safe = self._buffer
        else:
            safe = self._buffer[:pending_start]

        unresolved = self._contract.validate_response(safe)
        if unresolved:
            raise HydrationError(unresolved)

        hydrated, _ = self._contract.replace_registered(safe)
        self._buffer = "" if final else self._buffer[len(safe) :]
        return [hydrated] if hydrated else []

    def _pending_start(self, text: str) -> int | None:
        """Return the start of a trailing token that needs another chunk."""
        if not text or self._contract is None:
            return None

        match = _PARTIAL_TOKEN_RE.search(text)
        if match:
            token = match.group("token")
            category = token.lstrip("[").partition("#")[0]
            categories = {key.partition("#")[0].upper() for key in self._contract.registered_placeholders}
            if category == category.upper() or category.upper() in categories:
                return match.start("token")

        candidates: list[str] = []
        for key in self._contract.registered_placeholders:
            candidates.extend((key, f"[{key}]"))

        earliest: int | None = None
        for candidate in candidates:
            max_prefix = min(len(text), len(candidate) - 1)
            for length in range(max_prefix, 0, -1):
                prefix = candidate[:length]
                if not text.endswith(prefix):
                    continue
                start = len(text) - length
                if start and (text[start - 1].isalnum() or text[start - 1] == "_"):
                    continue
                earliest = start if earliest is None else min(earliest, start)
                break
        return earliest


def sensitive_tool_arguments_allowed(body: dict[str, object]) -> bool:
    """Return true only for an explicit boolean sensitive-argument release."""
    options = body.get("privacy_router")
    if not isinstance(options, dict):
        return False
    return options.get("allow_sensitive_tool_arguments") is True


@dataclass(frozen=True)
class ToolArgumentInspection:
    """Decoded, length-prefixed view used only by the local inspector."""

    text: str


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_non_finite_json_constant(_: str) -> object:
    raise ValueError("Non-finite numbers are not valid JSON.")


_MAX_TOOL_ARGUMENT_DEPTH = 64


def _validate_tool_argument_unicode(value: object) -> None:
    """Reject unsafe decoded text and excessive nesting."""

    def validate_text(text: str) -> None:
        for character in text:
            codepoint = ord(character)
            if codepoint == 0 or 0xD800 <= codepoint <= 0xDFFF:
                raise HydrationError(["INVALID_TOOL_ARGUMENTS"])

    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_TOOL_ARGUMENT_DEPTH:
            raise HydrationError(["INVALID_TOOL_ARGUMENTS"])
        if isinstance(current, dict):
            for key, item in current.items():
                validate_text(key)
                pending.append((item, depth + 1))
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            validate_text(current)


def _load_tool_arguments(arguments: str) -> object:
    """Parse strict JSON or raise the shared fail-closed hydration error."""
    try:
        value = json.loads(
            arguments,
            parse_constant=_reject_non_finite_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
        _validate_tool_argument_unicode(value)
        return value
    except (TypeError, ValueError, RecursionError) as error:
        raise HydrationError(["INVALID_TOOL_ARGUMENTS"]) from error


def _dump_tool_arguments(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise HydrationError(["INVALID_TOOL_ARGUMENTS"]) from error


def normalize_tool_call_arguments(arguments: str) -> str:
    """Decode JSON escapes and return strict canonical tool arguments."""
    return _dump_tool_arguments(_load_tool_arguments(arguments))


def build_tool_argument_inspection(arguments: str) -> ToolArgumentInspection:
    """Expose decoded scalar values with their JSON Pointer paths."""
    parsed = _load_tool_arguments(arguments)
    parts = ["Fully assembled tool/function-call arguments (decoded values).\n"]

    def append_entry(kind: str, path: str, value: str) -> None:
        parts.append(f"{kind} path={_dump_tool_arguments(path)} length={len(value)}\n")
        parts.append(value)
        parts.append("\n")

    def child_path(path: str, key: str) -> str:
        token = key.replace("~", "~0").replace("/", "~1")
        return f"{path}/{token}" if path else f"/{token}"

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            parts.append(f"OBJECT path={_dump_tool_arguments(path)} entries={len(value)}\n")
            for key, item in value.items():
                item_path = child_path(path, key)
                append_entry("KEY", item_path, key)
                visit(item, item_path)
            return
        if isinstance(value, list):
            parts.append(f"ARRAY path={_dump_tool_arguments(path)} items={len(value)}\n")
            for index, item in enumerate(value):
                visit(item, child_path(path, str(index)))
            return
        if isinstance(value, str):
            append_entry("STRING", path, value)
            return
        append_entry("SCALAR", path, _dump_tool_arguments(value))

    visit(parsed, "")
    return ToolArgumentInspection(text="".join(parts))


def build_tool_call_inspection(
    arguments: str,
    *,
    identifiers: dict[str, str],
    name: str,
) -> ToolArgumentInspection:
    """Expose generated protocol fields and decoded arguments for inspection."""
    argument_inspection = build_tool_argument_inspection(arguments)
    protocol_fields = {**identifiers, "name": name}
    parts = ["Fully assembled model-generated tool call.\n"]
    for field, value in protocol_fields.items():
        parts.append(f'PROTOCOL_FIELD path="/{field}" length={len(value)}\n')
        parts.append(value)
        parts.append("\n")
    parts.append(argument_inspection.text)
    return ToolArgumentInspection(text="".join(parts))


def merge_stream_tool_call_type(
    current: object,
    fragment: object,
    *,
    allowed_types: frozenset[str] = frozenset({"function"}),
) -> str:
    """Assemble a streamed call type while rejecting conflicting metadata."""
    if not isinstance(current, str) or not isinstance(fragment, str) or not fragment:
        raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])
    if current == fragment and current in allowed_types:
        return current
    candidate = f"{current}{fragment}"
    if not any(allowed.startswith(candidate) for allowed in allowed_types):
        raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])
    return candidate


def validate_tool_call_identifier_groups(
    identifier_groups: Iterable[Iterable[object]],
) -> None:
    """Reject incomplete or ambiguous identifiers across parallel calls."""
    seen: set[str] = set()
    for group in identifier_groups:
        current: set[str] = set()
        for identifier in group:
            if not isinstance(identifier, str) or not identifier:
                raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])
            current.add(identifier)
        if not current or seen.intersection(current):
            raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])
        seen.update(current)


def validate_stream_tool_call_index(index: object) -> int:
    """Return a safe streamed tool-call index or reject malformed metadata."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])
    return index


def validate_stream_tool_call_indices(indices: Iterable[object]) -> list[int]:
    """Return contiguous streamed tool-call positions or reject metadata."""
    ordered = sorted(validate_stream_tool_call_index(index) for index in indices)
    if ordered != list(range(len(ordered))):
        raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])
    return ordered


def validate_tool_call_protocol(
    *,
    identifiers: list[object],
    name: object,
    call_type: object,
    tools: list[dict[str, object]] | None,
    allowed_call_types: frozenset[str] = frozenset({"function"}),
) -> None:
    """Accept only declared functions with complete generated identifiers."""
    allowed_names: set[str] = set()
    for tool in tools or []:
        if tool.get("type") != "function":
            continue
        function = tool.get("function")
        declared_name = function.get("name") if isinstance(function, dict) else tool.get("name")
        if isinstance(declared_name, str) and declared_name:
            allowed_names.add(declared_name)

    if (
        not isinstance(call_type, str)
        or call_type not in allowed_call_types
        or not identifiers
        or any(not isinstance(identifier, str) or not identifier for identifier in identifiers)
        or not isinstance(name, str)
        or name not in allowed_names
    ):
        raise HydrationError(["INVALID_TOOL_CALL_PROTOCOL"])


def reject_sensitive_tool_call_protocol_fields(
    records: list[object],
    is_sensitive: bool,
    *,
    identifiers: list[str],
    name: str,
) -> None:
    """Reject sensitive generated IDs or names because they are not maskable."""
    spans = [
        span
        for record in records
        if isinstance(
            span := record.get("span") if isinstance(record, dict) else getattr(record, "span", None),
            str,
        )
        and span
    ]
    if is_sensitive and not spans:
        raise HydrationError(["UNMAPPABLE_SENSITIVE_TOOL_CALL"])
    protocol_values = [*identifiers, name]
    if any(span in value for span in spans for value in protocol_values):
        raise HydrationError(["SENSITIVE_TOOL_CALL_PROTOCOL"])


def validate_tool_call_arguments(
    arguments: str,
    contract: MaskingContract | None,
) -> None:
    """Validate tool arguments without hydrating sensitive values."""
    normalized = normalize_tool_call_arguments(arguments)

    if contract is None:
        return
    unresolved = contract.validate_response(normalized)
    if unresolved:
        raise HydrationError(unresolved)


async def hydrate_tool_call_arguments(
    arguments: str,
    contract: MaskingContract | None,
    *,
    allow_sensitive: bool,
    repairer: PlaceholderRepairProtocol | None,
    masked_messages: list[dict[str, object]],
) -> str:
    """Validate tool JSON and release sensitive values only with explicit consent.

    Tool arguments are executable side effects, so the default preserves
    registered placeholders. Opted-in calls hydrate only JSON string values;
    parsing first keeps quotes and control characters inside the JSON envelope.
    """
    parsed = _load_tool_arguments(arguments)
    normalized = _dump_tool_arguments(parsed)

    if contract is None:
        return arguments

    if not allow_sensitive:
        unresolved = contract.validate_response(normalized)
        if unresolved:
            raise HydrationError(unresolved)

        return normalized

    async def hydrate_value(value: object) -> object:
        if isinstance(value, str):
            return await hydrate_masked_response(
                value,
                contract,
                repairer=repairer,
                masked_messages=masked_messages,
            )
        if isinstance(value, list):
            return [await hydrate_value(item) for item in value]
        if isinstance(value, dict):
            hydrated_items = {}
            for key, item in value.items():
                unresolved = contract.validate_response(key)
                if unresolved:
                    raise HydrationError(unresolved)
                hydrated_items[key] = await hydrate_value(item)
            return hydrated_items
        return value

    hydrated = await hydrate_value(parsed)
    _validate_tool_argument_unicode(hydrated)
    return _dump_tool_arguments(hydrated)


def mask_sensitive_tool_call_arguments(
    arguments: str,
    records: list[object],
    *,
    is_sensitive: bool,
    placeholder_registry: dict[str, str] | None = None,
) -> str:
    """Mask inspected plaintext values without changing the JSON structure.

    String values are maskable. Sensitive object keys and numeric values are
    rejected because replacing them would change the downstream tool contract.
    """
    parsed = _load_tool_arguments(arguments)

    if not is_sensitive and not records:
        return arguments

    categories_by_span: dict[str, str] = {}
    for record in records:
        if isinstance(record, dict):
            span = record.get("span")
            category = record.get("category")
        else:
            span = getattr(record, "span", None)
            category = getattr(record, "category", None)
        if not isinstance(span, str) or not span:
            continue
        normalized_category = category if isinstance(category, str) else "SENSITIVE_DATA"
        existing_category = categories_by_span.get(span)
        if existing_category is not None and existing_category != normalized_category:
            raise HydrationError(["CONFLICTING_SENSITIVE_TOOL_ARGUMENTS"])
        categories_by_span[span] = normalized_category

    if not categories_by_span:
        raise HydrationError(["UNMAPPABLE_SENSITIVE_TOOL_ARGUMENTS"])

    normalized_records = list(categories_by_span.items())
    spans = set(categories_by_span)

    def reject_unmaskable_positions(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if any(span in key for span in spans):
                    raise HydrationError(["UNMAPPABLE_SENSITIVE_TOOL_ARGUMENTS"])
                reject_unmaskable_positions(item)
            return
        if isinstance(value, list):
            for item in value:
                reject_unmaskable_positions(item)
            return
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                encoded = json.dumps(value, allow_nan=False)
            except ValueError as error:
                raise HydrationError(["INVALID_TOOL_ARGUMENTS"]) from error
            if any(span in encoded for span in spans):
                raise HydrationError(["UNMAPPABLE_SENSITIVE_TOOL_ARGUMENTS"])

    reject_unmaskable_positions(parsed)

    masker = Masker()
    registry = placeholder_registry if placeholder_registry is not None else {}
    matched_spans: set[str] = set()

    def mask_value(value: object) -> object:
        if isinstance(value, str):
            value_records: list[dict[str, object]] = []
            for span, category in normalized_records:
                start = 0
                while True:
                    index = value.find(span, start)
                    if index < 0:
                        break
                    value_records.append(
                        {
                            "category": category,
                            "span": span,
                            "start": index,
                            "end": index + len(span),
                        }
                    )
                    matched_spans.add(span)
                    start = index + len(span)
            value_records.sort(key=lambda record: (int(record["start"]), int(record["end"])))
            previous_end = -1
            for value_record in value_records:
                record_start = int(value_record["start"])
                if record_start < previous_end:
                    raise HydrationError(["OVERLAPPING_SENSITIVE_TOOL_ARGUMENTS"])
                previous_end = int(value_record["end"])
            if value_records:
                return masker.mask(
                    value,
                    value_records,
                    placeholder_registry=registry,
                ).masked_text
            return value
        if isinstance(value, list):
            return [mask_value(item) for item in value]
        if isinstance(value, dict):
            return {key: mask_value(item) for key, item in value.items()}
        return value

    protected = mask_value(parsed)
    if matched_spans != spans:
        raise HydrationError(["UNMAPPABLE_SENSITIVE_TOOL_ARGUMENTS"])

    return json.dumps(
        protected,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


async def hydrate_masked_response(
    text: str,
    contract: MaskingContract,
    *,
    repairer: PlaceholderRepairProtocol | None,
    masked_messages: list[dict[str, object]],
) -> str:
    """Hydrate a complete response, repairing only malformed tokens."""
    candidate = text
    for _ in range(_MAX_REPAIRS_PER_CHUNK):
        try:
            return Masker().hydrate(candidate, contract).hydrated_text
        except HydrationError as error:
            if repairer is None or not error.unresolved:
                raise
            observed = error.unresolved[0]
            replacement = await repairer.repair(
                observed=observed,
                allowed=contract.registered_placeholders,
                masked_messages=masked_messages,
                masked_output=text,
            )
            if replacement not in contract.registered_placeholders:
                raise error
            candidate = candidate.replace(observed, replacement, 1)

    raise HydrationError(contract.validate_response(candidate))


async def hydrate_stream_chunk(
    hydrator: StreamingHydrator,
    chunk: str,
    *,
    repairer: PlaceholderRepairProtocol | None,
    masked_messages: list[dict[str, object]],
    masked_output: str,
) -> list[str]:
    """Hydrate one chunk, optionally repairing only an invalid token."""
    try:
        return hydrator.feed(chunk)
    except HydrationError as error:
        return await _repair_then_drain(
            hydrator,
            error,
            final=False,
            repairer=repairer,
            masked_messages=masked_messages,
            masked_output=masked_output,
        )


async def flush_stream_hydrator(
    hydrator: StreamingHydrator,
    *,
    repairer: PlaceholderRepairProtocol | None,
    masked_messages: list[dict[str, object]],
    masked_output: str,
) -> list[str]:
    """Flush buffered output, optionally repairing only an invalid token."""
    try:
        return hydrator.flush()
    except HydrationError as error:
        return await _repair_then_drain(
            hydrator,
            error,
            final=True,
            repairer=repairer,
            masked_messages=masked_messages,
            masked_output=masked_output,
        )


async def _repair_then_drain(
    hydrator: StreamingHydrator,
    error: HydrationError,
    *,
    final: bool,
    repairer: PlaceholderRepairProtocol | None,
    masked_messages: list[dict[str, object]],
    masked_output: str,
) -> list[str]:
    if repairer is None:
        raise error

    current = error
    for _ in range(_MAX_REPAIRS_PER_CHUNK):
        if not current.unresolved:
            raise current
        observed = current.unresolved[0]
        replacement = await repairer.repair(
            observed=observed,
            allowed=(hydrator._contract.registered_placeholders if hydrator._contract is not None else []),
            masked_messages=masked_messages,
            masked_output=masked_output,
        )
        if replacement is None or not hydrator.apply_repair(observed, replacement):
            raise current
        try:
            return hydrator.flush() if final else hydrator.feed("")
        except HydrationError as next_error:
            current = next_error

    raise current
