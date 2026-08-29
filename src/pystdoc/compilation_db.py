"""Compilation database (compile_commands.json) parser and compiler flags resolver."""

import json
import os
import shlex
from pathlib import Path
from typing import Dict, List, Optional


class CompilationDatabase:
    """Compilation database resolver for C/C++ compilation flags."""

    def __init__(self, db_path: Optional[Path] = None, target_dir: Optional[Path] = None):
        self.flags_map: Dict[str, List[str]] = {}
        self.loaded_path: Optional[Path] = None
        self.target_dir = target_dir

        # Auto-discover compile_commands.json
        candidates = []
        if db_path:
            candidates.append(Path(db_path))
        if target_dir:
            candidates.extend([
                target_dir / "compile_commands.json",
                target_dir / "build" / "compile_commands.json",
                target_dir / "builddir" / "compile_commands.json",
            ])
        candidates.extend([
            Path("compile_commands.json"),
            Path("build/compile_commands.json"),
            Path("builddir/compile_commands.json"),
        ])

        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    self._load_db(c)
                    self.loaded_path = c
                    break
                except Exception:
                    continue

    def _load_db(self, db_file: Path) -> None:
        """Parse compile_commands.json and extract flags for each source file."""
        data = json.loads(db_file.read_text(encoding="utf-8"))
        for entry in data:
            file_path = entry.get("file")
            if not file_path:
                continue

            directory = entry.get("directory", "")
            full_file = Path(directory) / file_path if directory else Path(file_path)
            norm_key = full_file.resolve().as_posix()

            # Extract arguments from command string or arguments list
            raw_args = []
            if "arguments" in entry:
                raw_args = entry["arguments"]
            elif "command" in entry:
                raw_args = shlex.split(entry["command"])

            # Filter valid flags for libclang
            clang_args = []
            skip_next = False
            for i, arg in enumerate(raw_args[1:], start=1):
                if skip_next:
                    skip_next = False
                    continue

                if arg in ("-c", "-o"):
                    skip_next = True
                    continue
                if arg.startswith("-o"):
                    continue

                if arg.startswith(("-I", "-D", "-U", "-isystem", "-std=", "-m", "-f")):
                    if arg in ("-I", "-isystem") and i + 1 < len(raw_args):
                        inc_path = raw_args[i + 1]
                        if directory:
                            inc_path = (Path(directory) / inc_path).resolve().as_posix()
                        clang_args.append(f"{arg}{inc_path}")
                        skip_next = True
                    else:
                        if arg.startswith("-I") and len(arg) > 2:
                            inc_dir = arg[2:]
                            if directory and not inc_dir.startswith("/"):
                                inc_dir = (Path(directory) / inc_dir).resolve().as_posix()
                            clang_args.append(f"-I{inc_dir}")
                        else:
                            clang_args.append(arg)

            self.flags_map[norm_key] = clang_args
            self.flags_map[Path(file_path).name] = clang_args

    def get_flags_for_file(self, file_path: Path) -> List[str]:
        """Get compilation flags for a given source file, or return smart defaults."""
        norm_key = file_path.resolve().as_posix()
        if norm_key in self.flags_map:
            return self.flags_map[norm_key]
        if file_path.name in self.flags_map:
            return self.flags_map[file_path.name]

        # Smart defaults with inferred include directories
        base_dir = self.target_dir or file_path.parent
        defaults = [
            "-std=c11" if file_path.suffix in (".c", ".h") else "-std=c++17",
            "-D_GNU_SOURCE",
            f"-I{base_dir.resolve().as_posix()}",
            f"-I{(base_dir / 'include').resolve().as_posix()}",
            f"-I{(base_dir / 'src').resolve().as_posix()}",
        ]
        return defaults
