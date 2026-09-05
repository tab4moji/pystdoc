"""Kotlin AST parser interface delegating to KotlinAdapter."""

from pathlib import Path
from typing import List, Optional

from pystdoc.adapters.kotlin_adapter import KotlinAdapter
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Symbol

_kotlin_adapter = KotlinAdapter()


def parse_kotlin_file(
    file_path: Path,
    comp_db: Optional[CompilationDatabase] = None,
    base_dir: Optional[Path] = None,
) -> List[Symbol]:
    """Parse Kotlin source file and extract full symbol definitions."""
    return _kotlin_adapter.parse(file_path, comp_db=comp_db, base_dir=base_dir)
