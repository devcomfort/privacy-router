"""Role and trust-boundary contracts for configured models."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

import config as config_package
from agents import Critic, ExtractorCore
from config import (
    load_config,
    load_config_from_yaml,
    resolve_api_base,
    resolve_generation_binding,
    resolve_model,
)
from db import Model, Profile, ProfileAgent, Provider, Workspace
from db import engine as shared_db_engine

VALID_CONFIG = """
models:
  - id: openai/LGAI-EXAONE/EXAONE-4.0-1.2B
    api_base: http://127.0.0.1:8000/v1
    location: local
    tier: small
    cost_per_1m_tokens: 0.0
  - id: openai/google/gemma-4-26b-local
    api_base: http://127.0.0.1:8001/v1
    location: local
    tier: middle
    cost_per_1m_tokens: 0.0
  - id: openrouter/google/gemma-4-26b-it
    location: external
    tier: middle
    cost_per_1m_tokens: 0.06
decision:
  model: openai/LGAI-EXAONE/EXAONE-4.0-1.2B
  config: {temperature: 0.0, max_tokens: 4096}
local:
  model: openai/google/gemma-4-26b-local
  config: {temperature: 0.7, max_tokens: 512}
external:
  model: openrouter/google/gemma-4-26b-it
  config: {temperature: 0.7, max_tokens: 512}
profiles:
  default:
    description: Three explicit runtime roles
    decision: {model: openai/LGAI-EXAONE/EXAONE-4.0-1.2B}
    local: {model: openai/google/gemma-4-26b-local}
    external: {model: openrouter/google/gemma-4-26b-it}
"""


def _write_config(tmp_path: Path, text: str = VALID_CONFIG) -> Path:
    path = tmp_path / "router.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_exactly_three_runtime_roles(tmp_path: Path) -> None:
    cfg = load_config_from_yaml(_write_config(tmp_path))

    assert cfg.decision.model == "openai/LGAI-EXAONE/EXAONE-4.0-1.2B"
    assert cfg.local.model == "openai/google/gemma-4-26b-local"
    assert cfg.external.model == "openrouter/google/gemma-4-26b-it"
    assert not hasattr(cfg, "extractor")
    assert not hasattr(cfg, "judge")
    assert not hasattr(cfg, "generator")


def test_repository_default_uses_available_external_model() -> None:
    cfg = load_config_from_yaml(Path(__file__).resolve().parents[2] / ".privacy-router.config.yaml")

    assert cfg.external.model == "openrouter/google/gemma-4-26b-a4b-it"


def test_extractor_components_default_to_decision_binding() -> None:
    cfg = load_config()
    core = ExtractorCore()
    critic = Critic()

    assert core._model == cfg.decision.model
    assert core._api_base == resolve_model(cfg, cfg.decision.model).api_base
    assert critic._model == cfg.decision.model
    assert critic._api_base == resolve_model(cfg, cfg.decision.model).api_base
    assert core._max_tokens == cfg.decision.config.max_tokens
    assert critic._max_tokens == cfg.decision.config.max_tokens


def test_repository_example_config_validates() -> None:
    config_path = Path(__file__).resolve().parents[2] / ".privacy-router.config.yaml.example"
    config = load_config_from_yaml(config_path)

    assert config.decision.model == "openai/LGAI-EXAONE/EXAONE-4.0-1.2B"
    assert config.local.model == "openai/google/gemma-4-26b-local"
    assert config.external.model == "openrouter/google/gemma-4-26b-a4b-it"


def test_mcp_generation_binding_keeps_local_endpoint(tmp_path: Path) -> None:

    cfg = load_config_from_yaml(_write_config(tmp_path))

    model, params, api_base = resolve_generation_binding(cfg, "block", None)

    assert model == "openai/google/gemma-4-26b-local"
    assert params == {"temperature": 0.7, "max_tokens": 512}
    assert api_base == "http://127.0.0.1:8001/v1"


def test_mcp_generation_binding_keeps_external_endpoint(tmp_path: Path) -> None:

    cfg = load_config_from_yaml(_write_config(tmp_path))

    model, params, api_base = resolve_generation_binding(cfg, "allow", None)

    assert model == "openrouter/google/gemma-4-26b-it"
    assert params == {"temperature": 0.7, "max_tokens": 512}
    assert api_base is None


def test_generation_binding_rejects_local_external_override(tmp_path: Path) -> None:
    cfg = load_config_from_yaml(_write_config(tmp_path))

    with pytest.raises(ValueError, match="external model"):
        resolve_generation_binding(
            cfg,
            "selective_mask",
            "openai/google/gemma-4-26b-local",
        )


def test_generation_binding_uses_registered_external_override_endpoint(
    tmp_path: Path,
) -> None:
    override = """
  - id: openrouter/alternate
    api_base: https://alternate.example/v1
    location: external
    tier: middle
    cost_per_1m_tokens: 0.1
"""
    config_text = VALID_CONFIG.replace(
        "decision:",
        f"{override}decision:",
        1,
    )
    cfg = load_config_from_yaml(_write_config(tmp_path, config_text))

    model, params, api_base = resolve_generation_binding(
        cfg,
        "allow",
        "openrouter/alternate",
    )

    assert model == "openrouter/alternate"
    assert params == {"temperature": 0.7, "max_tokens": 512}
    assert api_base == "https://alternate.example/v1"


@pytest.mark.parametrize(
    ("role", "model"),
    [
        ("decision", "openrouter/google/gemma-4-26b-it"),
        ("local", "openrouter/google/gemma-4-26b-it"),
        ("external", "openai/google/gemma-4-26b-local"),
    ],
)
def test_rejects_role_location_mismatch(tmp_path: Path, role: str, model: str) -> None:
    text = VALID_CONFIG.replace(
        f"{role}:\n  model: "
        + {
            "decision": "openai/LGAI-EXAONE/EXAONE-4.0-1.2B",
            "local": "openai/google/gemma-4-26b-local",
            "external": "openrouter/google/gemma-4-26b-it",
        }[role],
        f"{role}:\n  model: {model}",
        1,
    )

    with pytest.raises(ValidationError, match=f"{role} model must be"):
        load_config_from_yaml(_write_config(tmp_path, text))


def test_rejects_unregistered_role_model(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace(
        "model: openai/LGAI-EXAONE/EXAONE-4.0-1.2B",
        "model: openai/missing-model",
        1,
    )

    with pytest.raises(ValidationError, match="not registered"):
        load_config_from_yaml(_write_config(tmp_path, text))


def test_rejects_duplicate_model_ids(tmp_path: Path) -> None:
    duplicate = """
  - id: openai/google/gemma-4-26b-local
    api_base: http://127.0.0.1:8999/v1
    location: external
    tier: middle
    cost_per_1m_tokens: 0.0
"""
    text = VALID_CONFIG.replace("decision:", f"{duplicate}decision:", 1)

    with pytest.raises(ValidationError, match="Duplicate model id"):
        load_config_from_yaml(_write_config(tmp_path, text))


@pytest.mark.parametrize(
    "api_base",
    [
        "https://models.example.com/v1",
        "http://10.0.0.8:8000/v1",
        "http://0.0.0.0:8000/v1",
        "http://host.docker.internal:8000/v1",
    ],
)
def test_rejects_non_loopback_local_model_endpoint(tmp_path: Path, api_base: str) -> None:
    text = VALID_CONFIG.replace("http://127.0.0.1:8000/v1", api_base, 1)

    with pytest.raises(ValidationError, match="loopback"):
        load_config_from_yaml(_write_config(tmp_path, text))


def test_rejects_missing_endpoint_for_openai_compatible_local_model(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace("    api_base: http://127.0.0.1:8000/v1\n", "", 1)

    with pytest.raises(ValidationError, match="requires a loopback api_base"):
        load_config_from_yaml(_write_config(tmp_path, text))


def test_allows_native_ollama_local_model_without_api_base(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace(
        "openai/LGAI-EXAONE/EXAONE-4.0-1.2B",
        "ollama/exaone:1.2b",
    ).replace("    api_base: http://127.0.0.1:8000/v1\n", "", 1)

    cfg = load_config_from_yaml(_write_config(tmp_path, text))

    assert resolve_api_base(cfg, "ollama/exaone:1.2b") == "http://127.0.0.1:11434"


def test_runtime_resolution_rejects_unsafe_local_override(tmp_path: Path) -> None:
    cfg = load_config_from_yaml(_write_config(tmp_path))

    with pytest.raises(ValueError, match="loopback"):
        resolve_api_base(
            cfg,
            "openai/google/gemma-4-26b-local",
            "https://models.example.com/v1",
        )


def test_profile_model_override_does_not_inherit_previous_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alternate = """
  - id: openai/local-alternate
    api_base: http://127.0.0.1:8111/v1
    location: local
    tier: small
    cost_per_1m_tokens: 0.0
"""
    text = VALID_CONFIG.replace("decision:", f"{alternate}decision:", 1)
    text = text.replace(
        "local:\n  model: openai/google/gemma-4-26b-local",
        "local:\n  model: openai/google/gemma-4-26b-local\n  api_base: http://127.0.0.1:8999/v1",
        1,
    )
    text = text.replace(
        "local: {model: openai/google/gemma-4-26b-local}",
        "local: {model: openai/local-alternate}",
        1,
    )
    monkeypatch.setenv("PRIVACY_ROUTER_PROFILE", "default")

    cfg = load_config_from_yaml(_write_config(tmp_path, text))

    assert cfg.local.model == "openai/local-alternate"
    assert cfg.local.api_base is None
    assert resolve_api_base(cfg, cfg.local.model) == "http://127.0.0.1:8111/v1"


def test_db_sync_migrates_legacy_roles_and_selected_models(tmp_path: Path) -> None:
    from config.db_loader import _sync_runtime_schema

    cfg = load_config_from_yaml(_write_config(tmp_path))
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Provider(id="openrouter", name="OpenRouter"))
        session.add(
            Model(
                model_id="openrouter/google/gemma-4-26b-it",
                provider_id="openrouter",
                location="external",
                tier="middle",
                cost_per_1m_tokens=0.06,
            )
        )
        session.add(Workspace(id="default", name="Default", active_profile="default"))
        session.add(
            Profile(
                id="default",
                workspace_id="default",
                name="Default",
                description="Legacy profile",
                is_active=True,
            )
        )
        session.add(
            ProfileAgent(
                profile_id="default",
                agent_name="extractor",
                model_id="openrouter/google/gemma-4-26b-it",
            )
        )
        session.commit()

        _sync_runtime_schema(session, cfg)

        roles = {row.agent_name: row.model_id for row in session.exec(select(ProfileAgent)).all()}
        models = {row.model_id: row.location for row in session.exec(select(Model)).all()}

    assert roles == {
        "decision": "openai/LGAI-EXAONE/EXAONE-4.0-1.2B",
        "local": "openai/google/gemma-4-26b-local",
        "external": "openrouter/google/gemma-4-26b-it",
    }
    assert models["openai/LGAI-EXAONE/EXAONE-4.0-1.2B"] == "local"
    assert models["openai/google/gemma-4-26b-local"] == "local"


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("database unavailable"),
        ValueError("invalid local endpoint"),
    ],
)
def test_public_loader_propagates_db_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def fail_to_load_from_db():
        raise error

    monkeypatch.setattr(config_package, "load_config_from_db", fail_to_load_from_db)

    with pytest.raises(type(error), match=str(error)):
        config_package.load_config()


def test_db_loader_uses_shared_database_engine() -> None:
    from config import db_loader

    session = db_loader._get_session()
    try:
        assert session.bind is shared_db_engine
    finally:
        session.close()


def test_db_loader_closes_session_when_database_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import db_loader

    session = MagicMock()
    session.exec.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(db_loader, "_get_session", lambda: session)
    monkeypatch.setattr(db_loader, "init_db", lambda: None)

    with pytest.raises(RuntimeError, match="database unavailable"):
        db_loader.load_config_from_db()

    session.close.assert_called_once_with()


def test_public_yaml_seed_uses_shared_initialization_and_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import db_loader

    test_engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    yaml_config = load_config_from_yaml(_write_config(tmp_path))
    opened_sessions: list[Session] = []

    def open_test_session() -> Session:
        session = Session(test_engine)
        opened_sessions.append(session)
        return session

    monkeypatch.setattr("db.session.engine", test_engine)
    monkeypatch.setattr(db_loader, "_get_session", open_test_session)
    monkeypatch.setattr(db_loader, "load_yaml", lambda _path=None: yaml_config)

    db_loader.seed_from_yaml()

    assert len(opened_sessions) == 1
    with Session(test_engine) as session:
        assert session.get(Workspace, "default") is not None


def test_fresh_database_bootstrap_uses_one_shared_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import db_loader

    test_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    yaml_config = load_config_from_yaml(_write_config(tmp_path))
    opened_sessions: list[Session] = []

    def open_test_session() -> Session:
        session = Session(test_engine)
        opened_sessions.append(session)
        return session

    monkeypatch.setattr("db.session.engine", test_engine)
    monkeypatch.setattr(db_loader, "_get_session", open_test_session)
    monkeypatch.setattr(db_loader, "load_yaml", lambda _path=None: yaml_config)

    config = db_loader.load_config_from_db()

    assert len(opened_sessions) == 1
    assert config.active_profile == "default"
    assert config.decision.model == "openai/LGAI-EXAONE/EXAONE-4.0-1.2B"
