"""Config loader — reads .privacy-router.config.yaml with env var resolution.

Public API
----------
load_config
    Load config from a YAML file, returning a validated
    :class:`PrivacyRouterConfig`.
resolve_model
    Look up a :class:`ModelSpec` by id from the config's model registry.

Examples
--------
>>> from config.loader import load_config
>>> config = load_config()
>>> config.decision.model
'openai/LGAI-EXAONE/EXAONE-4.0-1.2B'
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .schemas import ModelSpec, PrivacyRouterConfig, ProfileOverride, validate_local_api_base

# ── Default locations to search ──────────────────────────────────────────────

_DEFAULT_PATH = Path(".privacy-router.config.yaml")


# ── Public API ───────────────────────────────────────────────────────────────


def load_config(path: str | Path | None = None) -> PrivacyRouterConfig:
    """Load and validate the Privacy Router config from a YAML file.

    Supports profile activation via ``PRIVACY_ROUTER_PROFILE`` env var.
    When set, the named profile's overrides are applied to the base config.

    Parameters
    ----------
    path : str, Path, or None
        Path to a YAML config file.  If ``None``, reads
        ``.privacy-router.config.yaml`` from CWD.

    Returns
    -------
    PrivacyRouterConfig
        Validated configuration object with profile overrides applied.

    Raises
    ------
    FileNotFoundError
        If no config file is found at the given or default paths.
    ValueError
        If the YAML is malformed or fails Pydantic validation.

    Examples
    --------
    >>> config = load_config()
    >>> config.decision.model
    'openai/LGAI-EXAONE/EXAONE-4.0-1.2B'
    """
    config_path = Path(path) if path is not None else _DEFAULT_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {config_path}. "
            "Copy .privacy-router.config.yaml.example to .privacy-router.config.yaml "
            "and edit it to match your setup."
        )

    raw = _read_yaml(config_path)
    resolved = _resolve_env_vars(raw)
    config = PrivacyRouterConfig.model_validate(resolved)

    # Apply profile overrides if PRIVACY_ROUTER_PROFILE is set
    profile_name = os.environ.get("PRIVACY_ROUTER_PROFILE")
    if profile_name:
        config = _apply_profile(config, profile_name)

    return config


def _apply_profile(config: PrivacyRouterConfig, profile_name: str) -> PrivacyRouterConfig:
    """Apply a named profile's overrides to the config.

    Parameters
    ----------
    config : PrivacyRouterConfig
        Base configuration.
    profile_name : str
        Name of the profile to activate.

    Returns
    -------
    PrivacyRouterConfig
        Config with profile overrides applied.
    """
    if profile_name not in config.profiles:
        available = list(config.profiles.keys())
        raise ValueError(f"Profile '{profile_name}' not found. Available: {available}")

    profile = config.profiles[profile_name]
    data = config.model_dump()

    for agent_name in ("decision", "local", "external"):
        override: ProfileOverride | None = getattr(profile, agent_name, None)
        if override is None:
            continue
        agent = data[agent_name]
        if override.model is not None:
            agent["model"] = override.model
            if override.api_base is None:
                agent["api_base"] = None
        if override.api_base is not None:
            agent["api_base"] = override.api_base
        if override.temperature is not None:
            agent["config"]["temperature"] = override.temperature
        if override.max_tokens is not None:
            agent["config"]["max_tokens"] = override.max_tokens

    data["active_profile"] = profile_name
    return PrivacyRouterConfig.model_validate(data)


def resolve_model(config: PrivacyRouterConfig, model_id: str) -> ModelSpec:
    """Find a model spec by id in the config's model registry.

    Parameters
    ----------
    config : PrivacyRouterConfig
        The loaded configuration.
    model_id : str
        The model id to look up.

    Returns
    -------
    ModelSpec
        The matching model spec.

    Raises
    ------
    KeyError
        If *model_id* is not found in the registry.

    Examples
    --------
    >>> config = load_config()
    >>> spec = resolve_model(config, "openrouter/mistralai/ministral-3b-2512")
    >>> spec.tier
    'edge'
    """
    for m in config.models:
        if m.id == model_id:
            return m
    raise KeyError(f"Model {model_id!r} not found in config.models. Available: {[m.id for m in config.models]}")


_NATIVE_LOCAL_API_BASES = {
    "ollama": "http://127.0.0.1:11434",
    "ollama_chat": "http://127.0.0.1:11434",
}


def resolve_api_base(
    config: PrivacyRouterConfig,
    model_id: str,
    configured_api_base: str | None = None,
) -> str | None:
    """Resolve and validate the effective endpoint for a registered model."""
    spec = resolve_model(config, model_id)
    api_base = configured_api_base if configured_api_base is not None else spec.api_base
    if spec.location != "local":
        return api_base

    provider = model_id.split("/", 1)[0]
    if api_base is None:
        api_base = _NATIVE_LOCAL_API_BASES.get(provider)
    validate_local_api_base(model_id, api_base)
    return api_base


def resolve_local_api_base(
    config: PrivacyRouterConfig,
    model_id: str,
    configured_api_base: str | None = None,
) -> str:
    """Resolve a registered on-device model to a validated loopback endpoint."""
    spec = resolve_model(config, model_id)
    if spec.location != "local":
        raise ValueError(f"Local execution requires a local model: {model_id}")
    api_base = resolve_api_base(config, model_id, configured_api_base)
    if api_base is None:  # Defensive: every supported local provider resolves above.
        raise ValueError(f"Local model {model_id!r} requires a loopback api_base")
    return api_base


def resolve_generation_binding(
    config: PrivacyRouterConfig,
    policy_action: str,
    requested: str | None = None,
) -> tuple[str, dict[str, Any], str | None]:
    """Bind generation to a registry model without crossing location boundaries."""
    if policy_action == "block":
        model_id = config.local.model
        return (
            model_id,
            config.local.config.model_dump(),
            resolve_local_api_base(config, model_id, config.local.api_base),
        )

    model_id = requested or config.external.model
    spec = resolve_model(config, model_id)
    if spec.location != "external":
        raise ValueError(f"External generation requires an external model: {model_id}")
    configured_api_base = config.external.api_base if model_id == config.external.model else None
    return (
        model_id,
        config.external.config.model_dump(),
        resolve_api_base(config, model_id, configured_api_base),
    )


# ── Internal helpers ─────────────────────────────────────────────────────────


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping.")
    return data


def _resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ``${ENV_VAR}`` and ``${ENV_VAR:default}`` in strings.

    Examples
    --------
    >>> os.environ["TEST_KEY"] = "hello"
    >>> _resolve_env_vars({"key": "${TEST_KEY}"})
    {'key': 'hello'}
    >>> _resolve_env_vars({"key": "${MISSING:world}"})
    {'key': 'world'}
    """
    _ENV_RE = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")

    def _resolve(value: str) -> str:
        def _replace(m: re.Match) -> str:
            var = m.group(1)
            default = m.group(2)
            return os.environ.get(var, default if default is not None else m.group(0))

        return _ENV_RE.sub(_replace, value)

    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(v) for v in data]
    if isinstance(data, str):
        return _resolve(data)
    return data
