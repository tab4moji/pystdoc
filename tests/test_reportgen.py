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
        self.assertIn("## 1. Software Classification & Purpose", content_en)

        # Japanese option
        content_ja = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=None,
            language="Japanese",
            allow_fallback=True,
        )
        self.assertIn("## 1. Software Classification & Purpose", content_ja)

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

    def test_readme_caching_and_llm(self):
        from unittest.mock import MagicMock
        from pystdoc.db import DocgenDB
        from pystdoc.llm_client import LLMError

        db = DocgenDB(self.docgen_dir / "index.db")
        mock_llm = MagicMock()
        mock_llm.chat_completion.side_effect = [
            "Answer 1",
            "Answer 2",
            "# Final Generated README",
        ]

        # 1. First run generates and caches in DB
        res = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=mock_llm,
            language="English",
            force=False,
            db=db,
        )
        self.assertIn("# Final Generated README", res)
        self.assertEqual(mock_llm.chat_completion.call_count, 3)

        # 2. Second run with same inputs hits cache
        mock_llm.reset_mock()
        res_cached = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=mock_llm,
            language="English",
            force=False,
            db=db,
        )
        self.assertIn("# Final Generated README", res_cached)
        self.assertEqual(mock_llm.chat_completion.call_count, 0)

        # 3. Force run bypasses cache
        mock_llm.chat_completion.side_effect = [
            "Ans 1", "Ans 2", "# Forced README"
        ]
        res_forced = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=mock_llm,
            language="English",
            force=True,
            db=db,
        )
        self.assertIn("# Forced README", res_forced)
        self.assertEqual(mock_llm.chat_completion.call_count, 3)

        # 4. Fallback exception test
        mock_llm_fail = MagicMock()
        mock_llm_fail.chat_completion.side_effect = Exception("LLM dead")
        with self.assertRaises(LLMError):
            generate_readme_doc(
                target_dir=self.test_dir,
                llm_client=mock_llm_fail,
                language="English",
                force=True,
                allow_fallback=False,
                db=db,
            )


if __name__ == "__main__":
    unittest.main()
