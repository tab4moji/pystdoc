"""Design Engine: Synthesizes high-level architectural documents with hierarchical Map-Reduce, SQLite caching, and multi-language support."""

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from pystdoc.cache import write_flushed_text
from pystdoc.db import DocgenDB
from pystdoc.doc_writer import normalize_language
from pystdoc.llm_client import LLMClient, LLMError


def parse_symbol_doc(md_path: Path) -> Dict[str, Any]:
    """Parse key sections from an individual symbol or file markdown document."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    data = {
        "file_name": md_path.name,
        "path": md_path.as_posix(),
        "title": "",
        "purpose": "",
        "signature": "",
        "kind": "",
        "callees": [],
        "referencing_funcs": [],
        "context": "",
        "raw_text": text,
    }

    m_title = re.search(r"^# (.+)$", text, re.MULTILINE)
    if m_title:
        data["title"] = m_title.group(1).strip()

    # 1. Extract Top-Down Context if present
    m_top_down = re.search(r"## 1\..*Top-Down.*\n([\s\S]*?)(?=\n## 2\.|\Z)", text, re.IGNORECASE)
    if m_top_down:
        data["context"] = m_top_down.group(1).strip()

    # 2. Extract Bottom-Up Purpose (from new layout or legacy layout)
    m_purpose_new = re.search(r"- \*\*Core Purpose\*\*:\s*([^\n]+)", text)
    if m_purpose_new:
        data["purpose"] = m_purpose_new.group(1).strip()
    else:
        m_purpose_legacy = re.search(r"## 1\..*(?:Design Intent|Purpose).*\n([\s\S]*?)(?=\n## 2\.|\Z)", text)
        if m_purpose_legacy and not m_top_down:
            data["purpose"] = m_purpose_legacy.group(1).strip()
        elif m_top_down:
            data["purpose"] = data["context"]

    # 3. Extract Kind & Signature
    m_kind = re.search(r"- \*\*(?:Symbol Kind|Kind)[^*]*\*\*:\s*`?([^`\n]+)`?", text, re.IGNORECASE)
    if m_kind:
        data["kind"] = m_kind.group(1).strip().split()[0]
    m_sig = re.search(r"- \*\*(?:Signature|Type)[^*]*\*\*:\s*`([^`]+)`", text, re.IGNORECASE)
    if m_sig:
        data["signature"] = m_sig.group(1).strip()

    # 4. Extract Callees & References (section 5 or 6)
    m_callees = re.search(r"## [56]\..*(?:Called Functions|Callees).*\n([\s\S]*?)(?=\n## |\Z)", text, re.IGNORECASE)
    if m_callees:
        callee_lines = re.findall(r"- `([^`]+)`", m_callees.group(1))
        data["callees"] = [c for c in callee_lines if c not in ("None", "none")]

    m_refs = re.search(r"## [56]\..*(?:Referencing Functions|References).*\n([\s\S]*?)(?=\n## |\Z)", text, re.IGNORECASE)
    if m_refs:
        ref_lines = re.findall(r"- `([^`]+)`", m_refs.group(1))
        data["referencing_funcs"] = [r for r in ref_lines if r not in ("None", "none")]

    return data


def group_docs_by_module(docs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group documents into logical modules based on directory paths and prefixes."""
    modules = defaultdict(list)
    for d in docs:
        filename = d["file_name"]
        clean_name = re.sub(r"\.(fn|var|type|const)\..*$", "", filename)
        clean_name = re.sub(r"\.md$", "", clean_name)

        parts = clean_name.split("/")
        if len(parts) > 1:
            mod_name = parts[-2] if parts[-1] in ("client.py", "service.py", "math.c", "math.h", "types.h", "run.sh") else parts[0]
            if mod_name in ("src", "include", "scripts"):
                mod_name = parts[1] if len(parts) > 2 else parts[-1].split(".")[0]
        else:
            base = parts[0].split(".")[0]
            mod_name = "main" if base in ("main", "app") else base

        modules[mod_name].append(d)
    return dict(modules)


def chunk_list_by_size(items: List[str], max_items: int = 15, max_chars: int = 3500) -> List[List[str]]:
    """Split a list of string items into chunks constrained by item count and character limit."""
    chunks: List[List[str]] = []
    current_chunk: List[str] = []
    current_length = 0

    for item in items:
        item_len = len(item)
        if (len(current_chunk) >= max_items or (current_length + item_len > max_chars)) and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [item]
            current_length = item_len
        else:
            current_chunk.append(item)
            current_length += item_len

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def hierarchical_reduce_summaries(
    items: List[str],
    category_title: str,
    llm_client: Optional[LLMClient],
    language: str = "English",
    allow_fallback: bool = False,
    max_items_per_chunk: int = 15,
    max_chars_per_chunk: int = 3500,
    depth: int = 0,
) -> str:
    """Recursively reduce a large list of item descriptions into a concise summary fitting in 16K context."""
    if not items:
        return "(None)"

    total_len = sum(len(it) for it in items)
    if (len(items) <= max_items_per_chunk and total_len <= max_chars_per_chunk) or depth > 5:
        return "\n".join(items)

    chunks = chunk_list_by_size(items, max_items=max_items_per_chunk, max_chars=max_chars_per_chunk)
    if len(chunks) <= 1 and depth > 0:
        return "\n".join(items)

    intermediate_summaries: List[str] = []

    for idx, chunk in enumerate(chunks, 1):
        chunk_text = "\n".join(chunk)
        if not llm_client:
            intermediate_summaries.append(f"- [Group {idx}]: " + " / ".join(c[:60] for c in chunk[:5]))
            continue

        prompt = f"""Please analyze the following {category_title} (Group {idx}/{len(chunks)}) and create a concise intermediate summary (300-500 words) in {language} for system-level architecture analysis.
Output Language: {language} (Write all summary text in {language}).

### Target Items:
{chunk_text}

Output as Markdown bullet points in {language}:"""

        messages = [
            {"role": "system", "content": f"You are a principal software architect. You output concise summaries in {language}."},
            {"role": "user", "content": prompt},
        ]

        try:
            summary = llm_client.chat_completion(messages)
            intermediate_summaries.append(f"#### Group {idx} Summary\n{summary.strip()}")
        except Exception as e:
            if not allow_fallback:
                raise LLMError(f"Failed intermediate summary for {category_title} (Group {idx}): {e}") from e
            intermediate_summaries.append(f"- Group {idx}: {chunk_text[:300]}")

    if len(intermediate_summaries) < len(items) and (len(intermediate_summaries) > max_items_per_chunk or sum(len(s) for s in intermediate_summaries) > max_chars_per_chunk):
        return hierarchical_reduce_summaries(
            intermediate_summaries,
            category_title,
            llm_client,
            language=language,
            allow_fallback=allow_fallback,
            max_items_per_chunk=max_items_per_chunk,
            max_chars_per_chunk=max_chars_per_chunk,
            depth=depth + 1,
        )

    return "\n\n".join(intermediate_summaries)


def generate_data_models_doc(
    type_docs: List[Dict[str, Any]],
    var_docs: List[Dict[str, Any]],
    llm_client: Optional[LLMClient],
    target_dir: Path,
    db: Optional[DocgenDB] = None,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
) -> str:
    """Step 1: Generate .docgen/design/data_models.md with SQLite caching and Map-Reduce."""
    norm_lang = normalize_language(language)
    types_raw = [f"- Type `{d['file_name']}` (Signature: `{d['signature']}`): {d['purpose'][:150]}" for d in type_docs]
    vars_raw = [f"- Variable/Field `{d['file_name']}` (Type: `{d['signature']}`): {d['purpose'][:120]}" for d in var_docs]

    combined_input = f"{norm_lang}\n" + "\n".join(types_raw + vars_raw)
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"design::data_models::{norm_lang}"
    out_file = target_dir / ".docgen" / "design" / "data_models.md"

    if db and not force:
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            print("  [Cached]: .docgen/design/data_models.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    reduced_types_summary = hierarchical_reduce_summaries(
        types_raw,
        "Type Definitions",
        llm_client,
        language=norm_lang,
        allow_fallback=allow_fallback,
    )
    reduced_vars_summary = hierarchical_reduce_summaries(
        vars_raw,
        "Variables and Fields",
        llm_client,
        language=norm_lang,
        allow_fallback=allow_fallback,
    )

    prompt = f"""Please analyze the aggregated type definitions and variables/fields, and create a comprehensive "Data Models & Data Structure Design" document in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).

### Defined Types:
{reduced_types_summary}

### Defined Variables & Fields:
{reduced_vars_summary}

Structure the Markdown as follows:
# Data Structure Design & Data Models

## 1. Design Intent & Core Philosophy
(Explain overall data architecture philosophy and domain abstractions)

## 2. Core Data Structures
(Table/list of structs, classes, enums with their responsibilities and rationale)

## 3. Data Lifecycle & Passing Flow
(Lifecycle explanation: creation, propagation between functions, and mutation/destruction)

## 4. Data Integrity & Invariants
(Constraints, valid state transitions, and concurrency guarantees)
"""

    messages = [
        {"role": "system", "content": f"You are a principal software architect. Write detailed architectural documentation in {norm_lang}."},
        {"role": "user", "content": prompt},
    ]

    try:
        content = llm_client.chat_completion(messages) if llm_client else "# Data Structure Design & Data Models\n\n## 1. Design Intent & Core Philosophy\nProvides core data structure definitions.\n"
    except Exception as e:
        if not allow_fallback:
            raise LLMError(f"Failed to generate data models document: {e}") from e
        content = "# Data Structure Design & Data Models\n\n## 1. Design Intent & Core Philosophy\nProvides core data structure definitions.\n"

    elapsed = time.time() - start_t
    print(f"       -> [Done in {elapsed:5.1f}s]: .docgen/design/data_models.md")

    write_flushed_text(out_file, content.strip() + "\n")
    if db:
        db.save_design_cache(cache_key, input_hash, content)
    return content


def generate_execution_model_doc(
    fn_docs: List[Dict[str, Any]],
    llm_client: Optional[LLMClient],
    target_dir: Path,
    db: Optional[DocgenDB] = None,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
) -> str:
    """Step 2: Generate .docgen/design/execution_model.md with SQLite caching and Map-Reduce."""
    norm_lang = normalize_language(language)
    funcs_raw = []
    for d in fn_docs:
        callees_str = ", ".join(d["callees"][:3]) if d["callees"] else "None"
        funcs_raw.append(f"- Function `{d['file_name']}` (Signature: `{d['signature']}`): Purpose: {d['purpose'][:120]} / Callees: {callees_str}")

    combined_input = f"{norm_lang}\n" + "\n".join(funcs_raw)
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"design::execution_model::{norm_lang}"
    out_file = target_dir / ".docgen" / "design" / "execution_model.md"

    if db and not force:
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            print("  [Cached]: .docgen/design/execution_model.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    reduced_funcs_summary = hierarchical_reduce_summaries(
        funcs_raw,
        "Function Call Structures",
        llm_client,
        language=norm_lang,
        allow_fallback=allow_fallback,
    )

    prompt = f"""Please analyze the function call graphs and create a comprehensive "System Execution Model & Runtime Architecture" document in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).

### Function Call Structures:
{reduced_funcs_summary}

Structure the Markdown as follows:
# System Execution Model & Runtime Architecture

## 1. Design Intent & Execution Paradigm
(Overall runtime model, execution paradigm, and design rationale)

## 2. Architectural Patterns
(Event-driven, batch execution, pipeline, client-server, or main-loop patterns)

## 3. Control Flow from Entry Point to Termination
(System bootstrap, initialization, dispatching, and teardown flow)

## 4. Concurrency, Asynchrony & Error Resilience
(Thread-safety, async I/O, error recovery, and failure modes)
"""

    messages = [
        {"role": "system", "content": f"You are a principal software architect. Write detailed architectural documentation in {norm_lang}."},
        {"role": "user", "content": prompt},
    ]

    try:
        content = llm_client.chat_completion(messages) if llm_client else "# System Execution Model & Runtime Architecture\n\n## 1. Design Intent & Execution Paradigm\nProvides system execution flow.\n"
    except Exception as e:
        if not allow_fallback:
            raise LLMError(f"Failed to generate execution model document: {e}") from e
        content = "# System Execution Model & Runtime Architecture\n\n## 1. Design Intent & Execution Paradigm\nProvides system execution flow.\n"

    elapsed = time.time() - start_t
    print(f"       -> [Done in {elapsed:5.1f}s]: .docgen/design/execution_model.md")

    write_flushed_text(out_file, content.strip() + "\n")
    if db:
        db.save_design_cache(cache_key, input_hash, content)
    return content


def generate_module_docs(
    modules: Dict[str, List[Dict[str, Any]]],
    llm_client: Optional[LLMClient],
    target_dir: Path,
    db: Optional[DocgenDB] = None,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
) -> Dict[str, str]:
    """Step 3: Generate .docgen/design/modules/<module_name>.md with SQLite caching per module."""
    norm_lang = normalize_language(language)
    module_summaries = {}

    for mod_name, docs in modules.items():
        doc_lines = [f"- `{d['file_name']}` ({d['kind']}): {d['purpose'][:120]}" for d in docs]
        combined_input = f"{norm_lang}\n" + "\n".join(doc_lines)
        input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
        cache_key = f"design::module::{mod_name}::{norm_lang}"
        out_file = target_dir / ".docgen" / "design" / "modules" / f"{mod_name}.md"

        if db and not force:
            cached_content = db.load_design_cache(cache_key, input_hash)
            if cached_content:
                print(f"    [Cached]: .docgen/design/modules/{mod_name}.md")
                write_flushed_text(out_file, cached_content.strip() + "\n")
                module_summaries[mod_name] = cached_content
                continue

        start_t = time.time()
        reduced_module_elements = hierarchical_reduce_summaries(
            doc_lines,
            f"Module `{mod_name}` Elements",
            llm_client,
            language=norm_lang,
            allow_fallback=allow_fallback,
        )

        prompt = f"""Please analyze the elements in module `{mod_name}` and create a comprehensive module design document in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).

### Module Name: `{mod_name}`
### Module Elements:
{reduced_module_elements}

Structure the Markdown as follows:
# Module Design: `{mod_name}`

## 1. Design Intent & Responsibilities
(Core responsibilities and rationale for module `{mod_name}`)

## 2. Public Interfaces & Provided Capabilities
(Public functions, classes, types, and exported symbols)

## 3. Internal Architecture & Data Flow
(Internal data transformation and computation pipelines)

## 4. Dependencies & Interactions
(Interactions with upstream and downstream modules)
"""

        messages = [
            {"role": "system", "content": f"You are a principal software architect. Write clean module documentation in {norm_lang}."},
            {"role": "user", "content": prompt},
        ]

        try:
            content = llm_client.chat_completion(messages) if llm_client else f"# Module Design: `{mod_name}`\n\n## 1. Design Intent & Responsibilities\nProvides capabilities for `{mod_name}`.\n"
        except Exception as e:
            if not allow_fallback:
                raise LLMError(f"Failed to generate module `{mod_name}` document: {e}") from e
            content = f"# Module Design: `{mod_name}`\n\n## 1. Design Intent & Responsibilities\nProvides capabilities for `{mod_name}`.\n"

        elapsed = time.time() - start_t
        print(f"         -> [Done in {elapsed:5.1f}s]: .docgen/design/modules/{mod_name}.md")

        write_flushed_text(out_file, content.strip() + "\n")
        if db:
            db.save_design_cache(cache_key, input_hash, content)
        module_summaries[mod_name] = content

    return module_summaries


def generate_overview_doc(
    data_models_content: str,
    execution_model_content: str,
    module_summaries: Dict[str, str],
    llm_client: Optional[LLMClient],
    target_dir: Path,
    db: Optional[DocgenDB] = None,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
) -> str:
    """Step 4: Generate .docgen/design/overview.md with SQLite caching and Mermaid synthesis."""
    norm_lang = normalize_language(language)
    mod_lines = []
    for mod_name, content in module_summaries.items():
        first_lines = " / ".join(line.strip() for line in content.strip().splitlines()[:5] if line.strip() and not line.startswith("#"))
        mod_lines.append(f"- Module `{mod_name}`: {first_lines[:150]}")

    combined_input = f"{norm_lang}\n{data_models_content[:600]}\n{execution_model_content[:600]}\n" + "\n".join(mod_lines)
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"design::overview::{norm_lang}"
    out_file = target_dir / ".docgen" / "design" / "overview.md"

    if db and not force:
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            print("  [Cached]: .docgen/design/overview.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    reduced_modules_overview = hierarchical_reduce_summaries(
        mod_lines,
        "All Modules Overview",
        llm_client,
        language=norm_lang,
        allow_fallback=allow_fallback,
    )

    prompt = f"""Please synthesize the overall system architecture overview document in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).

### Data Models Summary:
{data_models_content[:600]}

### Execution Model Summary:
{execution_model_content[:600]}

### Modules Overview:
{reduced_modules_overview}

Requirements:
1. Section "## 1. Architectural Overview & Design Philosophy" at the top.
2. Include a clean **Mermaid Diagram (```mermaid ... ```)** illustrating inter-module data flow.
3. Link index to detail documents ([Data Models](data_models.md), [Execution Model](execution_model.md), [Module Designs](modules/)).
"""

    messages = [
        {"role": "system", "content": f"You are a principal software architect. Write clean overview documentation with Mermaid diagrams in {norm_lang}."},
        {"role": "user", "content": prompt},
    ]

    try:
        content = llm_client.chat_completion(messages) if llm_client else "# System Architecture Overview\n\n## 1. Architectural Overview & Design Philosophy\nProvides overall system architectural design.\n"
    except Exception as e:
        if not allow_fallback:
            raise LLMError(f"Failed to generate overview document: {e}") from e
        content = "# System Architecture Overview\n\n## 1. Architectural Overview & Design Philosophy\nProvides overall system architectural design.\n"

    elapsed = time.time() - start_t
    print(f"       -> [Done in {elapsed:5.1f}s]: .docgen/design/overview.md")

    write_flushed_text(out_file, content.strip() + "\n")
    if db:
        db.save_design_cache(cache_key, input_hash, content)
    return content


def run_design_generation(
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
) -> int:
    """Main pipeline for synthesizing .docgen/design/ documents with SQLite caching and hierarchical Map-Reduce."""
    target_dir = target_dir.resolve()
    norm_lang = normalize_language(language)
    docs_dir = target_dir / ".docgen" / "documents"

    if not docs_dir.exists():
        print(f"Error: .docgen/documents/ does not exist. Run docgen first: {docs_dir}", file=sys.stderr)
        return 1

    print(f"=== designgen Started (Lang: {norm_lang}, SQLite Caching & Map-Reduce Enabled): {target_dir} ===")

    db_path = target_dir / ".docgen" / "index.db"
    db = DocgenDB(db_path)

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
            print(f"[LLM] Connected to server: {client.base_url} (model: {client.model}, context: {client.context_size}{auth_info})")
        else:
            if not allow_fallback:
                print(f"Error: Failed to connect to LLM server ({client.base_url}). Aborting without --allow-fallback.", file=sys.stderr)
                db.close()
                return 1
            else:
                print(f"[LLM Warning] LLM server unreachable ({client.base_url}). Fallback to static templates.")

    all_md_files = list(docs_dir.glob("*.md")) + list(docs_dir.glob("**/*.md"))
    all_md_files = sorted(list(set(all_md_files)))

    parsed_docs = [parse_symbol_doc(f) for f in all_md_files if f.is_file()]
    print(f"[1/5] Loaded parsed documents: {len(parsed_docs)} items")

    type_docs = [d for d in parsed_docs if ".type." in d["file_name"] or d["kind"] in ("struct", "class", "enum")]
    var_docs = [d for d in parsed_docs if ".var." in d["file_name"] or d["kind"] in ("variable", "field")]
    fn_docs = [d for d in parsed_docs if ".fn." in d["file_name"] or d["kind"] in ("function", "method")]

    # Step 1
    print(f"[2/5] Step 1/4: Synthesizing core data models -> .docgen/design/data_models.md")
    data_models_content = generate_data_models_doc(
        type_docs=type_docs,
        var_docs=var_docs,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
    )

    # Step 2
    print(f"[3/5] Step 2/4: Identifying system execution model -> .docgen/design/execution_model.md")
    execution_model_content = generate_execution_model_doc(
        fn_docs=fn_docs,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
    )

    # Step 3
    modules = group_docs_by_module(parsed_docs)
    total_mods = len(modules)
    print(f"[4/5] Step 3/4: Deriving module relationships and interfaces (Total {total_mods} modules)...")

    module_summaries = generate_module_docs(
        modules=modules,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
    )

    # Step 4
    print(f"[5/5] Step 4/4: Synthesizing architecture overview & Mermaid diagrams -> .docgen/design/overview.md")
    generate_overview_doc(
        data_models_content=data_models_content,
        execution_model_content=execution_model_content,
        module_summaries=module_summaries,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
    )

    db.close()
    print("=== designgen Finished: Successfully built design documentation ===")
    return 0
