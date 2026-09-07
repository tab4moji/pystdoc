"""Tests for progress bar and tracker utilities."""

import io
import threading
from pathlib import Path
from pystdoc.db import DocgenDB
from pystdoc.design_engine import (
    generate_data_models_doc,
    generate_execution_model_doc,
    generate_module_docs,
    generate_overview_doc,
)
from pystdoc.progress import (
    is_terminal,
    render_pip_bar,
    format_progress_line,
    PhaseProgressTracker,
)


def test_is_terminal():
    class DummyTTY:
        def isatty(self):
            return True

    class DummyNonTTY:
        def isatty(self):
            return False

    class BrokenStream:
        def isatty(self):
            raise RuntimeError("broken")

    assert is_terminal(DummyTTY()) is True
    assert is_terminal(DummyNonTTY()) is False
    assert is_terminal(BrokenStream()) is False
    assert isinstance(is_terminal(), bool)


def test_render_pip_bar():
    bar_0 = render_pip_bar(0, 0, width=10)
    assert bar_0 == "[━━━━━━━━━━]"

    bar_half = render_pip_bar(5, 10, width=10)
    assert bar_half == "[━━━━━     ]"

    bar_full = render_pip_bar(10, 10, width=10)
    assert bar_full == "[━━━━━━━━━━]"

    bar_over = render_pip_bar(15, 10, width=10)
    assert bar_over == "[━━━━━━━━━━]"

    bar_under = render_pip_bar(-5, 10, width=10)
    assert bar_under == "[          ]"


def test_format_progress_line():
    line_tty = format_progress_line(
        phase_label="Step 1/4 docgen",
        current=5,
        total=10,
        extra="src/main.py",
        elapsed=1.23,
        is_tty=True,
        width=10,
    )
    assert "[Step 1/4 docgen]" in line_tty
    assert "[━━━━━     ]" in line_tty
    assert "5/10 ( 50.0%)" in line_tty
    assert "[Done in   1.2s]" in line_tty
    assert ": src/main.py" in line_tty

    # TTY with empty extra
    line_tty_empty = format_progress_line(
        phase_label="Step 1/4 docgen",
        current=5,
        total=10,
        extra="",
        is_tty=True,
        width=10,
    )
    assert "[Step 1/4 docgen]" in line_tty_empty
    assert line_tty_empty.endswith("5/10 ( 50.0%)")

    # TTY with long extra (testing truncation)
    long_extra = "a" * 200
    line_tty_long = format_progress_line(
        phase_label="Step 1/4 docgen",
        current=5,
        total=10,
        extra=long_extra,
        is_tty=True,
        width=10,
    )
    assert "..." in line_tty_long

    line_nontty = format_progress_line(
        phase_label="Step 1/4 docgen",
        current=10,
        total=10,
        extra="src/main.py",
        elapsed=None,
        is_tty=False,
    )
    assert "[Step 1/4 docgen]" in line_nontty
    assert "━" not in line_nontty
    assert "10/10 (100.0%)" in line_nontty
    assert ": src/main.py" in line_nontty

    line_def = format_progress_line(
        phase_label="Step 3/4 designgen",
        current=0,
        total=0,
    )
    assert "[Step 3/4 designgen]" in line_def
    assert "0/0 (100.0%)" in line_def


def test_phase_progress_tracker():
    stream = io.StringIO()
    tracker = PhaseProgressTracker(
        phase_label="Step 1/4 docgen",
        total=5,
        is_tty=True,
        width=10,
        stream=stream,
    )
    assert tracker.total == 5
    assert tracker.current == 0

    l1 = tracker.advance(1, extra="sym1", elapsed=0.5)
    assert "1/5 ( 20.0%)" in l1
    assert "sym1" in l1
    assert "\r" in stream.getvalue()

    cur = tracker.render_current(extra="sym1_current")
    assert "1/5 ( 20.0%)" in cur
    assert "sym1_current" in cur

    tracker.advance(10, extra="done")
    assert tracker.current == 5

    tracker.finish(extra="done")
    assert "\n" in stream.getvalue()
    # Double finish should be safe no-op
    tracker.finish()

    tracker2 = PhaseProgressTracker(
        "Step 3/4 designgen", total=100, is_tty=False
    )
    threads = []
    for _ in range(10):
        t = threading.Thread(
            target=lambda: [tracker2.advance(1) for _ in range(10)]
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert tracker2.current == 100
    tracker2.finish()


def test_design_engine_cached_without_tracker(tmp_path: Path):
    docgen_dir = tmp_path / ".docgen"
    design_dir = docgen_dir / "design"
    design_dir.mkdir(parents=True)
    db = DocgenDB(docgen_dir / "index.db")

    # 1. data_models without tracker (first run + cached run)
    type_docs = [{"file_name": "t.md", "signature": "int", "purpose": "type"}]
    var_docs = [{"file_name": "v.md", "signature": "int", "purpose": "var"}]
    dm1 = generate_data_models_doc(
        type_docs, var_docs, None, tmp_path, db, tracker=None
    )
    dm2 = generate_data_models_doc(
        type_docs, var_docs, None, tmp_path, db, tracker=None
    )
    assert dm1 == dm2

    # 2. execution_model without tracker
    fn_docs = [{
        "file_name": "f.md", "signature": "void()",
        "purpose": "fn", "callees": [], "ui_role": ""
    }]
    em1 = generate_execution_model_doc(
        fn_docs, None, tmp_path, db, tracker=None
    )
    em2 = generate_execution_model_doc(
        fn_docs, None, tmp_path, db, tracker=None
    )
    assert em1 == em2

    # 3. modules without tracker
    modules = {"core": [{"file_name": "c.md", "kind": "fn", "purpose": "p"}]}
    m1 = generate_module_docs(
        modules, None, tmp_path, db, tracker=None
    )
    m2 = generate_module_docs(
        modules, None, tmp_path, db, tracker=None
    )
    assert m1 == m2

    # 4. overview without tracker
    ov1 = generate_overview_doc(
        dm1, em1, m1, None, tmp_path, db, tracker=None
    )
    ov2 = generate_overview_doc(
        dm1, em1, m1, None, tmp_path, db, tracker=None
    )
    assert ov1 == ov2
    db.close()
