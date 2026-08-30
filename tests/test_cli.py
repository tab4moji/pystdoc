#!/usr/bin/env python3
"""Unit tests for CLI entry points in pystdoc.cli."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pystdoc.cli import docgen_main, designgen_main, reportgen_main


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        sample_file = self.test_dir / "sample.c"
        sample_file.write_text("int main() { return 0; }\n", encoding="utf-8")

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
