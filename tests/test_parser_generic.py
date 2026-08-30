#!/usr/bin/env python3
"""Unit tests for parser_generic."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.parser_generic import parse_generic_file


class TestParserGeneric(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_shell_script(self):
        sh_file = self.test_dir / "setup.sh"
        sh_file.write_text(
            "#!/bin/bash\n"
            "# Comment line\n"
            "\n"
            "setup_env() {\n"
            "    echo 'setting up'\n"
            "}\n"
            "\n"
            "function run_task() {\n"
            "    echo 'running'\n"
            "}\n",
            encoding="utf-8",
        )

        symbols = parse_generic_file(sh_file)
        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[0].name, "setup_env")
        self.assertEqual(symbols[0].kind, "function")
        self.assertEqual(symbols[0].fqdn, "setup.sh::setup_env")
        self.assertEqual(symbols[1].name, "run_task")
        self.assertEqual(symbols[1].fqdn, "setup.sh::run_task")

    def test_parse_non_existent_file(self):
        non_existent = self.test_dir / "does_not_exist.sh"
        symbols = parse_generic_file(non_existent)
        self.assertEqual(symbols, [])


if __name__ == "__main__":
    unittest.main()
