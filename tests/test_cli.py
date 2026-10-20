#!/usr/bin/env python3
"""Unit tests for CLI entry points in pystdoc.cli."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pystdoc.cli import (
    designgen_main,
    docgen_main,
    normalize_step_identifier,
    pystdoc_main,
    reportgen_main,
)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        sample_file = self.test_dir / "sample.c"
        sample_file.write_text("int main() { return 0; }\n", encoding="utf-8")
        self.patcher = patch(
            "pystdoc.config.get_user_config_path",
            return_value=self.test_dir / "no_user_cfg.json",
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_docgen_cli_success(self):
        test_args = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--language", "English",
            "-j", "1",
        ]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                docgen_main()
            self.assertEqual(cm.exception.code, 0)

    def test_designgen_cli_success(self):
        docgen_args = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
        ]
        with patch("sys.argv", docgen_args):
            with self.assertRaises(SystemExit):
                docgen_main()

        designgen_args = [
            "designgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--language", "Japanese",
            "--force",
        ]
        with patch("sys.argv", designgen_args):
            with self.assertRaises(SystemExit) as cm:
                designgen_main()
            self.assertEqual(cm.exception.code, 0)

    def test_reportgen_cli_full_pipeline(self):
        test_args = [
            "pystdoc",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--language", "English",
        ]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 0)

    def test_reportgen_cli_invalid_dir(self):
        test_args = [
            "reportgen",
            "--dir", "/non_existent_directory_pystdoc_test_12345",
        ]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 1)

    def test_reportgen_cli_skip_flags(self):
        docgen_args = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
        ]
        with patch("sys.argv", docgen_args):
            with self.assertRaises(SystemExit):
                docgen_main()

        test_args = [
            "reportgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--skip-docgen",
            "--skip-designgen",
        ]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 0)

    def test_reportgen_cli_with_llm_mock(self):
        # Prepare docgen first
        docgen_args = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
        ]
        with patch("sys.argv", docgen_args):
            with self.assertRaises(SystemExit):
                docgen_main()

        # Success with LLM client available
        mock_client = MagicMock()
        mock_client.check_availability.return_value = True
        mock_client.chat_completion.return_value = "Mocked README content"

        test_args = [
            "reportgen",
            "--dir", str(self.test_dir),
            "--host", "http://127.0.0.1:11434",
            "--token", "sk-test",
            "--skip-docgen",
            "--skip-designgen",
        ]
        with patch("sys.argv", test_args), \
             patch("pystdoc.cli.LLMClient", return_value=mock_client):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 0)

        # Failure without fallback
        shutil.rmtree(self.test_dir / ".pystdoc", ignore_errors=True)
        docgen_args = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
        ]
        with patch("sys.argv", docgen_args):
            with self.assertRaises(SystemExit):
                docgen_main()

        readme_f = self.test_dir / ".pystdoc" / "README.md"
        if readme_f.exists():
            readme_f.unlink()

        mock_client_fail = MagicMock()
        mock_client_fail.check_availability.return_value = False
        mock_client_fail.base_url = "http://127.0.0.1:11434/v1"

        test_args_fail = [
            "reportgen",
            "--dir", str(self.test_dir),
            "--host", "http://127.0.0.1:11434",
            "--skip-docgen",
            "--skip-designgen",
        ]
        with patch("sys.argv", test_args_fail), \
             patch("pystdoc.cli.LLMClient", return_value=mock_client_fail):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 1)

    def test_reportgen_pipeline_error_exits(self):
        # docgen failure
        with patch("sys.argv", ["reportgen", "--dir", str(self.test_dir)]), \
             patch("pystdoc.cli.run_docgen", return_value=1):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 1)

        # designgen failure
        test_args = ["reportgen", "--dir", str(self.test_dir), "--skip-docgen"]
        with patch("sys.argv", test_args), \
             patch("pystdoc.cli.run_design_generation", return_value=2):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 2)

    def test_main_module(self):
        import runpy
        import pystdoc.__main__

        main_file = Path(pystdoc.__main__.__file__)
        with patch("pystdoc.cli.reportgen_main") as mock_reportgen:
            runpy.run_path(str(main_file), run_name="__main__")
            mock_reportgen.assert_called_once()

    def test_version_consistency_with_pyproject(self):
        import pystdoc
        import re

        pyproject_path = (
            Path(__file__).resolve().parent.parent / "pyproject.toml"
        )
        self.assertTrue(
            pyproject_path.exists(),
            f"pyproject.toml not found at {pyproject_path}",
        )

        content = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        self.assertIsNotNone(
            match, "Could not find 'version' in pyproject.toml"
        )
        pyproject_version = match.group(1).strip()
        self.assertEqual(
            pystdoc.__version__,
            pyproject_version,
            f"Version mismatch: pystdoc.__version__ ({pystdoc.__version__}) "
            f"!= pyproject.toml version ({pyproject_version})",
        )

    def test_reportgen_cli_sync_subcommand(self):
        test_args = [
            "pystdoc",
            "sync",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
        ]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 0)

    def test_reportgen_cli_query_subcommands(self):
        # 1. list / ls
        with patch("pystdoc.cli.run_list", return_value=0) as mock_list:
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(["list", str(self.test_dir)])
            self.assertEqual(cm.exception.code, 0)
            mock_list.assert_called_once()

        with patch("pystdoc.cli.run_list", return_value=0) as mock_list:
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(["ls", "--dir", str(self.test_dir)])
            self.assertEqual(cm.exception.code, 0)
            mock_list.assert_called_once()

        # 2. functions / fn / func / function / funcs / fns
        for alias in ["functions", "fn", "func", "function", "funcs", "fns"]:
            with patch("pystdoc.cli.run_functions", return_value=0) as mock_fn:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "--dir", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                mock_fn.assert_called_once()

            with patch(
                "pystdoc.cli.run_description", return_value=0
            ) as m_desc:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "my_func", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                m_desc.assert_called_once()

        # 3. variables / var / variable / vars
        for alias in ["variables", "var", "variable", "vars"]:
            with patch("pystdoc.cli.run_variables", return_value=0) as mock_v:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "--dir", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                mock_v.assert_called_once()

            with patch(
                "pystdoc.cli.run_description", return_value=0
            ) as m_desc:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "my_var", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                m_desc.assert_called_once()

        # 4. types / type / class / classes / struct / structs
        for alias in [
            "types", "type", "class", "classes", "struct", "structs"
        ]:
            with patch("pystdoc.cli.run_types", return_value=0) as mock_t:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "--dir", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                mock_t.assert_called_once()

            with patch(
                "pystdoc.cli.run_description", return_value=0
            ) as m_desc:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "MyClass", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                m_desc.assert_called_once()

        # 5. Directory detection branches in _parse_query_target_and_symbol
        # 5a. pos1 is dir with slash ending
        with patch("pystdoc.cli.run_functions", return_value=0) as mock_fn:
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(["fn", f"{self.test_dir}/"])
            self.assertEqual(cm.exception.code, 0)
            mock_fn.assert_called_once()

        # 5b. pos1 is existing dir
        with patch("pystdoc.cli.run_functions", return_value=0) as mock_fn:
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(["fn", str(self.test_dir)])
            self.assertEqual(cm.exception.code, 0)
            mock_fn.assert_called_once()

        # 5c. pos1 is symbol and --dir provided
        with patch("pystdoc.cli.run_description", return_value=0) as m_desc:
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(["fn", "calc", "--dir", str(self.test_dir)])
            self.assertEqual(cm.exception.code, 0)
            m_desc.assert_called_once()

        # 5d. pos1 is standalone symbol without directory
        with patch("pystdoc.cli.run_description", return_value=0) as m_desc:
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(["fn", "my_standalone_func"])
            self.assertEqual(cm.exception.code, 0)
            m_desc.assert_called_once()

        # 6. description / desc
        for alias in ["description", "desc"]:
            with patch(
                "pystdoc.cli.run_description", return_value=0
            ) as m_desc:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([alias, "Userlib.main", str(self.test_dir)])
                self.assertEqual(cm.exception.code, 0)
                m_desc.assert_called_once()

        # 7. description missing symbol
        with self.assertRaises(SystemExit) as cm:
            reportgen_main(["desc"])
        self.assertEqual(cm.exception.code, 1)

    def test_reportgen_cli_llm_unavailable_exit(self):
        shutil.rmtree(self.test_dir / ".pystdoc", ignore_errors=True)
        test_args = [
            "reportgen",
            "--dir", str(self.test_dir),
            "--host", "http://invalid-host:1234",
        ]
        with patch("sys.argv", test_args):
            with patch(
                "pystdoc.llm_client.LLMClient.check_availability",
                return_value=False,
            ):
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main()
                self.assertEqual(cm.exception.code, 1)

    def test_reportgen_cli_mcp_subcommand(self):
        for alias in ["mcp", "serve", "server"]:
            # 1. Default (no-watch is default)
            with patch("pystdoc.mcp_server.run_mcp_server") as mock_mcp:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([
                        alias,
                        "--dir", str(self.test_dir),
                    ])
                self.assertEqual(cm.exception.code, 0)
                mock_mcp.assert_called_once_with(
                    target_dir=self.test_dir, auto_watch=False
                )

            # 2. Explicit --watch
            with patch("pystdoc.mcp_server.run_mcp_server") as mock_mcp:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([
                        alias,
                        "--dir", str(self.test_dir),
                        "--watch",
                    ])
                self.assertEqual(cm.exception.code, 0)
                mock_mcp.assert_called_once_with(
                    target_dir=self.test_dir, auto_watch=True
                )

            # 3. Explicit --no-watch
            with patch("pystdoc.mcp_server.run_mcp_server") as mock_mcp:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([
                        alias,
                        "--dir", str(self.test_dir),
                        "--no-watch",
                    ])
                self.assertEqual(cm.exception.code, 0)
                mock_mcp.assert_called_once_with(
                    target_dir=self.test_dir, auto_watch=False
                )

    def test_reportgen_cli_locate_subcommand(self):
        for alias in ["locate", "find", "search"]:
            with patch("pystdoc.cli.run_locate", return_value=0) as mock_loc:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([
                        alias,
                        "--dir", str(self.test_dir),
                        "debug_button",
                    ])
                self.assertEqual(cm.exception.code, 0)
                mock_loc.assert_called_once_with(
                    self.test_dir, "debug_button"
                )

        # Missing query
        with self.assertRaises(SystemExit) as cm:
            reportgen_main(["locate", "--dir", str(self.test_dir)])
        self.assertEqual(cm.exception.code, 1)

    def test_reportgen_cli_impact_subcommand(self):
        for alias in ["impact", "trace", "callers"]:
            with patch("pystdoc.cli.run_impact", return_value=0) as mock_imp:
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main([
                        alias,
                        "--dir", str(self.test_dir),
                        "MySymbol",
                    ])
                self.assertEqual(cm.exception.code, 0)
                mock_imp.assert_called_once_with(
                    self.test_dir, "MySymbol"
                )

        # Missing symbol
        with self.assertRaises(SystemExit) as cm:
            reportgen_main(["impact", "--dir", str(self.test_dir)])
        self.assertEqual(cm.exception.code, 1)

    def test_reportgen_cli_fast_pipeline(self):
        test_args = [
            "pystdoc",
            "sync",
            "--fast",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--language", "English",
        ]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main()
            self.assertEqual(cm.exception.code, 0)
        # In fast mode, documents/ is created, but README.md is not generated
        self.assertTrue((self.test_dir / ".pystdoc" / "documents").exists())
        self.assertFalse((self.test_dir / ".pystdoc" / "README.md").exists())

    def test_watch_cli_fast(self):
        with patch("pystdoc.watcher.DNotifyWatcher.start") as mock_start:
            test_args = [
                "pystdoc",
                "watch",
                "--fast",
                "--dir", str(self.test_dir),
                "--no-llm",
                "--allow-fallback",
            ]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main()
                self.assertEqual(cm.exception.code, 0)
                mock_start.assert_called_once()

    def test_cli_default_language_from_terminal(self):
        # When --language is NOT specified, terminal language is used
        test_args = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
        ]
        with patch.dict("os.environ", {"LANG": "ja_JP.UTF-8"}, clear=False):
            with patch(
                "pystdoc.cli.run_docgen", return_value=0
            ) as mock_docgen:
                with patch("sys.argv", test_args):
                    with self.assertRaises(SystemExit) as cm:
                        docgen_main()
                    self.assertEqual(cm.exception.code, 0)
                    mock_docgen.assert_called_once()
                    _, kwargs = mock_docgen.call_args
                    self.assertEqual(kwargs.get("language"), "Japanese")

        # When --language IS specified, the explicit argument should be used
        test_args_explicit = [
            "docgen",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--language", "French",
        ]
        with patch.dict("os.environ", {"LANG": "ja_JP.UTF-8"}, clear=False):
            with patch(
                "pystdoc.cli.run_docgen", return_value=0
            ) as mock_docgen:
                with patch("sys.argv", test_args_explicit):
                    with self.assertRaises(SystemExit) as cm:
                        docgen_main()
                    self.assertEqual(cm.exception.code, 0)
                    mock_docgen.assert_called_once()
                    _, kwargs = mock_docgen.call_args
                    self.assertEqual(kwargs.get("language"), "French")

    def test_normalize_step_identifier(self):
        self.assertEqual(normalize_step_identifier("1"), 1)
        self.assertEqual(normalize_step_identifier("docgen"), 1)
        self.assertEqual(normalize_step_identifier("symbol"), 1)
        self.assertEqual(normalize_step_identifier("2"), 2)
        self.assertEqual(normalize_step_identifier("data"), 2)
        self.assertEqual(normalize_step_identifier("variables"), 2)
        self.assertEqual(normalize_step_identifier("3"), 3)
        self.assertEqual(normalize_step_identifier("designgen"), 3)
        self.assertEqual(normalize_step_identifier("design"), 3)
        self.assertEqual(normalize_step_identifier("4"), 4)
        self.assertEqual(normalize_step_identifier("reportgen"), 4)
        self.assertEqual(normalize_step_identifier("readme"), 4)
        self.assertIsNone(normalize_step_identifier(None))
        self.assertIsNone(normalize_step_identifier("invalid_step"))
        self.assertIsNone(normalize_step_identifier("99"))

    @patch("pystdoc.cli.run_docgen", return_value=0)
    @patch("pystdoc.cli.run_design_generation", return_value=0)
    @patch("pystdoc.cli.generate_readme_doc")
    def test_cli_from_step_and_step_options(
        self, mock_report, mock_design, mock_docgen
    ):
        # 1. --from-step 3: skips docgen (Step 1,2), executes design & report
        test_args_from3 = [
            "pystdoc",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--from-step", "3",
        ]
        with patch("sys.argv", test_args_from3):
            with self.assertRaises(SystemExit) as cm:
                pystdoc_main()
            self.assertEqual(cm.exception.code, 0)
            mock_docgen.assert_not_called()
            mock_design.assert_called_once()
            mock_report.assert_called_once()

        mock_docgen.reset_mock()
        mock_design.reset_mock()
        mock_report.reset_mock()

        # 2. --step 4 (reportgen): skips docgen & designgen, executes report
        test_args_step4 = [
            "pystdoc",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--step", "reportgen",
        ]
        with patch("sys.argv", test_args_step4):
            with self.assertRaises(SystemExit) as cm:
                pystdoc_main()
            self.assertEqual(cm.exception.code, 0)
            mock_docgen.assert_not_called()
            mock_design.assert_not_called()
            mock_report.assert_called_once()

        mock_docgen.reset_mock()
        mock_design.reset_mock()
        mock_report.reset_mock()

        # 3. --step 3 (designgen): skips docgen, runs designgen, skips report
        test_args_step3 = [
            "pystdoc",
            "--dir", str(self.test_dir),
            "--no-llm",
            "--allow-fallback",
            "--step", "3",
        ]
        with patch("sys.argv", test_args_step3):
            with self.assertRaises(SystemExit) as cm:
                pystdoc_main()
            self.assertEqual(cm.exception.code, 0)
            mock_docgen.assert_not_called()
            mock_design.assert_called_once()
            mock_report.assert_not_called()

        # 4. Invalid --from-step exits with code 1
        with patch("sys.argv", ["pystdoc", "--from-step", "invalid"]):
            with self.assertRaises(SystemExit) as cm:
                pystdoc_main()
            self.assertEqual(cm.exception.code, 1)

    @patch("pystdoc.cli.run_docgen", return_value=0)
    @patch("pystdoc.cli.run_design_generation", return_value=0)
    @patch("pystdoc.cli.generate_readme_doc")
    def test_cli_debug_flag(self, _mock_rep, _mock_des, _mock_doc):
        from pystdoc.llm_client import is_debug_mode, set_debug_mode
        try:
            set_debug_mode(False)
            self.assertFalse(is_debug_mode())

            test_args = [
                "pystdoc",
                "--dir", str(self.test_dir),
                "--no-llm",
                "--allow-fallback",
                "--debug",
            ]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as cm:
                    pystdoc_main()
                self.assertEqual(cm.exception.code, 0)
                self.assertTrue(is_debug_mode())
        finally:
            set_debug_mode(False)


if __name__ == "__main__":
    unittest.main()
