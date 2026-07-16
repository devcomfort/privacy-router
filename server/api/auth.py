"""API Key auth — Bearer token verification."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime

from fastapi import Header, HTTPException
from sqlmodel import select

from db import ApiKey, get_session


def create_api_key() -> tuple[str, str]:
    """Generate raw key + SHA-256 hash."""
    raw = f"pr-{secrets.token_urlsafe(32)}"
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def verify_api_key(raw: str, hashed: str) -> bool:
    """Check raw key against stored hash."""
    return secrets.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), hashed)


async def require_admin_auth(
    x_privacy_router_admin_key: str | None = Header(
        default=None,
        alias="X-Privacy-Router-Admin-Key",
    ),
) -> str:
    """Authenticate management requests with the configured admin key."""
    expected = os.getenv("PRIVACY_ROUTER_ADMIN_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if x_privacy_router_admin_key is None:
        raise HTTPException(status_code=401, detail="Missing admin key")
    if not secrets.compare_digest(x_privacy_router_admin_key, expected):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return "admin"


async def require_auth(authorization: str = Header(default="")) -> str:
    """Verify the bearer token and return its stable API-key ID."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    raw_key = authorization[len("Bearer ") :]
    session = get_session()
    try:
        keys = session.exec(select(ApiKey).where(ApiKey.is_active)).all()
        for k in keys:
            if verify_api_key(raw_key, k.key_hash):
                k.last_used_at = datetime.now(UTC).replace(tzinfo=None)
                session.add(k)
                session.commit()
                return k.id
        raise HTTPException(status_code=401, detail="Invalid API key")
    finally:
        session.close()
