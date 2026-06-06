"""Privacy Router Server — HTTP proxy + MCP server.

Public API
----------
app
    FastAPI application instance.
mcp
    FastMCP server instance with ``classify`` and ``route`` tools.
main()
    Start the HTTP server (uvicorn on port 8787).

Examples
--------
>>> from server import main
>>> main()  # starts uvicorn on :8787
"""

from server.api.main import app
from server.mcp import mcp

__all__ = ["app", "mcp", "main"]


def main():
    """Start the HTTP proxy server."""
    import uvicorn

    from server.config import get_config

    cfg = get_config()
    print("Privacy Router Server")
    print(f"  Extractor: {cfg.extractor.model}")
    print(f"  Judge:     {cfg.judge.model}")
    print(f"  Models:    {len(cfg.models)} registered")
    print()
    print("  HTTP Proxy:  http://localhost:8787")
    print("  Chat UI:     http://localhost:8787/")
    print("  API:         http://localhost:8787/v1/chat/completions")
    print("  MCP (stdio): connect via FastMCP")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8787)
