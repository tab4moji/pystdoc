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
3. **Multi-Language Codebase Deep Understanding (C/C++, Python, Java, Kotlin, Shell)**:
   - **C/C++**: `compile_commands.json` integration, include path resolution, and macro expansion via `libclang`.
   - **Java / Kotlin**: AST parsing via `javalang` & `kopyt` with class hierarchy, companion objects, and data classes.
   - **Python & Shell**: AST visitor and generic regex parser with import/call extraction.
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

#### 1. Generate & Sync Full Documentation Suite (`sync` / Default)
```bash
# Generate complete documentation (symbol docs, design docs, README overview)
pystdoc --dir ./my_project/

# Or explicitly with sync subcommand
pystdoc sync --dir ./my_project/ --language 日本語
```

#### 2. Inspect & Query Indexed Codebase (Read from `.docgen/`)
Once `.docgen/` is generated, you can query symbols, functions, variables, and files without touching LLMs:

```bash
# List all indexed source code files
pystdoc list ./my_project/
# Alias: ls
pystdoc ls

# List all functions and methods with file & line ranges (<name> (<file>:<from>:<to>))
pystdoc functions
# Aliases: fn, func, function, funcs, fns
pystdoc fn
# Inspect specific function description directly (shortcut for desc)
pystdoc fn processData

# List all variables, constants, and fields
pystdoc variables
# Aliases: var, variable, vars
pystdoc var
# Inspect specific variable description directly
pystdoc var CONFIG_TIMEOUT

# List all types, classes, structs, enums, and interfaces
pystdoc types
# Aliases: type, class, classes, struct, structs
pystdoc type
# Inspect specific type or class description directly
pystdoc type MainViewModel
pystdoc class UserModel

# Inspect detailed description, purpose, overview, and signature of a symbol
pystdoc description Userlib.main
# Alias: desc (Supports dot notation, C++ scope resolution, and short names)
pystdoc desc Userlib::main
pystdoc desc logMessage
```

#### 3. Practical Real-World Example (Dedicated Remote LLM Server)
```bash
pystdoc sync --dir ./target_project/ --host 192.168.0.123:11434 --model gemma4-26b-a4b --language 日本語
```

---

## 🛠️ CLI Subcommands & Commands Overview

| Subcommand | Aliases | Description |
| :--- | :--- | :--- |
| `sync` | *(default)* | Run full 3-in-1 unified pipeline: parse code, generate symbol docs, architecture design, and project README. |
| `list` | `ls` | List all indexed source files from `.docgen/`. |
| `functions` | `fn`, `func`, `function`, `funcs`, `fns` | List all functions/methods, or inspect `<name>` description directly (`fn <name>`). |
| `variables` | `var`, `variable`, `vars` | List all variables/constants/fields, or inspect `<name>` description directly (`var <name>`). |
| `types` | `type`, `class`, `classes`, `struct`, `structs` | List all types/classes/structs/enums, or inspect `<name>` description directly (`type <name>`). |
| `description` | `desc` | Display rich purpose, overview, signature, and source location for specified symbol or FQDN. |

---

## ⚙️ CLI Options (for `sync` / `pystdoc`)

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
