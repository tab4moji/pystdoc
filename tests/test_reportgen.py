#!/usr/bin/env python3
"""Unit tests for reportgen."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.design_engine import run_design_generation
from pystdoc.engine import run_docgen
from pystdoc.report_engine import generate_readme_doc


class TestReportgen(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.docgen_dir = self.test_dir / ".docgen"
        self.design_dir = self.docgen_dir / "design"
        self.design_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_readme_doc_multi_language(self):
        # Default English
        content_en = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=None,
            language="English",
            allow_fallback=True,
        )
        self.assertIn("## 1. What Does This Project Do?", content_en)

        # Japanese option
        content_ja = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=None,
            language="Japanese",
            allow_fallback=True,
        )
        self.assertIn("## 1. What Does This Project Do?", content_ja)

    def test_run_full_pipeline_no_llm(self):
        sample_file = self.test_dir / "main.c"
        sample_file.write_text("int main() { return 0; }\n", encoding="utf-8")

        res1 = run_docgen(
            target_dir=self.test_dir, use_llm=False, allow_fallback=True
        )
        self.assertEqual(res1, 0)
        res2 = run_design_generation(
            target_dir=self.test_dir, use_llm=False, allow_fallback=True
        )
        self.assertEqual(res2, 0)
        generate_readme_doc(
            target_dir=self.test_dir, llm_client=None, allow_fallback=True
        )
        self.assertTrue((self.test_dir / ".docgen" / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
