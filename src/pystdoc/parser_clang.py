"""Clang-based parser for C/C++ source and header files using libclang with compilation database integration."""

import os
from pathlib import Path
from typing import Any, List, Optional, Set

from pystdoc.symbols import Parameter, Symbol
from pystdoc.compilation_db import CompilationDatabase

_libclang_loaded = False


def _ensure_libclang_loaded() -> None:
    """Ensure libclang shared library is explicitly configured and loaded."""
    global _libclang_loaded
    if _libclang_loaded:
        return

    import clang.cindex

    candidates = [
        "/usr/lib/llvm-21/lib/libclang.so",
        "/usr/lib/llvm-20/lib/libclang.so",
        "/usr/lib/llvm-19/lib/libclang.so",
        "/usr/lib/llvm-18/lib/libclang.so",
        "/usr/lib/llvm-17/lib/libclang.so",
        "/usr/lib/x86_64-linux-gnu/libclang.so",
        "/usr/lib/x86_64-linux-gnu/libclang-19.so",
        "/usr/lib/x86_64-linux-gnu/libclang-18.so",
        "/usr/lib/libclang.so",
    ]

    for c in candidates:
        if os.path.exists(c):
            try:
                clang.cindex.Config.set_library_file(c)
                _libclang_loaded = True
                return
            except Exception:
                continue

    _libclang_loaded = True


def _extract_callees(cursor, file_path: Path) -> List[str]:
    """Recursively traverse cursor AST to collect function call names."""
    import clang.cindex

    callees: Set[str] = set()

    def visit(c):
        if c.kind == clang.cindex.CursorKind.CALL_EXPR:
            if c.spelling:
                callees.add(c.spelling)
            elif c.referenced and c.referenced.spelling:
                callees.add(c.referenced.spelling)
        for child in c.get_children():
            visit(child)

    visit(cursor)
    return sorted(list(callees))


def parse_clang_file(
    file_path: Path,
    comp_db: Optional[CompilationDatabase] = None,
) -> List[Symbol]:
    """Parse a C/C++ or header file with compile flags and extract symbols with FQDN."""
    _ensure_libclang_loaded()
    import clang.cindex

    index = clang.cindex.Index.create()
    target_abs = str(file_path.resolve())

    # Get flags from Compilation Database
    if comp_db:
        args = comp_db.get_flags_for_file(file_path)
    else:
        db = CompilationDatabase(target_dir=file_path.parent)
        args = db.get_flags_for_file(file_path)

    tu = index.parse(
        target_abs,
        args=args,
        options=clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )

    symbols: List[Symbol] = []
    file_prefix = file_path.name

    for cursor in tu.cursor.get_children():
        if not cursor.location.file or os.path.abspath(cursor.location.file.name) != target_abs:
            continue

        sym = _parse_cursor(cursor, file_path, prefix=file_prefix)
        if sym:
            symbols.append(sym)

    return symbols


def _parse_cursor(cursor, file_path: Path, prefix: str = "") -> Optional[Symbol]:
    """Convert a Clang cursor to a Symbol data structure with FQDN."""
    import clang.cindex

    kind_map = {
        clang.cindex.CursorKind.FUNCTION_DECL: "function",
        clang.cindex.CursorKind.CXX_METHOD: "method",
        clang.cindex.CursorKind.CONSTRUCTOR: "constructor",
        clang.cindex.CursorKind.DESTRUCTOR: "destructor",
        clang.cindex.CursorKind.STRUCT_DECL: "struct",
        clang.cindex.CursorKind.CLASS_DECL: "class",
        clang.cindex.CursorKind.ENUM_DECL: "enum",
        clang.cindex.CursorKind.TYPEDEF_DECL: "typedef",
        clang.cindex.CursorKind.TYPE_ALIAS_DECL: "type_alias",
        clang.cindex.CursorKind.VAR_DECL: "variable",
        clang.cindex.CursorKind.FIELD_DECL: "field",
        clang.cindex.CursorKind.ENUM_CONSTANT_DECL: "enum_constant",
    }

    if cursor.kind not in kind_map:
        return None

    name = cursor.spelling or cursor.displayname
    if not name:
        return None

    kind = kind_map[cursor.kind]
    line_start = cursor.extent.start.line
    line_end = cursor.extent.end.line
    raw_comment = cursor.raw_comment or ""
    signature = cursor.type.spelling if cursor.type else ""
    fqdn = f"{prefix}::{name}" if prefix else name

    callees = _extract_callees(cursor, file_path) if kind in ("function", "method", "constructor", "destructor") else []

    params: List[Parameter] = []
    return_type = ""

    if kind in ("function", "method", "constructor", "destructor"):
        return_type = cursor.result_type.spelling if cursor.result_type else ""
        for arg in cursor.get_arguments():
            params.append(
                Parameter(
                    name=arg.spelling,
                    type_hint=arg.type.spelling if arg.type else "",
                )
            )

    children: List[Symbol] = []
    if kind in ("struct", "class", "enum"):
        for child_cursor in cursor.get_children():
            child_sym = _parse_cursor(child_cursor, file_path, prefix=fqdn)
            if child_sym:
                children.append(child_sym)

    return Symbol(
        name=name,
        kind=kind,
        line_start=line_start,
        line_end=line_end,
        fqdn=fqdn,
        signature=signature,
        doc=raw_comment.strip(),
        parameters=params,
        return_type=return_type,
        callees=callees,
        children=children,
    )
