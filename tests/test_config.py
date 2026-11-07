"""Unit tests for pystdoc configuration loader."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pystdoc.config import (
    _read_json_file,
    detect_terminal_language,
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

    def test_detect_terminal_language_japanese(self):
        with patch.dict(os.environ, {"LANG": "ja_JP.UTF-8"}, clear=True):
            self.assertEqual(detect_terminal_language(), "Japanese")

    def test_detect_terminal_language_priority(self):
        # LC_ALL > LC_MESSAGES > LANG > LANGUAGE
        env = {
            "LANG": "ja_JP.UTF-8",
            "LC_MESSAGES": "fr_FR.UTF-8",
            "LC_ALL": "de_DE.UTF-8",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_terminal_language(), "German")

        env2 = {
            "LANG": "ja_JP.UTF-8",
            "LC_MESSAGES": "fr_FR.UTF-8",
        }
        with patch.dict(os.environ, env2, clear=True):
            self.assertEqual(detect_terminal_language(), "French")

    def test_detect_terminal_language_c_posix(self):
        with patch.dict(os.environ, {"LANG": "C"}, clear=True):
            self.assertEqual(detect_terminal_language(), "English")
        with patch.dict(os.environ, {"LANG": "POSIX"}, clear=True):
            self.assertEqual(detect_terminal_language(), "English")

    def test_load_config_defaults_to_terminal_language(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.dict(os.environ, {"LANG": "ja_JP.UTF-8"}, clear=True):
                with patch(
                    "pystdoc.config.get_user_config_path",
                    return_value=tmp_path / "not_found.json",
                ):
                    cfg = load_config(tmp_path)
                    self.assertEqual(cfg["language"], "Japanese")

    def test_doc_labels_initialization_and_customization(self):
        from unittest.mock import MagicMock
        from pystdoc.doc_labels import (
            get_or_init_document_labels,
            DEFAULT_ENGLISH_LABELS,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # 1. English initialization
            en_labels = get_or_init_document_labels(tmp_path, "English")
            self.assertEqual(
                en_labels["basic_info_title"],
                DEFAULT_ENGLISH_LABELS["basic_info_title"],
            )
            labels_file = tmp_path / ".pystdoc" / "document_labels.json"
            self.assertTrue(labels_file.exists())

            # 2. Japanese initialization with LLM client
            mock_llm = MagicMock()
            mock_llm.chat_completion.return_value = json.dumps({
                "language": "Japanese",
                "doc_title_template": "{kind}仕様書: `{name}`",
                "basic_info_title": "## 1. 基本情報",
                "label_symbol_kind": "シンボル種別",
                "kind_function": "関数",
            })
            ja_labels = get_or_init_document_labels(
                tmp_path, "Japanese", llm_client=mock_llm
            )
            self.assertEqual(ja_labels["basic_info_title"], "## 1. 基本情報")
            self.assertEqual(ja_labels["label_symbol_kind"], "シンボル種別")
            self.assertEqual(ja_labels["kind_function"], "関数")
            self.assertEqual(
                ja_labels["doc_title_template"], "{kind}仕様書: `{name}`"
            )

            # 3. Customization in JSON file is preserved
            loaded = json.loads(labels_file.read_text(encoding="utf-8"))
            loaded["basic_info_title"] = "## 1. カスタム基本情報"
            labels_file.write_text(
                json.dumps(loaded, ensure_ascii=False), encoding="utf-8"
            )

            custom_labels = get_or_init_document_labels(tmp_path, "Japanese")
            self.assertEqual(
                custom_labels["basic_info_title"], "## 1. カスタム基本情報"
            )

    def test_doc_labels_llm_generation_for_other_languages(self):
        from pystdoc.doc_labels import get_or_init_document_labels
        from unittest.mock import MagicMock

        def fake_chat(messages, **kwargs):
            body = messages[-1]["content"]
            chunk = json.loads(body.split("```json\n")[1].split("\n```")[0])
            out = {k: "[de] " + v for k, v in chunk.items()}
            if "basic_info_title" in out:
                out["basic_info_title"] = "## 1. Grundlegende Informationen"
            if "label_symbol_kind" in out:
                out["label_symbol_kind"] = "Symbolart"
            return json.dumps(out)

        mock_llm = MagicMock()
        mock_llm.chat_completion.side_effect = fake_chat

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            de_labels = get_or_init_document_labels(
                tmp_path, "German", llm_client=mock_llm
            )
            self.assertEqual(de_labels["language"], "German")
            self.assertEqual(
                de_labels["basic_info_title"],
                "## 1. Grundlegende Informationen",
            )
            self.assertEqual(de_labels["label_symbol_kind"], "Symbolart")
            # Localized design/README headings are also translated
            self.assertTrue(
                de_labels["design_overview_title"].startswith("[de]")
            )
            labels_file = tmp_path / ".pystdoc" / "document_labels.json"
            self.assertTrue(labels_file.exists())
            self.assertIn(
                "Grundlegende", labels_file.read_text(encoding="utf-8")
            )

            # Next call uses cached file without calling LLM again
            mock_llm.chat_completion.reset_mock()
            de_labels_cached = get_or_init_document_labels(
                tmp_path, "German", llm_client=mock_llm
            )
            self.assertEqual(mock_llm.chat_completion.call_count, 0)
            self.assertEqual(
                de_labels_cached["basic_info_title"],
                "## 1. Grundlegende Informationen",
            )

    def test_doc_labels_failed_translation_is_retried(self):
        from pystdoc.doc_labels import (
            get_or_init_document_labels,
            DEFAULT_ENGLISH_LABELS,
        )
        from unittest.mock import MagicMock

        bad_llm = MagicMock()
        bad_llm.chat_completion.return_value = "not json at all"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            labels = get_or_init_document_labels(
                tmp_path, "Japanese", llm_client=bad_llm
            )
            self.assertEqual(
                labels["input_return_title"],
                DEFAULT_ENGLISH_LABELS["input_return_title"],
            )
            labels_file = tmp_path / ".pystdoc" / "document_labels.json"
            saved = json.loads(labels_file.read_text(encoding="utf-8"))
            self.assertTrue(saved.get("_translation_incomplete"))

            # A working LLM on the next run fills the English leftovers
            good_llm = MagicMock()

            def fake_chat(messages, **kwargs):
                body = messages[-1]["content"]
                chunk = json.loads(
                    body.split("```json\n")[1].split("\n```")[0]
                )
                return json.dumps({k: "JA " + v for k, v in chunk.items()})

            good_llm.chat_completion.side_effect = fake_chat
            labels2 = get_or_init_document_labels(
                tmp_path, "Japanese", llm_client=good_llm
            )
            self.assertTrue(labels2["input_return_title"].startswith("JA "))
            self.assertNotIn("_translation_incomplete", labels2)
            saved2 = json.loads(labels_file.read_text(encoding="utf-8"))
            self.assertNotIn("_translation_incomplete", saved2)


if __name__ == "__main__":
    unittest.main()
