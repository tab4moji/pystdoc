"""Callee context summary builder for LLM prompts.

Purpose:
    Build a text summary of directly called functions and mutual
    recursion peers of a symbol node, used as bottom-up LLM context.

Change history:
    1. 2026-11-02 (v0.8.3): Split out of call_graph.py (no logic change).
"""

from typing import Dict, List

from pystdoc.call_graph_nodes import SymbolNode


def build_callee_context_summary(
    node: SymbolNode,
    resolved_symbols: Dict[str, SymbolNode],
) -> str:
    """Build summary text of called functions and recursion peers for LLM."""
    lines: List[str] = []

    if node.scc_group_ids:
        peer_names = []
        for peer_id in node.scc_group_ids:
            peer_node = resolved_symbols.get(peer_id)
            if peer_node:
                peer_names.append(
                    f"`{peer_node.symbol.name}` ({peer_node.rel_path.name})"
                )
        if peer_names:
            lines.append("[Mutual Recursion Group]:")
            lines.append(
                f"- Note: This function operates in mutual recursion "
                f"with {', '.join(peer_names)}."
            )
            lines.append("")

    if node.direct_callee_ids:
        lines.append("[Direct Callees Summary]:")
        for callee_id in sorted(node.direct_callee_ids):
            callee_node = resolved_symbols.get(callee_id)
            if callee_node:
                sym = callee_node.symbol
                purpose = sym.purpose or "Executes operation"
                params_str = ", ".join(
                    f"{p.name}: {p.type_hint}" for p in sym.parameters
                )
                inputs = sym.inputs_note or params_str or "None"
                outputs = sym.outputs_note or sym.return_type or "None"
                fqdn_str = sym.fqdn or sym.name
                lines.append(
                    f"- Function `{sym.name}` (FQDN: `{fqdn_str}`, "
                    f"File: `{callee_node.rel_path.name}`):"
                )
                lines.append(f"  - Purpose: {purpose}")
                lines.append(f"  - Inputs: {inputs}")
                lines.append(f"  - Outputs: {outputs}")
                if sym.overview:
                    first_lines = sym.overview.strip().splitlines()[:2]
                    summary_str = " / ".join(
                        line_item.strip() for line_item in first_lines
                    )
                    lines.append(f"  - Summary: {summary_str}")

    return "\n".join(lines)
