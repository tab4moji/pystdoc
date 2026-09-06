"""Command-line interface entry points for docgen, designgen, reportgen."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pystdoc
from pystdoc.config import load_config
from pystdoc.db import DocgenDB
from pystdoc.design_engine import run_design_generation
from pystdoc.engine import run_docgen
from pystdoc.llm_client import LLMClient
from pystdoc.query import (
    run_description,
    run_functions,
    run_list,
    run_types,
    run_variables,
)
from pystdoc.report_engine import generate_readme_doc


def docgen_main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for `docgen` command."""
    parser = argparse.ArgumentParser(
        description="Source code symbol document generator (docgen)"
    )
    ver_str = f"%(prog)s {pystdoc.__version__}"
    parser.add_argument(
        "--version", "-v", action="version", version=ver_str
    )
    parser.add_argument(
        "--dir", default="./", help="Target project directory (default: ./)"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Disable LLM explanation generation"
    )
    parser.add_argument(
        "--host",
        "-H",
        default=None,
        help="LLM server host URL",
    )
    parser.add_argument("--base-url", "-b", default=None,
                        help="Alias for --host")
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="LLM model identifier",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token / key",
    )
    parser.add_argument("--api-key", default=None, help="Alias for --token")
    parser.add_argument(
        "--context-size",
        "--ctx-size",
        type=int,
        default=None,
        help="LLM context window size",
    )
    parser.add_argument(
        "--language",
        "-l",
        default=None,
        help="Documentation language",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force regenerate all documents ignoring cache",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        default=None,
        help="Allow fallback to static template on LLM failure",
    )
    parser.add_argument(
        "--compile-commands",
        default=None,
        help="Path to compile_commands.json (auto-detected if omitted)",
    )
    parser.add_argument(
        "--concurrency",
        "-j",
        type=int,
        default=None,
        help="Number of parallel LLM workers",
    )

    args = parser.parse_args(argv)
    target = Path(args.dir)
    cfg = load_config(target)

    host = args.host or args.base_url or cfg.get("host")
    model = args.model or cfg.get("model", "gemma4-26b-a4b")
    token = args.token or args.api_key or cfg.get("token")
    ctx_size = args.context_size or cfg.get("context_size", 16384)
    lang = args.language or cfg.get("language", "English")
    concurrency = args.concurrency or cfg.get("concurrency", 1)
    allow_fallback = (
        args.allow_fallback
        if args.allow_fallback is not None
        else cfg.get("allow_fallback", False)
    )

    sys.exit(
        run_docgen(
            target_dir=target,
            use_llm=not args.no_llm,
            host=host,
            model=model,
            token=token,
            context_size=ctx_size,
            language=lang,
            force=args.force,
            allow_fallback=allow_fallback,
            compile_commands_path=args.compile_commands,
            concurrency=concurrency,
        )
    )


def designgen_main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for `designgen` command."""
    parser = argparse.ArgumentParser(
        description="Architecture and system design generator (designgen)"
    )
    ver_str = f"%(prog)s {pystdoc.__version__}"
    parser.add_argument(
        "--version", "-v", action="version", version=ver_str
    )
    parser.add_argument(
        "--dir", default="./", help="Target project directory (default: ./)"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Disable LLM explanation generation"
    )
    parser.add_argument(
        "--host",
        "-H",
        default=None,
        help="LLM server host URL",
    )
    parser.add_argument("--base-url", "-b", default=None,
                        help="Alias for --host")
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="LLM model identifier",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token / key",
    )
    parser.add_argument("--api-key", default=None, help="Alias for --token")
    parser.add_argument(
        "--context-size",
        "--ctx-size",
        type=int,
        default=None,
        help="LLM context window size",
    )
    parser.add_argument(
        "--language",
        "-l",
        default=None,
        help="Documentation language",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force regenerate all design documents ignoring cache",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        default=None,
        help="Allow fallback to static template on LLM failure",
    )

    args = parser.parse_args(argv)
    target = Path(args.dir)
    cfg = load_config(target)

    host = args.host or args.base_url or cfg.get("host")
    model = args.model or cfg.get("model", "gemma4-26b-a4b")
    token = args.token or args.api_key or cfg.get("token")
    ctx_size = args.context_size or cfg.get("context_size", 16384)
    lang = args.language or cfg.get("language", "English")
    allow_fallback = (
        args.allow_fallback
        if args.allow_fallback is not None
        else cfg.get("allow_fallback", False)
    )

    sys.exit(
        run_design_generation(
            target_dir=target,
            use_llm=not args.no_llm,
            host=host,
            model=model,
            token=token,
            context_size=ctx_size,
            language=lang,
            force=args.force,
            allow_fallback=allow_fallback,
        )
    )


def _parse_query_target_and_symbol(
    sub_args: List[str], prog_name: str, desc: str
) -> Tuple[Path, Optional[str]]:
    """Parse symbol name and target directory arguments for query."""
    parser = argparse.ArgumentParser(
        prog=f"pystdoc {prog_name}",
        description=desc,
    )
    parser.add_argument(
        "pos1", nargs="?", default=None, help="Symbol name or target directory"
    )
    parser.add_argument(
        "pos2",
        nargs="?",
        default=None,
        help="Target directory (when pos1 is a symbol)",
    )
    parser.add_argument(
        "--dir", default=None, help="Target project directory"
    )
    args = parser.parse_args(sub_args)

    symbol: Optional[str] = None
    target_path = Path("./")

    if args.dir:
        target_path = Path(args.dir)
        if args.pos1:
            symbol = args.pos1
    elif args.pos1 and args.pos2:
        symbol = args.pos1
        target_path = Path(args.pos2)
    elif args.pos1:
        p = Path(args.pos1)
        if "/" in args.pos1 or "\\" in args.pos1 or p.is_dir():
            target_path = p
        else:
            symbol = args.pos1
            target_path = Path("./")

    return target_path.resolve(), symbol


def reportgen_main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for `reportgen` and `pystdoc` commands."""
    if argv is None:
        argv = sys.argv[1:]

    sync_cmds = {"sync"}
    list_cmds = {"list", "ls"}
    fn_cmds = {"functions", "func", "function", "fn", "funcs", "fns"}
    var_cmds = {"variables", "variable", "var", "vars"}
    type_cmds = {"types", "type", "class", "classes", "struct", "structs"}
    desc_cmds = {"description", "desc"}
    mcp_cmds = {"mcp", "serve", "server"}

    subcmd: Optional[str] = None
    sub_args = list(argv)

    if argv and not argv[0].startswith("-"):
        first_arg = argv[0].lower()
        if first_arg in sync_cmds:
            subcmd = "sync"
            sub_args = argv[1:]
        elif first_arg in list_cmds:
            subcmd = "list"
            sub_args = argv[1:]
        elif first_arg in fn_cmds:
            subcmd = "functions"
            sub_args = argv[1:]
        elif first_arg in var_cmds:
            subcmd = "variables"
            sub_args = argv[1:]
        elif first_arg in type_cmds:
            subcmd = "types"
            sub_args = argv[1:]
        elif first_arg in desc_cmds:
            subcmd = "description"
            sub_args = argv[1:]
        elif first_arg in mcp_cmds:
            subcmd = "mcp"
            sub_args = argv[1:]

    if subcmd == "mcp":
        from pystdoc.mcp_server import run_mcp_server

        run_mcp_server()
        sys.exit(0)

    elif subcmd == "list":
        parser = argparse.ArgumentParser(
            prog="pystdoc list", description="List indexed source code files"
        )
        parser.add_argument(
            "dir_pos", nargs="?", default=None, help="Target directory"
        )
        parser.add_argument(
            "--dir", default="./", help="Target project directory"
        )
        args = parser.parse_args(sub_args)
        target = Path(args.dir_pos if args.dir_pos is not None else args.dir)
        sys.exit(run_list(target.resolve()))

    elif subcmd == "functions":
        target, symbol = _parse_query_target_and_symbol(
            sub_args, "functions", "List functions or show description"
        )
        if symbol:
            sys.exit(run_description(target, symbol))
        else:
            sys.exit(run_functions(target))

    elif subcmd == "variables":
        target, symbol = _parse_query_target_and_symbol(
            sub_args, "variables", "List variables or show description"
        )
        if symbol:
            sys.exit(run_description(target, symbol))
        else:
            sys.exit(run_variables(target))

    elif subcmd == "types":
        target, symbol = _parse_query_target_and_symbol(
            sub_args, "types", "List types/classes or show description"
        )
        if symbol:
            sys.exit(run_description(target, symbol))
        else:
            sys.exit(run_types(target))

    elif subcmd == "description":
        target, symbol = _parse_query_target_and_symbol(
            sub_args, "description", "Show symbol description and location"
        )
        if not symbol:
            print(
                "Error: Please specify a symbol name or FQDN.", file=sys.stderr
            )
            sys.exit(1)
        sys.exit(run_description(target, symbol))

    # Default / sync: Run unified documentation pipeline
    parser = argparse.ArgumentParser(
        description="Unified documentation orchestrator (reportgen / pystdoc)"
    )
    ver_str = f"%(prog)s {pystdoc.__version__}"
    parser.add_argument(
        "--version", "-v", action="version", version=ver_str
    )
    parser.add_argument(
        "--dir", default="./", help="Target project directory (default: ./)"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Disable LLM explanation generation"
    )
    parser.add_argument(
        "--host",
        "-H",
        default=None,
        help="LLM server host URL",
    )
    parser.add_argument("--base-url", "-b", default=None,
                        help="Alias for --host")
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="LLM model identifier",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token / key",
    )
    parser.add_argument("--api-key", default=None, help="Alias for --token")
    parser.add_argument(
        "--context-size",
        "--ctx-size",
        type=int,
        default=None,
        help="LLM context window size",
    )
    parser.add_argument(
        "--language",
        "-l",
        default=None,
        help="Documentation language",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force regenerate all documents ignoring cache",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        default=None,
        help="Allow fallback to static template on LLM failure",
    )
    parser.add_argument(
        "--compile-commands",
        default=None,
        help="Path to compile_commands.json (auto-detected if omitted)",
    )
    parser.add_argument(
        "--concurrency",
        "-j",
        type=int,
        default=None,
        help="Number of parallel LLM workers",
    )
    parser.add_argument("--skip-docgen", action="store_true",
                        help="Skip docgen step")
    parser.add_argument(
        "--skip-designgen", action="store_true", help="Skip designgen step"
    )

    args = parser.parse_args(sub_args)
    target_dir = Path(args.dir).resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        print(
            f"Error: Specified directory does not exist: {target_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = load_config(target_dir)

    host = args.host or args.base_url or cfg.get("host")
    model = args.model or cfg.get("model", "gemma4-26b-a4b")
    token = args.token or args.api_key or cfg.get("token")
    ctx_size = args.context_size or cfg.get("context_size", 16384)
    lang = args.language or cfg.get("language", "English")
    concurrency = args.concurrency or cfg.get("concurrency", 1)
    allow_fallback = (
        args.allow_fallback
        if args.allow_fallback is not None
        else cfg.get("allow_fallback", False)
    )

    print("=" * 64)
    print(
        f"=== pystdoc Unified Pipeline v{pystdoc.__version__} "
        f"(Lang: {lang}): {target_dir} ==="
    )
    print("=" * 64)

    # 1. docgen
    if not args.skip_docgen:
        print(
            "\n>>> [Step 1/3] docgen: "
            "Parsing source code and generating symbol docs..."
        )
        ret_docgen = run_docgen(
            target_dir=target_dir,
            use_llm=not args.no_llm,
            host=host,
            model=model,
            token=token,
            context_size=ctx_size,
            language=lang,
            force=args.force,
            allow_fallback=allow_fallback,
            compile_commands_path=args.compile_commands,
            concurrency=concurrency,
        )
        if ret_docgen != 0:
            sys.exit(ret_docgen)

    # 2. designgen
    if not args.skip_designgen:
        print(
            "\n>>> [Step 2/3] designgen: "
            "Synthesizing architecture and data models..."
        )
        ret_design = run_design_generation(
            target_dir=target_dir,
            use_llm=not args.no_llm,
            host=host,
            model=model,
            token=token,
            context_size=ctx_size,
            language=lang,
            force=args.force,
            allow_fallback=allow_fallback,
        )
        if ret_design != 0:
            sys.exit(ret_design)

    # 3. reportgen
    print(
        "\n>>> [Step 3/3] reportgen: "
        "Generating project overview README (.docgen/README.md)..."
    )

    llm_client = None
    if not args.no_llm:
        client = LLMClient(
            host=host,
            model=model,
            token=token,
            context_size=ctx_size,
        )
        if client.check_availability():
            llm_client = client
        elif not allow_fallback:
            print(
                f"Error: Failed to connect to LLM server ({client.base_url}).",
                file=sys.stderr,
            )
            sys.exit(1)

    db_path = target_dir / ".docgen" / "index.db"
    db = DocgenDB(db_path) if db_path.exists() else None

    generate_readme_doc(
        target_dir=target_dir,
        llm_client=llm_client,
        language=lang,
        force=args.force,
        allow_fallback=allow_fallback,
        db=db,
    )

    out_readme = target_dir / ".docgen" / "README.md"
    print("=" * 64)
    print(f"=== reportgen Finished: Created {out_readme} ===")
    print("=" * 64)
    sys.exit(0)
