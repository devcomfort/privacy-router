from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from litellm import completion

from probe_common import load_messages


MESSAGES = load_messages()


class Handler(BaseHTTPRequestHandler):
    captured: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        Handler.captured.append({"method": self.command, "url": self.path, "body": json.loads(body)})
        if self.path.endswith("/messages"):
            response = {
                "id": "msg-spike",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        else:
            response = {
                "id": "chatcmpl-spike",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    base = f"http://127.0.0.1:{server.server_port}"
    errors: list[str] = []
    for model in ("openai/test", "anthropic/claude-test"):
        try:
            completion(model=model, api_base=base, api_key="spike-key", messages=MESSAGES)
        except Exception as exc:
            errors.append(f"{model}: {type(exc).__name__}: {exc}")
finally:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()

print(json.dumps({"requests": Handler.captured, "errors": errors}, ensure_ascii=False, indent=2, sort_keys=True))
