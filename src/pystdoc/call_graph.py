"""Call graph construction, Tarjan SCC cycle condensation, FQDN matching, and Level-by-Level DAG parallel ordering."""

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pystdoc.symbols import Symbol, get_kind_prefix


@dataclass
class SymbolNode:
    symbol: Symbol
    rel_path: Path
    full_path: Path
    unique_id: str
    fqdn: str = ""
    direct_callee_ids: Set[str] = field(default_factory=set)
    scc_group_ids: List[str] = field(default_factory=list)
    dag_level: int = 0


def flatten_symbols(
    symbols: List[Symbol],
    rel_path: Path,
    full_path: Path,
    prefix: str = "",
) -> List[SymbolNode]:
    """Recursively collect all symbols into a flat list of SymbolNodes with FQDN and kind prefixes."""
    nodes: List[SymbolNode] = []
    for sym in symbols:
        k_prefix = get_kind_prefix(sym.kind)
        raw_name = f"{prefix}{sym.name}" if prefix else sym.name
        identifier = f"{k_prefix}.{raw_name}"
        uid = f"{rel_path.as_posix()}::{identifier}"

        fqdn = sym.fqdn or f"{rel_path.with_suffix('').as_posix().replace('/', '.')}.{raw_name}"

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
            )
            nodes.extend(child_nodes)
    return nodes


def link_variables_to_functions(nodes: List[SymbolNode]) -> None:
    """Detect which functions directly reference each variable using FQDN and scope matching."""
    fn_nodes = [n for n in nodes if get_kind_prefix(n.symbol.kind) == "fn"]
    var_nodes = [n for n in nodes if get_kind_prefix(n.symbol.kind) == "var"]

    for v_node in var_nodes:
        v_name = v_node.symbol.name
        ref_funcs: Set[str] = set()

        for f_node in fn_nodes:
            if f_node.rel_path == v_node.rel_path:
                if f_node.symbol.line_start <= v_node.symbol.line_start <= f_node.symbol.line_end:
                    ref_funcs.add(f"`{f_node.symbol.name}` (`{f_node.rel_path.name}`)")
                    continue

            try:
                code_lines = f_node.full_path.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(0, f_node.symbol.line_start - 1)
                end = min(len(code_lines), f_node.symbol.line_end)
                func_code = "\n".join(code_lines[start:end])

                if re.search(rf"\b{re.escape(v_name)}\b", func_code):
                    ref_funcs.add(f"`{f_node.symbol.name}` (`{f_node.rel_path.name}`)")
            except Exception:
                pass

        v_node.symbol.referencing_functions = sorted(list(ref_funcs))


def tarjan_scc(node_ids: List[str], adj: Dict[str, Set[str]]) -> List[List[str]]:
    """Tarjan's strongly connected components algorithm in O(V+E) time."""
    index = 0
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    sccs: List[List[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        lowlinks[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, set()):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for node_id in node_ids:
        if node_id not in indices:
            strongconnect(node_id)

    return sccs


def order_symbols_by_levels(nodes: List[SymbolNode]) -> List[List[SymbolNode]]:
    """Partition symbol nodes into strictly dependency-safe levels for parallel processing."""
    id_to_node: Dict[str, SymbolNode] = {n.unique_id: n for n in nodes}
    fqdn_to_node_ids: Dict[str, List[str]] = defaultdict(list)
    short_name_to_ids: Dict[str, List[str]] = defaultdict(list)

    for node in nodes:
        short_name_to_ids[node.symbol.name].append(node.unique_id)
        if node.fqdn:
            fqdn_to_node_ids[node.fqdn].append(node.unique_id)
        if "::" in node.unique_id:
            sym_part = node.unique_id.split("::", 1)[1]
            raw_without_prefix = sym_part.split(".", 1)[-1] if "." in sym_part else sym_part
            short_name_to_ids[raw_without_prefix].append(node.unique_id)

    caller_to_callees: Dict[str, Set[str]] = {n.unique_id: set() for n in nodes}

    for node in nodes:
        prefix_type = get_kind_prefix(node.symbol.kind)
        if prefix_type == "fn":
            for callee_name in node.symbol.callees:
                matched_ids = fqdn_to_node_ids.get(callee_name, [])
                if not matched_ids:
                    matched_ids = short_name_to_ids.get(callee_name, [])

                for target_id in matched_ids:
                    if target_id != node.unique_id and get_kind_prefix(id_to_node[target_id].symbol.kind) == "fn":
                        caller_to_callees[node.unique_id].add(target_id)
                        node.direct_callee_ids.add(target_id)

    base_types_and_vars = [n for n in nodes if get_kind_prefix(n.symbol.kind) in ("const", "type", "var")]
    for n in base_types_and_vars:
        n.dag_level = 0

    fn_nodes = [n for n in nodes if get_kind_prefix(n.symbol.kind) == "fn"]
    fn_ids = [n.unique_id for n in fn_nodes]

    # Tarjan SCC
    sccs = tarjan_scc(fn_ids, caller_to_callees)

    node_to_scc_idx: Dict[str, int] = {}
    for scc_idx, scc_members in enumerate(sccs):
        for member_id in scc_members:
            node_to_scc_idx[member_id] = scc_idx
            if len(scc_members) > 1:
                id_to_node[member_id].scc_group_ids = [m for m in scc_members if m != member_id]

    # Condensation DAG construction
    scc_callees: Dict[int, Set[int]] = defaultdict(set)
    scc_callers: Dict[int, Set[int]] = defaultdict(set)

    for caller_id, callee_ids in caller_to_callees.items():
        if caller_id not in node_to_scc_idx:
            continue
        c_scc = node_to_scc_idx[caller_id]
        for callee_id in callee_ids:
            if callee_id not in node_to_scc_idx:
                continue
            target_scc = node_to_scc_idx[callee_id]
            if target_scc != c_scc:
                scc_callees[c_scc].add(target_scc)
                scc_callers[target_scc].add(c_scc)

    # Bottom-up topological ranking
    scc_rank: Dict[int, int] = {}
    queue = deque([i for i in range(len(sccs)) if len(scc_callees[i]) == 0])
    for i in queue:
        scc_rank[i] = 0

    resolved_sccs = set(queue)
    while queue:
        curr_scc = queue.popleft()
        for parent_scc in scc_callers[curr_scc]:
            if scc_callees[parent_scc].issubset(resolved_sccs):
                max_child_rank = max(scc_rank[c] for c in scc_callees[parent_scc])
                scc_rank[parent_scc] = max_child_rank + 1
                resolved_sccs.add(parent_scc)
                queue.append(parent_scc)

    for i in range(len(sccs)):
        if i not in scc_rank:
            scc_rank[i] = 0

    # Assign DAG levels
    level_groups: Dict[int, List[SymbolNode]] = defaultdict(list)
    if base_types_and_vars:
        level_groups[0].extend(base_types_and_vars)

    for scc_idx, members in enumerate(sccs):
        rank = scc_rank[scc_idx]
        node_level = rank + (1 if base_types_and_vars else 0)
        for member_id in members:
            node = id_to_node[member_id]
            node.dag_level = node_level
            level_groups[node_level].append(node)

    max_lvl = max(level_groups.keys()) if level_groups else 0
    levels_list = [level_groups[i] for i in range(max_lvl + 1) if level_groups[i]]
    return levels_list


def order_symbols_bottom_up(nodes: List[SymbolNode]) -> List[SymbolNode]:
    """Flattened bottom-up order."""
    levels = order_symbols_by_levels(nodes)
    flat: List[SymbolNode] = []
    for lvl in levels:
        flat.extend(lvl)
    return flat


def build_callee_context_summary(
    node: SymbolNode,
    resolved_symbols: Dict[str, SymbolNode],
) -> str:
    """Build summary text of called low-level functions and mutual recursion peers for LLM prompt."""
    lines: List[str] = []

    if node.scc_group_ids:
        peer_names = []
        for peer_id in node.scc_group_ids:
            peer_node = resolved_symbols.get(peer_id)
            if peer_node:
                peer_names.append(f"`{peer_node.symbol.name}` ({peer_node.rel_path.name})")
        if peer_names:
            lines.append("[Mutual Recursion Group]:")
            lines.append(f"- Note: This function operates in mutual recursion with {', '.join(peer_names)}.")
            lines.append("")

    if node.direct_callee_ids:
        lines.append("[Direct Callees Summary]:")
        for callee_id in sorted(node.direct_callee_ids):
            callee_node = resolved_symbols.get(callee_id)
            if callee_node:
                sym = callee_node.symbol
                purpose = sym.purpose or "Executes operation"
                inputs = sym.inputs_note or ", ".join(f"{p.name}: {p.type_hint}" for p in sym.parameters) or "None"
                outputs = sym.outputs_note or sym.return_type or "None"
                lines.append(f"- Function `{sym.name}` (FQDN: `{sym.fqdn or sym.name}`, File: `{callee_node.rel_path.name}`):")
                lines.append(f"  - Purpose: {purpose}")
                lines.append(f"  - Inputs: {inputs}")
                lines.append(f"  - Outputs: {outputs}")
                if sym.overview:
                    first_lines = sym.overview.strip().splitlines()[:2]
                    lines.append(f"  - Summary: {' / '.join(l.strip() for l in first_lines)}")

    return "\n".join(lines)
