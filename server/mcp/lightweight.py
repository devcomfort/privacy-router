"""Privacy Router MCP Server — lightweight HTTP client.

This thin MCP server calls the Privacy Router HTTP API instead of
importing the full server stack, avoiding heavy agent-container dependencies.
"""

from __future__ import annotations

import os
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("privacy-router")

API_BASE = os.environ.get("PRIVACY_ROUTER_URL", "http://api:8787")
API_KEY = os.environ.get("PRIVACY_ROUTER_API_KEY", "").strip()


@mcp.tool()
def process(
    text: str,
    action: Literal["auto", "classify", "generate", "hydrate"] = "auto",
    model: str | None = None,
    chat_id: str | None = None,
) -> dict:
    """Process a prompt through one Privacy Router HTTP operation.

    Args:
        text: Raw prompt or masked response text.
        action: Privacy operation to perform.
        model: Optional generator-model override.
        chat_id: Optional masking session ID; required for hydration.

    Returns:
        The Privacy Router result for the selected operation.
    """
    supported = {"auto", "classify", "generate", "hydrate"}
    if action not in supported:
        raise ValueError(f"Unsupported action: {action}")

    if not API_KEY:
        raise RuntimeError("PRIVACY_ROUTER_API_KEY is required for Privacy Router MCP requests")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    if action == "classify":
        response = httpx.post(
            f"{API_BASE}/api/v1/classify",
            json={"text": text},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    if action == "hydrate":
        if not chat_id:
            raise ValueError("chat_id is required for hydration")
        response = httpx.post(
            f"{API_BASE}/api/v1/masking/{chat_id}/hydrate",
            json={"content": text},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        return {
            "action_taken": "hydrated",
            "content": result["hydrated"],
            "masking_session_id": chat_id,
        }

    payload = {"text": text}
    if model is not None:
        payload["model"] = model
    if chat_id is not None:
        payload["chat_id"] = chat_id
    response = httpx.post(
        f"{API_BASE}/api/v1/generate",
        json=payload,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    mcp.run(transport="stdio")
