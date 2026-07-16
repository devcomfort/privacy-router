"""Unit tests for agents.masker.contract_store — DB-backed masking persistence.

Requires: PostgreSQL running (docker compose up db).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from agents.masker import ContractStore, fingerprint_field
from db import MaskingRecord, MaskingSession, get_session, init_db

init_db()


class TestContractStoreCreateSession:
    """Test session creation."""

    def test_create_session(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="test-chat-1",
            record_count=2,
            policy_action="selective_mask",
        )
        assert session_id is not None

        # Verify in DB
        db = get_session()
        try:
            session = db.get(MaskingSession, session_id)
            assert session is not None
            assert session.chat_id == "test-chat-1"
            assert session.record_count == 2
            assert session.is_active is True
        finally:
            db.close()

    def test_session_owner_limits_contract_access(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="owned-chat",
            record_count=1,
            policy_action="selective_mask",
            owner_id="provider-a",
        )
        store.save_records(
            session_id,
            [{"category": "SECRET", "span": "private", "confidence": 0.9}],
            {"SECRET#deadbeef": "private"},
        )

        assert store.load_contract(session_id, owner_id="provider-a") is not None
        assert store.load_contract(session_id, owner_id="provider-b") is None


class TestContractStoreSaveAndLoad:
    """Test saving records and loading contracts."""

    def test_save_and_load(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="test-chat-2",
            record_count=1,
            policy_action="selective_mask",
        )

        records = [
            {
                "category": "PERSONAL_IDENTIFIER_NUMBER",
                "span": "901212-1234567",
                "confidence": 0.98,
                "is_essential": False,
            },
        ]
        placeholder_map = {"SENSITIVE_DATA#a1b2c3d4": "901212-1234567"}

        store.save_records(session_id, records, placeholder_map)
        db = get_session()
        try:
            saved = db.exec(select(MaskingRecord).where(MaskingRecord.session_id == session_id)).one()
            assert saved.category == "PERSONAL_IDENTIFIER_NUMBER"
            assert saved.uid == "a1b2c3d4"
            assert saved.confidence == 0.98
            assert saved.placeholder == "SENSITIVE_DATA#a1b2c3d4"
            assert saved.value_hash == fingerprint_field("901212-1234567")
            assert saved.value_hash != hashlib.sha256(b"901212-1234567").hexdigest()
        finally:
            db.close()

        # Load and verify
        contract = store.load_contract(session_id)
        assert contract is not None
        assert contract.count == 1
        assert "SENSITIVE_DATA#a1b2c3d4" in contract.placeholder_map

    def test_span_is_encrypted_in_db(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="test-chat-3",
            record_count=1,
            policy_action="selective_mask",
        )

        records = [{"category": "PERSONAL_IDENTIFIER_NUMBER", "span": "010-1234-5678"}]
        placeholder_map = {"SENSITIVE_DATA#xyz12345": "010-1234-5678"}
        store.save_records(session_id, records, placeholder_map)

        # Check raw DB — span should NOT be plaintext
        db = get_session()
        try:
            record = db.exec(select(MaskingRecord).where(MaskingRecord.session_id == session_id)).first()
            assert record is not None
            assert record.span != "010-1234-5678"  # encrypted, not plaintext
        finally:
            db.close()

        # But loading should decrypt
        contract = store.load_contract(session_id)
        assert contract is not None
        assert contract.placeholder_map["SENSITIVE_DATA#xyz12345"] == "010-1234-5678"

    def test_load_contract_requires_exact_owner(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="owner-bound-chat",
            record_count=1,
            policy_action="selective_mask",
            owner_id="provider-a",
        )
        store.save_records(
            session_id,
            [{"category": "CREDENTIAL", "span": "secret-value"}],
            {"SENSITIVE_DATA#deadbeef": "secret-value"},
        )

        assert store.load_contract(session_id, owner_id="provider-a") is not None
        assert store.load_contract(session_id, owner_id="provider-b") is None
        assert store.load_contract(session_id) is None

    def test_rejects_placeholder_without_matching_record(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="test-chat-unmatched",
            record_count=1,
            policy_action="selective_mask",
        )

        with pytest.raises(ValueError, match="No extraction record matches"):
            store.save_records(
                session_id,
                [{"category": "TEST", "span": "expected"}],
                {"SENSITIVE_DATA#deadbeef": "different"},
            )


class TestContractStoreDeactivate:
    """Test session deactivation."""

    def test_deactivate_session(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="test-chat-4",
            record_count=0,
            policy_action="allow",
        )

        store.deactivate_session(session_id)

        db = get_session()
        try:
            session = db.get(MaskingSession, session_id)
            assert session.is_active is False
        finally:
            db.close()

        # Loading deactivated session returns None
        contract = store.load_contract(session_id)
        assert contract is None

    def test_load_contract_rejects_expired_session(self):
        store = ContractStore()
        session_id = store.create_session(
            chat_id="test-chat-expired",
            record_count=1,
            policy_action="selective_mask",
        )
        store.save_records(
            session_id,
            [{"category": "CREDENTIAL", "span": "secret-value"}],
            {"CREDENTIAL#deadbeef": "secret-value"},
        )
        assert store.load_contract(session_id) is not None
        db = get_session()
        try:
            session = db.get(MaskingSession, session_id)
            assert session is not None
            session.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            db.add(session)
            db.commit()
        finally:
            db.close()

        assert store.load_contract(session_id) is None
