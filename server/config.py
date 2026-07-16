"""Privacy Router Server — config singleton and adapter resolver.

Used by both the HTTP API and MCP tools.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock, RLock
from typing import Any

from dotenv import load_dotenv

from config import load_config

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_config: Any = None
_config_lock = RLock()
_config_cache_lock = Lock()
_config_generation = 0


def config_write_lock():
    """Return the process-wide lock for runtime configuration mutations."""
    return _config_lock


def invalidate_config_cache() -> None:
    """Force the next request to reload authoritative runtime configuration."""
    global _config, _config_generation
    with _config_cache_lock:
        _config = None
        _config_generation += 1


def get_config():
    """Return cached config without publishing a load invalidated in flight."""
    global _config
    while True:
        with _config_cache_lock:
            if _config is not None:
                return _config
            generation = _config_generation

        try:
            loaded = load_config()
        except FileNotFoundError as exc:
            raise RuntimeError(
                ".privacy-router.config.yaml not found. Copy .privacy-router.config.yaml.example and edit it."
            ) from exc

        with _config_cache_lock:
            if generation != _config_generation:
                continue
            if _config is None:
                _config = loaded
            return _config
