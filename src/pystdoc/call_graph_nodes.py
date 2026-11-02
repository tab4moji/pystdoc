"""SymbolNode data structure and symbol flattening.

Purpose:
    Define the flat graph node (SymbolNode) and convert a hierarchical
    Symbol tree into a flat list of nodes with unique IDs and FQDNs.

Change history:
    1. 2026-11-02 (v0.8.3): Split out of call_graph.py (no logic change).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from pystdoc.symbols import Symbol, get_kind_prefix


@dataclass
class SymbolNode:
    symbol: Symbol
    rel_path: Path
    full_path: Path
    unique_id: str
    fqdn: str = ""
    direct_callee_ids: Set[str] = field(default_factory=set)
    direct_caller_ids: Set[str] = field(default_factory=set)
    scc_group_ids: List[str] = field(default_factory=list)
    dag_level: int = 0


def flatten_symbols(
    symbols: List[Symbol],
    rel_path: Path,
    full_path: Path,
    prefix: str = "",
    seen_ids: Optional[Dict[str, int]] = None,
) -> List[SymbolNode]:
    """Recursively collect symbols into flat list with FQDN and prefixes."""
    if seen_ids is None:
        seen_ids = defaultdict(int)
    nodes: List[SymbolNode] = []
    for sym in symbols:
        k_prefix = get_kind_prefix(sym.kind)
        raw_name = f"{prefix}{sym.name}" if prefix else sym.name
        identifier = f"{k_prefix}.{raw_name}"
        base_uid = f"{rel_path.as_posix()}::{identifier}"
        seen_ids[base_uid] += 1
        if seen_ids[base_uid] == 1:
            uid = base_uid
        else:
            uid = f"{base_uid}#{seen_ids[base_uid]}"

        base_mod = rel_path.with_suffix("").as_posix().replace("/", ".")
        fqdn = sym.fqdn or f"{base_mod}.{raw_name}"

        node = SymbolNode(
            symbol=sym,
            rel_path=rel_path,
            full_path=full_path,
            unique_id=uid,
            fqdn=fqdn,
            direct_callee_ids=set(),
            scc_group_ids=[],
            dag_level=0,
        )
        nodes.append(node)
        if sym.children:
            child_nodes = flatten_symbols(
                sym.children,
                rel_path,
                full_path,
                prefix=f"{raw_name}.",
                seen_ids=seen_ids,
            )
            nodes.extend(child_nodes)
    return nodes
