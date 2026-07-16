"""Masking session and hydration API endpoints.

Provides REST API for:
- GET /api/v1/masking/{session_id} — retrieve masking session details
- POST /api/v1/masking/{session_id}/hydrate — hydrate content using stored contract
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from sqlmodel import select

from agents import ContractStore, Masker
from db import MaskingRecord, MaskingSession, get_session
from server.api import app, require_auth


@app.get("/api/v1/masking/{session_id}")
async def get_masking_session(
    session_id: str,
    _auth: str = Depends(require_auth),
) -> dict:
    """Retrieve masking session details.

    Returns session metadata and per-record masking details
    (category, placeholder, confidence, is_essential).
    Original values are NEVER returned — only metadata.
    """
    db = get_session()
    try:
        session = db.get(MaskingSession, session_id)
        expired = (
            session is not None
            and session.expires_at is not None
            and session.expires_at <= datetime.now(UTC).replace(tzinfo=None)
        )
        if not session or session.owner_id != _auth or not session.is_active or expired:
            raise HTTPException(status_code=404, detail="Masking session not found")

        records = db.exec(select(MaskingRecord).where(MaskingRecord.session_id == session_id)).all()

        return {
            "session_id": session.id,
            "chat_id": session.chat_id,
            "record_count": session.record_count,
            "policy_action": session.policy_action,
            "is_active": session.is_active,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "extraction_records": [
                {
                    "uid": r.uid,
                    "category": r.category,
                    "placeholder": r.placeholder,
                    "confidence": r.confidence,
                    "is_essential": r.is_essential,
                }
                for r in records
            ],
        }
    finally:
        db.close()


@app.post("/api/v1/masking/{session_id}/hydrate")
async def hydrate_content(
    session_id: str,
    body: dict,
    _auth: str = Depends(require_auth),
) -> dict:
    """Hydrate content using a stored masking contract.

    Args:
        body: {"content": "text with [CATEGORY#uid] placeholders"}

    Returns:
        {"hydrated": "text with original values restored"}
    """
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content field required")

    store = ContractStore()
    contract = store.load_contract(session_id, owner_id=_auth)
    if not contract:
        raise HTTPException(status_code=404, detail="Masking session not found or expired")

    masker = Masker()
    result = masker.hydrate(content, contract)

    return {
        "hydrated": result.hydrated_text,
        "session_id": session_id,
        "records_restored": result.placeholders_restored,
    }
