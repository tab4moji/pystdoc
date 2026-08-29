"""Generic parser for shell scripts and other simple file formats using regex."""

import re
from pathlib import Path
from typing import List

from pystdoc.symbols import Symbol


def parse_generic_file(file_path: Path) -> List[Symbol]:
    """Extract functions and variable assignments from Shell or generic scripts."""
    symbols: List[Symbol] = []
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    func_pattern = re.compile(r"^(?:function\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(\)\s*\{?")
    file_prefix = file_path.name

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue

        m_func = func_pattern.match(stripped)
        if m_func:
            fn_name = m_func.group(1)
            fqdn = f"{file_prefix}::{fn_name}"
            sym = Symbol(
                name=fn_name,
                kind="function",
                line_start=idx,
                line_end=idx,
                fqdn=fqdn,
                signature=f"{fn_name}()",
                doc="Shell script function definition.",
            )
            symbols.append(sym)

    return symbols
