"""Privacy Router Server — MCP package.

The full in-process server is loaded lazily so the lightweight HTTP client can
run without importing the agent and database stacks.
"""

from importlib import import_module


def __getattr__(name: str):
    if name in {"mcp", "process"}:
        return getattr(import_module("server.mcp.tools"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["mcp", "process"]
