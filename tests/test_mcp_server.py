"""Unit tests for FastMCP server in pystdoc."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pystdoc.db import DocgenDB
from pystdoc.mcp_server import create_mcp_server, run_mcp_server
from pystdoc.symbols import Symbol


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmp_dir.name)
        self.docgen_dir = self.test_dir / ".docgen"
        self.docgen_dir.mkdir(parents=True)
        self.docs_dir = self.docgen_dir / "documents"
        self.docs_dir.mkdir(parents=True)
        self.design_dir = self.docgen_dir / "design"
        self.design_dir.mkdir(parents=True)

        # Setup sample files
        (self.docgen_dir / "files.txt").write_text(
            "src/main.py\n", encoding="utf-8"
        )
        (self.docgen_dir / "README.md").write_text(
            "# Project README", encoding="utf-8"
        )
        (self.design_dir / "overview.md").write_text(
            "# Architecture Overview", encoding="utf-8"
        )
        (self.design_dir / "data_models.md").write_text(
            "# Data Models", encoding="utf-8"
        )
        (self.design_dir / "execution_model.md").write_text(
            "# Execution Model", encoding="utf-8"
        )

        modules_dir = self.design_dir / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "query.md").write_text(
            "# Query Module", encoding="utf-8"
        )

        # Setup sample DB
        db_path = self.docgen_dir / "index.db"
        with DocgenDB(db_path) as db:
            sym_fn = Symbol(
                name="run_calc",
                kind="function",
                line_start=10,
                line_end=20,
                fqdn="calc.run_calc",
                signature="def run_calc(a, b)",
                purpose="Perform computation",
                overview="Calculates result from inputs.",
            )
            db.save_symbol_metadata("uid_fn", sym_fn, "src/calc.py")

            sym_type = Symbol(
                name="CalcState",
                kind="class",
                line_start=1,
                line_end=5,
                fqdn="calc.CalcState",
                signature="class CalcState",
            )
            db.save_symbol_metadata("uid_type", sym_type, "src/calc.py")

            sym_var = Symbol(
                name="MAX_VAL",
                kind="const",
                line_start=2,
                line_end=2,
                fqdn="calc.MAX_VAL",
                signature="MAX_VAL = 100",
            )
            db.save_symbol_metadata("uid_var", sym_var, "src/calc.py")

        # Setup sample markdown doc
        doc1 = self.docs_dir / "src/calc.py.fn.run_calc.md"
        doc1.parent.mkdir(parents=True, exist_ok=True)
        doc1.write_text(
            "# Function `run_calc`\n\nDetailed doc.", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_create_mcp_server_tools(self):
        server = create_mcp_server(target_dir=self.test_dir, auto_watch=True)
        self.assertIsNotNone(server)
        tool_fn = server._tool_manager.get_tool("pystdoc_get_overview").fn
        res = tool_fn(path=str(self.test_dir))
        self.assertIn("# Project README", res)
        server._watcher_manager.stop_all()

        server_no_watch = create_mcp_server(auto_watch=False)
        self.assertIsNotNone(server_no_watch)
        self.assertIsNone(server_no_watch._watcher_manager)

    def test_mcp_get_symbol(self):
        server = create_mcp_server()
        # Find get_symbol tool
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_get_symbol":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # 1. Existing symbol
        res = tool_fn(symbol="run_calc", path=str(self.test_dir))
        self.assertIn("Symbol: calc.run_calc", res)
        self.assertIn("Function `run_calc`", res)

        # 2. Non-existent symbol
        res_not_found = tool_fn(
            symbol="non_existent_func", path=str(self.test_dir)
        )
        self.assertIn("not found", res_not_found.lower())

        # 3. Non-existent .docgen dir
        with tempfile.TemporaryDirectory() as empty_dir:
            res_no_dir = tool_fn(symbol="run_calc", path=empty_dir)
            self.assertIn("Error: .docgen directory not found", res_no_dir)

    def test_mcp_list_symbols(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_list_symbols":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # 1. all
        res_all = tool_fn(kind="all", path=str(self.test_dir))
        self.assertIn("calc.CalcState", res_all)
        self.assertIn("calc.run_calc", res_all)
        self.assertIn("calc.MAX_VAL", res_all)

        # 2. function
        res_fn = tool_fn(kind="function", path=str(self.test_dir))
        self.assertIn("calc.run_calc", res_fn)

        # 3. variable
        res_var = tool_fn(kind="variable", path=str(self.test_dir))
        self.assertIn("calc.MAX_VAL", res_var)

        # 4. type
        res_type = tool_fn(kind="type", path=str(self.test_dir))
        self.assertIn("calc.CalcState", res_type)

        # 5. Non-existent .docgen dir
        with tempfile.TemporaryDirectory() as empty_dir:
            res_no_dir = tool_fn(kind="all", path=empty_dir)
            self.assertIn("Error: .docgen directory not found", res_no_dir)

    def test_mcp_get_design(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_get_design":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # 1. overview
        res_overview = tool_fn(section="overview", path=str(self.test_dir))
        self.assertEqual(res_overview, "# Architecture Overview")

        # 2. data_models
        res_data = tool_fn(section="data_models", path=str(self.test_dir))
        self.assertEqual(res_data, "# Data Models")

        # 3. execution_model
        res_exec = tool_fn(
            section="execution_model", path=str(self.test_dir)
        )
        self.assertEqual(res_exec, "# Execution Model")

        # 4. readme
        res_readme = tool_fn(section="readme", path=str(self.test_dir))
        self.assertEqual(res_readme, "# Project README")

        # 5. module
        res_mod = tool_fn(section="query", path=str(self.test_dir))
        self.assertEqual(res_mod, "# Query Module")

        # 6. Not found section
        res_not_found = tool_fn(
            section="unknown_section", path=str(self.test_dir)
        )
        self.assertIn("not found", res_not_found)
        self.assertIn("Available module sections: query.", res_not_found)

        # 7. File path as section
        res_file_path = tool_fn(
            section="src/pystdoc/query.py", path=str(self.test_dir)
        )
        self.assertEqual(res_file_path, "# Query Module")

        # 8. Non-existent .docgen dir
        with tempfile.TemporaryDirectory() as empty_dir:
            res_no_dir = tool_fn(section="overview", path=empty_dir)
            self.assertIn("Error: .docgen directory not found", res_no_dir)

    def test_mcp_get_overview(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_get_overview":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # 1. Success
        res = tool_fn(path=str(self.test_dir))
        self.assertIn("# Project README", res)
        self.assertIn("# Architecture Overview", res)

        # 2. Non-existent .docgen dir
        with tempfile.TemporaryDirectory() as empty_dir:
            res_no_dir = tool_fn(path=empty_dir)
            self.assertIn("Error: .docgen directory not found", res_no_dir)

        # 3. Empty docs
        with tempfile.TemporaryDirectory() as empty_proj:
            p = Path(empty_proj)
            (p / ".docgen" / "design").mkdir(parents=True)
            res_empty = tool_fn(path=empty_proj)
            self.assertIn("No overview documentation available", res_empty)

    def test_mcp_search_symbols(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_search_symbols":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # 1. Search all matching calc
        res_calc = tool_fn(query="calc", kind="all", path=str(self.test_dir))
        self.assertIn("Found 3 matching symbol(s)", res_calc)
        self.assertIn("calc.run_calc", res_calc)
        self.assertIn("calc.CalcState", res_calc)

        # 2. Search functions
        res_fn = tool_fn(query="calc", kind="func", path=str(self.test_dir))
        self.assertIn("calc.run_calc", res_fn)
        self.assertNotIn("calc.CalcState", res_fn)

        # 3. Search types
        res_type = tool_fn(query="calc", kind="class", path=str(self.test_dir))
        self.assertIn("calc.CalcState", res_type)

        # 4. Search vars
        res_var = tool_fn(query="max", kind="var", path=str(self.test_dir))
        self.assertIn("calc.MAX_VAL", res_var)

        # 5. No match
        res_none = tool_fn(query="xyz987", path=str(self.test_dir))
        self.assertIn("No symbols found", res_none)

        # 6. Non-existent dir
        with tempfile.TemporaryDirectory() as empty_dir:
            res_no_dir = tool_fn(query="calc", path=empty_dir)
            self.assertIn("Error: .docgen directory not found", res_no_dir)

        # 7. Missing DB
        with tempfile.TemporaryDirectory() as no_db_proj:
            p = Path(no_db_proj)
            (p / ".docgen").mkdir(parents=True)
            res_no_db = tool_fn(query="calc", path=no_db_proj)
            self.assertIn("Error: index database", res_no_db)

    def test_mcp_list_files(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_list_files":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        res = tool_fn(path=str(self.test_dir))
        self.assertIn("src/main.py", res)

    def test_mcp_sync(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_sync":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # Mock sync steps
        with patch(
            "pystdoc.mcp_server.run_docgen", return_value=0
        ) as m_docgen, patch(
            "pystdoc.mcp_server.run_design_generation", return_value=0
        ) as m_design, patch(
            "pystdoc.mcp_server.generate_readme_doc", return_value=""
        ) as m_readme, patch(
            "pystdoc.mcp_server.LLMClient"
        ) as mock_client_cls:

            mock_instance = MagicMock()
            mock_instance.check_availability.return_value = True
            mock_client_cls.return_value = mock_instance

            res = tool_fn(
                path=str(self.test_dir), no_llm=False, language="English"
            )
            self.assertIn("Successfully synchronized", res)
            m_docgen.assert_called_once()
            m_design.assert_called_once()
            m_readme.assert_called_once()

    def test_mcp_sync_failures(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_sync":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        # 1. docgen fails
        with patch("pystdoc.mcp_server.run_docgen", return_value=1):
            res = tool_fn(path=str(self.test_dir))
            self.assertIn("docgen failed", res)

        # 2. designgen fails
        with patch("pystdoc.mcp_server.run_docgen", return_value=0), \
             patch(
                 "pystdoc.mcp_server.run_design_generation", return_value=2
             ):
            res = tool_fn(path=str(self.test_dir))
            self.assertIn("designgen failed", res)

        # 3. exception during sync
        with patch(
            "pystdoc.mcp_server.run_docgen",
            side_effect=ValueError("Sync boom"),
        ):
            res = tool_fn(path=str(self.test_dir))
            self.assertIn("Error during sync", res)

    def test_create_mcp_server_import_error(self):
        with patch("pystdoc.mcp_server.FastMCP", None):
            with self.assertRaises(RuntimeError) as cm:
                create_mcp_server()
            self.assertIn("mcp package is not installed", str(cm.exception))

    def test_run_mcp_server(self):
        mock_server = MagicMock()
        with patch(
            "pystdoc.mcp_server.create_mcp_server", return_value=mock_server
        ):
            run_mcp_server(target_dir=self.test_dir, auto_watch=True)
            mock_server.run.assert_called_once_with(transport="stdio")
            mock_server._watcher_manager.stop_all.assert_called_once()

    def test_mcp_watcher_manager(self):
        from pystdoc.mcp_server import MCPWatcherManager
        mgr = MCPWatcherManager()

        # Non-directory path should do nothing
        mgr.watch_directory(self.test_dir / "non_existent")
        self.assertEqual(len(mgr._watchers), 0)

        # Watch valid directory
        with patch("pystdoc.mcp_server.DNotifyWatcher") as mock_watcher_cls:
            mock_w_inst = MagicMock()
            mock_watcher_cls.return_value = mock_w_inst

            mgr.watch_directory(self.test_dir)
            self.assertEqual(len(mgr._watchers), 1)
            mock_w_inst.start.assert_called_once_with(blocking=False)

            # Calling again should be idempotent
            mgr.watch_directory(self.test_dir)
            self.assertEqual(len(mgr._watchers), 1)

            # Test on_change callback execution
            on_change_cb = mock_watcher_cls.call_args[1]["on_change"]
            with patch("pystdoc.mcp_server.run_docgen") as m_docgen, \
                 patch("pystdoc.mcp_server.run_design_generation") as m_des, \
                 patch("pystdoc.mcp_server.generate_readme_doc") as m_rm, \
                 patch("pystdoc.mcp_server.LLMClient") as mock_client_cls:
                mock_inst = MagicMock()
                mock_inst.check_availability.return_value = True
                mock_client_cls.return_value = mock_inst

                on_change_cb()
                m_docgen.assert_called_once()
                m_des.assert_called_once()
                m_rm.assert_called_once()

            # Test exception in on_change callback
            with patch(
                "pystdoc.mcp_server.run_docgen",
                side_effect=Exception("sync error"),
            ):
                on_change_cb()

            # Stop all
            mgr.stop_all()
            mock_w_inst.stop.assert_called_once()
            self.assertEqual(len(mgr._watchers), 0)

    def test_mcp_module_import_fallback(self):
        import builtins
        import importlib
        import pystdoc.mcp_server

        orig_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if "mcp" in name:
                raise ImportError("Mocked MCP import error")
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            importlib.reload(pystdoc.mcp_server)
            self.assertIsNone(pystdoc.mcp_server.FastMCP)

        # Restore original module state
        importlib.reload(pystdoc.mcp_server)
        self.assertIsNotNone(pystdoc.mcp_server.FastMCP)

    def test_mcp_locate_feature(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_locate_feature":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        with patch("pystdoc.mcp_server.locate_features") as mock_loc:
            mock_loc.return_value = "Mocked Locate Result"
            res = tool_fn(query="debug button", path=str(self.test_dir))
            self.assertEqual(res, "Mocked Locate Result")
            mock_loc.assert_called_once_with(self.test_dir, "debug button")

    def test_mcp_trace_impact(self):
        server = create_mcp_server()
        tool_fn = None
        for t in server._tool_manager.list_tools():
            if t.name == "pystdoc_trace_impact":
                tool_fn = server._tool_manager.get_tool(t.name).fn
                break
        self.assertIsNotNone(tool_fn)

        with patch("pystdoc.mcp_server.trace_impact") as mock_imp:
            mock_imp.return_value = "Mocked Impact Result"
            res = tool_fn(symbol="DebugButton", path=str(self.test_dir))
            self.assertEqual(res, "Mocked Impact Result")
            mock_imp.assert_called_once_with(self.test_dir, "DebugButton")


if __name__ == "__main__":
    unittest.main()
