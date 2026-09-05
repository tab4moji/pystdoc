"""Generic language adapter for Shell scripts and other formats."""

from pathlib import Path
from typing import List, Optional, Tuple

from pystdoc.adapters.base import BaseLanguageAdapter
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Symbol


class GenericAdapter(BaseLanguageAdapter):
    """Adapter for generic/shell/rust files using regex and heuristics."""

    @property
    def name(self) -> str:
        return "generic"

    @property
    def supported_extensions(self) -> Tuple[str, ...]:
        return (".sh", ".bash", ".rs")

    @property
    def default_code_language(self) -> str:
        return "bash"

    def get_code_language(self, extension: str) -> str:
        ext = extension.lower()
        if ext in (".sh", ".bash"):
            return "bash"
        elif ext == ".rs":
            return "rust"
        return "text"

    def parse(
        self,
        file_path: Path,
        comp_db: Optional[CompilationDatabase] = None,
        base_dir: Optional[Path] = None,
    ) -> List[Symbol]:
        from pystdoc.parser_generic import parse_generic_file
        return parse_generic_file(file_path)
