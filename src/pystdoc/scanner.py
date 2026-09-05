"""File scanner: discovers source and script files in the target project."""

import os
from pathlib import Path
from typing import List, Set

TARGET_EXTENSIONS: Set[str] = {
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".hh",
    ".py",
    ".java",
    ".kt",
    ".kts",
    ".sh",
    ".bash",
    ".rs",
}

EXCLUDED_DIRS: Set[str] = {
    ".git",
    ".docgen",
    "build",
    "builddir",
    "subprojects",
    ".vscode",
    ".idea",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "env",
    "pip_package",
}


def scan_files(target_dir: Path) -> List[Path]:
    """Recursively scan target directory and return sorted relative paths."""
    matched_files: List[Path] = []
    target_dir = target_dir.resolve()

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS and not d.startswith(".")
        ]

        for file_name in files:
            file_path = Path(root) / file_name
            if file_path.suffix.lower() in TARGET_EXTENSIONS:
                rel_path = file_path.relative_to(target_dir)
                matched_files.append(rel_path)

    matched_files.sort(key=lambda p: str(p))
    return matched_files


def write_files_list(target_dir: Path, matched_files: List[Path]) -> Path:
    """Write discovered file list to target_dir/.docgen/files.txt."""
    docgen_dir = target_dir / ".docgen"
    docgen_dir.mkdir(parents=True, exist_ok=True)
    out_file = docgen_dir / "files.txt"

    with open(out_file, "w", encoding="utf-8") as f:
        for rel_path in matched_files:
            f.write(f"{rel_path.as_posix()}\n")

    return out_file
