"""LiteLLM adapter — concrete base for all litellm provider backends.

Handles openai-compatible endpoints by default (Ollama, vLLM, local
proxies, and the official OpenAI API).  Subclasses like
:class:`OpenRouterAdapter` override only provider-specific differences
(auth key, extra headers).

Examples
--------
>>> from adapters import LiteLLMAdapter, OpenRouterAdapter
>>> adapter = LiteLLMAdapter()
>>> adapter.resolve_backend_model("privacy-router/openai/gpt-4o")
'openai/gpt-4o'
>>> adapter.get_api_key("openai/gpt-4o")

>>> openrouter = OpenRouterAdapter()
>>> openrouter.resolve_backend_model("privacy-router/openrouter/google/gemini-3.1-flash-lite")
'openrouter/google/gemini-3.1-flash-lite'
"""

from __future__ import annotations

import ipaddress
import os
from contextlib import suppress
from typing import Any, get_args
from urllib.parse import urlsplit

import litellm
from litellm.types.llms.openai import OpenAIChatCompletionFinishReason

from config import resolve_model_api_key

_ALLOWED_FINISH_REASONS = frozenset(get_args(OpenAIChatCompletionFinishReason))
_MAX_REPORTED_TOKENS = 2_147_483_647


def _validated_token_count(value: object) -> int:
    """Return a bounded provider token count or reject untrusted metadata."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _MAX_REPORTED_TOKENS:
        raise ValueError("Invalid provider usage metadata")
    return value


def _validated_finish_reason(value: object) -> str:
    """Return a standard finish reason or reject provider-controlled text."""
    if value is None:
        return "stop"
    if not isinstance(value, str) or value not in _ALLOWED_FINISH_REASONS:
        raise ValueError("Invalid provider finish reason")
    return value


class LiteLLMAdapter:
    """Adapter for litellm backends.

    The default implementation handles any openai-compatible endpoint.
    Set ``provider_prefix`` in subclasses for provider-specific routing.

    Attributes
    ----------
    provider_prefix : str
        The litellm provider prefix (e.g. ``"openai"``, ``"openrouter"``).
    api_key_env : str
        Environment variable name for the API key.
    """

    provider_prefix: str = "openai"
    api_key_env: str = "OPENAI_API_KEY"

    # ── Public API ───────────────────────────────────────────────────────────

    def get_api_key(self, model: str) -> str:
        """Resolve the configured provider key, then fall back to the environment."""
        return resolve_model_api_key(model) or os.getenv(self.api_key_env, "")

    def resolve_backend_model(self, raw_model: str) -> str:
        """Strip ``privacy-router/`` prefix and return the litellm model ID.

        ``privacy-router/openai/gpt-4o`` → ``openai/gpt-4o``
        ``privacy-router/openrouter/google/gemini-3.1-flash-lite`` → ``openrouter/google/gemini-3.1-flash-lite``
        """
        prefix = "privacy-router/"
        if raw_model.startswith(prefix):
            return raw_model[len(prefix) :]
        return raw_model

    def supports_model(self, model_id: str) -> bool:
        """Check whether this adapter can handle *model_id*.

        Matches by ``provider_prefix/`` at the start of *model_id*.
        """
        return model_id.startswith(f"{self.provider_prefix}/")

    def call(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 256,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call the backend model via litellm.

        Parameters
        ----------
        model : str
            litellm-compatible model ID.
        messages : list of dict
            Chat messages in OpenAI format.
        temperature : float
            Sampling temperature.
        max_tokens : int
            Maximum completion tokens.
        api_base : str or None
            Custom API base URL for self-hosted endpoints.
        **kwargs
            Additional litellm parameters.

        Returns
        -------
        litellm response object
        """
        hostname = urlsplit(api_base).hostname if api_base else None
        loopback = hostname == "localhost"
        if hostname and not loopback:
            with suppress(ValueError):
                loopback = ipaddress.ip_address(hostname).is_loopback
        effective_api_key = "not-needed" if loopback else self.get_api_key(model) or None
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": effective_api_key,
        }
        if api_base:
            call_kwargs["api_base"] = api_base
        call_kwargs.update(kwargs)
        if loopback:
            call_kwargs["api_key"] = "not-needed"
        return litellm.completion(**call_kwargs)

    def format_response(
        self,
        litellm_response: Any,
        content: str,
    ) -> dict[str, Any]:
        """Format a litellm response into the standard output dict.

        Parameters
        ----------
        litellm_response
            Raw litellm completion response.
        content : str
            The (possibly hydrated) assistant message content.

        Returns
        -------
        dict
            ``{"usage": {...}, "finish_reason": str}``
        """
        usage_obj = getattr(litellm_response, "usage", None)
        usage = {
            "prompt_tokens": _validated_token_count(getattr(usage_obj, "prompt_tokens", None)),
            "completion_tokens": _validated_token_count(getattr(usage_obj, "completion_tokens", None)),
            "total_tokens": _validated_token_count(getattr(usage_obj, "total_tokens", None)),
        }
        finish_reason = _validated_finish_reason(getattr(litellm_response.choices[0], "finish_reason", None))
        return {"usage": usage, "finish_reason": finish_reason}
