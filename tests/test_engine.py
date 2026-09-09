#!/usr/bin/env python3
"""Unit tests for engine execution, FileLock, cache, and hasher operations."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pystdoc.cache import save_symbol_cache, load_symbol_cache
from pystdoc.hasher import (
    compute_file_hash,
    compute_symbol_hash,
    update_hash_record,
    update_symbol_hash_record,
)
from pystdoc.engine import (
    FileLock,
    generate_static_symbol_doc,
    run_docgen,
)
from pystdoc.symbols import Symbol


class TestEngineAndCache(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cache_operations(self):
        data = {"purpose": "Test cache", "overview": "Overview"}
        saved_path = save_symbol_cache(
            self.test_dir, "src/main.c::fn.test", data
        )
        self.assertTrue(saved_path.exists())

        loaded = load_symbol_cache(self.test_dir, "src/main.c::fn.test")
        self.assertEqual(loaded, data)

        # Non-existent cache
        self.assertIsNone(
            load_symbol_cache(self.test_dir, "src/main.c::fn.unknown")
        )

        # Corrupted cache file
        saved_path.write_text("invalid json {", encoding="utf-8")
        self.assertIsNone(
            load_symbol_cache(self.test_dir, "src/main.c::fn.test")
        )

    def test_hasher_operations(self):
        f = self.test_dir / "file.txt"
        f.write_text("hello world\n", encoding="utf-8")

        f_hash = compute_file_hash(f)
        self.assertTrue(len(f_hash) == 64)

        sym_hash = compute_symbol_hash("int a = 1;", "int a", "A var")
        self.assertTrue(len(sym_hash) == 64)

        changed1, h_file1 = update_hash_record(
            self.test_dir, Path("file.txt"), f_hash
        )
        self.assertTrue(changed1)
        self.assertTrue(h_file1.exists())

        # Second update without change
        changed2, _ = update_hash_record(
            self.test_dir, Path("file.txt"), f_hash
        )
        self.assertFalse(changed2)

        # Symbol hash record update
        sym = Symbol(name="my_fn", kind="function", line_start=1, line_end=2)
        changed_s1, h_sym1 = update_symbol_hash_record(
            self.test_dir, Path("file.txt"), sym, sym_hash
        )
        self.assertTrue(changed_s1)
        self.assertTrue(h_sym1.exists())

        changed_s2, _ = update_symbol_hash_record(
            self.test_dir, Path("file.txt"), sym, sym_hash
        )
        self.assertFalse(changed_s2)

    def test_file_lock_acquisition_and_contention(self):
        lock_file = self.test_dir / "test.lock"
        with FileLock(lock_file):
            self.assertTrue(lock_file.exists())
            # Attempting second lock should exit with SystemExit(1)
            with self.assertRaises(SystemExit) as cm:
                with FileLock(lock_file):
                    pass
            self.assertEqual(cm.exception.code, 1)

    def test_generate_static_symbol_doc(self):
        sym_enum = Symbol(
            name="Status",
            kind="enum",
            line_start=1,
            line_end=5,
            signature="enum Status",
            doc="Doc comment",
        )
        doc_en = generate_static_symbol_doc(sym_enum, "English")
        self.assertIn("constant", doc_en["purpose"].lower())
        self.assertIn("Enumeration", doc_en["overview"])

        doc_ja = generate_static_symbol_doc(sym_enum, "Japanese")
        self.assertIn("列挙型", doc_ja["purpose"])
        self.assertIn("ステータス管理", doc_ja["overview"])

        sym_var = Symbol(
            name="g_count", kind="variable", line_start=1, line_end=1
        )
        doc_var = generate_static_symbol_doc(sym_var, "English")
        self.assertIn("variable", doc_var["purpose"].lower())

    def test_run_docgen_with_llm_mock(self):
        c_file = self.src_dir / "app.c"
        c_file.write_text(
            "int counter = 0;\n"
            "int helper() { return 42; }\n"
            "int main() { counter = helper(); return 0; }\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        mock_client.explain_symbol.return_value = {
            "purpose": "Mock purpose",
            "inputs": "None",
            "outputs": "Result",
            "overview": "Mock overview",
        }
        mock_client.refine_variable_top_down.return_value = {
            "significance": "Mock significance",
            "usage_scenario": "Mock scenario",
            "top_down_summary": "Mock summary",
        }

        with patch("pystdoc.engine.LLMClient", return_value=mock_client):
            ret = run_docgen(
                target_dir=self.test_dir,
                use_llm=True,
                host="http://localhost:11434",
                concurrency=2,
                language="English",
            )
            self.assertEqual(ret, 0)
            self.assertTrue((self.test_dir / ".pystdoc" / "index.db").exists())


if __name__ == "__main__":
    unittest.main()
