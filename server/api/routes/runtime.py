"""Runtime capabilities and loopback-only demo session endpoints."""

from __future__ import annotations

from fastapi import HTTPException, Request, Response

from config import load_config
from server import get_runtime_mode
from server.api import (
    DEMO_SESSION_COOKIE,
    DEMO_SESSION_SUBJECT,
    DEMO_SESSION_TTL_SECONDS,
    SessionTokenConfigurationError,
    app,
    is_loopback_request,
    issue_session_token,
)


@app.get("/api/runtime")
async def runtime_capabilities() -> dict[str, object]:
    """Expose non-secret capabilities so the web demo can choose its auth flow."""
    mode = get_runtime_mode()
    config = load_config()
    model_roles = {
        "decision": config.decision.model,
        "local": config.local.model,
        "external": config.external.model,
    }
    selected_models = set(model_roles.values())
    model_costs = {model.id: model.cost_per_1m_tokens for model in config.models if model.id in selected_models}
    return {
        "mode": mode,
        "default_model": "privacy-router",
        "demo": {
            "authentication": "session" if mode == "dev" else "bearer",
            "session_available": mode == "dev",
        },
        "model_roles": model_roles,
        "model_costs": model_costs,
    }


@app.post("/api/demo/session")
async def create_demo_session(request: Request, response: Response) -> dict[str, int]:
    """Issue a narrow browser session only for an explicit dev process."""
    if get_runtime_mode() != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    if not is_loopback_request(request):
        raise HTTPException(status_code=403, detail="Demo session requires loopback access")
    try:
        token = issue_session_token(DEMO_SESSION_SUBJECT, purpose="demo")
    except SessionTokenConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Demo session is not configured") from exc
    response.set_cookie(
        key=DEMO_SESSION_COOKIE,
        value=token,
        max_age=DEMO_SESSION_TTL_SECONDS,
        path="/v1/chat/completions",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    return {"expires_in": DEMO_SESSION_TTL_SECONDS}
