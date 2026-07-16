"""Database models — SQLModel ORM for PostgreSQL/SQLite.

Tables:
    - provider, models, workspaces, profiles, profile_agents: runtime configuration
    - api_keys: authentication keys
    - usage_logs, responses: request metadata and stored responses
    - masking_sessions, masking_records: encrypted masking contracts
    - extraction_cache: encrypted extraction and conversation context

"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Provider(SQLModel, table=True):
    """Model provider (OpenRouter, local vLLM, etc.)."""

    __tablename__ = "provider"

    id: str = Field(primary_key=True)  # e.g. "openrouter", "local-vllm"
    name: str = Field(max_length=100)
    api_base: str | None = Field(default=None)
    api_key_env: str | None = Field(default=None)  # env var name (fallback)
    encrypted_api_key: str | None = Field(default=None)  # Fernet-encrypted key
    key_fingerprint: str | None = Field(default=None)  # domain-separated HMAC digest
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class ApiKey(SQLModel, table=True):
    """API key for authentication."""

    __tablename__ = "api_keys"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(default="default")
    key_hash: str = Field(...)
    prefix: str = Field(...)  # pr-xxxx...
    is_active: bool = Field(default=True)
    last_used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class Model(SQLModel, table=True):
    """Registered AI model."""

    __tablename__ = "models"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(..., unique=True)  # e.g. "openrouter/mistralai/ministral-3b-2512"
    provider_id: str = Field(default="openrouter")  # FK to provider.id
    display_name: str | None = Field(default=None)
    params: str | None = Field(default=None)  # e.g. "3B", "4B"
    location: str = Field(default="external")  # local | external
    tier: str = Field(default="small")  # small | middle | large
    cost_per_1m_tokens: float = Field(default=0.0, ge=0.0)
    api_base_override: str | None = Field(default=None)  # per-model override
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class Workspace(SQLModel, table=True):
    """Top-level workspace container."""

    __tablename__ = "workspaces"

    id: str = Field(primary_key=True, default="default")
    name: str = Field(max_length=100, default="Default Workspace")
    active_profile: str | None = Field(default=None)  # FK to profiles.id
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class Profile(SQLModel, table=True):
    """Named configuration within a workspace."""

    __tablename__ = "profiles"

    id: str = Field(primary_key=True)  # e.g. "default", "fast", "accurate"
    workspace_id: str = Field(foreign_key="workspaces.id", default="default")
    name: str = Field(max_length=100)
    description: str = Field(default="")
    is_active: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class ProfileAgent(SQLModel, table=True):
    """Which model each agent uses in a profile."""

    __tablename__ = "profile_agents"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: str = Field(foreign_key="profiles.id")
    agent_name: str = Field(max_length=50)  # extractor | judge | generator | local
    model_id: str = Field(foreign_key="models.model_id")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class UsageLog(SQLModel, table=True):
    """Request/response tracking."""

    __tablename__ = "usage_logs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    event: str = Field(...)  # classify | generate
    is_sensitive: bool = Field(default=False)
    records_count: int = Field(default=0)
    policy_action: str | None = Field(default=None)
    model_used: str | None = Field(default=None)
    latency_ms: float = Field(default=0.0)
    status_code: int = Field(default=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class Response(SQLModel, table=True):
    """Encrypted, expiring OpenResponses-compatible response."""

    __tablename__ = "responses"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model: str = Field(...)
    owner_id: str | None = Field(default=None, index=True)
    output_json: str = Field(default="")  # Fernet-encrypted full response JSON
    status: str = Field(default="completed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    expires_at: datetime | None = Field(default=None, index=True)
    storage_encrypted: bool = Field(default=True)


class MaskingSession(SQLModel, table=True):
    """Masking session — tracks a conversation's masking context.

    Each masking session corresponds to a chat/conversation and stores
    the mapping between placeholder UIDs and original values.
    """

    __tablename__ = "masking_sessions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    chat_id: str | None = Field(default=None, index=True)  # foreign key to chat/conversation
    owner_id: str | None = Field(default=None, index=True)
    record_count: int = Field(default=0)  # number of masked records
    policy_action: str = Field(default="")  # routing decision
    is_active: bool = Field(default=True)  # session still valid
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    expires_at: datetime | None = Field(default=None, index=True)  # TTL for session


class MaskingRecord(SQLModel, table=True):
    """Individual masking record — placeholder-to-HMAC mapping.

    Each record stores the UID, category, placeholder, keyed HMAC fingerprint,
    and Fernet-encrypted original value. The span field is decryptable only
    with the master key.
    """

    __tablename__ = "masking_records"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(index=True, foreign_key="masking_sessions.id")
    uid: str = Field(index=True)  # random per-record placeholder token
    category: str = Field(...)  # e.g., RESIDENT_REGISTRATION_NUMBER
    placeholder: str = Field(...)  # e.g., RESIDENT_REGISTRATION_NUMBER#abc123
    value_hash: str = Field(...)  # keyed HMAC fingerprint for equality checks
    span: str = Field(default="")  # Fernet-encrypted original text span
    confidence: float = Field(default=0.0)
    is_essential: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class ExtractionCache(SQLModel, table=True):
    """Encrypted extraction and conversation-context cache keyed by chat ID."""

    __tablename__ = "extraction_cache"

    chat_id: str = Field(primary_key=True)
    extraction: str = Field(default="")  # Fernet-encrypted JSON extraction result
    context: str | None = Field(default=None)  # Fernet-encrypted labeled context
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None),
        index=True,
    )
