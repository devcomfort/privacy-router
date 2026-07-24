"""Runtime-specific boundaries applied after privacy classification."""

from __future__ import annotations

from agents import RouteResult
from server import get_runtime_mode


def constrain_runtime_route(
    policy: RouteResult,
    *,
    has_uninspected_media: bool,
) -> tuple[RouteResult, bool]:
    """Force unsafe media and every dev request onto local inference.

    Returns the effective route and whether uninspected media caused the
    override. Dev mode keeps the classifier's policy action but never selects
    an external adapter.
    """
    media_forced_local = has_uninspected_media and policy.endpoint != "local_api"
    dev_forced_local = get_runtime_mode() == "dev" and policy.endpoint != "local_api"
    if not media_forced_local and not dev_forced_local:
        return policy, False

    description = (
        "Uninspected media requires local processing"
        if media_forced_local
        else "Development mode uses local inference only"
    )
    return (
        policy.model_copy(
            update={
                "endpoint": "local_api",
                "requires_masking": False,
                "description": description,
            }
        ),
        media_forced_local,
    )
