#!/usr/bin/env python3
"""Unit tests for designgen with Map-Reduce chunking, SQLite caching, and multi-language support."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pystdoc.db import DocgenDB
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
        self.docs_dir = self.test_dir / ".docgen" / "documents"
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_chunking_logic(self):
        items = [f"Item {i}: some detailed description of function or type {i}" for i in range(50)]
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
        sample_doc.write_text(
            "# Function Documentation: `main`\n\n"
            "## 1. Design Intent & Purpose\nMain entry point of the program.\n\n"
            "## 2. Basic Information\n- **Name**: `main`\n- **Symbol Kind**: `function`\n- **Signature / Type**: `int main()`\n\n"
            "## 5. Called Functions\n- `helper`\n",
            encoding="utf-8",
        )

        parsed = parse_symbol_doc(sample_doc)
        self.assertEqual(parsed["purpose"], "Main entry point of the program.")
        self.assertEqual(parsed["kind"], "function")
        self.assertEqual(parsed["callees"], ["helper"])

        grouped = group_docs_by_module([parsed])
        self.assertIn("main", grouped)

    def test_run_designgen_with_cache(self):
        sample_doc = self.docs_dir / "main.c.fn.main.md"
        sample_doc.write_text(
            "# Function Documentation: `main`\n\n"
            "## 1. Design Intent & Purpose\nMain entry point.\n\n"
            "## 2. Basic Information\n- **Name**: `main`\n- **Symbol Kind**: `function`\n- **Signature / Type**: `int main()`\n\n",
            encoding="utf-8",
        )

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
        self.assertTrue((self.test_dir / ".docgen" / "design" / "data_models.md").exists())
        self.assertTrue((self.test_dir / ".docgen" / "design" / "execution_model.md").exists())
        self.assertTrue((self.test_dir / ".docgen" / "design" / "overview.md").exists())


if __name__ == "__main__":
    unittest.main()
