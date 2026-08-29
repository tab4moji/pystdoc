"""Cache storage and atomic write operations with immediate disk sync."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional


def write_flushed_text(file_path: Path, text: str) -> None:
    """Write text to file with immediate directory creation, flush, and fsync."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def save_symbol_cache(target_dir: Path, unique_id: str, data: Dict[str, Any]) -> Path:
    """Save symbol LLM analysis result to json cache file with immediate sync."""
    safe_name = re.sub(r"[^\w\-.]", "_", unique_id)
    cache_dir = target_dir / ".docgen" / "cache"
    cache_file = cache_dir / f"{safe_name}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    write_flushed_text(cache_file, content)
    return cache_file


def load_symbol_cache(target_dir: Path, unique_id: str) -> Optional[Dict[str, Any]]:
    """Load cached LLM analysis data for a symbol."""
    safe_name = re.sub(r"[^\w\-.]", "_", unique_id)
    cache_file = target_dir / ".docgen" / "cache" / f"{safe_name}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None
