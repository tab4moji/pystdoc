"""Design Engine: Synthesizes high-level architectural documents."""

import hashlib
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from pystdoc.cache import write_flushed_text
from pystdoc.db import DocgenDB
from pystdoc.doc_writer import normalize_language
from pystdoc.llm_client import LLMClient, LLMError
from pystdoc.progress import PhaseProgressTracker, is_terminal
from pystdoc.ui_detector import (
    annotate_documents_with_ui_context,
    detect_ui_type,
)


def parse_symbol_doc(md_path: Path) -> Dict[str, Any]:

    """Parse key sections from an individual symbol or file markdown doc."""
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
        "ui_role": "",
        "raw_text": text,
    }

    m_title = re.search(r"^# (.+)$", text, re.MULTILINE)
    if m_title:
        data["title"] = m_title.group(1).strip()

    # 1. Extract Top-Down / Bottom-Up prose from the top or fallback
    m_prose = re.search(r"^# [^\n]+\n+([^#\s][\s\S]*?)(?=\n## |\Z)", text)
    if m_prose and m_prose.group(1).strip():
        data["context"] = m_prose.group(1).strip()
        data["purpose"] = data["context"]
    else:
        m_legacy = re.search(
            r"## 1\..*\n([\s\S]*?)(?=\n## 2\.|\Z)",
            text,
        )
        if m_legacy:
            data["context"] = m_legacy.group(1).strip()
            data["purpose"] = data["context"]

    # 2. Extract Kind & Signature
    m_kind = re.search(
        r"- \*\*(?:Symbol Kind|Kind)[^*]*\*\*:\s*`?([^`\n]+)`?",
        text,
        re.IGNORECASE,
    )
    if m_kind:
        data["kind"] = m_kind.group(1).strip()

    m_sig = re.search(
        r"- \*\*(?:Signature|Type)[^*]*\*\*:\s*`?([^`\n]+)`?",
        text,
        re.IGNORECASE,
    )
    if m_sig:
        data["signature"] = m_sig.group(1).strip()

    # 3. Extract Callees & Referencing Functions
    m_callees = re.search(
        r"## \d+\..*Called Functions.*\n([\s\S]*?)(?=\n## |\Z)",
        text,
        re.IGNORECASE,
    )
    if m_callees:
        callee_lines = re.findall(r"- `([^`]+)`", m_callees.group(1))
        data["callees"] = [
            c for c in callee_lines if c not in ("None", "none")
        ]

    m_refs = re.search(
        r"## \d+\..*(?:Referencing Functions|References).*\n"
        r"([\s\S]*?)(?=\n## |\Z)",
        text,
        re.IGNORECASE,
    )
    if m_refs:
        ref_lines = re.findall(r"- `([^`]+)`", m_refs.group(1))
        data["referencing_funcs"] = [
            r for r in ref_lines if r not in ("None", "none")
        ]

    # 4. Extract UI & Interaction Role
    m_ui = re.search(
        r"## .*(?:UI & Interaction Role|UI・ユーザー操作における役割).*\n"
        r"([\s\S]*?)(?=\n## |\Z)",
        text,
        re.IGNORECASE,
    )
    if m_ui:
        data["ui_role"] = m_ui.group(1).strip()

    return data


def group_docs_by_module(
    docs: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group documents into logical modules based on directory paths."""
    modules = defaultdict(list)
    common_files = (
        "client.py", "service.py", "math.c", "math.h", "types.h", "run.sh"
    )
    for d in docs:
        filename = d["file_name"]
        clean_name = re.sub(r"\.(fn|var|type|const)\..*$", "", filename)
        clean_name = re.sub(r"\.md$", "", clean_name)

        parts = clean_name.split("/")
        if len(parts) > 1:
            mod_name = (
                parts[-2]
                if parts[-1] in common_files
                else parts[0]
            )
            if mod_name in ("src", "include", "scripts"):
                mod_name = (
                    parts[1] if len(parts) > 2 else parts[-1].split(".")[0]
                )
        else:
            base = parts[0].split(".")[0]
            mod_name = "main" if base in ("main", "app") else base

        modules[mod_name].append(d)
    return dict(modules)


def chunk_list_by_size(
    items: List[str], max_items: int = 15, max_chars: int = 3500
) -> List[List[str]]:
    """Split a list of string items into size-constrained chunks."""
    chunks: List[List[str]] = []
    current_chunk: List[str] = []
    current_length = 0

    for item in items:
        item_len = len(item)
        if (
            len(current_chunk) >= max_items
            or (current_length + item_len > max_chars)
        ) and current_chunk:
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
    """Recursively reduce descriptions into a concise summary."""
    if not items:
        return "(None)"

    total_len = sum(len(it) for it in items)
    if (
        len(items) <= max_items_per_chunk and total_len <= max_chars_per_chunk
    ) or depth > 5:
        return "\n".join(items)

    chunks = chunk_list_by_size(
        items, max_items=max_items_per_chunk, max_chars=max_chars_per_chunk
    )
    if len(chunks) <= 1 and depth > 0:
        return "\n".join(items)

    intermediate_summaries: List[str] = []

    for idx, chunk in enumerate(chunks, 1):
        chunk_text = "\n".join(chunk)
        if not llm_client:
            summary_item = (
                f"- [Group {idx}]: "
                + " / ".join(c[:60] for c in chunk[:5])
            )
            intermediate_summaries.append(summary_item)
            continue

        grp_info = f"(Group {idx}/{len(chunks)})"
        prompt = f"""Please analyze {category_title} {grp_info}
and create a concise, factual summary (200-400 words) in {language}.
Output Language: {language} (Write all summary text in {language}).
Tone rule: Strictly objective, concise, and architectural. Absolutely NO
promotional words, praise, or marketing fluff. State concrete
architectural patterns, roles, and data flow directly.

### Target Items:
{chunk_text}

Output as Markdown bullet points in {language}:"""

        sys_msg = (
            f"You are an objective software architect. "
            f"You output concise, strictly factual summaries in {language}."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        try:
            summary = llm_client.chat_completion(messages)
            intermediate_summaries.append(
                f"#### Group {idx} Summary\n{summary.strip()}"
            )
        except Exception as e:
            if not allow_fallback:
                raise LLMError(
                    f"Failed intermediate summary for "
                    f"{category_title} (Group {idx}): {e}"
                ) from e
            intermediate_summaries.append(
                f"- Group {idx}: {chunk_text[:300]}"
            )

    if len(intermediate_summaries) < len(items) and (
        len(intermediate_summaries) > max_items_per_chunk
        or sum(len(s) for s in intermediate_summaries) > max_chars_per_chunk
    ):
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
    tracker: Optional[PhaseProgressTracker] = None,
) -> str:
    """Step 1: Generate data_models.md with SQLite cache & Map-Reduce."""
    norm_lang = normalize_language(language)
    types_raw = [
        f"- Type `{d['file_name']}` (Signature: `{d['signature']}`): "
        f"{d['purpose'][:150]}"
        for d in type_docs
    ]
    vars_raw = [
        f"- Variable/Field `{d['file_name']}` (Type: `{d['signature']}`): "
        f"{d['purpose'][:120]}"
        for d in var_docs
    ]

    combined_input = f"{norm_lang}\n" + "\n".join(types_raw + vars_raw)
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"design::data_models::{norm_lang}"
    out_file = target_dir / ".docgen" / "design" / "data_models.md"

    if db and not force and out_file.exists():
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            if tracker:
                tracker.advance(1, extra="[Cached]: data_models.md")
            else:
                print("  [Cached]: .docgen/design/data_models.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    if tracker:
        tracker.render_current(extra="data_models.md")

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

    prompt = f"""Please analyze aggregated types and variables/fields,
and create a factual "Data Models & Data Structure Design" doc in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).
Tone rule: Strictly objective, concise, and architectural. Absolutely NO
promotional words, praise, or marketing fluff (e.g., avoid "robust",
"flexible", "powerful", "cutting-edge", "優れた", "堅牢な"). State concrete
data structures, their responsibilities, and how data moves through the system.

### Defined Types:
{reduced_types_summary}

### Defined Variables & Fields:
{reduced_vars_summary}

Structure the Markdown as follows:
# Data Structure Design & Data Models

## 1. Architectural Role & Design Intent
(Concise 2-3 sentences: what domain models exist and their concrete role)

## 2. Core Data Structures
(Table/bullets of structs/classes/enums with fields and factual roles)

## 3. Data Lifecycle & Flow
(Factual flow: instantiation, mutations, parameter passing, and cleanup)

## 4. Constraints & State Invariants
(Concrete validations, state constraints, and concurrency rules)
"""

    default_data_models = (
        "# Data Structure Design & Data Models\n\n"
        "## 1. Architectural Role & Design Intent\n"
        "Provides core data structure definitions and domain models.\n"
    )
    sys_msg = (
        f"You are an objective software architect. "
        f"Write concise, strictly factual architectural "
        f"documentation in {norm_lang}."
    )
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": prompt},
    ]

    try:
        content = (
            llm_client.chat_completion(messages)
            if llm_client
            else default_data_models
        )
    except Exception as e:
        if not allow_fallback:
            raise LLMError(
                f"Failed to generate data models document: {e}"
            ) from e
        content = default_data_models

    elapsed = time.time() - start_t
    if tracker:
        tracker.advance(
            1,
            extra=".docgen/design/data_models.md",
            elapsed=elapsed,
        )
    else:
        print(
            f"       -> [Done in {elapsed:5.1f}s]: "
            ".docgen/design/data_models.md"
        )

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
    ui_info: Optional[Dict[str, Any]] = None,
    tracker: Optional[PhaseProgressTracker] = None,
) -> str:
    """Step 2: Generate execution_model.md with SQLite cache & Map-Reduce."""
    norm_lang = normalize_language(language)
    funcs_raw = []
    for d in fn_docs:
        callees_str = ", ".join(d["callees"][:3]) if d["callees"] else "None"
        ui_extra = f" / UI Role: {d['ui_role']}" if d.get("ui_role") else ""
        line_desc = (
            f"- Function `{d['file_name']}` (Signature: `{d['signature']}`): "
            f"Purpose: {d['purpose'][:120]}{ui_extra} / Callees: {callees_str}"
        )
        funcs_raw.append(line_desc)

    combined_input = f"{norm_lang}\n" + "\n".join(funcs_raw)
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"design::execution_model::{norm_lang}"
    out_file = target_dir / ".docgen" / "design" / "execution_model.md"

    if db and not force and out_file.exists():
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            if tracker:
                tracker.advance(
                    1, extra="[Cached]: execution_model.md"
                )
            else:
                print("  [Cached]: .docgen/design/execution_model.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    if tracker:
        tracker.render_current(extra="execution_model.md")

    reduced_funcs_summary = hierarchical_reduce_summaries(
        funcs_raw,
        "Function Call Structures",
        llm_client,
        language=norm_lang,
        allow_fallback=allow_fallback,
    )

    ui_context_text = ""
    if ui_info and ui_info.get("has_ui"):
        ui_t = ui_info.get("ui_type", "CLI")
        ui_f = ui_info.get("framework", "")
        ui_context_text = (
            f"\n### Detected UI & Interaction Framework:\n"
            f"- User Interface Type: `{ui_t}` ({ui_f})\n"
            f"- Account for user interactions, input dispatching, and UI "
            f"lifecycle.\n"
        )

    prompt = f"""Please analyze function call graphs and create
a factual "System Execution Model & Runtime Architecture" in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).
Tone rule: Strictly objective, concise, and architectural. Absolutely NO
promotional words, praise, or marketing fluff (e.g., avoid "robust",
"flexible", "seamless", "cutting-edge", "優れた", "堅牢な"). State the
concrete runtime execution pattern, entry points, dispatching, and flow.
{ui_context_text}
### Function Call Structures:
{reduced_funcs_summary}

Structure the Markdown as follows:
# System Execution Model & Runtime Architecture

## 1. Runtime Architecture Pattern
(Concise 2-3 sentences: identify concrete pattern e.g. MVVM, Event-Driven)

## 2. Execution Flow from Entry Point to Termination
(Step-by-step sequence: startup, initialization, main loop, and teardown)

## 3. Concurrency, Asynchrony & Lifecycle
(Concrete thread model, coroutines/async tasks, and cleanup handling)

## 4. Error Handling & Failure Modes
(Exception propagation, error returns, recovery, and failure boundaries)
"""

    default_exec_model = (
        "# System Execution Model & Runtime Architecture\n\n"
        "## 1. Runtime Architecture Pattern\n"
        "Provides system execution flow and runtime architecture.\n"
    )
    sys_msg = (
        f"You are an objective software architect. "
        f"Write concise, strictly factual execution model "
        f"documentation in {norm_lang}."
    )
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": prompt},
    ]

    try:
        content = (
            llm_client.chat_completion(messages)
            if llm_client
            else default_exec_model
        )
    except Exception as e:
        if not allow_fallback:
            raise LLMError(
                f"Failed to generate execution model document: {e}"
            ) from e
        content = default_exec_model

    elapsed = time.time() - start_t
    if tracker:
        tracker.advance(
            1,
            extra=".docgen/design/execution_model.md",
            elapsed=elapsed,
        )
    else:
        print(
            f"       -> [Done in {elapsed:5.1f}s]: "
            ".docgen/design/execution_model.md"
        )

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
    tracker: Optional[PhaseProgressTracker] = None,
) -> Dict[str, str]:
    """Step 3: Generate module docs with SQLite caching per module."""
    norm_lang = normalize_language(language)
    module_summaries = {}

    for mod_name, docs in modules.items():
        doc_lines = [
            f"- `{d['file_name']}` ({d['kind']}): {d['purpose'][:120]}"
            for d in docs
        ]
        combined_input = f"{norm_lang}\n" + "\n".join(doc_lines)
        input_hash = hashlib.sha256(
            combined_input.encode("utf-8")
        ).hexdigest()
        cache_key = f"design::module::{mod_name}::{norm_lang}"
        out_file = (
            target_dir
            / ".docgen"
            / "design"
            / "modules"
            / f"{mod_name}.md"
        )

        if db and not force and out_file.exists():
            cached_content = db.load_design_cache(cache_key, input_hash)
            if cached_content:
                if tracker:
                    tracker.advance(
                        1, extra=f"[Cached]: modules/{mod_name}.md"
                    )
                else:
                    print(
                        f"    [Cached]: .docgen/design/modules/{mod_name}.md"
                    )
                write_flushed_text(out_file, cached_content.strip() + "\n")
                module_summaries[mod_name] = cached_content
                continue

        start_t = time.time()
        if tracker:
            tracker.render_current(extra=f"modules/{mod_name}.md")
        reduced_module_elements = hierarchical_reduce_summaries(
            doc_lines,
            f"Module `{mod_name}` Elements",
            llm_client,
            language=norm_lang,
            allow_fallback=allow_fallback,
        )

        prompt = f"""Please analyze elements in module `{mod_name}`
and create a concise, factual module design in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).
Tone rule: Strictly objective, concise, and architectural. Absolutely NO
promotional words, praise, or marketing fluff. State the module's exact
responsibilities, public interfaces, and component interactions directly.

### Module Name: `{mod_name}`
### Module Elements:
{reduced_module_elements}

Structure the Markdown as follows:
# Module Design: `{mod_name}`

## 1. Module Responsibility & Role
(Concise 2-3 sentences: what concrete responsibility this module has)

## 2. Public Interfaces & Exported Symbols
(List/table of public functions, classes, and types with their exact roles)

## 3. Internal Data Flow & Processing
(Factual flow of data processing and state transformation in this module)

## 4. Dependencies & Inter-Module Interactions
(Direct dependencies: upstream caller modules and downstream callee modules)
"""

        default_mod_doc = (
            f"# Module Design: `{mod_name}`\n\n"
            "## 1. Module Responsibility & Role\n"
            f"Defines responsibilities and public interfaces for "
            f"module `{mod_name}`.\n"
        )
        sys_msg = (
            f"You are an objective software architect. "
            f"Write concise, strictly factual module "
            f"documentation in {norm_lang}."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        try:
            content = (
                llm_client.chat_completion(messages)
                if llm_client
                else default_mod_doc
            )
        except Exception as e:
            if not allow_fallback:
                raise LLMError(
                    f"Failed to generate module `{mod_name}` document: {e}"
                ) from e
            content = default_mod_doc

        elapsed = time.time() - start_t
        if tracker:
            tracker.advance(
                1,
                extra=f".docgen/design/modules/{mod_name}.md",
                elapsed=elapsed,
            )
        else:
            print(
                f"         -> [Done in {elapsed:5.1f}s]: "
                f".docgen/design/modules/{mod_name}.md"
            )

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
    ui_info: Optional[Dict[str, Any]] = None,
    tracker: Optional[PhaseProgressTracker] = None,
) -> str:
    """Step 4: Generate overview.md with SQLite cache & Mermaid synthesis."""
    norm_lang = normalize_language(language)
    mod_lines = []
    for mod_name, content in module_summaries.items():
        first_lines = " / ".join(
            line.strip()
            for line in content.strip().splitlines()[:5]
            if line.strip() and not line.startswith("#")
        )
        mod_lines.append(f"- Module `{mod_name}`: {first_lines[:150]}")

    combined_input = (
        f"{norm_lang}\n{data_models_content[:600]}\n"
        f"{execution_model_content[:600]}\n"
        + "\n".join(mod_lines)
    )
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"design::overview::{norm_lang}"
    out_file = target_dir / ".docgen" / "design" / "overview.md"

    if db and not force and out_file.exists():
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            if tracker:
                tracker.advance(1, extra="[Cached]: overview.md")
            else:
                print("  [Cached]: .docgen/design/overview.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    if tracker:
        tracker.render_current(extra="overview.md")
    reduced_modules_overview = hierarchical_reduce_summaries(
        mod_lines,
        "All Modules Overview",
        llm_client,
        language=norm_lang,
        allow_fallback=allow_fallback,
    )

    ui_overview_text = ""
    if ui_info and ui_info.get("has_ui"):
        ui_overview_text = (
            f"\n### User Interface Structure:\n"
            f"- Primary UI Pattern: `{ui_info.get('ui_type')}` "
            f"({ui_info.get('framework')})\n"
            f"- Reflect user interaction layer in Mermaid diagram and "
            f"overview.\n"
        )

    prompt = f"""Please synthesize a concise architecture overview
in {norm_lang}.
Output Language: {norm_lang} (Write all text in {norm_lang}).
Tone rule: Strictly objective, concise, and architectural. Absolutely NO
promotional words, praise, or marketing fluff (e.g., avoid "robust",
"flexible", "powerful", "cutting-edge", "優れた", "堅牢な", "高度な").
Clearly and concisely state the overall architecture pattern (e.g. MVVM,
Layered, Pipeline, Clean Architecture), component roles, and interactions.
{ui_overview_text}
### Data Models Summary:
{data_models_content[:600]}

### Execution Model Summary:
{execution_model_content[:600]}

### Modules Overview:
{reduced_modules_overview}

Requirements:
1. Section "## 1. Architecture Pattern & System Overview" at the top
   (Concise summary of architecture pattern and core layers/components).
2. Include a clean Mermaid Diagram (```mermaid ... ```) depicting the
   actual component architecture and data/control flow.
3. Link index to details (data_models.md, execution_model.md, modules/).
"""

    default_overview = (
        "# System Architecture Overview\n\n"
        "## 1. Architecture Pattern & System Overview\n"
        "Provides overall system architectural design and component "
        "structure.\n"
    )
    sys_msg = (
        f"You are an objective software architect. "
        f"Write concise, strictly factual overview documentation "
        f"with Mermaid in {norm_lang}."
    )
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": prompt},
    ]

    try:
        content = (
            llm_client.chat_completion(messages)
            if llm_client
            else default_overview
        )
    except Exception as e:
        if not allow_fallback:
            raise LLMError(
                f"Failed to generate overview document: {e}"
            ) from e
        content = default_overview

    elapsed = time.time() - start_t
    if tracker:
        tracker.advance(
            1,
            extra=".docgen/design/overview.md",
            elapsed=elapsed,
        )
    else:
        print(
            f"       -> [Done in {elapsed:5.1f}s]: "
            ".docgen/design/overview.md"
        )

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
    is_tty: Optional[bool] = None,
) -> int:
    """Main pipeline for synthesizing .docgen/design/ documents."""
    target_dir = target_dir.resolve()
    norm_lang = normalize_language(language)
    if is_tty is None:
        is_tty = is_terminal(sys.stdout)
    docs_dir = target_dir / ".docgen" / "documents"

    if not docs_dir.exists():
        print(
            f"Error: .docgen/documents/ does not exist: {docs_dir}",
            file=sys.stderr,
        )
        return 1

    print(
        f"=== designgen Started (Lang: {norm_lang}, "
        f"SQLite Caching & Map-Reduce Enabled): {target_dir} ==="
    )

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
            print(
                f"[LLM] Connected to server: {client.base_url} "
                f"(model: {client.model}, "
                f"context: {client.context_size}{auth_info})"
            )
        else:
            if not allow_fallback:
                print(
                    f"Error: Failed to connect to LLM server "
                    f"({client.base_url}). Aborting without --allow-fallback.",
                    file=sys.stderr,
                )
                db.close()
                return 1
            else:
                print(
                    f"[LLM Warning] LLM server unreachable "
                    f"({client.base_url}). Fallback to static templates."
                )

    all_md_files = (
        list(docs_dir.glob("*.md")) + list(docs_dir.glob("**/*.md"))
    )
    all_md_files = sorted(list(set(all_md_files)))

    parsed_docs = [parse_symbol_doc(f) for f in all_md_files if f.is_file()]
    print(f"[1/5] Loaded parsed documents: {len(parsed_docs)} items")

    # Bottom-up UI inference & symbol doc annotation
    ui_info = detect_ui_type(parsed_docs)
    annotated = annotate_documents_with_ui_context(
        docs_dir, ui_info, language=norm_lang
    )
    if annotated > 0:
        parsed_docs = [
            parse_symbol_doc(f) for f in all_md_files if f.is_file()
        ]
        print(
            f"       -> [UI Context Bottom-Up Annotated]: "
            f"{ui_info['ui_type']} ({ui_info['framework']}) "
            f"across {annotated} symbol docs"
        )

    type_docs = [
        d
        for d in parsed_docs
        if ".type." in d["file_name"]
        or d["kind"] in ("struct", "class", "enum")
    ]
    var_docs = [
        d
        for d in parsed_docs
        if ".var." in d["file_name"] or d["kind"] in ("variable", "field")
    ]
    fn_docs = [
        d
        for d in parsed_docs
        if ".fn." in d["file_name"] or d["kind"] in ("function", "method")
    ]

    modules = group_docs_by_module(parsed_docs)
    total_mods = len(modules)
    total_design_steps = 1 + 1 + total_mods + 1
    tracker = PhaseProgressTracker(
        phase_label="Step 3/4 designgen",
        total=total_design_steps,
        is_tty=is_tty,
    )

    # Step 1: Synthesize core data models
    data_models_content = generate_data_models_doc(
        type_docs=type_docs,
        var_docs=var_docs,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
        tracker=tracker,
    )

    # Step 2: Identify system execution model
    execution_model_content = generate_execution_model_doc(
        fn_docs=fn_docs,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
        ui_info=ui_info,
        tracker=tracker,
    )

    # Step 3: Derive module relationships and interfaces
    module_summaries = generate_module_docs(
        modules=modules,
        llm_client=llm_client,
        target_dir=target_dir,
        db=db,
        language=norm_lang,
        force=force,
        allow_fallback=allow_fallback,
        tracker=tracker,
    )

    # Step 4: Synthesize architecture overview & diagrams
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
        ui_info=ui_info,
        tracker=tracker,
    )

    tracker.finish()
    db.close()
    print("=== designgen Finished: Successfully built documentation ===")
    return 0
