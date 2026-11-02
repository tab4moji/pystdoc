"""Tarjan strongly connected components.

Purpose:
    Compute SCCs of the function call graph in O(V+E) time so that
    mutual recursion groups can be processed together.

Change history:
    1. 2026-11-02 (v0.8.3): Split out of call_graph.py (no logic change).
"""

from typing import Dict, List, Set


def tarjan_scc(
    node_ids: List[str], adj: Dict[str, Set[str]]
) -> List[List[str]]:
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
