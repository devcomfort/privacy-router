"""Config schemas — Pydantic models for .privacy-router.config.yaml.

All public types are re-exported via ``config/__init__.py``.
"""

from __future__ import annotations

from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

_NATIVE_LOOPBACK_MODEL_PREFIXES = ("ollama/", "ollama_chat/")


def validate_local_api_base(model_id: str, api_base: str | None) -> str | None:
    """Require local custom endpoints to use an unambiguous loopback host."""
    if api_base is None:
        if model_id.startswith(_NATIVE_LOOPBACK_MODEL_PREFIXES):
            return None
        raise ValueError(f"Local model {model_id!r} requires a loopback api_base")

    try:
        parsed = urlsplit(api_base)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Local model {model_id!r} has an invalid api_base") from exc

    if parsed.scheme not in {"http", "https"} or not host or port is None:
        raise ValueError(f"Local model {model_id!r} api_base must be an HTTP(S) loopback URL with an explicit port")

    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost":
        return api_base
    try:
        is_loopback = ip_address(normalized_host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise ValueError(f"Local model {model_id!r} api_base host must be loopback: {host!r}")
    return api_base


# ── Model spec ───────────────────────────────────────────────────────────────


class ModelSpec(BaseModel):
    """A single model entry in the model registry.

    litellm infers the provider from the ``id`` prefix:

    - ``openrouter/...`` → OpenRouter
    - ``openai/...`` → OpenAI or any OpenAI-compatible endpoint
      (set ``api_base`` for custom endpoints like Ollama, vLLM)
    - ``ollama/...`` → Ollama (auto-detected by litellm)
    - ``anthropic/...`` → Anthropic
    - ``google/...`` → Google (Gemini)

    API keys are resolved by litellm automatically from environment
    variables (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.).

    Attributes
    ----------
    id : str
        litellm model identifier.
    api_base : str or None
        Base URL for OpenAI-compatible endpoints.
        Unnecessary for litellm-native providers (OpenRouter, etc.).
    location : str
        ``"local"`` (on-premises) or ``"external"`` (cloud API).
    tier : str
        Capability tier: ``"small"`` (<8B), ``"middle"`` (8-30B), or ``"large"`` (>30B).
    cost_per_1m_tokens : float
        Approximate cost per 1M input tokens (USD). Informational only.

    Examples
    --------
    >>> m = ModelSpec(id="openrouter/mistralai/ministral-3b-2512", location="external", tier="small", cost_per_1m_tokens=0.10)
    >>> m.tier
    'small'

    >>> local = ModelSpec(id="openai/qwen2.5:7b", api_base="http://localhost:11434/v1", location="local", tier="small", cost_per_1m_tokens=0.0)
    >>> local.location
    'local'
    """

    id: str = Field(
        ...,
        description="litellm model identifier. Prefix determines provider routing.",
        examples=["openrouter/mistralai/ministral-3b-2512", "openai/qwen2.5:7b"],
    )
    api_base: str | None = Field(
        default=None,
        description="Base URL for OpenAI-compatible endpoints. Not needed for native litellm providers.",
        examples=["http://localhost:11434/v1"],
    )
    location: Literal["local", "external"] = Field(
        default="external",
        description="Model location: local (on-premises) or external (cloud API).",
        examples=["local", "external"],
    )
    tier: Literal["small", "middle", "large"] = Field(
        ...,
        description="Capability tier: small (<8B), middle (8-30B), large (>30B).",
        examples=["small", "middle", "large"],
    )
    cost_per_1m_tokens: float = Field(
        ...,
        ge=0.0,
        description="Approximate cost per 1M input tokens (USD). Informational only.",
        examples=[0.10, 0.25],
    )

    @model_validator(mode="after")
    def validate_local_endpoint(self) -> ModelSpec:
        if self.location == "local":
            validate_local_api_base(self.id, self.api_base)
        return self


# ── Agent config ─────────────────────────────────────────────────────────────


class LLMConfig(BaseModel):
    """LLM call-level knobs shared by all agents.

    Attributes
    ----------
    temperature : float
        Sampling temperature (0.0 = deterministic).
    max_tokens : int
        Maximum completion tokens.

    Examples
    --------
    >>> c = LLMConfig(temperature=0.0, max_tokens=4096)
    >>> c.temperature
    0.0
    """

    temperature: float = Field(
        ...,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
        examples=[0.0],
    )
    max_tokens: int = Field(
        ...,
        ge=1,
        description="Maximum completion tokens.",
        examples=[4096],
    )


class AgentConfig(BaseModel):
    """Per-agent configuration: which model to use and how.

    Attributes
    ----------
    model : str
        Model id (must match a key in the top-level ``models`` list).
    api_base : str or None
        Override API base URL. If None, resolved from model registry.
    config : LLMConfig
        LLM call parameters.

    Examples
    --------
    >>> a = AgentConfig(model="openrouter/mistralai/ministral-3b-2512", config=LLMConfig(temperature=0.0, max_tokens=4096))
    >>> a.model
    'openrouter/mistralai/ministral-3b-2512'
    """

    model: str = Field(
        ...,
        description="Model id. Must appear in the top-level models registry.",
        examples=["openrouter/mistralai/ministral-3b-2512"],
    )
    api_base: str | None = Field(
        default=None,
        description="Override API base URL. If None, resolved from model registry.",
    )
    config: LLMConfig = Field(
        ...,
        description="LLM call parameters (temperature, max_tokens).",
    )


# ── Profile ──────────────────────────────────────────────────────────────────


class ProfileOverride(BaseModel):
    """Per-agent override within a profile.

    Only specified fields override the base config; omitted fields inherit.
    """

    model: str | None = Field(
        default=None,
        description="Override model id. None = inherit from base config.",
    )
    api_base: str | None = Field(
        default=None,
        description="Override API base URL. None = inherit from base config.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Override temperature. None = inherit.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Override max_tokens. None = inherit.",
    )


class Profile(BaseModel):
    """Named overrides for the three runtime model roles."""

    decision: ProfileOverride | None = Field(
        default=None,
        description="Sensitive decision model override.",
    )
    local: ProfileOverride | None = Field(
        default=None,
        description="Local generation model override.",
    )
    external: ProfileOverride | None = Field(
        default=None,
        description="External generation model override.",
    )
    description: str = Field(
        default="",
        description="Human-readable profile description.",
    )


# ── Top-level config ─────────────────────────────────────────────────────────


class PrivacyRouterConfig(BaseModel):
    """Validated model catalog and the three explicit runtime roles.

    ``decision`` and ``local`` are hard-bound to on-device models.
    ``external`` is hard-bound to a cloud model.  These location checks are
    trust-boundary invariants, not UI hints.
    """

    models: list[ModelSpec] = Field(
        ...,
        min_length=1,
        description="Available model registry.",
    )
    decision: AgentConfig = Field(
        ...,
        description="Local model for sensitivity analysis and structured extraction.",
    )
    local: AgentConfig = Field(
        ...,
        description="Local model for raw sensitive generation and hydration repair.",
    )
    external: AgentConfig = Field(
        ...,
        description="External model for safe or masked generation.",
    )
    profiles: dict[str, Profile] = Field(
        default_factory=dict,
        description="Named profiles that override runtime model assignments.",
    )
    active_profile: str | None = Field(
        default=None,
        description="Currently active profile name. Set via PRIVACY_ROUTER_PROFILE.",
    )

    @model_validator(mode="after")
    def validate_role_locations(self) -> PrivacyRouterConfig:
        catalog: dict[str, ModelSpec] = {}
        for model in self.models:
            if model.id in catalog:
                raise ValueError(f"Duplicate model id: {model.id!r}")
            catalog[model.id] = model

        expected_locations = {
            "decision": "local",
            "local": "local",
            "external": "external",
        }

        def validate_binding(
            role: str,
            model_id: str,
            api_base: str | None,
        ) -> None:
            expected_location = expected_locations[role]
            model = catalog.get(model_id)
            if model is None:
                raise ValueError(f"{role} model {model_id!r} is not registered in models")
            if model.location != expected_location:
                raise ValueError(f"{role} model must be {expected_location}, got {model.location}: {model.id}")
            if model.location == "local":
                validate_local_api_base(model.id, api_base if api_base is not None else model.api_base)

        for role in expected_locations:
            configured = getattr(self, role)
            validate_binding(role, configured.model, configured.api_base)

        for profile_name, profile in self.profiles.items():
            for role in expected_locations:
                base = getattr(self, role)
                override = getattr(profile, role)
                if override is None:
                    continue
                model_id = override.model or base.model
                api_base = override.api_base
                if api_base is None and override.model is None:
                    api_base = base.api_base
                try:
                    validate_binding(role, model_id, api_base)
                except ValueError as exc:
                    raise ValueError(f"Profile {profile_name!r}: {exc}") from exc
        return self
