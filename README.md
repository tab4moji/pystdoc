# pystdoc: Python Structural & Topological Documentation Engine

**pystdoc** (*Python Structural & Topological Documentation Engine*) is an enterprise-grade, high-precision codebase and architectural documentation generator powered by LLMs, AST parsing, and `libclang`.

It analyzes codebases in **bottom-up + top-down topological passes**, constructs hierarchical execution/data models, and synthesizes clean, human-centric Markdown and Mermaid diagrams within a **16K context window**.

> [!WARNING]
> **⚠️ Caution: Potential LLM API Usage Costs**
> `pystdoc` performs thorough, multi-pass analysis by sending prompts for individual symbols, modules, and architecture synthesis.
> When using commercial paid API endpoints (such as OpenAI GPT-4, Claude, etc.), analyzing large codebases can consume a significant amount of tokens and may incur substantial financial costs.
> We **strongly recommend** using self-hosted/local LLM backends (e.g., **LiteRT-LM, Ollama, vLLM, or LocalAI**) or setting strict API budget limits before running against large projects.

---

## 📁 Output Directory: `.docgen/`

> [!IMPORTANT]
> **All generated documentation, architecture designs, and caches are automatically centralized inside the `.docgen/` directory of your target project.**
> Your existing source code files are never modified.

When `pystdoc` finishes, you can explore the complete documentation suite starting from `.docgen/README.md`:

```text
your_project/
├── .docgen/                          # <-- Centralized output directory
│   ├── README.md                     # Executive summary: "What does this project actually do?"
│   ├── design/                       # System architecture and design documentation
│   │   ├── overview.md               # Architecture overview & inter-module Mermaid diagram
│   │   ├── data_models.md            # Data structure design, models, lifecycle & integrity
│   │   ├── execution_model.md        # Runtime execution model, paradigms, & control flow
│   │   └── modules/                  # Module-by-module detailed design documents
│   │       ├── module_a.md
│   │       └── ...
│   ├── documents/                    # Granular symbol & source code documentation
│   │   ├── src/main.c.md             # File-level overview and symbol list
│   │   ├── src/main.c.fn.main.md     # Individual symbol document (with call graph & context)
│   │   └── ...
│   ├── files.txt                     # List of scanned source files
│   └── index.db                      # SQLite WAL database for instantaneous incremental caching
├── src/
└── ...
```

---

## 🌟 Key Features

1. **Topological & Structural Ordering (Tarjan SCC + Kahn DAG)**:
   - Evaluates call graphs in $O(V+E)$ linear time.
   - Automatically breaks cyclic mutual recursions and organizes code symbols into dependency-safe execution levels.
   - Level-by-level parallel LLM execution guarantees context-rich bottom-up summaries without race conditions.
2. **3-in-1 Unified Documentation Pipeline**:
   - `docgen`: Bottom-up & top-down symbol-level documentation with SHA-256 and SQLite caching (`.docgen/documents/`).
   - `designgen`: Map-Reduce architectural synthesis (`.docgen/design/`).
   - `reportgen` / `pystdoc`: Executive summary README (`.docgen/README.md`) answering *"What does this project actually do?"*
3. **C/C++, Python & Shell Deep Understanding**:
   - **`compile_commands.json` Integration**: Full include path resolution and macro expansion via `libclang`.
   - **Fully Qualified Domain Names (FQDN)**: Disambiguates identical symbol names across large monorepos.
4. **Standard LLM Options & Multi-Language Support**:
   - Works with **Ollama, LiteRT-LM, vLLM, and OpenAI API**.
   - Supports `--host`, `--model`, `--token` / `--api-key`, `--context-size`, and `--language` (e.g. `English`, `Japanese`, `日本語`).

---

## 🚀 Quick Start

### Installation
```bash
pip install pystdoc
```

### Basic Usage

#### 1. Generate Full Documentation & README (One Command)
```bash
pystdoc --dir ./my_project/
```
*Output will be created at `./my_project/.docgen/README.md`.*

#### 2. Generate in Japanese
```bash
pystdoc --dir ./my_project/ --language 日本語
```

#### 3. Run Individual Steps
```bash
# Generate symbol-level docs into .docgen/documents/
docgen --dir ./my_project/ -j 4

# Synthesize architecture design docs into .docgen/design/
designgen --dir ./my_project/
```

---

## ⚙️ CLI Options

| Option | Alias / Env | Default | Description |
| :--- | :--- | :--- | :--- |
| `--dir` | | `./` | Target project directory path |
| `--language` | `-l` | `English` | Output documentation language (`English`, `Japanese`, `日本語`) |
| `--host` | `-H`, `--base-url` | `http://127.0.0.1:11434` | LLM server host endpoint URL |
| `--model` | `-m`, `LLM_MODEL` | `gemma4-26b-a4b` | LLM model identifier |
| `--token` | `--api-key`, `OPENAI_API_KEY` | `None` | API Bearer token |
| `--context-size` | `--ctx-size` | `16384` | Context window size |
| `--concurrency` | `-j` | `1` | Number of parallel LLM workers |
| `--force` | `-f` | `false` | Force regenerate all documents ignoring cache |
| `--compile-commands` | | `None` | Path to `compile_commands.json` |

---

## 📄 License
MIT License. Author: **tab4moji**.
