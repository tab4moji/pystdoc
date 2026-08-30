#!/usr/bin/env python3
"""Comprehensive coverage tests for design_engine.py."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pystdoc.design_engine import (
    run_design_generation,
    group_docs_by_module,
    generate_data_models_doc,
    generate_execution_model_doc,
    generate_module_docs,
    generate_overview_doc,
)
from pystdoc.llm_client import LLMError


class TestDesignEngineFull(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.doc_dir = self.test_dir / ".docgen" / "documents"
        self.doc_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_run_design_generation_empty_docs(self):
        ret = run_design_generation(target_dir=self.test_dir, use_llm=False)
        self.assertEqual(ret, 0)

    def test_group_docs_by_module_paths(self):
        docs = [
            {"file_name": "src/network/client.py"},
            {"file_name": "src/service.py"},
            {"file_name": "include/math.h"},
            {"file_name": "scripts/run.sh"},
            {"file_name": "app.c"},
        ]
        grouped = group_docs_by_module(docs)
        self.assertIn("network", grouped)
        self.assertIn("main", grouped)

    def test_synthesize_functions_strict_error(self):
        mock_client = MagicMock()
        mock_client.chat_completion.side_effect = LLMError("LLM offline")

        dummy_docs = [
            {
                "file_name": "src/main.c",
                "purpose": "App main",
                "kind": "function",
                "signature": "int main()",
                "callees": [],
                "referencing_funcs": [],
            }
        ]

        # 1. generate_data_models_doc error
        with self.assertRaises(LLMError):
            generate_data_models_doc(
                dummy_docs,
                dummy_docs,
                mock_client,
                self.test_dir,
                language="English",
                allow_fallback=False,
            )

        # 2. generate_execution_model_doc error
        with self.assertRaises(LLMError):
            generate_execution_model_doc(
                dummy_docs,
                mock_client,
                self.test_dir,
                language="English",
                allow_fallback=False,
            )

        # 3. generate_module_docs error
        with self.assertRaises(LLMError):
            generate_module_docs(
                {"main": dummy_docs},
                mock_client,
                self.test_dir,
                language="English",
                allow_fallback=False,
            )

        # 4. generate_overview_doc error
        with self.assertRaises(LLMError):
            generate_overview_doc(
                "data models",
                "execution model",
                {"main": "module summary"},
                mock_client,
                self.test_dir,
                language="English",
                allow_fallback=False,
            )

    def test_map_reduce_many_docs(self):
        # Create 20 dummy documents to trigger Map-Reduce chunking
        for i in range(20):
            f = self.doc_dir / f"mod_{i}.c.md"
            f.write_text(
                f"# src/mod_{i}.c\n"
                f"- **Symbol Kind**: function\n"
                f"- **Signature**: `void run_{i}()`\n"
                f"- **Core Purpose**: Worker {i} logic\n"
                f"## 5. Called Functions\n- `helper`\n",
                encoding="utf-8",
            )

        mock_client = MagicMock()
        mock_client.chat_completion.return_value = "Synthesized section chunk."

        from unittest.mock import patch
        with patch.object(
            mock_client, "chat_completion", return_value="Synthesized chunk"
        ), patch(
            "pystdoc.design_engine.LLMClient", return_value=mock_client
        ):
            ret = run_design_generation(
                target_dir=self.test_dir,
                use_llm=True,
                language="Japanese",
                force=True,
                allow_fallback=True,
            )
        self.assertEqual(ret, 0)
        self.assertTrue(
            (self.test_dir / ".docgen" / "design" / "data_models.md").exists()
        )
        self.assertTrue(
            (self.test_dir / ".docgen" / "design" / "overview.md").exists()
        )


if __name__ == "__main__":
    unittest.main()
