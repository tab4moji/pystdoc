"""MCP (Model Context Protocol) Server for pystdoc."""

import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server.fastmcp import FastMCP
    except (ImportError, ModuleNotFoundError):
        FastMCP = None  # type: ignore

from pystdoc.config import load_config
from pystdoc.db import DocgenDB
from pystdoc.design_engine import run_design_generation
from pystdoc.engine import run_docgen
from pystdoc.llm_client import LLMClient
from pystdoc.query import (
    _get_docgen_dir,
    run_description,
    run_functions,
    run_list,
    run_types,
    run_variables,
)
from pystdoc.report_engine import generate_readme_doc
from pystdoc.watcher import DNotifyWatcher


class MCPWatcherManager:
    """Manages background directory watchers for MCP server."""

    def __init__(self, debounce_seconds: float = 1.0):
        self.debounce_seconds = debounce_seconds
        self._watchers: Dict[Path, DNotifyWatcher] = {}
        self._lock = threading.Lock()

    def watch_directory(self, target_dir: Path) -> None:
        """Register and start a background watcher for target directory."""
        target_dir = target_dir.resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            return

        with self._lock:
            if target_dir in self._watchers:
                return

            def _on_change() -> None:
                try:
                    cfg = load_config(target_dir)
                    lang = cfg.get("language", "English")
                    host = cfg.get("host")
                    model = cfg.get("model")
                    token = cfg.get("token")
                    ctx_size = cfg.get("context_size", 16384)
                    workers = cfg.get("concurrency", 1)
                    fallback = cfg.get("allow_fallback", False)

                    # 1. docgen
                    run_docgen(
                        target_dir=target_dir,
                        use_llm=True,
                        host=host,
                        model=model,
                        token=token,
                        context_size=ctx_size,
                        concurrency=workers,
                        language=lang,
                        allow_fallback=fallback,
                    )
                    # 2. designgen
                    run_design_generation(
                        target_dir=target_dir,
                        use_llm=True,
                        host=host,
                        model=model,
                        token=token,
                        context_size=ctx_size,
                        language=lang,
                        allow_fallback=fallback,
                    )
                    # 3. reportgen
                    llm_client = None
                    client = LLMClient(
                        host=host,
                        model=model,
                        token=token,
                        context_size=ctx_size,
                    )
                    if client.check_availability():
                        llm_client = client

                    db_path = target_dir / ".docgen" / "index.db"
                    db = DocgenDB(db_path) if db_path.exists() else None
                    generate_readme_doc(
                        target_dir=target_dir,
                        llm_client=llm_client,
                        language=lang,
                        allow_fallback=fallback,
                        db=db,
                    )
                except Exception as e:
                    print(
                        f"[MCP Auto-Sync Error for {target_dir}]: {e}",
                        file=sys.stderr,
                        flush=True,
                    )

            watcher = DNotifyWatcher(
                target_dir=target_dir,
                on_change=_on_change,
                debounce_seconds=self.debounce_seconds,
                log_to_stderr=True,
            )
            watcher.start(blocking=False)
            self._watchers[target_dir] = watcher

    def stop_all(self) -> None:
        """Stop all running background watchers."""
        with self._lock:
            for w in self._watchers.values():
                w.stop()
            self._watchers.clear()


def create_mcp_server(
    target_dir: Optional[Path] = None,
    auto_watch: bool = True,
) -> Any:
    """Create and configure the FastMCP server instance for pystdoc."""
    if FastMCP is None:
        raise RuntimeError(
            "mcp package is not installed. "
            "Please install with `pip install mcp`."
        )

    watcher_mgr: Optional[MCPWatcherManager] = None
    if auto_watch:
        watcher_mgr = MCPWatcherManager()
        init_dir = (target_dir or Path.cwd()).resolve()
        if init_dir.exists() and init_dir.is_dir():
            watcher_mgr.watch_directory(init_dir)

    def _ensure_watching(p: Path) -> None:
        if watcher_mgr is not None and p.exists() and p.is_dir():
            watcher_mgr.watch_directory(p)

    server_instructions = (
        "pystdoc: Structural & Architecture Documentation MCP Server.\n"
        "Guidelines for LLM assistant:\n"
        "1. To understand or explain the system/project, call "
        "`pystdoc_get_overview` or `pystdoc_get_design(section='readme')`.\n"
        "2. To explore architecture, data models, or execution flow, call "
        "`pystdoc_get_design` with 'overview', 'data_models', or "
        "'execution_model'.\n"
        "3. To find classes, functions, or variables, call "
        "`pystdoc_search_symbols` or `pystdoc_list_symbols`.\n"
        "4. To inspect signature and doc for a specific symbol, call "
        "`pystdoc_get_symbol`.\n"
        "5. If documentation is missing or outdated, call `pystdoc_sync` "
        "to generate full docs."
    )

    mcp = FastMCP(
        "pystdoc",
        instructions=server_instructions,
    )
    mcp._watcher_manager = watcher_mgr

    @mcp.tool(
        name="pystdoc_get_overview",
        description=(
            "Get the high-level executive summary, software classification, "
            "purpose, and architectural overview of the project in one call."
        ),
    )
    def get_overview(path: str = "./") -> str:
        """Get the executive README and high-level architectural overview."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        docgen_dir = _get_docgen_dir(target_dir)
        if not docgen_dir.exists():
            return (
                f"Error: .docgen directory not found in {target_dir}. "
                "Please run pystdoc_sync first."
            )
        readme_file = docgen_dir / "README.md"
        overview_file = docgen_dir / "design" / "overview.md"
        parts = []
        if readme_file.exists():
            parts.append(
                readme_file.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            )
        if overview_file.exists():
            parts.append(
                overview_file.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            )
        if not parts:
            return (
                "No overview documentation available in .docgen. "
                "Please run pystdoc_sync."
            )
        return "\n\n---\n\n".join(parts)

    @mcp.tool(
        name="pystdoc_search_symbols",
        description=(
            "Search indexed symbols (functions, classes/types, variables) "
            "by name, keyword, or substring match, returning their FQDN, "
            "definition location, and purpose summary."
        ),
    )
    def search_symbols(
        query: str, kind: str = "all", path: str = "./"
    ) -> str:
        """Search symbols by query string."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        docgen_dir = _get_docgen_dir(target_dir)
        if not docgen_dir.exists():
            return (
                f"Error: .docgen directory not found in {target_dir}. "
                "Please run pystdoc_sync first."
            )
        db_path = docgen_dir / "index.db"
        if not db_path.exists():
            return "Error: index database (.docgen/index.db) not found."

        db = DocgenDB(db_path)
        try:
            cur = db.conn.cursor()
            q_str = f"%{query.strip().lower()}%"
            k_prefix = kind.lower().strip()

            sql = (
                "SELECT m.unique_id, m.name, m.kind, m.rel_path, "
                "m.line_start, m.line_end, m.fqdn, c.purpose "
                "FROM symbols_metadata m "
                "LEFT JOIN symbol_cache c ON m.unique_id = c.unique_id "
                "WHERE (LOWER(m.name) LIKE ? "
                "OR LOWER(COALESCE(m.fqdn, '')) LIKE ? "
                "OR LOWER(COALESCE(c.purpose, '')) LIKE ?)"
            )
            params = [q_str, q_str, q_str]
            if k_prefix in ("fn", "func", "function", "functions"):
                sql += (
                    " AND (LOWER(m.kind) LIKE '%func%' "
                    "OR LOWER(m.kind) LIKE '%method%' "
                    "OR LOWER(m.kind) LIKE '%fn%')"
                )
            elif k_prefix in ("type", "class", "types", "classes", "struct"):
                sql += (
                    " AND (LOWER(m.kind) LIKE '%class%' "
                    "OR LOWER(m.kind) LIKE '%type%' "
                    "OR LOWER(m.kind) LIKE '%struct%' "
                    "OR LOWER(m.kind) LIKE '%enum%' "
                    "OR LOWER(m.kind) LIKE '%interface%')"
                )
            elif k_prefix in ("var", "variable", "vars", "variables", "const"):
                sql += (
                    " AND (LOWER(m.kind) LIKE '%var%' "
                    "OR LOWER(m.kind) LIKE '%const%' "
                    "OR LOWER(m.kind) LIKE '%field%' "
                    "OR LOWER(m.kind) LIKE '%member%')"
                )

            sql += " ORDER BY m.rel_path, m.line_start LIMIT 30"
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                return f"No symbols found matching query '{query}'."

            results = []
            for r in rows:
                _, sname, skind, rpath, lstart, lend, fqdn, purpose = r
                disp_name = fqdn or sname
                p_text = f" - {purpose}" if purpose else ""
                results.append(
                    f"- **`{disp_name}`** (`{skind}`): "
                    f"`{rpath}:{lstart}:{lend}`{p_text}"
                )
            return (
                f"Found {len(results)} matching symbol(s) for '{query}':\n"
                + "\n".join(results)
            )
        finally:
            db.close()

    @mcp.tool(
        name="pystdoc_get_symbol",
        description=(
            "Get rich purpose, overview, signature, line ranges and "
            "markdown doc for a symbol (function, class, variable, or FQDN)."
        ),
    )
    def get_symbol(symbol: str, path: str = "./") -> str:
        """Get documentation for a specific symbol."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        docgen_dir = _get_docgen_dir(target_dir)
        if not docgen_dir.exists():
            return (
                f"Error: .docgen directory not found in {target_dir}. "
                "Please run pystdoc_sync first."
            )

        # Capture output or format response
        from io import StringIO
        import sys
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        capture_out = StringIO()
        capture_err = StringIO()
        try:
            sys.stdout = capture_out
            sys.stderr = capture_err
            ret = run_description(target_dir, symbol)
            out_str = capture_out.getvalue()
            err_str = capture_err.getvalue()
            if ret != 0:
                return (
                    err_str.strip()
                    or f"Symbol '{symbol}' not found in .docgen."
                )
            return out_str.strip()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    @mcp.tool(
        name="pystdoc_list_symbols",
        description=(
            "List all indexed symbols (functions, variables, types/classes) "
            "with definition line ranges (<file>:<from>:<to>)."
        ),
    )
    def list_symbols(kind: str = "all", path: str = "./") -> str:
        """List symbols ('all', 'function', 'variable', 'type')."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        docgen_dir = _get_docgen_dir(target_dir)
        if not docgen_dir.exists():
            return (
                f"Error: .docgen directory not found in {target_dir}. "
                "Please run pystdoc_sync first."
            )

        from io import StringIO
        import sys
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        capture = StringIO()
        try:
            sys.stdout = capture
            sys.stderr = capture
            k = kind.lower().strip()
            if k in ("function", "func", "fn", "functions", "funcs", "fns"):
                run_functions(target_dir)
            elif k in ("variable", "var", "variables", "vars"):
                run_variables(target_dir)
            elif k in (
                "type", "class", "types", "classes", "struct", "structs"
            ):
                run_types(target_dir)
            else:
                print("=== Types & Classes ===")
                run_types(target_dir)
                print("\n=== Functions & Methods ===")
                run_functions(target_dir)
                print("\n=== Variables & Constants ===")
                run_variables(target_dir)
            return capture.getvalue().strip()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    @mcp.tool(
        name="pystdoc_get_design",
        description=(
            "Get high-level architecture design documents ('readme', "
            "'overview', 'data_models', 'execution_model', or module name)."
        ),
    )
    def get_design(section: str = "readme", path: str = "./") -> str:
        """Get high-level architecture design document."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        docgen_dir = _get_docgen_dir(target_dir)
        if not docgen_dir.exists():
            return (
                f"Error: .docgen directory not found in {target_dir}. "
                "Please run pystdoc_sync first."
            )

        design_dir = docgen_dir / "design"
        sec = section.lower().strip()

        # Handle file paths passed as section
        if "/" in sec or "\\" in sec or sec.endswith(
            (".py", ".kt", ".java", ".c", ".cpp", ".h")
        ):
            sec_stem = Path(sec).stem
        else:
            sec_stem = sec

        if sec in ("readme", "summary", "project"):
            f = docgen_dir / "README.md"
        elif sec in ("overview", "arch", "architecture", "overview.md"):
            f = design_dir / "overview.md"
        elif sec in ("data_models", "data", "models", "schema"):
            f = design_dir / "data_models.md"
        elif sec in ("execution_model", "exec", "runtime", "flow"):
            f = design_dir / "execution_model.md"
        else:
            # Check modules
            f = design_dir / "modules" / f"{section}.md"
            if not f.exists():
                f = design_dir / "modules" / f"{sec}.md"
            if not f.exists():
                f = design_dir / "modules" / f"{sec_stem}.md"
            if not f.exists():
                f = design_dir / f"{section}.md"
            if not f.exists():
                f = design_dir / f"{sec}.md"

        if f.exists() and f.is_file():
            return f.read_text(encoding="utf-8", errors="replace").strip()

        available_modules = []
        modules_dir = design_dir / "modules"
        if modules_dir.exists():
            available_modules = [m.stem for m in modules_dir.glob("*.md")]
        mod_hint = (
            f" Available module sections: {', '.join(available_modules)}."
            if available_modules
            else ""
        )
        return (
            f"Design document section '{section}' not found in "
            f".docgen/design/.{mod_hint} Valid standard sections are "
            "'readme', 'overview', 'data_models', 'execution_model'."
        )

    @mcp.tool(
        name="pystdoc_list_files",
        description="List all indexed source code files.",
    )
    def list_files(path: str = "./") -> str:
        """List all indexed source code files."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        from io import StringIO
        import sys
        old_stdout = sys.stdout
        capture = StringIO()
        try:
            sys.stdout = capture
            run_list(target_dir)
            return capture.getvalue().strip()
        finally:
            sys.stdout = old_stdout

    @mcp.tool(
        name="pystdoc_sync",
        description=(
            "Generate or update full documentation suite (.docgen/) for a "
            "codebase using configured LLM, returning project summary."
        ),
    )
    def sync_codebase(
        path: str = "./",
        no_llm: Optional[bool] = None,
        language: Optional[str] = None,
    ) -> str:
        """Synchronize documentation suite for codebase."""
        target_dir = Path(path).resolve()
        _ensure_watching(target_dir)
        cfg = load_config(target_dir)

        use_llm = not no_llm if no_llm is not None else True
        lang = language or cfg.get("language", "English")
        host = cfg.get("host")
        model = cfg.get("model")
        token = cfg.get("token")
        ctx_size = cfg.get("context_size", 16384)
        workers = cfg.get("concurrency", 1)
        fallback = cfg.get("allow_fallback", False)

        try:
            # 1. docgen
            res1 = run_docgen(
                target_dir=target_dir,
                use_llm=use_llm,
                host=host,
                model=model,
                token=token,
                context_size=ctx_size,
                concurrency=workers,
                language=lang,
                allow_fallback=fallback,
            )
            if res1 != 0:
                return f"Error: docgen failed with exit code {res1}."

            # 2. designgen
            res2 = run_design_generation(
                target_dir=target_dir,
                use_llm=use_llm,
                host=host,
                model=model,
                token=token,
                context_size=ctx_size,
                language=lang,
                allow_fallback=fallback,
            )
            if res2 != 0:
                return f"Error: designgen failed with exit code {res2}."

            # 3. reportgen
            llm_client = None
            if use_llm:
                client = LLMClient(
                    host=host,
                    model=model,
                    token=token,
                    context_size=ctx_size,
                )
                if client.check_availability():
                    llm_client = client

            generate_readme_doc(
                target_dir=target_dir,
                llm_client=llm_client,
                language=lang,
                allow_fallback=fallback,
            )

            readme_file = target_dir / ".docgen" / "README.md"
            readme_summary = ""
            if readme_file.exists():
                readme_summary = (
                    "\n\n### Project Executive Summary (.docgen/README.md):\n"
                    + readme_file.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                )

            return (
                "Successfully synchronized documentation in "
                f"{target_dir / '.docgen'}.{readme_summary}"
            )
        except Exception as e:
            return f"Error during sync: {e}"

    return mcp


def run_mcp_server(
    target_dir: Optional[Path] = None,
    auto_watch: bool = True,
) -> None:
    """Run FastMCP server on stdio transport."""
    server = create_mcp_server(target_dir=target_dir, auto_watch=auto_watch)
    try:
        server.run(transport="stdio")
    finally:
        if hasattr(server, "_watcher_manager") and server._watcher_manager:
            server._watcher_manager.stop_all()
