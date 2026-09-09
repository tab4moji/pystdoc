"""Tests for CLI query subcommands (list, functions, variables, desc)."""

from pathlib import Path
import pytest
from pystdoc.db import DocgenDB
from pystdoc.query import (
    _find_markdown_doc,
    locate_features,
    run_description,
    run_functions,
    run_impact,
    run_list,
    run_locate,
    run_types,
    run_variables,
    trace_impact,
)
from pystdoc.symbols import Symbol


@pytest.fixture
def sample_docgen_dir(tmp_path):
    """Setup a mock .pystdoc structure with DB and markdown docs."""
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    docs_dir = docgen / "documents"
    docs_dir.mkdir(parents=True)

    # 1. files.txt
    files_txt = docgen / "files.txt"
    files_txt.write_text("src/main.c\nsrc/utils.py\n", encoding="utf-8")

    # 2. SQLite DB
    db_path = docgen / "index.db"
    with DocgenDB(db_path) as db:
        db.update_file_hash("src/main.c", "hash_c")
        db.update_file_hash("src/utils.py", "hash_py")

        sym_main = Symbol(
            name="main",
            kind="function",
            line_start=10,
            line_end=25,
            fqdn="Userlib.main",
            signature="int main(int argc, char **argv)",
            purpose="Entry point of application",
            overview="Initializes resources and enters event loop.",
        )
        db.save_symbol_metadata(
            "src/main.c::func.main", sym_main, "src/main.c"
        )
        db.save_symbol_cache(
            "src/main.c::func.main",
            {
                "purpose": sym_main.purpose,
                "overview": sym_main.overview,
                "top_down_context": "Root dispatcher",
            },
        )

        sym_helper = Symbol(
            name="helper_calc",
            kind="function",
            line_start=30,
            line_end=40,
            fqdn="utils.helper_calc",
            signature="def helper_calc(x: int) -> int",
        )
        db.save_symbol_metadata(
            "src/utils.py::func.helper_calc", sym_helper, "src/utils.py"
        )

        sym_var = Symbol(
            name="MAX_COUNT",
            kind="const",
            line_start=5,
            line_end=5,
            fqdn="config.MAX_COUNT",
            signature="const int MAX_COUNT = 100",
        )
        db.save_symbol_metadata(
            "src/config.h::const.MAX_COUNT", sym_var, "src/config.h"
        )

        sym_member = Symbol(
            name="count",
            kind="field",
            line_start=12,
            line_end=12,
            fqdn="Counter.count",
            signature="val count: Int",
        )
        db.save_symbol_metadata(
            "src/Counter.kt::field.count", sym_member, "src/Counter.kt"
        )

        sym_type = Symbol(
            name="Point",
            kind="struct",
            line_start=1,
            line_end=8,
            fqdn="geometry.Point",
            signature="struct Point { int x; int y; }",
        )
        db.save_symbol_metadata(
            "src/geometry.h::struct.Point", sym_type, "src/geometry.h"
        )

    # 3. Markdown files
    fn_md = docs_dir / "src/main.c.fn.main.md"
    fn_md.parent.mkdir(parents=True, exist_ok=True)
    fn_md.write_text(
        "# Function Documentation: `main`\n\nMain entry point of the tool.",
        encoding="utf-8",
    )

    return tmp_path


def test_run_list_normal(sample_docgen_dir, capsys):
    ret = run_list(sample_docgen_dir)
    assert ret == 0
    out = capsys.readouterr().out
    assert "src/main.c" in out
    assert "src/utils.py" in out


def test_run_list_missing_docgen(tmp_path, capsys):
    ret = run_list(tmp_path)
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: .pystdoc directory not found" in err


def test_run_list_db_fallback(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir()
    db_path = docgen / "index.db"
    with DocgenDB(db_path) as db:
        db.update_file_hash("lib/test.c", "hash1")

    ret = run_list(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "lib/test.c" in out


def test_run_list_docs_fallback(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc" / "documents"
    docgen.mkdir(parents=True)
    (docgen / "src_test.c.md").write_text("dummy", encoding="utf-8")

    ret = run_list(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "src_test.c" in out


def test_run_list_empty(tmp_path, capsys):
    (tmp_path / ".pystdoc").mkdir()
    ret = run_list(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "No source files found in .pystdoc." in out


def test_run_functions_normal(sample_docgen_dir, capsys):
    ret = run_functions(sample_docgen_dir)
    assert ret == 0
    out = capsys.readouterr().out
    assert "Userlib.main (src/main.c:10:25)" in out
    assert "utils.helper_calc (src/utils.py:30:40)" in out


def test_run_functions_missing_docgen(tmp_path, capsys):
    ret = run_functions(tmp_path)
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: .pystdoc directory not found" in err


def test_run_functions_docs_fallback(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc" / "documents"
    docgen.mkdir(parents=True)
    (docgen / "test.c.fn.calc_sum.md").write_text("dummy", encoding="utf-8")

    ret = run_functions(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "calc_sum" in out


def test_run_functions_empty(tmp_path, capsys):
    (tmp_path / ".pystdoc").mkdir()
    ret = run_functions(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "No functions found in .pystdoc." in out


def test_run_variables_normal(sample_docgen_dir, capsys):
    ret = run_variables(sample_docgen_dir)
    assert ret == 0
    out = capsys.readouterr().out
    assert "config.MAX_COUNT (src/config.h:5:5)" in out
    assert "Counter.count (src/Counter.kt:12:12)" in out


def test_run_variables_missing_docgen(tmp_path, capsys):
    ret = run_variables(tmp_path)
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: .pystdoc directory not found" in err


def test_run_variables_docs_fallback(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc" / "documents"
    docgen.mkdir(parents=True)
    (docgen / "test.c.var.g_state.md").write_text("dummy", encoding="utf-8")
    (docgen / "test.c.const.MAX_VAL.md").write_text("dummy", encoding="utf-8")

    ret = run_variables(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "g_state" in out
    assert "MAX_VAL" in out


def test_run_variables_empty(tmp_path, capsys):
    (tmp_path / ".pystdoc").mkdir()
    ret = run_variables(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "No variables or constants found in .pystdoc." in out


def test_run_description_exact_and_colon(sample_docgen_dir, capsys):
    # Test dot query
    ret = run_description(sample_docgen_dir, "Userlib.main")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Symbol: Userlib.main" in out
    assert "Source: src/main.c (Lines: 10-25)" in out
    assert "# Function Documentation: `main`" in out

    # Test :: colon query
    ret2 = run_description(sample_docgen_dir, "Userlib::main")
    assert ret2 == 0
    out2 = capsys.readouterr().out
    assert "Symbol: Userlib.main" in out2


def test_run_description_cached_fallback(sample_docgen_dir, capsys):
    ret = run_description(sample_docgen_dir, "helper_calc")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Symbol: utils.helper_calc" in out
    assert "Source: src/utils.py (Lines: 30-40)" in out


def test_run_description_empty_query(sample_docgen_dir, capsys):
    ret = run_description(sample_docgen_dir, "")
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: Please specify a symbol name" in err


def test_run_description_missing_docgen(tmp_path, capsys):
    ret = run_description(tmp_path, "main")
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: .pystdoc directory not found" in err


def test_run_description_not_found(sample_docgen_dir, capsys):
    ret = run_description(sample_docgen_dir, "non_existent_symbol")
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: Symbol 'non_existent_symbol' not found in .pystdoc." in err


def test_db_find_symbols_suffix_and_substring(sample_docgen_dir):
    db_path = sample_docgen_dir / ".pystdoc" / "index.db"
    with DocgenDB(db_path) as db:
        # 1. Suffix match (query="calc" matches fqdn "pkg.module.calc")
        db.save_symbol_metadata(
            "uid_suffix",
            Symbol(name="internal_calc", kind="fn", line_start=1,
                   line_end=2, fqdn="pkg.module.calc"),
            "src/pkg.py"
        )
        rows_suffix = db.find_symbols_by_query("calc")
        assert len(rows_suffix) > 0
        assert rows_suffix[0]["fqdn"] == "pkg.module.calc"

        # 2. Substring match
        rows_sub = db.find_symbols_by_query("odule")
        assert len(rows_sub) > 0
        assert rows_sub[0]["fqdn"] == "pkg.module.calc"


def test_query_exceptions_and_edge_cases(tmp_path, capsys, monkeypatch):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir()
    docs_dir = docgen / "documents"
    docs_dir.mkdir()

    # 1. files_txt exception & db exception in run_list
    files_txt = docgen / "files.txt"
    files_txt.write_text("invalid", encoding="utf-8")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(IOError("disk error")),
    )
    assert run_list(tmp_path) == 0

    # 2. db exception handling in run_functions/variables/description
    db_path = docgen / "index.db"
    db_path.write_text("corrupted db file", encoding="utf-8")
    monkeypatch.undo()

    assert run_functions(tmp_path) == 0
    assert run_variables(tmp_path) == 0
    assert run_description(tmp_path, "test") == 1

    # 3. test description docs fallback when no DB
    (docs_dir / "app.mod.fn.test_func.md").write_text(
        "# Test Func Doc", encoding="utf-8"
    )
    assert run_description(tmp_path, "test_func") == 0
    out = capsys.readouterr().out
    assert "# Test Func Doc" in out


def test_description_multiple_symbols_and_formats(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir()
    docs_dir = docgen / "documents"
    docs_dir.mkdir()
    db_path = docgen / "index.db"

    with DocgenDB(db_path) as db:
        sym1 = Symbol(
            name="test_fn",
            kind="function",
            line_start=10,
            line_end=None,
            fqdn="pkg.test_fn",
            signature="def test_fn()",
        )
        sym2 = Symbol(
            name="test_fn",
            kind="function",
            line_start=None,
            line_end=None,
            fqdn="",
            signature="",
        )
        sym3 = Symbol(
            name="test_fn3",
            kind="function",
            line_start=10,
            line_end=20,
            fqdn="pkg.test_fn3",
            signature="def test_fn3()",
        )
        db.save_symbol_metadata("uid1", sym1, "src/a.py")
        db.save_symbol_metadata("uid2", sym2, "")
        db.save_symbol_metadata("uid3", sym3, "src/c.py")

        # FQDN md file match
        a_md = docs_dir / "src/a.py.fn.pkg.test_fn.md"
        a_md.parent.mkdir(parents=True, exist_ok=True)
        a_md.write_text("Content A", encoding="utf-8")

        # Symbol cache fallback
        db.save_symbol_cache(
            "uid3",
            {
                "top_down_context": "Top down desc",
                "purpose": "Purpose desc",
                "overview": "Overview desc",
            },
        )

    # Test run_functions with rel_path / no line_start and no rel_path
    ret_fn = run_functions(tmp_path)
    assert ret_fn == 0

    # Test run_variables with no rel_path
    with DocgenDB(db_path) as db:
        db.save_symbol_metadata(
            "uid_var",
            Symbol(
                name="g_v", kind="var", line_start=None, line_end=None,
                fqdn="g_v"
            ),
            "",
        )
    ret_var = run_variables(tmp_path)
    assert ret_var == 0

    # Run description for test_fn (matches multiple)
    ret = run_description(tmp_path, "test_fn")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Content A" in out
    assert "No detailed markdown document found" in out
    assert "-" * 64 in out

    # Run description for test_fn3 (tests cache rendering)
    ret3 = run_description(tmp_path, "test_fn3")
    assert ret3 == 0
    out3 = capsys.readouterr().out
    assert "Purpose desc" in out3
    assert "Overview desc" in out3

    # Test cache rendering when purpose is missing but top_down_context exists
    with DocgenDB(db_path) as db:
        db.save_symbol_metadata(
            "uid4",
            Symbol(
                name="test_fn4", kind="function", line_start=1, line_end=1,
                fqdn="pkg.test_fn4"
            ),
            "src/d.py",
        )
        db.save_symbol_cache(
            "uid4",
            {
                "top_down_context": "Top down only desc",
                "purpose": "",
                "overview": "",
            },
        )
    ret4 = run_description(tmp_path, "test_fn4")
    assert ret4 == 0
    out4 = capsys.readouterr().out
    assert "Top down only desc" in out4


def test_find_markdown_doc_missing_dir(tmp_path):
    res = _find_markdown_doc(
        tmp_path / "non_existent_docs", "test.py", "fn", "fn", "fn"
    )
    assert res is None


def test_query_additional_coverage_branches(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir()
    db_path = docgen / "index.db"

    # DB exception in run_list when files.txt does not exist
    db_path.write_text("corrupt db", encoding="utf-8")
    assert run_list(tmp_path) == 0

    # rel_path exists but line_start is None
    db_path.unlink()
    with DocgenDB(db_path) as db:
        db.save_symbol_metadata(
            "uid_fn_noline",
            Symbol(
                name="noline_fn", kind="function", line_start=None,
                line_end=None, fqdn="pkg.noline_fn"
            ),
            "src/noline.py",
        )
        db.save_symbol_metadata(
            "uid_var_noline",
            Symbol(
                name="noline_var", kind="var", line_start=None,
                line_end=None, fqdn="pkg.noline_var"
            ),
            "src/noline.py",
        )

    assert run_functions(tmp_path) == 0
    out_fn = capsys.readouterr().out
    assert "pkg.noline_fn (src/noline.py)" in out_fn

    assert run_variables(tmp_path) == 0
    out_var = capsys.readouterr().out
    assert "pkg.noline_var (src/noline.py)" in out_var

    # rel_path exists and line_start exists but line_end is None
    with DocgenDB(db_path) as db:
        db.save_symbol_metadata(
            "uid_fn_start_only",
            Symbol(
                name="start_fn", kind="function", line_start=15,
                line_end=None, fqdn="pkg.start_fn"
            ),
            "src/start.py",
        )
        db.save_symbol_metadata(
            "uid_var_start_only",
            Symbol(
                name="start_var", kind="var", line_start=20,
                line_end=None, fqdn="pkg.start_var"
            ),
            "src/start.py",
        )

    assert run_functions(tmp_path) == 0
    out_fn2 = capsys.readouterr().out
    assert "pkg.start_fn (src/start.py:15:15)" in out_fn2

    assert run_variables(tmp_path) == 0
    out_var2 = capsys.readouterr().out
    assert "pkg.start_var (src/start.py:20:20)" in out_var2


def test_find_markdown_doc_nested_fqdn(tmp_path):
    docs_dir = tmp_path / ".pystdoc" / "documents"
    docs_dir.mkdir(parents=True)
    # Create file matching tail parts
    target_md = docs_dir / "src/Main.kt.type.Model.prop.md"
    target_md.parent.mkdir(parents=True, exist_ok=True)
    target_md.write_text("Nested prop doc", encoding="utf-8")

    res = _find_markdown_doc(
        docs_dir=docs_dir,
        rel_path="src/Main.kt",
        sym_name="prop",
        fqdn="pkg.Model.prop",
        kind="field",
    )
    assert res == "Nested prop doc"


def test_run_types_normal(sample_docgen_dir, capsys):
    ret = run_types(sample_docgen_dir)
    assert ret == 0
    out = capsys.readouterr().out
    assert "geometry.Point (src/geometry.h:1:8)" in out


def test_run_types_missing_docgen(tmp_path, capsys):
    ret = run_types(tmp_path)
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error: .pystdoc directory not found" in err


def test_run_types_fallback_documents(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docs_dir = docgen / "documents"
    docs_dir.mkdir(parents=True)

    (docs_dir / "User.type.User.md").write_text("# User", encoding="utf-8")
    (docs_dir / "Item.type.Item.md").write_text("# Item", encoding="utf-8")

    ret = run_types(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "Item" in out
    assert "User" in out


def test_run_types_empty(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    ret = run_types(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "No types or classes found in .pystdoc." in out


def test_run_types_db_corrupt_fallback(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    # create invalid DB file
    (docgen / "index.db").write_text("not a sqlite db", encoding="utf-8")
    ret = run_types(tmp_path)
    assert ret == 0
    out = capsys.readouterr().out
    assert "No types or classes found in .pystdoc." in out


def test_run_types_formatting_variations(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    db_path = docgen / "index.db"
    with DocgenDB(db_path) as db:
        # no rel_path
        db.save_symbol_metadata(
            "uid_t1",
            Symbol(
                name="T1", kind="class", line_start=None,
                line_end=None, fqdn="T1"
            ),
            "",
        )
        # rel_path + no line
        db.save_symbol_metadata(
            "uid_t2",
            Symbol(
                name="T2", kind="class", line_start=None,
                line_end=None, fqdn="T2"
            ),
            "src/t2.py",
        )
        # rel_path + line_start only
        db.save_symbol_metadata(
            "uid_t3",
            Symbol(
                name="T3", kind="class", line_start=10,
                line_end=None, fqdn="T3"
            ),
            "src/t3.py",
        )

    assert run_types(tmp_path) == 0
    out = capsys.readouterr().out
    assert "T1\n" in out
    assert "T2 (src/t2.py)\n" in out
    assert "T3 (src/t3.py:10:10)\n" in out


def test_locate_features_errors(tmp_path):
    # Empty query
    assert "Please provide" in locate_features(tmp_path, "   ")

    # No .pystdoc dir
    assert ".pystdoc directory not found" in locate_features(
        tmp_path, "some query"
    )

    # No index.db
    (tmp_path / ".pystdoc").mkdir(parents=True)
    assert "index database (.pystdoc/index.db) not found" in locate_features(
        tmp_path, "some query"
    )


def test_locate_features_full(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    db_path = docgen / "index.db"

    # Add design module
    modules_dir = docgen / "design" / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "notification_module.md").write_text(
        "# Notification Module\nデバッグ通知ボタンを消したい場合のガイド。",
        encoding="utf-8",
    )

    with DocgenDB(db_path) as db:
        sym_btn = Symbol(
            name="DebugButton",
            kind="function",
            line_start=10,
            line_end=20,
            fqdn="ui.DebugButton",
            signature="@Composable fun DebugButton(onClick: () -> Unit)",
            purpose="Renders the debug notification button.",
            overview="Displays a button for sending test FCM notifications.",
        )
        db.save_symbol_metadata(
            "src/ui/Debug.kt::func.DebugButton", sym_btn, "src/ui/Debug.kt"
        )
        db.save_symbol_cache(
            "src/ui/Debug.kt::func.DebugButton",
            {
                "purpose": sym_btn.purpose,
                "overview": sym_btn.overview,
                "direct_callers": ["ui.MainScreen"],
                "direct_callees": ["fcm.sendDebugNotification"],
            },
        )

        sym_line_start_only = Symbol(
            name="initDebug",
            kind="function",
            line_start=5,
            line_end=None,
            fqdn="debug.initDebug",
            signature="fun initDebug()",
            purpose="Initialize debug tools",
        )
        db.save_symbol_metadata(
            "src/debug/Init.kt::func.initDebug",
            sym_line_start_only,
            "src/debug/Init.kt",
        )
        db.save_symbol_cache(
            "src/debug/Init.kt::func.initDebug",
            {"purpose": "Initialize debug tools"},
        )

        sym_no_line = Symbol(
            name="DEBUG_FLAG",
            kind="const",
            line_start=None,
            line_end=None,
            fqdn="debug.DEBUG_FLAG",
            signature="const val DEBUG_FLAG = true",
        )
        db.save_symbol_metadata(
            "src/debug/Const.kt::const.DEBUG_FLAG",
            sym_no_line,
            "src/debug/Const.kt",
        )

    # 1. Locate UI feature (Japanese query)
    res_ja = locate_features(tmp_path, "デバッグ通知ボタンを消したい")
    assert "DebugButton" in res_ja
    assert "src/ui/Debug.kt" in res_ja
    assert "Lines 10-20" in res_ja
    assert "notification_module" in res_ja

    # 2. Locate line start only
    res_init = locate_features(tmp_path, "initDebug")
    assert "Line 5" in res_init

    # 3. Locate no line
    res_const = locate_features(tmp_path, "DEBUG_FLAG")
    assert "src/debug/Const.kt" in res_const

    # 4. Locate no match with module hint
    res_nomatch = locate_features(tmp_path, "notification")
    assert "notification_module" in res_nomatch

    # 5. Locate completely unknown
    (modules_dir / "notification_module.md").unlink()
    res_none = locate_features(tmp_path, "completely_unknown_xyz_123")
    assert "No specific symbols found matching" in res_none

    # 6. run_locate CLI
    ret = run_locate(tmp_path, "DebugButton")
    assert ret == 0
    out = capsys.readouterr().out
    assert "DebugButton" in out


def test_trace_impact_errors(tmp_path):
    # Empty symbol
    assert "Please specify" in trace_impact(tmp_path, "   ")

    # No .pystdoc dir
    assert ".pystdoc directory not found" in trace_impact(tmp_path, "MySymbol")

    # No index.db
    (tmp_path / ".pystdoc").mkdir(parents=True)
    assert "index database (.pystdoc/index.db) not found" in trace_impact(
        tmp_path, "MySymbol"
    )


def test_trace_impact_full(tmp_path, capsys):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    db_path = docgen / "index.db"

    with DocgenDB(db_path) as db:
        sym_btn = Symbol(
            name="DebugButton",
            kind="function",
            line_start=10,
            line_end=20,
            fqdn="ui.DebugButton",
            signature="@Composable fun DebugButton()",
            purpose="Debug trigger button.",
            referencing_functions=["ui.MainScreen", "ui.TestPanel"],
            callees=["fcm.sendDebugNotification"],
        )
        db.save_symbol_metadata(
            "src/ui/Debug.kt::func.DebugButton", sym_btn, "src/ui/Debug.kt"
        )
        db.save_symbol_cache(
            "src/ui/Debug.kt::func.DebugButton",
            {
                "purpose": sym_btn.purpose,
            },
        )

        sym_leaf = Symbol(
            name="leafNode",
            kind="function",
            line_start=50,
            line_end=None,
            fqdn="core.leafNode",
        )
        db.save_symbol_metadata(
            "src/core/Leaf.kt::func.leafNode", sym_leaf, "src/core/Leaf.kt"
        )
        db.save_symbol_cache(
            "src/core/Leaf.kt::func.leafNode",
            {"direct_callers": [], "direct_callees": []},
        )

    # 1. Trace symbol with callers and callees
    res_btn = trace_impact(tmp_path, "ui.DebugButton")
    assert "Impact & Dependency Analysis for `ui.DebugButton`" in res_btn
    assert "src/ui/Debug.kt" in res_btn
    assert "Lines 10-20" in res_btn
    assert "ui.MainScreen" in res_btn
    assert "ui.TestPanel" in res_btn
    assert "fcm.sendDebugNotification" in res_btn

    # 2. Trace leaf symbol without callers/callees
    res_leaf = trace_impact(tmp_path, "leafNode")
    assert "Line 50" in res_leaf
    assert "No direct internal callers detected" in res_leaf
    assert "No outbound symbol dependencies" in res_leaf

    # 3. Trace non-existent symbol
    res_nf = trace_impact(tmp_path, "NonExistentSymbol")
    assert "not found in index database" in res_nf

    # 4. run_impact CLI
    ret = run_impact(tmp_path, "DebugButton")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Impact & Dependency Analysis" in out


def test_locate_and_trace_coverage_branches(tmp_path):
    docgen = tmp_path / ".pystdoc"
    docgen.mkdir(parents=True)
    db_path = docgen / "index.db"

    # Add design module
    modules_dir = docgen / "design" / "modules"
    modules_dir.mkdir(parents=True)
    bad_module = modules_dir / "bad.md"
    bad_module.write_text("Test module content", encoding="utf-8")

    with DocgenDB(db_path) as db:
        sym_complex = Symbol(
            name="processData",
            kind="method",
            line_start=None,
            line_end=None,
            fqdn="data.processData",
            signature="def processData(val: int) -> bool",
            purpose="Process incoming stream records",
            overview="Transforms and filters raw data items",
            referencing_functions=["ui.Handler"],
            callees=["db.save"],
        )
        db.save_symbol_metadata(
            "src/data/Process.py::func.processData",
            sym_complex,
            "src/data/Process.py",
        )
        db.save_symbol_cache(
            "src/data/Process.py::func.processData",
            {
                "purpose": sym_complex.purpose,
                "overview": sym_complex.overview,
            },
        )

    # 1. Search matches purpose (substring & tokens)
    res_purp = locate_features(tmp_path, "incoming stream records")
    assert "processData" in res_purp

    # 2. Search matches overview
    res_ovw = locate_features(tmp_path, "filters raw data")
    assert "processData" in res_ovw

    # 3. Search matches token in sname and sig
    res_token = locate_features(tmp_path, "processData int")
    assert "processData" in res_token

    # 4. Search matches token in signature and test 1-char token
    res_sig = locate_features(tmp_path, "def processData(val: int) a")
    assert "processData" in res_sig

    # 5. Trace symbol with callers and callees and purpose
    res_trace = trace_impact(tmp_path, "processData")
    assert "data.processData" in res_trace
    assert "Process incoming stream records" in res_trace
    assert "ui.Handler" in res_trace
    assert "db.save" in res_trace

    # 6. Test corrupt JSON handling in trace_impact
    with DocgenDB(db_path) as db:
        cur = db.conn.cursor()
        cur.execute(
            "UPDATE symbols_metadata SET referencing_funcs_json = ?, "
            "callees_json = ? WHERE unique_id = ?",
            (
                "invalid json",
                "invalid json",
                "src/data/Process.py::func.processData",
            ),
        )
        db.conn.commit()

    res_corrupt = trace_impact(tmp_path, "processData")
    assert "No direct internal callers detected" in res_corrupt

    # 7. Test exception when reading module doc
    from unittest.mock import patch
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        res_err = locate_features(tmp_path, "processData")
        assert "processData" in res_err
