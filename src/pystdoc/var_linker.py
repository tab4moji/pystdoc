"""Link variables / constants / types to the functions that use them.

Purpose:
    For every var/const/type node, find the functions that reference it,
    either by containing its declaration line or by mentioning its name
    as a whole word in the function body.

    Each source file is read once and every function body is tokenized
    once into a word -> functions inverted index, so the cost is
    O(total source size + matches) instead of O(targets x functions x
    file size). Results are identical to the former `\\bname\\b` scan.

Change history:
    1. 2026-11-02 (v0.8.3): Split out of call_graph.py. Replaced the
       per-pair file re-read with a single read plus inverted index.
"""

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from pystdoc.call_graph_nodes import SymbolNode
from pystdoc.symbols import get_kind_prefix

_WORD = re.compile(r"\w+")
_TARGET_PREFIXES = ("var", "const", "type")


@dataclass
class FunctionIndex:
    """Per-run lookup tables built from function bodies."""

    inverted: Dict[str, List[SymbolNode]] = field(
        default_factory=lambda: defaultdict(list)
    )
    codes: Dict[str, str] = field(default_factory=dict)
    by_file: Dict[Path, List[SymbolNode]] = field(
        default_factory=lambda: defaultdict(list)
    )


def read_lines_cached(
    path: Path, cache: Dict[Path, Optional[List[str]]]
) -> Optional[List[str]]:
    """Read a file once; unreadable files are reported and cached as None."""
    if path not in cache:
        try:
            cache[path] = path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except Exception as exc:
            print(f"Warning: cannot read {path}: {exc}", file=sys.stderr)
            cache[path] = None
    return cache[path]


def build_function_index(fn_nodes: List[SymbolNode]) -> FunctionIndex:
    """Tokenize each function body once into the inverted index."""
    index = FunctionIndex()
    cache: Dict[Path, Optional[List[str]]] = {}
    for f_node in fn_nodes:
        index.by_file[f_node.rel_path].append(f_node)
        lines = read_lines_cached(f_node.full_path, cache)
        if lines is not None:
            start = max(0, f_node.symbol.line_start - 1)
            end = min(len(lines), f_node.symbol.line_end)
            code = "\n".join(lines[start:end])
            index.codes[f_node.unique_id] = code
            for token in set(_WORD.findall(code)):
                index.inverted[token].append(f_node)
    return index


def find_referencing_functions(
    t_node: SymbolNode,
    fn_nodes: List[SymbolNode],
    index: FunctionIndex,
) -> Dict[str, SymbolNode]:
    """Return functions (by unique_id) that contain or mention t_node."""
    hits: Dict[str, SymbolNode] = {}
    t_start = t_node.symbol.line_start
    for f_node in index.by_file.get(t_node.rel_path, ()):
        if f_node.symbol.line_start <= t_start <= f_node.symbol.line_end:
            hits[f_node.unique_id] = f_node

    name = t_node.symbol.name
    if _WORD.fullmatch(name):
        for f_node in index.inverted.get(name, ()):
            hits.setdefault(f_node.unique_id, f_node)
    else:
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        for f_node in fn_nodes:
            code = index.codes.get(f_node.unique_id)
            if code is not None and pattern.search(code):
                hits.setdefault(f_node.unique_id, f_node)
    return hits


def link_variables_to_functions(nodes: List[SymbolNode]) -> None:
    """Detect functions referencing variables/consts/types using scope/text."""
    fn_nodes = [n for n in nodes if get_kind_prefix(n.symbol.kind) == "fn"]
    targets = [
        n
        for n in nodes
        if get_kind_prefix(n.symbol.kind) in _TARGET_PREFIXES
    ]
    index = build_function_index(fn_nodes)

    for t_node in targets:
        hits = find_referencing_functions(t_node, fn_nodes, index)
        refs = set()
        for f_node in hits.values():
            refs.add(f"`{f_node.symbol.name}` (`{f_node.rel_path.name}`)")
            t_node.direct_caller_ids.add(f_node.unique_id)
        t_node.symbol.referencing_functions = sorted(refs)
