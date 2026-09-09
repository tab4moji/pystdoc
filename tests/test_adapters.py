#!/usr/bin/env python3
"""Unit tests for language adapters and registry."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.adapters.base import (
    BaseLanguageAdapter,
    LanguageAdapterRegistry,
    build_fqdn,
    calculate_block_end_line,
    clean_docstring,
    get_default_registry,
)
from pystdoc.adapters.clang_adapter import ClangAdapter
from pystdoc.adapters.generic_adapter import GenericAdapter
from pystdoc.adapters.java_adapter import JavaAdapter
from pystdoc.adapters.kotlin_adapter import KotlinAdapter
from pystdoc.adapters.python_adapter import PythonAdapter
from pystdoc.doc_writer import extract_symbols, get_code_language
from pystdoc.engine import run_docgen
from pystdoc.symbols import Symbol


class DummyCustomAdapter(BaseLanguageAdapter):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def supported_extensions(self):
        return (".dummy",)

    @property
    def default_code_language(self) -> str:
        return "dummy"

    def parse(self, file_path, comp_db=None, base_dir=None):
        return [
            Symbol(
                name="dummy_sym",
                kind="function",
                line_start=1,
                line_end=1,
                fqdn="dummy_sym",
            )
        ]


class TestLanguageAdapters(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_registry_operations(self):
        registry = LanguageAdapterRegistry()
        dummy = DummyCustomAdapter()
        registry.register(dummy)

        self.assertIn(dummy, registry.get_all_adapters())
        self.assertIn(".dummy", registry.get_supported_extensions())
        self.assertEqual(
            registry.get_adapter_for_file(Path("test.dummy")), dummy
        )
        self.assertEqual(registry.get_code_language(".dummy"), "dummy")
        self.assertEqual(registry.get_code_language(".unknown"), "text")
        self.assertIsNone(registry.get_adapter_for_file(Path("test.unknown")))

    def test_default_registry(self):
        reg = get_default_registry()
        exts = reg.get_supported_extensions()
        self.assertIn(".c", exts)
        self.assertIn(".cpp", exts)
        self.assertIn(".py", exts)
        self.assertIn(".java", exts)
        self.assertIn(".kt", exts)
        self.assertIn(".kts", exts)
        self.assertIn(".sh", exts)
        self.assertIn(".rs", exts)

        self.assertIsInstance(
            reg.get_adapter_for_file(Path("main.c")), ClangAdapter
        )
        self.assertIsInstance(
            reg.get_adapter_for_file(Path("app.py")), PythonAdapter
        )
        self.assertIsInstance(
            reg.get_adapter_for_file(Path("App.java")), JavaAdapter
        )
        self.assertIsInstance(
            reg.get_adapter_for_file(Path("App.kt")), KotlinAdapter
        )
        self.assertIsInstance(
            reg.get_adapter_for_file(Path("run.sh")), GenericAdapter
        )

        self.assertEqual(reg.get_code_language(".c"), "c")
        self.assertEqual(reg.get_code_language(".cpp"), "cpp")
        self.assertEqual(reg.get_code_language(".py"), "python")
        self.assertEqual(reg.get_code_language(".java"), "java")
        self.assertEqual(reg.get_code_language(".kt"), "kotlin")
        self.assertEqual(reg.get_code_language(".kts"), "kotlin")
        self.assertEqual(reg.get_code_language(".sh"), "bash")
        self.assertEqual(reg.get_code_language(".rs"), "rust")

    def test_clean_docstring(self):
        self.assertEqual(clean_docstring(None), "")
        self.assertEqual(clean_docstring(""), "")
        self.assertEqual(clean_docstring("Hello world"), "Hello world")

        c_doc = """/**
 * First line
 * Second line
 */"""
        self.assertEqual(
            clean_docstring(c_doc),
            "First line\nSecond line",
        )

    def test_calculate_block_end_line(self):
        lines = [
            "class Foo {",
            "    int a = 10;",
            "    void bar() {",
            "        // comment {",
            '        String s = "{";',
            "    }",
            "}",
        ]
        self.assertEqual(calculate_block_end_line(lines, 1), 7)
        self.assertEqual(calculate_block_end_line(lines, 3), 6)
        self.assertEqual(calculate_block_end_line(lines, 2), 2)
        self.assertEqual(calculate_block_end_line(lines, 100), 100)
        self.assertEqual(calculate_block_end_line(lines, -1), 1)

    def test_build_fqdn(self):
        self.assertEqual(build_fqdn([], "func"), "func")
        self.assertEqual(
            build_fqdn(["pkg", "Class"], "method"),
            "pkg.Class.method",
        )
        self.assertEqual(
            build_fqdn(["file.c"], "func", separator="::"),
            "file.c::func",
        )

    def test_doc_writer_integration(self):
        java_p = self.test_dir / "Test.java"
        java_p.write_text(
            "public class Test { public void hello() {} }",
            encoding="utf-8",
        )
        syms = extract_symbols(java_p)
        self.assertEqual(len(syms), 1)
        self.assertEqual(syms[0].name, "Test")

        kt_p = self.test_dir / "Test.kt"
        kt_p.write_text(
            "class Test { fun hello() {} }",
            encoding="utf-8",
        )
        syms_kt = extract_symbols(kt_p)
        self.assertEqual(len(syms_kt), 1)
        self.assertEqual(syms_kt[0].name, "Test")

        self.assertEqual(get_code_language(".java"), "java")
        self.assertEqual(get_code_language(".kt"), "kotlin")
        self.assertEqual(extract_symbols(self.test_dir / "unknown.xyz"), [])

    def test_full_docgen_with_java_and_kotlin(self):
        src_dir = self.test_dir / "project"
        src_dir.mkdir()

        java_file = src_dir / "Main.java"
        java_file.write_text(
            """package com.app;
public class Main {
    public static void main(String[] args) {
        AppHelper helper = new AppHelper();
        helper.run();
    }
}
class AppHelper {
    public void run() {}
}
""",
            encoding="utf-8",
        )

        kt_file = src_dir / "Utils.kt"
        kt_file.write_text(
            """package com.app
fun calculateSum(a: Int, b: Int): Int {
    return a + b
}
""",
            encoding="utf-8",
        )

        ret = run_docgen(
            target_dir=src_dir,
            use_llm=False,
            allow_fallback=True,
        )
        self.assertEqual(ret, 0)

        # Verify generated documents
        docgen_dir = src_dir / ".pystdoc" / "documents"
        self.assertTrue((docgen_dir / "Main.java.md").exists())
        self.assertTrue((docgen_dir / "Utils.kt.md").exists())
        self.assertTrue((docgen_dir / "Main.java.type.Main.md").exists())
        self.assertTrue((docgen_dir / "Main.java.fn.Main.main.md").exists())
        self.assertTrue((docgen_dir / "Utils.kt.fn.calculateSum.md").exists())


if __name__ == "__main__":
    unittest.main()
