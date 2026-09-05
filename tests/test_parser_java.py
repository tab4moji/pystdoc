#!/usr/bin/env python3
"""Unit tests for Java parser and JavaAdapter."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.adapters.java_adapter import (
    JavaAdapter,
    _extract_java_callees,
    _format_type,
)
from pystdoc.parser_java import parse_java_file


class TestParserJava(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.adapter = JavaAdapter()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_adapter_properties(self):
        self.assertEqual(self.adapter.name, "java")
        self.assertEqual(self.adapter.supported_extensions, (".java",))
        self.assertEqual(self.adapter.default_code_language, "java")
        self.assertEqual(self.adapter.get_code_language(".java"), "java")
        self.assertTrue(self.adapter.can_handle(Path("Foo.java")))
        self.assertFalse(self.adapter.can_handle(Path("Foo.py")))

    def test_parse_comprehensive_java(self):
        java_file = self.test_dir / "OrderService.java"
        java_file.write_text(
            """package com.example.service;

import java.io.IOException;
import java.util.List;
import java.util.Map;

/**
 * Service for managing orders.
 */
public class OrderService {
    private final Database db;
    public static int counter = 0;
    private String[] tags;

    /**
     * Constructs OrderService.
     */
    public OrderService(Database db) {
        this(db, 0);
    }

    public OrderService(Database db, int initialCount) {
        this.db = db;
        counter = initialCount;
    }

    /**
     * Processes an order for a customer.
     * @param customerId the customer id
     * @param items list of item names
     * @return boolean true if successful
     */
    public boolean processOrder(
        int customerId,
        List<String> items,
        Map<String, Integer> options
    ) throws IOException {
        validate(customerId);
        int total = calculateTotal(items);
        DatabaseHelper helper = new DatabaseHelper();
        db.saveOrder(customerId, total);
        counter++;
        return true;
    }

    private int calculateTotal(List<String> items) {
        return items.size() * 10;
    }

    private void validate(int id) {
        if (id <= 0) {
            throw new IllegalArgumentException();
        }
    }

    public enum Priority {
        /** Low priority */
        LOW,
        MEDIUM,
        HIGH
    }

    public interface Callback {
        void onComplete(boolean success);
    }
}
""",
            encoding="utf-8",
        )

        symbols = parse_java_file(java_file)
        self.assertEqual(len(symbols), 1)

        cls_sym = symbols[0]
        self.assertEqual(cls_sym.name, "OrderService")
        self.assertEqual(cls_sym.kind, "class")
        self.assertEqual(cls_sym.fqdn, "com.example.service.OrderService")
        self.assertIn("Service for managing orders", cls_sym.doc)
        self.assertEqual(cls_sym.line_start, 10)
        self.assertGreaterEqual(cls_sym.line_end, 50)

        child_names = [c.name for c in cls_sym.children]
        self.assertIn("db", child_names)
        self.assertIn("counter", child_names)
        self.assertIn("tags", child_names)
        self.assertIn("OrderService", child_names)
        self.assertIn("processOrder", child_names)
        self.assertIn("calculateTotal", child_names)
        self.assertIn("validate", child_names)
        self.assertIn("Priority", child_names)
        self.assertIn("Callback", child_names)

        # Check fields
        f_db = next(c for c in cls_sym.children if c.name == "db")
        self.assertEqual(f_db.kind, "field")
        self.assertIn("Database db", f_db.signature)
        self.assertEqual(f_db.fqdn, "com.example.service.OrderService.db")

        # Check constructor
        ctors = [c for c in cls_sym.children if c.kind == "constructor"]
        self.assertEqual(len(ctors), 2)
        self.assertEqual(len(ctors[0].parameters), 1)
        self.assertEqual(ctors[0].parameters[0].name, "db")
        self.assertEqual(ctors[0].parameters[0].type_hint, "Database")

        # Check method
        m_proc = next(c for c in cls_sym.children if c.name == "processOrder")
        self.assertEqual(m_proc.kind, "method")
        self.assertEqual(m_proc.return_type, "boolean")
        self.assertEqual(len(m_proc.parameters), 3)
        self.assertEqual(m_proc.parameters[0].name, "customerId")
        self.assertEqual(m_proc.parameters[0].type_hint, "int")
        self.assertEqual(m_proc.parameters[1].name, "items")
        self.assertEqual(m_proc.parameters[1].type_hint, "List<String>")
        self.assertEqual(m_proc.parameters[2].name, "options")
        self.assertEqual(
            m_proc.parameters[2].type_hint, "Map<String, Integer>"
        )
        self.assertIn("validate", m_proc.callees)
        self.assertIn("calculateTotal", m_proc.callees)
        self.assertIn("saveOrder", m_proc.callees)
        self.assertIn("DatabaseHelper", m_proc.callees)

        # Check enum
        enum_sym = next(c for c in cls_sym.children if c.name == "Priority")
        self.assertEqual(enum_sym.kind, "enum")
        self.assertEqual(
            enum_sym.fqdn, "com.example.service.OrderService.Priority"
        )
        const_names = [c.name for c in enum_sym.children]
        self.assertEqual(const_names, ["LOW", "MEDIUM", "HIGH"])
        self.assertEqual(enum_sym.children[0].kind, "enum_constant")
        self.assertIn("Low priority", enum_sym.children[0].doc)

        # Check inner interface
        iface_sym = next(c for c in cls_sym.children if c.name == "Callback")
        self.assertEqual(iface_sym.kind, "class")
        self.assertEqual(len(iface_sym.children), 1)
        self.assertEqual(iface_sym.children[0].name, "onComplete")

    def test_parse_java_without_package(self):
        java_file = self.test_dir / "Simple.java"
        java_file.write_text(
            "public class Simple { public void run() {} }",
            encoding="utf-8",
        )
        symbols = parse_java_file(java_file)
        self.assertEqual(len(symbols), 1)
        self.assertEqual(symbols[0].fqdn, "Simple.Simple")
        self.assertEqual(symbols[0].children[0].fqdn, "Simple.Simple.run")

    def test_parse_non_existent_and_invalid_file(self):
        non_existent = self.test_dir / "Missing.java"
        self.assertEqual(parse_java_file(non_existent), [])

        invalid_file = self.test_dir / "Broken.java"
        invalid_file.write_text(
            "class Broken { ??? invalid syntax",
            encoding="utf-8",
        )
        self.assertEqual(parse_java_file(invalid_file), [])

    def test_helpers_direct(self):
        self.assertEqual(_format_type(None), "void")
        self.assertEqual(_format_type("String"), "String")
        self.assertEqual(_extract_java_callees(None), [])


if __name__ == "__main__":
    unittest.main()
