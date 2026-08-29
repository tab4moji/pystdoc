# pystdoc: Python Structural & Topological Documentation Engine

**pystdoc** (*Python Structural & Topological Documentation Engine*) is an enterprise-grade, high-precision codebase and architectural documentation generator powered by LLMs, AST parsing, and `libclang`.

It analyzes codebases in **bottom-up + top-down topological passes**, constructs hierarchical execution/data models, and synthesizes clean, human-centric Markdown and Mermaid diagrams within a **16K context window**.

---

## 🌟 Key Features

1. **Topological & Structural Ordering (Tarjan SCC + Kahn DAG)**:
   - Evaluates call graphs in $O(V+E)$ linear time.
   - Automatically breaks cyclic mutual recursions and organizes code symbols into dependency-safe execution levels.
   - Level-by-level parallel LLM execution guarantees context-rich bottom-up summaries without race conditions.
2. **3-in-1 Unified Documentation Pipeline**:
   - `docgen`: Bottom-up & top-down symbol-level documentation with SHA-256 and SQLite caching.
   - `designgen`: Map-Reduce architectural synthesis (`data_models.md`, `execution_model.md`, `modules/*.md`, `overview.md`).
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

#### 2. Generate in Japanese
```bash
pystdoc --dir ./my_project/ --language 日本語
```

#### 3. Run Individual Steps
```bash
# Generate symbol-level docs
docgen --dir ./my_project/ -j 4

# Synthesize architecture design docs
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
| `--concurrency` | `-j` | `4` | Number of parallel LLM workers |
| `--force` | `-f` | `false` | Force regenerate all documents ignoring cache |
| `--compile-commands` | | `None` | Path to `compile_commands.json` |

---

## 📄 License
MIT License. Author: **tab4moji**.
