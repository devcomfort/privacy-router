"""Privacy Router Server — FastAPI application.

OpenAI-compatible ``/v1/chat/completions`` endpoint that runs the
Extractor → Judge → Router pipeline before forwarding to the backend.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from server.config import get_config

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load config on startup."""
    get_config()
    yield


app = FastAPI(title="Privacy Router", version="0.1.0", lifespan=lifespan)


# Register routes (imported after app creation to avoid circular imports)
from server.api import routes as _routes  # noqa: F401, E402
