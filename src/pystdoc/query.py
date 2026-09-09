"""Query utilities for inspecting .pystdoc documentation index."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pystdoc.db import DocgenDB
from pystdoc.symbols import get_kind_prefix


def _get_docgen_dir(target_dir: Path) -> Path:
    """Return .pystdoc directory path."""
    return target_dir / ".pystdoc"


def run_list(target_dir: Path) -> int:
    """List all indexed source files from .pystdoc."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .pystdoc directory not found in {target_dir}. "
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
        print("No source files found in .pystdoc.")
        return 0

    for f in sorted(list(dict.fromkeys(files))):
        print(f)
    return 0


def run_functions(target_dir: Path) -> int:
    """List all indexed functions and methods from .pystdoc."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .pystdoc directory not found in {target_dir}. "
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
        print("No functions found in .pystdoc.")
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
    """List all indexed variables and constants from .pystdoc."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .pystdoc directory not found in {target_dir}. "
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
        print("No variables or constants found in .pystdoc.")
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


def run_types(target_dir: Path) -> int:
    """List all indexed types, classes, structs, enums from .pystdoc."""
    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        print(
            f"Error: .pystdoc directory not found in {target_dir}. "
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
                        get_kind_prefix(k) == "type"
                        or k in (
                            "struct",
                            "class",
                            "enum",
                            "interface",
                            "typedef",
                            "union",
                            "type",
                            "data class",
                            "object",
                            "companion object",
                            "annotation",
                        )
                    ):
                        symbols.append(s)
        except Exception:
            symbols = []

    if not symbols:
        # Fallback to scanning documents directory
        docs_dir = docgen_dir / "documents"
        if docs_dir.exists():
            for p in sorted(docs_dir.glob("*.type.*.md")):
                name = p.stem.split(".type.", 1)[-1]
                symbols.append({"name": name, "fqdn": name, "rel_path": ""})

    if not symbols:
        print("No types or classes found in .pystdoc.")
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
            f"Error: .pystdoc directory not found in {target_dir}. "
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
            f"Error: Symbol '{clean_query}' not found in .pystdoc.",
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


def locate_features(target_dir: Path, query: str, limit: int = 10) -> str:
    """Find exact files, functions, UI components, or line ranges."""
    clean_query = query.strip()
    if not clean_query:
        return "Error: Please provide a feature description or search query."

    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        return (
            f"Error: .pystdoc directory not found in {target_dir}. "
            "Please run pystdoc_sync first."
        )

    db_path = docgen_dir / "index.db"
    if not db_path.exists():
        return "Error: index database (.pystdoc/index.db) not found."

    import re
    words = set(
        re.findall(
            r"[\w\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+",
            clean_query.lower(),
        )
    )
    raw_q = clean_query.lower()

    db = DocgenDB(db_path)
    scored_results: List[Any] = []
    try:
        cur = db.conn.cursor()
        cur.execute(
            "SELECT m.unique_id, m.name, m.kind, m.rel_path, "
            "m.line_start, m.line_end, m.fqdn, m.signature, "
            "m.referencing_funcs_json, m.callees_json, "
            "c.purpose, c.overview "
            "FROM symbols_metadata m "
            "LEFT JOIN symbol_cache c ON m.unique_id = c.unique_id"
        )
        rows = cur.fetchall()

        for row in rows:
            (
                uid, sname, skind, rpath,
                lstart, lend, fqdn, sig,
                ref_funcs_raw, callees_raw,
                purp, ovw
            ) = row
            sname_l = (sname or "").lower()
            fqdn_l = (fqdn or "").lower()
            rpath_l = (rpath or "").lower()
            sig_l = (sig or "").lower()
            purp_l = (purp or "").lower()
            ovw_l = (ovw or "").lower()
            skind_l = (skind or "").lower()

            score = 0.0
            # 1. Exact / Substring query matches
            if raw_q in sname_l or raw_q in fqdn_l:
                score += 50.0
            if raw_q in purp_l:
                score += 35.0
            if raw_q in ovw_l:
                score += 20.0
            if raw_q in sig_l:
                score += 25.0

            # 2. Token matches
            for w in words:
                if len(w) < 2 and not any(
                    '\u3040' <= c <= '\u9fff' for c in w
                ):
                    continue
                if w in sname_l:
                    score += 15.0
                if w in fqdn_l:
                    score += 10.0
                if w in purp_l:
                    score += 10.0
                if w in ovw_l:
                    score += 5.0
                if w in rpath_l:
                    score += 8.0
                if w in sig_l:
                    score += 6.0

            # 3. Boost UI elements if query mentions button/ui/view/screen/etc.
            ui_keywords = (
                "button", "ui", "screen", "view", "dialog", "click", "tap",
                "画面", "ボタン", "表示", "削除", "デバッグ", "debug", "test"
            )
            is_ui_query = any(k in raw_q for k in ui_keywords)
            if is_ui_query:
                if any(
                    k in sname_l or k in fqdn_l or k in skind_l
                    for k in (
                        "button", "view", "compose", "screen", "dialog",
                        "activity", "fragment", "ui"
                    )
                ):
                    score += 15.0
                if any(
                    k in sig_l
                    for k in (
                        "composable", "button", "onclick", "modifier",
                        "setonclicklistener"
                    )
                ):
                    score += 20.0

            if score > 0.0:
                sym_data = {
                    "unique_id": uid,
                    "name": sname,
                    "kind": skind,
                    "rel_path": rpath,
                    "line_start": lstart,
                    "line_end": lend,
                    "fqdn": fqdn,
                    "signature": sig,
                    "purpose": purp,
                    "overview": ovw,
                }
                scored_results.append((score, sym_data, purp or ovw or ""))

        # Check module design docs for additional context
        design_modules_dir = docgen_dir / "design" / "modules"
        module_matches: List[str] = []
        if design_modules_dir.exists():
            for mod_file in sorted(design_modules_dir.glob("*.md")):
                try:
                    mod_text = mod_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    mod_text_l = mod_text.lower()
                    if raw_q in mod_text_l or any(
                        w in mod_text_l for w in words if len(w) >= 3
                    ):
                        module_matches.append(mod_file.stem)
                except Exception:
                    pass

        if not scored_results:
            mod_hint = (
                f" Related design modules: {', '.join(module_matches)}."
                if module_matches
                else ""
            )
            return (
                f"No specific symbols found matching '{query}'.{mod_hint} "
                "Try searching with symbol names via `pystdoc_search_symbols`."
            )

        # Sort descending by score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        top_results = scored_results[:limit]

        output_lines = [
            f"### Implementation / Feature Locations for '{query}':",
            f"Found {len(scored_results)} candidate location(s) "
            f"(showing top {len(top_results)}):\n",
        ]

        for rank, (_, sym, desc) in enumerate(top_results, 1):
            disp_name = sym.get("fqdn") or sym.get("name")
            rpath = sym.get("rel_path") or "Unknown"
            lstart = sym.get("line_start")
            lend = sym.get("line_end")
            kind = sym.get("kind", "symbol")

            loc_str = f"`{rpath}`"
            if lstart is not None and lend is not None:
                loc_str += f" (Lines {lstart}-{lend})"
            elif lstart is not None:
                loc_str += f" (Line {lstart})"

            desc_str = f" - **Purpose**: {desc}" if desc else ""
            sig = sym.get("signature")
            sig_str = f"\n   - **Signature**: `{sig}`" if sig else ""

            output_lines.append(
                f"{rank}. **{loc_str}**\n"
                f"   - **Symbol**: `{disp_name}` (`{kind}`){desc_str}{sig_str}"
            )

        if module_matches:
            output_lines.append(
                f"\n- **Relevant Architecture Module(s)**: "
                f"{', '.join(module_matches)}"
            )

        return "\n".join(output_lines)
    finally:
        db.close()


def trace_impact(target_dir: Path, symbol_query: str) -> str:
    """Trace inbound callers and outbound dependencies for impact analysis."""
    clean_sym = symbol_query.strip()
    if not clean_sym:
        return "Error: Please specify a symbol name or FQDN to trace."

    docgen_dir = _get_docgen_dir(target_dir)
    if not docgen_dir.exists():
        return (
            f"Error: .pystdoc directory not found in {target_dir}. "
            "Please run pystdoc_sync first."
        )

    db_path = docgen_dir / "index.db"
    if not db_path.exists():
        return "Error: index database (.pystdoc/index.db) not found."

    db = DocgenDB(db_path)
    try:
        symbols = db.find_symbols_by_query(clean_sym)
        if not symbols:
            return f"Symbol '{clean_sym}' not found in index database."

        sym = symbols[0]
        uid = sym.get("unique_id", "")
        sname = sym.get("name", "")
        fqdn = sym.get("fqdn") or sname
        kind = sym.get("kind", "symbol")
        rpath = sym.get("rel_path", "")
        lstart = sym.get("line_start")
        lend = sym.get("line_end")

        loc_str = f"`{rpath}`"
        if lstart is not None and lend is not None:
            loc_str += f" (Lines {lstart}-{lend})"
        elif lstart is not None:
            loc_str += f" (Line {lstart})"

        cache = db.load_symbol_cache(uid) if uid else {}
        purpose = cache.get("purpose", "") if cache else ""

        ref_funcs_raw = sym.get("referencing_funcs_json")
        callees_raw = sym.get("callees_json")
        callers: List[str] = []
        if ref_funcs_raw:
            try:
                callers = json.loads(ref_funcs_raw)
            except Exception:
                pass
        callees: List[str] = []
        if callees_raw:
            try:
                callees = json.loads(callees_raw)
            except Exception:
                pass

        lines = [
            f"### Impact & Dependency Analysis for `{fqdn}`:",
            f"- **Kind**: `{kind}`",
            f"- **Location**: {loc_str}",
        ]
        if purpose:
            lines.append(f"- **Purpose**: {purpose}")

        lines.append(
            "\n#### 🔼 Inbound Callers / References (Where this is used):"
        )
        if callers:
            for c in callers:
                lines.append(f"- `{c}`")
        else:
            lines.append(
                "- *No direct internal callers detected "
                "(entry point, top-level, or uncalled).*"
            )

        lines.append(
            "\n#### 🔽 Outbound Dependencies (What this calls/uses):"
        )
        if callees:
            for c in callees:
                lines.append(f"- `{c}`")
        else:
            lines.append("- *No outbound symbol dependencies.*")

        return "\n".join(lines)
    finally:
        db.close()


def run_locate(target_dir: Path, query: str) -> int:
    """CLI handler for locate command."""
    res = locate_features(target_dir, query)
    print(res)
    return 0


def run_impact(target_dir: Path, symbol: str) -> int:
    """CLI handler for impact command."""
    res = trace_impact(target_dir, symbol)
    print(res)
    return 0
