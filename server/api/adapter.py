"""Privacy Router Server — adapter resolver.

Selects the right LiteLLM adapter based on the backend model prefix.
"""

from __future__ import annotations

from server.adapters import LiteLLMAdapter, OpenRouterAdapter


def adapter_for(model_id: str) -> LiteLLMAdapter:
    """Select the right adapter for *model_id* based on its prefix.

    Parameters
    ----------
    model_id : str
        A litellm model ID (e.g. ``"openrouter/google/gemini-3.1-flash-lite"``).

    Returns
    -------
    LiteLLMAdapter
        The adapter that supports this model.

    Raises
    ------
    ValueError
        If no adapter matches the model prefix.
    """
    adapters: list[LiteLLMAdapter] = [OpenRouterAdapter(), LiteLLMAdapter()]
    for a in adapters:
        if a.supports_model(model_id):
            return a
    raise ValueError(
        f"No adapter found for model {model_id!r}. "
        f"Supported prefixes: {[a.provider_prefix for a in adapters]}"
    )
