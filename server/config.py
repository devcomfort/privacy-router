"""Privacy Router Server — config singleton and adapter resolver.

Used by both the HTTP API and MCP tools.
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from pathlib import Path

from config import load_config

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_config: Any = None


def get_config():
    """Return the cached PrivacyRouterConfig, loading it on first call."""
    global _config
    if _config is None:
        try:
            _config = load_config()
        except FileNotFoundError:
            raise RuntimeError(
                ".privacy-router.config.yaml not found. "
                "Copy .privacy-router.config.yaml.example and edit it."
            )
    return _config
