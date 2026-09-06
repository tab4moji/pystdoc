"""Core engine for docgen: parallel analysis, SQLite, and progress."""

import concurrent.futures
import fcntl
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from pystdoc.scanner import scan_files, write_files_list
from pystdoc.hasher import compute_file_hash, compute_symbol_hash
from pystdoc.db import DocgenDB
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.doc_writer import (
    extract_symbols,
    get_code_language,
    get_code_snippet,
    write_symbol_doc,
    write_single_symbol_doc,
    write_individual_symbol_docs,
    normalize_language,
)
from pystdoc.llm_client import (
    LLMClient,
    sanitize_architectural_context,
)
from pystdoc.symbols import get_kind_prefix
from pystdoc.call_graph import (
    SymbolNode,
    flatten_symbols,
    link_variables_to_functions,
    order_symbols_by_levels,
    build_callee_context_summary,
)


class FileLock:
    """Inter-process directory lock using flock."""

    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self.fd = None

    def __enter__(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.lock_file, "w")
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.fd.close()
            self.fd = None
            print(
                f"Error: Another docgen process is currently processing "
                f"this directory: {self.lock_file}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            try:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                except Exception:
                    pass
            finally:
                self.fd.close()
                self.fd = None


def generate_static_symbol_doc(sym, lang_norm: str) -> Dict[str, str]:
    """Generate docs for enums/constants/fields/types from AST metadata."""
    is_ja = lang_norm in ("Japanese", "日本語")
    kind = sym.kind.lower()

    # Extract parent container name from FQDN if available
    parent_name = ""
    if sym.fqdn and "." in sym.fqdn:
        parts = sym.fqdn.split(".")
        if len(parts) >= 2:
            parent_name = parts[-2]

    sig_display = sym.signature or sym.name

    if "enum" in kind or kind == "enum_constant" or "const" in kind:
        if is_ja:
            p_ctx = f"「{parent_name}」における" if parent_name else ""
            return {
                "purpose": (
                    f"{p_ctx}状態コードまたは識別定数 `{sym.name}` を定義する"
                    "列挙型・定数要素。"
                ),
                "inputs": "なし（定数定義）。",
                "outputs": f"`{sig_display}` の定数識別値。",
                "overview": (
                    f"ステータス管理や条件判定で各処理から参照される"
                    f"列挙型・定数 `{sym.name}` の仕様。"
                ),
            }
        else:
            p_ctx = f" in `{parent_name}`" if parent_name else ""
            return {
                "purpose": (
                    f"Defines status code, constant, or enumeration "
                    f"`{sym.name}`{p_ctx}."
                ),
                "inputs": "None (constant definition).",
                "outputs": f"Constant `{sig_display}`.",
                "overview": (
                    f"Enumeration and constant definition `{sym.name}` "
                    "referenced in conditional logic and status management."
                ),
            }
    elif "field" in kind or "member" in kind:
        if is_ja:
            p_ctx = (
                f"データモデル「{parent_name}」"
                if parent_name
                else "データ構造"
            )
            return {
                "purpose": (
                    f"{p_ctx}において、`{sym.name}` ({sig_display}) の"
                    "データを保持・伝達するフィールド定義。"
                ),
                "inputs": "インスタンス初期化時またはプロパティ代入時の設定値。",
                "outputs": f"`{sig_display}` の保持データ値。",
                "overview": (
                    f"{p_ctx}のプロパティとして、モジュール間や関数間での"
                    f"データ受渡し・状態保持に利用されます。"
                ),
            }
        else:
            p_ctx = (
                f"in data model `{parent_name}`"
                if parent_name
                else "in data structure"
            )
            return {
                "purpose": (
                    f"Defines field `{sym.name}` ({sig_display}) {p_ctx} "
                    "for data storage and transfer."
                ),
                "inputs": (
                    "Value supplied during initialization or assignment."
                ),
                "outputs": f"Retained value `{sig_display}`.",
                "overview": (
                    f"Property utilized {p_ctx} to manage state and pass "
                    "structured data across functions."
                ),
            }
    elif "typedef" in kind or "type" in kind:
        if is_ja:
            return {
                "purpose": f"データ型または型エイリアス `{sym.name}` の仕様定義。",
                "inputs": "なし（型定義）。",
                "outputs": f"`{sig_display}` 型定義。",
                "overview": (
                    f"システム全体で共通利用されるデータ構造または"
                    f"型エイリアス `{sym.name}` の仕様。"
                ),
            }
        else:
            return {
                "purpose": f"Defines data type or alias `{sym.name}`.",
                "inputs": "None (type definition).",
                "outputs": f"Type `{sig_display}`.",
                "overview": (
                    "Specification of data structure or type alias "
                    f"`{sym.name}` used across modules."
                ),
            }
    elif "struct" in kind or "class" in kind:
        if is_ja:
            return {
                "purpose": (
                    f"データモデルまたは構造 `{sym.name}` の定義。"
                ),
                "inputs": "メンバ変数の初期化・設定パラメータ。",
                "outputs": f"`{sig_display}` の構造体データ。",
                "overview": (
                    "複数のデータ項目を集約して各モジュール間で受け渡すための "
                    f"`{sym.name}` の定義。"
                ),
            }
        else:
            return {
                "purpose": (
                    f"Defines data model or structure `{sym.name}`."
                ),
                "inputs": "Member field initialization parameters.",
                "outputs": f"Data structure `{sig_display}`.",
                "overview": (
                    "Encapsulates structured data fields for inter-module "
                    f"passing as `{sym.name}`."
                ),
            }
    elif "var" in kind:
        if is_ja:
            return {
                "purpose": (
                    f"状態データ `{sym.name}` ({sig_display}) を保持する変数定義。"
                ),
                "inputs": "代入される状態値。",
                "outputs": f"`{sig_display}` の保持値。",
                "overview": (
                    "各処理関数から参照・更新される共有状態 "
                    f"`{sym.name}` のデータ領域。"
                ),
            }
        else:
            return {
                "purpose": (
                    f"Holds state data for variable `{sym.name}` "
                    f"({sig_display})."
                ),
                "inputs": "Assigned state value.",
                "outputs": f"Retained value `{sig_display}`.",
                "overview": (
                    "Shared state data storage accessed and updated "
                    f"by processing functions as `{sym.name}`."
                ),
            }

    if is_ja:
        return {
            "purpose": f"`{sym.name}` ({sym.kind}) の機能定義。",
            "inputs": "パラメータ定義に従う。",
            "outputs": f"`{sig_display}` の処理結果。",
            "overview": f"`{sym.name}` の処理仕様およびモジュール内での役割。",
        }
    else:
        return {
            "purpose": f"Defines `{sym.name}` ({sym.kind}).",
            "inputs": "According to parameter definitions.",
            "outputs": f"Result `{sig_display}`.",
            "overview": f"Basic specification and role for `{sym.name}`.",
        }


def run_docgen(
    target_dir: Path,
    use_llm: bool = True,
    host: Optional[str] = None,
    base_url: Optional[str] = None,
    model: str = "gemma4-26b-a4b",
    token: Optional[str] = None,
    api_key: Optional[str] = None,
    context_size: int = 16384,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
    compile_commands_path: Optional[str] = None,
    concurrency: int = 1,
) -> int:
    target_dir = target_dir.resolve()
    norm_lang = normalize_language(language)
    if not target_dir.exists() or not target_dir.is_dir():
        print(
            f"Error: Specified directory does not exist: {target_dir}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    lock_path = target_dir / ".docgen" / ".lock"
    with FileLock(lock_path):
        header_msg = (
            f"=== docgen Started (Workers: {concurrency}, "
            f"Lang: {norm_lang}, SQLite index): {target_dir} ==="
        )
        print(header_msg, flush=True)

        db_path = target_dir / ".docgen" / "index.db"
        db = DocgenDB(db_path)

        comp_db = CompilationDatabase(
            db_path=Path(
                compile_commands_path) if compile_commands_path else None,
            target_dir=target_dir,
        )
        if comp_db.loaded_path:
            print(
                f"[CompDB] Detected compilation database: "
                f"{comp_db.loaded_path}",
                flush=True,
            )

        llm_client = None
        if use_llm:
            client = LLMClient(
                host=host or base_url,
                model=model,
                token=token or api_key,
                context_size=context_size,
            )
            if client.check_availability():
                llm_client = client
                auth_info = " (authenticated)" if client.token else ""
                print(
                    f"[LLM] Connected to server: {client.base_url} "
                    f"(model: {client.model}, "
                    f"context: {client.context_size}{auth_info})",
                    flush=True,
                )
            else:
                if not allow_fallback:
                    print(
                        f"Error: Failed to connect to LLM server "
                        f"({client.base_url}). Aborting without "
                        "--allow-fallback.",
                        file=sys.stderr,
                        flush=True,
                    )
                    db.close()
                    return 1
                else:
                    print(
                        f"[LLM Warning] LLM server unreachable "
                        f"({client.base_url}). Fallback to static templates.",
                        flush=True,
                    )

        # 1. Scan files
        matched_files = scan_files(target_dir)
        files_txt = write_files_list(target_dir, matched_files)
        print(
            f"[1/5] Scanned files: {len(matched_files)} detected -> "
            f"{files_txt}",
            flush=True,
        )

        # 2. Compute hashes and enumerate all symbols
        file_hashes: Dict[Path, str] = {}
        file_symbols: Dict[Path, list] = {}
        all_symbol_nodes: List[SymbolNode] = []

        for rel_path in matched_files:
            full_path = target_dir / rel_path
            h = compute_file_hash(full_path)
            file_hashes[rel_path] = h
            db.update_file_hash(rel_path.as_posix(), h)

            symbols = extract_symbols(full_path, comp_db=comp_db)
            file_symbols[rel_path] = symbols

            nodes = flatten_symbols(symbols, rel_path, full_path)
            all_symbol_nodes.extend(nodes)

        total_symbols_count = len(all_symbol_nodes)
        print(
            f"[2/5] Enumerated symbols (with FQDN): "
            f"{total_symbols_count} symbols total",
            flush=True,
        )

        link_variables_to_functions(all_symbol_nodes)

        # 3. Pass 1: Level-by-Level DAG parallel processing
        level_groups = order_symbols_by_levels(all_symbol_nodes)
        total_levels = len(level_groups)
        resolved_symbols_map: Dict[str, SymbolNode] = {
            node.unique_id: node for node in all_symbol_nodes
        }

        print_lock = threading.Lock()
        started_counter = [0]
        completed_counter = [0]

        print(
            f"[3/5] Pass 1: Level-by-Level analysis "
            f"(Total {total_levels} levels, Workers: {concurrency})...",
            flush=True,
        )

        def process_single_node(node: SymbolNode) -> None:
            sym = node.symbol
            rel_path = node.rel_path
            full_path = node.full_path

            snippet = get_code_snippet(
                full_path, sym.line_start, sym.line_end
            )
            prefix_in_unique_id = ""
            if "::" in node.unique_id:
                id_part = node.unique_id.split("::", 1)[1]
                raw_id = id_part.split(".", 1)[-1]
                if "." in raw_id:
                    prefix_in_unique_id = raw_id.rsplit(".", 1)[0] + "."

            sym_hash = compute_symbol_hash(snippet, sym.signature, sym.doc)
            is_sym_changed = db.update_symbol_hash(
                node.unique_id, rel_path.as_posix(), sym_hash
            )
            db.save_symbol_metadata(node.unique_id, sym, rel_path.as_posix())

            k_pfx = get_kind_prefix(sym.kind)
            sym_id_str = (
                f"{prefix_in_unique_id}{sym.name}"
                if prefix_in_unique_id
                else sym.name
            )
            docgen_docs_dir = target_dir / ".docgen" / "documents"
            expected_sym_doc = (
                docgen_docs_dir
                / f"{rel_path.as_posix()}.{k_pfx}.{sym_id_str}.md"
            )
            expected_file_doc = docgen_docs_dir / f"{rel_path.as_posix()}.md"
            doc_file_missing = (
                not expected_sym_doc.exists() or not expected_file_doc.exists()
            )

            # Cache check with language key (bypass if file was deleted)
            cache_key = f"{node.unique_id}::{norm_lang}"
            cached_data = (
                db.load_symbol_cache(cache_key)
                or db.load_symbol_cache(node.unique_id)
                if not force and not is_sym_changed and not doc_file_missing
                else None
            )

            with print_lock:
                started_counter[0] += 1
                curr_idx = started_counter[0]
                percent = (
                    (curr_idx / total_symbols_count * 100.0)
                    if total_symbols_count > 0
                    else 100.0
                )
                progress_str = (
                    f"[{curr_idx}/{total_symbols_count} ({percent:5.1f}%)]"
                )

            # Check if this symbol should be statically resolved without LLM
            sym_kind_lower = sym.kind.lower()
            is_static_bypass = (
                "enum" in sym_kind_lower
                or sym_kind_lower in (
                    "enum_constant",
                    "typedef",
                    "field",
                    "member",
                    "variable",
                    "const",
                )
            )

            if cached_data:
                sym.purpose = cached_data.get("purpose", sym.purpose)
                sym.inputs_note = cached_data.get(
                    "inputs_note", sym.inputs_note)
                sym.outputs_note = cached_data.get(
                    "outputs_note", sym.outputs_note)
                sym.overview = cached_data.get("overview", sym.overview)
                sym.top_down_context = cached_data.get(
                    "top_down_context", sym.top_down_context
                )
                with print_lock:
                    completed_counter[0] += 1
                    print(
                        f"  {progress_str} [Cached]: "
                        f"{node.unique_id} (Lvl {node.dag_level})",
                        flush=True,
                    )
            elif is_static_bypass:
                # Fast AST-based static generation (0s, prevents LLM deadlock)
                static_doc = generate_static_symbol_doc(sym, norm_lang)
                sym.purpose = static_doc["purpose"]
                sym.inputs_note = static_doc["inputs"]
                sym.outputs_note = static_doc["outputs"]
                sym.overview = static_doc["overview"]

                save_payload = {
                    "purpose": sym.purpose,
                    "inputs_note": sym.inputs_note,
                    "outputs_note": sym.outputs_note,
                    "overview": sym.overview,
                    "top_down_context": sym.top_down_context,
                }
                db.save_symbol_cache(cache_key, save_payload)
                db.save_symbol_cache(node.unique_id, save_payload)

                with print_lock:
                    completed_counter[0] += 1
                    print(
                        f"  {progress_str} [Static Spec]: "
                        f"{node.unique_id} (Lvl {node.dag_level})",
                        flush=True,
                    )
            elif llm_client:
                callee_context = build_callee_context_summary(
                    node, resolved_symbols_map
                )
                dep_info = (
                    f" (Callees: {len(node.direct_callee_ids)})"
                    if node.direct_callee_ids
                    else ""
                )
                with print_lock:
                    print(
                        f"  {progress_str} [LLM Requesting...]: "
                        f"{node.unique_id} (Lvl {node.dag_level}){dep_info}",
                        flush=True,
                    )

                param_strs = [
                    f"{p.name} ({p.type_hint})" if p.type_hint else p.name
                    for p in sym.parameters
                ]
                lang = get_code_language(full_path.suffix)

                start_sym_time = time.time()
                explanation = llm_client.explain_symbol(
                    name=sym.name,
                    kind=sym.kind,
                    code=snippet,
                    signature=sym.signature,
                    lang=lang,
                    callees=sym.callees,
                    params=param_strs,
                    ret_type=sym.return_type,
                    callee_context=callee_context,
                    language=norm_lang,
                    allow_fallback=allow_fallback,
                )
                sym_elapsed = time.time() - start_sym_time

                if explanation.get("purpose"):
                    sym.purpose = explanation["purpose"]
                if explanation.get("inputs"):
                    sym.inputs_note = explanation["inputs"]
                if explanation.get("outputs"):
                    sym.outputs_note = explanation["outputs"]
                if explanation.get("overview"):
                    sym.overview = explanation["overview"]
                raw_arch = (
                    explanation.get("architectural_context")
                    or explanation.get("role")
                )
                if raw_arch:
                    sym.top_down_context = sanitize_architectural_context(
                        raw_arch, fallback_text=sym.purpose or ""
                    )

                save_payload = {
                    "purpose": sym.purpose,
                    "inputs_note": sym.inputs_note,
                    "outputs_note": sym.outputs_note,
                    "overview": sym.overview,
                    "top_down_context": sym.top_down_context,
                }
                db.save_symbol_cache(cache_key, save_payload)
                db.save_symbol_cache(node.unique_id, save_payload)

                with print_lock:
                    completed_counter[0] += 1
                    done_count = completed_counter[0]
                    done_pct = (
                        (done_count / total_symbols_count * 100.0)
                        if total_symbols_count > 0
                        else 100.0
                    )
                    done_msg = (
                        f"       -> [Done in {sym_elapsed:5.1f}s] "
                        f"({done_count}/{total_symbols_count} - "
                        f"{done_pct:5.1f}%): {node.unique_id}"
                    )
                    print(done_msg, flush=True)
            else:
                with print_lock:
                    completed_counter[0] += 1
                    print(
                        f"  {progress_str} [Static Info]: {node.unique_id}",
                        flush=True,
                    )

            write_single_symbol_doc(
                target_dir,
                rel_path,
                sym,
                prefix_name=prefix_in_unique_id,
                language=norm_lang,
            )

        # Process Level by Level
        for lvl_idx, lvl_nodes in enumerate(level_groups):
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=concurrency
            ) as executor:
                futures = [
                    executor.submit(process_single_node, node)
                    for node in lvl_nodes
                ]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        print(f"\nError: {e}", file=sys.stderr, flush=True)
                        db.close()
                        return 1

        # 4. Pass 2: Top-down variable & field refinement
        type_nodes = [
            n
            for n in all_symbol_nodes
            if get_kind_prefix(n.symbol.kind) == "type"
        ]
        var_nodes = [
            n
            for n in all_symbol_nodes
            if get_kind_prefix(n.symbol.kind) in ("var", "const")
            or n.symbol.kind.lower() in (
                "field",
                "member",
                "variable",
                "var",
                "const",
                "constant",
                "enum_constant",
            )
        ]
        total_var_count = len(var_nodes)
        print(
            f"[4/5] Pass 2: Top-down contextual refinement "
            f"({total_var_count} data symbols)...",
            flush=True,
        )

        fn_nodes = [
            n
            for n in all_symbol_nodes
            if get_kind_prefix(n.symbol.kind) == "fn"
        ]
        var_counter = [0]
        var_done_counter = [0]

        def process_var_node(v_node: SymbolNode) -> None:
            v_sym = v_node.symbol
            v_rel = v_node.rel_path
            v_full = v_node.full_path

            with print_lock:
                var_counter[0] += 1
                v_curr = var_counter[0]
                v_percent = (
                    (v_curr / total_var_count * 100.0)
                    if total_var_count > 0
                    else 100.0
                )
                v_progress = (
                    f"[{v_curr}/{total_var_count} ({v_percent:5.1f}%)]"
                )

            # Find parent container (class/struct/model)
            parent_container_info = None
            parent_name = ""
            if v_sym.fqdn and "." in v_sym.fqdn:
                parts = v_sym.fqdn.split(".")
                if len(parts) >= 2:
                    parent_name = parts[-2]
            elif "::" in v_node.unique_id:
                id_part = v_node.unique_id.split("::", 1)[1]
                raw_id = id_part.split(".", 1)[-1]
                if "." in raw_id:
                    parent_name = raw_id.rsplit(".", 1)[0].split(".")[-1]

            if parent_name:
                for t in type_nodes:
                    if t.rel_path == v_rel and t.symbol.name == parent_name:
                        parent_container_info = {
                            "name": t.symbol.name,
                            "kind": t.symbol.kind,
                            "purpose": t.symbol.purpose or "",
                            "overview": t.symbol.overview or "",
                        }
                        break
                if not parent_container_info:
                    parent_container_info = {
                        "name": parent_name,
                        "kind": "class/struct/data model",
                        "purpose": "",
                        "overview": "",
                    }

            # Find referencing/parent functions
            parent_funcs = []
            for f in fn_nodes:
                if f.rel_path == v_rel:
                    parent_funcs.append(
                        {
                            "name": f.symbol.name,
                            "file": f.rel_path.name,
                            "purpose": f.symbol.purpose or "Execution",
                            "overview": f.symbol.overview or "",
                        }
                    )

            if not parent_funcs:
                for f in fn_nodes:
                    callees = f.symbol.callees
                    sig = f.symbol.signature or ""
                    if v_sym.name in callees or v_sym.name in sig:
                        parent_funcs.append(
                            {
                                "name": f.symbol.name,
                                "file": f.rel_path.name,
                                "purpose": f.symbol.purpose or "Execution",
                                "overview": f.symbol.overview or "",
                            }
                        )

            prefix_in_unique_id = ""
            if "::" in v_node.unique_id:
                id_part = v_node.unique_id.split("::", 1)[1]
                raw_id = id_part.split(".", 1)[-1]
                if "." in raw_id:
                    prefix_in_unique_id = raw_id.rsplit(".", 1)[0] + "."

            v_k_pfx = get_kind_prefix(v_sym.kind)
            v_sym_id_str = (
                f"{prefix_in_unique_id}{v_sym.name}"
                if prefix_in_unique_id
                else v_sym.name
            )
            v_docgen_docs_dir = target_dir / ".docgen" / "documents"
            v_expected_sym_doc = (
                v_docgen_docs_dir
                / f"{v_rel.as_posix()}.{v_k_pfx}.{v_sym_id_str}.md"
            )
            v_doc_missing = not v_expected_sym_doc.exists()

            should_refine = (
                llm_client
                and (parent_funcs or parent_container_info)
                and (force or v_doc_missing or not v_sym.top_down_context)
            )
            if should_refine:
                ctx_names = []
                if parent_container_info:
                    ctx_names.append(f"Model: {parent_container_info['name']}")
                if parent_funcs:
                    f_names = ", ".join(f["name"] for f in parent_funcs[:2])
                    ctx_names.append(f"Funcs: {f_names}")
                ctx_desc = " | ".join(ctx_names)

                with print_lock:
                    print(
                        f"  {v_progress} [Top-down Context Updating...]: "
                        f"{v_node.unique_id} ({ctx_desc})",
                        flush=True,
                    )

                v_snippet = get_code_snippet(
                    v_full, v_sym.line_start, v_sym.line_end
                )
                lang = get_code_language(v_full.suffix)

                start_var_time = time.time()
                top_down_res = llm_client.refine_variable_top_down(
                    var_name=v_sym.name,
                    var_kind=v_sym.kind,
                    var_signature=v_sym.signature,
                    var_code=v_snippet,
                    parent_functions_info=parent_funcs,
                    lang=lang,
                    language=norm_lang,
                    allow_fallback=allow_fallback,
                    parent_container_info=parent_container_info,
                )
                var_elapsed = time.time() - start_var_time

                raw_v_role = (
                    top_down_res.get("architectural_context")
                    or top_down_res.get("role")
                    or top_down_res.get("significance")
                    or top_down_res.get("top_down_summary")
                )
                if raw_v_role:
                    v_sym.top_down_context = sanitize_architectural_context(
                        raw_v_role, fallback_text=v_sym.purpose or ""
                    )
                if top_down_res.get("purpose"):
                    v_sym.purpose = top_down_res["purpose"]
                if top_down_res.get("overview"):
                    v_sym.overview = top_down_res["overview"]

                save_payload = {
                    "purpose": v_sym.purpose,
                    "inputs_note": v_sym.inputs_note,
                    "outputs_note": v_sym.outputs_note,
                    "overview": v_sym.overview,
                    "top_down_context": v_sym.top_down_context,
                }
                cache_key = f"{v_node.unique_id}::{norm_lang}"
                db.save_symbol_cache(cache_key, save_payload)
                db.save_symbol_cache(v_node.unique_id, save_payload)

                with print_lock:
                    var_done_counter[0] += 1
                    vd = var_done_counter[0]
                    v_pct = (
                        (vd / total_var_count * 100.0)
                        if total_var_count > 0
                        else 100.0
                    )
                    done_var_msg = (
                        f"       -> [Done in {var_elapsed:5.1f}s] "
                        f"({vd}/{total_var_count} - {v_pct:5.1f}%): "
                        f"{v_node.unique_id}"
                    )
                    print(done_var_msg, flush=True)

                prefix_in_unique_id = ""
                if "::" in v_node.unique_id:
                    id_part = v_node.unique_id.split("::", 1)[1]
                    raw_id = id_part.split(".", 1)[-1]
                    if "." in raw_id:
                        prefix_in_unique_id = raw_id.rsplit(".", 1)[0] + "."
                write_single_symbol_doc(
                    target_dir,
                    v_rel,
                    v_sym,
                    prefix_name=prefix_in_unique_id,
                    language=norm_lang,
                )
            else:
                with print_lock:
                    var_done_counter[0] += 1
                    print(
                        f"  {v_progress} [Retained Variable Context]: "
                        f"{v_node.unique_id}",
                        flush=True,
                    )

        if var_nodes:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=concurrency
            ) as executor:
                futures = [
                    executor.submit(process_var_node, v) for v in var_nodes
                ]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        print(f"\nError: {e}", file=sys.stderr, flush=True)
                        db.close()
                        return 1

        # 5. Flush all documentation with caller usage purposes
        id_to_node_map = {n.unique_id: n for n in all_symbol_nodes}
        for n in all_symbol_nodes:
            if n.direct_caller_ids:
                caller_info_list = []
                for c_id in sorted(list(n.direct_caller_ids)):
                    if c_id in id_to_node_map:
                        c_node = id_to_node_map[c_id]
                        c_purpose = c_node.symbol.purpose or ""
                        c_rel = c_node.rel_path.name
                        if c_purpose:
                            caller_info_list.append(
                                f"`{c_node.symbol.name}` (`{c_rel}`): "
                                f"{c_purpose}"
                            )
                        else:
                            caller_info_list.append(
                                f"`{c_node.symbol.name}` (`{c_rel}`)"
                            )
                if caller_info_list:
                    n.symbol.referencing_functions = caller_info_list

        total_individual_docs = 0
        for rel_path in matched_files:
            symbols = file_symbols[rel_path]
            current_hash = file_hashes[rel_path]

            write_symbol_doc(
                target_dir, rel_path, current_hash, symbols, language=norm_lang
            )
            ind_docs = write_individual_symbol_docs(
                target_dir, rel_path, symbols, language=norm_lang
            )
            total_individual_docs += len(ind_docs)

        db.close()
        summary_msg = (
            f"[5/5] Recorded documents: {len(matched_files)} files, "
            f"{total_individual_docs} individual symbol docs"
        )
        print(summary_msg, flush=True)
        print("=== docgen Finished ===", flush=True)
    return 0
