# pystdoc: Python Structural & Topological Documentation Engine

**pystdoc** (*Python Structural & Topological Documentation Engine*) is an enterprise-grade, high-precision codebase and architectural documentation generator powered by LLMs, AST parsing, and `libclang`.

It analyzes codebases in **bottom-up + top-down topological passes**, constructs hierarchical execution/data models, and synthesizes clean, human-centric Markdown and Mermaid diagrams within a **16K context window**.

> [!WARNING]
> **⚠️ Caution: Potential LLM API Usage Costs**
> `pystdoc` performs thorough, multi-pass analysis by sending prompts for individual symbols, modules, and architecture synthesis.
> When using commercial paid API endpoints (such as OpenAI GPT-4, Claude, etc.), analyzing large codebases can consume a significant amount of tokens and may incur substantial financial costs.
> We **strongly recommend** using self-hosted/local LLM backends (e.g., **LiteRT-LM, Ollama, vLLM, or LocalAI**) or setting strict API budget limits before running against large projects.

---

## 📁 Output Directory: `.pystdoc/`

> [!IMPORTANT]
> **All generated documentation, architecture designs, and caches are automatically centralized inside the `.pystdoc/` directory of your target project.**
> Your existing source code files are never modified.

When `pystdoc` finishes, you can explore the complete documentation suite starting from `.pystdoc/README.md`:

```text
your_project/
├── .pystdoc/                         # <-- Centralized output directory
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
   - `docgen`: Bottom-up & top-down symbol-level documentation with SHA-256 and SQLite caching (`.pystdoc/documents/`).
   - `designgen`: Map-Reduce architectural synthesis (`.pystdoc/design/`).
   - `reportgen` / `pystdoc`: Executive summary README (`.pystdoc/README.md`) answering *"What does this project actually do?"*
3. **Multi-Language Codebase Deep Understanding (C/C++, Python, Java, Kotlin, Shell)**:
   - **C/C++**: `compile_commands.json` integration, include path resolution, and macro expansion via `libclang`.
   - **Java / Kotlin**: AST parsing via `javalang` & `kopyt` with class hierarchy, companion objects, and data classes.
   - **Python & Shell**: AST visitor and generic regex parser with import/call extraction.
   - **Fully Qualified Domain Names (FQDN)**: Disambiguates identical symbol names across large monorepos.
4. **Feature Location & UI Component Pinpointing (`locate` / `pystdoc_locate_feature`)**:
   - Pinpoint exact files, functions, UI elements, and line ranges (`Lines X-Y`) from high-level natural language queries (e.g., *"where is the debug notification button"*, *"add auth header"*) without running brute-force `Glob`/`Grep` across the entire project.
   - Built-in multi-lingual token scoring with automatic boosting for UI elements (`@Composable`, `Button`, `Dialog`, `Activity`, `Modifier`, etc.).
5. **Impact & Inbound/Outbound Dependency Analysis (`impact` / `pystdoc_trace_impact`)**:
   - Instant 360-degree dependency tracing: inspect where a symbol is called from (*Inbound Callers / References*) and what it uses (*Outbound Dependencies*) before making breaking code changes or deletions.
6. **Standard LLM Options & Multi-Language Support**:
   - Works with **Ollama, LiteRT-LM, vLLM, and OpenAI API**.
   - Supports `--host`, `--model`, `--token` / `--api-key`, `--context-size`, and `--language` (e.g. `English`, `Japanese`, `日本語`).

---

## 🚀 Quick Start

### Installation
```bash
pip install pystdoc
```

### Basic Usage

#### 1. Generate & Sync Documentation Suite (`sync` / Default)
```bash
# Full sync: complete 4-step pipeline (symbol docs, design docs, README overview)
pystdoc --dir ./my_project/

# Fast sync: bottom-up symbol analysis & indexing only (skips top-down design/report synthesis)
pystdoc sync --fast --dir ./my_project/

# Explicitly with sync subcommand and options
pystdoc sync --dir ./my_project/ --language 日本語
```

#### 2. Inspect & Query Indexed Codebase (Read from `.pystdoc/`)
Once `.pystdoc/` is generated, you can query symbols, functions, variables, and files without touching LLMs:

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

# Locate feature, UI component, or line ranges by natural language query
pystdoc locate "デバッグ通知ボタンを消したい"
# Aliases: find, search
pystdoc find "auth header"
pystdoc search "MainViewModel"

# Trace inbound callers and outbound dependencies for impact analysis before modifying code
pystdoc impact MainViewModel.sendNotification
# Aliases: trace, callers
pystdoc trace DebugButton
pystdoc callers processData
```

#### 3. Continuous File Change Watch & Auto-Sync (`watch` Mode)
Automatically monitor source code directories via Linux `dnotify` (and snapshot polling) and auto-sync on file save:

```bash
# Start continuous watcher
pystdoc watch --dir ./my_project/

# Or with flag and custom debounce interval (default: 1.0s)
pystdoc --watch --interval 0.5
```

#### 4. Practical Real-World Example (Dedicated Remote LLM Server)
```bash
pystdoc sync --dir ./target_project/ --host 192.168.0.11:11434 --model gemma4-26b-a4b --language 日本語
```

---

## 🛠️ CLI Subcommands & Commands Overview

| Subcommand | Aliases | Description |
| :--- | :--- | :--- |
| `sync` | *(default)* | Run full 3-in-1 unified pipeline: parse code, generate symbol docs, architecture design, and project README. |
| `watch` | `monitor` | Continuously watch source directories for changes (dnotify / mtime) and auto-sync on save. |
| `locate` | `find`, `search` | Locate candidate files, functions, UI components, or line ranges matching a feature description or query. |
| `impact` | `trace`, `callers` | Trace inbound callers and outbound dependencies of a symbol for impact analysis before modifying or deleting code. |
| `list` | `ls` | List all indexed source files from `.pystdoc/`. |
| `functions` | `fn`, `func`, `function`, `funcs`, `fns` | List all functions/methods, or inspect `<name>` description directly (`fn <name>`). |
| `variables` | `var`, `variable`, `vars` | List all variables/constants/fields, or inspect `<name>` description directly (`var <name>`). |
| `types` | `type`, `class`, `classes`, `struct`, `structs` | List all types/classes/structs/enums, or inspect `<name>` description directly (`type <name>`). |
| `description` | `desc` | Display rich purpose, overview, signature, and source location for specified symbol or FQDN. |
| `mcp` | `serve`, `server` | Run Model Context Protocol (MCP) stdio server for OpenCode / AI coding agents. |

---

## 🔧 Configuration File (`~/.config/pystdoc/pystdoc.json`)

`pystdoc` automatically loads defaults from `~/.config/pystdoc/pystdoc.json` (or `./.pystdoc.json` for per-project configuration). This allows commands and MCP servers to run without passing long CLI flags.

```json:~/.config/pystdoc/pystdoc.json
{
  "host": "http://192.168.0.123:11434",
  "model": "gemma4-26b-a4b",
  "language": "Japanese",
  "context_size": 16384,
  "concurrency": 2,
  "allow_fallback": true,
  "token": null
}
```

### Precedence Resolution:
1. **CLI Flags** (`--host`, `--model`, `-l`, etc.)
2. **Environment Variables** (`LLM_HOST`, `LLM_MODEL`, `OPENAI_API_KEY`, etc.)
3. **Project Config** (`<project>/.pystdoc.json`)
4. **User Config** (`~/.config/pystdoc/pystdoc.json`)
5. **Builtin Defaults** (`http://127.0.0.1:11434`, `gemma4-26b-a4b`, `English`)

---

## 🔌 Model Context Protocol (MCP) Server

`pystdoc` includes a built-in MCP server (`pystdoc mcp`) for **OpenCode**, Claude Desktop, and other MCP-compatible AI agents. It enables small local LLMs to retrieve targeted AST structures and symbol docs on-demand without loading multi-thousand-line source files into context.

> [!NOTE]
> **File Watching Option (`--watch`)**: In MCP mode, `--no-watch` is the default. To enable automatic background file watching via Linux `dnotify` / mtime monitoring (which automatically keeps `.pystdoc/` synchronized whenever code files are edited), pass `--watch` to the command (e.g. `["pystdoc", "mcp", "--watch"]`). Internal `.pystdoc/` files are strictly excluded from monitoring to prevent self-update loops.

### OpenCode Configuration (`~/.config/opencode/opencode.json`)

```json:~/.config/opencode/opencode.json
{
  "mcp": {
    "pystdoc": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "pystdoc",
        "mcp"
      ]
    }
  }
}
```

### Tools Provided by MCP Server:
- `pystdoc_get_overview(path)`: Retrieve the executive summary (`README.md`) and high-level architectural overview (`overview.md`) in one call.
- `pystdoc_locate_feature(query, path)`: Find candidate file locations, UI components, and line ranges (`Lines X-Y`) for a feature or bug fix. **Use this instead of grep/glob.**
- `pystdoc_trace_impact(symbol, path)`: Trace inbound callers and outbound dependencies of a symbol to determine ripple effects before modifying or deleting code.
- `pystdoc_search_symbols(query, kind, path)`: Search indexed symbols by keyword/substring, returning their FQDN, file location, and purpose summary.
- `pystdoc_get_symbol(symbol, path)`: Retrieve rich purpose, overview, signature, line ranges, and markdown snippet for a specific symbol.
- `pystdoc_list_symbols(kind, path)`: List indexed symbols (`function`, `variable`, `type`, or `all`) with definition line ranges (`file:from:to`).
- `pystdoc_get_design(section, path)`: Retrieve architecture design docs (`readme`, `overview`, `data_models`, `execution_model`, or module names like `MainViewModel`).
- `pystdoc_list_files(path)`: List all indexed source code files.
- `pystdoc_sync(path, fast, no_llm, language)`: Generate or update documentation suite. **Recommended for OpenCode**: Use `fast=True` during active coding to rapidly refresh symbol and call-graph indexes without top-down synthesis overhead.

---

## ⚙️ CLI Options (for `sync` / `pystdoc`)

| Option | Alias / Env | Default | Description |
| :--- | :--- | :--- | :--- |
| `--dir` | | `./` | Target project directory path |
| `--fast` | | `false` | Fast bottom-up sync only (runs docgen symbol indexing, skips designgen and reportgen) |
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

