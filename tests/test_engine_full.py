#!/usr/bin/env python3
"""Coverage booster for engine, call_graph, parsers, and doc_writer."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pystdoc.symbols import Symbol
from pystdoc.engine import run_docgen
from pystdoc.call_graph import (
    flatten_symbols,
    link_variables_to_functions,
)
from pystdoc.doc_writer import (
    format_symbol_section,
    write_individual_symbol_docs,
)
from pystdoc.parser_clang import _parse_cursor
from pystdoc.parser_python import parse_python_file
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.hasher import update_hash_record, update_symbol_hash_record
from pystdoc.llm_client import LLMError


class TestEngineFull(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_run_docgen_empty_and_invalid_dir(self):
        # 1. Invalid directory returns 1
        ret_inv = run_docgen(
            target_dir=Path("/non_existent_pystdoc_dir_12345"),
            use_llm=False,
        )
        self.assertEqual(ret_inv, 1)

        # 2. Empty directory (0 scanned files) returns 0
        ret_empty = run_docgen(
            target_dir=self.test_dir,
            use_llm=False,
        )
        self.assertEqual(ret_empty, 0)

    def test_run_docgen_strict_llm_errors(self):
        # Setup source file with function and variable
        c_file = self.src_dir / "calc.c"
        c_file.write_text(
            "int g_flag = 1;\n"
            "int compute() { return g_flag; }\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        mock_client.explain_symbol.side_effect = LLMError("Pass 1 error")
        mock_client.refine_variable_top_down.side_effect = LLMError(
            "Pass 2 error"
        )

        with patch("pystdoc.engine.LLMClient", return_value=mock_client):
            # Pass 1 failure in strict mode returns 1
            ret = run_docgen(
                target_dir=self.test_dir,
                use_llm=True,
                allow_fallback=False,
            )
            self.assertEqual(ret, 1)

    def test_call_graph_nested_line_linking(self):
        c_file = self.src_dir / "nested.c"
        c_file.write_text(
            "void outer() {\n"
            "    int inner_var = 10;\n"
            "    (void)inner_var;\n"
            "}\n",
            encoding="utf-8",
        )
        sym_fn = Symbol(
            name="outer", kind="function", line_start=1, line_end=4
        )
        sym_var = Symbol(
            name="inner_var", kind="variable", line_start=2, line_end=2
        )

        nodes = flatten_symbols(
            [sym_fn, sym_var], Path("src/nested.c"), c_file
        )
        link_variables_to_functions(nodes)
        self.assertTrue(len(nodes[1].symbol.referencing_functions) >= 1)
        self.assertIn("outer", nodes[1].symbol.referencing_functions[0])

    def test_doc_writer_all_kinds_formatting(self):
        dummy_file = self.src_dir / "kinds.cpp"
        dummy_file.write_text("class Test {};\n", encoding="utf-8")

        all_kinds = (
            "constructor", "destructor", "field", "enum_constant", "macro"
        )
        for k in all_kinds:
            sym = Symbol(
                name=f"sym_{k}",
                kind=k,
                line_start=1,
                line_end=1,
                signature=f"{k}_sig",
                purpose=f"Purpose of {k}",
            )
            sec = format_symbol_section(
                sym, dummy_file, level=2, language="Japanese"
            )
            self.assertIn(f"Purpose of {k}", sec)

    def test_doc_writer_recursive_children(self):
        parent = Symbol(
            name="ParentClass", kind="class", line_start=1, line_end=10
        )
        child = Symbol(
            name="childMethod", kind="method", line_start=2, line_end=5
        )
        parent.children.append(child)

        created = write_individual_symbol_docs(
            self.test_dir,
            Path("src/classes.py"),
            [parent],
        )
        self.assertTrue(len(created) >= 2)

    def test_parser_clang_unnamed_cursor(self):
        mock_cursor = MagicMock()
        mock_cursor.spelling = ""
        mock_cursor.displayname = ""
        mock_cursor.kind = 1  # clang CursorKind
        res = _parse_cursor(mock_cursor, self.src_dir / "test.c")
        self.assertIsNone(res)

    def test_parser_python_src_path_resolution(self):
        py_file = self.src_dir / "service.py"
        py_file.write_text("def serve(): pass\n", encoding="utf-8")

        # Parse without base_dir to trigger src parts index resolution
        symbols = parse_python_file(py_file, base_dir=None)
        self.assertTrue(len(symbols) >= 1)
        self.assertIn("service.serve", symbols[0].fqdn)

    def test_compilation_db_corrupted_and_output_flags(self):
        build_dir = self.test_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        bad_json = build_dir / "compile_commands.json"
        bad_json.write_text("invalid json {", encoding="utf-8")

        cdb = CompilationDatabase(db_path=bad_json, target_dir=self.test_dir)
        self.assertEqual(cdb.flags_map, {})

    def test_hasher_corrupted_hash_files(self):
        f = self.test_dir / "file.c"
        f.write_text("int x = 1;\n", encoding="utf-8")

        # Corrupt existing hash files
        hash_f = self.test_dir / ".pystdoc" / "documents" / "file.c.hash"
        hash_f.parent.mkdir(parents=True, exist_ok=True)
        hash_f.write_text("old_hash", encoding="utf-8")

        sym = Symbol(name="x", kind="variable", line_start=1, line_end=1)
        docgen_doc = self.test_dir / ".pystdoc" / "documents"
        sym_hash_f = docgen_doc / "file.c.var.x.hash"
        sym_hash_f.write_text("old_sym_hash", encoding="utf-8")

        # Updates should succeed gracefully
        ch1, _ = update_hash_record(self.test_dir, Path("file.c"), "new_hash")
        self.assertTrue(ch1)

        ch2, _ = update_symbol_hash_record(
            self.test_dir, Path("file.c"), sym, "new_sym_hash"
        )
        self.assertTrue(ch2)

    def test_run_docgen_cache_hit_and_unknown_ext(self):
        # 1. Unknown extension file
        (self.src_dir / "ignored.xyz").write_text(
            "dummy data", encoding="utf-8"
        )
        # 2. Valid source file
        c_file = self.src_dir / "cached.c"
        c_file.write_text(
            "int g_var = 10;\n"
            "int run() { return g_var; }\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        mock_client.explain_symbol.return_value = {
            "purpose": "Calculates",
            "inputs_note": "None",
            "outputs_note": "None",
            "overview": "Overview",
        }
        mock_client.refine_variable_top_down.return_value = {
            "purpose": "Global state",
            "inputs_note": "None",
            "outputs_note": "None",
            "overview": "Overview",
        }

        with patch("pystdoc.engine.LLMClient", return_value=mock_client):
            # First run: writes cache
            ret1 = run_docgen(target_dir=self.test_dir, use_llm=True)
            self.assertEqual(ret1, 0)

            # Second run: hits cache
            ret2 = run_docgen(target_dir=self.test_dir, use_llm=True)
            self.assertEqual(ret2, 0)


if __name__ == "__main__":
    unittest.main()
