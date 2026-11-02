"""Helpers for dependency-level ordering of symbol nodes.

Purpose:
    Provide the building blocks used by call_graph.order_symbols_by_levels:
    name indexes, callee edges, SCC condensation, bottom-up ranking and
    level assembly.

Change history:
    1. 2026-11-02 (v0.8.3): Split out of call_graph.py. rank_sccs now
       skips already-resolved SCCs; previously they were re-queued once
       per child, which cost up to 20 s on a 2.4k-symbol C project and
       made the run time depend on the hash seed.
"""

from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

from pystdoc.call_graph_nodes import SymbolNode
from pystdoc.symbols import get_kind_prefix

IdIndex = Dict[str, List[str]]


def index_nodes(
    nodes: List[SymbolNode],
) -> Tuple[Dict[str, SymbolNode], IdIndex, IdIndex]:
    """Build unique_id, FQDN and short-name lookup tables."""
    id_to_node: Dict[str, SymbolNode] = {n.unique_id: n for n in nodes}
    fqdn_to_ids: IdIndex = defaultdict(list)
    short_to_ids: IdIndex = defaultdict(list)

    for node in nodes:
        short_to_ids[node.symbol.name].append(node.unique_id)
        if node.fqdn:
            fqdn_to_ids[node.fqdn].append(node.unique_id)
        if "::" in node.unique_id:
            sym_part = node.unique_id.split("::", 1)[1]
            raw = sym_part.split(".", 1)[-1] if "." in sym_part else sym_part
            short_to_ids[raw].append(node.unique_id)
    return id_to_node, fqdn_to_ids, short_to_ids


def build_callee_edges(
    nodes: List[SymbolNode],
    id_to_node: Dict[str, SymbolNode],
    fqdn_to_ids: IdIndex,
    short_to_ids: IdIndex,
) -> Dict[str, Set[str]]:
    """Resolve callee names to node IDs and record caller/callee links."""
    caller_to_callees: Dict[str, Set[str]] = {
        n.unique_id: set() for n in nodes
    }
    for node in nodes:
        if get_kind_prefix(node.symbol.kind) != "fn":
            continue
        for callee_name in node.symbol.callees:
            matched = fqdn_to_ids.get(callee_name, [])
            if not matched:
                matched = short_to_ids.get(callee_name, [])
            for target_id in matched:
                target = id_to_node[target_id]
                is_fn = get_kind_prefix(target.symbol.kind) == "fn"
                if target_id != node.unique_id and is_fn:
                    caller_to_callees[node.unique_id].add(target_id)
                    node.direct_callee_ids.add(target_id)
                    target.direct_caller_ids.add(node.unique_id)
    return caller_to_callees


def assign_scc_groups(
    sccs: List[List[str]], id_to_node: Dict[str, SymbolNode]
) -> Dict[str, int]:
    """Map member IDs to SCC index and set mutual-recursion peers."""
    node_to_scc_idx: Dict[str, int] = {}
    for scc_idx, members in enumerate(sccs):
        for member_id in members:
            node_to_scc_idx[member_id] = scc_idx
            if len(members) > 1:
                id_to_node[member_id].scc_group_ids = [
                    m for m in members if m != member_id
                ]
    return node_to_scc_idx


def build_condensation(
    node_to_scc_idx: Dict[str, int],
    caller_to_callees: Dict[str, Set[str]],
) -> Tuple[Dict[int, Set[int]], Dict[int, Set[int]]]:
    """Build the SCC condensation DAG (callees and callers per SCC)."""
    scc_callees: Dict[int, Set[int]] = defaultdict(set)
    scc_callers: Dict[int, Set[int]] = defaultdict(set)
    for caller_id, callee_ids in caller_to_callees.items():
        c_scc = node_to_scc_idx.get(caller_id)
        for callee_id in callee_ids:
            t_scc = node_to_scc_idx.get(callee_id)
            if c_scc is not None and t_scc is not None and t_scc != c_scc:
                scc_callees[c_scc].add(t_scc)
                scc_callers[t_scc].add(c_scc)
    return scc_callees, scc_callers


def rank_sccs(
    scc_count: int,
    scc_callees: Dict[int, Set[int]],
    scc_callers: Dict[int, Set[int]],
) -> Dict[int, int]:
    """Bottom-up topological rank; each SCC is resolved exactly once."""
    scc_rank: Dict[int, int] = {}
    queue = deque(i for i in range(scc_count) if not scc_callees[i])
    resolved: Set[int] = set(queue)
    for i in queue:
        scc_rank[i] = 0

    while queue:
        curr = queue.popleft()
        for parent in scc_callers[curr]:
            ready = parent not in resolved and scc_callees[
                parent
            ].issubset(resolved)
            if ready:
                scc_rank[parent] = (
                    max(scc_rank[c] for c in scc_callees[parent]) + 1
                )
                resolved.add(parent)
                queue.append(parent)

    for i in range(scc_count):
        scc_rank.setdefault(i, 0)
    return scc_rank


def assemble_levels(
    base_nodes: List[SymbolNode],
    sccs: List[List[str]],
    scc_rank: Dict[int, int],
    id_to_node: Dict[str, SymbolNode],
) -> List[List[SymbolNode]]:
    """Group nodes by DAG level (non-functions first at level 0)."""
    offset = 1 if base_nodes else 0
    level_groups: Dict[int, List[SymbolNode]] = defaultdict(list)
    if base_nodes:
        level_groups[0].extend(base_nodes)

    for scc_idx, members in enumerate(sccs):
        node_level = scc_rank[scc_idx] + offset
        for member_id in members:
            node = id_to_node[member_id]
            node.dag_level = node_level
            level_groups[node_level].append(node)

    max_lvl = max(level_groups.keys()) if level_groups else 0
    return [level_groups[i] for i in range(max_lvl + 1) if level_groups[i]]
