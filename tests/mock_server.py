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
        elif (
            "localizer" in req_body.lower()
            or "doc_title_template" in req_body.lower()
        ):
            resp_text = json.dumps({
                "language": "Japanese",
                "doc_title_template": "{kind}仕様書: `{name}`",
                "basic_info_title": "## 1. 基本情報",
                "label_name": "名前",
                "label_fqdn": "FQDN",
                "label_symbol_kind": "シンボル種別",
                "label_location": "定義位置",
                "location_template": "{start}行目から{end}行目",
                "label_signature": "シグネチャ / 型",
                "parameters_title": "## 2. パラメータ",
                "label_none": "なし",
                "input_return_title": "## 3. 入力・戻り値の仕様",
                "label_input_constraints": "入力制約",
                "label_return_type": "戻り値の型",
                "label_return_value_side_effects": "戻り値と副作用",
                "label_void_none": "void / なし",
                "called_functions_title": "## 4. 呼び出し先関数",
                "referencing_functions_title": "## 4. 参照元関数",
                "source_code_snippet_title": "## ソースコード",
                "file_doc_title_template": "ファイル仕様書: `{path}`",
                "label_file_hash": "ファイル SHA-256",
                "label_detected_symbols": "検出シンボル数",
                "symbol_list_title": "## シンボル一覧",
                "symbol_list_item_template": (
                    "- `{name}` ({kind}) [{line_range}行]"
                ),
                "kind_function": "関数",
                "kind_class": "クラス",
                "kind_method": "メソッド",
                "kind_variable": "変数",
                "kind_struct": "構造体",
                "kind_enum": "列挙型",
                "kind_interface": "インターフェース",
                "kind_constant": "定数",
                "kind_type": "型",
                "kind_module": "モジュール",
            })
        elif "json" in req_body.lower() or "inputs_note" in req_body.lower():
            resp_text = json.dumps({
                "role": "Main computation unit.",
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
