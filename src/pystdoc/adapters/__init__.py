"""Language adapters and unified registry for multi-language AST parsing."""

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

__all__ = [
    "BaseLanguageAdapter",
    "LanguageAdapterRegistry",
    "get_default_registry",
    "ClangAdapter",
    "PythonAdapter",
    "JavaAdapter",
    "KotlinAdapter",
    "GenericAdapter",
    "calculate_block_end_line",
    "clean_docstring",
    "build_fqdn",
]
