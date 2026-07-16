"""Privacy Router — Config package.

Centralised configuration for the Privacy Router pipeline.
Configuration is stored in SQLite (primary) with YAML as bootstrap fallback.

Public API
----------
PrivacyRouterConfig
    Root config model.
ModelSpec
    A single model entry in the registry.
AgentConfig
    Per-agent model + LLM parameter configuration.
LLMConfig
    LLM call-level knobs (temperature, max_tokens).
Profile / ProfileOverride
    Named profile definitions and per-agent overrides.
load_config
    Load config from SQLite (primary) or YAML (fallback).
resolve_model / resolve_generation_binding
    Resolve registered models and policy-bound generation endpoints.

Examples
--------
>>> from config import load_config, resolve_model
>>> config = load_config()
>>> spec = resolve_model(config, config.decision.model)
>>> spec.location
'local'
"""

from .db_loader import load_config_from_db, resolve_model_api_key, seed_from_yaml
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
    validate_local_api_base,
)


def load_config() -> PrivacyRouterConfig:
    """Load authoritative config from SQLite, seeding it from YAML on first run."""
    return load_config_from_db()


__all__ = [
    "PrivacyRouterConfig",
    "ModelSpec",
    "AgentConfig",
    "LLMConfig",
    "Profile",
    "ProfileOverride",
    "load_config",
    "load_config_from_db",
    "load_config_from_yaml",
    "resolve_model",
    "resolve_model_api_key",
    "resolve_api_base",
    "resolve_generation_binding",
    "resolve_local_api_base",
    "seed_from_yaml",
    "validate_local_api_base",
]
