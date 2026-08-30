#!/usr/bin/env python3
"""In-process mock LLM HTTP server for fast and realistic unit testing."""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Tuple


class MockLLMHandler(BaseHTTPRequestHandler):
    fail_requests: bool = False
    return_broken_json: bool = False

    def log_message(self, format, *args):
        pass  # Suppress console logging during tests

    def do_GET(self):
        if self.path in ("/v1/models", "/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = {"data": [{"id": "gemma4-26b-a4b"}]}
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")

    def do_POST(self):
        if MockLLMHandler.fail_requests:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Internal Server Error"}')
            return

        content_length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(content_length).decode("utf-8")

        if MockLLMHandler.return_broken_json:
            resp_text = "Here is broken result { invalid json"
        elif "json" in req_body.lower() or "inputs_note" in req_body.lower():
            resp_text = json.dumps({
                "purpose": "Executes core computation task.",
                "overview": (
                    "Performs fast arithmetic and updates global total."
                ),
                "inputs_note": "None",
                "outputs_note": "Calculated value",
            })
        elif "top-down" in req_body.lower() or "variable" in req_body.lower():
            resp_text = json.dumps({
                "purpose": "Global state variable modified by compute().",
                "overview": "Tracks computation count and application state.",
                "inputs_note": "None",
                "outputs_note": "None",
            })
        elif "mermaid" in req_body.lower() or "overview" in req_body.lower():
            resp_text = (
                "# Architecture Overview\n\n"
                "## System Architecture\n"
                "```mermaid\ngraph TD\n"
                "  client --> server\n"
                "```\n"
            )
        elif "module" in req_body.lower():
            resp_text = (
                "# Module Design\n\n"
                "## 1. Responsibilities\nProvides core processing.\n"
            )
        elif "data structure" in req_body.lower() or (
            "data models" in req_body.lower()
        ):
            resp_text = (
                "# Data Structure Design\n\n"
                "## 1. Core Data Models\nCore data structure definitions.\n"
            )
        else:
            resp_text = json.dumps({
                "purpose": "Executes core computation task.",
                "overview": (
                    "Performs fast arithmetic and updates global total."
                ),
                "inputs_note": "None",
                "outputs_note": "Calculated value",
            })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        resp_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": resp_text,
                    }
                }
            ]
        }
        self.wfile.write(json.dumps(resp_data).encode("utf-8"))


def start_mock_llm_server() -> Tuple[HTTPServer, str, threading.Thread]:
    """Start local mock LLM server on an auto-allocated free port."""
    server = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    host, port = server.server_address
    url = f"http://{host}:{port}/v1"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, url, thread
