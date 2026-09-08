"""Report Engine: Synthesizes high-level project README (.docgen/README.md)."""

import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Optional


from pystdoc.cache import write_flushed_text
from pystdoc.db import DocgenDB
from pystdoc.doc_writer import normalize_language
from pystdoc.llm_client import LLMClient, LLMError
from pystdoc.perf import PerfProfileManager
from pystdoc.progress import PhaseProgressTracker, is_terminal


def generate_readme_doc(
    target_dir: Path,
    llm_client: Optional[LLMClient] = None,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
    db: Optional[DocgenDB] = None,
    is_tty: Optional[bool] = None,
) -> str:
    """Generate human-centric executive summary document: README.md."""
    norm_lang = normalize_language(language)
    if is_tty is None:
        is_tty = is_terminal(sys.stdout)

    perf_mgr = PerfProfileManager.get_instance()
    host_str = llm_client.base_url if llm_client else None
    model_str = llm_client.model if llm_client else None

    est_duration = (
        perf_mgr.predict_duration(
            host=host_str,
            model=model_str,
            gen_type="top_down",
            symbol_kind="readme",
            line_count=30,
        )
        if llm_client
        else 0.001
    )

    tracker = PhaseProgressTracker(
        phase_label="Step 4/4 reportgen",
        total=1,
        is_tty=is_tty,
    )
    tracker.set_remaining_estimate(est_duration)

    docgen_dir = target_dir / ".docgen"
    design_dir = docgen_dir / "design"
    docs_dir = docgen_dir / "documents"
    out_file = docgen_dir / "README.md"

    # 1. Read design overview

    overview_text = ""
    overview_file = design_dir / "overview.md"
    if overview_file.exists():
        overview_text = overview_file.read_text(
            encoding="utf-8", errors="replace"
        )

    # 2. Read data models
    data_models_text = ""
    data_models_file = design_dir / "data_models.md"
    if data_models_file.exists():
        data_models_text = data_models_file.read_text(
            encoding="utf-8", errors="replace"
        )

    # 3. Read execution model
    exec_model_text = ""
    exec_model_file = design_dir / "execution_model.md"
    if exec_model_file.exists():
        exec_model_text = exec_model_file.read_text(
            encoding="utf-8", errors="replace"
        )

    # 4. Collect module documents
    modules_dir = design_dir / "modules"
    module_files = (
        sorted(list(modules_dir.glob("*.md"))) if modules_dir.exists() else []
    )
    module_links = []
    module_summaries_snippet = []

    for mf in module_files:
        mod_name = mf.stem
        module_links.append(
            f"  - [{mod_name} Module](design/modules/{mf.name})"
        )
        m_content = mf.read_text(encoding="utf-8", errors="replace")
        first_lines = " / ".join(
            line.strip()
            for line in m_content.splitlines()[:4]
            if line.strip() and not line.startswith("#")
        )
        module_summaries_snippet.append(
            f"- **`{mod_name}`**: {first_lines[:150]}"
        )

    modules_snippet_str = (
        "\n".join(module_summaries_snippet)
        if module_summaries_snippet
        else "(No modules)"
    )
    mod_links_str = "\n".join(module_links) if module_links else "  - (None)"

    # 5. Extract UI hints from symbol documents bottom-up
    symbol_ui_snippets = []
    if docs_dir.exists():
        for sf in sorted(list(docs_dir.glob("*.md")))[:15]:
            s_text = sf.read_text(encoding="utf-8", errors="replace")
            m_ui_role = re.search(
                r"- \*\*Interaction Specification\*\*:\s*([^\n]+)", s_text
            )
            if m_ui_role:
                symbol_ui_snippets.append(
                    f"- `{sf.name}`: {m_ui_role.group(1).strip()}"
                )
    ui_snippets_str = (
        "\n".join(symbol_ui_snippets[:8])
        if symbol_ui_snippets
        else "No specific symbol UI annotations"
    )

    # Compute cache key and input hash
    combined_input = (
        f"{norm_lang}\n{overview_text[:800]}\n"
        f"{data_models_text[:500]}\n{exec_model_text[:500]}\n"
        f"{modules_snippet_str}\n{ui_snippets_str}"
    )
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"report::readme::{norm_lang}"

    if db and not force and out_file.exists():
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            tracker.advance(1, extra="[Cached]: .docgen/README.md")
            tracker.finish()
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    tracker.render_current(extra=".docgen/README.md")

    sys_msg = (
        "You are an objective senior code analyst and technical writer. "
        "Strictly prohibit marketing fluff, promotional buzzwords, or "
        "exaggerated praise. Report purely objective facts derived "
        f"directly from code in concise, plain {norm_lang}. "
        "Always write in a definitive tone (言い切り型: 〜である / "
        "〜を提供する. Never use ambiguous guesses like 'seems to be' or "
        "'〜と思われる')."
    )

    turn1_prompt = f"""We are analyzing a codebase. Below are excerpts
from architectural models, module summaries, and bottom-up UI annotations.

### Architecture Overview (Excerpt):
{overview_text[:800]}

### Data Models (Excerpt):
{data_models_text[:500]}

### Execution Model (Excerpt):
{exec_model_text[:500]}

### Modules Overview:
{modules_snippet_str}

### Bottom-Up UI Annotations:
{ui_snippets_str}

Answer these 3 factual questions definitively in {norm_lang}
(no fluff, use assertive sentences):
1. **Software Classification (Application vs Library)**:
   - State definitively whether this is an Application or a Library.
   - If it is an Application, specify the exact user interface presence:
     GUI, TUI, or CLI.
2. **Implementation Status & Role**: What is the factual role and state of
   the code (e.g. CLI tool, Android GUI app, backend library)?
3. **Core Functionality**: In plain terms, what does it actually do with
   inputs and outputs? (1 assertive sentence)
"""

    turn2_prompt = (
        f"Based on the above facts and bottom-up symbol UI roles, "
        f"answer in {norm_lang} (no fluff, use assertive sentences):\n"
        "1. **Reconsidered Invocation & Usage**: Based on entry points and "
        "parsed options, provide the exact invocation command line syntax "
        "with flags/arguments (if CLI), or concrete UI user interaction / "
        "API usage example (if GUI/TUI/Library).\n"
        "2. **Input and Output Data**: Specifically what input data format\n"
        "   is accepted, and what concrete output is produced?\n"
    )

    turn3_prompt = (
        "Synthesize a concise, fact-based executive README "
        f"(.docgen/README.md) in {norm_lang}.\n"
        f"Output Language: {norm_lang} (Write all text in {norm_lang}).\n"
        "Tone rule: Strictly objective, concise, and definitive (言い切り型: "
        "〜である / 〜を提供する. Absolutely no vague expressions or praise).\n\n"
        "Structure the Markdown exactly as follows:\n"
        "# Project Overview & Executive Summary\n\n"
        "## 1. Software Classification & Purpose\n"
        "- **Type**: (State definitively whether this is an Application "
        "[GUI / TUI / CLI] or a Library in 1 assertive sentence)\n"
        "- **Purpose**: (Factual summary: what this software does with "
        "inputs and outputs, written in definitive tone)\n\n"
        "## 2. Invocation & Usage Example\n"
        "(If CLI: Exact command-line invocation syntax with options/arguments "
        "and description. If Library/GUI: Concrete execution or API call "
        "example)\n\n"
        "## 3. Core Features & Capabilities\n"
        "(Concise bullet points of implemented features and interfaces)\n\n"
        "## 4. How It Works (High-Level Architecture Story)\n"
        "(Concise factual narrative of internal data flow between modules)\n\n"
        "## 5. Documentation Navigation (Detailed Design Links)\n"
        "- [**Architecture Overview (Overview)**](design/overview.md)\n"
        "- [**Data Models & Structures (Data Models)**]"
        "(design/data_models.md)\n"
        "- [**Execution Model & Runtime (Execution Model)**]"
        "(design/execution_model.md)\n"
        "- **Module Design Documents**:\n"
        f"{mod_links_str}\n"
        "- [**Symbol & Source Code Index**](documents/)\n"
    )

    proj_name = target_dir.name or "Project"
    inferred_type = "Software Module / Application"
    if any(
        k in ui_snippets_str
        for k in ("Activity", "Compose", "Android", "GUI", "View")
    ):
        inferred_type = "GUI Application"
    elif "CLI" in overview_text or "main(" in overview_text:
        inferred_type = "CLI Application"
    elif module_files:
        inferred_type = "Library / Module Package"

    mod_names_str = (
        ", ".join(f"`{mf.stem}`" for mf in module_files[:6])
        if module_files
        else "source modules"
    )

    default_readme = f"""# Project Overview & Executive Summary ({proj_name})

## 1. Software Classification & Purpose
- **Type**: {inferred_type}
- **Purpose**: Provides functionality implemented across {len(module_files)} \
key module(s) ({mod_names_str}).

## 2. Invocation & Usage Example
Refer to the module interfaces and entry points described in documentation.

## 3. Core Features & Capabilities
{modules_snippet_str}

## 4. How It Works (High-Level Architecture Story)
Modular software system structured into interconnected components with \
topological dependency mapping.

## 5. Documentation Navigation (Detailed Design Links)
- [**Architecture Overview (Overview)**](design/overview.md)
- [**Data Models & Structures (Data Models)**](design/data_models.md)
- [**Execution Model & Runtime (Execution Model)**](design/execution_model.md)
- **Module Design Documents**:
{mod_links_str}
- [**Symbol & Source Code Index**](documents/)
"""

    try:
        if llm_client:
            # Turn 1: Project classification and essence
            msg1 = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": turn1_prompt},
            ]
            ans1 = llm_client.chat_completion(msg1)

            # Turn 2: Typical usage and execution flow
            msg2 = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": turn1_prompt},
                {"role": "assistant", "content": ans1},
                {"role": "user", "content": turn2_prompt},
            ]
            ans2 = llm_client.chat_completion(msg2)

            # Turn 3: Final executive README synthesis
            msg3 = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": turn1_prompt},
                {"role": "assistant", "content": ans1},
                {"role": "user", "content": turn2_prompt},
                {"role": "assistant", "content": ans2},
                {"role": "user", "content": turn3_prompt},
            ]
            content = llm_client.chat_completion(msg3)
        else:
            content = default_readme
    except Exception as e:
        if not allow_fallback:
            raise LLMError(
                f"Failed to generate README document: {e}"
            ) from e
        content = default_readme

    elapsed = time.time() - start_t
    perf_mgr.record_measurement(
        host=host_str,
        model=model_str,
        gen_type="top_down",
        symbol_kind="readme",
        line_count=30,
        elapsed_seconds=elapsed,
    )
    tracker.advance(1, extra=".docgen/README.md", elapsed=elapsed)
    tracker.finish()

    write_flushed_text(out_file, content.strip() + "\n")
    if db:
        db.save_design_cache(cache_key, input_hash, content)
    return content
