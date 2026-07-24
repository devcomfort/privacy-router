"""ASGI request tracing boundary regression tests."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from agents import decrypt_field
from db import RequestTrace, init_db
from server.api import RequestTraceMiddleware
from telemetry import build_litellm_metadata


def test_streaming_body_runs_inside_request_trace(tmp_path, monkeypatch) -> None:
    """The trace remains active until a streaming iterator is fully consumed."""
    tracing_engine = create_engine(f"sqlite:///{tmp_path / 'stream.db'}")
    monkeypatch.setattr("db.session.engine", tracing_engine)
    init_db()
    app = FastAPI()
    app.add_middleware(RequestTraceMiddleware)

    @app.post("/v1/chat/completions")
    async def stream() -> StreamingResponse:
        async def chunks():
            metadata = build_litellm_metadata("generator")
            yield json.dumps(metadata)

        return StreamingResponse(chunks(), media_type="application/json")

    body = {
        "messages": [{"role": "user", "content": "private input"}],
        "metadata": {"phone-number-value": True},
    }
    response = TestClient(app).post("/v1/chat/completions", json=body)

    request_id = response.headers["x-privacy-router-request-id"]
    assert response.json()["privacy_router"] == {
        "request_id": request_id,
        "component": "generator",
    }
    with Session(tracing_engine) as session:
        traces = session.exec(select(RequestTrace)).all()
    assert len(traces) == 1
    assert traces[0].id == request_id
    assert traces[0].status == "completed"
    assert traces[0].status_code == 200
    assert json.loads(decrypt_field(traces[0].input_encrypted)) == body
    assert "private input" not in traces[0].input_redacted
    assert "phone-number-value" not in traces[0].input_redacted
    assert json.loads(traces[0].input_redacted) == {
        "messages": [{"content": "[REDACTED]", "role": "[REDACTED]"}],
        "metadata": {"[REDACTED_KEY_0]": "[REDACTED]"},
    }
