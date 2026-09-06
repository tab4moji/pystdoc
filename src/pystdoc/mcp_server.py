"""MCP (Model Context Protocol) Server for pystdoc."""

from pathlib import Path
from typing import Any, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server.fastmcp import FastMCP
    except (ImportError, ModuleNotFoundError):
        FastMCP = None  # type: ignore

from pystdoc.config import load_config
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


def create_mcp_server() -> Any:
    """Create and configure the FastMCP server instance for pystdoc."""
    if FastMCP is None:
        raise RuntimeError(
            "mcp package is not installed. "
            "Please install with `pip install mcp`."
        )

    mcp = FastMCP(
        "pystdoc",
        instructions="Python Structural & Codebase Documentation MCP",
    )

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
            "Get high-level architecture design documents ('overview', "
            "'data_models', 'execution_model', 'readme', or module name)."
        ),
    )
    def get_design(section: str = "overview", path: str = "./") -> str:
        """Get high-level architecture design document."""
        target_dir = Path(path).resolve()
        docgen_dir = _get_docgen_dir(target_dir)
        if not docgen_dir.exists():
            return (
                f"Error: .docgen directory not found in {target_dir}. "
                "Please run pystdoc_sync first."
            )

        design_dir = docgen_dir / "design"
        sec = section.lower().strip()

        if sec in ("readme", "summary", "project"):
            f = docgen_dir / "README.md"
        elif sec in ("overview", "arch", "architecture"):
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
                f = design_dir / f"{section}.md"

        if f.exists() and f.is_file():
            return f.read_text(encoding="utf-8", errors="replace").strip()
        return (
            f"Design document section '{section}' not found in "
            ".docgen/design/."
        )

    @mcp.tool(
        name="pystdoc_list_files",
        description="List all indexed source code files.",
    )
    def list_files(path: str = "./") -> str:
        """List all indexed source code files."""
        target_dir = Path(path).resolve()
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
            "codebase using configured LLM."
        ),
    )
    def sync_codebase(
        path: str = "./",
        no_llm: Optional[bool] = None,
        language: Optional[str] = None,
    ) -> str:
        """Synchronize documentation suite for codebase."""
        target_dir = Path(path).resolve()
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
            return (
                "Successfully synchronized documentation in "
                f"{target_dir / '.docgen'}."
            )
        except Exception as e:
            return f"Error during sync: {e}"

    return mcp


def run_mcp_server() -> None:
    """Run FastMCP server on stdio transport."""
    server = create_mcp_server()
    server.run(transport="stdio")
