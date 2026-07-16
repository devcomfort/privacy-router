"""Provider response metadata validation tests."""

from types import SimpleNamespace

import pytest

from server.adapters import LiteLLMAdapter


def _response(
    *,
    finish_reason: object = "stop",
    prompt_tokens: object = 1,
    completion_tokens: object = 2,
    total_tokens: object = 3,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason)],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


@pytest.mark.parametrize(
    "finish_reason",
    [
        "stop",
        "length",
        "tool_calls",
        "content_filter",
        "function_call",
        "guardrail_intervened",
        "eos",
        "finish_reason_unspecified",
        "malformed_function_call",
    ],
)
def test_format_response_accepts_standard_finish_reasons(finish_reason: str) -> None:
    formatted = LiteLLMAdapter().format_response(
        _response(finish_reason=finish_reason),
        "ignored",
    )

    assert formatted == {
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
        "finish_reason": finish_reason,
    }


@pytest.mark.parametrize(
    "finish_reason",
    [True, 7, "stop\ndata: injected", "", "unknown"],
)
def test_format_response_rejects_invalid_finish_reason(finish_reason: object) -> None:
    with pytest.raises(ValueError, match="Invalid provider finish reason"):
        LiteLLMAdapter().format_response(
            _response(finish_reason=finish_reason),
            "ignored",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_tokens", True),
        ("completion_tokens", -1),
        ("total_tokens", "3"),
        ("prompt_tokens", 1.5),
        ("total_tokens", 2_147_483_648),
    ],
)
def test_format_response_rejects_invalid_usage(field: str, value: object) -> None:
    values: dict[str, object] = {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }
    values[field] = value

    with pytest.raises(ValueError, match="Invalid provider usage metadata"):
        LiteLLMAdapter().format_response(_response(**values), "ignored")


def test_format_response_defaults_missing_metadata() -> None:
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason=None)], usage=None)

    assert LiteLLMAdapter().format_response(response, "ignored") == {
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "finish_reason": "stop",
    }


def test_call_never_sends_remote_provider_key_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "server.adapters.base.resolve_model_api_key",
        lambda model_id: "REMOTE_PROVIDER_SECRET",
    )

    def capture_completion(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("server.adapters.base.litellm.completion", capture_completion)

    LiteLLMAdapter().call(
        "openai/local-model",
        [{"role": "user", "content": "test"}],
        api_base="http://127.0.0.1:8000/v1",
        api_key="EXPLICIT_REMOTE_SECRET",
    )

    assert captured["api_key"] == "not-needed"
