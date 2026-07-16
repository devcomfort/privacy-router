"""ContractStore — Persistence for masking contracts.

Stores masking sessions and records in PostgreSQL. Each masking
operation creates a session with a unique ID. Records store
placeholder-to-hash mappings and Fernet-encrypted original values.
Original values are encrypted with AES-128-CBC (Fernet) before storage.

Usage:
    store = ContractStore()
    session_id = store.create_session(chat_id="user-123", record_count=2, policy_action="selective_mask")
    store.save_records(session_id, records, placeholder_map)
    contract = store.load_contract(session_id)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import select

from db import MaskingRecord, MaskingSession, get_session

from .crypto import decrypt_field, encrypt_field, fingerprint_field
from .schemas import MaskingContract


class ContractStore:
    """Persists masking contracts to PostgreSQL.

    Each masking operation creates a session. Records store placeholder-to-hash
    mappings; original values are encrypted before being stored at rest.
    """

    def __init__(self, ttl_hours: int = 24) -> None:
        self._ttl = timedelta(hours=ttl_hours)

    def create_session(
        self,
        chat_id: str | None,
        record_count: int,
        policy_action: str,
        owner_id: str | None = None,
    ) -> str:
        """Create a new masking session. Returns session_id."""

        session_id = str(uuid.uuid4())
        db = get_session()
        try:
            session = MaskingSession(
                id=session_id,
                chat_id=chat_id,
                owner_id=owner_id,
                record_count=record_count,
                policy_action=policy_action,
                is_active=True,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + self._ttl,
            )
            db.add(session)
            db.commit()
        finally:
            db.close()
        return session_id

    def save_records(
        self,
        session_id: str,
        records: list[dict[str, Any]],
        placeholder_map: dict[str, str],
    ) -> None:
        """Persist one masking operation without plaintext or raw hashes."""
        db = get_session()
        try:
            for placeholder, original_value in placeholder_map.items():
                matching = next(
                    (record for record in records if record.get("span") == original_value),
                    None,
                )
                if matching is None:
                    raise ValueError(f"No extraction record matches placeholder {placeholder!r}")

                canonical = placeholder.strip("[]")
                _label, separator, uid = canonical.partition("#")
                if not separator or not uid:
                    raise ValueError(f"Invalid masking placeholder {placeholder!r}")

                record = MaskingRecord(
                    session_id=session_id,
                    uid=uid,
                    category=matching.get("category", "SENSITIVE_DATA"),
                    placeholder=canonical,
                    value_hash=fingerprint_field(original_value),
                    span=encrypt_field(original_value),
                    confidence=matching.get("confidence", 0.0),
                    is_essential=matching.get("is_essential", False),
                )
                db.add(record)
            db.commit()
        finally:
            db.close()

    def load_contract(
        self,
        session_id: str,
        owner_id: str | None = None,
    ) -> MaskingContract | None:
        """Load an active, unexpired masking contract for its exact owner.

        Ownerless MCP sessions and authenticated REST sessions are separate
        namespaces. Returns None on any owner mismatch.
        """
        db = get_session()
        try:
            session = db.get(MaskingSession, session_id)
            if not session or not session.is_active:
                return None
            if session.owner_id != owner_id:
                return None
            if session.expires_at and session.expires_at <= datetime.now(UTC).replace(tzinfo=None):
                return None

            records = db.exec(select(MaskingRecord).where(MaskingRecord.session_id == session_id)).all()

            if not records:
                return None
            placeholder_map = {
                (record.placeholder or f"{record.category}#{record.uid}"): decrypt_field(record.span)
                for record in records
            }
            return MaskingContract(
                placeholder_map=placeholder_map,
                count=len(placeholder_map),
            )
        finally:
            db.close()

    def deactivate_session(self, session_id: str) -> None:
        """Mark a session as inactive."""

        db = get_session()
        try:
            session = db.get(MaskingSession, session_id)
            if session:
                session.is_active = False
                db.commit()
        finally:
            db.close()
