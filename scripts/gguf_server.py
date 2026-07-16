#!/usr/bin/env python3
"""Serve a GGUF model via llama-cpp-python with OpenAI-compatible API.

Usage:
    scripts/gguf_server.py --model /path/to/model.gguf --port 8002
    scripts/gguf_server.py --model /path/to/model.gguf --port 8002 --n-gpu-layers 99
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Path to GGUF model file")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--n-gpu-layers", type=int, default=99, help="Number of layers to offload to GPU")
    parser.add_argument("--n-ctx", type=int, default=8192, help="Context window size")
    parser.add_argument("--host", default="0.0.0.0")
    return parser.parse_args()


class LlamaServer:
    def __init__(self, model_path, n_gpu_layers, n_ctx):
        from llama_cpp import Llama

        print(f"Loading model: {model_path}")
        print(f"  GPU layers: {n_gpu_layers}")
        print(f"  Context: {n_ctx}")
        self.llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            verbose=False,
            chat_format="chatml",
        )
        self.model_name = model_path.split("/")[-1].replace(".gguf", "")
        print(f"Model loaded: {self.model_name}")

    def chat_completions(self, messages, max_tokens=512, temperature=0.0):
        start = time.time()
        response = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency = time.time() - start
        return response, latency


server_instance = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = {"object": "list", "data": [{"id": server_instance.model_name, "object": "model"}]}
            self.wfile.write(json.dumps(data).encode())
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length))

            messages = body.get("messages", [])
            max_tokens = body.get("max_tokens", 512)
            temperature = body.get("temperature", 0.0)

            try:
                response, latency = server_instance.chat_completions(messages, max_tokens, temperature)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def main():
    global server_instance
    args = parse_args()

    server_instance = LlamaServer(args.model, args.n_gpu_layers, args.n_ctx)

    httpd = HTTPServer((args.host, args.port), Handler)
    print(f"GGUF server listening on {args.host}:{args.port}")
    print(f"Model: {server_instance.model_name}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    main()
