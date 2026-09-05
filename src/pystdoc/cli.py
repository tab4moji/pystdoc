"""Command-line interface entry points for docgen, designgen, reportgen."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import pystdoc
from pystdoc.db import DocgenDB
from pystdoc.design_engine import run_design_generation
from pystdoc.engine import run_docgen
from pystdoc.llm_client import LLMClient
from pystdoc.query import (
    run_description,
    run_functions,
    run_list,
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
        help="LLM server host URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument("--base-url", "-b", default=None,
                        help="Alias for --host")
    parser.add_argument(
        "--model",
        "-m",
        default="gemma4-26b-a4b",
        help="LLM model identifier (default: gemma4-26b-a4b)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token / key (or env OPENAI_API_KEY / LLM_TOKEN)",
    )
    parser.add_argument("--api-key", default=None, help="Alias for --token")
    parser.add_argument(
        "--context-size",
        "--ctx-size",
        type=int,
        default=16384,
        help="LLM context window size (default: 16384)",
    )
    parser.add_argument(
        "--language",
        "-l",
        default="English",
        help="Documentation language (default: English)",
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
        default=1,
        help="Number of parallel LLM workers (default: 1)",
    )

    args = parser.parse_args(argv)
    sys.exit(
        run_docgen(
            target_dir=Path(args.dir),
            use_llm=not args.no_llm,
            host=args.host,
            base_url=args.base_url,
            model=args.model,
            token=args.token,
            api_key=args.api_key,
            context_size=args.context_size,
            language=args.language,
            force=args.force,
            allow_fallback=args.allow_fallback,
            compile_commands_path=args.compile_commands,
            concurrency=args.concurrency,
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
        help="LLM server host URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument("--base-url", "-b", default=None,
                        help="Alias for --host")
    parser.add_argument(
        "--model",
        "-m",
        default="gemma4-26b-a4b",
        help="LLM model identifier (default: gemma4-26b-a4b)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token / key (or env OPENAI_API_KEY / LLM_TOKEN)",
    )
    parser.add_argument("--api-key", default=None, help="Alias for --token")
    parser.add_argument(
        "--context-size",
        "--ctx-size",
        type=int,
        default=16384,
        help="LLM context window size (default: 16384)",
    )
    parser.add_argument(
        "--language",
        "-l",
        default="English",
        help="Documentation language (default: English)",
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
        help="Allow fallback to static template on LLM failure",
    )

    args = parser.parse_args(argv)
    sys.exit(
        run_design_generation(
            target_dir=Path(args.dir),
            use_llm=not args.no_llm,
            host=args.host,
            base_url=args.base_url,
            model=args.model,
            token=args.token,
            api_key=args.api_key,
            context_size=args.context_size,
            language=args.language,
            force=args.force,
            allow_fallback=args.allow_fallback,
        )
    )


def reportgen_main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for `reportgen` and `pystdoc` commands."""
    if argv is None:
        argv = sys.argv[1:]

    sync_cmds = {"sync"}
    list_cmds = {"list", "ls"}
    fn_cmds = {"functions", "func", "fn", "funcs", "fns"}
    var_cmds = {"variables", "var", "vars"}
    desc_cmds = {"description", "desc"}

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
        elif first_arg in desc_cmds:
            subcmd = "description"
            sub_args = argv[1:]

    if subcmd == "list":
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
        parser = argparse.ArgumentParser(
            prog="pystdoc functions",
            description="List indexed functions and methods",
        )
        parser.add_argument(
            "dir_pos", nargs="?", default=None, help="Target directory"
        )
        parser.add_argument(
            "--dir", default="./", help="Target project directory"
        )
        args = parser.parse_args(sub_args)
        target = Path(args.dir_pos if args.dir_pos is not None else args.dir)
        sys.exit(run_functions(target.resolve()))

    elif subcmd == "variables":
        parser = argparse.ArgumentParser(
            prog="pystdoc variables",
            description="List indexed variables and constants",
        )
        parser.add_argument(
            "dir_pos", nargs="?", default=None, help="Target directory"
        )
        parser.add_argument(
            "--dir", default="./", help="Target project directory"
        )
        args = parser.parse_args(sub_args)
        target = Path(args.dir_pos if args.dir_pos is not None else args.dir)
        sys.exit(run_variables(target.resolve()))

    elif subcmd == "description":
        parser = argparse.ArgumentParser(
            prog="pystdoc description",
            description="Show symbol description and location",
        )
        parser.add_argument(
            "symbol", nargs="?", default=None, help="Symbol name or FQDN"
        )
        parser.add_argument(
            "dir_pos", nargs="?", default=None, help="Target directory"
        )
        parser.add_argument(
            "--dir", default="./", help="Target project directory"
        )
        args = parser.parse_args(sub_args)
        if not args.symbol:
            print(
                "Error: Please specify a symbol name or FQDN.", file=sys.stderr
            )
            sys.exit(1)
        target = Path(args.dir_pos if args.dir_pos is not None else args.dir)
        sys.exit(run_description(target.resolve(), args.symbol))

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
        help="LLM server host URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument("--base-url", "-b", default=None,
                        help="Alias for --host")
    parser.add_argument(
        "--model",
        "-m",
        default="gemma4-26b-a4b",
        help="LLM model identifier (default: gemma4-26b-a4b)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token / key (or env OPENAI_API_KEY / LLM_TOKEN)",
    )
    parser.add_argument("--api-key", default=None, help="Alias for --token")
    parser.add_argument(
        "--context-size",
        "--ctx-size",
        type=int,
        default=16384,
        help="LLM context window size (default: 16384)",
    )
    parser.add_argument(
        "--language",
        "-l",
        default="English",
        help="Documentation language (default: English)",
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
        default=1,
        help="Number of parallel LLM workers (default: 1)",
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

    print("=" * 64)
    print(
        f"=== pystdoc Unified Pipeline v{pystdoc.__version__} "
        f"(Lang: {args.language}): {target_dir} ==="
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
            host=args.host,
            base_url=args.base_url,
            model=args.model,
            token=args.token,
            api_key=args.api_key,
            context_size=args.context_size,
            language=args.language,
            force=args.force,
            allow_fallback=args.allow_fallback,
            compile_commands_path=args.compile_commands,
            concurrency=args.concurrency,
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
            host=args.host,
            base_url=args.base_url,
            model=args.model,
            token=args.token,
            api_key=args.api_key,
            context_size=args.context_size,
            language=args.language,
            force=args.force,
            allow_fallback=args.allow_fallback,
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
            host=args.host or args.base_url,
            model=args.model,
            token=args.token or args.api_key,
            context_size=args.context_size,
        )
        if client.check_availability():
            llm_client = client
        elif not args.allow_fallback:
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
        language=args.language,
        force=args.force,
        allow_fallback=args.allow_fallback,
        db=db,
    )

    out_readme = target_dir / ".docgen" / "README.md"
    print("=" * 64)
    print(f"=== reportgen Finished: Created {out_readme} ===")
    print("=" * 64)
    sys.exit(0)
