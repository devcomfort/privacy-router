"""Privacy Router API — FastAPI application.

Start through the runtime CLI::

    privacy-router dev    # loopback-only development
    privacy-router serve  # authenticated deployment
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from agents import (
    PrivacyAnalysisUnavailable,
    log_privacy_failure,
    privacy_failure,
    public_error_fields,
)
from db import init_db, purge_expired_data
from server import ensure_runtime_admin_password, ensure_runtime_master_key, get_runtime_mode
from server.api import RequestTraceMiddleware, bootstrap_api_key_from_env
from telemetry import install_litellm_usage_callback

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
    ensure_runtime_master_key(get_runtime_mode())
    ensure_runtime_admin_password(get_runtime_mode())
    init_db()
    bootstrap_api_key_from_env()
    purge_expired_data()
    install_litellm_usage_callback()
    retention_task = asyncio.create_task(_retention_sweep_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        with suppress(asyncio.CancelledError):
            await retention_task


app = FastAPI(
    title="Privacy Router",
    version="0.2.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
    lifespan=lifespan,
)


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

app.add_middleware(RequestTraceMiddleware)

# Lazy-import routes after app creation
import server.api.routes.admin_session  # noqa: E402, F401
import server.api.routes.classify  # noqa: E402, F401
import server.api.routes.guardrail  # noqa: E402, F401
import server.api.routes.keys  # noqa: E402, F401
import server.api.routes.masking  # noqa: E402, F401
import server.api.routes.models  # noqa: E402, F401
import server.api.routes.proxy  # noqa: E402, F401
import server.api.routes.responses  # noqa: E402, F401
import server.api.routes.runtime  # noqa: E402, F401
import server.api.routes.telemetry  # noqa: E402, F401
