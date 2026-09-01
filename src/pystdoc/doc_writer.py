"""Markdown doc generator for symbols with layout & language support."""

from pathlib import Path
from typing import List, Optional

from pystdoc.cache import write_flushed_text
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.parser_clang import parse_clang_file
from pystdoc.parser_generic import parse_generic_file
from pystdoc.parser_python import parse_python_file
from pystdoc.symbols import Symbol, get_kind_prefix


def normalize_language(lang: Optional[str]) -> str:
    """Normalize language string into standard representation."""
    if not lang:
        return "English"
    l_lower = lang.strip().lower()
    if l_lower in ("japanese", "ja", "jp", "日本語"):
        return "Japanese"
    elif l_lower in ("english", "en"):
        return "English"
    elif l_lower in ("chinese", "zh"):
        return "Chinese"
    elif l_lower in ("spanish", "es"):
        return "Spanish"
    return lang.strip().capitalize()


def get_code_language(extension: str) -> str:
    """Map file extension to Markdown code block language identifier."""
    ext = extension.lower()
    if ext in (".c", ".h"):
        return "c"
    elif ext in (".cpp", ".hpp", ".cc", ".cxx", ".hh"):
        return "cpp"
    elif ext == ".py":
        return "python"
    elif ext in (".sh", ".bash"):
        return "bash"
    elif ext == ".rs":
        return "rust"
    return "text"


def get_code_snippet(file_path: Path, line_start: int, line_end: int) -> str:
    """Extract code lines between line_start and line_end."""
    try:
        lines = file_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        start = max(0, line_start - 1)
        end = min(len(lines), line_end)
        return "\n".join(lines[start:end])
    except Exception:
        return ""


def extract_symbols(
    file_path: Path,
    comp_db: Optional[CompilationDatabase] = None,
) -> List[Symbol]:
    """Parse file based on extension and return list of Symbol objects."""
    ext = file_path.suffix.lower()
    if ext in (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh"):
        return parse_clang_file(file_path, comp_db=comp_db)
    elif ext == ".py":
        return parse_python_file(file_path)
    elif ext in (".sh", ".bash"):
        return parse_generic_file(file_path)
    return []


def format_symbol_section(
    sym: Symbol,
    file_path: Path,
    level: int = 2,
    language: str = "English",
) -> str:
    """Format symbol doc with Top-Down first, followed by Bottom-Up."""
    norm_lang = normalize_language(language)
    is_ja = norm_lang == "Japanese"

    h_prefix = "#" * level
    kind_display = sym.kind
    if sym.fqdn:
        kind_display = f"{sym.kind} (FQDN: `{sym.fqdn}`)"

    snippet = get_code_snippet(file_path, sym.line_start, sym.line_end)
    lang_id = get_code_language(file_path.suffix)

    kind_lower = sym.kind.lower()
    if "var" in kind_lower:
        default_purpose = (
            f"`{sym.name}` の状態データを保持する。"
            if is_ja
            else f"Holds state data for `{sym.name}`."
        )
        data_flow_desc = (
            "参照元関数から読み書きされ、状態を伝達します。"
            if is_ja
            else "It is read and written by referencing functions "
            "to share state."
        )
    elif "enum" in kind_lower or "const" in kind_lower:
        default_purpose = (
            f"`{sym.name}` の識別定数値を定義する。"
            if is_ja
            else f"Defines constant identifier `{sym.name}`."
        )
        data_flow_desc = (
            "条件判定やステータスコードとして参照されます。"
            if is_ja
            else "It is referenced in conditional logic and "
            "status checks."
        )
    elif (
        "struct" in kind_lower
        or "class" in kind_lower
        or "type" in kind_lower
    ):
        default_purpose = (
            f"`{sym.name}` のデータ構造／モデルを定義する。"
            if is_ja
            else f"Defines data model for `{sym.name}`."
        )
        data_flow_desc = (
            "関数の引数・戻り値やメンバアクセスでデータを受け渡します。"
            if is_ja
            else "It is passed via function arguments, returns, "
            "or member access."
        )
    else:
        default_purpose = (
            f"`{sym.name}` の処理を実行する。"
            if is_ja
            else f"Executes `{sym.name}` operations."
        )
        data_flow_desc = (
            "入力パラメータを受け取り、処理結果を返します。"
            if is_ja
            else "It accepts parameters and returns computed results."
        )

    role_desc = sym.top_down_context or sym.purpose or default_purpose

    # Build pure prose description (Top-Down context + Bottom-Up overview)
    prose_sentences = [role_desc.rstrip("。.") + ("。" if is_ja else ".")]

    if sym.referencing_functions:
        callers_str = (
            "、".join(sym.referencing_functions)
            if is_ja
            else ", ".join(sym.referencing_functions)
        )
        if is_ja:
            prose_sentences.append(
                f"上位モジュールからは、{callers_str} などの目的で利用・参照されます。"
            )
        else:
            prose_sentences.append(
                f"In the system architecture, it is referenced by "
                f"{callers_str}."
            )
    elif sym.name in ("main", "app", "cli", "run"):
        if is_ja:
            prose_sentences.append(
                "プログラムの最上位エントリーポイント（起動・全体統括）として"
                "位置付けられています。"
            )
        else:
            prose_sentences.append(
                "It serves as the root entry point (system bootstrap and "
                "dispatcher)."
            )

    prose_sentences.append(
        data_flow_desc.rstrip("。.") + ("。" if is_ja else ".")
    )

    if (
        sym.overview
        and sym.overview != sym.purpose
        and sym.overview != role_desc
    ):
        if is_ja:
            prose_sentences.append(f"実装面では、{sym.overview}")
        else:
            prose_sentences.append(
                f"Implementation overview: {sym.overview}"
            )

    prose_paragraph = " ".join(prose_sentences)

    lines = [
        f"{h_prefix} {sym.kind.capitalize()} Documentation: `{sym.name}`",
        "",
        prose_paragraph,
        "",
        "## 1. Basic Information",
        f"- **Name**: `{sym.name}`",
        f"- **FQDN**: `{sym.fqdn or sym.name}`",
        f"- **Symbol Kind**: `{kind_display}`",
        f"- **Location**: Line {sym.line_start} to Line {sym.line_end}",
    ]
    if sym.signature:
        lines.append(f"- **Signature / Type**: `{sym.signature}`")

    if sym.parameters:
        lines.extend(["", "## 2. Parameters"])
        for p in sym.parameters:
            p_type = f": `{p.type_hint}`" if p.type_hint else ""
            lines.append(f"- `{p.name}`{p_type}")
    else:
        lines.extend(["", "## 2. Parameters", "- None"])

    if sym.return_type or sym.outputs_note or sym.inputs_note:
        lines.extend(["", "## 3. Input / Return Specifications"])
        if sym.inputs_note:
            lines.append(f"- Input Constraints: {sym.inputs_note}")
        lines.append(f"- Return Type: `{sym.return_type or 'void / None'}`")
        if sym.outputs_note:
            lines.append(f"- Return Value & Side Effects: {sym.outputs_note}")

    if sym.callees:
        lines.extend(["", "## 4. Called Functions"])
        for c in sym.callees:
            lines.append(f"- `{c}`")
    elif sym.referencing_functions:
        lines.extend(["", "## 4. Referencing Functions"])
        for r in sym.referencing_functions:
            lines.append(f"- {r}")

    if snippet:
        lines.extend(
            [
                "",
                "## Source Code Snippet",
                f"```{lang_id}",
                snippet,
                "```",
            ]
        )

    if sym.children:
        lines.append("")
        for child in sym.children:
            lines.append(
                format_symbol_section(
                    child, file_path, level=level + 1, language=norm_lang
                )
            )

    return "\n".join(lines)


def write_single_symbol_doc(
    target_dir: Path,
    rel_path: Path,
    symbol: Symbol,
    prefix_name: str = "",
    language: str = "English",
) -> Path:
    """Write an individual symbol document with immediate flush."""
    norm_lang = normalize_language(language)
    docgen_dir = target_dir / ".docgen" / "documents"
    docgen_dir.mkdir(parents=True, exist_ok=True)

    k_prefix = get_kind_prefix(symbol.kind)
    sym_id = f"{prefix_name}{symbol.name}" if prefix_name else symbol.name
    out_file = docgen_dir / f"{rel_path.as_posix()}.{k_prefix}.{sym_id}.md"

    full_path = target_dir / rel_path
    content = format_symbol_section(
        symbol, full_path, level=1, language=norm_lang
    )

    write_flushed_text(out_file, content + "\n")
    return out_file


def write_individual_symbol_docs(
    target_dir: Path,
    rel_path: Path,
    symbols: List[Symbol],
    prefix_name: str = "",
    language: str = "English",
) -> List[Path]:
    """Recursively write docs for each symbol with immediate flush."""
    norm_lang = normalize_language(language)
    created_files: List[Path] = []

    for sym in symbols:
        out_file = write_single_symbol_doc(
            target_dir,
            rel_path,
            sym,
            prefix_name=prefix_name,
            language=norm_lang,
        )
        created_files.append(out_file)

        if sym.children:
            child_prefix = (
                f"{prefix_name}{sym.name}." if prefix_name else f"{sym.name}."
            )
            child_files = write_individual_symbol_docs(
                target_dir,
                rel_path,
                sym.children,
                prefix_name=child_prefix,
                language=norm_lang,
            )
            created_files.extend(child_files)

    return created_files


def write_symbol_doc(
    target_dir: Path,
    rel_path: Path,
    file_hash: str,
    symbols: List[Symbol],
    language: str = "English",
) -> Path:
    """Write comprehensive file documentation with immediate flush."""
    norm_lang = normalize_language(language)
    docgen_dir = target_dir / ".docgen" / "documents"
    docgen_dir.mkdir(parents=True, exist_ok=True)

    out_file = docgen_dir / f"{rel_path.as_posix()}.md"
    full_path = target_dir / rel_path

    lines = [
        f"# File Documentation: `{rel_path.as_posix()}`",
        "",
        f"- **File SHA-256**: `{file_hash}`",
        f"- **Detected Symbols**: {len(symbols)}",
        "",
        "## Symbol List",
    ]

    for sym in symbols:
        line_range = f"{sym.line_start}-{sym.line_end}"
        lines.append(
            f"- `{sym.name}` ({sym.kind}) [Lines: {line_range}]"
        )

    lines.append("")
    for sym in symbols:
        lines.append(
            format_symbol_section(sym, full_path, level=2, language=norm_lang)
        )
        lines.append("")

    write_flushed_text(out_file, "\n".join(lines).strip() + "\n")
    return out_file
