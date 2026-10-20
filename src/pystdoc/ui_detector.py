"""UI detector: infers UI type (GUI/TUI/CLI/Library) & symbol docs."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pystdoc.cache import write_flushed_text
from pystdoc.doc_writer import normalize_language


def detect_ui_type(
    docs: List[Dict[str, Any]], raw_texts: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Detect UI classification (GUI / TUI / CLI / Library) and frameworks."""
    joined_text = "\n".join(
        [d.get("raw_text", "") for d in docs] + (raw_texts or [])
    )
    file_names = [d.get("file_name", "") for d in docs]

    gui_score = 0
    tui_score = 0
    cli_score = 0
    gui_evidences = []
    tui_evidences = []
    cli_evidences = []
    has_high_confidence_gui = False

    # 1. Check High-Confidence GUI indicators
    # (strictly avoid generic words like Stage/Scene)
    # Strictly NO JavaFX detection as per requirement.
    gui_patterns = [
        (r"@Composable\b|setContent\s*\{", "Jetpack Compose", True),
        (
            r"class\s+\w+\s*:\s*(?:Activity|AppCompatActivity|"
            r"ComponentActivity)\b|findViewById\(",
            "Android UI",
            True,
        ),
        (
            r"import\s+javax\.swing\b|new\s+JFrame\(|new\s+JButton\(",
            "Java Swing",
            True,
        ),
        (
            r"(?:from|import)\s+(?:PyQt[56]|PySide[26])|"
            r"QMainWindow\(|QApplication\(|QWidget\(",
            "Qt Framework",
            True,
        ),
        (
            r"(?:from|import)\s+tkinter\b|tk\.Tk\(|tkinter\.Tk\(|"
            r"ttk\.Button\(",
            "Tkinter",
            True,
        ),
        (
            r"gi\.repository\s+import\s+Gtk|import\s+gtk\b|"
            r"gtk_window_new|GtkWindow\s*\*",
            "GTK",
            True,
        ),
        (r"(?:from|import)\s+wx\b|wx\.App\(", "wxWidgets", True),
        (r"(?:from|import)\s+(?:kivy|flet)\b", "Kivy/Flet", True),
    ]
    for pattern, name, is_high_conf in gui_patterns:
        m = re.findall(pattern, joined_text, re.IGNORECASE)
        if m:
            gui_score += len(m) * 2
            gui_evidences.append(f"{name} ({len(m)} matches)")
            if is_high_conf:
                has_high_confidence_gui = True

    # 2. Check TUI indicators
    tui_patterns = [
        (r"curses|ncurses|initscr|wrefresh|addstr", "curses/ncurses"),
        (r"prompt_toolkit|Application\(|KeyBindings", "prompt_toolkit"),
        (r"rich\.live|rich\.layout|rich\.console\.Console", "rich TUI"),
        (r"termion|crossterm|tview|blessed", "Terminal UI lib"),
    ]
    for pattern, name in tui_patterns:
        m = re.findall(pattern, joined_text, re.IGNORECASE)
        if m:
            tui_score += len(m) * 2
            tui_evidences.append(f"{name} ({len(m)} matches)")

    # 3. Check CLI indicators (Prioritized)
    cli_patterns = [
        (r"argparse|ArgumentParser|add_argument|parse_args", "argparse"),
        (r"@click\.command|click\.option|@click\.group", "Click"),
        (r"typer\.Typer|typer\.Option|typer\.Argument", "Typer"),
        (r"getopt|docopt|picocli|CommandLine", "CLI Parser"),
        (r"sys\.argv|os\.environ|\bargc\b|\bargv\b", "Command-line args"),
        (r"if\s+__name__\s*==\s*['\"]__main__['\"]", "Python main entry"),
        (
            r"\bmain\s*\(\s*int\s+argc|\bmain\s*\(\s*String\s*\[\s*\]",
            "Standard main entry",
        ),
    ]
    for pattern, name in cli_patterns:
        m = re.findall(pattern, joined_text, re.IGNORECASE)
        if m:
            cli_score += len(m) * 3
            cli_evidences.append(f"{name} ({len(m)} matches)")

    # Check file names/paths for strong CLI evidence
    for fn in file_names:
        fn_lower = fn.lower()
        if any(
            tok in fn_lower
            for tok in ("/cli/", "cli.py", "_cli.", "-cli.", "cli/")
        ):
            cli_score += 15
            cli_evidences.append(f"CLI file path pattern: {fn}")
        elif any(tok in fn_lower for tok in ("main.py", "__main__.py")):
            cli_score += 5
            cli_evidences.append(f"Main entry script: {fn}")

    # Determine primary UI type with CLI PRIORITY:
    # Prioritize CLI unless GUI has high confidence and clearly dominates.
    if cli_score > 0 and (
        cli_score >= gui_score or not has_high_confidence_gui
    ):
        ui_type = "CLI"
        framework = (
            cli_evidences[0].split(" (")[0] if cli_evidences else "CLI"
        )
        evidences = cli_evidences
    elif gui_score > 0 and has_high_confidence_gui and gui_score > cli_score:
        ui_type = "GUI"
        framework = gui_evidences[0].split(" (")[0] if gui_evidences else "GUI"
        evidences = gui_evidences
    elif tui_score > 0 and tui_score >= cli_score:
        ui_type = "TUI"
        framework = tui_evidences[0].split(" (")[0] if tui_evidences else "TUI"
        evidences = tui_evidences
    elif cli_score > 0:
        ui_type = "CLI"
        framework = cli_evidences[0].split(" (")[0] if cli_evidences else "CLI"
        evidences = cli_evidences
    elif gui_score > 0 and has_high_confidence_gui:
        ui_type = "GUI"
        framework = gui_evidences[0].split(" (")[0] if gui_evidences else "GUI"
        evidences = gui_evidences
    else:
        ui_type = "Library"
        framework = "API / Module Library"
        evidences = ["No standalone GUI/TUI/CLI entry detected"]

    return {
        "ui_type": ui_type,
        "framework": framework,
        "score_gui": gui_score,
        "score_tui": tui_score,
        "score_cli": cli_score,
        "evidences": evidences,
        "has_ui": ui_type in ("GUI", "TUI", "CLI"),
    }


def infer_symbol_ui_role(
    sym_data: Dict[str, Any],
    ui_info: Dict[str, Any],
    language: str = "English",
) -> str:
    """Infer the UI & interaction role of a symbol based on UI type."""
    is_ja = normalize_language(language) == "Japanese"
    ui_type = ui_info.get("ui_type", "Library")
    name = sym_data.get("file_name", "")
    sig = sym_data.get("signature", "")
    kind = sym_data.get("kind", "").lower()
    raw = sym_data.get("raw_text", "")
    name_lower = name.lower()

    if ui_type == "GUI":
        if "viewmodel" in name_lower or "viewmodel" in sig.lower():
            return (
                "UI画面の状態管理およびイベント処理を統括し、"
                "View層とドメイン層を仲介する。"
                if is_ja
                else "Manages UI state and user interaction events, "
                "bridging the View and Domain layers."
            )
        elif "@composable" in raw or "view" in kind or "screen" in name_lower:
            return (
                "UI画面コンポーネントの描画およびユーザー操作を受け付ける。"
                if is_ja
                else "Renders UI components and captures direct user inputs."
            )
        elif (
            "click" in name_lower
            or "event" in name_lower
            or "tap" in name_lower
        ):
            return (
                "ユーザーのボタン操作やイベントを検知して処理を発行する。"
                if is_ja
                else "Captures user clicks/events and triggers corresponding "
                "actions."
            )
        elif "state" in name_lower or "model" in name_lower:
            return (
                "UIコンポーネントにバインドされる表示用状態データを保持する。"
                if is_ja
                else "Holds view-bound state data reflected in the UI "
                "interface."
            )
        else:
            return (
                "GUIアプリケーションの内部処理およびデータ連携を支援する。"
                if is_ja
                else "Supports GUI internal processing and data flow."
            )

    elif ui_type == "CLI":
        if any(
            k in name_lower
            for k in ("main", "cli", "run", "app", "parser", "arg", "option")
        ):
            return (
                "コマンドライン引数・オプションの解析および実行コマンドの"
                "ディスパッチを担う。"
                if is_ja
                else "Parses CLI arguments/flags and dispatches subcommands."
            )
        elif (
            "output" in name_lower
            or "print" in name_lower
            or "log" in name_lower
        ):
            return (
                "ターミナル標準出力・標準エラー出力への結果表示を制御する。"
                if is_ja
                else "Controls terminal standard output and error rendering."
            )
        else:
            return (
                "CLIツールの実行パイプラインにおいて指定処理を担う。"
                if is_ja
                else "Executes processing in CLI execution pipeline."
            )

    elif ui_type == "TUI":
        if (
            "draw" in name_lower
            or "render" in name_lower
            or "screen" in name_lower
        ):
            return (
                "ターミナル画面のリアルタイム描画とレイアウト更新を行う。"
                if is_ja
                else "Renders terminal UI screens and manages real-time "
                "layouts."
            )
        elif "key" in name_lower or "input" in name_lower:
            return (
                "ターミナルでのキーバインド入力や操作イベントをハンドリングする。"
                if is_ja
                else "Handles keyboard navigation and terminal interaction "
                "events."
            )
        else:
            return (
                "TUIアプリケーションの画面状態およびロジックを管理する。"
                if is_ja
                else "Manages TUI screen state and internal logic."
            )

    else:
        return (
            "ライブラリの公開APIまたは内部モジュール機能を提供する。"
            if is_ja
            else "Provides public API endpoints or internal library modules."
        )


def annotate_documents_with_ui_context(
    documents_dir: Path,
    ui_info: Dict[str, Any],
    language: str = "English",
    force: bool = False,
) -> int:
    """Bottom-up pass: Annotate symbol documents with inferred UI context."""
    if not documents_dir.exists():
        return 0

    norm_lang = normalize_language(language)
    is_ja = norm_lang == "Japanese"
    ui_type = ui_info.get("ui_type", "Library")
    framework = ui_info.get("framework", "None")

    section_header = (
        "## UI & Interaction Role"
        if not is_ja
        else "## UI・ユーザー操作における役割"
    )

    all_mds = sorted(list(set(
        list(documents_dir.glob("*.md")) + list(documents_dir.glob("**/*.md"))
    )))

    annotated_count = 0
    for md_path in all_mds:
        if not md_path.is_file():
            continue

        text = md_path.read_text(encoding="utf-8", errors="replace")
        if section_header in text:
            if not force:
                continue
            # Remove existing UI annotation block cleanly before re-annotating
            pat = (
                r"\n*"
                + re.escape(section_header)
                + r"[\s\S]*?(?=\n## |\Z)"
            )
            text = re.sub(pat, "", text)

        sym_data = {
            "file_name": md_path.name,
            "raw_text": text,
            "signature": "",
            "kind": "",
        }
        m_kind = re.search(
            r"- \*\*(?:Symbol Kind|Kind)[^*]*\*\*:\s*`?([^`\n]+)`?",
            text,
            re.IGNORECASE,
        )
        if m_kind:
            sym_data["kind"] = m_kind.group(1).strip()
        m_sig = re.search(
            r"- \*\*(?:Signature|Type)[^*]*\*\*:\s*`?([^`\n]+)`?",
            text,
            re.IGNORECASE,
        )
        if m_sig:
            sym_data["signature"] = m_sig.group(1).strip()

        ui_role = infer_symbol_ui_role(sym_data, ui_info, language=norm_lang)

        ui_block = (
            f"\n{section_header}\n"
            f"- **UI Type**: `{ui_type}` ({framework})\n"
            f"- **Interaction Specification**: {ui_role}\n"
        )

        if "## Source Code Snippet" in text:
            parts = text.split("## Source Code Snippet", 1)
            new_text = (
                parts[0].rstrip()
                + f"\n{ui_block}\n## Source Code Snippet"
                + parts[1]
            )
        else:
            new_text = text.rstrip() + f"\n{ui_block}\n"

        write_flushed_text(md_path, new_text.strip() + "\n")
        annotated_count += 1

    return annotated_count
