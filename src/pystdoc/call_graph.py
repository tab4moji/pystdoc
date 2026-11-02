"""Call graph facade: Level DAG ordering and backward-compatible exports.

Purpose:
    Partition symbol nodes into dependency-safe levels (callees before
    callers, SCC groups together) for level-by-level parallel LLM runs.
    The implementation is split across small modules; the public names
    below are re-exported so existing imports keep working:

    - call_graph_nodes : SymbolNode, flatten_symbols
    - var_linker       : link_variables_to_functions
    - scc              : tarjan_scc
    - level_graph      : ordering helpers
    - callee_summary   : build_callee_context_summary

Change history:
    1. 2026-11-02 (v0.8.3): Split into the modules above. Fixed the
       redundant SCC re-queueing in ranking (see level_graph.py).
"""

from typing import List

from pystdoc.callee_summary import build_callee_context_summary
from pystdoc.call_graph_nodes import SymbolNode, flatten_symbols
from pystdoc.level_graph import (
    assemble_levels,
    assign_scc_groups,
    build_callee_edges,
    build_condensation,
    index_nodes,
    rank_sccs,
)
from pystdoc.scc import tarjan_scc
from pystdoc.symbols import get_kind_prefix
from pystdoc.var_linker import link_variables_to_functions

__all__ = [
    "SymbolNode",
    "flatten_symbols",
    "link_variables_to_functions",
    "tarjan_scc",
    "order_symbols_by_levels",
    "order_symbols_bottom_up",
    "build_callee_context_summary",
]


def order_symbols_by_levels(
    nodes: List[SymbolNode],
) -> List[List[SymbolNode]]:
    """Partition symbol nodes into strictly dependency-safe levels."""
    id_to_node, fqdn_to_ids, short_to_ids = index_nodes(nodes)
    caller_to_callees = build_callee_edges(
        nodes, id_to_node, fqdn_to_ids, short_to_ids
    )

    base_nodes = [n for n in nodes if get_kind_prefix(n.symbol.kind) != "fn"]
    for node in base_nodes:
        node.dag_level = 0
    fn_ids = [
        n.unique_id for n in nodes if get_kind_prefix(n.symbol.kind) == "fn"
    ]

    sccs = tarjan_scc(fn_ids, caller_to_callees)
    node_to_scc_idx = assign_scc_groups(sccs, id_to_node)
    scc_callees, scc_callers = build_condensation(
        node_to_scc_idx, caller_to_callees
    )
    scc_rank = rank_sccs(len(sccs), scc_callees, scc_callers)
    return assemble_levels(base_nodes, sccs, scc_rank, id_to_node)


def order_symbols_bottom_up(nodes: List[SymbolNode]) -> List[SymbolNode]:
    """Flattened bottom-up order."""
    flat: List[SymbolNode] = []
    for level in order_symbols_by_levels(nodes):
        flat.extend(level)
    return flat
