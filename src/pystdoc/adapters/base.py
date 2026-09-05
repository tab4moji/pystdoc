"""Base language adapter interface, utilities, and registry."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Symbol


def clean_docstring(doc: Optional[str]) -> str:
    """Clean and strip docstring/Javadoc/KDoc/line comments."""
    if not doc:
        return ""
    text = doc.strip()
    if text.startswith("/*"):
        lines = text.splitlines()
        cleaned_lines = []
        for line in lines:
            l_strip = line.strip()
            if l_strip.startswith("/**"):
                l_strip = l_strip[3:].strip()
            elif l_strip.startswith("/*"):
                l_strip = l_strip[2:].strip()
            if l_strip.endswith("*/"):
                l_strip = l_strip[:-2].strip()
            if l_strip.startswith("*"):
                l_strip = l_strip[1:].strip()
            if l_strip:
                cleaned_lines.append(l_strip)
        return "\n".join(cleaned_lines).strip()
    elif text.startswith("//"):
        lines = text.splitlines()
        cleaned_lines = []
        for line in lines:
            l_strip = line.strip()
            if l_strip.startswith("//"):
                l_strip = l_strip[2:].strip()
            if l_strip:
                cleaned_lines.append(l_strip)
        return "\n".join(cleaned_lines).strip()
    return text


def calculate_block_end_line(
    source_lines: List[str], start_line: int
) -> int:
    """Accurately calculate the end line of a block by counting braces."""
    if start_line > len(source_lines) or start_line < 1:
        return max(1, start_line)

    brace_depth = 0
    found_brace = False
    in_block_comment = False

    for idx in range(start_line - 1, len(source_lines)):
        line = source_lines[idx]
        i = 0
        while i < len(line):
            if in_block_comment:
                if line[i:i + 2] == "*/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if line[i:i + 2] == "/*":
                in_block_comment = True
                i += 2
                continue
            if line[i:i + 2] == "//":
                break
            if line[i] in ('"', "'"):
                quote = line[i]
                i += 1
                while i < len(line) and line[i] != quote:
                    if line[i] == "\\":
                        i += 1
                    i += 1
                i += 1
                continue
            if line[i] == "{":
                brace_depth += 1
                found_brace = True
            elif line[i] == "}":
                brace_depth -= 1
                if found_brace and brace_depth == 0:
                    return idx + 1
            elif line[i] == ";" and not found_brace and brace_depth == 0:
                return idx + 1
            i += 1

        if not found_brace and idx > start_line + 4:
            return start_line

    return len(source_lines) if found_brace else start_line


def build_fqdn(
    scope_stack: List[str], name: str, separator: str = "."
) -> str:
    """Build a clean FQDN string from a scope stack and symbol name."""
    clean_scopes = [s for s in scope_stack if s]
    if clean_scopes:
        return f"{separator.join(clean_scopes)}{separator}{name}"
    return name


class BaseLanguageAdapter(ABC):
    """Abstract base class for all language-specific AST adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Language adapter identifier name."""
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> Tuple[str, ...]:
        """Tuple of supported file extensions (with leading dot)."""
        ...

    @property
    @abstractmethod
    def default_code_language(self) -> str:
        """Markdown code block language tag (e.g. c, python, java, kotlin)."""
        ...

    def can_handle(self, file_path: Path) -> bool:
        """Check if this adapter can process the given file."""
        return file_path.suffix.lower() in self.supported_extensions

    def get_code_language(self, extension: str) -> str:
        """Get markdown code block language for an extension."""
        return self.default_code_language

    @abstractmethod
    def parse(
        self,
        file_path: Path,
        comp_db: Optional[CompilationDatabase] = None,
        base_dir: Optional[Path] = None,
    ) -> List[Symbol]:
        """Parse source file and extract hierarchical Symbol definitions."""
        ...


class LanguageAdapterRegistry:
    """Registry managing language adapters for unified symbol extraction."""

    def __init__(self):
        self._adapters: List[BaseLanguageAdapter] = []
        self._ext_map: Dict[str, BaseLanguageAdapter] = {}

    def register(self, adapter: BaseLanguageAdapter) -> None:
        """Register a language adapter instance."""
        self._adapters.append(adapter)
        for ext in adapter.supported_extensions:
            self._ext_map[ext.lower()] = adapter

    def get_adapter_for_file(
        self, file_path: Path
    ) -> Optional[BaseLanguageAdapter]:
        """Retrieve adapter responsible for parsing the given file."""
        ext = file_path.suffix.lower()
        if ext in self._ext_map:
            return self._ext_map[ext]
        for adapter in self._adapters:
            if adapter.can_handle(file_path):
                return adapter
        return None

    def get_all_adapters(self) -> List[BaseLanguageAdapter]:
        """Retrieve all registered adapters."""
        return list(self._adapters)

    def get_supported_extensions(self) -> Set[str]:
        """Retrieve set of all supported file extensions."""
        return set(self._ext_map.keys())

    def get_code_language(self, extension: str) -> str:
        """Map file extension to Markdown syntax highlighting language."""
        ext = extension.lower()
        adapter = self._ext_map.get(ext)
        if adapter:
            return adapter.get_code_language(ext)
        return "text"


_default_registry: Optional[LanguageAdapterRegistry] = None


def get_default_registry() -> LanguageAdapterRegistry:
    """Return the global default adapter registry instance."""
    global _default_registry
    if _default_registry is None:
        from pystdoc.adapters.clang_adapter import ClangAdapter
        from pystdoc.adapters.generic_adapter import GenericAdapter
        from pystdoc.adapters.java_adapter import JavaAdapter
        from pystdoc.adapters.kotlin_adapter import KotlinAdapter
        from pystdoc.adapters.python_adapter import PythonAdapter

        reg = LanguageAdapterRegistry()
        reg.register(ClangAdapter())
        reg.register(PythonAdapter())
        reg.register(JavaAdapter())
        reg.register(KotlinAdapter())
        reg.register(GenericAdapter())
        _default_registry = reg
    return _default_registry
