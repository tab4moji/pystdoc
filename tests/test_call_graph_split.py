"""Regression tests for the v0.8.3 call_graph split and speed fixes."""

import io
import re
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from pystdoc import call_graph
from pystdoc.call_graph import (
    SymbolNode,
    link_variables_to_functions,
    order_symbols_by_levels,
)
from pystdoc.level_graph import rank_sccs
from pystdoc.symbols import Symbol, get_kind_prefix

SOURCE = (
    "LIMIT = 3\n"
    "def alpha():\n"
    "    return LIMIT + beta()\n"
    "def beta():\n"
    "    return 1\n"
    "def gamma():\n"
    "    return LIMITED\n"
)


def make_node(root, name, kind, start, end, callees=None):
    sym = Symbol(
        name=name, kind=kind, line_start=start, line_end=end,
        callees=callees or [],
    )
    return SymbolNode(
        symbol=sym,
        rel_path=Path("m.py"),
        full_path=root / "m.py",
        unique_id=f"m.py::{get_kind_prefix(kind)}.{name}",
    )


def reference_link(nodes):
    """Former brute-force semantics, used as the oracle."""
    fns = [n for n in nodes if get_kind_prefix(n.symbol.kind) == "fn"]
    out = {}
    for t in nodes:
        if get_kind_prefix(t.symbol.kind) not in ("var", "const", "type"):
            continue
        refs = set()
        for f in fns:
            lines = f.full_path.read_text().splitlines()
            code = "\n".join(
                lines[max(0, f.symbol.line_start - 1):f.symbol.line_end]
            )
            inside = f.symbol.line_start <= t.symbol.line_start
            inside = inside and t.symbol.line_start <= f.symbol.line_end
            if inside or re.search(rf"\b{re.escape(t.symbol.name)}\b", code):
                refs.add(f.unique_id)
        out[t.unique_id] = refs
    return out


class TestLinkEquivalence(unittest.TestCase):
    def test_matches_reference_and_whole_word_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text(SOURCE)
            nodes = [
                make_node(root, "LIMIT", "variable", 1, 1),
                make_node(root, "~odd", "variable", 1, 1),
                make_node(root, "alpha", "function", 2, 3),
                make_node(root, "beta", "function", 4, 5),
                make_node(root, "gamma", "function", 6, 7),
            ]
            link_variables_to_functions(nodes)
            expected = reference_link(nodes)
            for node in nodes[:2]:
                self.assertEqual(
                    node.direct_caller_ids, expected[node.unique_id]
                )
            self.assertEqual(
                nodes[0].symbol.referencing_functions,
                ["`alpha` (`m.py`)"],
            )

    def test_unreadable_file_warns_on_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nodes = [
                make_node(root, "V", "variable", 1, 1),
                make_node(root, "f", "function", 2, 3),
            ]
            err = io.StringIO()
            with redirect_stderr(err):
                link_variables_to_functions(nodes)
            self.assertIn("Warning: cannot read", err.getvalue())
            self.assertEqual(nodes[0].symbol.referencing_functions, [])


class TestOrdering(unittest.TestCase):
    def test_layered_graph_is_fast_and_ranked(self):
        depth, width = 24, 3
        callees = {i: set() for i in range(depth * width)}
        callers = {i: set() for i in range(depth * width)}
        for layer in range(1, depth):
            for a in range(width):
                for b in range(width):
                    hi = layer * width + a
                    lo = (layer - 1) * width + b
                    callees[hi].add(lo)
                    callers[lo].add(hi)
        start = time.perf_counter()
        rank = rank_sccs(depth * width, callees, callers)
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertEqual(rank[0], 0)
        self.assertEqual(rank[(depth - 1) * width], depth - 1)

    def test_levels_put_callees_first(self):
        root = Path(".")
        nodes = [
            make_node(root, "top", "function", 1, 2, ["mid"]),
            make_node(root, "mid", "function", 3, 4, ["leaf"]),
            make_node(root, "leaf", "function", 5, 6),
        ]
        levels = order_symbols_by_levels(nodes)
        names = [[n.symbol.name for n in lv] for lv in levels]
        self.assertEqual(names, [["leaf"], ["mid"], ["top"]])

    def test_facade_exports(self):
        for name in call_graph.__all__:
            self.assertTrue(hasattr(call_graph, name), name)


if __name__ == "__main__":
    unittest.main()
