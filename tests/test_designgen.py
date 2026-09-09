#!/usr/bin/env python3
"""Unit tests for designgen."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.design_engine import (
    parse_symbol_doc,
    group_docs_by_module,
    chunk_list_by_size,
    hierarchical_reduce_summaries,
    run_design_generation,
)


class TestDesigngen(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.docs_dir = self.test_dir / ".pystdoc" / "documents"
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_chunking_logic(self):
        items = [
            f"Item {i}: some detailed description of function or type {i}"
            for i in range(50)
        ]
        chunks = chunk_list_by_size(items, max_items=10, max_chars=500)
        self.assertTrue(len(chunks) >= 5)
        self.assertEqual(sum(len(c) for c in chunks), 50)

    def test_hierarchical_reduction(self):
        items = [f"- Function {i} does task {i}" for i in range(40)]
        reduced_en = hierarchical_reduce_summaries(
            items=items,
            category_title="Test Functions",
            llm_client=None,
            language="English",
            allow_fallback=True,
            max_items_per_chunk=10,
            max_chars_per_chunk=300,
        )
        self.assertIn("Group 1", reduced_en)

    def test_parse_and_group(self):
        sample_doc = self.docs_dir / "main.c.fn.main.md"
        doc_content = (
            "# Function Documentation: `main`\n\n"
            "## 1. Design Intent & Purpose\n"
            "Main entry point of the program.\n\n"
            "## 2. Basic Information\n"
            "- **Name**: `main`\n"
            "- **Symbol Kind**: `function`\n"
            "- **Signature / Type**: `int main()`\n\n"
            "## 5. Called Functions\n- `helper`\n"
        )
        sample_doc.write_text(doc_content, encoding="utf-8")

        parsed = parse_symbol_doc(sample_doc)
        self.assertEqual(
            parsed["purpose"], "Main entry point of the program."
        )
        self.assertEqual(parsed["kind"], "function")
        self.assertEqual(parsed["callees"], ["helper"])

        grouped = group_docs_by_module([parsed])
        self.assertIn("main", grouped)

    def test_run_designgen_with_cache(self):
        sample_doc = self.docs_dir / "main.c.fn.main.md"
        doc_content = (
            "# Function Documentation: `main`\n\n"
            "## 1. Design Intent & Purpose\nMain entry point.\n\n"
            "## 2. Basic Information\n"
            "- **Name**: `main`\n"
            "- **Symbol Kind**: `function`\n"
            "- **Signature / Type**: `int main()`\n\n"
        )
        sample_doc.write_text(doc_content, encoding="utf-8")

        # 1st run
        res1 = run_design_generation(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
            language="English",
        )
        self.assertEqual(res1, 0)

        # 2nd run (Cached)
        res2 = run_design_generation(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
            language="English",
        )
        self.assertEqual(res2, 0)
        design_dir = self.test_dir / ".pystdoc" / "design"
        self.assertTrue((design_dir / "data_models.md").exists())
        self.assertTrue((design_dir / "execution_model.md").exists())
        self.assertTrue((design_dir / "overview.md").exists())

    def test_designgen_regenerates_when_design_file_deleted(self):
        sample_doc = self.docs_dir / "main.c.fn.main.md"
        doc_content = (
            "# Function Documentation: `main`\n\n"
            "## 1. Design Intent & Purpose\nMain entry point.\n\n"
            "## 2. Basic Information\n"
            "- **Name**: `main`\n"
            "- **Symbol Kind**: `function`\n"
            "- **Signature / Type**: `int main()`\n\n"
        )
        sample_doc.write_text(doc_content, encoding="utf-8")

        # 1st run
        res1 = run_design_generation(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
            language="English",
        )
        self.assertEqual(res1, 0)
        overview_file = self.test_dir / ".pystdoc" / "design" / "overview.md"
        self.assertTrue(overview_file.exists())

        # Delete overview.md
        overview_file.unlink()
        self.assertFalse(overview_file.exists())

        # 2nd run: should detect missing file and regenerate
        res2 = run_design_generation(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
            language="English",
        )
        self.assertEqual(res2, 0)
        self.assertTrue(overview_file.exists())


if __name__ == "__main__":
    unittest.main()
