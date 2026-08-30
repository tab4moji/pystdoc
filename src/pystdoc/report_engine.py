"""Report Engine: Synthesizes high-level project README (.docgen/README.md)."""

from pathlib import Path
from typing import Optional

from pystdoc.cache import write_flushed_text
from pystdoc.doc_writer import normalize_language
from pystdoc.llm_client import LLMClient, LLMError


def generate_readme_doc(
    target_dir: Path,
    llm_client: Optional[LLMClient] = None,
    language: str = "English",
    allow_fallback: bool = False,
) -> str:
    """Generate human-centric executive summary document: README.md."""
    norm_lang = normalize_language(language)
    docgen_dir = target_dir / ".docgen"
    design_dir = docgen_dir / "design"

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

    prompt = f"""Please synthesize an executive README (.docgen/README.md)
in {norm_lang}.
Output Language: {norm_lang} (Write all explanation text in {norm_lang}).
Goal: **"What does this project do, and what value does it provide?"**

### Architecture Overview (Excerpt):
{overview_text[:800]}

### Data Models (Excerpt):
{data_models_text[:500]}

### Execution Model (Excerpt):
{exec_model_text[:500]}

### Modules Overview:
{modules_snippet_str}

Structure the Markdown as follows:
# Project Overview & Executive Summary

## 1. What Does This Project Do? (Purpose & Value Proposition)
(Explain clearly in 3-5 sentences: what system does and why it exists)

## 2. Core Features & Capabilities
(Bullet points of primary capabilities and exposed interfaces)

## 3. System Architecture Summary
(Concise summary of data flow, layers, and how modules cooperate)

## 4. Documentation Navigation (Detailed Design Links)
- [**Architecture Overview (Overview)**](design/overview.md)
- [**Data Models & Structures (Data Models)**](design/data_models.md)
- [**Execution Model & Runtime (Execution Model)**](design/execution_model.md)
- **Module Design Documents**:
{mod_links_str}
- [**Symbol & Source Code Index**](documents/)
"""

    sys_msg = (
        "You are an executive technical writer and principal architect. "
        f"Write clear human-friendly documentation in {norm_lang}."
    )
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": prompt},
    ]

    default_readme = f"""# Project Overview & Executive Summary

## 1. What Does This Project Do? (Purpose & Value Proposition)
This project provides high-precision source code analysis and documentation.

## 2. Core Features & Capabilities
- **Codebase Analysis**: Deep symbol extraction for multiple languages.
- **Design Document Synthesis**: Automated synthesis of Data Models, etc.

## 3. System Architecture Summary
Organized as a multi-pass AST and LLM Map-Reduce processing pipeline.

## 4. Documentation Navigation (Detailed Design Links)
- [**Architecture Overview (Overview)**](design/overview.md)
- [**Data Models & Structures (Data Models)**](design/data_models.md)
- [**Execution Model & Runtime (Execution Model)**](design/execution_model.md)
- **Module Design Documents**:
{mod_links_str}
- [**Symbol & Source Code Index**](documents/)
"""

    try:
        if llm_client:
            content = llm_client.chat_completion(messages)
        else:
            content = default_readme
    except Exception as e:
        if not allow_fallback:
            raise LLMError(
                f"Failed to generate README document: {e}"
            ) from e
        content = (
            f"# Project Overview\n\n## 1. Purpose\n"
            f"Provides project documentation.\n\n"
            f"## 4. Navigation\n{mod_links_str}\n"
        )

    out_file = docgen_dir / "README.md"
    write_flushed_text(out_file, content.strip() + "\n")
    return content
