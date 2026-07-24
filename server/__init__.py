"""Privacy Router HTTP server package.

``app`` is loaded lazily so importing a lightweight submodule does not pull in
the API, agent, and database stacks. Import the MCP server from ``server.mcp``.

Examples
--------
>>> from server import main
>>> main(["dev"])  # starts a loopback-only development server
"""

import argparse
import base64
import os
import secrets
from collections.abc import Sequence
from importlib import import_module

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from server.runtime import RuntimeMode, get_runtime_mode, set_runtime_mode

__all__ = [
    "app",
    "ensure_runtime_admin_password",
    "ensure_runtime_master_key",
    "get_runtime_mode",
    "main",
]


def __getattr__(name: str):
    if name == "app":
        return import_module("server.api").app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def ensure_runtime_master_key(mode: RuntimeMode) -> None:
    """Validate a persistent deployment key or create one ephemeral dev key."""
    key = os.environ.get("PRIVACY_ROUTER_MASTER_KEY") or os.environ.get("MASKING_ENCRYPTION_KEY")
    if not key:
        if mode != "dev":
            raise RuntimeError("PRIVACY_ROUTER_MASTER_KEY is required in serve mode")
        key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        os.environ["PRIVACY_ROUTER_MASTER_KEY"] = key
    try:
        Fernet(key.strip().encode())
    except ValueError as exc:
        raise RuntimeError("PRIVACY_ROUTER_MASTER_KEY must be a valid Fernet key") from exc


def ensure_runtime_admin_password(mode: RuntimeMode) -> None:
    """Require the browser-management secret for a deployed server."""
    if mode == "serve" and not os.environ.get("PRIVACY_ROUTER_ADMIN_PASSWORD", "").strip():
        raise RuntimeError("PRIVACY_ROUTER_ADMIN_PASSWORD is required in serve mode")


def _start_server(mode: RuntimeMode, host: str, port: int, reload: bool) -> None:
    """Start the HTTP server with the selected security posture."""
    load_dotenv(dotenv_path=".env")
    set_runtime_mode(mode)
    ensure_runtime_master_key(mode)
    ensure_runtime_admin_password(mode)
    cfg = import_module("server.config").get_config()
    display_host = "localhost" if host in {"127.0.0.1", "::1"} else host
    base_url = f"http://{display_host}:{port}"

    print(f"Privacy Router Server ({mode})")
    print(f"  Privacy analysis:    {cfg.decision.model}")
    print(f"  Local generation:    {cfg.local.model}")
    print(f"  External generation: {cfg.external.model}")
    print(f"  Models:              {len(cfg.models)} registered")
    print()
    print(f"  HTTP Proxy:  {base_url}")
    print(f"  Chat UI:     {base_url}/")
    print(f"  API:         {base_url}/v1/chat/completions")
    print("  MCP (stdio): connect via FastMCP")
    print()

    target = "server.api.main:app" if reload else import_module("server.api").app
    import_module("uvicorn").run(target, host=host, port=port, reload=reload)


def main(argv: Sequence[str] | None = None) -> None:
    """Parse console arguments and start the Privacy Router HTTP server."""
    parser = argparse.ArgumentParser(
        prog="privacy-router",
        description="Start the Privacy Router HTTP server.",
    )
    commands = parser.add_subparsers(dest="mode", required=True)

    dev = commands.add_parser("dev", help="Start a loopback-only keyless demo.")
    dev.add_argument("--port", type=int, default=8787)
    dev.add_argument("--reload", action="store_true")

    serve = commands.add_parser("serve", help="Start the authenticated public server.")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8787)

    args = parser.parse_args(argv)
    mode = args.mode
    host = "127.0.0.1" if mode == "dev" else args.host
    _start_server(mode, host, args.port, getattr(args, "reload", False))
