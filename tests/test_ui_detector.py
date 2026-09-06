import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pystdoc.design_engine import (
    generate_execution_model_doc,
    generate_overview_doc,
)
from pystdoc.report_engine import generate_readme_doc
from pystdoc.ui_detector import (
    annotate_documents_with_ui_context,
    detect_ui_type,
    infer_symbol_ui_role,
)


class TestUIDetector(unittest.TestCase):
    def test_detect_ui_type_all_patterns(self):
        # Test GUI patterns
        gui_samples = [
            ("Jetpack Compose", [
                {"raw_text": "@Composable fun MyScreen() { "
                             "remember { mutableStateOf(1) } }"}
            ], "GUI"),
            ("Android UI", [
                {"raw_text": "class MyActivity : Activity() { "
                             "fun onCreate() { findViewById(0) } }"}
            ], "GUI"),
            ("Java Swing", [
                {"raw_text": "JFrame frame = new JFrame(); "
                             "JButton btn = new JButton();"}
            ], "GUI"),
            ("JavaFX", [
                {"raw_text": "javafx.application.Application Stage Scene"}
            ], "GUI"),
            ("Qt", [
                {"raw_text": "class MainWindow(QMainWindow): "
                             "def __init__(self): QApplication([])"}
            ], "GUI"),
            ("Tkinter", [
                {"raw_text": "import tkinter as tk; root = tk.Tk(); "
                             "ttk.Button(root)"}
            ], "GUI"),
            ("GTK", [
                {"raw_text": "GtkWindow *win = gtk_window_new(); "
                             "GtkWidget *btn;"}
            ], "GUI"),
        ]
        for name, docs, expected in gui_samples:
            res = detect_ui_type(docs)
            self.assertEqual(res["ui_type"], expected, f"Failed for {name}")
            self.assertTrue(res["has_ui"])

        # Test TUI patterns
        tui_samples = [
            ("curses", [
                {"raw_text": "import curses\ncurses.initscr()\n"
                             "curses.wrefresh()"}
            ], "TUI"),
            ("prompt_toolkit", [
                {"raw_text": "from prompt_toolkit import Application\n"
                             "KeyBindings()"}
            ], "TUI"),
            ("rich", [
                {"raw_text": "from rich.live import Live\n"
                             "from rich.layout import Layout"}
            ], "TUI"),
            ("termion", [
                {"raw_text": "termion crossterm tview blessed"}
            ], "TUI"),
        ]
        for name, docs, expected in tui_samples:
            res = detect_ui_type(docs)
            self.assertEqual(res["ui_type"], expected, f"Failed for {name}")
            self.assertTrue(res["has_ui"])

        # Test CLI patterns
        cli_samples = [
            ("argparse", [
                {"raw_text": "parser = argparse.ArgumentParser(); "
                             "parser.add_argument('-f')"}
            ], "CLI"),
            ("click", [
                {"raw_text": "@click.command()\n@click.option('--name')"}
            ], "CLI"),
            ("typer", [
                {"raw_text": "app = typer.Typer()\n@app.command()"}
            ], "CLI"),
            ("getopt", [
                {"raw_text": "import getopt\nopts, args = getopt.getopt()"}
            ], "CLI"),
            ("sys.argv", [
                {"raw_text": "sys.argv os.environ"}
            ], "CLI"),
            ("c main argc", [
                {"raw_text": "int main(int argc, char** argv) { return 0; }"}
            ], "CLI"),
            ("java main args", [
                {"raw_text": "public static void main(String[] args) {}"}
            ], "CLI"),
        ]
        for name, docs, expected in cli_samples:
            res = detect_ui_type(docs)
            self.assertEqual(res["ui_type"], expected, f"Failed for {name}")
            self.assertTrue(res["has_ui"])

        # Test Library fallback
        res_lib = detect_ui_type([
            {"raw_text": "def compute_add(a, b): return a + b"}
        ])
        self.assertEqual(res_lib["ui_type"], "Library")
        self.assertFalse(res_lib["has_ui"])
        self.assertEqual(res_lib["framework"], "API / Module Library")

    def test_infer_symbol_ui_role(self):
        # GUI Japanese & English
        ui_gui = {"ui_type": "GUI", "framework": "Android UI"}
        vm_sym = {
            "file_name": "MainViewModel.kt",
            "signature": "",
            "kind": "",
        }
        self.assertIn(
            "UI画面の状態管理",
            infer_symbol_ui_role(vm_sym, ui_gui, "ja"),
        )
        self.assertIn(
            "Manages UI state",
            infer_symbol_ui_role(vm_sym, ui_gui, "en"),
        )

        comp_sym = {
            "file_name": "HomeScreen.kt",
            "raw_text": "@Composable",
            "kind": "view",
        }
        self.assertIn(
            "UI画面コンポーネントの描画",
            infer_symbol_ui_role(comp_sym, ui_gui, "ja"),
        )
        self.assertIn(
            "Renders UI components",
            infer_symbol_ui_role(comp_sym, ui_gui, "en"),
        )

        click_sym = {"file_name": "onButtonClick.kt", "kind": "function"}
        self.assertIn(
            "ユーザーのボタン操作",
            infer_symbol_ui_role(click_sym, ui_gui, "ja"),
        )
        self.assertIn(
            "Captures user clicks",
            infer_symbol_ui_role(click_sym, ui_gui, "en"),
        )

        state_sym = {"file_name": "UiStateModel.kt", "kind": "class"}
        self.assertIn(
            "表示用状態データ",
            infer_symbol_ui_role(state_sym, ui_gui, "ja"),
        )
        self.assertIn(
            "Holds view-bound state data",
            infer_symbol_ui_role(state_sym, ui_gui, "en"),
        )

        util_sym = {"file_name": "UtilHelper.kt", "kind": "function"}
        self.assertIn(
            "GUIアプリケーションの内部処理",
            infer_symbol_ui_role(util_sym, ui_gui, "ja"),
        )
        self.assertIn(
            "Supports GUI internal processing",
            infer_symbol_ui_role(util_sym, ui_gui, "en"),
        )

        # CLI Japanese & English
        ui_cli = {"ui_type": "CLI", "framework": "argparse"}
        main_sym = {"file_name": "main.py", "kind": "function"}
        self.assertIn(
            "コマンドライン引数",
            infer_symbol_ui_role(main_sym, ui_cli, "ja"),
        )
        self.assertIn(
            "Parses CLI arguments",
            infer_symbol_ui_role(main_sym, ui_cli, "en"),
        )

        out_sym = {"file_name": "log_output.py", "kind": "function"}
        self.assertIn(
            "標準出力",
            infer_symbol_ui_role(out_sym, ui_cli, "ja"),
        )
        self.assertIn(
            "Controls terminal standard output",
            infer_symbol_ui_role(out_sym, ui_cli, "en"),
        )

        pipe_sym = {"file_name": "worker.py", "kind": "function"}
        self.assertIn(
            "CLIツールの実行パイプライン",
            infer_symbol_ui_role(pipe_sym, ui_cli, "ja"),
        )
        self.assertIn(
            "Executes processing in CLI execution pipeline",
            infer_symbol_ui_role(pipe_sym, ui_cli, "en"),
        )

        # TUI Japanese & English
        ui_tui = {"ui_type": "TUI", "framework": "curses"}
        draw_sym = {"file_name": "draw_screen.py", "kind": "function"}
        self.assertIn(
            "ターミナル画面のリアルタイム描画",
            infer_symbol_ui_role(draw_sym, ui_tui, "ja"),
        )
        self.assertIn(
            "Renders terminal UI screens",
            infer_symbol_ui_role(draw_sym, ui_tui, "en"),
        )

        key_sym = {"file_name": "key_handler.py", "kind": "function"}
        self.assertIn(
            "キーバインド入力",
            infer_symbol_ui_role(key_sym, ui_tui, "ja"),
        )
        self.assertIn(
            "Handles keyboard navigation",
            infer_symbol_ui_role(key_sym, ui_tui, "en"),
        )

        tui_st_sym = {"file_name": "app_state.py", "kind": "class"}
        self.assertIn(
            "TUIアプリケーションの画面状態",
            infer_symbol_ui_role(tui_st_sym, ui_tui, "ja"),
        )
        self.assertIn(
            "Manages TUI screen state",
            infer_symbol_ui_role(tui_st_sym, ui_tui, "en"),
        )

        # Library Japanese & English
        ui_lib = {"ui_type": "Library", "framework": "API / Module Library"}
        lib_sym = {"file_name": "calc.py", "kind": "function"}
        self.assertIn(
            "ライブラリの公開API",
            infer_symbol_ui_role(lib_sym, ui_lib, "ja"),
        )
        self.assertIn(
            "Provides public API endpoints",
            infer_symbol_ui_role(lib_sym, ui_lib, "en"),
        )

    def test_annotate_documents_with_ui_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "documents"
            docs_dir.mkdir(parents=True)

            # Non-existent dir test
            self.assertEqual(
                annotate_documents_with_ui_context(tmp_path / "not_exist", {}),
                0,
            )

            # Create sample symbol doc with snippet section
            doc1 = docs_dir / "sym1.md"
            doc1.write_text(
                "# Symbol sym1\n- **Symbol Kind**: `function`\n"
                "- **Signature**: `def run()`\n\n## Overview\nTest sym\n\n"
                "## Source Code Snippet\n```python\npass\n```\n",
                encoding="utf-8",
            )
            # Create sample symbol doc without snippet section
            doc2 = docs_dir / "sym2.md"
            doc2.write_text(
                "# Symbol sym2\n- **Kind**: `class`\n"
                "- **Type**: `MainViewModel`\n\n## Overview\nTest sym 2\n",
                encoding="utf-8",
            )
            # Create a subdirectory with a doc
            sub_dir = docs_dir / "sub"
            sub_dir.mkdir()
            doc3 = sub_dir / "sym3.md"
            doc3.write_text(
                "# Symbol sym3\n- **Kind**: `method`\n",
                encoding="utf-8",
            )

            # Create a non-file directory named *.md inside documents
            dummy_dir = docs_dir / "not_a_file.md"
            dummy_dir.mkdir()

            ui_info = {"ui_type": "CLI", "framework": "argparse"}
            count = annotate_documents_with_ui_context(
                docs_dir, ui_info, language="English"
            )
            self.assertEqual(count, 3)

            # Check that re-running skips already annotated files
            count2 = annotate_documents_with_ui_context(
                docs_dir, ui_info, language="English"
            )
            self.assertEqual(count2, 0)

            # Verify contents
            t1 = doc1.read_text(encoding="utf-8")
            self.assertIn("## UI & Interaction Role", t1)
            self.assertIn("- **UI Type**: `CLI` (argparse)", t1)
            self.assertIn("- **Interaction Specification**:", t1)
            self.assertIn("## Source Code Snippet", t1)

    def test_design_engine_with_ui_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docgen_dir = tmp_path / ".docgen"
            design_dir = docgen_dir / "design"
            docs_dir = docgen_dir / "documents"
            docs_dir.mkdir(parents=True)

            doc1 = docs_dir / "main.md"
            doc1.write_text(
                "# Symbol main\n- **Kind**: `function`\n"
                "- **Signature**: `def main(argc, argv)`\n"
                "- **Interaction Specification**: CLI dispatcher\n\n"
                "## Source Code Snippet\n```c\nint main() {}\n```",
                encoding="utf-8",
            )

            ui_info = {
                "ui_type": "CLI",
                "framework": "argparse",
                "has_ui": True,
            }

            mock_llm = MagicMock()
            overview_ret = (
                "## Architecture Overview\nObjective system overview."
            )
            mock_llm.generate.return_value = overview_ret
            mock_llm.chat_completion.return_value = overview_ret

            fn_docs = [{
                "file_name": "main.py",
                "signature": "def main()",
                "purpose": "CLI entry",
                "callees": ["parse_args"],
                "ui_role": "Command dispatcher",
            }]

            # Execution model with ui_info
            generate_execution_model_doc(
                fn_docs=fn_docs,
                llm_client=mock_llm,
                target_dir=tmp_path,
                ui_info=ui_info,
            )
            self.assertTrue((design_dir / "execution_model.md").exists())

            # Overview doc with ui_info
            generate_overview_doc(
                data_models_content="## Data Models\nModel info",
                execution_model_content="## Execution Model\nExec info",
                module_summaries={"main": "Main module summary"},
                llm_client=mock_llm,
                target_dir=tmp_path,
                ui_info=ui_info,
            )
            self.assertTrue((design_dir / "overview.md").exists())

            # Test reportgen generate_readme_doc extracting symbol_ui_snippets
            generate_readme_doc(
                target_dir=tmp_path,
                llm_client=mock_llm,
                allow_fallback=True,
            )
            self.assertTrue((docgen_dir / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
