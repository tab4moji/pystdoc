"""Python language adapter using standard AST module."""

from pathlib import Path
from typing import List, Optional, Tuple

from pystdoc.adapters.base import BaseLanguageAdapter
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Symbol


class PythonAdapter(BaseLanguageAdapter):
    """Adapter for Python source files using AST."""

    @property
    def name(self) -> str:
        return "python"

    @property
    def supported_extensions(self) -> Tuple[str, ...]:
        return (".py",)

    @property
    def default_code_language(self) -> str:
        return "python"

    def parse(
        self,
        file_path: Path,
        comp_db: Optional[CompilationDatabase] = None,
        base_dir: Optional[Path] = None,
    ) -> List[Symbol]:
        from pystdoc.parser_python import parse_python_file
        return parse_python_file(file_path, base_dir=base_dir)
