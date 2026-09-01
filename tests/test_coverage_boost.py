#!/usr/bin/env python3
"""Comprehensive coverage booster tests for remaining branch & error paths."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pystdoc.symbols import Symbol, Parameter, get_kind_prefix
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.parser_python import parse_python_file
from pystdoc.parser_clang import parse_clang_file
from pystdoc.doc_writer import (
    write_symbol_doc,
    write_individual_symbol_docs,
    format_symbol_section,
)
from pystdoc.design_engine import run_design_generation
from pystdoc.report_engine import generate_readme_doc
from pystdoc.call_graph import (
    flatten_symbols,
    link_variables_to_functions,
    build_callee_context_summary,
)
from pystdoc.hasher import update_hash_record
from pystdoc.llm_client import LLMError


class TestCoverageBoost(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_symbols_prefixes(self):
        self.assertEqual(get_kind_prefix("constant"), "const")
        self.assertEqual(get_kind_prefix("macro"), "const")
        self.assertEqual(get_kind_prefix("unknown_kind"), "sym")

        sym = Symbol(
            name="test",
            kind="custom",
            line_start=1,
            line_end=1,
        )
        self.assertEqual(sym.kind_prefix, "sym")

    def test_compilation_db_branches(self):
        build_dir = self.test_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        comp_json = build_dir / "compile_commands.json"

        # Test with arguments list and -isystem flags
        data = [
            {
                "directory": str(self.test_dir),
                "arguments": [
                    "clang", "-c", "src/main.c",
                    "-isystem", "include/sys",
                    "-I", "include/app",
                    "-o", "main.o",
                ],
                "file": "src/main.c",
            },
            {
                "directory": str(self.test_dir),
                # No file
            },
        ]
        comp_json.write_text(json.dumps(data), encoding="utf-8")

        cdb = CompilationDatabase(db_path=comp_json, target_dir=self.test_dir)
        flags = cdb.get_flags_for_file(self.src_dir / "main.c")
        self.assertTrue(any("-isystem" in f for f in flags))

        # Default fallback for unknown file
        default_flags = cdb.get_flags_for_file(self.src_dir / "other.cpp")
        self.assertTrue(any("-std=c++17" in f for f in default_flags))

    def test_parser_python_advanced_features(self):
        py_file = self.src_dir / "async_app.py"
        py_file.write_text(
            "async def fetch_async(url: str) -> dict:\n"
            "    print(url)\n"
            "    return {}\n"
            "\n"
            "class Server:\n"
            "    def start(self):\n"
            "        self.fetch_async('http://test')\n",
            encoding="utf-8",
        )

        symbols = parse_python_file(py_file, base_dir=self.test_dir)
        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[0].kind, "async_function")
        self.assertEqual(symbols[0].return_type, "dict")
        self.assertEqual(symbols[1].kind, "class")
        self.assertEqual(len(symbols[1].children), 1)

        # Invalid Python syntax file
        broken_py = self.src_dir / "broken.py"
        broken_py.write_text("def broken(: invalid", encoding="utf-8")
        self.assertEqual(parse_python_file(broken_py), [])

    def test_parser_clang_nested_types(self):
        c_file = self.src_dir / "structs.c"
        c_file.write_text(
            "struct Point {\n"
            "    int x;\n"
            "    int y;\n"
            "};\n"
            "enum State {\n"
            "    IDLE,\n"
            "    ACTIVE\n"
            "};\n",
            encoding="utf-8",
        )

        # Without comp_db explicitly provided
        symbols = parse_clang_file(c_file, comp_db=None)
        self.assertTrue(len(symbols) >= 2)
        names = [s.name for s in symbols]
        self.assertIn("Point", names)
        self.assertIn("State", names)

    def test_call_graph_complex_linking_and_summary(self):
        c_file = self.src_dir / "app.c"
        c_file.write_text(
            "int g_total = 0;\n"
            "void add_to_total() {\n"
            "    g_total += calc();\n"
            "}\n",
            encoding="utf-8",
        )

        sym_var = Symbol(
            name="g_total", kind="variable", line_start=1, line_end=1
        )
        sym_fn = Symbol(
            name="add_to_total",
            kind="function",
            line_start=2,
            line_end=4,
            callees=["calc"],
        )

        nodes = flatten_symbols(
            [sym_var, sym_fn], Path("src/app.c"), c_file
        )

        link_variables_to_functions(nodes)
        self.assertTrue(len(nodes[0].symbol.referencing_functions) >= 1)
        self.assertIn("add_to_total", nodes[0].symbol.referencing_functions[0])

        # Test context summary building
        calc_sym = Symbol(
            name="calc",
            kind="function",
            line_start=6,
            line_end=8,
            purpose="Does math",
            overview="Fast calculation",
        )
        caller_sym = Symbol(
            name="caller",
            kind="function",
            line_start=9,
            line_end=12,
            callees=["calc"],
        )
        nodes_list = flatten_symbols(
            [calc_sym, caller_sym], Path("app.c"), self.src_dir / "app.c"
        )
        caller_node = nodes_list[1]
        calc_node = nodes_list[0]
        caller_node.direct_callee_ids.add(calc_node.unique_id)
        caller_node.direct_callee_ids.add("unknown_callee_id")

        nodes_dict = {
            calc_node.unique_id: calc_node,
            caller_node.unique_id: caller_node,
        }
        summary = build_callee_context_summary(caller_node, nodes_dict)
        self.assertIn("Does math", summary)

    def test_doc_writer_individual_symbol_docs(self):
        param = Parameter(
            name="code", type_hint="int", description="Status code"
        )
        sym = Symbol(
            name="process",
            kind="function",
            line_start=1,
            line_end=10,
            signature="void process(int code)",
            purpose="Process task",
            inputs_note="Input code",
            outputs_note="None",
            overview="Task processor",
            parameters=[param],
            return_type="void",
        )
        dummy_path = self.src_dir / "proc.c"
        dummy_path.write_text("void process(int code) {}\n", encoding="utf-8")

        write_symbol_doc(
            target_dir=self.test_dir,
            rel_path=Path("src/proc.c"),
            file_hash="dummy_hash_123",
            symbols=[sym],
        )
        write_individual_symbol_docs(
            target_dir=self.test_dir,
            rel_path=Path("src/proc.c"),
            symbols=[sym],
        )

        doc_file = (
            self.test_dir
            / ".docgen"
            / "documents"
            / "src"
            / "proc.c.fn.process.md"
        )
        self.assertTrue(doc_file.exists())
        content = doc_file.read_text(encoding="utf-8")
        self.assertIn("Process task", content)

    def test_designgen_with_llm_mock(self):
        # Prepare dummy symbol doc first
        doc_dir = self.test_dir / ".docgen" / "documents" / "src"
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "mod.c.md").write_text(
            "# src/mod.c\n## Symbols\n- `process`: Does work\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        mock_client.chat_completion.return_value = (
            "## Architecture Overview\nSystem synthesized."
        )

        with patch(
            "pystdoc.design_engine.LLMClient", return_value=mock_client
        ):
            ret = run_design_generation(
                target_dir=self.test_dir,
                use_llm=True,
                host="http://localhost:11434",
                language="English",
                force=True,
            )
            self.assertEqual(ret, 0)
            self.assertTrue(
                (self.test_dir / ".docgen" / "design" / "overview.md").exists()
            )

    def test_report_engine_llm_fallback_error(self):
        mock_client = MagicMock()
        mock_client.chat_completion.side_effect = LLMError("Server down")

        with self.assertRaises(LLMError):
            generate_readme_doc(
                target_dir=self.test_dir,
                llm_client=mock_client,
                allow_fallback=False,
            )

    def test_doc_writer_languages_and_snippets(self):
        from pystdoc.doc_writer import (
            normalize_language,
            get_code_language,
            get_code_snippet,
        )
        self.assertEqual(normalize_language(None), "English")
        self.assertEqual(normalize_language("ja"), "Japanese")
        self.assertEqual(normalize_language("zh"), "Chinese")
        self.assertEqual(normalize_language("es"), "Spanish")
        self.assertEqual(normalize_language("german"), "German")

        self.assertEqual(get_code_language(".cpp"), "cpp")
        self.assertEqual(get_code_language(".py"), "python")
        self.assertEqual(get_code_language(".sh"), "bash")
        self.assertEqual(get_code_language(".rs"), "rust")
        self.assertEqual(get_code_language(".txt"), "text")

        # Non-existent file for snippet
        non_file = self.test_dir / "non_existent.c"
        self.assertEqual(get_code_snippet(non_file, 1, 10), "")

    def test_call_graph_scc_and_nested_symbols(self):
        parent_sym = Symbol(
            name="Outer",
            kind="class",
            line_start=1,
            line_end=10,
        )
        child_sym = Symbol(
            name="Inner",
            kind="struct",
            line_start=2,
            line_end=5,
        )
        parent_sym.children.append(child_sym)

        nodes = flatten_symbols(
            [parent_sym], Path("test.py"), self.src_dir / "test.py"
        )
        self.assertEqual(len(nodes), 2)
        self.assertIn("Outer.Inner", nodes[1].unique_id)

        # SCC mutual recursion summary test
        node_a = nodes[0]
        node_b = nodes[1]
        node_a.scc_group_ids = [node_b.unique_id]
        node_b.symbol.purpose = "Recursive helper"
        nodes_dict = {node_b.unique_id: node_b}

        summary = build_callee_context_summary(node_a, nodes_dict)
        self.assertIn("Mutual Recursion", summary)
        self.assertIn("Inner", summary)

    def test_engine_static_doc_typedef_and_other(self):
        from pystdoc.engine import generate_static_symbol_doc
        sym_type = Symbol(
            name="UserID",
            kind="typedef",
            line_start=1,
            line_end=1,
            signature="typedef int UserID;",
        )
        doc_en = generate_static_symbol_doc(sym_type, "English")
        self.assertIn("alias", doc_en["purpose"].lower())

        doc_ja = generate_static_symbol_doc(sym_type, "Japanese")
        self.assertIn("エイリアス", doc_ja["purpose"])

        # Test struct
        sym_struct = Symbol(
            name="Point", kind="struct", line_start=1, line_end=5
        )
        doc_struct_en = generate_static_symbol_doc(sym_struct, "English")
        self.assertIn("data model", doc_struct_en["purpose"].lower())
        doc_struct_ja = generate_static_symbol_doc(sym_struct, "Japanese")
        self.assertIn("データモデル", doc_struct_ja["purpose"])

        # Test var
        sym_var = Symbol(
            name="g_count", kind="variable", line_start=1, line_end=1
        )
        doc_var_en = generate_static_symbol_doc(sym_var, "English")
        self.assertIn("state data", doc_var_en["purpose"].lower())
        doc_var_ja = generate_static_symbol_doc(sym_var, "Japanese")
        self.assertIn("状態データ", doc_var_ja["purpose"])

        sym_custom = Symbol(
            name="CustomSym",
            kind="unknown_kind",
            line_start=1,
            line_end=1,
        )
        doc_custom = generate_static_symbol_doc(sym_custom, "English")
        self.assertIn("CustomSym", doc_custom["purpose"])

    def test_doc_writer_globals_formatting(self):
        dummy_file = self.src_dir / "globals.c"
        dummy_file.write_text("int g_a = 1;\n", encoding="utf-8")
        sym = Symbol(
            name="fn_with_globals",
            kind="function",
            line_start=1,
            line_end=5,
            signature="void fn_with_globals()",
            purpose="Uses globals",
            callees=["calc_helper"],
            inputs_note="Custom inputs",
            outputs_note="Custom outputs",
        )
        sec_en = format_symbol_section(
            sym, dummy_file, level=1, language="English"
        )
        self.assertIn("calc_helper", sec_en)
        self.assertIn("Custom inputs", sec_en)
        self.assertIn("Custom outputs", sec_en)

        sec_ja = format_symbol_section(
            sym, dummy_file, level=1, language="Japanese"
        )
        self.assertIn("calc_helper", sec_ja)
        self.assertIn("Custom inputs", sec_ja)

    def test_compilation_db_command_string_and_name_lookup(self):
        build_dir = self.test_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        comp_json = build_dir / "compile_commands.json"
        data = [
            {
                "directory": str(self.test_dir),
                "command": "gcc -Iinclude/app -c src/tool.c -o build/tool.o",
                "file": "src/tool.c",
            }
        ]
        comp_json.write_text(json.dumps(data), encoding="utf-8")

        cdb = CompilationDatabase(db_path=comp_json, target_dir=self.test_dir)
        # Search by file path name fallback
        flags = cdb.get_flags_for_file(Path("/outside/project/tool.c"))
        self.assertTrue(any("-I" in f for f in flags))

    def test_hasher_exception_paths(self):
        # Create existing hash file
        hash_f = self.test_dir / ".docgen" / "documents" / "bad.c.hash"
        hash_f.parent.mkdir(parents=True, exist_ok=True)
        hash_f.write_text("old_hash", encoding="utf-8")

        with patch.object(
            Path, "read_text", side_effect=Exception("Disk read error")
        ):
            ch, _ = update_hash_record(self.test_dir, Path("bad.c"), "dummy")
            self.assertTrue(ch)

            from pystdoc.hasher import update_symbol_hash_record
            sym = Symbol(
                name="dummy_var", kind="variable", line_start=1, line_end=1
            )
            ch_s, _ = update_symbol_hash_record(
                self.test_dir, Path("bad.c"), sym, "dummy_hash"
            )
            self.assertTrue(ch_s)

    def test_doc_writer_extract_symbols_all_languages(self):
        from pystdoc.doc_writer import extract_symbols
        c_f = self.src_dir / "t.c"
        c_f.write_text("int f() { return 0; }\n", encoding="utf-8")
        self.assertTrue(len(extract_symbols(c_f)) >= 1)

        py_f = self.src_dir / "t.py"
        py_f.write_text("def f(): pass\n", encoding="utf-8")
        self.assertTrue(len(extract_symbols(py_f)) >= 1)

        sh_f = self.src_dir / "t.sh"
        sh_f.write_text("f() { echo 1; }\n", encoding="utf-8")
        self.assertTrue(len(extract_symbols(sh_f)) >= 1)

        unknown_f = self.src_dir / "t.unknown"
        unknown_f.write_text("nothing\n", encoding="utf-8")
        self.assertEqual(extract_symbols(unknown_f), [])

    def test_compilation_db_dash_o_flag_skip(self):
        build_dir = self.test_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        comp_json = build_dir / "compile_commands.json"
        data = [
            {
                "directory": str(self.test_dir),
                "command": "gcc -I/usr/include -ooutput.o -c src/tool2.c",
                "file": "src/tool2.c",
            }
        ]
        comp_json.write_text(json.dumps(data), encoding="utf-8")
        cdb = CompilationDatabase(db_path=comp_json, target_dir=self.test_dir)
        flags = cdb.get_flags_for_file(self.src_dir / "tool2.c")
        self.assertFalse(any(f == "-ooutput.o" for f in flags))

    def test_design_generation_pipeline_strict_error(self):
        mock_client = MagicMock()
        mock_client.chat_completion.side_effect = LLMError("Design error")
        dummy_md = self.test_dir / ".docgen" / "documents" / "sample.c.md"
        dummy_md.parent.mkdir(parents=True, exist_ok=True)
        dummy_md.write_text(
            "# doc\n- **Symbol Kind**: function\n", encoding="utf-8"
        )

        with patch(
            "pystdoc.design_engine.LLMClient", return_value=mock_client
        ):
            with self.assertRaises(LLMError):
                run_design_generation(
                    target_dir=self.test_dir,
                    use_llm=True,
                    allow_fallback=False,
                )


if __name__ == "__main__":
    unittest.main()
