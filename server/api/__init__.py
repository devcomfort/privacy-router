"""Privacy Router Server — API package.

Import ``app`` from ``server.api.main`` to get the FastAPI application.
"""

from __future__ import annotations

from pathlib import Path

# Directory containing demo web UI
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "web"
