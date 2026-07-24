"""Process-local runtime mode selected by the server CLI."""

from __future__ import annotations

import os
from typing import Literal, cast

RuntimeMode = Literal["dev", "serve"]

_RUNTIME_MODE_ENV = "_PRIVACY_ROUTER_RUNTIME_MODE"
_VALID_MODES = frozenset({"dev", "serve"})
_configured_mode = os.environ.get(_RUNTIME_MODE_ENV, "serve")
_runtime_mode: RuntimeMode = cast(
    RuntimeMode,
    _configured_mode if _configured_mode in _VALID_MODES else "serve",
)


def set_runtime_mode(mode: RuntimeMode) -> None:
    """Set the immutable process mode before the API application is imported."""
    if mode not in _VALID_MODES:
        raise ValueError(f"Unsupported runtime mode: {mode}")
    global _runtime_mode
    _runtime_mode = mode
    os.environ[_RUNTIME_MODE_ENV] = mode


def get_runtime_mode() -> RuntimeMode:
    """Return the current mode; direct ASGI imports default to secure serve mode."""
    return _runtime_mode
