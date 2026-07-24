"""Password-to-session exchange for the browser admin surface."""

from __future__ import annotations

import os
import secrets
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from server.api import (
    ADMIN_CSRF_COOKIE,
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_TTL_SECONDS,
    SessionTokenConfigurationError,
    admin_session_subject,
    app,
    is_loopback_request,
    issue_session_token,
    require_admin_auth,
)

_LOGIN_ATTEMPT_LIMIT = 5
_LOGIN_ATTEMPT_WINDOW_SECONDS = 60
_MAX_TRACKED_PEERS = 4096
_failed_logins: defaultdict[str, deque[float]] = defaultdict(deque)
_failed_logins_lock = Lock()


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _require_secure_transport(request: Request) -> None:
    allow_insecure_admin = os.getenv("PRIVACY_ROUTER_ALLOW_INSECURE_ADMIN") == "1"
    if request.url.scheme != "https" and not is_loopback_request(request) and not allow_insecure_admin:
        raise HTTPException(status_code=403, detail="Admin login requires HTTPS")


def _peer_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _prune_failed_logins(now: float) -> None:
    for tracked_peer, attempts in list(_failed_logins.items()):
        while attempts and now - attempts[0] >= _LOGIN_ATTEMPT_WINDOW_SECONDS:
            attempts.popleft()
        if not attempts:
            _failed_logins.pop(tracked_peer, None)


def _reserve_login_attempt(peer: str) -> None:
    now = monotonic()
    with _failed_logins_lock:
        _prune_failed_logins(now)
        if peer not in _failed_logins and len(_failed_logins) >= _MAX_TRACKED_PEERS:
            oldest_peer = min(
                _failed_logins,
                key=lambda tracked_peer: _failed_logins[tracked_peer][-1],
            )
            _failed_logins.pop(oldest_peer, None)
        attempts = _failed_logins[peer]
        if len(attempts) >= _LOGIN_ATTEMPT_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many administrator login attempts",
                headers={"Retry-After": str(_LOGIN_ATTEMPT_WINDOW_SECONDS)},
            )
        attempts.append(now)


def _clear_login_attempts(peer: str) -> None:
    with _failed_logins_lock:
        _failed_logins.pop(peer, None)


@app.post("/api/admin/session")
async def create_admin_session(
    body: AdminLoginRequest,
    request: Request,
    response: Response,
) -> dict[str, bool | int | str]:
    """Exchange the environment-configured password for a scoped cookie."""
    response.headers["Cache-Control"] = "no-store"
    _require_secure_transport(request)
    expected = os.getenv("PRIVACY_ROUTER_ADMIN_PASSWORD")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    peer = _peer_key(request)
    _reserve_login_attempt(peer)
    if not secrets.compare_digest(body.password.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid administrator credentials")
    _clear_login_attempts(peer)
    csrf_token = secrets.token_urlsafe(32)
    try:
        token = issue_session_token(admin_session_subject(csrf_token), purpose="admin")
    except SessionTokenConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Admin session is not configured") from exc
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        max_age=ADMIN_SESSION_TTL_SECONDS,
        path="/api",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        key=ADMIN_CSRF_COOKIE,
        value=csrf_token,
        max_age=ADMIN_SESSION_TTL_SECONDS,
        path="/api",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    return {
        "authenticated": True,
        "expires_in": ADMIN_SESSION_TTL_SECONDS,
        "csrf_token": csrf_token,
    }


@app.get("/api/admin/session")
async def get_admin_session(
    response: Response,
    pr_admin_csrf: str | None = Cookie(default=None, alias=ADMIN_CSRF_COOKIE),
    _admin: str = Depends(require_admin_auth),
) -> dict[str, bool | str]:
    """Report whether the browser currently has a valid admin session."""
    response.headers["Cache-Control"] = "no-store"
    if pr_admin_csrf is None:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return {"authenticated": True, "csrf_token": pr_admin_csrf}


@app.delete("/api/admin/session")
async def delete_admin_session(
    response: Response,
    _admin: str = Depends(require_admin_auth),
) -> dict[str, bool]:
    """Clear an authenticated browser session and its CSRF binding."""
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path="/api",
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        key=ADMIN_CSRF_COOKIE,
        path="/api",
        httponly=True,
        samesite="strict",
    )
    return {"authenticated": False}
