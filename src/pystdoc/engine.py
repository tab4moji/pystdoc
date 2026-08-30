"""Core engine for docgen: level-by-level parallel LLM analysis and SQLite storage with static bypass for enums/constants and real-time progress."""

import concurrent.futures
import fcntl
import os
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
from pystdoc.llm_client import LLMClient, LLMError
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
            print(f"Error: Another docgen process is currently processing this directory: {self.lock_file}", file=sys.stderr, flush=True)
            sys.exit(1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
            except Exception:
                pass


def generate_static_symbol_doc(sym, lang_norm: str) -> Dict[str, str]:
    """Generate high-precision documentation for enums, constants, and basic types from static AST metadata."""
    is_ja = lang_norm in ("Japanese", "日本語")
    kind = sym.kind.lower()

    if "enum" in kind or kind == "enum_constant":
        if is_ja:
            return {
                "purpose": f"状態コードまたは識別子定数 `{sym.name}` を定義する列挙型要素。",
                "inputs": "なし（定数定義）。",
                "outputs": f"`{sym.signature or sym.name}` の定数識別値。",
                "overview": f"システム全体で一貫したステータス管理や条件判定に使用される `{sym.name}` の定義。",
            }
        else:
            return {
                "purpose": f"Defines status code or identifier constant `{sym.name}`.",
                "inputs": "None (constant definition).",
                "outputs": f"Constant identifier value `{sym.signature or sym.name}`.",
                "overview": f"Enumeration definition used for status handling and conditional flow across the system.",
            }
    elif "typedef" in kind or "type" in kind:
        if is_ja:
            return {
                "purpose": f"データ型またはエイリアス `{sym.name}` の定義。",
                "inputs": "なし（型定義）。",
                "outputs": f"`{sym.signature or sym.name}` 型。",
                "overview": f"システム全体で共通利用されるデータ構造または型エイリアス `{sym.name}` の仕様。",
            }
        else:
            return {
                "purpose": f"Defines data type or alias `{sym.name}`.",
                "inputs": "None (type definition).",
                "outputs": f"Type `{sym.signature or sym.name}`.",
                "overview": f"Specification of data structure or type alias `{sym.name}` used across modules.",
            }

    if is_ja:
        return {
            "purpose": f"`{sym.name}` ({sym.kind}) の定義。",
            "inputs": "パラメータ定義に従う。",
            "outputs": "結果値または状態遷移。",
            "overview": f"`{sym.name}` の基本仕様。",
        }
    else:
        return {
            "purpose": f"Defines `{sym.name}` ({sym.kind}).",
            "inputs": "According to parameter definitions.",
            "outputs": "Result value or state mutation.",
            "overview": f"Basic specification for `{sym.name}`.",
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
        print(f"Error: Specified directory does not exist: {target_dir}", file=sys.stderr, flush=True)
        return 1

    lock_path = target_dir / ".docgen" / ".lock"
    with FileLock(lock_path):
        print(f"=== docgen Started (Workers: {concurrency}, Lang: {norm_lang}, SQLite index): {target_dir} ===", flush=True)

        db_path = target_dir / ".docgen" / "index.db"
        db = DocgenDB(db_path)

        comp_db = CompilationDatabase(
            db_path=Path(compile_commands_path) if compile_commands_path else None,
            target_dir=target_dir,
        )
        if comp_db.loaded_path:
            print(f"[CompDB] Detected compilation database: {comp_db.loaded_path}", flush=True)

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
                print(f"[LLM] Connected to server: {client.base_url} (model: {client.model}, context: {client.context_size}{auth_info})", flush=True)
            else:
                if not allow_fallback:
                    print(f"Error: Failed to connect to LLM server ({client.base_url}). Aborting without --allow-fallback.", file=sys.stderr, flush=True)
                    db.close()
                    return 1
                else:
                    print(f"[LLM Warning] LLM server unreachable ({client.base_url}). Fallback to static templates.", flush=True)

        # 1. Scan files
        matched_files = scan_files(target_dir)
        files_txt = write_files_list(target_dir, matched_files)
        print(f"[1/5] Scanned files: {len(matched_files)} detected -> {files_txt}", flush=True)

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
        print(f"[2/5] Enumerated symbols (with FQDN): {total_symbols_count} symbols total", flush=True)

        link_variables_to_functions(all_symbol_nodes)

        # 3. Pass 1: Level-by-Level DAG parallel processing
        level_groups = order_symbols_by_levels(all_symbol_nodes)
        total_levels = len(level_groups)
        resolved_symbols_map: Dict[str, SymbolNode] = {node.unique_id: node for node in all_symbol_nodes}

        print_lock = threading.Lock()
        started_counter = [0]
        completed_counter = [0]

        print(f"[3/5] Pass 1: Level-by-Level analysis (Total {total_levels} levels, Workers: {concurrency})...", flush=True)

        def process_single_node(node: SymbolNode) -> None:
            sym = node.symbol
            rel_path = node.rel_path
            full_path = node.full_path

            snippet = get_code_snippet(full_path, sym.line_start, sym.line_end)
            prefix_in_unique_id = ""
            if "::" in node.unique_id:
                id_part = node.unique_id.split("::", 1)[1]
                raw_id = id_part.split(".", 1)[-1]
                if "." in raw_id:
                    prefix_in_unique_id = raw_id.rsplit(".", 1)[0] + "."

            sym_hash = compute_symbol_hash(snippet, sym.signature, sym.doc)
            is_sym_changed = db.update_symbol_hash(node.unique_id, rel_path.as_posix(), sym_hash)
            db.save_symbol_metadata(node.unique_id, sym, rel_path.as_posix())

            # Cache check with language key
            cache_key = f"{node.unique_id}::{norm_lang}"
            cached_data = db.load_symbol_cache(cache_key) or db.load_symbol_cache(node.unique_id) if not force and not is_sym_changed else None

            with print_lock:
                started_counter[0] += 1
                curr_idx = started_counter[0]
                percent = (curr_idx / total_symbols_count * 100.0) if total_symbols_count > 0 else 100.0
                progress_str = f"[{curr_idx}/{total_symbols_count} ({percent:5.1f}%)]"

            # Check if this symbol should be statically resolved without LLM (enum, enum_constant, typedef)
            sym_kind_lower = sym.kind.lower()
            is_static_bypass = ("enum" in sym_kind_lower or sym_kind_lower in ("enum_constant", "typedef"))

            if cached_data:
                sym.purpose = cached_data.get("purpose", sym.purpose)
                sym.inputs_note = cached_data.get("inputs_note", sym.inputs_note)
                sym.outputs_note = cached_data.get("outputs_note", sym.outputs_note)
                sym.overview = cached_data.get("overview", sym.overview)
                sym.top_down_context = cached_data.get("top_down_context", sym.top_down_context)
                with print_lock:
                    completed_counter[0] += 1
                    print(f"  {progress_str} [Cached]: {node.unique_id} (Lvl {node.dag_level})", flush=True)
            elif is_static_bypass:
                # Fast AST-based static generation (0s, prevents LLM deadlock on enums)
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
                    done_count = completed_counter[0]
                    done_pct = (done_count / total_symbols_count * 100.0) if total_symbols_count > 0 else 100.0
                    print(f"  {progress_str} [Static Spec]: {node.unique_id} (Lvl {node.dag_level})", flush=True)
            elif llm_client:
                callee_context = build_callee_context_summary(node, resolved_symbols_map)
                dep_info = f" (Callees: {len(node.direct_callee_ids)})" if node.direct_callee_ids else ""
                with print_lock:
                    print(f"  {progress_str} [LLM Requesting...]: {node.unique_id} (Lvl {node.dag_level}){dep_info}", flush=True)

                param_strs = [f"{p.name} ({p.type_hint})" if p.type_hint else p.name for p in sym.parameters]
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
                    done_pct = (done_count / total_symbols_count * 100.0) if total_symbols_count > 0 else 100.0
                    print(f"       -> [Done in {sym_elapsed:5.1f}s] ({done_count}/{total_symbols_count} - {done_pct:5.1f}%): {node.unique_id}", flush=True)
            else:
                with print_lock:
                    completed_counter[0] += 1
                    print(f"  {progress_str} [Static Info]: {node.unique_id}", flush=True)

            write_single_symbol_doc(target_dir, rel_path, sym, prefix_name=prefix_in_unique_id, language=norm_lang)

        # Process Level by Level
        for lvl_idx, lvl_nodes in enumerate(level_groups):
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(process_single_node, node) for node in lvl_nodes]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        print(f"\nError: {e}", file=sys.stderr, flush=True)
                        db.close()
                        return 1

        # 4. Pass 2: Top-down variable refinement
        var_nodes = [n for n in all_symbol_nodes if get_kind_prefix(n.symbol.kind) == "var"]
        total_var_count = len(var_nodes)
        print(f"[4/5] Pass 2: Top-down variable contextual refinement ({total_var_count} variables)...", flush=True)

        fn_nodes = [n for n in all_symbol_nodes if get_kind_prefix(n.symbol.kind) == "fn"]
        var_counter = [0]
        var_done_counter = [0]

        def process_var_node(v_node: SymbolNode) -> None:
            v_sym = v_node.symbol
            v_rel = v_node.rel_path
            v_full = v_node.full_path

            with print_lock:
                var_counter[0] += 1
                v_curr = var_counter[0]
                v_percent = (v_curr / total_var_count * 100.0) if total_var_count > 0 else 100.0
                v_progress = f"[{v_curr}/{total_var_count} ({v_percent:5.1f}%)]"

            parent_funcs = []
            for f in fn_nodes:
                if f.rel_path == v_rel:
                    parent_funcs.append({
                        "name": f.symbol.name,
                        "file": f.rel_path.name,
                        "purpose": f.symbol.purpose or "Execution",
                        "overview": f.symbol.overview or "",
                    })

            if not parent_funcs:
                for f in fn_nodes:
                    if v_sym.name in f.symbol.callees or (f.symbol.signature and v_sym.name in f.symbol.signature):
                        parent_funcs.append({
                            "name": f.symbol.name,
                            "file": f.rel_path.name,
                            "purpose": f.symbol.purpose or "Execution",
                            "overview": f.symbol.overview or "",
                        })

            if llm_client and parent_funcs and (force or not v_sym.top_down_context):
                funcs_names = ", ".join(f["name"] for f in parent_funcs[:2])
                with print_lock:
                    print(f"  {v_progress} [Top-down Variable Updating...]: {v_node.unique_id} (Referenced by: {funcs_names})", flush=True)

                v_snippet = get_code_snippet(v_full, v_sym.line_start, v_sym.line_end)
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
                )
                var_elapsed = time.time() - start_var_time

                lines = []
                if top_down_res.get("significance"):
                    lines.append(f"- **Role in Callers**: {top_down_res['significance']}")
                if top_down_res.get("usage_scenario"):
                    lines.append(f"- **Data Flow & Usage Scenario**: {top_down_res['usage_scenario']}")
                if top_down_res.get("top_down_summary"):
                    lines.append(f"- **Summary**: {top_down_res['top_down_summary']}")

                v_sym.top_down_context = "\n".join(lines)

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
                    v_pct = (vd / total_var_count * 100.0) if total_var_count > 0 else 100.0
                    print(f"       -> [Done in {var_elapsed:5.1f}s] ({vd}/{total_var_count} - {v_pct:5.1f}%): {v_node.unique_id}", flush=True)

                prefix_in_unique_id = ""
                if "::" in v_node.unique_id:
                    id_part = v_node.unique_id.split("::", 1)[1]
                    raw_id = id_part.split(".", 1)[-1]
                    if "." in raw_id:
                        prefix_in_unique_id = raw_id.rsplit(".", 1)[0] + "."
                write_single_symbol_doc(target_dir, v_rel, v_sym, prefix_name=prefix_in_unique_id, language=norm_lang)
            else:
                with print_lock:
                    var_done_counter[0] += 1
                    print(f"  {v_progress} [Retained Variable Context]: {v_node.unique_id}", flush=True)

        if var_nodes:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(process_var_node, v) for v in var_nodes]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        print(f"\nError: {e}", file=sys.stderr, flush=True)
                        db.close()
                        return 1

        # 5. Flush all documentation
        total_individual_docs = 0
        for rel_path in matched_files:
            symbols = file_symbols[rel_path]
            current_hash = file_hashes[rel_path]

            write_symbol_doc(target_dir, rel_path, current_hash, symbols, language=norm_lang)
            ind_docs = write_individual_symbol_docs(target_dir, rel_path, symbols, language=norm_lang)
            total_individual_docs += len(ind_docs)

        db.close()
        print(f"[5/5] Recorded documents: {len(matched_files)} files, {total_individual_docs} individual symbol docs", flush=True)
        print("=== docgen Finished ===", flush=True)
    return 0
