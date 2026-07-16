"""Regression tests for message-local request masking."""

from __future__ import annotations

import pytest

from agents import ExtractionRecord
from server.api.masking import (
    chat_context_segments,
    chat_context_text,
    mask_chat_messages,
    mask_responses_input,
    merge_context_segments,
    render_context_segments,
    responses_context_text,
    responses_input_to_messages,
)


def _record(category: str, span: str, start: int, end: int) -> ExtractionRecord:
    return ExtractionRecord(
        category=category,
        span=span,
        confidence=0.99,
        start=start,
        end=end,
        is_essential=False,
    )


def test_chat_messages_preserve_boundaries_roles_and_content():
    first = "Call 010-1234-5678"
    second = "Project Aurora is ready"
    aggregate = f"{first} {second}"
    phone_start = aggregate.index("010-1234-5678")
    project_start = aggregate.index("Aurora")
    messages = [
        {"role": "system", "content": "Be concise"},
        {"role": "user", "content": first},
        {"role": "assistant", "content": "Which project?"},
        {"role": "user", "content": second},
    ]

    result = mask_chat_messages(
        messages,
        [
            _record(
                "MOBILE_PHONE_NUMBER",
                "010-1234-5678",
                phone_start,
                phone_start + len("010-1234-5678"),
            ),
            _record(
                "INTERNAL_PROJECT_NAME",
                "Aurora",
                project_start,
                project_start + len("Aurora"),
            ),
        ],
    )

    assert [message["role"] for message in result.value] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert result.value[0]["content"] == "Be concise"
    assert result.value[2]["content"] == "Which project?"
    assert result.value[1]["content"].startswith("Call SENSITIVE_DATA#")
    assert result.value[3]["content"].startswith("Project SENSITIVE_DATA#")
    assert "Project Aurora is ready" not in result.value[1]["content"]
    assert result.contract.count == 2


def test_repeated_sensitive_value_is_masked_in_every_context_occurrence():
    messages = [
        {"role": "user", "content": "Code Aurora"},
        {"role": "assistant", "content": "I heard Aurora"},
        {"role": "user", "content": "Review Aurora"},
    ]
    aggregate = "Code Aurora Review Aurora"
    first_start = aggregate.index("Aurora")

    result = mask_chat_messages(
        messages,
        [
            _record(
                "INTERNAL_PROJECT_NAME",
                "Aurora",
                first_start,
                first_start + len("Aurora"),
            )
        ],
    )

    assert result.value[0]["content"].startswith("Code SENSITIVE_DATA#")
    assert result.value[1]["content"].startswith("I heard SENSITIVE_DATA#")
    assert result.value[2]["content"].startswith("Review SENSITIVE_DATA#")
    assert all("Aurora" not in message["content"] for message in result.value)
    assert result.contract.count == 1


def test_missing_extracted_span_fails_closed_instead_of_forwarding_plaintext():
    messages = [{"role": "user", "content": "Code Aurora"}]

    with pytest.raises(ValueError, match="not present"):
        mask_chat_messages(
            messages,
            [_record("INTERNAL_PROJECT_NAME", "Orion", 999, 1004)],
        )


def test_chat_content_parts_and_system_text_are_masked_without_changing_shape():
    messages = [
        {"role": "system", "content": "Keep Aurora unchanged"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Call 010-1234-5678"},
                {"type": "text", "text": "Project Aurora"},
            ],
        },
    ]
    aggregate = "Call 010-1234-5678 Project Aurora"

    result = mask_chat_messages(
        messages,
        [
            _record(
                "MOBILE_PHONE_NUMBER",
                "010-1234-5678",
                aggregate.index("010-1234-5678"),
                aggregate.index("010-1234-5678") + len("010-1234-5678"),
            ),
            _record(
                "INTERNAL_PROJECT_NAME",
                "Aurora",
                aggregate.index("Aurora"),
                aggregate.index("Aurora") + len("Aurora"),
            ),
        ],
    )

    assert result.value[0]["content"].startswith("Keep SENSITIVE_DATA#")
    assert result.value[1]["content"][0]["type"] == "text"
    assert result.value[1]["content"][0]["text"].startswith("Call SENSITIVE_DATA#")
    assert result.value[1]["content"][1]["text"].startswith("Project SENSITIVE_DATA#")
    assert messages[1]["content"][0]["text"] == "Call 010-1234-5678"


def test_responses_input_preserves_shape_and_masks_complete_context():
    input_data = [
        {"role": "assistant", "content": "Prior Aurora"},
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Call 010-1234-5678"},
                {"type": "input_text", "text": "Project Aurora"},
            ],
        },
    ]
    aggregate = "Call 010-1234-5678 Project Aurora"
    phone_start = aggregate.index("010-1234-5678")
    project_start = aggregate.index("Aurora")

    result = mask_responses_input(
        input_data,
        [
            _record(
                "MOBILE_PHONE_NUMBER",
                "010-1234-5678",
                phone_start,
                phone_start + len("010-1234-5678"),
            ),
            _record(
                "INTERNAL_PROJECT_NAME",
                "Aurora",
                project_start,
                project_start + len("Aurora"),
            ),
        ],
    )

    assert result.value[0]["content"].startswith("Prior SENSITIVE_DATA#")
    content = result.value[1]["content"]
    assert content[0]["type"] == "input_text"
    assert content[0]["text"].startswith("Call SENSITIVE_DATA#")
    assert content[1]["text"].startswith("Project SENSITIVE_DATA#")
    assert result.contract.count == 2


def test_responses_input_converts_to_chat_without_flattening_segments():
    input_data = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "First"},
                {"type": "input_text", "text": "Second"},
            ],
        },
        {"role": "assistant", "content": "Prior reply"},
        {"role": "user", "content": "Follow-up"},
    ]

    messages = responses_input_to_messages(input_data)

    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert messages[0]["content"] == [
        {"type": "text", "text": "First"},
        {"type": "text", "text": "Second"},
    ]
    assert messages[1]["content"] == "Prior reply"
    assert messages[2]["content"] == "Follow-up"


def test_responses_input_replays_output_text_as_chat_text():
    messages = responses_input_to_messages(
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Prior answer"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Follow up"}],
            },
        ]
    )

    assert messages == [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Prior answer"}],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Follow up"}],
        },
    ]


def test_analysis_text_contains_complete_labeled_conversation_context():
    chat_messages = [
        {"role": "system", "content": "System secret"},
        {"role": "user", "content": "First"},
        {
            "role": "assistant",
            "content": "Prior answer",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"account":"Research Alpha"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "Research Alpha is confidential",
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Second"}],
        },
    ]
    responses_input = [
        {
            "type": "message",
            "role": "assistant",
            "content": "Prior answer",
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"account":"Research Alpha"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "Research Alpha is confidential",
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Second"}],
        },
    ]

    chat_context = chat_context_text(chat_messages)
    responses_context = responses_context_text(responses_input)

    assert chat_context == (
        "[message[0].system.content]\nSystem secret\n\n"
        "[message[1].user.content]\nFirst\n\n"
        "[message[2].assistant.content]\nPrior answer\n\n"
        "[message[2].assistant.tool_calls[0].id]\ncall_1\n\n"
        "[message[2].assistant.tool_calls[0].function.name]\nlookup\n\n"
        "[message[2].assistant.tool_calls[0].function.arguments]\n"
        '{"account":"Research Alpha"}\n\n'
        "[message[3].tool.content]\nResearch Alpha is confidential\n\n"
        "[message[3].tool.tool_call_id]\ncall_1\n\n"
        "[message[4].user.content[0].text]\nSecond"
    )
    assert responses_context == (
        "[input[0].assistant.content]\nPrior answer\n\n"
        "[input[1].function_call.call_id]\ncall_1\n\n"
        "[input[1].function_call.name]\nlookup\n\n"
        "[input[1].function_call.arguments]\n"
        '{"account":"Research Alpha"}\n\n'
        "[input[2].function_call_output.call_id]\ncall_1\n\n"
        "[input[2].function_call_output.output]\n"
        "Research Alpha is confidential\n\n"
        "[input[3].user.content[0].text]\nSecond"
    )


def test_analysis_context_excludes_binary_media_payloads():
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": "BASE64_PRIVATE_PAYLOAD",
                        "format": "wav",
                    },
                },
                {"type": "text", "text": "Analyze the quarterly plan."},
            ],
        }
    ]

    context = render_context_segments(chat_context_segments(messages))

    assert "BASE64_PRIVATE_PAYLOAD" not in context
    assert "Analyze the quarterly plan." in context


def test_session_context_merges_full_history_without_duplicate_messages_or_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "send_report",
                "description": "Send Project Aurora to the approved recipient",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recipient": {
                            "type": "string",
                            "description": "Approved Project Aurora recipient",
                        }
                    },
                },
            },
        }
    ]
    previous = chat_context_segments(
        [
            {"role": "system", "content": "Keep company data private"},
            {"role": "user", "content": "Project Aurora is confidential"},
        ],
        tools=tools,
    )
    current = chat_context_segments(
        [
            {"role": "system", "content": "Keep company data private"},
            {"role": "user", "content": "Project Aurora is confidential"},
            {"role": "assistant", "content": "Understood"},
            {"role": "user", "content": "Can I send it to the vendor?"},
        ],
        tools=tools,
    )

    merged = render_context_segments(merge_context_segments(previous, current))

    assert merged.count("Project Aurora is confidential") == 1
    assert merged.count("Send Project Aurora to the approved recipient") == 1
    assert "Can I send it to the vendor?" in merged


def test_session_context_appends_delta_request_and_keeps_repeated_tools_once():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "send_report",
                "description": "Send the report",
            },
        }
    ]
    previous = chat_context_segments(
        [{"role": "user", "content": "Project Aurora is confidential"}],
        tools=tools,
    )
    current = chat_context_segments(
        [{"role": "user", "content": "Can I send it?"}],
        tools=tools,
    )

    merged = render_context_segments(merge_context_segments(previous, current))

    assert merged.count("Project Aurora is confidential") == 1
    assert merged.count("Send the report") == 1
    assert merged.index("Can I send it?") < merged.index("Send the report")


def test_chat_masks_tool_arguments_and_tool_outputs():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"project":"Aurora"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "Aurora costs 15 million",
        },
    ]

    result = mask_chat_messages(
        messages,
        [_record("INTERNAL_PROJECT_NAME", "Aurora", 0, len("Aurora"))],
    )

    arguments = result.value[0]["tool_calls"][0]["function"]["arguments"]
    assert "Aurora" not in arguments
    assert "SENSITIVE_DATA#" in arguments
    assert "Aurora" not in result.value[1]["content"]
    assert "SENSITIVE_DATA#" in result.value[1]["content"]
    assert result.contract.count == 1


def test_chat_rejects_sensitive_tool_call_identifiers_instead_of_masking():
    identifier = "SECRET-CALL-ID"
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": identifier,
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": identifier, "content": "safe"},
    ]

    with pytest.raises(ValueError, match="protocol fields"):
        mask_chat_messages(
            messages,
            [_record("CREDENTIAL", identifier, 0, len(identifier))],
        )


def test_responses_masks_function_call_arguments_and_outputs():
    input_data = [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"project":"Aurora"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "Aurora costs 15 million",
        },
    ]

    result = mask_responses_input(
        input_data,
        [_record("INTERNAL_PROJECT_NAME", "Aurora", 0, len("Aurora"))],
    )
    messages = responses_input_to_messages(result.value)

    assert "Aurora" not in result.value[0]["arguments"]
    assert "Aurora" not in result.value[1]["output"]
    assert messages[0]["role"] == "assistant"
    assert messages[0]["tool_calls"][0]["function"]["arguments"].startswith('{"project":"SENSITIVE_DATA#')
    assert messages[1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": result.value[1]["output"],
    }


def test_responses_rejects_sensitive_call_identifiers_instead_of_masking():
    identifier = "SECRET-CALL-ID"
    input_data = [
        {
            "type": "function_call",
            "call_id": identifier,
            "name": "lookup",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": identifier,
            "output": "safe",
        },
    ]

    with pytest.raises(ValueError, match="protocol fields"):
        mask_responses_input(
            input_data,
            [_record("CREDENTIAL", identifier, 0, len(identifier))],
        )


@pytest.mark.parametrize(
    "context_text,mask_call",
    [
        (
            lambda tools, tool_choice: chat_context_text(
                [{"role": "user", "content": "safe"}],
                tools=tools,
                tool_choice=tool_choice,
            ),
            lambda record, tools, tool_choice: mask_chat_messages(
                [{"role": "user", "content": "safe"}],
                [record],
                tools=tools,
                tool_choice=tool_choice,
            ),
        ),
        (
            lambda tools, tool_choice: responses_context_text(
                "safe",
                tools=tools,
                tool_choice=tool_choice,
            ),
            lambda record, tools, tool_choice: mask_responses_input(
                "safe",
                [record],
                tools=tools,
                tool_choice=tool_choice,
            ),
        ),
    ],
)
@pytest.mark.parametrize("location", ["definition", "choice"])
def test_sensitive_callable_names_are_inspected_then_fail_closed(
    context_text,
    mask_call,
    location,
):
    name = "SECRET_TOOL_NAME"
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "safe",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    tool_choice = {"type": "function", "function": {"name": name}} if location == "choice" else "auto"
    if location == "choice":
        tools[0]["function"]["name"] = "safe_tool"

    assert name in context_text(tools, tool_choice)
    with pytest.raises(ValueError, match="protocol fields"):
        mask_call(
            _record("CREDENTIAL", name, 0, len(name)),
            tools,
            tool_choice,
        )
