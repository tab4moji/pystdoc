"""Live integration tests using real LiteRT-LM Gemma 4 server on LAN."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.db import DocgenDB
from pystdoc.design_engine import run_design_generation
from pystdoc.engine import run_docgen
from pystdoc.llm_client import LLMClient
from pystdoc.report_engine import generate_readme_doc

REAL_SERVER_HOST = "http://192.168.11.6:11434"
REAL_SERVER_MODEL = "gemma4-26b-a4b"


def is_real_server_available() -> bool:
    """Check if the real LiteRT-LM server is reachable."""
    try:
        client = LLMClient(
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
        )
        return client.check_availability()
    except Exception:
        return False


@unittest.skipUnless(
    is_real_server_available(),
    f"Real LiteRT-LM server not reachable at {REAL_SERVER_HOST}",
)
class TestRealLiteRTServer(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_real_server_explain_symbol_and_labels(self):
        """Test symbol explanation on Gemma 4 and document_labels.json."""
        py_file = self.src_dir / "math_service.py"
        py_file.write_text(
            "def multiply(a: int, b: int) -> int:\n"
            "    \"\"\"Multiply two integers.\"\"\"\n"
            "    return a * b\n\n"
            "def compute_total(x: int) -> int:\n"
            "    return multiply(x, 10)\n",
            encoding="utf-8",
        )

        ret = run_docgen(
            target_dir=self.test_dir,
            use_llm=True,
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
            language="Japanese",
            force=True,
        )
        self.assertEqual(ret, 0)

        # 1. Verify .pystdoc/document_labels.json was created
        # with Japanese software terms
        labels_file = self.test_dir / ".pystdoc" / "document_labels.json"
        self.assertTrue(labels_file.exists())
        labels_text = labels_file.read_text(encoding="utf-8")
        self.assertIn('"language": "Japanese"', labels_text)
        self.assertIn('"basic_info_title": "## 1. 基本情報"', labels_text)
        self.assertIn('"label_symbol_kind": "シンボル種別"', labels_text)

        # 2. Verify symbol doc contains Japanese headings and 関数仕様書
        mul_doc = (
            self.test_dir
            / ".pystdoc"
            / "documents"
            / "src"
            / "math_service.py.fn.multiply.md"
        )
        self.assertTrue(mul_doc.exists())
        doc_text = mul_doc.read_text(encoding="utf-8")
        self.assertIn("関数仕様書: `multiply`", doc_text)
        self.assertNotIn("Function 仕様書", doc_text)
        self.assertIn("## 1. 基本情報", doc_text)
        self.assertIn("- **シンボル種別**:", doc_text)
        self.assertIn("## 3.", doc_text)
        self.assertIn("return a * b", doc_text)

    def test_real_server_sync_and_early_stopping_code_flush(self):
        """Test bottom-up sync with early stopping updates code snippets."""
        c_file = self.src_dir / "calculator.c"
        c_file.write_text(
            "int add(int a, int b) {\n"
            "    return a + b;\n"
            "}\n"
            "int calculate(int x) {\n"
            "    return add(x, 5);\n"
            "}\n",
            encoding="utf-8",
        )

        ret1 = run_docgen(
            target_dir=self.test_dir,
            use_llm=True,
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
            language="Japanese",
        )
        self.assertEqual(ret1, 0)

        add_doc = (
            self.test_dir
            / ".pystdoc"
            / "documents"
            / "src"
            / "calculator.c.fn.add.md"
        )
        self.assertTrue(add_doc.exists())
        self.assertIn("return a + b;", add_doc.read_text(encoding="utf-8"))

        # Modify add() internal code without changing external signature
        import time
        time.sleep(0.05)
        c_file.write_text(
            "int add(int a, int b) {\n"
            "    int sum = a + b;\n"
            "    return sum;\n"
            "}\n"
            "int calculate(int x) {\n"
            "    return add(x, 5);\n"
            "}\n",
            encoding="utf-8",
        )

        ret2 = run_docgen(
            target_dir=self.test_dir,
            use_llm=True,
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
            language="Japanese",
        )
        self.assertEqual(ret2, 0)

        # Code snippet must be updated with newest implementation
        updated_add = add_doc.read_text(encoding="utf-8")
        self.assertIn("int sum = a + b;", updated_add)

    def test_real_server_full_pipeline_sync(self):
        """Test full pipeline: docgen -> designgen -> reportgen on Gemma 4."""
        py_file = self.src_dir / "app_entry.py"
        py_file.write_text(
            "def main():\n"
            "    print('App running')\n"
            "    return 0\n",
            encoding="utf-8",
        )

        # Step 1-2: docgen
        ret_docgen = run_docgen(
            target_dir=self.test_dir,
            use_llm=True,
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
            language="Japanese",
        )
        self.assertEqual(ret_docgen, 0)

        # Step 3: designgen
        ret_design = run_design_generation(
            target_dir=self.test_dir,
            use_llm=True,
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
            language="Japanese",
        )
        self.assertEqual(ret_design, 0)
        self.assertTrue(
            (self.test_dir / ".pystdoc" / "design" / "overview.md").exists()
        )

        # Step 4: reportgen (README)
        client = LLMClient(host=REAL_SERVER_HOST, model=REAL_SERVER_MODEL)
        db_path = self.test_dir / ".pystdoc" / "index.db"
        db = DocgenDB(db_path)
        ret_readme = generate_readme_doc(
            target_dir=self.test_dir,
            llm_client=client,
            language="Japanese",
            db=db,
        )
        db.close()
        self.assertTrue(bool(ret_readme))
        readme_path = self.test_dir / ".pystdoc" / "README.md"
        self.assertTrue(readme_path.exists())

    def test_real_server_foreign_language_labels_generation(self):
        """Test LLM generation of document_labels.json for foreign language."""
        py_file = self.src_dir / "greeter.py"
        py_file.write_text(
            "def greet(name: str) -> str:\n"
            "    \"\"\"Return greeting message.\"\"\"\n"
            "    return f'Hello, {name}'\n",
            encoding="utf-8",
        )

        ret = run_docgen(
            target_dir=self.test_dir,
            use_llm=True,
            host=REAL_SERVER_HOST,
            model=REAL_SERVER_MODEL,
            language="German",
            force=True,
        )
        self.assertEqual(ret, 0)

        # 1. Verify .pystdoc/document_labels.json was generated by LLM
        labels_file = self.test_dir / ".pystdoc" / "document_labels.json"
        self.assertTrue(labels_file.exists())
        labels_text = labels_file.read_text(encoding="utf-8")
        self.assertIn('"language": "German"', labels_text)

        # 2. Verify symbol doc exists and uses generated labels
        greet_doc = (
            self.test_dir
            / ".pystdoc"
            / "documents"
            / "src"
            / "greeter.py.fn.greet.md"
        )
        self.assertTrue(greet_doc.exists())
        doc_text = greet_doc.read_text(encoding="utf-8")
        # German document should contain generated heading (not empty)
        self.assertIn("##", doc_text)
        self.assertIn("greet", doc_text)


if __name__ == "__main__":
    unittest.main()
