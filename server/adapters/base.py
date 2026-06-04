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
>>> adapter.get_api_key()  # reads OPENAI_API_KEY from env

>>> openrouter = OpenRouterAdapter()
>>> openrouter.resolve_backend_model("privacy-router/openrouter/google/gemini-3.1-flash-lite")
'openrouter/google/gemini-3.1-flash-lite'
"""

from __future__ import annotations

import os
from typing import Any

import litellm


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

    def get_api_key(self) -> str:
        """Return the API key for this provider from the environment."""
        return os.getenv(self.api_key_env, "")

    def resolve_backend_model(self, raw_model: str) -> str:
        """Strip ``privacy-router/`` prefix and return the litellm model ID.

        ``privacy-router/openai/gpt-4o`` → ``openai/gpt-4o``
        ``privacy-router/openrouter/google/gemini-3.1-flash-lite`` → ``openrouter/google/gemini-3.1-flash-lite``
        """
        prefix = "privacy-router/"
        if raw_model.startswith(prefix):
            return raw_model[len(prefix):]
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
        api_key = self.get_api_key()
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": api_key if api_key else None,
        }
        if api_base:
            call_kwargs["api_base"] = api_base
        call_kwargs.update(kwargs)
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
        usage = {
            "prompt_tokens": (
                getattr(litellm_response.usage, "prompt_tokens", 0)
                if litellm_response.usage else 0
            ),
            "completion_tokens": (
                getattr(litellm_response.usage, "completion_tokens", 0)
                if litellm_response.usage else 0
            ),
            "total_tokens": (
                getattr(litellm_response.usage, "total_tokens", 0)
                if litellm_response.usage else 0
            ),
        }
        finish_reason = (
            litellm_response.choices[0].finish_reason or "stop"
        )
        return {"usage": usage, "finish_reason": finish_reason}
