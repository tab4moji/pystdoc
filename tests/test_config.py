"""Unit tests for pystdoc configuration loader."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pystdoc.config import (
    _read_json_file,
    get_user_config_path,
    load_config,
)


class TestConfig(unittest.TestCase):
    def test_default_config_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.dict(os.environ, {}, clear=True):
                with patch(
                    "pystdoc.config.get_user_config_path",
                    return_value=tmp_path / "not_found.json",
                ):
                    cfg = load_config(tmp_path)
                    self.assertEqual(cfg["host"], "http://127.0.0.1:11434")
                    self.assertEqual(cfg["model"], "gemma4-26b-a4b")
                    self.assertIsNone(cfg["token"])
                    self.assertEqual(cfg["language"], "English")
                    self.assertEqual(cfg["context_size"], 16384)
                    self.assertEqual(cfg["concurrency"], 1)
                    self.assertFalse(cfg["allow_fallback"])

    def test_user_config_loading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            user_json = tmp_path / "pystdoc.json"
            user_json.write_text(
                json.dumps({
                    "host": "http://192.168.1.100:11434",
                    "model": "custom-model",
                    "language": "Japanese",
                    "context_size": 32768,
                    "concurrency": 4,
                    "allow_fallback": True,
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with patch(
                    "pystdoc.config.get_user_config_path",
                    return_value=user_json,
                ):
                    cfg = load_config()
                    self.assertEqual(
                        cfg["host"], "http://192.168.1.100:11434"
                    )
                    self.assertEqual(cfg["model"], "custom-model")
                    self.assertEqual(cfg["language"], "Japanese")
                    self.assertEqual(cfg["context_size"], 32768)
                    self.assertEqual(cfg["concurrency"], 4)
                    self.assertTrue(cfg["allow_fallback"])

    def test_project_config_overrides_user_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            user_json = tmp_path / "user.json"
            user_json.write_text(
                json.dumps({
                    "host": "http://user-host:11434",
                    "model": "user-model",
                }),
                encoding="utf-8",
            )
            proj_json = tmp_path / ".pystdoc.json"
            proj_json.write_text(
                json.dumps({"model": "proj-model", "language": "French"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with patch(
                    "pystdoc.config.get_user_config_path",
                    return_value=user_json,
                ):
                    cfg = load_config(tmp_path)
                    # host from user, model from proj, language from proj
                    self.assertEqual(cfg["host"], "http://user-host:11434")
                    self.assertEqual(cfg["model"], "proj-model")
                    self.assertEqual(cfg["language"], "French")

    def test_env_vars_override_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            proj_json = tmp_path / ".pystdoc.json"
            proj_json.write_text(
                json.dumps({
                    "host": "http://proj-host:11434",
                    "model": "proj-model",
                }),
                encoding="utf-8",
            )
            env_vars = {
                "LLM_HOST": "http://env-host:11434",
                "LLM_MODEL": "env-model",
                "OPENAI_API_KEY": "secret-token",
                "DOCGEN_LANG": "German",
                "LLM_CONTEXT_SIZE": "8192",
                "DOCGEN_WORKERS": "3",
                "PYSTDOC_ALLOW_FALLBACK": "1",
            }
            with patch.dict(os.environ, env_vars, clear=True):
                with patch(
                    "pystdoc.config.get_user_config_path",
                    return_value=tmp_path / "none.json",
                ):
                    cfg = load_config(tmp_path)
                    self.assertEqual(cfg["host"], "http://env-host:11434")
                    self.assertEqual(cfg["model"], "env-model")
                    self.assertEqual(cfg["token"], "secret-token")
                    self.assertEqual(cfg["language"], "German")
                    self.assertEqual(cfg["context_size"], 8192)
                    self.assertEqual(cfg["concurrency"], 3)
                    self.assertTrue(cfg["allow_fallback"])

    def test_read_json_file_edge_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Not existing
            self.assertEqual(_read_json_file(tmp_path / "not_exist.json"), {})
            # Is a directory
            d = tmp_path / "dir.json"
            d.mkdir()
            self.assertEqual(_read_json_file(d), {})
            # Invalid JSON syntax
            corrupt = tmp_path / "corrupt.json"
            corrupt.write_text("invalid json {", encoding="utf-8")
            self.assertEqual(_read_json_file(corrupt), {})
            # JSON array instead of dict
            arr = tmp_path / "arr.json"
            arr.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(_read_json_file(arr), {})

    def test_get_user_config_path_xdg(self):
        with patch.dict(
            os.environ, {"XDG_CONFIG_HOME": "/custom/config"}, clear=True
        ):
            p = get_user_config_path()
            self.assertEqual(p, Path("/custom/config/pystdoc/pystdoc.json"))

        with patch.dict(os.environ, {}, clear=True):
            p = get_user_config_path()
            self.assertEqual(
                p, Path.home() / ".config" / "pystdoc" / "pystdoc.json"
            )


if __name__ == "__main__":
    unittest.main()
