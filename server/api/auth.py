"""API Key auth — Bearer token verification."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
from datetime import UTC, datetime

from fastapi import Cookie, Header, HTTPException, Request
from sqlmodel import select

from db import ApiKey, get_session
from server.api.session_tokens import (
    ADMIN_CSRF_COOKIE,
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_SUBJECT,
    ADMIN_SESSION_TTL_SECONDS,
    admin_session_subject,
    verify_session_token,
)

_MIN_CLIENT_API_KEY_LENGTH = 24
_ENVIRONMENT_API_KEY_ID = "environment"
_SAFE_ADMIN_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_loopback_request(request: Request) -> bool:
    """Return whether the directly connected HTTP peer is loopback."""
    if request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def create_api_key() -> tuple[str, str]:
    """Generate raw key + SHA-256 hash."""
    raw = f"pr-{secrets.token_urlsafe(32)}"
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def verify_api_key(raw: str, hashed: str) -> bool:
    """Check raw key against stored hash."""
    return secrets.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), hashed)


def bootstrap_api_key_from_env() -> None:
    """Upsert the client API key supplied to containerized integrations."""
    raw_key = os.getenv("PRIVACY_ROUTER_API_KEY", "").strip()
    if not raw_key:
        return
    if not raw_key.startswith("pr-") or len(raw_key) < _MIN_CLIENT_API_KEY_LENGTH:
        raise RuntimeError("PRIVACY_ROUTER_API_KEY must start with 'pr-' and contain at least 24 characters")

    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    session = get_session()
    try:
        key = session.get(ApiKey, _ENVIRONMENT_API_KEY_ID)
        managed_hashes = {key_hash}
        if key is not None:
            managed_hashes.add(key.key_hash)
        collisions = session.exec(
            select(ApiKey).where(
                ApiKey.id != _ENVIRONMENT_API_KEY_ID,
                ApiKey.key_hash.in_(managed_hashes),
            )
        ).all()
        for collision in collisions:
            collision.is_active = False
            session.add(collision)

        if key is None:
            key = ApiKey(
                id=_ENVIRONMENT_API_KEY_ID,
                name="environment",
                key_hash=key_hash,
                prefix=raw_key[:11],
            )
        else:
            key.key_hash = key_hash
            key.prefix = raw_key[:11]
            key.is_active = True
            key.last_used_at = None
        session.add(key)
        session.commit()
    finally:
        session.close()


async def require_admin_auth(
    request: Request,
    pr_admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE),
    pr_admin_csrf: str | None = Cookie(default=None, alias=ADMIN_CSRF_COOKIE),
    x_privacy_router_csrf_token: str | None = Header(
        default=None,
        alias="X-Privacy-Router-CSRF-Token",
    ),
) -> str:
    """Authenticate management requests and enforce CSRF on state changes."""
    if not os.getenv("PRIVACY_ROUTER_ADMIN_PASSWORD"):
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if (
        pr_admin_session is None
        or pr_admin_csrf is None
        or not verify_session_token(
            pr_admin_session,
            admin_session_subject(pr_admin_csrf),
            ADMIN_SESSION_TTL_SECONDS,
            purpose="admin",
        )
    ):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    if request.method not in _SAFE_ADMIN_METHODS and (
        x_privacy_router_csrf_token is None
        or not secrets.compare_digest(
            x_privacy_router_csrf_token.encode(),
            pr_admin_csrf.encode(),
        )
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return ADMIN_SESSION_SUBJECT


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
