"""Provider adapters — encapsulate backend-specific differences.

Each adapter handles authentication, model resolution, and
provider-specific request/response formatting for a single
LLM backend (OpenAI, OpenRouter, etc.).

All adapters are re-exported via ``adapters/__init__.py``.
"""

from .base import LiteLLMAdapter
from .openrouter import OpenRouterAdapter

__all__ = ["LiteLLMAdapter", "OpenRouterAdapter"]
