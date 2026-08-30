#!/usr/bin/env python3
"""End-to-end unit tests using in-process mock LLM server for 100% coverage."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pystdoc.engine import run_docgen
from pystdoc.design_engine import run_design_generation

try:
    from tests.mock_server import start_mock_llm_server, MockLLMHandler
except ImportError:
    from mock_server import start_mock_llm_server, MockLLMHandler


class TestLiveServer100(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.server_url, cls.server_thread = (
            start_mock_llm_server()
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockLLMHandler.fail_requests = False
        MockLLMHandler.return_broken_json = False
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)
        (self.test_dir / "compile_commands.json").write_text("[]")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_end_to_end_docgen_and_designgen_full_pipeline(self):
        (self.src_dir / "globals.h").write_text(
            "int g_app_mode = 1;\n", encoding="utf-8"
        )
        c_code = (
            "typedef int custom_int_t;\n\n"
            "struct PointData {\n"
            "    int pos_x;\n"
            "    int pos_y;\n"
            "};\n\n"
            "enum AppState {\n"
            "    STATE_INIT = 0,\n"
            "    STATE_READY = 1\n"
            "};\n\n"
            "int g_total_count = 0;\n\n"
            "int calculate(int x, int g_app_mode) {\n"
            "    struct PointData pt;\n"
            "    pt.pos_x = x;\n"
            "    g_total_count += pt.pos_x + g_app_mode;\n"
            "    return g_total_count;\n"
            "}\n\n"
            "int main() {\n"
            "    g_app_mode();\n"
            "    return calculate(42, 1);\n"
            "}\n"
        )
        (self.src_dir / "main.c").write_text(c_code, encoding="utf-8")
        (self.src_dir / "vars_only.py").write_text(
            "global_mode_code = 123\n", encoding="utf-8"
        )
        py_code = (
            "total_records = 100\n\n"
            "class WorkerService:\n"
            "    service_val = 50\n\n"
            "    def process_item(self, item):\n"
            "        service_val()\n"
            "        return item * 2\n\n"
            "def fetch_data():\n"
            "    global_mode_code()\n"
            "    return 1\n"
        )
        (self.src_dir / "service.py").write_text(py_code, encoding="utf-8")

        # 2. Execute docgen without LLM (static bypass mode, lines 338-356)
        ret_static = run_docgen(
            target_dir=self.test_dir,
            use_llm=False,
            language="English",
            force=True,
        )
        self.assertEqual(ret_static, 0)

        # 3. Execute docgen with live mock server (Pass 1 & Pass 2 execution)
        ret_doc1 = run_docgen(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            language="English",
            concurrency=2,
            force=True,
        )
        self.assertEqual(ret_doc1, 0)

        # 3. Second run to hit cache completely
        ret_doc2 = run_docgen(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            language="English",
            concurrency=1,
            force=False,
        )
        self.assertEqual(ret_doc2, 0)

        # 4. Execute designgen with live mock server
        ret_des1 = run_design_generation(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            language="Japanese",
            force=True,
        )
        self.assertEqual(ret_des1, 0)

        # 5. Second designgen run to hit cache
        ret_des2 = run_design_generation(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            language="Japanese",
            force=False,
        )
        self.assertEqual(ret_des2, 0)

    def test_docgen_strict_error_handling_with_server_failure(self):
        (self.src_dir / "app.c").write_text(
            "int g_val = 1;\nvoid run() { g_val++; }\n", encoding="utf-8"
        )
        MockLLMHandler.fail_requests = True

        # Strict error mode returns 1
        ret_strict = run_docgen(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            allow_fallback=False,
        )
        self.assertEqual(ret_strict, 1)

        # Fallback mode returns 0
        ret_fb = run_docgen(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            allow_fallback=True,
        )
        self.assertEqual(ret_fb, 0)

    def test_designgen_broken_json_and_fallback(self):
        # Prepare sample doc
        doc_dir = self.test_dir / ".docgen" / "documents" / "src"
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "tool.c.md").write_text(
            "# src/tool.c\n## 1. Purpose\nTool logic.\n", encoding="utf-8"
        )

        MockLLMHandler.return_broken_json = True
        ret = run_design_generation(
            target_dir=self.test_dir,
            host=self.server_url,
            use_llm=True,
            allow_fallback=True,
        )
        self.assertEqual(ret, 0)

    def test_docgen_var_thread_exception_handling(self):
        (self.src_dir / "state_var.py").write_text(
            "g_state = 100\n", encoding="utf-8"
        )
        (self.src_dir / "user_fn.py").write_text(
            "def run_fn():\n    g_state()\n",
            encoding="utf-8",
        )

        call_cnt = [0]

        def throw_after_pass1(*args, **kwargs):
            call_cnt[0] += 1
            if call_cnt[0] > 1:
                raise IOError("Pass 2 thread IO error")

        with patch(
            "pystdoc.db.DocgenDB.save_symbol_cache",
            side_effect=throw_after_pass1,
        ):
            ret = run_docgen(
                target_dir=self.test_dir,
                host=self.server_url,
                use_llm=True,
                force=True,
            )
            self.assertEqual(ret, 1)


if __name__ == "__main__":
    unittest.main()
