#!/usr/bin/env python3
"""Unit tests for LLMClient, JSON extraction, host discovery, and fallbacks."""

import json
import os
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

from pystdoc.llm_client import (
    LLMClient,
    LLMError,
    normalize_host_url,
    normalize_llm_json_dict,
    extract_json_from_text,
)


class TestLLMClient(unittest.TestCase):
    def test_normalize_host_url(self):
        self.assertEqual(normalize_host_url(None), "http://127.0.0.1:11434/v1")
        self.assertEqual(normalize_host_url(""), "http://127.0.0.1:11434/v1")
        self.assertEqual(
            normalize_host_url("localhost:8000"), "http://localhost:8000/v1"
        )
        self.assertEqual(
            normalize_host_url("https://api.openai.com"),
            "https://api.openai.com/v1",
        )
        self.assertEqual(
            normalize_host_url("http://192.168.0.1:11434/v1"),
            "http://192.168.0.1:11434/v1",
        )

    def test_normalize_llm_json_dict_all_keys(self):
        # English keys
        data_en = {
            "purpose": "Main goal",
            "inputs": "args",
            "outputs": "ret",
            "overview": "summary",
            "significance": "role",
            "usage_scenario": "scenario",
            "top_down_summary": "top summary",
        }
        res_en = normalize_llm_json_dict(data_en)
        self.assertEqual(res_en["purpose"], "Main goal")
        self.assertEqual(res_en["inputs"], "args")
        self.assertEqual(res_en["outputs"], "ret")
        self.assertEqual(res_en["overview"], "summary")
        self.assertEqual(res_en["significance"], "role")
        self.assertEqual(res_en["usage_scenario"], "scenario")
        self.assertEqual(res_en["top_down_summary"], "top summary")

        # Japanese keys
        data_ja = {
            "設計意図": "目的",
            "パラメータ": "入力値",
            "返り値": "結果値",
            "説明": "処理概要",
            "重要性": "役割",
            "データフロー": "受け渡し",
            "全体設計要約": "要約",
        }
        res_ja = normalize_llm_json_dict(data_ja)
        self.assertEqual(res_ja["purpose"], "目的")
        self.assertEqual(res_ja["inputs"], "入力値")
        self.assertEqual(res_ja["outputs"], "結果値")
        self.assertEqual(res_ja["overview"], "処理概要")
        self.assertEqual(res_ja["significance"], "役割")
        self.assertEqual(res_ja["usage_scenario"], "受け渡し")
        self.assertEqual(res_ja["top_down_summary"], "要約")

    def test_extract_json_from_text(self):
        # Markdown fenced
        text_fenced = "Here is JSON:\n```json\n{\"purpose\": \"Fenced\"}\n```"
        self.assertEqual(
            extract_json_from_text(text_fenced), {"purpose": "Fenced"}
        )

        # Outermost braces
        text_braces = "Leading text {\"purpose\": \"Braced\"} trailing text"
        self.assertEqual(
            extract_json_from_text(text_braces), {"purpose": "Braced"}
        )

        # Direct JSON
        text_direct = "{\"purpose\": \"Direct\"}"
        self.assertEqual(
            extract_json_from_text(text_direct), {"purpose": "Direct"}
        )

        # Invalid JSON
        with self.assertRaises(Exception):
            extract_json_from_text("Totally invalid response")

    @patch("pystdoc.llm_client.LLMClient._ping_url", return_value=True)
    def test_init_from_env_vars(self, _mock_ping):
        env = {
            "LLM_HOST": "http://env-host:11434",
            "LLM_MODEL": "env-model",
            "LLM_TOKEN": "env-token",
            "LLM_CONTEXT_SIZE": "8192",
        }
        with patch.dict(os.environ, env):
            client = LLMClient(model=None, context_size=None)
            self.assertEqual(client.base_url, "http://env-host:11434/v1")
            self.assertEqual(client.model, "env-model")
            self.assertEqual(client.token, "env-token")
            self.assertEqual(client.context_size, 8192)

    @patch("subprocess.run")
    @patch("pathlib.Path.read_text")
    def test_detect_wsl_host(self, mock_read_text, mock_run):
        # Test via ip route
        mock_proc = MagicMock()
        mock_proc.stdout = "default via 172.20.0.1 dev eth0 proto kernel\n"
        mock_run.return_value = mock_proc

        with patch(
            "pystdoc.llm_client.LLMClient._ping_url", return_value=False
        ):
            client = LLMClient(host="127.0.0.1:11434")
            client.user_specified_host = False
            wsl_ip = client._detect_wsl_host()
            self.assertEqual(wsl_ip, "172.20.0.1")

        # Test via resolv.conf fallback
        mock_run.side_effect = Exception("No ip command")
        mock_read_text.return_value = "nameserver 172.25.0.1\n"
        wsl_ip2 = client._detect_wsl_host()
        self.assertEqual(wsl_ip2, "172.25.0.1")

    def test_ping_url_status_handling(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434", token="secret")

        # Success on 200
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.assertTrue(client._ping_url("http://localhost:11434/v1"))

        # HTTP error 401 (still means server is alive)
        http_err_401 = urllib.error.HTTPError(
            "http://localhost:11434/v1", 401, "Unauthorized", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=http_err_401):
            self.assertTrue(client._ping_url("http://localhost:11434/v1"))

        # HTTP error 500 (unreachable)
        http_err_500 = urllib.error.HTTPError(
            "http://localhost:11434/v1", 500, "Internal Error", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=http_err_500):
            self.assertFalse(client._ping_url("http://localhost:11434/v1"))

    def test_chat_completion_success_and_json_mode(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434", token="secret")

        mock_resp_obj = MagicMock()
        content_str = "{\"purpose\": \"Success\"}"
        body_bytes = json.dumps({
            "choices": [{"message": {"content": content_str}}]
        }).encode("utf-8")
        mock_resp_obj.read.return_value = body_bytes
        lines_iter = [body_bytes, b""]
        mock_resp_obj.readline.side_effect = (
            lambda: lines_iter.pop(0) if lines_iter else b""
        )
        mock_resp_obj.__enter__.return_value = mock_resp_obj
        mock_resp_obj.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp_obj):
            res = client.chat_completion(
                [{"role": "user", "content": "hello"}],
                json_mode=True,
            )
            self.assertEqual(res, "{\"purpose\": \"Success\"}")

    def test_chat_completion_http_errors_and_retries(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434")

        # 404 error aborts immediately
        mock_fp = MagicMock()
        mock_fp.read.return_value = b"Not Found"
        err_404 = urllib.error.HTTPError(
            "http://localhost:11434", 404, "Not Found", {}, mock_fp
        )
        with patch("urllib.request.urlopen", side_effect=err_404):
            with self.assertRaises(LLMError) as cm:
                client.chat_completion(
                    [{"role": "user", "content": "hi"}], max_retries=1
                )
            self.assertIn("HTTP Error 404", str(cm.exception))

        # General error retries and fails
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("Connection reset"),
        ):
            with patch("time.sleep", return_value=None):
                with self.assertRaises(LLMError) as cm:
                    client.chat_completion(
                        [{"role": "user", "content": "hi"}], max_retries=2
                    )
                self.assertIn("Connection reset", str(cm.exception))

    def test_explain_symbol_success_and_fallbacks(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434")

        # Success path
        ret_val = "{\"purpose\": \"Calculate math\"}"
        with patch.object(client, "chat_completion", return_value=ret_val):
            res = client.explain_symbol(
                name="add",
                kind="function",
                code="int add() { return 1; }",
                signature="int add()",
                lang="C",
                callees=[],
                params=["a", "b"],
                ret_type="int",
                language="English",
            )
            self.assertEqual(res["purpose"], "Calculate math")

        # Fallback English
        with patch.object(
            client, "chat_completion", side_effect=LLMError("LLM failed")
        ):
            res_fb_en = client.explain_symbol(
                name="add",
                kind="function",
                code="int add() { return 1; }",
                signature="int add()",
                lang="C",
                callees=[],
                params=[],
                ret_type="int",
                language="English",
                allow_fallback=True,
            )
            self.assertIn("Executes `add` operations.", res_fb_en["purpose"])

        # Fallback Japanese
        with patch.object(
            client, "chat_completion", side_effect=LLMError("LLM failed")
        ):
            res_fb_ja = client.explain_symbol(
                name="add",
                kind="function",
                code="int add() { return 1; }",
                signature="int add()",
                lang="C",
                callees=[],
                params=[],
                ret_type="int",
                language="Japanese",
                allow_fallback=True,
            )
            self.assertIn("`add` の処理を実行する。", res_fb_ja["purpose"])

        # Strict error when allow_fallback=False
        with patch.object(
            client, "chat_completion", side_effect=LLMError("LLM failed")
        ):
            with self.assertRaises(LLMError):
                client.explain_symbol(
                    name="add",
                    kind="function",
                    code="int add() { return 1; }",
                    signature="int add()",
                    lang="C",
                    callees=[],
                    params=[],
                    ret_type="int",
                    allow_fallback=False,
                )

    def test_refine_variable_top_down_success_and_fallbacks(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434")

        parents = [{
            "name": "main",
            "file": "main.c",
            "purpose": "App run",
            "overview": "Desc",
        }]

        # Success path
        ret_val = "{\"significance\": \"Important counter\"}"
        with patch.object(client, "chat_completion", return_value=ret_val):
            res = client.refine_variable_top_down(
                var_name="counter",
                var_kind="variable",
                var_signature="int counter",
                var_code="int counter = 0;",
                parent_functions_info=parents,
                lang="C",
                language="English",
            )
            self.assertEqual(res["significance"], "Important counter")

        # Fallback English
        with patch.object(
            client, "chat_completion", side_effect=LLMError("LLM failed")
        ):
            res_fb_en = client.refine_variable_top_down(
                var_name="counter",
                var_kind="variable",
                var_signature="int counter",
                var_code="int counter = 0;",
                parent_functions_info=parents,
                lang="C",
                language="English",
                allow_fallback=True,
            )
            self.assertIn("counter", res_fb_en["significance"])

        # Fallback Japanese
        with patch.object(
            client, "chat_completion", side_effect=LLMError("LLM failed")
        ):
            res_fb_ja = client.refine_variable_top_down(
                var_name="counter",
                var_kind="variable",
                var_signature="int counter",
                var_code="int counter = 0;",
                parent_functions_info=parents,
                lang="C",
                language="Japanese",
                allow_fallback=True,
            )
            self.assertIn("状態/データ", res_fb_ja["significance"])

        # Strict error when allow_fallback=False
        with patch.object(
            client, "chat_completion", side_effect=LLMError("LLM failed")
        ):
            with self.assertRaises(LLMError):
                client.refine_variable_top_down(
                    var_name="counter",
                    var_kind="variable",
                    var_signature="int counter",
                    var_code="int counter = 0;",
                    parent_functions_info=parents,
                    lang="C",
                    allow_fallback=False,
                )

    def test_json_extract_fallback_stages(self):
        # 1. Unfenced but braced JSON
        braced_text = "Analysis result: {\"purpose\": \"Braced\"} done."
        res = extract_json_from_text(braced_text)
        self.assertEqual(res["purpose"], "Braced")

        # 2. Broken fenced JSON raises exception
        broken_fence = "```json\n{broken\n```"
        with self.assertRaises(Exception):
            extract_json_from_text(broken_fence)

    @patch("subprocess.run")
    def test_wsl_reachable_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.stdout = "default via 192.168.1.1 dev eth0\n"
        mock_run.return_value = mock_proc

        with patch.object(
            LLMClient,
            "_ping_url",
            side_effect=[False, True, True],
        ):
            client = LLMClient()
            self.assertTrue(client.check_availability())
            self.assertIn("192.168.1.1", client.base_url)

    def test_ping_url_exception_handling(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434")

        with patch("urllib.request.urlopen", side_effect=Exception("Timeout")):
            self.assertFalse(client._ping_url("http://localhost:11434/v1"))

    def test_chat_completion_retry_sleep_path(self):
        with patch(
            "pystdoc.llm_client.LLMClient.ensure_reachable", return_value=True
        ):
            client = LLMClient("http://localhost:11434")

        mock_err_fp = MagicMock()
        mock_err_fp.read.side_effect = Exception("Read error")
        http_err_500 = urllib.error.HTTPError(
            "http://localhost:11434", 500, "Internal Error", {}, mock_err_fp
        )

        with patch("urllib.request.urlopen", side_effect=http_err_500):
            with patch(
                "pystdoc.llm_client.interruptible_sleep"
            ) as mock_sleep:
                with self.assertRaises(LLMError):
                    client.chat_completion(
                        [{"role": "user", "content": "test"}], max_retries=2
                    )
                self.assertTrue(mock_sleep.called)


if __name__ == "__main__":
    unittest.main()
