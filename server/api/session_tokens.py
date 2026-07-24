"""Short-lived signed session tokens for browser-only access."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ADMIN_CSRF_COOKIE = "pr_admin_csrf"
ADMIN_SESSION_COOKIE = "pr_admin_session"
ADMIN_SESSION_SUBJECT = "admin"
ADMIN_SESSION_TTL_SECONDS = 30 * 60

DEMO_SESSION_COOKIE = "pr_demo_session"
DEMO_SESSION_SUBJECT = "local-demo"
DEMO_SESSION_TTL_SECONDS = 15 * 60


class SessionTokenConfigurationError(RuntimeError):
    """Raised when browser sessions cannot be signed safely."""


SessionPurpose = Literal["demo", "admin"]


def _fernet(purpose: SessionPurpose) -> Fernet:
    key = os.getenv("PRIVACY_ROUTER_MASTER_KEY") or os.getenv("MASKING_ENCRYPTION_KEY")
    if not key:
        raise SessionTokenConfigurationError("PRIVACY_ROUTER_MASTER_KEY is not configured")
    try:
        master_key = base64.urlsafe_b64decode(key.strip().encode())
    except (ValueError, binascii.Error) as exc:
        raise SessionTokenConfigurationError("PRIVACY_ROUTER_MASTER_KEY is invalid") from exc
    if len(master_key) != 32:
        raise SessionTokenConfigurationError("PRIVACY_ROUTER_MASTER_KEY is invalid")
    session_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"privacy-router/{purpose}-session/v1".encode(),
    ).derive(master_key)
    return Fernet(base64.urlsafe_b64encode(session_key))


def admin_session_subject(csrf_token: str) -> str:
    """Bind one admin session token to its matching CSRF token."""
    digest = hashlib.sha256(b"privacy-router/admin-csrf/v1\0" + csrf_token.encode()).hexdigest()
    return f"{ADMIN_SESSION_SUBJECT}:{digest}"


def issue_session_token(subject: str, *, purpose: SessionPurpose) -> str:
    """Sign a browser session subject with a purpose-derived key."""
    return _fernet(purpose).encrypt(subject.encode()).decode()


def verify_session_token(
    token: str,
    expected_subject: str,
    ttl_seconds: int,
    *,
    purpose: SessionPurpose,
) -> bool:
    """Validate a purpose-bound signed subject and enforce its maximum age."""
    if not token:
        return False
    try:
        subject = _fernet(purpose).decrypt(token.encode(), ttl=ttl_seconds).decode()
    except (InvalidToken, SessionTokenConfigurationError, UnicodeDecodeError):
        return False
    return secrets.compare_digest(subject, expected_subject)
