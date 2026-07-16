"""Streaming placeholder hydration and beta repair regression tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from agents import HydrationError, MaskingContract
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
    reject_sensitive_tool_call_protocol_fields,
    validate_stream_tool_call_index,
    validate_stream_tool_call_indices,
    validate_tool_call_arguments,
    validate_tool_call_identifier_groups,
    validate_tool_call_protocol,
)


@dataclass
class FakeRepairer:
    answer: str | None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def repair(
        self,
        *,
        observed: str,
        allowed: list[str],
        masked_messages: list[dict[str, object]],
        masked_output: str,
    ) -> str | None:
        self.calls.append(
            {
                "observed": observed,
                "allowed": allowed,
                "masked_messages": masked_messages,
                "masked_output": masked_output,
            }
        )
        return self.answer


def _contract() -> MaskingContract:
    return MaskingContract(
        placeholder_map={"PHONE#abc12345": "010-1234-5678"},
        count=1,
    )


class TestStreamingHydrator:
    def test_known_placeholder_split_across_chunks_is_never_emitted_raw(self):
        hydrator = StreamingHydrator(_contract())

        first = hydrator.feed("Call PHONE#ab")
        second = hydrator.feed("c12345 now")
        final = hydrator.flush()

        output = "".join(first + second + final)
        assert output == "Call 010-1234-5678 now"
        assert "PHONE#" not in output

    def test_unknown_placeholder_fails_closed_before_emission(self):
        hydrator = StreamingHydrator(_contract())

        with pytest.raises(HydrationError) as exc_info:
            hydrator.feed("Call PHONE#deadbeef now")

        assert exc_info.value.unresolved == ["PHONE#deadbeef"]

    def test_incomplete_placeholder_fails_closed_on_flush(self):
        hydrator = StreamingHydrator(_contract())

        assert hydrator.feed("Call PHONE#dead") == ["Call "]
        with pytest.raises(HydrationError) as exc_info:
            hydrator.flush()

        assert exc_info.value.unresolved == ["PHONE#dead"]

    def test_trailing_plaintext_prefix_flushes_without_false_positive(self):
        hydrator = StreamingHydrator(_contract())

        assert hydrator.feed("Ask P") == ["Ask "]
        assert hydrator.flush() == ["P"]


@pytest.mark.asyncio
async def test_beta_repair_uses_masked_context_then_resumes_stream():
    hydrator = StreamingHydrator(_contract())
    repairer = FakeRepairer("PHONE#abc12345")
    masked_messages = [{"role": "user", "content": "Call PHONE#abc12345"}]

    output = await hydrate_stream_chunk(
        hydrator,
        "Draft for PHONE#deadbeef is ready",
        repairer=repairer,
        masked_messages=masked_messages,
        masked_output="Draft for PHONE#deadbeef is ready",
    )

    assert "".join(output) == "Draft for 010-1234-5678 is ready"
    assert repairer.calls == [
        {
            "observed": "PHONE#deadbeef",
            "allowed": ["PHONE#abc12345"],
            "masked_messages": masked_messages,
            "masked_output": "Draft for PHONE#deadbeef is ready",
        }
    ]


@pytest.mark.asyncio
async def test_tool_arguments_remain_masked_without_explicit_release():
    arguments = await hydrate_tool_call_arguments(
        '{"phone":"PHONE#abc12345"}',
        _contract(),
        allow_sensitive=False,
        repairer=None,
        masked_messages=[],
    )

    assert json.loads(arguments) == {"phone": "PHONE#abc12345"}


@pytest.mark.asyncio
async def test_tool_arguments_hydrate_nested_values_and_preserve_valid_json():
    contract = MaskingContract(
        placeholder_map={"SECRET#abc12345": 'say "hello"\nnow'},
        count=1,
    )

    arguments = await hydrate_tool_call_arguments(
        '{"payload":{"items":["SECRET#abc12345"]}}',
        contract,
        allow_sensitive=True,
        repairer=None,
        masked_messages=[],
    )

    assert json.loads(arguments) == {"payload": {"items": ['say "hello"\nnow']}}


@pytest.mark.asyncio
async def test_tool_arguments_reject_disallowed_unicode_after_hydration():
    contract = MaskingContract(
        placeholder_map={"SECRET#abc12345": "\x00secret"},
        count=1,
    )

    with pytest.raises(HydrationError):
        await hydrate_tool_call_arguments(
            '{"value":"SECRET#abc12345"}',
            contract,
            allow_sensitive=True,
            repairer=None,
            masked_messages=[],
        )


@pytest.mark.asyncio
async def test_tool_arguments_repair_unknown_placeholder_then_hydrate():
    repairer = FakeRepairer("PHONE#abc12345")

    arguments = await hydrate_tool_call_arguments(
        '{"phone":"PHONE#deadbeef"}',
        _contract(),
        allow_sensitive=True,
        repairer=repairer,
        masked_messages=[{"role": "user", "content": "Call PHONE#abc12345"}],
    )

    assert json.loads(arguments) == {"phone": "010-1234-5678"}
    assert repairer.calls[0]["observed"] == "PHONE#deadbeef"


@pytest.mark.asyncio
async def test_tool_arguments_unknown_placeholder_fails_closed():
    with pytest.raises(HydrationError):
        await hydrate_tool_call_arguments(
            '{"phone":"PHONE#deadbeef"}',
            _contract(),
            allow_sensitive=False,
            repairer=None,
            masked_messages=[],
        )


@pytest.mark.asyncio
async def test_tool_arguments_reject_unknown_placeholder_keys_when_releasing():
    with pytest.raises(HydrationError):
        await hydrate_tool_call_arguments(
            '{"PHONE#deadbeef":"value"}',
            _contract(),
            allow_sensitive=True,
            repairer=None,
            masked_messages=[],
        )


def test_tool_arguments_validation_accepts_registered_placeholder():
    arguments = '{"phone":"PHONE#abc12345"}'

    validate_tool_call_arguments(arguments, _contract())


def test_tool_arguments_reject_unknown_placeholder():
    with pytest.raises(HydrationError):
        validate_tool_call_arguments(
            '{"phone":"PHONE#deadbeef"}',
            _contract(),
        )


def test_tool_arguments_reject_invalid_json():
    with pytest.raises(HydrationError):
        validate_tool_call_arguments(
            '{"phone":"PHONE#abc12345"',
            _contract(),
        )


@pytest.mark.asyncio
async def test_tool_arguments_canonicalize_registered_escaped_placeholder():
    arguments = await hydrate_tool_call_arguments(
        '{"phone":"PHONE\\u0023abc12345"}',
        _contract(),
        allow_sensitive=False,
        repairer=None,
        masked_messages=[],
    )

    assert json.loads(arguments) == {"phone": "PHONE#abc12345"}
    assert "\\u0023" not in arguments


@pytest.mark.asyncio
async def test_tool_arguments_reject_escaped_unknown_placeholder():
    escaped = '{"phone":"PHONE\\u0023deadbeef"}'

    with pytest.raises(HydrationError):
        validate_tool_call_arguments(escaped, _contract())

    with pytest.raises(HydrationError):
        await hydrate_tool_call_arguments(
            escaped,
            _contract(),
            allow_sensitive=False,
            repairer=None,
            masked_messages=[],
        )


def _declared_tools() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_tool_call_inspection_includes_all_protocol_fields_and_decoded_arguments():
    inspection = build_tool_call_inspection(
        '{"value":"MODEL_OUTPUT_SECRET"}',
        identifiers={"id": "item_1", "call_id": "call_1"},
        name="send_value",
    )

    assert 'PROTOCOL_FIELD path="/id"' in inspection.text
    assert 'PROTOCOL_FIELD path="/call_id"' in inspection.text
    assert 'PROTOCOL_FIELD path="/name"' in inspection.text
    assert 'STRING path="/value"' in inspection.text
    assert "call_1" in inspection.text
    assert "send_value" in inspection.text
    assert "item_1" in inspection.text
    assert "MODEL_OUTPUT_SECRET" in inspection.text


@pytest.mark.parametrize(
    ("identifiers", "name", "call_type"),
    [
        ([], "send_value", "function"),
        ([""], "send_value", "function"),
        (["call_1"], "undeclared", "function"),
        (["call_1"], "send_value", "function_call"),
        (["call_1"], "send_value", []),
    ],
)
def test_tool_call_protocol_rejects_incomplete_or_undeclared_calls(
    identifiers,
    name,
    call_type,
):
    with pytest.raises(HydrationError, match="INVALID_TOOL_CALL_PROTOCOL"):
        validate_tool_call_protocol(
            identifiers=identifiers,
            name=name,
            call_type=call_type,
            tools=_declared_tools(),
        )


def test_tool_call_protocol_accepts_complete_declared_call():
    validate_tool_call_protocol(
        identifiers=["item_1", "call_1"],
        name="send_value",
        call_type="function_call",
        tools=_declared_tools(),
        allowed_call_types=frozenset({"function_call"}),
    )


def test_tool_call_protocol_accepts_flat_responses_declaration():
    validate_tool_call_protocol(
        identifiers=["item_1", "call_1"],
        name="send_value",
        call_type="function_call",
        tools=[
            {
                "type": "function",
                "name": "send_value",
                "parameters": {"type": "object"},
            }
        ],
        allowed_call_types=frozenset({"function_call"}),
    )


@pytest.mark.parametrize(
    ("current", "fragment", "expected"),
    [
        ("", "function", "function"),
        ("", "fun", "fun"),
        ("fun", "ction", "function"),
        ("function", "function", "function"),
    ],
)
def test_stream_tool_call_type_assembles_valid_fragments(current, fragment, expected):
    assert merge_stream_tool_call_type(current, fragment) == expected


@pytest.mark.parametrize(
    ("current", "fragment"),
    [
        ("", ""),
        ("", "custom"),
        ("function", "custom"),
        ("fun", 1),
    ],
)
def test_stream_tool_call_type_rejects_invalid_or_conflicting_fragments(current, fragment):
    with pytest.raises(HydrationError, match="INVALID_TOOL_CALL_PROTOCOL"):
        merge_stream_tool_call_type(current, fragment)


def test_tool_call_identifier_groups_reject_cross_call_collisions_and_missing_ids():
    validate_tool_call_identifier_groups([["item_1", "call_1"], ["item_2", "call_2"]])

    with pytest.raises(HydrationError, match="INVALID_TOOL_CALL_PROTOCOL"):
        validate_tool_call_identifier_groups([["item_1", "call_1"], ["item_2", "call_1"]])
    with pytest.raises(HydrationError, match="INVALID_TOOL_CALL_PROTOCOL"):
        validate_tool_call_identifier_groups([[""]])


@pytest.mark.parametrize("index", [True, -1, 1.5, "MODEL_OUTPUT_INDEX"])
def test_stream_tool_call_index_rejects_malformed_values(index):
    with pytest.raises(HydrationError, match="INVALID_TOOL_CALL_PROTOCOL"):
        validate_stream_tool_call_index(index)


def test_stream_tool_call_indices_require_contiguous_positions():
    assert validate_stream_tool_call_indices([1, 0]) == [0, 1]
    with pytest.raises(HydrationError, match="INVALID_TOOL_CALL_PROTOCOL"):
        validate_stream_tool_call_indices([7])


@pytest.mark.parametrize(
    ("records", "is_sensitive", "reason"),
    [
        ([], True, "UNMAPPABLE_SENSITIVE_TOOL_CALL"),
        ([{}], True, "UNMAPPABLE_SENSITIVE_TOOL_CALL"),
        ([{"span": "call_1"}], True, "SENSITIVE_TOOL_CALL_PROTOCOL"),
        ([{"span": "send_value"}], True, "SENSITIVE_TOOL_CALL_PROTOCOL"),
    ],
)
def test_sensitive_tool_call_protocol_fields_are_fail_closed(
    records,
    is_sensitive,
    reason,
):
    with pytest.raises(HydrationError, match=reason):
        reject_sensitive_tool_call_protocol_fields(
            records,
            is_sensitive=is_sensitive,
            identifiers=["item_1", "call_1"],
            name="send_value",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
    ],
)
async def test_tool_argument_paths_reject_non_finite_json(arguments):
    with pytest.raises(HydrationError):
        validate_tool_call_arguments(arguments, _contract())

    with pytest.raises(HydrationError):
        mask_sensitive_tool_call_arguments(
            arguments,
            [],
            is_sensitive=False,
        )

    with pytest.raises(HydrationError):
        await hydrate_tool_call_arguments(
            arguments,
            _contract(),
            allow_sensitive=False,
            repairer=None,
            masked_messages=[],
        )


@pytest.mark.asyncio
async def test_tool_argument_paths_reject_duplicate_json_keys():
    arguments = '{"value":"UNKNOWN#badc0ffe","value":"safe"}'

    with pytest.raises(HydrationError):
        validate_tool_call_arguments(arguments, _contract())

    with pytest.raises(HydrationError):
        mask_sensitive_tool_call_arguments(
            arguments,
            [],
            is_sensitive=False,
        )

    with pytest.raises(HydrationError):
        await hydrate_tool_call_arguments(
            arguments,
            _contract(),
            allow_sensitive=False,
            repairer=None,
            masked_messages=[],
        )


@pytest.mark.parametrize(
    "arguments",
    [
        '{"\\u0000key":"safe"}',
        '{"value":"\\ud800"}',
    ],
)
def test_tool_argument_inspection_rejects_disallowed_decoded_unicode(arguments):
    with pytest.raises(HydrationError):
        build_tool_argument_inspection(arguments)


def test_tool_argument_inspection_rejects_excessive_nesting():
    arguments = "[" * 2000 + '"safe"' + "]" * 2000

    with pytest.raises(HydrationError):
        build_tool_argument_inspection(arguments)


def test_tool_argument_inspection_enforces_nesting_depth_boundary():
    allowed = "[" * 64 + '"safe"' + "]" * 64
    blocked = "[" * 65 + '"safe"' + "]" * 65

    assert "safe" in build_tool_argument_inspection(allowed).text
    with pytest.raises(HydrationError):
        build_tool_argument_inspection(blocked)


def test_tool_argument_inspection_allows_multilingual_formatting_characters():
    value = "family 👨‍👩‍👧; العربية \u2067text\u2069"
    inspection = build_tool_argument_inspection(json.dumps({"message": value}))

    assert value in inspection.text


def test_inspection_document_exposes_decoded_string_values_for_masking():
    raw_secret = 'pa"ss\nword'
    arguments = json.dumps({"password": raw_secret})
    inspection = build_tool_argument_inspection(arguments)
    start = inspection.text.index(raw_secret)

    protected = mask_sensitive_tool_call_arguments(
        arguments,
        [
            {
                "category": "CREDENTIAL",
                "span": raw_secret,
                "start": start,
                "end": start + len(raw_secret),
            }
        ],
        is_sensitive=True,
    )

    assert raw_secret not in protected
    assert json.loads(protected)["password"].startswith("SENSITIVE_DATA#")


def test_sensitive_tool_arguments_mask_nested_string_values():
    registry: dict[str, str] = {}
    arguments = mask_sensitive_tool_call_arguments(
        '{"payload":{"items":["010-1234-5678","010-1234-5678"]}}',
        [
            {
                "category": "PHONE_NUMBER",
                "span": "010-1234-5678",
                "start": 22,
                "end": 35,
            }
        ],
        is_sensitive=True,
        placeholder_registry=registry,
    )

    parsed = json.loads(arguments)
    first, second = parsed["payload"]["items"]
    assert first == second
    assert first.startswith("SENSITIVE_DATA#")
    assert registry == {"010-1234-5678": first}
    assert "010-1234-5678" not in arguments


def test_sensitive_tool_arguments_preserve_non_sensitive_json():
    arguments = '{ "value": "safe", "count": 3 }'

    protected = mask_sensitive_tool_call_arguments(
        arguments,
        [],
        is_sensitive=False,
    )

    assert protected == arguments


def test_sensitive_tool_arguments_treat_records_as_sensitive_when_flag_is_false():
    protected = mask_sensitive_tool_call_arguments(
        '{"value":"secret"}',
        [{"span": "secret", "category": "SECRET"}],
        is_sensitive=False,
    )

    assert "secret" not in protected
    assert json.loads(protected)["value"].startswith("SENSITIVE_DATA#")


@pytest.mark.parametrize(
    "arguments, record",
    [
        (
            '{"010-1234-5678":"value"}',
            {"span": "010-1234-5678", "category": "PHONE_NUMBER"},
        ),
        (
            '{"value":9012121234567}',
            {"span": "9012121234567", "category": "IDENTIFIER"},
        ),
    ],
)
def test_sensitive_tool_arguments_reject_unmaskable_json_positions(arguments, record):
    with pytest.raises(HydrationError):
        mask_sensitive_tool_call_arguments(
            arguments,
            [record],
            is_sensitive=True,
        )


def test_sensitive_tool_arguments_fail_closed_without_mappable_record():
    with pytest.raises(HydrationError):
        mask_sensitive_tool_call_arguments(
            '{"value":"safe"}',
            [{"span": "unmapped-secret", "category": "SECRET"}],
            is_sensitive=True,
        )


def test_sensitive_tool_arguments_fail_closed_without_records():
    with pytest.raises(HydrationError):
        mask_sensitive_tool_call_arguments(
            '{"value":"secret"}',
            [],
            is_sensitive=True,
        )


@pytest.mark.parametrize(
    "records",
    [
        [
            {"span": "123", "category": "SHORT"},
            {"span": "12345", "category": "LONG"},
        ],
        [
            {"span": "12345", "category": "FIRST"},
            {"span": "12345", "category": "SECOND"},
        ],
    ],
)
def test_sensitive_tool_arguments_reject_overlapping_or_conflicting_records(records):
    with pytest.raises(HydrationError):
        mask_sensitive_tool_call_arguments(
            '{"value":"12345"}',
            records,
            is_sensitive=True,
        )


@pytest.mark.asyncio
async def test_beta_repair_hydrates_non_stream_response():
    repairer = FakeRepairer("PHONE#abc12345")

    output = await hydrate_masked_response(
        "Draft for PHONE#deadbeef is ready",
        _contract(),
        repairer=repairer,
        masked_messages=[{"role": "user", "content": "Call PHONE#abc12345"}],
    )

    assert output == "Draft for 010-1234-5678 is ready"


@pytest.mark.asyncio
async def test_beta_repair_failure_remains_fail_closed():
    hydrator = StreamingHydrator(_contract())
    repairer = FakeRepairer(None)

    with pytest.raises(HydrationError):
        await hydrate_stream_chunk(
            hydrator,
            "PHONE#deadbeef done",
            repairer=repairer,
            masked_messages=[],
            masked_output="PHONE#deadbeef done",
        )


@pytest.mark.asyncio
async def test_beta_repair_can_resolve_trailing_token_at_flush():
    hydrator = StreamingHydrator(_contract())
    repairer = FakeRepairer("PHONE#abc12345")

    assert hydrator.feed("Call PHONE#deadbeef") == ["Call "]
    output = await flush_stream_hydrator(
        hydrator,
        repairer=repairer,
        masked_messages=[],
        masked_output="Call PHONE#deadbeef",
    )

    assert output == ["010-1234-5678"]
