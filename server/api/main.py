"""Privacy Router API — FastAPI application.

Start with::

    uvicorn server.api.main:app
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception:
        pass
    yield


app = FastAPI(title="Privacy Router", version="0.2.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Lazy-import routes after app creation
import server.api.routes.providers  # noqa: E402, F401
import server.api.routes.models     # noqa: E402, F401
import server.api.routes.classify   # noqa: E402, F401
import server.api.routes.keys       # noqa: E402, F401
import server.api.routes.proxy      # noqa: E402, F401
