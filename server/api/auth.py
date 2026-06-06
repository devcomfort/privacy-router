"""API Key auth — Bearer token verification."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import Header, HTTPException
from sqlmodel import select

from db.models import ApiKey
from db.session import get_session


def create_api_key() -> tuple[str, str]:
    """Generate raw key + SHA-256 hash."""
    raw = f"pr-{secrets.token_urlsafe(32)}"
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def verify_api_key(raw: str, hashed: str) -> bool:
    """Check raw key against stored hash."""
    return hashlib.sha256(raw.encode()).hexdigest() == hashed


async def require_auth(authorization: str = Header(default="")) -> str:
    """Verify Bearer token and return provider_id."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    raw_key = authorization[len("Bearer "):]
    session = get_session()
    try:
        keys = session.exec(select(ApiKey).where(ApiKey.is_active)).all()
        for k in keys:
            if verify_api_key(raw_key, k.key_hash):
                k.last_used_at = datetime.utcnow()
                session.add(k)
                session.commit()
                return k.provider_id
        raise HTTPException(status_code=401, detail="Invalid API key")
    finally:
        session.close()
