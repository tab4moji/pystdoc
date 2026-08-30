#!/usr/bin/env python3
"""Final branch coverage tests to achieve 100% test coverage."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pystdoc.symbols import Symbol
from pystdoc.report_engine import generate_readme_doc
from pystdoc.db import DocgenDB
from pystdoc.call_graph import (
    SymbolNode,
    flatten_symbols,
    link_variables_to_functions,
    tarjan_scc,
    order_symbols_by_levels,
    build_callee_context_summary,
)
from pystdoc.parser_clang import _ensure_libclang_loaded
from pystdoc.parser_python import parse_python_file
from pystdoc.llm_client import LLMError


class TestFinal100(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_report_engine_strict_error(self):
        mock_client = MagicMock()
        mock_client.chat_completion.side_effect = LLMError("Readme fail")
        with self.assertRaises(LLMError):
            generate_readme_doc(
                target_dir=self.test_dir,
                llm_client=mock_client,
                language="English",
                allow_fallback=False,
            )

    def test_db_save_design_cache_rollback(self):
        db = DocgenDB(self.test_dir / "index.db")
        orig_conn = db.conn
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB Execute error")
        db.conn = mock_conn
        with self.assertRaises(Exception):
            db.save_design_cache("key1", "hash1", "content1")
        if orig_conn:
            orig_conn.close()
        db.close()

    def test_call_graph_exception_and_empty_nodes(self):
        # 1. read_text exception in link_variables_to_functions
        sym_var = Symbol(name="v", kind="variable", line_start=1, line_end=1)
        sym_fn = Symbol(name="f", kind="function", line_start=2, line_end=5)
        non_file = self.src_dir / "non_existent.c"
        nodes = flatten_symbols([sym_var, sym_fn], Path("non.c"), non_file)
        link_variables_to_functions(nodes)

        # 2. tarjan_scc with single isolated node
        u_id = nodes[0].unique_id
        scc = tarjan_scc([u_id], {u_id: []})
        self.assertEqual(len(scc), 1)

        # 3. order_symbols_by_levels with empty and single node
        self.assertEqual(order_symbols_by_levels([]), [])
        lvls = order_symbols_by_levels([nodes[0]])
        self.assertEqual(len(lvls), 1)

        # 4. build_callee_context_summary with unknown callees
        node = nodes[0]
        node.direct_callee_ids.add("unknown_callee_id")
        summary = build_callee_context_summary(node, {})
        self.assertIsInstance(summary, str)

    def test_parser_clang_load_exceptions(self):
        import pystdoc.parser_clang as pc
        pc._libclang_loaded = False
        with patch("os.path.exists", return_value=True), patch(
            "clang.cindex.Config.set_library_file",
            side_effect=Exception("Load error"),
        ):
            _ensure_libclang_loaded()
            self.assertTrue(pc._libclang_loaded)

        import clang.cindex
        mock_c = MagicMock()
        mock_c.kind = clang.cindex.CursorKind.VAR_DECL
        mock_c.spelling = ""
        mock_c.displayname = ""
        from pystdoc.parser_clang import _parse_cursor
        res = _parse_cursor(mock_c, self.src_dir / "t.c")
        self.assertIsNone(res)

    def test_parser_python_src_in_parts_and_stem_fallback(self):
        src_pkg_file = self.src_dir / "pkg" / "mod.py"
        src_pkg_file.parent.mkdir(parents=True, exist_ok=True)
        src_pkg_file.write_text("def sub_func(): pass\n", encoding="utf-8")
        symbols = parse_python_file(src_pkg_file, base_dir=self.test_dir)
        self.assertTrue(len(symbols) >= 1)
        self.assertIn("pkg.mod.sub_func", symbols[0].fqdn)

    def test_db_load_symbol_cache_missing(self):
        with DocgenDB(self.test_dir / "db_missing.db") as db:
            res = db.load_symbol_cache("non_existent_id")
            self.assertIsNone(res)

        # Explicitly test __del__ and close exception
        temp_db = DocgenDB(self.test_dir / "db_del.db")
        real_conn = temp_db.conn
        temp_conn = MagicMock()
        temp_conn.close.side_effect = Exception("Close error")
        temp_db.conn = temp_conn
        temp_db.close()
        real_conn.close()

    def test_call_graph_circular_levels_and_unknown_adj(self):
        # Mutual recursion cycle: node_a <-> node_b with variable callee
        node_var = SymbolNode(
            symbol=Symbol(
                name="g_data", kind="variable", line_start=1, line_end=1
            ),
            rel_path=Path("a.c"),
            full_path=self.src_dir / "a.c",
            unique_id="a.c::var.g_data",
            fqdn="g_data",
        )
        node_a = SymbolNode(
            symbol=Symbol(
                name="fa",
                kind="function",
                line_start=2,
                line_end=4,
                callees=["fb", "g_data"],
            ),
            rel_path=Path("a.c"),
            full_path=self.src_dir / "a.c",
            unique_id="a.c::fn.fa",
            fqdn="fa",
        )
        node_b = SymbolNode(
            symbol=Symbol(
                name="fb",
                kind="function",
                line_start=5,
                line_end=7,
                callees=["fa"],
            ),
            rel_path=Path("b.c"),
            full_path=self.src_dir / "b.c",
            unique_id="b.c::fn.fb",
            fqdn="fb",
        )
        levels = order_symbols_by_levels([node_var, node_a, node_b])
        self.assertTrue(len(levels) >= 1)
        self.assertEqual(node_a.scc_group_ids, ["b.c::fn.fb"])

    def test_parser_clang_call_expr_with_referenced_spelling(self):
        from clang.cindex import CursorKind
        mock_cursor = MagicMock()
        mock_cursor.kind = CursorKind.CALL_EXPR
        mock_cursor.spelling = ""
        mock_cursor.referenced.spelling = "target_callee_fn"
        mock_cursor.get_children.return_value = []
        from pystdoc.parser_clang import _extract_callees
        callees = _extract_callees(mock_cursor, self.src_dir / "app.c")
        self.assertIn("target_callee_fn", callees)

    def test_hasher_symbol_read_exception(self):
        sym = Symbol(name="g_x", kind="variable", line_start=1, line_end=1)
        sym_hash_f = (
            self.test_dir / ".docgen" / "documents" / "file.c.var.g_x.hash"
        )
        sym_hash_f.parent.mkdir(parents=True, exist_ok=True)
        sym_hash_f.write_text("old_hash", encoding="utf-8")

        from pystdoc.hasher import update_symbol_hash_record
        with patch.object(
            Path, "read_text", side_effect=Exception("Disk error")
        ):
            ch, _ = update_symbol_hash_record(
                self.test_dir, Path("file.c"), sym, "new_hash"
            )
            self.assertTrue(ch)

    def test_report_engine_fallback_on_error(self):
        mock_client = MagicMock()
        mock_client.chat_completion.side_effect = LLMError("Readme fail")
        res = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=mock_client,
            language="English",
            allow_fallback=True,
        )
        self.assertIn("Project Overview", res)

    def test_parser_python_no_src_and_exception_stem(self):
        non_src_f = self.test_dir / "lib" / "helper.py"
        non_src_f.parent.mkdir(parents=True, exist_ok=True)
        non_src_f.write_text("def assist(): pass\n", encoding="utf-8")
        # 1. base_dir=None and "src" not in parts
        syms1 = parse_python_file(non_src_f, base_dir=None)
        self.assertTrue(len(syms1) >= 1)
        self.assertIn("helper.assist", syms1[0].fqdn)

        # 2. Exception in rel parts
        with patch.object(
            Path, "with_suffix", side_effect=Exception("Suffix error")
        ):
            syms2 = parse_python_file(non_src_f, base_dir=None)
            self.assertTrue(len(syms2) >= 1)

    def test_llm_client_resolv_conf_and_json_fallback(self):
        from pystdoc.llm_client import LLMClient, extract_json_from_text
        client = LLMClient(base_url="http://localhost:11434")
        # 1. Broken brace JSON extraction fallback raises JSONDecodeError
        broken_json = "Here is json: {invalid json content}"
        import json
        with self.assertRaises(json.JSONDecodeError):
            extract_json_from_text(broken_json)

        # 2. resolv.conf read exception
        with patch(
            "subprocess.run", side_effect=Exception("ip error")
        ), patch.object(
            Path, "read_text", side_effect=Exception("resolv error")
        ):
            self.assertIsNone(client._detect_wsl_host())

        # 3. ensure_reachable where wsl_host found but ping fails (line 175)
        auto_client = LLMClient()
        with patch.object(
            auto_client, "_ping_url", return_value=False
        ), patch.object(
            auto_client, "_detect_wsl_host", return_value="192.168.1.100"
        ):
            self.assertFalse(auto_client.ensure_reachable())

    def test_engine_filelock_exit_exception_and_others(self):
        from pystdoc.engine import (
            FileLock,
            generate_static_symbol_doc,
        )
        lock_file = self.test_dir / "test.lock"
        fl = FileLock(lock_file)
        fl.__enter__()
        # Exception during unlock should pass silently
        with patch("fcntl.flock", side_effect=Exception("Unlock error")):
            fl.__exit__(None, None, None)

        # Static doc for unknown kind (line 120)
        sym_unknown = Symbol(
            name="Mystery",
            kind="custom_kind",
            line_start=1,
            line_end=1,
        )
        doc_res = generate_static_symbol_doc(sym_unknown, "English")
        self.assertIn("Mystery", doc_res["purpose"])

    def test_design_engine_markdown_parser_and_mermaid_extract(self):
        from pystdoc.design_engine import parse_symbol_doc
        # 1. parse_symbol_doc with top_down only (line 56)
        raw_md_file = self.test_dir / "do_task.md"
        raw_md_file.write_text(
            "# Function Documentation: `do_task`\n\n"
            "## 1. Top-Down Architectural Context & Role\n"
            "Orchestrates sub-tasks across system.\n",
            encoding="utf-8",
        )
        parsed = parse_symbol_doc(raw_md_file)
        self.assertIn("Orchestrates", parsed["purpose"])

    def test_call_graph_bottom_up_flatten(self):
        from pystdoc.call_graph import order_symbols_bottom_up
        node = SymbolNode(
            symbol=Symbol(name="f", kind="function", line_start=1, line_end=2),
            rel_path=Path("f.c"),
            full_path=self.src_dir / "f.c",
            unique_id="f.c::fn.f",
            fqdn="f",
        )
        res = order_symbols_bottom_up([node])
        self.assertEqual(len(res), 1)

    def test_call_graph_cyclic_sccs_no_leaf(self):
        node_var = SymbolNode(
            symbol=Symbol(
                name="g_v", kind="variable", line_start=1, line_end=1
            ),
            rel_path=Path("v.c"),
            full_path=self.src_dir / "v.c",
            unique_id="v.c::var.g_v",
            fqdn="g_v",
        )
        node_a1 = SymbolNode(
            symbol=Symbol(
                name="fa1", kind="function", line_start=2, line_end=4,
                callees=["fa2", "g_var"],
            ),
            rel_path=Path("a.c"),
            full_path=self.src_dir / "a.c",
            unique_id="a.c::fn.fa1",
            fqdn="fa1",
        )
        node_a2 = SymbolNode(
            symbol=Symbol(
                name="fa2", kind="function", line_start=5, line_end=7,
                callees=["fa1"],
            ),
            rel_path=Path("a.c"),
            full_path=self.src_dir / "a.c",
            unique_id="a.c::fn.fa2",
            fqdn="fa2",
        )
        node_b1 = SymbolNode(
            symbol=Symbol(
                name="fb1", kind="function", line_start=2, line_end=4,
                callees=["fb2", "fa1"],
            ),
            rel_path=Path("b.c"),
            full_path=self.src_dir / "b.c",
            unique_id="b.c::fn.fb1",
            fqdn="fb1",
        )
        node_b2 = SymbolNode(
            symbol=Symbol(
                name="fb2", kind="function", line_start=5, line_end=7,
                callees=["fb1"],
            ),
            rel_path=Path("b.c"),
            full_path=self.src_dir / "b.c",
            unique_id="b.c::fn.fb2",
            fqdn="fb2",
        )
        levels = order_symbols_by_levels(
            [node_var, node_a1, node_a2, node_b1, node_b2]
        )
        self.assertTrue(len(levels) >= 1)

        # Line 218: callee_id not in node_to_scc_idx
        # Line 244: SCC not in scc_rank fallback safety loop

        def custom_tarjan(fn_ids, caller_to_callees):
            # Inject unindexed callee_id
            caller_to_callees["a.c::fn.fa1"].add("missing_id_999")
            return [["a.c::fn.fa1"], ["a.c::fn.fa2"]]

        with patch("pystdoc.call_graph.tarjan_scc", side_effect=custom_tarjan):
            levels_patched = order_symbols_by_levels([node_a1, node_a2])
            self.assertTrue(len(levels_patched) >= 1)

    def test_design_engine_strict_llm_errors_and_mermaid_fallback(self):
        from pystdoc.design_engine import (
            generate_data_models_doc,
            generate_execution_model_doc,
            generate_module_docs,
            generate_overview_doc,
        )
        mock_client = MagicMock()
        mock_client.chat_completion.side_effect = LLMError("Design error")

        # 1. generate_data_models_doc strict error (line 349)
        mock_client.chat_completion.side_effect = LLMError("Design error")
        with self.assertRaises(LLMError):
            generate_data_models_doc(
                [{"file_name": "T", "signature": "int", "purpose": "Type"}],
                [],
                mock_client,
                self.test_dir,
                allow_fallback=False,
            )

        # 2. generate_execution_model_doc strict error (line 451)
        with self.assertRaises(LLMError):
            generate_execution_model_doc(
                [{
                    "file_name": "E",
                    "signature": "void()",
                    "purpose": "Exec",
                    "callees": ["c1"],
                }],
                mock_client,
                self.test_dir,
                allow_fallback=False,
            )

        # 3. generate_module_docs strict error (line 562)
        with self.assertRaises(LLMError):
            generate_module_docs(
                {
                    "modA": [{
                        "file_name": "M", "kind": "function", "purpose": "text"
                    }]
                },
                mock_client,
                self.test_dir,
                allow_fallback=False,
            )

        # 4. generate_overview_doc strict error (line 668)
        with self.assertRaises(LLMError):
            generate_overview_doc(
                "data", "exec", {"modA": "summary"},
                mock_client,
                self.test_dir,
                allow_fallback=False,
            )

        # 5. Fallback content branches (lines 349, 451, 562, 668)
        res_dm = generate_data_models_doc(
            [], [], mock_client, self.test_dir, allow_fallback=True
        )
        self.assertIn("Data Structure", res_dm)

        res_em = generate_execution_model_doc(
            [], mock_client, self.test_dir, allow_fallback=True
        )
        self.assertIn("Execution Model", res_em)

        res_mod = generate_module_docs(
            {"modA": []}, mock_client, self.test_dir, allow_fallback=True
        )
        self.assertIn("Module Design", res_mod["modA"])

        res_ov = generate_overview_doc(
            "data", "exec", {"modA": "summary"},
            mock_client, self.test_dir, allow_fallback=True
        )
        self.assertIn("Overview", res_ov)

        # 6. hierarchical_reduce_summaries (lines 181, 221, 225)
        from pystdoc.design_engine import (
            hierarchical_reduce_summaries,
            run_design_generation,
        )
        # Line 181: depth > 0 with single large chunk exceeding max_chars
        long_single_item = ["Z" * 15000]
        res_depth = hierarchical_reduce_summaries(
            long_single_item, "Category", mock_client, depth=1
        )
        self.assertIn("ZZZ", res_depth)

        # Line 221: strict error in chunk
        mock_err_client = MagicMock()
        mock_err_client.chat_completion.side_effect = LLMError("Reduce error")
        many_lines = [f"Item {i} data string" for i in range(25)]
        with self.assertRaises(LLMError):
            hierarchical_reduce_summaries(
                many_lines, "Category", mock_err_client, allow_fallback=False
            )

        # Line 225: fallback in chunk
        res_fb_chunk = hierarchical_reduce_summaries(
            many_lines, "Category", mock_err_client, allow_fallback=True
        )
        self.assertIn("Group 1", res_fb_chunk)

        # 7. run_design_generation error paths (lines 698-702, 729-738)
        ret_no_docs = run_design_generation(
            self.test_dir / "non_existent_dir_123"
        )
        self.assertEqual(ret_no_docs, 1)

        # Create docs dir for server check
        (self.test_dir / ".docgen" / "documents").mkdir(
            parents=True, exist_ok=True
        )
        with patch(
            "pystdoc.llm_client.LLMClient.check_availability",
            return_value=False,
        ):
            ret_des_unreach = run_design_generation(
                self.test_dir,
                host="http://127.0.0.1:9999",
                use_llm=True,
                allow_fallback=False,
            )
            self.assertEqual(ret_des_unreach, 1)

            ret_des_warn = run_design_generation(
                self.test_dir,
                host="http://127.0.0.1:9999",
                use_llm=True,
                allow_fallback=True,
            )
            self.assertEqual(ret_des_warn, 0)

    def test_engine_empty_dir_process_nodes_and_thread_exception(self):
        from pystdoc.engine import run_docgen

        # 1. Empty directory with no source files (lines 516-520)
        empty_dir = self.test_dir / "empty_dir"
        empty_dir.mkdir(parents=True, exist_ok=True)
        ret_empty = run_docgen(empty_dir, use_llm=False)
        self.assertEqual(ret_empty, 0)

        # 2. LLM server unreachable without fallback (lines 201-212)
        src_file = self.src_dir / "app.py"
        src_file.write_text(
            "class MyService:\n    count = 10\n", encoding="utf-8"
        )
        with patch(
            "pystdoc.llm_client.LLMClient.check_availability",
            return_value=False,
        ):
            ret_unreach = run_docgen(
                self.test_dir,
                host="http://127.0.0.1:9999",
                use_llm=True,
                allow_fallback=False,
            )
            self.assertEqual(ret_unreach, 1)

        # 3. Static bypass for vars & classes (lines 338-356, 610)
        ret_static = run_docgen(
            self.test_dir,
            use_llm=False,
            force=True,
        )
        self.assertEqual(ret_static, 0)

        # 5. LLM unreachable warning fallback (line 212)
        with patch(
            "pystdoc.llm_client.LLMClient.check_availability",
            return_value=False,
        ):
            ret_warn = run_docgen(
                self.test_dir,
                host="http://127.0.0.1:9999",
                use_llm=True,
                allow_fallback=True,
            )
            self.assertEqual(ret_warn, 0)

        # 6. Global variable referenced via callees (lines 516-520)
        (self.src_dir / "calc.c").write_text(
            "int g_flag = 1;\nint get_flag() { return g_flag; }\n",
            encoding="utf-8",
        )
        ret_flag = run_docgen(
            self.test_dir,
            use_llm=False,
            force=True,
        )
        self.assertEqual(ret_flag, 0)

        # 7. Worker exception during Pass 2 var refinement (lines 637-640)
        orig_print = print

        def crash_print(*args, **kwargs):
            if args and "[Retained Variable Context]" in str(args[0]):
                raise RuntimeError("Pass 2 thread worker crash")
            return orig_print(*args, **kwargs)

        with patch("builtins.print", side_effect=crash_print):
            ret_var_crash = run_docgen(
                self.test_dir,
                use_llm=False,
                force=True,
            )
            self.assertEqual(ret_var_crash, 1)

    def test_engine_remaining_branches_100(self):
        from pystdoc.engine import (
            generate_static_symbol_doc,
        )
        # Line 120: static symbol doc for unknown symbol kind (Japanese)
        sym_other = Symbol(name="O", kind="other", line_start=1, line_end=1)
        res_other_ja = generate_static_symbol_doc(sym_other, "Japanese")
        self.assertIn("O", res_other_ja["purpose"])


if __name__ == "__main__":
    unittest.main()
