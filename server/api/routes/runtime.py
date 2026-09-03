"""Runtime capability endpoint."""

from __future__ import annotations

from config import load_config
from server import get_runtime_mode
from server.api import app


@app.get("/api/runtime")
async def runtime_capabilities() -> dict[str, object]:
    """Expose non-secret capabilities for API clients."""
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
        "model_roles": model_roles,
        "model_costs": model_costs,
    }
