from __future__ import annotations

import json
from typing import Any, get_args

from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam


def keys(item: Any) -> list[str]:
    required = getattr(item, "__required_keys__", set())
    optional = getattr(item, "__optional_keys__", set())
    annotations = getattr(item, "__annotations__", {})
    return sorted(set(required) | set(optional) | set(annotations))


print(
    json.dumps(
        {
            "alias_type": str(ChatCompletionMessageParam),
            "combined_fields": keys(ChatCompletionMessageParam),
            "union_members": [
                {"name": getattr(item, "__name__", str(item)), "fields": keys(item)}
                for item in get_args(ChatCompletionMessageParam)
            ],
        },
        indent=2,
        sort_keys=True,
    )
)
