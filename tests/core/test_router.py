"""Deterministic unit tests for Router, PrivacyRouter, and runtime config."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import MagicMock

import pytest

from agents import ExtractionRecord, ExtractionResult, Sensitivity
from agents.router import PrivacyRouter, Router, get_cache
from config import load_config, resolve_model
from db import ExtractionCache, get_session, init_db

init_db()


def _expire_cache_entry(chat_id: str) -> None:
    with get_session() as session:
        entry = session.get(ExtractionCache, chat_id)
        assert entry is not None
        entry.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
        session.add(entry)
        session.commit()


def test_cache_round_trips_encrypted_session_context():
    chat_id = f"context-test-{uuid.uuid4().hex}"
    cache = get_cache()
    context = [
        {"label": "message[0].content", "text": "Project Aurora is confidential"},
        {"label": "message[1].content", "text": "Can I send it?"},
    ]

    try:
        cache.put_context(chat_id, context)

        assert cache.get_context(chat_id) == context
        with get_session() as session:
            entry = session.get(ExtractionCache, chat_id)
            assert entry is not None
            assert entry.context is not None
            assert "Project Aurora" not in entry.context
    finally:
        cache.delete(chat_id)


def test_cache_atomically_merges_concurrent_session_deltas():
    chat_id = f"context-merge-test-{uuid.uuid4().hex}"
    cache = get_cache()
    barrier = Barrier(2)

    def merge(previous, current):
        known = {(segment["label"], segment["text"]) for segment in previous}
        return previous + [segment for segment in current if (segment["label"], segment["text"]) not in known]

    def persist(label: str, text: str) -> None:
        barrier.wait()
        cache.merge_context(
            chat_id,
            [{"label": label, "text": text}],
            merge,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(persist, "message[0].content", "FIRST_TURN"),
                pool.submit(persist, "message[1].content", "SECOND_TURN"),
            ]
            for future in futures:
                future.result()

        assert {segment["text"] for segment in cache.get_context(chat_id)} == {
            "FIRST_TURN",
            "SECOND_TURN",
        }
    finally:
        cache.delete(chat_id)


def test_cache_discards_expired_extraction():
    chat_id = f"expired-extraction-{uuid.uuid4().hex}"
    cache = get_cache()
    try:
        cache.put_extraction(chat_id, {"result": "private text"})
        _expire_cache_entry(chat_id)

        assert cache.get_extraction(chat_id) is None
        with get_session() as session:
            assert session.get(ExtractionCache, chat_id) is None
    finally:
        cache.delete(chat_id)


def test_cache_discards_expired_context():
    chat_id = f"expired-context-{uuid.uuid4().hex}"
    cache = get_cache()
    try:
        cache.put_context(chat_id, [{"label": "message[0]", "text": "OLD_SECRET"}])
        _expire_cache_entry(chat_id)

        assert cache.get_context(chat_id) == []
        with get_session() as session:
            assert session.get(ExtractionCache, chat_id) is None
    finally:
        cache.delete(chat_id)


def test_cache_merge_does_not_revive_expired_context():
    chat_id = f"expired-merge-{uuid.uuid4().hex}"
    cache = get_cache()
    try:
        cache.put_context(chat_id, [{"label": "message[0]", "text": "OLD_SECRET"}])
        _expire_cache_entry(chat_id)

        cache.merge_context(
            chat_id,
            [{"label": "message[1]", "text": "NEW_CONTEXT"}],
            lambda previous, current: [*previous, *current],
        )

        assert cache.get_context(chat_id) == [{"label": "message[1]", "text": "NEW_CONTEXT"}]
    finally:
        cache.delete(chat_id)


def test_cache_put_extraction_does_not_revive_expired_context():
    chat_id = f"expired-put-extraction-{uuid.uuid4().hex}"
    cache = get_cache()
    try:
        cache.put_context(chat_id, [{"label": "message[0]", "text": "OLD_SECRET"}])
        _expire_cache_entry(chat_id)

        cache.put_extraction(chat_id, {"result": "new"})

        assert cache.get_context(chat_id) == []
        assert cache.get_extraction(chat_id) == {"result": "new"}
    finally:
        cache.delete(chat_id)


def test_cache_put_context_does_not_revive_expired_extraction():
    chat_id = f"expired-put-context-{uuid.uuid4().hex}"
    cache = get_cache()
    try:
        cache.put_extraction(chat_id, {"result": "OLD_SECRET"})
        _expire_cache_entry(chat_id)

        cache.put_context(chat_id, [{"label": "message[0]", "text": "NEW_CONTEXT"}])

        assert cache.get_extraction(chat_id) is None
        assert cache.get_context(chat_id) == [{"label": "message[0]", "text": "NEW_CONTEXT"}]
    finally:
        cache.delete(chat_id)


class TestRouterResolve:
    """Test Router.resolve() — policy_action → RouteResult mapping."""

    def test_allow(self):
        router = Router()
        result = router.resolve("allow")
        assert result.endpoint == "external_api"
        assert result.requires_masking is False

    def test_selective_mask(self):
        router = Router()
        result = router.resolve("selective_mask")
        assert result.endpoint == "external_api"
        assert result.requires_masking is True

    def test_unknown_action_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="Unknown policy_action"):
            router.resolve("nonexistent")


class TestPrivacyRouterProcess:
    """Test the full deterministic pipeline with mocked Decision Model output."""

    @staticmethod
    def _process(monkeypatch, text: str, extraction: ExtractionResult):
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = extraction
        monkeypatch.setattr("agents.router.router.Extractor", mock_cls)
        return PrivacyRouter().process(text)

    def test_non_sensitive(self, monkeypatch):
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean"),
            records=[],
        )
        result = self._process(monkeypatch, "오늘 서울 날씨는 맑습니다", extraction)
        assert result.sensitivity.is_sensitive is False
        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is False
        assert result.judgment.policy_action == "allow"
        assert result.records == []

    def test_sensitive_pii_essential(self, monkeypatch):
        """An essential PII target uses the canonical block action."""
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="PII target"),
            records=[
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="주민등록번호",
                    confidence=0.99,
                    start=2,
                    end=9,
                    is_essential=True,
                )
            ],
        )
        result = self._process(monkeypatch, "내 주민등록번호가 뭐야?", extraction)
        assert result.sensitivity.is_sensitive is True
        assert any(record.is_essential for record in result.records)
        assert result.judgment.policy_action == "block"
        assert result.route.endpoint == "local_api"

    def test_sensitive_pii_maskable(self, monkeypatch):
        """A maskable PII context uses the canonical selective_mask action."""
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="PII context"),
            records=[
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.99,
                    start=7,
                    end=21,
                    is_essential=False,
                )
            ],
        )
        result = self._process(
            monkeypatch,
            "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘",
            extraction,
        )
        assert result.sensitivity.is_sensitive is True
        assert result.judgment.policy_action == "selective_mask"
        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is True

    def test_business_secret(self, monkeypatch):
        """A non-essential business secret is maskable."""
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="business secret"),
            records=[
                ExtractionRecord(
                    category="FABRICATION_PROCESS_DECISION",
                    span="TSMC 3nm 공정",
                    confidence=0.95,
                    start=0,
                    end=11,
                    is_essential=False,
                )
            ],
        )
        result = self._process(
            monkeypatch,
            "TSMC 3nm 공정을 채택하기로 결정했다",
            extraction,
        )
        assert result.sensitivity.is_sensitive is True
        assert result.judgment.policy_action == "selective_mask"

    def test_config_model_used(self):
        """PrivacyRouter uses the configured Decision Model."""
        pr = PrivacyRouter()
        cfg = load_config()
        assert pr._decision_model == cfg.decision.model


class TestConfigResolution:
    """Test that config properly resolves model specs."""

    def test_config_loads(self):
        from config import load_config

        cfg = load_config()
        assert cfg is not None
        assert len(cfg.models) > 0

    def test_decision_model_exists(self):
        from config import load_config

        cfg = load_config()
        spec = resolve_model(cfg, cfg.decision.model)
        assert spec is not None
        assert spec.id == cfg.decision.model
        assert spec.location == "local"

    def test_external_model_exists(self):
        from config import load_config

        cfg = load_config()
        spec = resolve_model(cfg, cfg.external.model)
        assert spec is not None
        assert spec.location == "external"

    def test_all_models_resolvable(self):
        from config import load_config

        cfg = load_config()
        for model in cfg.models:
            spec = resolve_model(cfg, model.id)
            assert spec is not None, f"Model {model.id} not resolvable"

    def test_resolve_model_not_found_raises(self):
        from config import load_config

        cfg = load_config()
        with pytest.raises(KeyError, match="not found in config.models"):
            resolve_model(cfg, "nonexistent/model")


class TestConfigEnvInterpolation:
    """Test env var interpolation in config loader."""

    def test_resolve_env_var_present(self, monkeypatch):
        from config.loader import _resolve_env_vars

        monkeypatch.setenv("TEST_SECRET", "hello123")
        result = _resolve_env_vars({"key": "${TEST_SECRET}"})
        assert result == {"key": "hello123"}

    def test_resolve_env_var_with_default(self, monkeypatch):
        from config.loader import _resolve_env_vars

        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = _resolve_env_vars({"key": "${MISSING_VAR:fallback_value}"})
        assert result == {"key": "fallback_value"}

    def test_resolve_env_var_no_default_keeps_placeholder(self, monkeypatch):
        from config.loader import _resolve_env_vars

        monkeypatch.delenv("TOTALLY_MISSING", raising=False)
        result = _resolve_env_vars({"key": "${TOTALLY_MISSING}"})
        assert result == {"key": "${TOTALLY_MISSING}"}

    def test_resolve_nested_dict(self, monkeypatch):
        from config.loader import _resolve_env_vars

        monkeypatch.setenv("MY_KEY", "resolved")
        data = {"outer": {"inner": "${MY_KEY}"}, "list": ["${MY_KEY}", "plain"]}
        result = _resolve_env_vars(data)
        assert result == {"outer": {"inner": "resolved"}, "list": ["resolved", "plain"]}

    def test_resolve_non_string_passthrough(self):
        from config.loader import _resolve_env_vars

        data = {"num": 42, "flag": True, "nothing": None}
        result = _resolve_env_vars(data)
        assert result == {"num": 42, "flag": True, "nothing": None}

    def test_resolve_list_of_dicts(self, monkeypatch):
        from config.loader import _resolve_env_vars

        monkeypatch.setenv("API_KEY", "sk-test-123")
        data = [{"api_key": "${API_KEY}"}, {"other": "value"}]
        result = _resolve_env_vars(data)
        assert result == [{"api_key": "sk-test-123"}, {"other": "value"}]

    def test_resolve_multiple_vars_in_one_string(self, monkeypatch):
        from config.loader import _resolve_env_vars

        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        result = _resolve_env_vars({"url": "http://${HOST}:${PORT}/api"})
        assert result == {"url": "http://localhost:8080/api"}

    def test_resolve_empty_string(self):
        from config.loader import _resolve_env_vars

        result = _resolve_env_vars({"key": ""})
        assert result == {"key": ""}


class TestConfigMissingFile:
    """Test config loader error handling."""

    def test_missing_config_file_raises(self):
        from config.loader import load_config

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config("/nonexistent/path/config.yaml")

    def test_read_yaml_non_dict_raises(self, tmp_path):
        from config.loader import _read_yaml

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must contain a YAML mapping"):
            _read_yaml(bad_yaml)

    def test_load_config_with_env_vars_in_yaml(self, tmp_path, monkeypatch):
        """End-to-end: config file with env vars gets resolved."""
        from config.loader import load_config

        monkeypatch.setenv("PR_MODEL_ID", "openrouter/test/model")
        config_content = """
models:
  - id: openai/local-analysis
    api_base: http://127.0.0.1:8000/v1
    location: local
    tier: small
    cost_per_1m_tokens: 0.0
  - id: ${PR_MODEL_ID}
    location: external
    tier: small
    cost_per_1m_tokens: 0.10

decision:
  model: openai/local-analysis
  config:
    temperature: 0.0
    max_tokens: 4096

local:
  model: openai/local-analysis
  config:
    temperature: 0.7
    max_tokens: 512

external:
  model: ${PR_MODEL_ID}
  config:
    temperature: 0.7
    max_tokens: 512
"""
        config_file = tmp_path / "test-config.yaml"
        config_file.write_text(config_content)
        cfg = load_config(config_file)
        assert cfg.external.model == "openrouter/test/model"
        assert cfg.decision.model == "openai/local-analysis"

    def test_load_config_with_defaults_in_yaml(self, tmp_path, monkeypatch):
        """Config with env var defaults when vars are unset."""
        from config.loader import load_config

        monkeypatch.delenv("PR_FALLBACK_MODEL", raising=False)
        config_content = """
models:
  - id: openai/local-analysis
    api_base: http://127.0.0.1:8000/v1
    location: local
    tier: small
    cost_per_1m_tokens: 0.0
  - id: ${PR_FALLBACK_MODEL:openrouter/fallback/model}
    location: external
    tier: small
    cost_per_1m_tokens: 0.10

decision:
  model: openai/local-analysis
  config:
    temperature: 0.0
    max_tokens: 4096

local:
  model: openai/local-analysis
  config:
    temperature: 0.7
    max_tokens: 512

external:
  model: ${PR_FALLBACK_MODEL:openrouter/fallback/model}
  config:
    temperature: 0.7
    max_tokens: 512
"""
        config_file = tmp_path / "test-config.yaml"
        config_file.write_text(config_content)
        cfg = load_config(config_file)
        assert cfg.external.model == "openrouter/fallback/model"
