from __future__ import annotations

import importlib
import importlib.metadata
import json
import sys
from typing import Any

from probe_common import load_messages


FIXTURE = load_messages()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def type_names(value: Any) -> Any:
    if isinstance(value, list):
        return [type_names(item) for item in value]
    if isinstance(value, dict):
        return {str(key): type_names(item) for key, item in value.items()}
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    return type(value).__name__


def safe_dump(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [safe_dump(item) for item in value]
    if isinstance(value, dict):
        return {str(key): safe_dump(item) for key, item in value.items()}
    for method_name in ("model_dump", "to_dict", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return safe_dump(method(mode="json"))
            except TypeError:
                try:
                    return safe_dump(method())
                except Exception:
                    pass
            except Exception:
                pass
    return repr(value)


def field_names(cls: Any) -> list[str]:
    model_fields = getattr(cls, "model_fields", None)
    if isinstance(model_fields, dict):
        return sorted(model_fields)
    fields = getattr(cls, "__fields__", None)
    if isinstance(fields, dict):
        return sorted(fields)
    required = getattr(cls, "__required_keys__", set())
    optional = getattr(cls, "__optional_keys__", set())
    if required or optional:
        return sorted(required | optional)
    annotations = getattr(cls, "__annotations__", None)
    if isinstance(annotations, dict):
        return sorted(annotations)
    return []


def imported_attr(module_name: str, attribute: str, fallback: Any = None) -> Any:
    try:
        return getattr(importlib.import_module(module_name), attribute)
    except (ImportError, ModuleNotFoundError, AttributeError):
        return fallback


def type_kind(value: Any) -> str:
    try:
        if issubclass(value, dict) and hasattr(value, "__annotations__"):
            return "TypedDict"
    except TypeError:
        pass
    return "typing.Union"


def report_openai() -> dict[str, Any]:
    try:
        module = importlib.import_module("openai.types.chat")
        param_module = importlib.import_module("openai.types.chat.chat_completion_message_param")
        user_cls = imported_attr(
            "openai.types.chat.chat_completion_user_message_param",
            "ChatCompletionUserMessageParam",
            getattr(param_module, "ChatCompletionUserMessageParam", None),
        )
        assistant_cls = imported_attr(
            "openai.types.chat.chat_completion_assistant_message_param",
            "ChatCompletionAssistantMessageParam",
            getattr(param_module, "ChatCompletionAssistantMessageParam", None),
        )
        tool_cls = imported_attr(
            "openai.types.chat.chat_completion_tool_message_param",
            "ChatCompletionToolMessageParam",
            getattr(param_module, "ChatCompletionToolMessageParam", None),
        )
        user = {"role": "user", "content": FIXTURE[1]["content"]}
        assistant = {"role": "assistant", "content": FIXTURE[2]["content"]}
        combined_cls = getattr(param_module, "ChatCompletionMessageParam", None)
        result: dict[str, Any] = {
            "package_version": package_version("openai"),
            "message_param_kind": type_kind(combined_cls),
            "combined_param_fields": field_names(combined_cls),
            "param_classes": {
                "user": field_names(user_cls),
                "assistant": field_names(assistant_cls),
                "tool": field_names(tool_cls),
            },
            "fixture_shape": {
                "user_class": type(user).__name__,
                "assistant_class": type(assistant).__name__,
                "user_keys": sorted(user),
            },
            "chat_module": module.__name__,
        }
        return result
    except Exception as exc:
        return {"package_version": package_version("openai"), "error": f"{type(exc).__name__}: {exc}"}


def report_anthropic() -> dict[str, Any]:
    try:
        param_module = importlib.import_module("anthropic.types.message_param")
        message_module = importlib.import_module("anthropic.types.message")
        create_module = importlib.import_module("anthropic.types.message_create_params")
        message_param_cls = getattr(param_module, "MessageParam", None)
        message_cls = getattr(message_module, "Message", None)
        messages_cls = getattr(create_module, "MessageCreateParamsBase", None)
        user = {"role": "user", "content": FIXTURE[1]["content"]}
        result: dict[str, Any] = {
            "package_version": package_version("anthropic"),
            "message_param_kind": type_kind(message_param_cls),
            "message_param_fields": field_names(message_param_cls),
            "response_fields": field_names(message_cls),
            "request_fields": field_names(messages_cls),
            "fixture_shape": {"class": type(user).__name__, "keys": sorted(user)},
        }
        return result
    except Exception as exc:
        return {"package_version": package_version("anthropic"), "error": f"{type(exc).__name__}: {exc}"}


def report_langchain() -> dict[str, Any]:
    try:
        messages = importlib.import_module("langchain_core.messages")
        base = importlib.import_module("langchain_core.messages.base")
        human = messages.HumanMessage(content=FIXTURE[1]["content"])
        assistant = messages.AIMessage(content=FIXTURE[2]["content"])
        serialize = getattr(messages, "messages_to_dict", None) or getattr(base, "messages_to_dict")
        deserialize = getattr(messages, "messages_from_dict", None) or getattr(base, "messages_from_dict")
        serialized = serialize([human, assistant])
        restored = deserialize(serialized)
        return {
            "package_version": package_version("langchain-core"),
            "base_message_fields": field_names(base.BaseMessage),
            "message_classes": [type(human).__name__, type(assistant).__name__],
            "serialized": safe_dump(serialized),
            "roundtrip_classes": [type(item).__name__ for item in restored],
        }
    except Exception as exc:
        return {"package_version": package_version("langchain-core"), "error": f"{type(exc).__name__}: {exc}"}


def report_litellm() -> dict[str, Any]:
    try:
        utils = importlib.import_module("litellm.types.utils")
        message_cls = utils.Message
        message = message_cls(role="assistant", content=FIXTURE[2]["content"])
        return {
            "package_version": package_version("litellm"),
            "message_fields": field_names(message_cls),
            "model_config_extra": getattr(getattr(message_cls, "model_config", {}), "get", lambda *_: None)("extra"),
            "serialized": safe_dump(message),
            "input_shape": {
                "messages": [
                    {"role": FIXTURE[1]["role"], "content": FIXTURE[1]["content"]},
                    {"role": FIXTURE[2]["role"], "content": FIXTURE[2]["content"]},
                ]
            },
        }
    except Exception as exc:
        return {"package_version": package_version("litellm"), "error": f"{type(exc).__name__}: {exc}"}


print(
    json.dumps(
        {
            "python": sys.version.split()[0],
            "openai": report_openai(),
            "anthropic": report_anthropic(),
            "langchain_core": report_langchain(),
            "litellm": report_litellm(),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
)
