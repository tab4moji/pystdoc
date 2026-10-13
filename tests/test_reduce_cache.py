"""Tests for group-level caching in hierarchical_reduce_summaries."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pystdoc.db import DocgenDB
from pystdoc.design_engine import (
    chunk_list_stable,
    hierarchical_reduce_summaries,
)


def _items(n, changed=None):
    out = []
    for i in range(n):
        text = f"- Function `mod{i:04d}.fn.f{i}.md`: purpose of item {i} " * 3
        if changed is not None and i == changed:
            text += " CHANGED"
        out.append(text)
    return out


class TestReduceCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = DocgenDB(self.tmp / "index.db")

    def tearDown(self):
        self.db.close()

    def test_stable_chunking_localizes_change(self):
        a = chunk_list_stable(_items(300))
        b = chunk_list_stable(_items(300, changed=150))
        changed = sum(1 for c in b if c not in a)
        self.assertGreater(len(a), 5)
        self.assertLessEqual(changed, 2)
        self.assertEqual(sum(len(c) for c in a), 300)

    def test_group_cache_only_recomputes_changed_groups(self):
        llm = MagicMock()
        llm.chat_completion.side_effect = lambda m: "summary"
        hierarchical_reduce_summaries(
            _items(300), "Funcs", llm, language="Japanese", db=self.db
        )
        first_calls = llm.chat_completion.call_count
        self.assertGreater(first_calls, 5)

        llm.chat_completion.reset_mock()
        hierarchical_reduce_summaries(
            _items(300), "Funcs", llm, language="Japanese", db=self.db
        )
        self.assertEqual(llm.chat_completion.call_count, 0)

        llm.chat_completion.reset_mock()
        hierarchical_reduce_summaries(
            _items(300, changed=150), "Funcs", llm,
            language="Japanese", db=self.db,
        )
        self.assertLessEqual(llm.chat_completion.call_count, 4)
        self.assertGreater(llm.chat_completion.call_count, 0)

    def test_force_bypasses_group_cache(self):
        llm = MagicMock()
        llm.chat_completion.side_effect = lambda m: "summary"
        hierarchical_reduce_summaries(
            _items(100), "Funcs", llm, db=self.db
        )
        llm.chat_completion.reset_mock()
        hierarchical_reduce_summaries(
            _items(100), "Funcs", llm, db=self.db, force=True
        )
        self.assertGreater(llm.chat_completion.call_count, 0)


if __name__ == "__main__":
    unittest.main()
