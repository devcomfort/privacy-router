"""Privacy Router HTTP server package.

``app`` is loaded lazily so importing a lightweight submodule does not pull in
the API, agent, and database stacks. Import the MCP server from ``server.mcp``.

Examples
--------
>>> from server import main
>>> main()  # starts uvicorn on :8787
"""

import argparse
from collections.abc import Sequence
from importlib import import_module

__all__ = ["app", "main"]


def __getattr__(name: str):
    if name == "app":
        return import_module("server.api").app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _start_server() -> None:
    """Start the HTTP server on port 8787."""
    cfg = import_module("server.config").get_config()
    print("Privacy Router Server")
    print(f"  Privacy analysis:   {cfg.decision.model}")
    print(f"  Local generation:   {cfg.local.model}")
    print(f"  External generation: {cfg.external.model}")
    print(f"  Models:             {len(cfg.models)} registered")
    print()
    print("  HTTP Proxy:  http://localhost:8787")
    print("  Chat UI:     http://localhost:8787/")
    print("  API:         http://localhost:8787/v1/chat/completions")
    print("  MCP (stdio): connect via FastMCP")
    print()

    api_app = import_module("server.api").app
    import_module("uvicorn").run(api_app, host="0.0.0.0", port=8787)


def main(argv: Sequence[str] | None = None) -> None:
    """Parse console arguments and start the Privacy Router HTTP server."""
    parser = argparse.ArgumentParser(
        prog="privacy-router",
        description="Start the Privacy Router HTTP server.",
    )
    parser.parse_args(argv)
    _start_server()
