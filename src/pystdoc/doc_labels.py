"""Documentation label localization and JSON template management."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

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
}


def get_default_labels(language: str = "English") -> Dict[str, str]:
    """Return default dictionary of documentation labels (English base)."""
    return dict(DEFAULT_ENGLISH_LABELS)


def translate_labels_with_llm(
    llm_client: Any,
    target_language: str,
) -> Dict[str, str]:
    """Translate documentation labels to target_language using LLM."""
    from pystdoc.llm_client import extract_json_from_text

    base_labels = dict(DEFAULT_ENGLISH_LABELS)
    base_labels["language"] = target_language

    system_prompt = (
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
        "- For other languages, translate software terms idiomatic to that "
        "language (e.g. Funktion in German, 函数 in Chinese).\n"
        "- Keep placeholders {kind}, {name}, {path}, {start}, {end}, "
        "{line_range}, {callers}, {overview} exactly as is.\n"
        "- Respond strictly with a valid JSON object matching the input keys."
    )
    user_prompt = (
        f"Translate the following JSON documentation labels into "
        f"{target_language}:\n\n"
        f"```json\n"
        f"{json.dumps(base_labels, indent=2, ensure_ascii=False)}\n"
        f"```\n\n"
        f"Output ONLY valid JSON."
    )

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response_text = llm_client.chat_completion(messages)
        parsed = extract_json_from_text(response_text)
        if isinstance(parsed, dict) and len(parsed) >= 5:
            merged = dict(base_labels)
            for k, v in parsed.items():
                if k in merged and isinstance(v, str) and v.strip():
                    merged[k] = v.strip()
            merged["language"] = target_language
            return merged
    except Exception:
        pass

    return base_labels


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

    pystdoc_dir = target_dir / ".pystdoc"
    labels_file = pystdoc_dir / "document_labels.json"

    if labels_file.exists():
        try:
            content = labels_file.read_text(encoding="utf-8")
            loaded = json.loads(content)
            if (
                isinstance(loaded, dict)
                and loaded.get("language") == norm_lang
            ):
                merged = dict(defaults)
                merged.update(loaded)
                return merged
        except Exception:
            pass

    # If language is not English, generate localized labels via LLM
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

    # Save initial labels JSON for the target language
    try:
        pystdoc_dir.mkdir(parents=True, exist_ok=True)
        content = json.dumps(final_labels, indent=2, ensure_ascii=False) + "\n"
        labels_file.write_text(content, encoding="utf-8")
    except Exception:
        pass

    return final_labels
