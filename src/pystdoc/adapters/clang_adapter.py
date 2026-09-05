"""Clang language adapter for C/C++ source and header files."""

from pathlib import Path
from typing import List, Optional, Tuple

from pystdoc.adapters.base import BaseLanguageAdapter
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Symbol


class ClangAdapter(BaseLanguageAdapter):
    """Adapter for C/C++ files using libclang."""

    @property
    def name(self) -> str:
        return "clang"

    @property
    def supported_extensions(self) -> Tuple[str, ...]:
        return (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh")

    @property
    def default_code_language(self) -> str:
        return "c"

    def get_code_language(self, extension: str) -> str:
        ext = extension.lower()
        if ext in (".c", ".h"):
            return "c"
        return "cpp"

    def parse(
        self,
        file_path: Path,
        comp_db: Optional[CompilationDatabase] = None,
        base_dir: Optional[Path] = None,
    ) -> List[Symbol]:
        from pystdoc.parser_clang import parse_clang_file
        return parse_clang_file(file_path, comp_db=comp_db)
