"""OpenRouter adapter — handles openrouter/* models.

OpenRouter acts as a unified gateway to 200+ models from different
providers (OpenAI, Anthropic, Google, Meta, etc.).  A single
``OPENROUTER_API_KEY`` gives access to all of them.

Differences from the raw OpenAI adapter:

- Model IDs use the ``openrouter/`` prefix
  (e.g. ``openrouter/anthropic/claude-sonnet-4``).
- Authentication uses ``OPENROUTER_API_KEY``.
- Optional ``HTTP-Referer`` and ``X-Title`` headers for ranking.

Examples
--------
>>> adapter = OpenRouterAdapter()
>>> adapter.resolve_backend_model("privacy-router/openrouter/google/gemini-3.1-flash-lite")
'openrouter/google/gemini-3.1-flash-lite'
>>> adapter.supports_model("openrouter/anthropic/claude-sonnet-4")
True
"""

from __future__ import annotations

import os
from typing import Any

from .base import LiteLLMAdapter


class OpenRouterAdapter(LiteLLMAdapter):
    """Adapter for the OpenRouter API.

    OpenRouter provides a unified interface to models from OpenAI,
    Anthropic, Google, Meta, and others through a single API key.

    Optional ``HTTP-Referer`` and ``X-Title`` headers can be set
    via environment variables to identify this application on the
    OpenRouter leaderboard.
    """

    provider_prefix = "openrouter"

    # ── LiteLLMAdapter interface ─────────────────────────────────────────────

    provider_prefix = "openrouter"
    api_key_env = "OPENROUTER_API_KEY"

    def call(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 256,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call OpenRouter, injecting ranking headers automatically.

        Reads ``OPENROUTER_HTTP_REFERER`` and ``OPENROUTER_X_TITLE``
        from the environment and passes them as ``HTTP-Referer`` and
        ``X-Title`` headers.  These are used by OpenRouter for usage
        ranking and are entirely optional.
        """
        referer = os.getenv("OPENROUTER_HTTP_REFERER", "")
        title = os.getenv("OPENROUTER_X_TITLE", "")
        if referer or title:
            extra: dict[str, str] = {}
            if referer:
                extra["HTTP-Referer"] = referer
            if title:
                extra["X-Title"] = title
            kwargs["extra_headers"] = extra
        return super().call(model, messages, temperature, max_tokens, api_base=api_base, **kwargs)
