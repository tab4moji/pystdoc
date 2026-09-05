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
    SymbolNode,
    flatten_symbols,
    link_variables_to_functions,
    build_callee_context_summary,
)
from pystdoc.engine import run_docgen
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

    def test_docgen_pass2_prefixed_var_node(self):
        c_file = self.src_dir / "mod_vars.c"
        c_file.write_text(
            "int g_val = 10;\nvoid run() { g_val++; }\n", encoding="utf-8"
        )
        mock_client = MagicMock()
        mock_client.explain_symbol.return_value = {
            "role": "Mod value",
            "purpose": "State",
            "overview": "Var overview",
        }
        mock_client.refine_variable_top_down.return_value = {
            "role": "Global mod state",
            "usage_scenario": "Updated in run",
            "top_down_summary": "Summary",
        }
        with patch("pystdoc.engine.LLMClient", return_value=mock_client):
            with patch("pystdoc.engine.flatten_symbols") as mock_flat:
                sym_var = Symbol(
                    name="val", kind="variable", line_start=1, line_end=1
                )
                sym_fn = Symbol(
                    name="run",
                    kind="function",
                    line_start=2,
                    line_end=2,
                    purpose="Runner",
                )
                node_var = SymbolNode(
                    symbol=sym_var,
                    rel_path=Path("src/mod_vars.c"),
                    full_path=c_file,
                    unique_id="src/mod_vars.c::var.Outer.val",
                    fqdn="src.mod_vars.Outer.val",
                )
                node_fn = SymbolNode(
                    symbol=sym_fn,
                    rel_path=Path("src/mod_vars.c"),
                    full_path=c_file,
                    unique_id="src/mod_vars.c::fn.run",
                    fqdn="src.mod_vars.run",
                )
                mock_flat.return_value = [node_var, node_fn]
                ret = run_docgen(
                    target_dir=self.test_dir,
                    use_llm=True,
                    allow_fallback=True,
                    force=True,
                )
                self.assertEqual(ret, 0)

    def test_adapter_coverage_boost(self):
        from pystdoc.adapters.base import (
            BaseLanguageAdapter,
            LanguageAdapterRegistry,
            build_fqdn,
            calculate_block_end_line,
            clean_docstring,
        )
        from pystdoc.adapters.clang_adapter import ClangAdapter
        from pystdoc.adapters.generic_adapter import GenericAdapter
        from pystdoc.adapters.java_adapter import (
            _extract_java_callees,
            _format_type,
        )
        from pystdoc.adapters.kotlin_adapter import (
            _extract_preceding_doc,
            _format_type_node,
        )
        from pystdoc.adapters.python_adapter import PythonAdapter
        from pystdoc.parser_java import parse_java_file
        from pystdoc.parser_kotlin import parse_kotlin_file
        import javalang
        import kopyt

        # 1. BaseLanguageAdapter abstract methods
        class MinimalAdapter(BaseLanguageAdapter):
            @property
            def name(self):
                return "minimal"

            @property
            def supported_extensions(self):
                return ()

            @property
            def default_code_language(self):
                return "text"

            def parse(self, file_path, comp_db=None, base_dir=None):
                return []

        min_ad = MinimalAdapter()
        self.assertEqual(min_ad.name, "minimal")
        self.assertEqual(min_ad.default_code_language, "text")

        # 2. Registry fallback search
        class WildcardAdapter(BaseLanguageAdapter):
            @property
            def name(self):
                return "wildcard"

            @property
            def supported_extensions(self):
                return ()

            @property
            def default_code_language(self):
                return "wild"

            def can_handle(self, file_path):
                return file_path.name.endswith(".custom_ext")

            def parse(self, file_path, comp_db=None, base_dir=None):
                return []

        reg = LanguageAdapterRegistry()
        w_ad = WildcardAdapter()
        reg.register(w_ad)
        found = reg.get_adapter_for_file(Path("my_file.custom_ext"))
        self.assertEqual(found, w_ad)

        # 3. docstring & line calculation branches
        doc_c = "/* Simple C comment */"
        self.assertEqual(clean_docstring(doc_c), "Simple C comment")
        doc_slash = "// Line 1\n// Line 2"
        self.assertEqual(clean_docstring(doc_slash), "Line 1\nLine 2")

        lines = [
            "int a = 1; /* inline comment */ int b = 2;",
            'String s = "\\"escaped\\"";',
            "void foo() {",
            "    if (true) {",
            "    }",
            "}",
        ]
        self.assertEqual(calculate_block_end_line(lines, 1), 1)
        self.assertEqual(calculate_block_end_line(lines, 2), 2)
        self.assertEqual(calculate_block_end_line(lines, 3), 6)
        self.assertEqual(calculate_block_end_line(lines, 0), 1)

        self.assertEqual(build_fqdn([], "test"), "test")
        self.assertEqual(build_fqdn(["a"], "b"), "a.b")

        # 4. Clang, Python, Generic properties
        clang_ad = ClangAdapter()
        self.assertEqual(clang_ad.name, "clang")
        self.assertEqual(clang_ad.default_code_language, "c")

        py_ad = PythonAdapter()
        self.assertEqual(py_ad.name, "python")
        self.assertEqual(py_ad.default_code_language, "python")

        gen_ad = GenericAdapter()
        self.assertEqual(gen_ad.name, "generic")
        self.assertEqual(gen_ad.default_code_language, "bash")
        self.assertEqual(gen_ad.get_code_language(".txt"), "text")
        self.assertEqual(gen_ad.get_code_language(".sh"), "bash")
        self.assertEqual(gen_ad.get_code_language(".rs"), "rust")

        # 5. Java type and AST branches
        class MockTypeArgNamed:
            name = "NamedType"

        class MockTypeArgStr:
            def __str__(self):
                return "StrType"

        class MockTypeNodeWithArgs:
            name = "CustomMap"
            arguments = [MockTypeArgNamed(), MockTypeArgStr()]
            dimensions = None
            sub_type = None

        self.assertEqual(
            _format_type(MockTypeNodeWithArgs()),
            "CustomMap<NamedType, StrType>",
        )

        class MockSubtype:
            name = "Sub"
            arguments = None
            dimensions = None
            sub_type = None

        class MockTypeWithSub:
            name = "Outer"
            arguments = None
            dimensions = None
            sub_type = MockSubtype()

        self.assertEqual(_format_type(MockTypeWithSub()), "Outer.Sub")

        # ExplicitConstructorInvocation with qualifier
        java_src_exp = """
        class SuperBase {
            class Inner {
                Inner() {
                    SuperBase.super();
                }
            }
        }
        """
        tree_exp = javalang.parse.parse(java_src_exp)
        inner_cls = tree_exp.types[0].body[0]
        callees_exp = _extract_java_callees(inner_cls.constructors[0])
        self.assertIn("SuperBase", callees_exp)

        # Java Interface and Annotation declarations
        java_iface_src = """package com.example;
        public @interface MyAnno {}
        interface MyIface { void run(); }
        """
        j_iface_file = self.test_dir / "Types.java"
        j_iface_file.write_text(java_iface_src, encoding="utf-8")
        iface_syms = parse_java_file(j_iface_file)
        self.assertEqual(len(iface_syms), 2)
        self.assertEqual(iface_syms[0].kind, "class")
        self.assertEqual(iface_syms[1].kind, "class")

        # 6. Kotlin branches
        class MockTypeWrapper:
            subtype = kopyt.node.NullableType(None, None, "?")

        self.assertEqual(_format_type_node(MockTypeWrapper()), "Any?")

        class MockNamedType:
            name = "NamedKotlinType"

        self.assertEqual(_format_type_node(MockNamedType()), "NamedKotlinType")

        class MockArbitraryType:
            def __str__(self):
                return "ArbitraryTypeStr"

        self.assertEqual(
            _format_type_node(MockArbitraryType()), "ArbitraryTypeStr"
        )

        kt_preceding_lines = [
            "/**",
            " * Doc comment",
            " */",
            "@Anno1",
            "@Anno2",
            "fun annotatedFunc() {}",
        ]
        doc_extracted = _extract_preceding_doc(kt_preceding_lines, 6)
        self.assertEqual(doc_extracted, "Doc comment")

        # Kotlin package with sequence and header branches
        kt_full = """package com.pkg.sub
        class Outer {
            object MyObj {
                val prop: Int = 1
            }
        }
        """
        kt_full_file = self.test_dir / "Outer.kt"
        kt_full_file.write_text(kt_full, encoding="utf-8")
        kt_full_syms = parse_kotlin_file(kt_full_file)
        self.assertEqual(len(kt_full_syms), 1)
        self.assertEqual(kt_full_syms[0].children[0].kind, "class")

        # Test Kotlin package header string fallback
        class MockPackageHeader:
            header = "package com.custom.pkg"
            name = None
            sequence = None

        class MockTreeWithHeader:
            package = MockPackageHeader()
            declarations = []

        with patch("kopyt.Parser.parse", return_value=MockTreeWithHeader()):
            kt_hdr_file = self.test_dir / "Hdr.kt"
            kt_hdr_file.write_text("fun dummy() {}", encoding="utf-8")
            self.assertEqual(parse_kotlin_file(kt_hdr_file), [])

        class MockPkgSeqItem:
            value = "seqpkg"

        class MockPkgSeq:
            name = None
            sequence = [MockPkgSeqItem()]

        class MockTreeSeq:
            package = MockPkgSeq()
            declarations = []

        with patch("kopyt.Parser.parse", return_value=MockTreeSeq()):
            self.assertEqual(parse_kotlin_file(kt_hdr_file), [])

        # Java this() and super() constructor calls
        java_ctors_src = """package com.example;
        class Base { Base() {} }
        class Sub extends Base {
            Sub() { super(); }
            Sub(int x) { this(); }
        }
        """
        j_ctor_file = self.test_dir / "Ctors.java"
        j_ctor_file.write_text(java_ctors_src, encoding="utf-8")
        ctor_syms = parse_java_file(j_ctor_file)
        self.assertEqual(len(ctor_syms), 2)
        sub_cls = ctor_syms[1]
        sub_ctors = [c for c in sub_cls.children if c.kind == "constructor"]
        self.assertEqual(len(sub_ctors), 2)
        self.assertIn("super", sub_ctors[0].callees)
        self.assertIn("this", sub_ctors[1].callees)

        # Java field with missing decl position fallback
        class MockDecl:
            name = "x"
            position = None

        class MockField:
            type = "int"
            documentation = None
            modifiers = []
            declarators = [MockDecl()]
            position = None

        class MockClassDecl:
            name = "FieldFallback"
            position = None
            documentation = None
            modifiers = []
            fields = [MockField()]
            body = []

        class MockJavaTree:
            package = None
            types = [MockClassDecl()]

        with patch("javalang.parse.parse", return_value=MockJavaTree()):
            j_mock_file = self.test_dir / "MockField.java"
            j_mock_file.write_text("class FieldFallback {}", encoding="utf-8")
            mock_syms = parse_java_file(j_mock_file)
            self.assertEqual(len(mock_syms), 1)
            self.assertEqual(len(mock_syms[0].children), 1)
            self.assertEqual(mock_syms[0].children[0].name, "x")

    def test_java_adapter_edge_cases(self):
        from pystdoc.adapters.java_adapter import (
            JavaAdapter,
            _extract_java_callees,
        )

        adapter = JavaAdapter()

        # Anonymous / empty name type decl
        class MockEmptyType:
            name = ""

        res = adapter._parse_type_declaration(MockEmptyType(), [], ["pkg"])
        self.assertIsNone(res)

        # Explicit constructor invocation with qualifier
        class MockExp:
            qualifier = "Outer"

        class MockNode:
            def filter(self, target_type):
                import javalang

                if target_type == javalang.tree.ExplicitConstructorInvocation:
                    return [(None, MockExp())]
                return []

        callees = _extract_java_callees(MockNode())
        self.assertIn("Outer", callees)

        # Field declarator with position
        class MockPos:
            line = 42

        class MockDeclWithPos:
            name = "y"
            position = MockPos()

        class MockFieldWithPos:
            type = "String"
            documentation = ""
            modifiers = []
            declarators = [MockDeclWithPos()]
            position = None

        class MockClassWithField:
            name = "FieldPosClass"
            position = MockPos()
            documentation = ""
            modifiers = []
            fields = [MockFieldWithPos()]
            body = []

        cls_res = adapter._parse_type_declaration(
            MockClassWithField(), [], ["pkg"]
        )
        self.assertEqual(len(cls_res.children), 1)
        self.assertEqual(cls_res.children[0].line_start, 42)

    def test_kotlin_adapter_edge_cases(self):
        from pystdoc.adapters.kotlin_adapter import KotlinAdapter

        adapter = KotlinAdapter()

        # None decl
        self.assertIsNone(adapter._parse_declaration(None, [], ["pkg"]))

        # Unknown decl type returning None
        class UnknownDecl:
            pass

        self.assertIsNone(
            adapter._parse_declaration(UnknownDecl(), [], ["pkg"])
        )

        # Property without declaration or name
        class MockPropNoDecl:
            declaration = None

        class MockPropEmptyName:
            class MockInnerDecl:
                name = ""

            declaration = MockInnerDecl()

        self.assertIsNone(
            adapter._parse_property(MockPropNoDecl(), [], ["pkg"])
        )
        self.assertIsNone(
            adapter._parse_property(MockPropEmptyName(), [], ["pkg"])
        )

        # List return in top level and class body
        dummy_sym = Symbol(
            name="dummy", kind="function", line_start=1, line_end=1
        )
        with patch.object(
            adapter, "_parse_declaration", return_value=[dummy_sym]
        ):
            class MockTopTree:
                declarations = [UnknownDecl()]

            with patch("kopyt.Parser") as mock_parser_cls:
                mock_parser_instance = mock_parser_cls.return_value
                mock_parser_instance.parse.return_value = MockTopTree()
                k_file = self.test_dir / "Edge.kt"
                k_file.write_text("fun dummy() {}", encoding="utf-8")
                syms = adapter.parse(k_file)
                self.assertEqual(len(syms), 1)

        # List return inside class body members
        class MockClassBody:
            members = [UnknownDecl()]
            entries = []

        class MockClassNode:
            name = "TestList"
            position = None
            modifiers = []
            constructor = None
            body = MockClassBody()

        with patch.object(
            adapter,
            "_parse_declaration",
            side_effect=lambda decl, lines, stack: [dummy_sym]
            if isinstance(decl, UnknownDecl)
            else None,
        ):
            cls_sym = adapter._parse_class_like(MockClassNode(), [], ["pkg"])
            self.assertEqual(len(cls_sym.children), 1)

        # Kotlin companion object with keyword name and named companion object
        import kopyt

        class MockCompanionNode(kopyt.node.CompanionObject):
            def __init__(self, name_val, mods=None):
                self.name = name_val
                self.modifiers = mods or []
                self.position = None
                self.body = None
                self.interfaces = ()

        comp_kw = adapter._parse_class_like(
            MockCompanionNode("public", []), [], ["pkg"]
        )
        self.assertEqual(comp_kw.name, "Companion")
        self.assertIn("public", comp_kw.signature)

        comp_named = adapter._parse_class_like(
            MockCompanionNode("Factory", []), [], ["pkg"]
        )
        self.assertEqual(comp_named.name, "Factory")
        self.assertIn("companion object Factory", comp_named.signature)

    def test_llm_client_retry_and_json_edge_cases(self):
        import os
        from pystdoc.llm_client import (
            LLMClient,
            extract_json_from_text,
        )

        # 1. extract_json_from_text edge cases
        with self.assertRaises(ValueError):
            extract_json_from_text("")
        with self.assertRaises(ValueError):
            extract_json_from_text("   ")
        with self.assertRaises(ValueError):
            extract_json_from_text("[1, 2, 3]")
        with self.assertRaises(ValueError):
            extract_json_from_text('"just a string"')

        # 2. LLMClient default init without env
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "pystdoc.llm_client.LLMClient.ensure_reachable",
                return_value=True,
            ):
                default_client = LLMClient(host=None, base_url=None)
                self.assertEqual(
                    default_client.base_url, "http://localhost:11434/v1"
                )

        # 3. chat_completion empty response content retry & fail
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            c = LLMClient("http://localhost:11434")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": ""}}]}
        ).encode("utf-8")
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_resp
        mock_cm.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_cm):
            with patch("time.sleep", return_value=None):
                with self.assertRaises(LLMError) as cm:
                    c.chat_completion(
                        [{"role": "user", "content": "hi"}], max_retries=2
                    )
                self.assertIn("empty response content", str(cm.exception))

        # 4. explain_symbol and refine_variable retry with invalid json
        call_count = [0]

        def fake_chat(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "Not a valid JSON at all"
            return '{"purpose": "Recovered", "overview": "Ok"}'

        with patch.object(c, "chat_completion", side_effect=fake_chat):
            with patch("time.sleep", return_value=None):
                res = c.explain_symbol(
                    name="retry_fn",
                    kind="function",
                    code="void retry_fn() {}",
                    signature="void retry_fn()",
                    lang="C",
                    callees=[],
                    params=[],
                    ret_type="void",
                )
                self.assertEqual(res["purpose"], "Recovered")

        # 5. refine_variable_top_down retry and fallback
        with patch.object(
            c, "chat_completion", return_value="Invalid non-json response"
        ):
            with patch("time.sleep", return_value=None):
                fb_res = c.refine_variable_top_down(
                    var_name="v",
                    var_kind="var",
                    var_signature="int v",
                    var_code="int v = 0;",
                    parent_functions_info=[],
                    lang="C",
                    language="Japanese",
                    allow_fallback=True,
                    max_attempts=2,
                )
                self.assertIn("v", fb_res["significance"])

                fb_res_en = c.refine_variable_top_down(
                    var_name="v",
                    var_kind="var",
                    var_signature="int v",
                    var_code="int v = 0;",
                    parent_functions_info=[],
                    lang="C",
                    language="English",
                    allow_fallback=True,
                    parent_container_info={
                        "name": "DataModel",
                        "kind": "class",
                        "purpose": "Holds data",
                    },
                    max_attempts=1,
                )
                self.assertIn("DataModel", fb_res_en["purpose"])

                # Fallback without parent container in English
                fb_res_en2 = c.refine_variable_top_down(
                    var_name="g_val",
                    var_kind="var",
                    var_signature="int g_val",
                    var_code="int g_val;",
                    parent_functions_info=[],
                    lang="C",
                    language="English",
                    allow_fallback=True,
                    max_attempts=1,
                )
                self.assertIn("g_val", fb_res_en2["purpose"])

    def test_static_symbol_doc_all_variations(self):
        from pystdoc.engine import generate_static_symbol_doc
        # Member / field with parent container
        sym_field = Symbol(
            name="logMessage",
            kind="field",
            line_start=1,
            line_end=1,
            signature="val logMessage: String",
            fqdn="pkg.LogData.logMessage",
        )
        doc_field_ja = generate_static_symbol_doc(sym_field, "Japanese")
        self.assertIn("LogData", doc_field_ja["purpose"])
        self.assertIn("logMessage", doc_field_ja["purpose"])

        doc_field_en = generate_static_symbol_doc(sym_field, "English")
        self.assertIn("LogData", doc_field_en["purpose"])

        # Member without parent FQDN
        sym_field_noparent = Symbol(
            name="count",
            kind="member",
            line_start=1,
            line_end=1,
            signature="int count",
        )
        doc_f_ja = generate_static_symbol_doc(sym_field_noparent, "Japanese")
        self.assertIn("count", doc_f_ja["purpose"])
        doc_f_en = generate_static_symbol_doc(sym_field_noparent, "English")
        self.assertIn("count", doc_f_en["purpose"])

        # Typedef
        sym_type = Symbol(
            name="MyType", kind="typedef", line_start=1, line_end=1
        )
        doc_t_ja = generate_static_symbol_doc(sym_type, "Japanese")
        self.assertIn("MyType", doc_t_ja["purpose"])
        doc_t_en = generate_static_symbol_doc(sym_type, "English")
        self.assertIn("MyType", doc_t_en["purpose"])

        # Struct / class
        sym_struct = Symbol(
            name="User", kind="struct", line_start=1, line_end=5
        )
        doc_s_ja = generate_static_symbol_doc(sym_struct, "Japanese")
        self.assertIn("User", doc_s_ja["purpose"])
        doc_s_en = generate_static_symbol_doc(sym_struct, "English")
        self.assertIn("User", doc_s_en["purpose"])

        # Generic symbol
        sym_other = Symbol(
            name="custom_sym", kind="unknown_kind", line_start=1, line_end=1
        )
        doc_o_ja = generate_static_symbol_doc(sym_other, "Japanese")
        self.assertIn("custom_sym", doc_o_ja["purpose"])
        doc_o_en = generate_static_symbol_doc(sym_other, "English")
        self.assertIn("custom_sym", doc_o_en["purpose"])

        # Enum with parent container
        sym_enum = Symbol(
            name="ACTIVE",
            kind="enum_constant",
            line_start=1,
            line_end=1,
            signature="ACTIVE = 1",
            fqdn="pkg.State.ACTIVE",
        )
        doc_e_ja = generate_static_symbol_doc(sym_enum, "Japanese")
        self.assertIn("State", doc_e_ja["purpose"])
        doc_e_en = generate_static_symbol_doc(sym_enum, "English")
        self.assertIn("State", doc_e_en["purpose"])

    def test_pass2_refinement_full_coverage(self):
        kt_file = self.src_dir / "Main.kt"
        kt_file.write_text(
            "class Container {\n"
            "    val myField: String = \"test\"\n"
            "    fun doAction() {\n"
            "        println(myField)\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        mock_client.explain_symbol.return_value = {
            "purpose": "Container purpose",
            "inputs": "None",
            "outputs": "Result",
            "overview": "Container overview",
            "role": "Container role",
        }
        mock_client.refine_variable_top_down.return_value = {
            "role": "Field role",
            "purpose": "Field purpose",
            "overview": "Field overview",
            "usage_scenario": "Field scenario",
        }

        with patch("pystdoc.engine.LLMClient", return_value=mock_client):
            ret = run_docgen(
                target_dir=self.test_dir,
                use_llm=True,
                host="http://localhost:11434",
                concurrency=1,
                language="Japanese",
                force=True,
            )
            self.assertEqual(ret, 0)

    def test_sanitize_architectural_context(self):
        from pystdoc.llm_client import sanitize_architectural_context
        # None and empty
        self.assertEqual(
            sanitize_architectural_context(None, "fallback"), "fallback"
        )
        self.assertEqual(
            sanitize_architectural_context("", "fallback"), "fallback"
        )

        # Persona self-identifications
        self.assertEqual(
            sanitize_architectural_context("ソフトウェアアーキテクト", "fb"),
            "fb",
        )
        self.assertEqual(
            sanitize_architectural_context("Software Architect", "fb"),
            "fb",
        )
        self.assertEqual(
            sanitize_architectural_context(
                "principal software architect", "fb"
            ),
            "fb",
        )

        # Legitimate architectural context
        valid_ctx = "ViewModelの破棄時にリソースの解放を行う。"
        self.assertEqual(
            sanitize_architectural_context(valid_ctx, "fb"), valid_ctx
        )


if __name__ == "__main__":
    unittest.main()
