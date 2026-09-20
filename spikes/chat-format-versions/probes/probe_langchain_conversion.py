from __future__ import annotations

import json
from importlib.metadata import version

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.base import message_to_dict, messages_to_dict
from langchain_core.messages.utils import convert_to_openai_messages

from probe_common import load_messages


fixture = load_messages()
messages = [
    SystemMessage(content=fixture[0]["content"]),
    HumanMessage(content=fixture[1]["content"]),
    AIMessage(
        content="",
        tool_calls=[{"name": "weather", "args": {"city": "Seoul"}, "id": "call_1", "type": "tool_call"}],
    ),
    ToolMessage(content="Sunny", tool_call_id="call_1"),
]

print(
    json.dumps(
        {
            "package_version": version("langchain-core"),
            "langchain_serialization": messages_to_dict(messages),
            "single_message_serialization": message_to_dict(messages[1]),
            "openai_conversion": convert_to_openai_messages(messages),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
)
