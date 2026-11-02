"""Markdown doc generator for symbols with layout & language support."""

from pathlib import Path
from typing import Dict, List, Optional

from pystdoc.adapters import get_default_registry
from pystdoc.cache import write_flushed_text
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.doc_labels import get_default_labels, get_or_init_document_labels
from pystdoc.parser_clang import parse_clang_file
from pystdoc.parser_generic import parse_generic_file
from pystdoc.parser_java import parse_java_file
from pystdoc.parser_kotlin import parse_kotlin_file
from pystdoc.parser_python import parse_python_file
from pystdoc.symbols import Symbol, get_kind_prefix

__all__ = [
    "normalize_language",
    "get_code_language",
    "get_code_snippet",
    "extract_symbols",
    "format_symbol_section",
    "write_single_symbol_doc",
    "write_individual_symbol_docs",
    "write_symbol_doc",
    "parse_clang_file",
    "parse_generic_file",
    "parse_java_file",
    "parse_kotlin_file",
    "parse_python_file",
]


def normalize_language(lang: Optional[str]) -> str:
    """Normalize language string into standard representation."""
    if not lang:
        return "English"
    l_strip = lang.strip()
    if not l_strip:
        return "English"
    l_lower = l_strip.lower()
    if l_lower in ("c", "posix", "c.utf-8", "c.utf8"):
        return "English"
    if l_lower in ("japanese", "ja", "jp", "日本語"):
        return "Japanese"
    elif l_lower in ("english", "en"):
        return "English"
    elif l_lower in ("chinese", "zh"):
        return "Chinese"
    elif l_lower in ("spanish", "es"):
        return "Spanish"
    elif l_lower in ("french", "fr"):
        return "French"
    elif l_lower in ("german", "de"):
        return "German"
    elif l_lower in ("korean", "ko"):
        return "Korean"

    first_part = l_lower.split(":")[0].strip()
    lang_tag = first_part.split(".")[0].split("@")[0].strip()
    primary = lang_tag.split("_")[0].split("-")[0]
    from pystdoc.config import LANGUAGE_CODE_MAP

    if primary in LANGUAGE_CODE_MAP:
        return LANGUAGE_CODE_MAP[primary]
    return l_strip.capitalize()


def get_code_language(extension: str) -> str:
    """Map file extension to Markdown code block language identifier."""
    return get_default_registry().get_code_language(extension)


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
    adapter = get_default_registry().get_adapter_for_file(file_path)
    if adapter:
        return adapter.parse(file_path, comp_db=comp_db)
    return []


def format_symbol_section(
    sym: Symbol,
    file_path: Path,
    level: int = 2,
    language: str = "English",
    labels: Optional[Dict[str, str]] = None,
) -> str:
    """Format symbol doc with Top-Down first, followed by Bottom-Up."""
    norm_lang = normalize_language(language)
    if labels is None:
        labels = get_default_labels(norm_lang)
    is_ja = norm_lang == "Japanese"

    h_prefix = "#" * level
    kind_lower = sym.kind.lower()
    kind_key = f"kind_{kind_lower}"
    kind_display_name = labels.get(kind_key, sym.kind.capitalize())
    kind_display = kind_display_name
    if sym.fqdn:
        kind_display = f"{kind_display_name} (FQDN: `{sym.fqdn}`)"

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
        tmpl_ref = labels.get("prose_referenced_by_template")
        eng_ref = "In the system architecture, it is referenced by {callers}."
        if not tmpl_ref or (is_ja and tmpl_ref == eng_ref):
            tmpl_ref = (
                "上位モジュールからは、{callers} などの目的で利用・参照されます。"
                if is_ja
                else eng_ref
            )
        prose_sentences.append(tmpl_ref.format(callers=callers_str))
    elif sym.name in ("main", "app", "cli", "run"):
        prose_root = labels.get("prose_root_entry_point")
        eng_root = (
            "It serves as the root entry point (system bootstrap and "
            "dispatcher)."
        )
        if not prose_root or (is_ja and prose_root == eng_root):
            prose_root = (
                "プログラムの最上位エントリーポイント（起動・全体統括）として"
                "位置付けられています。"
                if is_ja
                else eng_root
            )
        prose_sentences.append(prose_root)

    prose_sentences.append(
        data_flow_desc.rstrip("。.") + ("。" if is_ja else ".")
    )

    if (
        sym.overview
        and sym.overview != sym.purpose
        and sym.overview != role_desc
    ):
        tmpl_ov = labels.get("prose_implementation_overview_template")
        eng_ov = "Implementation overview: {overview}"
        if not tmpl_ov or (is_ja and tmpl_ov == eng_ov):
            tmpl_ov = (
                "実装面では、{overview}"
                if is_ja
                else eng_ov
            )
        prose_sentences.append(tmpl_ov.format(overview=sym.overview))

    prose_paragraph = " ".join(prose_sentences)

    doc_title_tmpl = labels.get(
        "doc_title_template", "{kind} Documentation: `{name}`"
    )
    doc_title = doc_title_tmpl.format(
        kind=kind_display_name, name=sym.name
    )
    # Ensure natural Japanese phrasing without awkward space (e.g. '関数仕様書')
    if is_ja and f"{kind_display_name} 仕様書" in doc_title:
        doc_title = doc_title.replace(
            f"{kind_display_name} 仕様書", f"{kind_display_name}仕様書"
        )
    for eng_kind, ja_kind in (
        ("Function", "関数"),
        ("Class", "クラス"),
        ("Method", "メソッド"),
        ("Variable", "変数"),
        ("Struct", "構造体"),
        ("Enum", "列挙型"),
    ):
        if is_ja and f"{eng_kind} 仕様書" in doc_title:
            doc_title = doc_title.replace(
                f"{eng_kind} 仕様書", f"{ja_kind}仕様書"
            )
        elif is_ja and f"{eng_kind}仕様書" in doc_title:
            doc_title = doc_title.replace(
                f"{eng_kind}仕様書", f"{ja_kind}仕様書"
            )

    loc_tmpl = labels.get("location_template", "Line {start} to Line {end}")
    loc_str = loc_tmpl.format(start=sym.line_start, end=sym.line_end)

    lines = [
        f"{h_prefix} {doc_title}",
        "",
        prose_paragraph,
        "",
        labels.get("basic_info_title", "## 1. Basic Information"),
        f"- **{labels.get('label_fqdn', 'FQDN')}**: "
        f"`{sym.fqdn or sym.name}`",
        f"- **{labels.get('label_symbol_kind', 'Symbol Kind')}**: "
        f"`{kind_display}`",
        f"- **{labels.get('label_location', 'Location')}**: {loc_str}",
    ]
    if sym.signature:
        sig_lbl = labels.get("label_signature", "Signature / Type")
        lines.append(f"- **{sig_lbl}**: `{sym.signature}`")

    param_title = labels.get("parameters_title", "## 2. Parameters")
    none_lbl = labels.get("label_none", "None")
    if sym.parameters:
        lines.extend(["", param_title])
        for p in sym.parameters:
            p_type = f": `{p.type_hint}`" if p.type_hint else ""
            lines.append(f"- `{p.name}`{p_type}")
    else:
        lines.extend(["", param_title, f"- {none_lbl}"])

    if sym.return_type or sym.outputs_note or sym.inputs_note:
        input_ret_title = labels.get(
            "input_return_title", "## 3. Input / Return Specifications"
        )
        lines.extend(["", input_ret_title])
        if sym.inputs_note:
            in_lbl = labels.get("label_input_constraints", "Input Constraints")
            lines.append(f"- {in_lbl}: {sym.inputs_note}")
        void_lbl = labels.get("label_void_none", "void / None")
        ret_lbl = labels.get("label_return_type", "Return Type")
        lines.append(f"- {ret_lbl}: `{sym.return_type or void_lbl}`")
        if sym.outputs_note:
            out_lbl = labels.get(
                "label_return_value_side_effects",
                "Return Value & Side Effects",
            )
            lines.append(f"- {out_lbl}: {sym.outputs_note}")

    if sym.callees:
        callees_title = labels.get(
            "called_functions_title", "## 4. Called Functions"
        )
        lines.extend(["", callees_title])
        for c in sym.callees:
            lines.append(f"- `{c}`")
    elif sym.referencing_functions:
        refs_title = labels.get(
            "referencing_functions_title", "## 4. Referencing Functions"
        )
        lines.extend(["", refs_title])
        for r in sym.referencing_functions:
            lines.append(f"- {r}")

    if snippet:
        src_title = labels.get(
            "source_code_snippet_title", "## Source Code Snippet"
        )
        lines.extend(
            [
                "",
                src_title,
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
                    child,
                    file_path,
                    level=level + 1,
                    language=norm_lang,
                    labels=labels,
                )
            )

    return "\n".join(lines)


def write_single_symbol_doc(
    target_dir: Path,
    rel_path: Path,
    symbol: Symbol,
    prefix_name: str = "",
    language: str = "English",
    symbol_id_override: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
) -> Path:
    """Write an individual symbol document with immediate flush."""
    norm_lang = normalize_language(language)
    if labels is None:
        labels = get_or_init_document_labels(target_dir, norm_lang)
    pystdoc_dir = target_dir / ".pystdoc" / "documents"
    pystdoc_dir.mkdir(parents=True, exist_ok=True)

    k_prefix = get_kind_prefix(symbol.kind)
    sym_id = (
        symbol_id_override
        if symbol_id_override
        else (f"{prefix_name}{symbol.name}" if prefix_name else symbol.name)
    )
    out_file = pystdoc_dir / f"{rel_path.as_posix()}.{k_prefix}.{sym_id}.md"

    full_path = target_dir / rel_path
    content = format_symbol_section(
        symbol, full_path, level=1, language=norm_lang, labels=labels
    )

    write_flushed_text(out_file, content + "\n")
    return out_file


def write_individual_symbol_docs(
    target_dir: Path,
    rel_path: Path,
    symbols: List[Symbol],
    prefix_name: str = "",
    language: str = "English",
    labels: Optional[Dict[str, str]] = None,
) -> List[Path]:
    """Recursively write docs for each symbol with immediate flush."""
    norm_lang = normalize_language(language)
    if labels is None:
        labels = get_or_init_document_labels(target_dir, norm_lang)
    created_files: List[Path] = []

    for sym in symbols:
        out_file = write_single_symbol_doc(
            target_dir,
            rel_path,
            sym,
            prefix_name=prefix_name,
            language=norm_lang,
            labels=labels,
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
                labels=labels,
            )
            created_files.extend(child_files)

    return created_files


def write_symbol_doc(
    target_dir: Path,
    rel_path: Path,
    file_hash: str,
    symbols: List[Symbol],
    language: str = "English",
    labels: Optional[Dict[str, str]] = None,
) -> Path:
    """Write comprehensive file documentation with immediate flush."""
    norm_lang = normalize_language(language)
    if labels is None:
        labels = get_or_init_document_labels(target_dir, norm_lang)
    pystdoc_dir = target_dir / ".pystdoc" / "documents"
    pystdoc_dir.mkdir(parents=True, exist_ok=True)

    out_file = pystdoc_dir / f"{rel_path.as_posix()}.md"
    full_path = target_dir / rel_path

    title_fmt = labels.get(
        "file_doc_title_template", "File Documentation: `{path}`"
    )
    lines = [
        f"# {title_fmt.format(path=rel_path.as_posix())}",
        "",
        f"- **{labels.get('label_file_hash', 'File SHA-256')}**: "
        f"`{file_hash}`",
        f"- **{labels.get('label_detected_symbols', 'Detected Symbols')}**: "
        f"{len(symbols)}",
        "",
        labels.get("symbol_list_title", "## Symbol List"),
    ]

    item_tmpl = labels.get(
        "symbol_list_item_template",
        "- `{name}` ({kind}) [Lines: {line_range}]",
    )
    for sym in symbols:
        line_range = f"{sym.line_start}-{sym.line_end}"
        k_key = f"kind_{sym.kind.lower()}"
        k_name = labels.get(k_key, sym.kind)
        lines.append(
            item_tmpl.format(
                name=sym.name, kind=k_name, line_range=line_range
            )
        )

    lines.append("")
    for sym in symbols:
        lines.append(
            format_symbol_section(
                sym, full_path, level=2, language=norm_lang, labels=labels
            )
        )
        lines.append("")

    write_flushed_text(out_file, "\n".join(lines).strip() + "\n")
    return out_file
