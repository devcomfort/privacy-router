"""Database migration regression tests."""

from datetime import UTC, datetime, timedelta

import sqlalchemy
from sqlmodel import Session, create_engine, select

from db import (
    ExtractionCache,
    MaskingRecord,
    MaskingSession,
    Model,
    ModelInvocation,
    Provider,
    RequestTrace,
    Response,
    init_db,
    purge_expired_data,
)


def test_init_db_removes_legacy_plaintext_contract_column(tmp_path, monkeypatch):
    """Legacy cache contracts must not survive as plaintext storage."""
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    now = datetime.now(UTC).replace(tzinfo=None)
    with legacy_engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                """
                CREATE TABLE extraction_cache (
                    chat_id VARCHAR PRIMARY KEY,
                    text_hash VARCHAR NOT NULL,
                    extraction VARCHAR NOT NULL,
                    contract VARCHAR,
                    context VARCHAR,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO extraction_cache (
                    chat_id, text_hash, extraction, contract, context,
                    created_at, updated_at
                ) VALUES (
                    'chat-1', 'hash', '', 'PLAINTEXT_SECRET', NULL,
                    :created_at, :updated_at
                )
                """
            ),
            {"created_at": now, "updated_at": now},
        )

    monkeypatch.setattr("db.session.engine", legacy_engine)
    init_db()

    columns = {column["name"] for column in sqlalchemy.inspect(legacy_engine).get_columns("extraction_cache")}
    assert "contract" not in columns
    assert "text_hash" not in columns
    with legacy_engine.connect() as connection:
        stored = connection.execute(sqlalchemy.text("SELECT * FROM extraction_cache")).mappings().all()
    assert stored == []


def test_init_db_creates_fresh_cache_without_contract_column(tmp_path, monkeypatch):
    """New databases must never create legacy plaintext contract storage."""
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr("db.session.engine", fresh_engine)

    init_db()

    columns = {column["name"] for column in sqlalchemy.inspect(fresh_engine).get_columns("extraction_cache")}
    assert "contract" not in columns
    assert "text_hash" not in columns


def test_init_db_removes_legacy_input_fingerprints(tmp_path, monkeypatch):
    """Dictionary-attackable input hashes must be scrubbed and dropped."""
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'input-hashes.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            sqlalchemy.text("CREATE TABLE usage_logs (id VARCHAR PRIMARY KEY, input_hash VARCHAR NOT NULL)")
        )
        connection.execute(
            sqlalchemy.text("CREATE TABLE masking_sessions (id VARCHAR PRIMARY KEY, input_hash VARCHAR NOT NULL)")
        )
        connection.execute(sqlalchemy.text("INSERT INTO usage_logs VALUES ('usage-1', 'RAW_SHA256')"))
        connection.execute(sqlalchemy.text("INSERT INTO masking_sessions VALUES ('session-1', 'RAW_SHA256')"))

    monkeypatch.setattr("db.session.engine", legacy_engine)
    init_db()

    inspector = sqlalchemy.inspect(legacy_engine)
    assert "input_hash" not in {column["name"] for column in inspector.get_columns("usage_logs")}
    assert "input_hash" not in {column["name"] for column in inspector.get_columns("masking_sessions")}


def test_init_db_scrubs_and_drops_legacy_provider_secret_columns(tmp_path, monkeypatch):
    """Provider secrets and fingerprints must not remain in the configuration database."""
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'provider-secrets.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                """
                CREATE TABLE provider (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    api_base VARCHAR,
                    api_key_env VARCHAR,
                    encrypted_api_key VARCHAR,
                    key_fingerprint VARCHAR,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO provider (
                    id, name, api_key_env, encrypted_api_key, key_fingerprint
                ) VALUES (
                    'legacy', 'Legacy provider', 'OPENROUTER_API_KEY',
                    'LEGACY_ENCRYPTED_SECRET', 'LEGACY_KEY_FINGERPRINT'
                )
                """
            )
        )

    monkeypatch.setattr("db.session.engine", legacy_engine)
    init_db()

    columns = {column["name"] for column in sqlalchemy.inspect(legacy_engine).get_columns("provider")}
    assert "encrypted_api_key" not in columns
    assert "key_fingerprint" not in columns
    with legacy_engine.connect() as connection:
        stored = (
            connection.execute(sqlalchemy.text("SELECT id, api_key_env FROM provider WHERE id = 'legacy'"))
            .mappings()
            .one()
        )
    assert dict(stored) == {
        "id": "legacy",
        "api_key_env": "OPENROUTER_API_KEY",
    }


def test_init_db_purges_legacy_plaintext_responses(tmp_path, monkeypatch):
    """Legacy response bodies are transient and cannot remain plaintext."""
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'responses.db'}")
    now = datetime.now(UTC).replace(tzinfo=None)
    with legacy_engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                """
                CREATE TABLE responses (
                    id VARCHAR PRIMARY KEY,
                    model VARCHAR NOT NULL,
                    output_text VARCHAR NOT NULL,
                    output_json VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO responses (
                    id, model, output_text, output_json, status, created_at
                ) VALUES (
                    'response-1', 'model', 'PLAINTEXT_SECRET',
                    '{"input":"PLAINTEXT_SECRET"}', 'completed', :created_at
                )
                """
            ),
            {"created_at": now},
        )

    monkeypatch.setattr("db.session.engine", legacy_engine)
    init_db()

    columns = {column["name"] for column in sqlalchemy.inspect(legacy_engine).get_columns("responses")}
    assert "output_text" not in columns
    assert {"expires_at", "storage_encrypted"} <= columns
    with legacy_engine.connect() as connection:
        stored = connection.execute(sqlalchemy.text("SELECT * FROM responses")).mappings().all()
    assert stored == []


def test_init_db_migrates_legacy_edge_model_tier(tmp_path, monkeypatch):
    """The retired edge tier maps to the supported small tier."""
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'model-tier.db'}")
    monkeypatch.setattr("db.session.engine", legacy_engine)
    init_db()
    with Session(legacy_engine) as session:
        session.add(Provider(id="legacy", name="Legacy"))
        session.add(
            Model(
                model_id="legacy/edge-model",
                provider_id="legacy",
                tier="edge",
            )
        )
        session.commit()

    init_db()

    with Session(legacy_engine) as session:
        model = session.exec(select(Model).where(Model.model_id == "legacy/edge-model")).one()
        assert model.tier == "small"


def test_purge_expired_data_removes_raw_rows_and_keeps_live_rows(tmp_path, monkeypatch):
    """The application retention job removes every expired raw-data container."""
    retention_engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}")
    monkeypatch.setattr("db.session.engine", retention_engine)
    init_db()

    now = datetime.now(UTC).replace(tzinfo=None)
    expired_at = now - timedelta(seconds=1)
    old_cache_time = now - timedelta(hours=24, seconds=1)
    live_at = now + timedelta(hours=1)
    with Session(retention_engine) as session:
        expired_session = MaskingSession(
            id="expired-session",
            record_count=1,
            expires_at=expired_at,
        )
        session.add(expired_session)
        session.add(
            MaskingRecord(
                session_id=expired_session.id,
                uid="deadbeef",
                category="SECRET",
                placeholder="SECRET#deadbeef",
                value_hash="fingerprint",
                span="ciphertext",
            )
        )
        session.add(
            ExtractionCache(
                chat_id="expired-cache",
                extraction="ciphertext",
                updated_at=old_cache_time,
            )
        )
        session.add(
            Response(
                id="expired-response",
                model="model",
                owner_id="owner",
                output_json="ciphertext",
                expires_at=expired_at,
            )
        )
        session.add(
            Response(
                id="live-response",
                model="model",
                owner_id="owner",
                output_json="ciphertext",
                expires_at=live_at,
            )
        )
        session.add(
            RequestTrace(
                id="expired-trace",
                endpoint="responses",
                input_encrypted="ciphertext",
                expires_at=expired_at,
            )
        )
        session.add(
            ModelInvocation(
                id="expired-invocation",
                request_id="expired-trace",
                component="extractor",
                model="openrouter/model",
            )
        )
        session.add(
            RequestTrace(
                id="live-trace",
                endpoint="chat_completions",
                input_encrypted="ciphertext",
                expires_at=live_at,
            )
        )
        session.add(
            ModelInvocation(
                id="live-invocation",
                request_id="live-trace",
                component="generator",
                model="openrouter/model",
            )
        )
        session.commit()

    removed = purge_expired_data(now=now)

    assert removed == {
        "extraction_cache": 1,
        "masking_records": 1,
        "masking_sessions": 1,
        "responses": 1,
        "model_invocations": 1,
        "request_traces": 1,
    }
    with Session(retention_engine) as session:
        assert session.get(MaskingSession, "expired-session") is None
        assert session.exec(select(MaskingRecord).where(MaskingRecord.session_id == "expired-session")).all() == []
        assert session.get(ExtractionCache, "expired-cache") is None
        assert session.get(Response, "expired-response") is None
        assert session.get(RequestTrace, "expired-trace") is None
        assert session.get(ModelInvocation, "expired-invocation") is None
        assert session.get(RequestTrace, "live-trace") is not None
        assert session.get(ModelInvocation, "live-invocation") is not None
        assert session.get(Response, "live-response") is not None


def test_migrate_legacy_masking_requiredness_columns(tmp_path, monkeypatch):
    """Legacy essentiality values migrate to nested requiredness storage."""
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'masking-requiredness.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                """
                CREATE TABLE masking_records (
                    id VARCHAR PRIMARY KEY,
                    session_id VARCHAR NOT NULL,
                    uid VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    placeholder VARCHAR NOT NULL,
                    value_hash VARCHAR NOT NULL,
                    span VARCHAR NOT NULL,
                    confidence FLOAT NOT NULL DEFAULT 0,
                    is_essential BOOLEAN NOT NULL DEFAULT false
                )
                """
            )
        )
        connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO masking_records (
                    id, session_id, uid, category, placeholder,
                    value_hash, span, confidence, is_essential
                ) VALUES (
                    'record-1', 'session-1', 'uid-1', 'EMAIL_ADDRESS',
                    'EMAIL_ADDRESS#uid-1', 'hash', 'encrypted', 0.95, true
                )
                """
            )
        )

    monkeypatch.setattr("db.session.engine", legacy_engine)
    from db.session import _migrate_db

    _migrate_db()

    columns = {column["name"] for column in sqlalchemy.inspect(legacy_engine).get_columns("masking_records")}
    assert "is_required" not in columns
    assert "is_required_value" in columns
    assert "is_required_reason" in columns
    with legacy_engine.connect() as connection:
        row = connection.execute(
            sqlalchemy.text("SELECT is_required_value, is_required_reason FROM masking_records WHERE id = 'record-1'")
        ).one()
    assert row.is_required_value in (True, 1)
    assert row.is_required_reason == "migrated from legacy essentiality flag"
