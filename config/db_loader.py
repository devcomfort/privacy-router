"""Config DB loader — reads config from SQLite instead of YAML.

This is the new primary config source. YAML is used only for bootstrap/seed.

Public API
----------
load_config_from_db
    Load config from SQLite, returning a validated PrivacyRouterConfig.
seed_from_yaml
    Populate SQLite from .privacy-router.config.yaml (first-run bootstrap).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlmodel import Session, select

from db import Model as ModelDB
from db import Profile as ProfileDB
from db import ProfileAgent as ProfileAgentDB
from db import Provider as ProviderDB
from db import Workspace as WorkspaceDB
from db import get_session, init_db

from .loader import load_config as load_yaml
from .schemas import (
    AgentConfig,
    LLMConfig,
    ModelSpec,
    PrivacyRouterConfig,
    Profile,
    ProfileOverride,
)

# ── Session ──────────────────────────────────────────────────────────────────


def _get_session() -> Session:
    """Open a session on the database shared by the API and runtime loader."""
    return get_session()


# ── Public API ───────────────────────────────────────────────────────────────


_RUNTIME_ROLES = ("decision", "local", "external")


def _sync_runtime_schema(
    session: Session,
    yaml_config: PrivacyRouterConfig,
) -> None:
    """Migrate legacy role rows and register models selected by the YAML bootstrap.

    SQLite remains authoritative for existing role assignments. YAML only supplies
    missing catalog entries and missing roles during a clean cutover.
    """
    for spec in yaml_config.models:
        provider_id = spec.id.split("/", 1)[0] if "/" in spec.id else "unknown"
        provider = session.get(ProviderDB, provider_id)
        if provider is None:
            session.add(
                ProviderDB(
                    id=provider_id,
                    name=provider_id.title(),
                    api_base=spec.api_base,
                )
            )

        model = session.exec(select(ModelDB).where(ModelDB.model_id == spec.id)).first()
        if model is None:
            session.add(
                ModelDB(
                    model_id=spec.id,
                    provider_id=provider_id,
                    display_name=spec.id.rsplit("/", 1)[-1],
                    location=spec.location,
                    tier=spec.tier,
                    cost_per_1m_tokens=spec.cost_per_1m_tokens,
                    api_base_override=spec.api_base,
                )
            )

    profiles = session.exec(select(ProfileDB)).all()
    for profile in profiles:
        rows = session.exec(select(ProfileAgentDB).where(ProfileAgentDB.profile_id == profile.id)).all()
        by_role = {row.agent_name: row for row in rows}
        for row in rows:
            if row.agent_name not in _RUNTIME_ROLES:
                session.delete(row)

        yaml_profile = yaml_config.profiles.get(profile.id)
        for role in _RUNTIME_ROLES:
            if role in by_role:
                continue
            override = getattr(yaml_profile, role, None) if yaml_profile else None
            base = getattr(yaml_config, role)
            session.add(
                ProfileAgentDB(
                    profile_id=profile.id,
                    agent_name=role,
                    model_id=override.model if override and override.model else base.model,
                    temperature=override.temperature if override else None,
                    max_tokens=override.max_tokens if override else None,
                )
            )

    session.commit()


def load_config_from_db() -> PrivacyRouterConfig:
    """Load validated config from the shared database."""
    init_db()
    session = _get_session()
    try:
        return _load_config_from_session(session)
    finally:
        session.close()


def _load_config_from_session(session: Session) -> PrivacyRouterConfig:
    """Build runtime config from one caller-owned database session."""
    # Check if DB has data
    workspace = session.exec(select(WorkspaceDB).where(WorkspaceDB.id == "default")).first()
    if workspace is None:
        # First run — seed from YAML in the same transaction boundary.
        _seed_from_yaml(session)
        workspace = session.exec(select(WorkspaceDB).where(WorkspaceDB.id == "default")).first()

    try:
        yaml_base = load_yaml()
    except Exception:
        yaml_base = None
    if yaml_base is not None:
        _sync_runtime_schema(session, yaml_base)

    # Load models registry
    models = session.exec(select(ModelDB).where(ModelDB.is_active)).all()
    model_specs = [
        ModelSpec(
            id=m.model_id,
            location=m.location,
            tier=m.tier,
            cost_per_1m_tokens=m.cost_per_1m_tokens,
            api_base=m.api_base_override or _get_provider_api_base(session, m.provider_id),
        )
        for m in models
    ]

    # Determine active profile
    profile_name = os.environ.get("PRIVACY_ROUTER_PROFILE") or workspace.active_profile or "default"
    profile = session.exec(select(ProfileDB).where(ProfileDB.id == profile_name)).first()

    # Load profile agents
    agent_configs = {}
    if profile:
        profile_agents = session.exec(select(ProfileAgentDB).where(ProfileAgentDB.profile_id == profile.id)).all()
        for pa in profile_agents:
            model = session.exec(select(ModelDB).where(ModelDB.model_id == pa.model_id)).first()
            if model:
                api_base = model.api_base_override or _get_provider_api_base(session, model.provider_id)
                agent_configs[pa.agent_name] = AgentConfig(
                    model=pa.model_id,
                    api_base=api_base,
                    config=LLMConfig(
                        temperature=(
                            pa.temperature
                            if pa.temperature is not None
                            else getattr(yaml_base, pa.agent_name).config.temperature
                            if yaml_base is not None and pa.agent_name in _RUNTIME_ROLES
                            else 0.0
                        ),
                        max_tokens=(
                            pa.max_tokens
                            if pa.max_tokens is not None
                            else getattr(yaml_base, pa.agent_name).config.max_tokens
                            if yaml_base is not None and pa.agent_name in _RUNTIME_ROLES
                            else 4096
                        ),
                    ),
                )

    # Build profiles dict for the config
    all_profiles = session.exec(select(ProfileDB)).all()
    profiles_dict = {}
    for p in all_profiles:
        pas = session.exec(select(ProfileAgentDB).where(ProfileAgentDB.profile_id == p.id)).all()
        overrides = {}
        for pa in pas:
            overrides[pa.agent_name] = ProfileOverride(
                model=pa.model_id,
                temperature=pa.temperature,
                max_tokens=pa.max_tokens,
            )
        profiles_dict[p.id] = Profile(
            decision=overrides.get("decision"),
            local=overrides.get("local"),
            external=overrides.get("external"),
            description=p.description,
        )
    # Fill missing roles with YAML base config values.
    yaml_defaults = {role: getattr(yaml_base, role) for role in _RUNTIME_ROLES} if yaml_base is not None else {}

    for role in _RUNTIME_ROLES:
        if role in agent_configs:
            continue
        if role in yaml_defaults:
            agent_configs[role] = yaml_defaults[role]
            continue
        raise ValueError(f"Missing required model role: {role}")

    return PrivacyRouterConfig(
        models=model_specs,
        decision=agent_configs["decision"],
        local=agent_configs["local"],
        external=agent_configs["external"],
        profiles=profiles_dict,
        active_profile=profile_name,
    )


def seed_from_yaml(yaml_path: str | Path | None = None) -> None:
    """Bootstrap the shared database from YAML and close its session."""
    init_db()
    session = _get_session()
    try:
        _seed_from_yaml(session, yaml_path)
    finally:
        session.close()


def _seed_from_yaml(
    session: Session,
    yaml_path: str | Path | None = None,
) -> None:
    """Seed configuration rows using a caller-owned session."""
    yaml_config = load_yaml(yaml_path)

    # Seed providers
    provider_ids = set()
    for m in yaml_config.models:
        provider_id = m.id.split("/")[0] if "/" in m.id else "unknown"
        if provider_id not in provider_ids:
            provider = ProviderDB(
                id=provider_id,
                name=provider_id.title(),
                api_base=m.api_base,
            )
            session.merge(provider)
            provider_ids.add(provider_id)

    # Seed models
    for m in yaml_config.models:
        provider_id = m.id.split("/")[0] if "/" in m.id else "unknown"
        existing = session.exec(select(ModelDB).where(ModelDB.model_id == m.id)).first()
        if existing:
            existing.provider_id = provider_id
            existing.display_name = m.id.split("/")[-1]
            existing.location = m.location
            existing.tier = m.tier
            existing.cost_per_1m_tokens = m.cost_per_1m_tokens
            existing.api_base_override = m.api_base
            session.add(existing)
        else:
            model = ModelDB(
                model_id=m.id,
                provider_id=provider_id,
                display_name=m.id.split("/")[-1],
                location=m.location,
                tier=m.tier,
                cost_per_1m_tokens=m.cost_per_1m_tokens,
                api_base_override=m.api_base,
            )
            session.add(model)

    # Seed workspace
    workspace = WorkspaceDB(id="default", name="Default Workspace", active_profile="default")
    session.merge(workspace)

    # Seed profiles
    for name, profile in yaml_config.profiles.items():
        profile_db = ProfileDB(
            id=name,
            workspace_id="default",
            name=name.title(),
            description=profile.description,
            is_active=(name == "default"),
        )
        session.merge(profile_db)

        for agent_name in ("decision", "local", "external"):
            override = getattr(profile, agent_name, None)
            if override and override.model:
                existing_pa = session.exec(
                    select(ProfileAgentDB)
                    .where(ProfileAgentDB.profile_id == name)
                    .where(ProfileAgentDB.agent_name == agent_name)
                ).first()
                if existing_pa:
                    existing_pa.model_id = override.model
                    existing_pa.temperature = override.temperature
                    existing_pa.max_tokens = override.max_tokens
                    session.add(existing_pa)
                else:
                    pa = ProfileAgentDB(
                        profile_id=name,
                        agent_name=agent_name,
                        model_id=override.model,
                        temperature=override.temperature,
                        max_tokens=override.max_tokens,
                    )
                    session.add(pa)

    session.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_provider_api_base(session: Session, provider_id: str) -> str | None:
    """Get api_base from provider table."""
    provider = session.exec(select(ProviderDB).where(ProviderDB.id == provider_id)).first()
    return provider.api_base if provider else None


def _get_provider_key(session: Session, provider_id: str) -> str | None:
    """Resolve provider API key: DB encrypted → env fallback → None."""
    # Delayed to break the agents -> config.db_loader -> agents import cycle.
    from agents.masker.crypto import resolve_provider_key

    provider = session.exec(select(ProviderDB).where(ProviderDB.id == provider_id)).first()
    if not provider:
        return None
    return resolve_provider_key(provider.encrypted_api_key, provider.api_key_env)


def resolve_model_api_key(model_id: str) -> str | None:
    """Resolve the configured provider key for a registered model."""
    normalized_model_id = model_id.removeprefix("privacy-router/")
    try:
        session = get_session()
        try:
            model = session.exec(select(ModelDB).where(ModelDB.model_id == normalized_model_id)).first()
            provider_id = (
                model.provider_id
                if model is not None
                else normalized_model_id.split("/", 1)[0]
                if "/" in normalized_model_id
                else "openrouter"
            )
            return _get_provider_key(session, provider_id)
        finally:
            session.close()
    except Exception:
        return None
