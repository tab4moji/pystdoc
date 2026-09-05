"""Java AST parser interface delegating to JavaAdapter."""

from pathlib import Path
from typing import List, Optional

from pystdoc.adapters.java_adapter import JavaAdapter
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Symbol

_java_adapter = JavaAdapter()


def parse_java_file(
    file_path: Path,
    comp_db: Optional[CompilationDatabase] = None,
    base_dir: Optional[Path] = None,
) -> List[Symbol]:
    """Parse Java source file and extract full symbol definitions."""
    return _java_adapter.parse(file_path, comp_db=comp_db, base_dir=base_dir)
