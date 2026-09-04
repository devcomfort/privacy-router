"""Privacy Router — Config package.

Centralised configuration for the Privacy Router pipeline, loaded from YAML and environment variables.
"""

import os

from .loader import (
    load_config as load_config_from_yaml,
)
from .loader import (
    resolve_api_base,
    resolve_generation_binding,
    resolve_local_api_base,
    resolve_model,
)
from .schemas import (
    AgentConfig,
    LLMConfig,
    ModelSpec,
    PrivacyRouterConfig,
    Profile,
    ProfileOverride,
    is_trusted_local_api_base,
    validate_local_api_base,
)


def resolve_model_api_key(model: str) -> str | None:
    """Resolve provider API key for a model from environment variables."""
    if model.startswith("openrouter/") or "openrouter" in model.lower():
        return os.getenv("OPENROUTER_API_KEY")
    if model.startswith("openai/") or "openai" in model.lower():
        return os.getenv("OPENAI_API_KEY")
    return os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")


def load_config(path: str | None = None) -> PrivacyRouterConfig:
    """Load config from YAML file with environment variable resolution."""
    return load_config_from_yaml(path)


__all__ = [
    "PrivacyRouterConfig",
    "ModelSpec",
    "AgentConfig",
    "LLMConfig",
    "Profile",
    "ProfileOverride",
    "load_config",
    "is_trusted_local_api_base",
    "load_config_from_yaml",
    "resolve_model",
    "resolve_model_api_key",
    "resolve_api_base",
    "resolve_generation_binding",
    "resolve_local_api_base",
    "validate_local_api_base",
]
