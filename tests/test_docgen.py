#!/usr/bin/env python3
"""Unit tests for docgen: DAG levels, SQLite index, Compilation DB, FQDN resolution, and multi-language support."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pystdoc.call_graph import (
    SymbolNode,
    flatten_symbols,
    order_symbols_by_levels,
    tarjan_scc,
)
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.db import DocgenDB
from pystdoc.engine import run_docgen
from pystdoc.llm_client import LLMClient, normalize_host_url
from pystdoc.parser_clang import parse_clang_file
from pystdoc.parser_python import parse_python_file
from pystdoc.symbols import Symbol


class TestDocgen(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_tarjan_scc_mutual_recursion(self):
        adj = {
            "fn_a": {"fn_b"},
            "fn_b": {"fn_a", "fn_c"},
            "fn_c": set(),
        }
        sccs = tarjan_scc(["fn_a", "fn_b", "fn_c"], adj)
        scc_sets = [set(s) for s in sccs]
        self.assertIn({"fn_a", "fn_b"}, scc_sets)
        self.assertIn({"fn_c"}, scc_sets)

    def test_dag_levels_ordering(self):
        sym_type = Symbol(name="Point", kind="struct", line_start=1, line_end=5)
        sym_leaf = Symbol(name="leaf", kind="function", line_start=6, line_end=8, callees=[])
        sym_caller = Symbol(name="caller", kind="function", line_start=9, line_end=12, callees=["leaf"])

        dummy_path = self.src_dir / "sample.c"
        nodes = flatten_symbols([sym_type, sym_leaf, sym_caller], Path("src/sample.c"), dummy_path)

        levels = order_symbols_by_levels(nodes)
        self.assertTrue(len(levels) >= 2)
        level0_names = [n.symbol.name for n in levels[0]]
        self.assertIn("Point", level0_names)

        level1_names = [n.symbol.name for n in levels[1]]
        self.assertIn("leaf", level1_names)

        level2_names = [n.symbol.name for n in levels[2]]
        self.assertIn("caller", level2_names)

    def test_compilation_database_flags(self):
        build_dir = self.test_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        comp_json = build_dir / "compile_commands.json"
        comp_json.write_text(
            """[
              {
                "directory": "%s",
                "command": "gcc -Iinclude -DTEST_MACRO=1 -c src/main.c -o build/main.o",
                "file": "src/main.c"
              }
            ]"""
            % str(self.test_dir),
            encoding="utf-8",
        )

        cdb = CompilationDatabase(db_path=comp_json, target_dir=self.test_dir)
        flags = cdb.get_flags_for_file(self.src_dir / "main.c")
        self.assertTrue(any("-DTEST_MACRO=1" in f for f in flags))
        self.assertTrue(any("-I" in f for f in flags))

    def test_python_fqdn_extraction(self):
        py_file = self.src_dir / "client.py"
        py_file.write_text(
            "class APIClient:\n"
            "    def fetch(self, url: str) -> dict:\n"
            "        return {}\n",
            encoding="utf-8",
        )

        symbols = parse_python_file(py_file, base_dir=self.test_dir)
        self.assertEqual(len(symbols), 1)
        self.assertEqual(symbols[0].name, "APIClient")
        self.assertEqual(symbols[0].fqdn, "src.client.APIClient")
        self.assertEqual(symbols[0].children[0].name, "fetch")
        self.assertEqual(symbols[0].children[0].fqdn, "src.client.APIClient.fetch")

    def test_sqlite_db_operations(self):
        db_path = self.test_dir / ".docgen" / "index.db"
        db = DocgenDB(db_path)

        is_changed = db.update_file_hash("src/test.c", "hash_v1")
        self.assertTrue(is_changed)
        is_changed_again = db.update_file_hash("src/test.c", "hash_v1")
        self.assertFalse(is_changed_again)

        db.save_symbol_cache(
            "src/test.c::fn.compute",
            {"purpose": "Calculates math.", "overview": "Overview note."},
        )
        loaded = db.load_symbol_cache("src/test.c::fn.compute")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["purpose"], "Calculates math.")
        db.close()

    def test_full_pipeline_multi_language(self):
        c_file = self.src_dir / "sample.c"
        c_file.write_text(
            "#include <stdio.h>\n"
            "int add(int a, int b) {\n"
            "    return a + b;\n"
            "}\n"
            "int main(int argc, char **argv) {\n"
            "    int val = 10;\n"
            "    return add(val, 2);\n"
            "}\n",
            encoding="utf-8",
        )

        # Default English
        res_en = run_docgen(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
            language="English",
        )
        self.assertEqual(res_en, 0)
        doc_en = (self.test_dir / ".docgen" / "documents" / "src" / "sample.c.md").read_text(encoding="utf-8")
        self.assertIn("## 1. Design Intent & Purpose", doc_en)

        # Japanese option
        res_ja = run_docgen(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
            language="Japanese",
            force=True,
        )
        self.assertEqual(res_ja, 0)
        doc_ja = (self.test_dir / ".docgen" / "documents" / "src" / "sample.c.md").read_text(encoding="utf-8")
        self.assertIn("## 1. Design Intent & Purpose", doc_ja)

    def test_llm_client_host_and_token(self):
        self.assertEqual(normalize_host_url("127.0.0.1:11434"), "http://127.0.0.1:11434/v1")
        self.assertEqual(normalize_host_url("http://localhost:8000"), "http://localhost:8000/v1")
        self.assertEqual(normalize_host_url("https://api.openai.com/v1"), "https://api.openai.com/v1")

        client = LLMClient(host="127.0.0.1:11434", token="sk-test-token", context_size=8192)
        self.assertEqual(client.token, "sk-test-token")
        self.assertEqual(client.context_size, 8192)


if __name__ == "__main__":
    unittest.main()
