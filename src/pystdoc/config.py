"""Configuration loader for pystdoc from configuration files and env."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "http://127.0.0.1:11434",
    "model": "gemma4-26b-a4b",
    "token": None,
    "language": "English",
    "context_size": 16384,
    "concurrency": 1,
    "allow_fallback": False,
}


def get_user_config_path() -> Path:
    """Return user configuration path ~/.config/pystdoc/pystdoc.json."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "pystdoc" / "pystdoc.json"
    return Path.home() / ".config" / "pystdoc" / "pystdoc.json"


def get_perf_metrics_path() -> Path:
    """Return performance metrics path ~/.config/pystdoc/perf_metrics.json."""
    return get_user_config_path().parent / "perf_metrics.json"


def _read_json_file(file_path: Path) -> Dict[str, Any]:
    """Safely read and parse a JSON configuration file."""
    if not file_path.exists() or not file_path.is_file():
        return {}
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_config(target_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load configuration with cascading priority:

    Defaults < ~/.config/pystdoc/pystdoc.json < ./.pystdoc.json < Env vars
    """
    config = dict(DEFAULT_CONFIG)

    # 1. User config (~/.config/pystdoc/pystdoc.json)
    user_cfg_path = get_user_config_path()
    user_cfg = _read_json_file(user_cfg_path)
    for k, v in user_cfg.items():
        if k in DEFAULT_CONFIG and v is not None:
            config[k] = v

    # 2. Project config (<target_dir>/.pystdoc.json or ./.pystdoc.json)
    proj_paths = []
    if target_dir:
        proj_paths.append(target_dir / ".pystdoc.json")
    proj_paths.append(Path.cwd() / ".pystdoc.json")

    for p_path in proj_paths:
        if p_path.exists() and p_path.is_file():
            proj_cfg = _read_json_file(p_path)
            for k, v in proj_cfg.items():
                if k in DEFAULT_CONFIG and v is not None:
                    config[k] = v
            break

    # 3. Environment variables
    env_host = os.environ.get("LLM_HOST") or os.environ.get("LLM_BASE_URL")
    if env_host:
        config["host"] = env_host

    env_model = os.environ.get("LLM_MODEL")
    if env_model:
        config["model"] = env_model

    env_token = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_TOKEN")
    if env_token:
        config["token"] = env_token

    env_lang = (
        os.environ.get("DOCGEN_LANG")
        or os.environ.get("PYSTDOC_LANG")
        or os.environ.get("LANGUAGE")
    )
    if env_lang:
        config["language"] = env_lang

    env_ctx = os.environ.get("LLM_CONTEXT_SIZE") or os.environ.get("CTX_SIZE")
    if env_ctx and env_ctx.isdigit():
        config["context_size"] = int(env_ctx)

    env_workers = os.environ.get("DOCGEN_WORKERS") or os.environ.get(
        "PYSTDOC_CONCURRENCY"
    )
    if env_workers and env_workers.isdigit():
        config["concurrency"] = int(env_workers)

    env_fallback = os.environ.get("PYSTDOC_ALLOW_FALLBACK")
    if env_fallback is not None:
        config["allow_fallback"] = env_fallback.lower() in (
            "1", "true", "yes", "on"
        )

    return config
