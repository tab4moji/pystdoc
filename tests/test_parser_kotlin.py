#!/usr/bin/env python3
"""Unit tests for Kotlin parser and KotlinAdapter."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pystdoc.adapters.kotlin_adapter import (
    KotlinAdapter,
    _extract_kotlin_callees,
    _extract_preceding_doc,
    _format_type_node,
)
from pystdoc.parser_kotlin import parse_kotlin_file


class TestParserKotlin(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.adapter = KotlinAdapter()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_adapter_properties(self):
        self.assertEqual(self.adapter.name, "kotlin")
        self.assertEqual(self.adapter.supported_extensions, (".kt", ".kts"))
        self.assertEqual(self.adapter.default_code_language, "kotlin")
        self.assertEqual(self.adapter.get_code_language(".kt"), "kotlin")
        self.assertEqual(self.adapter.get_code_language(".kts"), "kotlin")
        self.assertTrue(self.adapter.can_handle(Path("App.kt")))
        self.assertTrue(self.adapter.can_handle(Path("build.gradle.kts")))
        self.assertFalse(self.adapter.can_handle(Path("App.java")))

    def test_parse_comprehensive_kotlin(self):
        kt_file = self.test_dir / "UserService.kt"
        kt_file.write_text(
            """package com.example.user

import java.io.File

/**
 * Status of the user account.
 */
enum class UserStatus {
    /** Active status */
    ACTIVE,
    PENDING,
    SUSPENDED
}

interface UserHandler {
    fun handleUser(id: Long): Boolean
}

/**
 * Service to manage users and notifications.
 */
class UserService(
    val repo: String,
    var timeout: Int
) : UserHandler {
    var maxUsers: Int = 100

    companion object {
        val DEFAULT_TIMEOUT = 3000
        fun createDefault(): UserService {
            return UserService("default_repo", DEFAULT_TIMEOUT)
        }
    }

    constructor(repo: String) : this(repo, 1000)

    /**
     * Finds and processes a user.
     */
    suspend fun findAndProcess(
        userId: Long,
        tags: List<String>
    ): Map<String, Int> {
        val status = checkStatus(userId)
        logger.info("Processing user: " + userId)
        println(status)
        return emptyMap()
    }

    private fun checkStatus(id: Long): UserStatus {
        return UserStatus.ACTIVE
    }

    override fun handleUser(id: Long): Boolean {
        return true
    }
}

val GLOBAL_VERSION = "1.0.0"

fun topLevelUtility(input: String): String {
    return input.trim()
}
""",
            encoding="utf-8",
        )

        symbols = parse_kotlin_file(kt_file)
        self.assertGreaterEqual(len(symbols), 4)

        sym_names = [s.name for s in symbols]
        self.assertIn("UserStatus", sym_names)
        self.assertIn("UserHandler", sym_names)
        self.assertIn("UserService", sym_names)
        self.assertIn("GLOBAL_VERSION", sym_names)
        self.assertIn("topLevelUtility", sym_names)

        # 1. Check Enum
        enum_sym = next(s for s in symbols if s.name == "UserStatus")
        self.assertEqual(enum_sym.kind, "enum")
        self.assertEqual(enum_sym.fqdn, "com.example.user.UserStatus")
        self.assertIn("Status of the user account", enum_sym.doc)
        entry_names = [c.name for c in enum_sym.children]
        self.assertEqual(entry_names, ["ACTIVE", "PENDING", "SUSPENDED"])
        self.assertEqual(enum_sym.children[0].kind, "enum_constant")
        self.assertIn("Active status", enum_sym.children[0].doc)

        # 2. Check Interface
        iface_sym = next(s for s in symbols if s.name == "UserHandler")
        self.assertEqual(iface_sym.kind, "class")
        self.assertEqual(len(iface_sym.children), 1)
        self.assertEqual(iface_sym.children[0].name, "handleUser")

        # 3. Check Class
        cls_sym = next(s for s in symbols if s.name == "UserService")
        self.assertEqual(cls_sym.kind, "class")
        self.assertEqual(cls_sym.fqdn, "com.example.user.UserService")
        self.assertIn("Service to manage users", cls_sym.doc)

        child_names = [c.name for c in cls_sym.children]
        self.assertIn("repo", child_names)
        self.assertIn("timeout", child_names)
        self.assertIn("maxUsers", child_names)
        self.assertIn("Companion", child_names)
        self.assertIn("UserService", child_names)  # secondary constructor
        self.assertIn("findAndProcess", child_names)
        self.assertIn("checkStatus", child_names)

        # Check primary constructor properties
        f_repo = next(c for c in cls_sym.children if c.name == "repo")
        self.assertEqual(f_repo.kind, "field")
        self.assertEqual(f_repo.fqdn, "com.example.user.UserService.repo")

        # Check companion object
        comp_sym = next(c for c in cls_sym.children if c.name == "Companion")
        self.assertEqual(comp_sym.kind, "class")
        comp_children = [c.name for c in comp_sym.children]
        self.assertIn("DEFAULT_TIMEOUT", comp_children)
        self.assertIn("createDefault", comp_children)

        # Check function
        fn_sym = next(
            c for c in cls_sym.children if c.name == "findAndProcess"
        )
        self.assertEqual(fn_sym.kind, "method")
        self.assertEqual(fn_sym.return_type, "Map<String, Int>")
        self.assertEqual(len(fn_sym.parameters), 2)
        self.assertEqual(fn_sym.parameters[0].name, "userId")
        self.assertEqual(fn_sym.parameters[0].type_hint, "Long")
        self.assertEqual(fn_sym.parameters[1].name, "tags")
        self.assertEqual(fn_sym.parameters[1].type_hint, "List<String>")
        self.assertIn("checkStatus", fn_sym.callees)
        self.assertIn("info", fn_sym.callees)
        self.assertIn("println", fn_sym.callees)
        self.assertIn("emptyMap", fn_sym.callees)

        # 4. Check Top-level property & function
        prop_sym = next(s for s in symbols if s.name == "GLOBAL_VERSION")
        self.assertEqual(prop_sym.kind, "variable")
        self.assertEqual(prop_sym.fqdn, "com.example.user.GLOBAL_VERSION")

        top_fn = next(s for s in symbols if s.name == "topLevelUtility")
        self.assertEqual(top_fn.kind, "function")
        self.assertEqual(top_fn.fqdn, "com.example.user.topLevelUtility")
        self.assertEqual(top_fn.return_type, "String")

    def test_parse_kotlin_without_package(self):
        kt_file = self.test_dir / "Script.kt"
        kt_file.write_text(
            "fun standalone(): Int { return 42 }",
            encoding="utf-8",
        )
        symbols = parse_kotlin_file(kt_file)
        self.assertEqual(len(symbols), 1)
        self.assertEqual(symbols[0].fqdn, "Script.standalone")

    def test_parse_non_existent_and_invalid_file(self):
        non_existent = self.test_dir / "Missing.kt"
        self.assertEqual(parse_kotlin_file(non_existent), [])

        invalid_file = self.test_dir / "Broken.kt"
        invalid_file.write_text(
            "class Broken { ??@! invalid syntax",
            encoding="utf-8",
        )
        self.assertEqual(parse_kotlin_file(invalid_file), [])

    def test_helpers_direct(self):
        self.assertEqual(_format_type_node(None), "")
        self.assertEqual(_format_type_node("String"), "String")
        self.assertEqual(_extract_kotlin_callees(None), [])
        lines = ["// Single comment", "fun foo() {}"]
        self.assertEqual(_extract_preceding_doc(lines, 2), "Single comment")
        self.assertEqual(_extract_preceding_doc(lines, 1), "")
        self.assertEqual(_extract_preceding_doc(lines, 10), "")


if __name__ == "__main__":
    unittest.main()
