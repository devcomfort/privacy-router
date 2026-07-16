"""SQLModel-backed cache for encrypted extraction results and conversation context."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, text
from sqlmodel import Session, select

from agents.masker import decrypt_field, encrypt_field
from db import ExtractionCache, engine

_CACHE_TTL = timedelta(hours=24)


def _is_expired(entry: ExtractionCache) -> bool:
    """Return whether an entry exceeded the inactivity TTL."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - _CACHE_TTL
    return entry.updated_at < cutoff


def _load_active_entry(
    session: Session,
    chat_id: str,
) -> ExtractionCache | None:
    """Load a row and atomically remove it only if it remains expired."""
    for _ in range(3):
        entry = session.get(ExtractionCache, chat_id)
        if entry is None or not _is_expired(entry):
            return entry
        cutoff = datetime.now(UTC).replace(tzinfo=None) - _CACHE_TTL
        result = session.exec(
            delete(ExtractionCache).where(
                ExtractionCache.chat_id == chat_id,
                ExtractionCache.updated_at < cutoff,
            )
        )
        if result.rowcount:
            session.commit()
            return None
        session.expire_all()
    raise RuntimeError("Cache entry changed repeatedly during expiration")


def _load_locked_entry(
    session: Session,
    chat_id: str,
) -> ExtractionCache | None:
    """Serialize cache writers for one chat and load its current row."""
    if engine.dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return session.get(ExtractionCache, chat_id)
    if engine.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:chat_id, 0))"),
            {"chat_id": chat_id},
        )
    return session.exec(
        select(ExtractionCache).where(ExtractionCache.chat_id == chat_id).with_for_update()
    ).one_or_none()


def _discard_expired_locked(
    session: Session,
    entry: ExtractionCache | None,
) -> ExtractionCache | None:
    """Delete an expired row after the caller has acquired its write lock."""
    if entry is None or not _is_expired(entry):
        return entry
    session.delete(entry)
    session.flush()
    return None


class SQLiteKVCache:
    """Persistent encrypted cache keyed by chat ID."""

    # ── Extraction ───────────────────────────────────────────────────────

    def get_extraction(self, chat_id: str) -> dict | None:
        """Get and decrypt a cached extraction by chat_id."""
        with Session(engine) as session:
            entry = _load_active_entry(session, chat_id)
            if entry and entry.extraction:
                return json.loads(decrypt_field(entry.extraction))
        return None

    def put_extraction(self, chat_id: str, extraction: dict) -> None:
        """Cache an encrypted extraction result."""
        serialized = json.dumps(extraction, ensure_ascii=False)
        encrypted = encrypt_field(serialized)
        with Session(engine) as session:
            entry = _load_locked_entry(session, chat_id)
            entry = _discard_expired_locked(session, entry)
            if entry:
                entry.extraction = encrypted
                entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                entry = ExtractionCache(
                    chat_id=chat_id,
                    extraction=encrypted,
                )
                session.add(entry)
            session.commit()

    # ── Conversation context ─────────────────────────────────────────────

    def get_context(self, chat_id: str) -> list[dict[str, str]]:
        """Load and decrypt the complete privacy-analysis context."""
        with Session(engine) as session:
            entry = _load_active_entry(session, chat_id)
            if not entry or not entry.context:
                return []
            context = json.loads(decrypt_field(entry.context))
        if not isinstance(context, list) or any(
            not isinstance(segment, dict)
            or not isinstance(segment.get("label"), str)
            or not isinstance(segment.get("text"), str)
            for segment in context
        ):
            raise ValueError("Persisted privacy context is invalid")
        return context

    def put_context(
        self,
        chat_id: str,
        context: list[dict[str, str]],
    ) -> None:
        """Encrypt and persist the complete privacy-analysis context."""
        serialized = json.dumps(context, ensure_ascii=False)
        encrypted = encrypt_field(serialized)
        with Session(engine) as session:
            entry = _load_locked_entry(session, chat_id)
            entry = _discard_expired_locked(session, entry)
            if entry:
                entry.context = encrypted
                entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                entry = ExtractionCache(
                    chat_id=chat_id,
                    context=encrypted,
                )
                session.add(entry)
            session.commit()

    def merge_context(
        self,
        chat_id: str,
        current: list[dict[str, str]],
        merge: Callable[
            [list[dict[str, str]], list[dict[str, str]]],
            list[Any],
        ],
    ) -> None:
        """Atomically merge a request delta with the latest persisted context."""
        with Session(engine) as session:
            entry = _load_locked_entry(session, chat_id)
            entry = _discard_expired_locked(session, entry)
            previous = json.loads(decrypt_field(entry.context)) if entry and entry.context else []
            merged = [
                (
                    segment
                    if isinstance(segment, dict)
                    else {
                        "label": segment.label,
                        "text": segment.text,
                    }
                )
                for segment in merge(previous, current)
            ]
            encrypted = encrypt_field(json.dumps(merged, ensure_ascii=False))
            if entry:
                entry.context = encrypted
                entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                session.add(
                    ExtractionCache(
                        chat_id=chat_id,
                        context=encrypted,
                    )
                )
            session.commit()

    # ── Maintenance ──────────────────────────────────────────────────────

    def delete(self, chat_id: str) -> bool:
        """Remove cache entry. Returns True if found."""
        with Session(engine) as session:
            entry = session.get(ExtractionCache, chat_id)
            if entry:
                session.delete(entry)
                session.commit()
                return True
        return False


# Singleton
_CACHE: SQLiteKVCache | None = None


def get_cache() -> SQLiteKVCache:
    """Get or create the default cache."""
    global _CACHE
    if _CACHE is None:
        _CACHE = SQLiteKVCache()
    return _CACHE
