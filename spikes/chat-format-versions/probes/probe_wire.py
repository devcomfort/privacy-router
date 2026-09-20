from __future__ import annotations

import importlib.metadata
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from probe_common import load_messages


MESSAGES = load_messages()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

def openai_wire() -> dict[str, Any]:
    try:
        import httpx2 as httpx
    except ModuleNotFoundError:
        import httpx
    from openai import OpenAI

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": {key: value for key, value in request.headers.items() if key.lower() in {"content-type", "authorization"}},
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-spike",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    client = OpenAI(
        api_key="spike-key",
        base_url="https://wire-format.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.chat.completions.create(model="gpt-test", messages=MESSAGES)
    return {"package_version": package_version("openai"), "request": captured}


def anthropic_wire() -> dict[str, Any]:
    try:
        import httpx2 as httpx
    except ModuleNotFoundError:
        import httpx
    from anthropic import Anthropic

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": {key: value for key, value in request.headers.items() if key.lower() in {"content-type", "anthropic-version"}},
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "msg_spike",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = Anthropic(
        api_key="spike-key",
        base_url="https://wire-format.invalid",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.messages.create(model="claude-test", max_tokens=32, messages=[MESSAGES[1]], system=MESSAGES[0]["content"])
    return {"package_version": package_version("anthropic"), "request": captured}


def litellm_wire() -> dict[str, Any]:
    from litellm import completion

    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(content_length)
            captured.update(
                {
                    "method": self.command,
                    "url": self.path,
                    "headers": {key: value for key, value in self.headers.items() if key.lower() in {"content-type", "authorization"}},
                    "body": json.loads(body),
                }
            )
            response = json.dumps(
                {
                    "id": "chatcmpl-spike",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completion(
            model="openai/test",
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="spike-key",
            messages=MESSAGES,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    return {"package_version": package_version("litellm"), "request": captured}


results: dict[str, Any] = {}
for name, function in (("openai", openai_wire), ("anthropic", anthropic_wire), ("litellm", litellm_wire)):
    try:
        results[name] = function()
    except Exception as exc:
        results[name] = {"error": f"{type(exc).__name__}: {exc}", "package_version": package_version(name)}

print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
