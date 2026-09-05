"""Report Engine: Synthesizes high-level project README (.docgen/README.md)."""

import hashlib
import time
from pathlib import Path
from typing import Optional

from pystdoc.cache import write_flushed_text
from pystdoc.db import DocgenDB
from pystdoc.doc_writer import normalize_language
from pystdoc.llm_client import LLMClient, LLMError


def generate_readme_doc(
    target_dir: Path,
    llm_client: Optional[LLMClient] = None,
    language: str = "English",
    force: bool = False,
    allow_fallback: bool = False,
    db: Optional[DocgenDB] = None,
) -> str:
    """Generate human-centric executive summary document: README.md."""
    norm_lang = normalize_language(language)
    docgen_dir = target_dir / ".docgen"
    design_dir = docgen_dir / "design"
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

    # Compute cache key and input hash
    combined_input = (
        f"{norm_lang}\n{overview_text[:800]}\n"
        f"{data_models_text[:500]}\n{exec_model_text[:500]}\n"
        f"{modules_snippet_str}"
    )
    input_hash = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()
    cache_key = f"report::readme::{norm_lang}"

    if db and not force:
        cached_content = db.load_design_cache(cache_key, input_hash)
        if cached_content:
            print("  [Cached]: .docgen/README.md")
            write_flushed_text(out_file, cached_content.strip() + "\n")
            return cached_content

    start_t = time.time()
    sys_msg = (
        "You are an objective senior code analyst and technical writer. "
        "Strictly prohibit marketing fluff, promotional buzzwords, or "
        "exaggerated praise (e.g. avoid 'mathematical rigor', 'robust', "
        "'flexible', 'next-gen', 'cutting-edge'). Report purely objective "
        f"facts derived directly from code in concise, plain {norm_lang}."
    )

    turn1_prompt = f"""We are analyzing a codebase. Below are excerpts
from architectural models and module summaries.

### Architecture Overview (Excerpt):
{overview_text[:800]}

### Data Models (Excerpt):
{data_models_text[:500]}

### Execution Model (Excerpt):
{exec_model_text[:500]}

### Modules Overview:
{modules_snippet_str}

Answer these 3 factual questions objectively in {norm_lang} (no buzzwords):
1. **Project Category & Language**: What kind of software is this, and what
   is its concrete role? (e.g. C CLI tool for hashing, Python SDK for API,
   C++ matrix math routines, minimal prototype, etc.)
2. **Implementation Status & Scale**: What is the factual state of the code?
   (e.g. Small prototype/study, full-featured CLI, work-in-progress library)
3. **Core Essence (1 Fact-Based Sentence)**: In plain, everyday terms,
   what does it actually do with inputs and outputs?
"""

    turn2_prompt = (
        f"Based on the above facts, answer in {norm_lang} (no fluff):\n"
        "1. **Concrete Usage & Execution**: Provide a realistic command-line\n"
        "   or API call example based directly on the entry points.\n"
        "2. **Input and Output Data**: Specifically what input data format\n"
        "   is accepted, and what concrete output is produced?\n"
    )

    turn3_prompt = (
        "Synthesize a concise, fact-based executive README "
        f"(.docgen/README.md) in {norm_lang}.\n"
        f"Output Language: {norm_lang} (Write all text in {norm_lang}).\n"
        "Tone rule: Strictly objective and concise. No promotional words.\n\n"
        "Structure the Markdown exactly as follows:\n"
        "# Project Overview & Executive Summary\n\n"
        "## 1. What Does This Project Do? (Purpose & Category)\n"
        "(Factual 2-3 sentence summary: tool type, state, and function)\n\n"
        "## 2. Typical Usage & Execution Example\n"
        "(Concrete CLI command or API usage example with input/output)\n\n"
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

    default_readme = f"""# Project Overview & Executive Summary

## 1. What Does This Project Do? (Purpose & Category)
This project provides automated high-precision source code analysis.

## 2. Typical Usage & Execution Example
```bash
pystdoc --dir ./target_project/ --language {norm_lang}
```

## 3. Core Features & Capabilities
- **Codebase Analysis**: Deep symbol extraction (C/C++, Python, Shell).
- **Design Document Synthesis**: Automated synthesis of Data Models, etc.

## 4. How It Works (High-Level Architecture Story)
Analyzes code structure using AST and call graphs, then synthesizes
hierarchical documentation through multi-turn LLM reasoning.

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
        content = (
            f"# Project Overview\n\n## 1. Purpose & Category\n"
            f"Provides project documentation.\n\n"
            f"## 5. Navigation\n{mod_links_str}\n"
        )

    elapsed = time.time() - start_t
    print(f"       -> [Done in {elapsed:5.1f}s]: .docgen/README.md")

    write_flushed_text(out_file, content.strip() + "\n")
    if db:
        db.save_design_cache(cache_key, input_hash, content)
    return content
