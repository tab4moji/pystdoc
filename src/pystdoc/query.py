"""Query utilities for inspecting .docgen documentation index."""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pystdoc.db import DocgenDB
from pystdoc.symbols import get_kind_prefix


def _get_docgen_dir(target_dir: Path) -> Path:
    """Return .docgen directory path."""
    return target_dir / ".docgen"


def run_list(target_dir: Path) -> int:
    """List all indexed source files from .docgen."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .docgen directory not found in {target_dir}. "
            "Please run 'pystdoc sync' first.",
            file=sys.stderr,
        )
        return 1

    files: List[str] = []
    files_txt = docgen_dir / "files.txt"
    if files_txt.exists():
        try:
            content = files_txt.read_text(encoding="utf-8", errors="replace")
            files = [
                line.strip() for line in content.splitlines() if line.strip()
            ]
        except Exception:
            files = []

    if not files:
        db_path = docgen_dir / "index.db"
        if db_path.exists():
            try:
                with DocgenDB(db_path) as db:
                    files = db.get_all_files()
            except Exception:
                files = []

    if not files:
        docs_dir = docgen_dir / "documents"
        if docs_dir.exists():
            for p in sorted(docs_dir.glob("*.md")):
                if not any(
                    p.name.endswith(f".{k}.md")
                    for k in ("fn", "var", "type", "const", "sym")
                ):
                    files.append(p.stem)

    if not files:
        print("No source files found in .docgen.")
        return 0

    for f in sorted(list(dict.fromkeys(files))):
        print(f)
    return 0


def run_functions(target_dir: Path) -> int:
    """List all indexed functions and methods from .docgen."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .docgen directory not found in {target_dir}. "
            "Please run 'pystdoc sync' first.",
            file=sys.stderr,
        )
        return 1

    symbols: List[Dict[str, Any]] = []
    db_path = docgen_dir / "index.db"
    if db_path.exists():
        try:
            with DocgenDB(db_path) as db:
                all_syms = db.get_all_symbols_metadata()
                for s in all_syms:
                    k = s.get("kind", "").lower()
                    if (
                        get_kind_prefix(k) == "fn"
                        or "func" in k
                        or "method" in k
                        or "constructor" in k
                        or "destructor" in k
                    ):
                        symbols.append(s)
        except Exception:
            symbols = []

    if not symbols:
        # Fallback to scanning documents directory
        docs_dir = docgen_dir / "documents"
        if docs_dir.exists():
            for p in sorted(docs_dir.glob("*.fn.*.md")):
                name = p.stem.split(".fn.", 1)[-1]
                symbols.append({"name": name, "fqdn": name, "rel_path": ""})

    if not symbols:
        print("No functions found in .docgen.")
        return 0

    for s in symbols:
        display = s.get("fqdn") or s.get("name", "")
        rel_path = s.get("rel_path", "")
        line_start = s.get("line_start")
        line_end = s.get("line_end")
        if rel_path and line_start is not None and line_end is not None:
            print(f"{display} ({rel_path}:{line_start}:{line_end})")
        elif rel_path and line_start is not None:
            print(f"{display} ({rel_path}:{line_start}:{line_start})")
        elif rel_path:
            print(f"{display} ({rel_path})")
        else:
            print(display)
    return 0


def run_variables(target_dir: Path) -> int:
    """List all indexed variables and constants from .docgen."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .docgen directory not found in {target_dir}. "
            "Please run 'pystdoc sync' first.",
            file=sys.stderr,
        )
        return 1

    symbols: List[Dict[str, Any]] = []
    db_path = docgen_dir / "index.db"
    if db_path.exists():
        try:
            with DocgenDB(db_path) as db:
                all_syms = db.get_all_symbols_metadata()
                for s in all_syms:
                    k = s.get("kind", "").lower()
                    if (
                        get_kind_prefix(k) in ("var", "const")
                        or k in (
                            "variable",
                            "var",
                            "const",
                            "constant",
                            "enum_constant",
                            "field",
                            "member",
                            "macro",
                        )
                    ):
                        symbols.append(s)
        except Exception:
            symbols = []

    if not symbols:
        # Fallback to scanning documents directory
        docs_dir = docgen_dir / "documents"
        if docs_dir.exists():
            for p in sorted(docs_dir.glob("*.var.*.md")) + sorted(
                docs_dir.glob("*.const.*.md")
            ):
                tag = ".var." if ".var." in p.name else ".const."
                name = p.stem.split(tag, 1)[-1]
                symbols.append({"name": name, "fqdn": name, "rel_path": ""})

    if not symbols:
        print("No variables or constants found in .docgen.")
        return 0

    for s in symbols:
        display = s.get("fqdn") or s.get("name", "")
        rel_path = s.get("rel_path", "")
        line_start = s.get("line_start")
        line_end = s.get("line_end")
        if rel_path and line_start is not None and line_end is not None:
            print(f"{display} ({rel_path}:{line_start}:{line_end})")
        elif rel_path and line_start is not None:
            print(f"{display} ({rel_path}:{line_start}:{line_start})")
        elif rel_path:
            print(f"{display} ({rel_path})")
        else:
            print(display)
    return 0


def _find_markdown_doc(
    docs_dir: Path, rel_path: str, sym_name: str, fqdn: str, kind: str
) -> Optional[str]:
    """Find and read markdown documentation file for a symbol."""
    if not docs_dir.exists():
        return None

    k_prefix = get_kind_prefix(kind)

    # 1. Direct candidate paths
    if rel_path:
        exact_file = docs_dir / f"{rel_path}.{k_prefix}.{sym_name}.md"
        if exact_file.exists():
            return exact_file.read_text(encoding="utf-8", errors="replace")

        if fqdn:
            # Try with full or partial FQDN
            fqdn_file = docs_dir / f"{rel_path}.{k_prefix}.{fqdn}.md"
            if fqdn_file.exists():
                return fqdn_file.read_text(encoding="utf-8", errors="replace")

            # Try nested name inside class (e.g., LogMessageData.logMessage)
            if "." in fqdn:
                tail_parts = ".".join(fqdn.split(".")[1:])
                tail_file = docs_dir / f"{rel_path}.{k_prefix}.{tail_parts}.md"
                if tail_file.exists():
                    return tail_file.read_text(
                        encoding="utf-8", errors="replace"
                    )

    # 2. Search patterns in docs_dir
    candidates = list(docs_dir.glob(f"*.{k_prefix}.*{sym_name}.md"))
    if not candidates:
        candidates = list(docs_dir.glob(f"*{sym_name}.md"))
    if not candidates and fqdn:
        candidates = list(docs_dir.glob(f"*{fqdn}*.md"))
    if not candidates:
        candidates = list(docs_dir.glob(f"*{sym_name}*"))

    for c in candidates:
        if c.is_file() and c.suffix == ".md":
            return c.read_text(encoding="utf-8", errors="replace")
    return None


def run_description(target_dir: Path, query: str) -> int:
    """Show symbol description, source location, and detailed markdown doc."""
    clean_query = query.strip()
    if not clean_query:
        print("Error: Please specify a symbol name or FQDN.", file=sys.stderr)
        return 1

    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .docgen directory not found in {target_dir}. "
            "Please run 'pystdoc sync' first.",
            file=sys.stderr,
        )
        return 1

    symbols: List[Dict[str, Any]] = []
    db_path = docgen_dir / "index.db"
    symbol_cache_map: Dict[str, Dict[str, Any]] = {}

    if db_path.exists():
        try:
            with DocgenDB(db_path) as db:
                symbols = db.find_symbols_by_query(clean_query)
                for s in symbols:
                    uid = s.get("unique_id")
                    if uid:
                        c = db.load_symbol_cache(uid)
                        if c:
                            symbol_cache_map[uid] = c
        except Exception:
            symbols = []

    docs_dir = docgen_dir / "documents"

    # Fallback to search markdown docs if no DB or DB found nothing
    if not symbols and docs_dir.exists():
        dot_q = clean_query.replace("::", ".")
        for p in docs_dir.glob("*.md"):
            if dot_q in p.name or clean_query in p.name:
                symbols.append(
                    {
                        "name": p.stem,
                        "fqdn": p.stem,
                        "kind": "symbol",
                        "rel_path": "",
                        "line_start": None,
                        "line_end": None,
                        "signature": "",
                    }
                )

    if not symbols:
        print(
            f"Error: Symbol '{clean_query}' not found in .docgen.",
            file=sys.stderr,
        )
        return 1

    for idx, sym in enumerate(symbols):
        if idx > 0:
            print("\n" + "-" * 64 + "\n")

        name = sym.get("name", "")
        fqdn = sym.get("fqdn") or name
        kind = sym.get("kind", "symbol")
        rel_path = sym.get("rel_path", "")
        line_start = sym.get("line_start")
        line_end = sym.get("line_end")
        signature = sym.get("signature", "")
        unique_id = sym.get("unique_id", "")

        loc_str = rel_path or "Unknown"
        if line_start is not None and line_end is not None:
            loc_str = f"{loc_str} (Lines: {line_start}-{line_end})"
        elif line_start is not None:
            loc_str = f"{loc_str} (Line: {line_start})"

        print("=" * 64)
        print(f"Symbol: {fqdn}")
        print(f"Source: {loc_str}")
        print(f"Kind:   {kind}")
        if signature:
            print(f"Signature: {signature}")
        print("=" * 64)
        print()

        # Try to read Markdown doc
        md_content = _find_markdown_doc(docs_dir, rel_path, name, fqdn, kind)
        if md_content:
            print(md_content.strip())
        else:
            cache_info = symbol_cache_map.get(unique_id, {})
            purpose = cache_info.get("purpose", "")
            overview = cache_info.get("overview", "")
            top_down = cache_info.get("top_down_context", "")

            if not purpose and top_down:
                purpose = top_down

            if purpose or overview:
                if purpose:
                    print(f"## Purpose\n{purpose}\n")
                if overview:
                    print(f"## Overview\n{overview}\n")
            else:
                print(f"No detailed markdown document found for `{fqdn}`.")

    return 0
