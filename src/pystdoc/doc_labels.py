"""Documentation label localization and JSON template management."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_ENGLISH_LABELS: Dict[str, str] = {
    "language": "English",
    "doc_title_template": "{kind} Documentation: `{name}`",
    "basic_info_title": "## 1. Basic Information",
    "label_name": "Name",
    "label_fqdn": "FQDN",
    "label_symbol_kind": "Symbol Kind",
    "label_location": "Location",
    "location_template": "Line {start} to Line {end}",
    "label_signature": "Signature / Type",
    "parameters_title": "## 2. Parameters",
    "label_none": "None",
    "input_return_title": "## 3. Input / Return Specifications",
    "label_input_constraints": "Input Constraints",
    "label_return_type": "Return Type",
    "label_return_value_side_effects": "Return Value & Side Effects",
    "label_void_none": "void / None",
    "called_functions_title": "## 4. Called Functions",
    "referencing_functions_title": "## 4. Referencing Functions",
    "source_code_snippet_title": "## Source Code Snippet",
    "file_doc_title_template": "File Documentation: `{path}`",
    "label_file_hash": "File SHA-256",
    "label_detected_symbols": "Detected Symbols",
    "symbol_list_title": "## Symbol List",
    "symbol_list_item_template": "- `{name}` ({kind}) [Lines: {line_range}]",
    "kind_function": "Function",
    "kind_class": "Class",
    "kind_method": "Method",
    "kind_variable": "Variable",
    "kind_struct": "Struct",
    "kind_enum": "Enum",
    "kind_interface": "Interface",
    "kind_constant": "Constant",
    "kind_type": "Type",
    "kind_module": "Module",
    "prose_referenced_by_template": (
        "In the system architecture, it is referenced by {callers}."
    ),
    "prose_root_entry_point": (
        "It serves as the root entry point (system bootstrap and dispatcher)."
    ),
    "prose_implementation_overview_template": (
        "Implementation overview: {overview}"
    ),
    "ui_role_title": "## UI & Interaction Role",
    "label_ui_type": "UI Type",
    "label_ui_interaction": "Interaction Specification",
    "design_data_models_title": "# Data Structure Design & Data Models",
    "design_data_models_sec1": "## 1. Architectural Role & Design Intent",
    "design_data_models_sec2": "## 2. Core Data Structures",
    "design_data_models_sec3": "## 3. Data Lifecycle & Flow",
    "design_data_models_sec4": "## 4. Constraints & State Invariants",
    "design_data_models_default": (
        "Provides core data structure definitions and domain models."
    ),
    "design_execution_title": (
        "# System Execution Model & Runtime Architecture"
    ),
    "design_execution_sec1": "## 1. Runtime Architecture Pattern",
    "design_execution_sec2": (
        "## 2. Execution Flow from Entry Point to Termination"
    ),
    "design_execution_sec3": "## 3. Concurrency, Asynchrony & Lifecycle",
    "design_execution_sec4": "## 4. Error Handling & Failure Modes",
    "design_execution_default": (
        "Provides system execution flow and runtime architecture."
    ),
    "design_module_title_template": "# Module Design: `{name}`",
    "design_module_sec1": "## 1. Module Responsibility & Role",
    "design_module_sec2": "## 2. Public Interfaces & Exported Symbols",
    "design_module_sec3": "## 3. Internal Data Flow & Processing",
    "design_module_sec4": "## 4. Dependencies & Inter-Module Interactions",
    "design_module_default_template": (
        "Defines responsibilities and public interfaces for module `{name}`."
    ),
    "design_overview_title": "# System Architecture Overview",
    "design_overview_sec1": "## 1. Architecture Pattern & System Overview",
    "design_overview_default": (
        "Provides overall system architectural design and component "
        "structure."
    ),
    "readme_title": "# Project Overview & Executive Summary",
    "readme_title_with_project_template": (
        "# Project Overview & Executive Summary ({project})"
    ),
    "readme_sec1": "## 1. Software Classification & Purpose",
    "readme_sec2": "## 2. Invocation & Usage Example",
    "readme_sec3": "## 3. Core Features & Capabilities",
    "readme_sec4": "## 4. How It Works (High-Level Architecture Story)",
    "readme_sec5": "## 5. Documentation Navigation (Detailed Design Links)",
    "readme_label_type": "Type",
    "readme_label_purpose": "Purpose",
    "readme_type_cli": "CLI Application",
    "readme_type_gui": "GUI Application",
    "readme_type_library": "Library / Module Package",
    "readme_type_default": "Software Module / Application",
    "readme_default_purpose_template": (
        "Provides functionality implemented across {count} key module(s) "
        "({modules})."
    ),
    "readme_default_invocation": (
        "Refer to the module interfaces and entry points described in "
        "documentation."
    ),
    "readme_default_how_it_works": (
        "Modular software system structured into interconnected components "
        "with topological dependency mapping."
    ),
    "readme_nav_overview": "Architecture Overview (Overview)",
    "readme_nav_data_models": "Data Models & Structures (Data Models)",
    "readme_nav_execution_model": (
        "Execution Model & Runtime (Execution Model)"
    ),
    "readme_nav_modules": "Module Design Documents",
    "readme_nav_symbol_index": "Symbol & Source Code Index",
    "readme_module_link_template": "{name} Module",
}


def get_default_labels(language: str = "English") -> Dict[str, str]:
    """Return default dictionary of documentation labels (English base)."""
    return dict(DEFAULT_ENGLISH_LABELS)


# Labels that may legitimately stay identical to English in any language
_NEUTRAL_KEYS = frozenset(
    {"language", "label_fqdn", "label_file_hash", "label_name"}
)
_INCOMPLETE_MARKER = "_translation_incomplete"
_CHUNK_SIZE = 20
_MAX_ATTEMPTS = 2


def untranslated_keys(labels: Dict[str, str]) -> List[str]:
    """Return label keys whose value is still the English default."""
    return [
        k for k, v in DEFAULT_ENGLISH_LABELS.items()
        if k not in _NEUTRAL_KEYS and labels.get(k, v) == v
    ]


def _is_incomplete(labels: Dict[str, str]) -> bool:
    """True if most labels remain English (translation likely failed)."""
    total = len(DEFAULT_ENGLISH_LABELS) - len(_NEUTRAL_KEYS)
    return len(untranslated_keys(labels)) * 2 > total


def _build_system_prompt(target_language: str) -> str:
    return (
        "You are an expert technical documentation localizer. "
        f"Translate software documentation labels and headings into natural, "
        f"standard software engineering terms in {target_language}.\n"
        "Guidelines:\n"
        "- In Japanese software engineering, documentation is conventionally "
        "called '仕様書' (e.g. '関数仕様書' for Function Documentation, "
        "'クラス仕様書' for Class Documentation, "
        "'ファイル仕様書' for File Documentation).\n"
        "- When translating into Japanese, translate `doc_title_template` "
        "as '{kind}仕様書: `{name}`', `file_doc_title_template` as "
        "'ファイル仕様書: `{path}`', `kind_function` as '関数', "
        "`kind_class` as 'クラス', `kind_method` as 'メソッド', "
        "`kind_variable` as '変数', `kind_struct` as '構造体', "
        "`kind_enum` as '列挙型', `kind_constant` as '定数'.\n"
        "- Keys starting with `design_` and `readme_` are titles and "
        "headings of architecture design documents and the project README "
        "(e.g. 'System Architecture Overview' -> 'システム構成概要' in "
        "Japanese, 'Data Structure Design & Data Models' -> "
        "'データ構造設計・データモデル'). Translate them as well.\n"
        "- Keep the leading Markdown markers ('#', '##') and section "
        "numbers ('1.', '2.') of headings exactly as is.\n"
        "- For other languages, translate software terms idiomatic to that "
        "language (e.g. Funktion in German, 函数 in Chinese).\n"
        "- Keep placeholders {kind}, {name}, {path}, {start}, {end}, "
        "{line_range}, {callers}, {overview}, {project}, {count}, "
        "{modules} exactly as is.\n"
        "- Respond strictly with a valid JSON object matching the input keys."
    )


def _translate_chunk(
    llm_client: Any,
    target_language: str,
    chunk: Dict[str, str],
) -> Dict[str, str]:
    """Translate one small group of labels (retrying on bad responses)."""
    from pystdoc.llm_client import extract_json_from_text

    user_prompt = (
        f"Translate the VALUES of the following JSON documentation labels "
        f"into {target_language}. Keep every key unchanged.\n\n"
        f"```json\n"
        f"{json.dumps(chunk, indent=2, ensure_ascii=False)}\n"
        f"```\n\n"
        f"Output ONLY valid JSON."
    )
    messages = [
        {"role": "system", "content": _build_system_prompt(target_language)},
        {"role": "user", "content": user_prompt},
    ]
    for _ in range(_MAX_ATTEMPTS):
        try:
            parsed = extract_json_from_text(
                llm_client.chat_completion(messages)
            )
        except Exception:
            continue
        if isinstance(parsed, dict):
            out = {
                k: v.strip() for k, v in parsed.items()
                if k in chunk and isinstance(v, str) and v.strip()
            }
            if out:
                return out
    return {}


def translate_labels_with_llm(
    llm_client: Any,
    target_language: str,
    base: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Translate documentation labels to target_language using LLM.

    Labels are translated in small chunks so that small local models can
    handle them. If `base` is given, only those keys are translated (used to
    fill in labels that are missing or still English). Labels that could not
    be translated keep their English text.
    """
    base_labels = dict(base) if base else dict(DEFAULT_ENGLISH_LABELS)
    base_labels.pop("language", None)

    merged = dict(base_labels)
    items = list(base_labels.items())
    for i in range(0, len(items), _CHUNK_SIZE):
        chunk = dict(items[i:i + _CHUNK_SIZE])
        merged.update(_translate_chunk(llm_client, target_language, chunk))
    merged["language"] = target_language
    return merged


def _save_labels(labels_file: Path, labels: Dict[str, str]) -> None:
    """Write labels JSON (flagging incomplete translations for retry)."""
    data = dict(labels)
    data.pop(_INCOMPLETE_MARKER, None)
    lang = data.get("language", "English")
    if lang != "English" and _is_incomplete(data):
        data[_INCOMPLETE_MARKER] = True
    try:
        labels_file.parent.mkdir(parents=True, exist_ok=True)
        labels_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _warn_if_incomplete(labels: Dict[str, str], language: str) -> None:
    if language != "English" and _is_incomplete(labels):
        n = len(untranslated_keys(labels))
        print(
            f"[Labels] Warning: {n} labels remain in English "
            f"(LLM translation to {language} incomplete). "
            f"Will retry on the next run.",
            file=sys.stderr,
            flush=True,
        )


def get_or_init_document_labels(
    target_dir: Optional[Path],
    language: str = "English",
    llm_client: Optional[Any] = None,
) -> Dict[str, str]:
    """Load or initialize document_labels.json under target_dir/.pystdoc/."""
    from pystdoc.doc_writer import normalize_language

    norm_lang = normalize_language(language)
    defaults = get_default_labels(norm_lang)

    if target_dir is None:
        return defaults

    labels_file = target_dir / ".pystdoc" / "document_labels.json"

    if labels_file.exists():
        try:
            loaded = json.loads(labels_file.read_text(encoding="utf-8"))
            if (
                isinstance(loaded, dict)
                and loaded.get("language") == norm_lang
            ):
                incomplete = bool(loaded.pop(_INCOMPLETE_MARKER, False))
                merged = dict(defaults)
                merged.update(loaded)
                pending = {
                    k: v for k, v in defaults.items()
                    if k not in loaded and k != "language"
                }
                if incomplete:
                    for k in untranslated_keys(merged):
                        pending[k] = defaults[k]
                if pending and norm_lang != "English" and llm_client:
                    # New labels or earlier failed translation: retry only
                    # those labels, keeping user customizations intact.
                    print(
                        f"[Labels] Translating {len(pending)} document "
                        f"labels for {norm_lang} via LLM...",
                        flush=True,
                    )
                    translated = translate_labels_with_llm(
                        llm_client, norm_lang, base=pending
                    )
                    for k in pending:
                        merged[k] = translated.get(k, pending[k])
                    merged["language"] = norm_lang
                    _save_labels(labels_file, merged)
                    _warn_if_incomplete(merged, norm_lang)
                return merged
        except Exception:
            pass

    # Language is not English: generate localized labels via LLM
    final_labels = defaults
    if norm_lang != "English" and llm_client is not None:
        try:
            print(
                f"[Labels] Generating localized document labels for "
                f"{norm_lang} via LLM...",
                flush=True,
            )
            final_labels = translate_labels_with_llm(llm_client, norm_lang)
        except Exception:
            final_labels = defaults
        _warn_if_incomplete(final_labels, norm_lang)

    _save_labels(labels_file, final_labels)
    return final_labels
