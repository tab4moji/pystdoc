"""SHA-256 hash calculator for files and symbols with flush persistence."""

import hashlib
import os
from pathlib import Path
import re
from typing import Any, Optional, Tuple
from pystdoc.symbols import Symbol, get_kind_prefix


def compute_file_hash(file_path: Path) -> str:
    """Calculate SHA-256 hash of a file's content."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def strip_comments(code: str, lang: str = "") -> str:
    """Remove comments from code snippet while preserving string literals."""
    if not code:
        return ""

    lang_lower = lang.lower() if lang else ""

    # Python AST-based comment removal if valid Python code
    if lang_lower in ("python", "py"):
        try:
            import ast
            parsed = ast.parse(code)
            return ast.unparse(parsed).strip()
        except Exception:
            pass

    def _replacer(match):
        s = match.group(0)
        if s.startswith("/") or (
            s.startswith("#")
            and not (s.startswith("'") or s.startswith('"'))
        ):
            return " "
        return s

    if lang_lower in ("sh", "bash", "shell", "python", "py"):
        pattern = re.compile(
            r'#.*?$|"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|'
            r"\'(?:\\.|[^\\\'])*\'|\"(?:\\.|[^\\\"])*\"",
            re.MULTILINE,
        )
    else:
        pattern = re.compile(
            r'//.*?$|/\*[\s\S]*?\*/|'
            r"\'(?:\\.|[^\\\'])*\'|\"(?:\\.|[^\\\"])*\"",
            re.MULTILINE,
        )

    cleaned = pattern.sub(_replacer, code)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines)


def compute_symbol_hash(
    code_snippet: str, signature: str = "", doc: str = ""
) -> str:
    """Calculate SHA-256 full hash for an individual symbol's code & doc."""
    raw = f"{signature}\n{doc}\n{code_snippet}".strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_logic_hash(
    code_snippet: str,
    signature: str = "",
    lang: str = "",
    ast_node: Optional[Any] = None,
) -> str:
    """Calculate SHA-256 logic-only hash excluding comments and formatting."""
    if ast_node is not None:
        try:
            import ast
            if isinstance(ast_node, ast.AST):
                ast_str = ast.dump(
                    ast_node, annotate_fields=False, include_attributes=False
                )
                return hashlib.sha256(
                    f"{signature}\n{ast_str}".encode("utf-8")
                ).hexdigest()
        except Exception:
            pass

    logic_code = strip_comments(code_snippet, lang=lang)
    raw = f"{signature}\n{logic_code}".strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def update_hash_record(
    target_dir: Path, rel_path: Path, current_hash: str
) -> Tuple[bool, Path]:
    """Check and update file SHA-256 hash record with immediate flush."""
    hash_file = (
        target_dir / ".pystdoc" / "documents" / f"{rel_path.as_posix()}.hash"
    )
    hash_file.parent.mkdir(parents=True, exist_ok=True)

    previous_hash: Optional[str] = None
    if hash_file.exists():
        try:
            previous_hash = hash_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    is_changed = previous_hash != current_hash

    if is_changed or not hash_file.exists():
        with open(hash_file, "w", encoding="utf-8") as f:
            f.write(current_hash + "\n")
            f.flush()
            os.fsync(f.fileno())

    return is_changed, hash_file


def update_symbol_hash_record(
    target_dir: Path,
    rel_path: Path,
    symbol: Symbol,
    current_sym_hash: str,
    prefix_name: str = "",
) -> Tuple[bool, Path]:
    """Check and update individual symbol hash record with immediate flush."""
    k_prefix = get_kind_prefix(symbol.kind)
    sym_id = f"{prefix_name}{symbol.name}" if prefix_name else symbol.name
    hash_file = (
        target_dir
        / ".pystdoc"
        / "documents"
        / f"{rel_path.as_posix()}.{k_prefix}.{sym_id}.hash"
    )
    hash_file.parent.mkdir(parents=True, exist_ok=True)

    previous_hash: Optional[str] = None
    if hash_file.exists():
        try:
            previous_hash = hash_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    is_changed = previous_hash != current_sym_hash

    if is_changed or not hash_file.exists():
        with open(hash_file, "w", encoding="utf-8") as f:
            f.write(current_sym_hash + "\n")
            f.flush()
            os.fsync(f.fileno())

    return is_changed, hash_file
