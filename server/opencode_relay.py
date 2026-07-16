"""OpenCode Go relay server — OpenAI-compatible proxy for OpenCode API.

Translates OpenAI chat/completions requests into OpenCode session.prompt() calls,
enabling Privacy Router to use OpenCode Go models through the standard OpenAI API.

Usage:
    python server/opencode_relay.py
    # Listens on :8789 by default

Environment:
    OPENCODE_API_KEY    — OpenCode API key (required)
    OPENCODE_BASE_URL   — OpenCode server URL (default: http://localhost:4096)
    RELAY_PORT           — Relay server port (default: 8789)
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import suppress
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="OpenCode Go Relay")

OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY", "")
OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "http://localhost:4096")
RELAY_PORT = int(os.environ.get("RELAY_PORT", "8789"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENCODE_API_KEY}",
        "Content-Type": "application/json",
    }


def _create_session(client: httpx.Client, model: str | None = None) -> str:
    """Create an OpenCode session and return its ID."""
    body: dict[str, Any] = {"title": f"relay-{uuid.uuid4().hex[:8]}"}
    if model:
        body["model"] = model
    resp = client.post(f"{OPENCODE_BASE_URL}/session", headers=_headers(), json=body)
    resp.raise_for_status()
    return resp.json()["id"]


def _send_prompt(
    client: httpx.Client,
    session_id: str,
    messages: list[dict],
    model: str | None = None,
) -> dict:
    """Send a prompt to an OpenCode session and return the response."""
    parts = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append({"type": "text", "text": part["text"]})

    body: dict[str, Any] = {"parts": parts}
    if model:
        if "/" in model:
            provider_id, model_id = model.split("/", 1)
            body["model"] = {"providerID": provider_id, "modelID": model_id}
        else:
            body["model"] = {"modelID": model}

    resp = client.post(
        f"{OPENCODE_BASE_URL}/session/{session_id}/prompt",
        headers=_headers(),
        json=body,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_content(response: dict) -> str:
    """Extract text content from OpenCode response."""
    parts = response.get("parts", [])
    return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")


def _to_openai(content: str, model: str, session_id: str) -> dict:
    """Format as OpenAI chat/completions response."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "opencode_session_id": session_id,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    """OpenAI-compatible chat/completions endpoint."""
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", "")

    with httpx.Client(timeout=120) as client:
        session_id = _create_session(client, model)
        response = _send_prompt(client, session_id, messages, model)
        with suppress(Exception):
            client.delete(f"{OPENCODE_BASE_URL}/session/{session_id}", headers=_headers())

    content = _extract_content(response)
    return JSONResponse(_to_openai(content, model, session_id))


@app.get("/v1/models")
async def list_models() -> dict:
    """List available OpenCode Go models."""
    return {
        "object": "list",
        "data": [
            {"id": "opencode-go/glm-5.1", "object": "model", "owned_by": "opencode-go"},
            {"id": "opencode-go/kimi-k2.6", "object": "model", "owned_by": "opencode-go"},
            {"id": "opencode-go/deepseek-v4-pro", "object": "model", "owned_by": "opencode-go"},
            {"id": "opencode-go/deepseek-v4-flash", "object": "model", "owned_by": "opencode-go"},
            {"id": "opencode-go/mimo-v2-pro", "object": "model", "owned_by": "opencode-go"},
            {"id": "opencode-go/minimax-m2.7", "object": "model", "owned_by": "opencode-go"},
            {"id": "opencode-go/qwen3.6-plus", "object": "model", "owned_by": "opencode-go"},
        ],
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "provider": "opencode-go"}


if __name__ == "__main__":
    print(f"OpenCode Go Relay starting on :{RELAY_PORT}")
    print(f"OpenCode API: {OPENCODE_BASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=RELAY_PORT)
