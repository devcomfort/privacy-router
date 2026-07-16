"""Privacy Router API — FastAPI application.

Start with::

    uvicorn server.api.main:app
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agents import (
    PrivacyAnalysisUnavailable,
    log_privacy_failure,
    privacy_failure,
    public_error_fields,
)
from db import init_db, purge_expired_data

logger = logging.getLogger(__name__)


_RETENTION_SWEEP_INTERVAL_SECONDS = 60 * 60


async def _retention_sweep_loop() -> None:
    """Physically delete expired raw-data containers once per hour."""
    while True:
        await asyncio.sleep(_RETENTION_SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(purge_expired_data)
        except Exception:
            logger.exception("Raw-data retention sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize privacy migrations and the bounded-retention worker."""
    init_db()
    purge_expired_data()
    retention_task = asyncio.create_task(_retention_sweep_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        with suppress(asyncio.CancelledError):
            await retention_task


app = FastAPI(title="Privacy Router", version="0.2.0", lifespan=lifespan)


@app.exception_handler(PrivacyAnalysisUnavailable)
async def privacy_analysis_unavailable(
    _request: Request,
    _exc: PrivacyAnalysisUnavailable,
) -> JSONResponse:
    """Return a safe failure without exposing the input or upstream error."""
    failure = privacy_failure("extraction_failed")
    request_id = uuid4().hex
    log_privacy_failure(failure, request_id)
    return JSONResponse(
        status_code=failure.status_code,
        content={"error": public_error_fields(failure, request_id)},
    )


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Mount SvelteKit static assets

_build_dir = Path(__file__).resolve().parent.parent.parent / "web" / "build"
if _build_dir.exists():
    app.mount("/_app", StaticFiles(directory=str(_build_dir / "_app")), name="sveltekit-assets")

# Lazy-import routes after app creation
import server.api.routes.classify  # noqa: E402, F401
import server.api.routes.guardrail  # noqa: E402, F401
import server.api.routes.keys  # noqa: E402, F401
import server.api.routes.masking  # noqa: E402, F401
import server.api.routes.models  # noqa: E402, F401
import server.api.routes.proxy  # noqa: E402, F401
import server.api.routes.responses  # noqa: E402, F401
from server.api import STATIC_DIR  # noqa: E402


@app.get("/{path:path}")
async def serve_static(path: str):
    """Serve static files after every API route has been registered."""
    static_root = STATIC_DIR.resolve()
    file_path = (static_root / path).resolve()
    if not file_path.is_relative_to(static_root):
        return HTMLResponse("<h1>404</h1>", status_code=404)
    if file_path.is_file():
        mime, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(str(file_path), media_type=mime)

    html_path = STATIC_DIR / f"{path}.html"
    if html_path.is_file():
        return HTMLResponse(html_path.read_text())

    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>404</h1>", status_code=404)
