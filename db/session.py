"""Database session management — SQLite for dev, PostgreSQL for production."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy
from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

import db.models  # noqa: F401 — register models with SQLModel.metadata

# Save env vars before load_dotenv (env takes precedence)
_env_db_url = os.environ.get("DATABASE_URL")

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = _env_db_url or os.getenv("DATABASE_URL", "sqlite:///privacy_router.db")

engine = create_engine(DATABASE_URL, echo=False)


def _migrate_db() -> None:
    """Add the essentiality flag to legacy masking-record tables."""
    inspector = sqlalchemy.inspect(engine)
    if "masking_records" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("masking_records")}
    if "is_essential" not in columns:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text("ALTER TABLE masking_records ADD COLUMN is_essential BOOLEAN NOT NULL DEFAULT false")
            )


def _migrate_model_tiers() -> None:
    """Map the retired edge tier to the supported small tier."""
    if "models" not in sqlalchemy.inspect(engine).get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("UPDATE models SET tier = 'small' WHERE tier = 'edge'"))


def _migrate_extraction_context() -> None:
    """Add encrypted session-context storage to an existing database."""
    inspector = sqlalchemy.inspect(engine)
    if "extraction_cache" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("extraction_cache")}
    if "context" not in columns:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("ALTER TABLE extraction_cache ADD COLUMN context TEXT"))


def _migrate_masking_session_owner() -> None:
    """Add the API-key owner binding to existing masking sessions."""
    inspector = sqlalchemy.inspect(engine)
    if "masking_sessions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("masking_sessions")}
    with engine.begin() as conn:
        if "owner_id" not in columns:
            conn.execute(sqlalchemy.text("ALTER TABLE masking_sessions ADD COLUMN owner_id VARCHAR"))
        conn.execute(
            sqlalchemy.text("CREATE INDEX IF NOT EXISTS ix_masking_sessions_owner_id ON masking_sessions (owner_id)")
        )


def _migrate_response_owner() -> None:
    """Add the API-key owner binding to stored Responses resources."""
    inspector = sqlalchemy.inspect(engine)
    if "responses" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("responses")}
    with engine.begin() as conn:
        if "owner_id" not in columns:
            conn.execute(sqlalchemy.text("ALTER TABLE responses ADD COLUMN owner_id VARCHAR"))
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS ix_responses_owner_id ON responses (owner_id)"))


def _migrate_response_storage() -> None:
    """Purge legacy plaintext responses and enforce encrypted, expiring storage."""
    inspector = sqlalchemy.inspect(engine)
    if "responses" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("responses")}
    legacy_or_partial = "output_text" in columns or "expires_at" not in columns or "storage_encrypted" not in columns
    if legacy_or_partial:
        # Commit the purge before DDL. A failed column migration may prevent
        # startup, but it cannot roll legacy plaintext back into service.
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("DELETE FROM responses"))

    timestamp_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    if "expires_at" not in columns:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f"ALTER TABLE responses ADD COLUMN expires_at {timestamp_type}"))
    if "storage_encrypted" not in columns:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text("ALTER TABLE responses ADD COLUMN storage_encrypted BOOLEAN NOT NULL DEFAULT false")
            )
    if "output_text" in columns:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("ALTER TABLE responses DROP COLUMN output_text"))

    # Reject partial/manual migrations that left plaintext or unbounded rows.
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM responses WHERE storage_encrypted IS NOT TRUE OR expires_at IS NULL"))
        conn.execute(sqlalchemy.text("CREATE INDEX IF NOT EXISTS ix_responses_expires_at ON responses (expires_at)"))


def purge_expired_data(*, now: datetime | None = None) -> dict[str, int]:
    """Physically delete expired raw-data containers in one transaction."""
    current = (now or datetime.now(UTC)).replace(tzinfo=None)
    cache_cutoff = current - timedelta(hours=24)
    counts = {
        "extraction_cache": 0,
        "masking_records": 0,
        "masking_sessions": 0,
        "responses": 0,
        "model_invocations": 0,
        "request_traces": 0,
    }

    with engine.begin() as conn:
        expired_session_ids = [
            row[0]
            for row in conn.execute(
                sqlalchemy.select(db.models.MaskingSession.id).where(
                    sqlalchemy.or_(
                        db.models.MaskingSession.expires_at.is_(None),
                        db.models.MaskingSession.expires_at <= current,
                    )
                )
            )
        ]
        if expired_session_ids:
            result = conn.execute(
                sqlalchemy.delete(db.models.MaskingRecord).where(
                    db.models.MaskingRecord.session_id.in_(expired_session_ids)
                )
            )
            counts["masking_records"] = result.rowcount or 0
            result = conn.execute(
                sqlalchemy.delete(db.models.MaskingSession).where(db.models.MaskingSession.id.in_(expired_session_ids))
            )
            counts["masking_sessions"] = result.rowcount or 0

        result = conn.execute(
            sqlalchemy.delete(db.models.ExtractionCache).where(db.models.ExtractionCache.updated_at <= cache_cutoff)
        )
        counts["extraction_cache"] = result.rowcount or 0
        expired_trace_ids = [
            row[0]
            for row in conn.execute(
                sqlalchemy.select(db.models.RequestTrace.id).where(db.models.RequestTrace.expires_at <= current)
            )
        ]
        if expired_trace_ids:
            result = conn.execute(
                sqlalchemy.delete(db.models.ModelInvocation).where(
                    db.models.ModelInvocation.request_id.in_(expired_trace_ids)
                )
            )
            counts["model_invocations"] = result.rowcount or 0
            result = conn.execute(
                sqlalchemy.delete(db.models.RequestTrace).where(db.models.RequestTrace.id.in_(expired_trace_ids))
            )
            counts["request_traces"] = result.rowcount or 0
        result = conn.execute(
            sqlalchemy.delete(db.models.Response).where(
                sqlalchemy.or_(
                    db.models.Response.expires_at.is_(None),
                    db.models.Response.expires_at <= current,
                )
            )
        )
        counts["responses"] = result.rowcount or 0

    return counts


def _migrate_legacy_extraction_cache() -> None:
    """Remove linkable legacy cache keys and plaintext-contract storage."""
    inspector = sqlalchemy.inspect(engine)
    if "extraction_cache" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("extraction_cache")}
    legacy_columns = columns & {"contract", "text_hash"}
    if not legacy_columns:
        return

    # Cache-key derivation changed to a domain-separated HMAC. Old keys and
    # plaintext fingerprints cannot be upgraded without the original input.
    # Purge in its own committed transaction. If later DDL fails, no legacy
    # fingerprint or plaintext contract can be restored by rollback.
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM extraction_cache"))
    if "text_hash" in legacy_columns:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("DROP INDEX IF EXISTS ix_extraction_cache_text_hash"))
    for column in sorted(legacy_columns):
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f"ALTER TABLE extraction_cache DROP COLUMN {column}"))


def _migrate_legacy_input_hashes() -> None:
    """Remove reversible-by-dictionary input fingerprints from metadata tables."""
    inspector = sqlalchemy.inspect(engine)
    tables = set(inspector.get_table_names())
    for table_name in ("masking_sessions", "usage_logs"):
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "input_hash" not in columns:
            continue
        # Commit the scrub before DDL so unsupported DROP COLUMN cannot restore
        # the legacy fingerprints.
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f"UPDATE {table_name} SET input_hash = ''"))
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f"ALTER TABLE {table_name} DROP COLUMN input_hash"))


def _migrate_legacy_provider_secrets() -> None:
    """Scrub and remove retired database-backed provider secret columns."""
    inspector = sqlalchemy.inspect(engine)
    if "provider" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("provider")}
    legacy_columns = columns & {"encrypted_api_key", "key_fingerprint"}
    if not legacy_columns:
        return

    # Commit the scrub before DDL. Even if an older database cannot drop a
    # column, no provider secret or derived fingerprint remains queryable.
    assignments = ", ".join(f"{column} = NULL" for column in sorted(legacy_columns))
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f"UPDATE provider SET {assignments}"))
    for column in sorted(legacy_columns):
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f"ALTER TABLE provider DROP COLUMN {column}"))


def _drop_legacy_agent_configs() -> None:
    """Drop the obsolete configuration table superseded by profile_agents."""
    if "agent_configs" not in sqlalchemy.inspect(engine).get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("DROP TABLE agent_configs"))


def _migrate_request_trace_redacted_input() -> None:
    """Add the safe-by-default request summary to existing trace tables."""
    inspector = sqlalchemy.inspect(engine)
    if "request_traces" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("request_traces")}
    if "input_redacted" in columns:
        return
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("ALTER TABLE request_traces ADD COLUMN input_redacted TEXT NOT NULL DEFAULT '{}'"))


def init_db() -> None:
    """Create all tables and apply lightweight backward-compatible migrations."""
    SQLModel.metadata.create_all(engine)
    _migrate_db()
    _migrate_model_tiers()
    _migrate_extraction_context()
    _migrate_legacy_extraction_cache()
    _migrate_legacy_input_hashes()
    _migrate_legacy_provider_secrets()
    _drop_legacy_agent_configs()
    _migrate_masking_session_owner()
    _migrate_response_owner()
    _migrate_response_storage()
    _migrate_request_trace_redacted_input()


def get_session() -> Session:
    """Get a new database session."""
    return Session(engine)
