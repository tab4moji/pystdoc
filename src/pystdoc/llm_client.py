"""LLM Client for LiteRT-LM, Ollama, and OpenAI-compatible endpoints with multi-language JSON normalization and retry resilience."""

import json
import os
import re
import subprocess
import time
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class LLMError(RuntimeError):
    """Exception raised when LLM generation or connection fails in strict mode."""
    pass


def normalize_host_url(host: Optional[str]) -> str:
    """Normalize user-provided host string into a standard OpenAI-compatible base URL."""
    if not host:
        return "http://127.0.0.1:11434/v1"

    h = host.strip().rstrip("/")
    if not h.startswith(("http://", "https://")):
        h = f"http://{h}"

    if not h.endswith("/v1"):
        h = f"{h}/v1"

    return h


def normalize_llm_json_dict(data: Dict[str, Any]) -> Dict[str, str]:
    """Normalize JSON dictionary keys from any language (English, Japanese, etc.) into standardized keys."""
    normalized: Dict[str, str] = {}

    for k in ("purpose", "目的", "設計意図", "意図", "description", "target", "role", "機能"):
        if k in data and data[k]:
            normalized["purpose"] = str(data[k]).strip()
            break

    for k in ("inputs", "入力", "引数", "パラメータ", "input", "arguments", "parameters"):
        if k in data and data[k]:
            normalized["inputs"] = str(data[k]).strip()
            break

    for k in ("outputs", "出力", "戻り値", "返り値", "output", "returns", "result"):
        if k in data and data[k]:
            normalized["outputs"] = str(data[k]).strip()
            break

    for k in ("overview", "概要", "要約", "説明", "summary", "details"):
        if k in data and data[k]:
            normalized["overview"] = str(data[k]).strip()
            break

    for k in ("significance", "重要性", "役割", "意義", "role"):
        if k in data and data[k]:
            normalized["significance"] = str(data[k]).strip()
            break

    for k in ("usage_scenario", "利用シナリオ", "使用シナリオ", "データフロー", "データ受け渡し", "scenario"):
        if k in data and data[k]:
            normalized["usage_scenario"] = str(data[k]).strip()
            break

    for k in ("top_down_summary", "要約", "概要", "全体設計要約", "summary"):
        if k in data and data[k]:
            normalized["top_down_summary"] = str(data[k]).strip()
            break

    return normalized


def extract_json_from_text(raw_text: str) -> Dict[str, Any]:
    """Robustly extract and parse JSON object from LLM response text."""
    clean = raw_text.strip()
    # 1. Try markdown code block extraction
    m_code = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
    if m_code:
        try:
            return json.loads(m_code.group(1).strip())
        except Exception:
            pass

    # 2. Try outermost curly braces
    m_brace = re.search(r"\{[\s\S]*\}", clean)
    if m_brace:
        try:
            return json.loads(m_brace.group(0).strip())
        except Exception:
            pass

    # 3. Direct parse
    return json.loads(clean)


class LLMClient:
    """OpenAI-compatible client with standard host, token, context size, and model configuration."""

    def __init__(
        self,
        host: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gemma4-26b-a4b",
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        context_size: int = 16384,
        timeout: int = 60,
    ):
        raw_host = host or base_url or os.environ.get("LLM_HOST") or os.environ.get("OPENAI_BASE_URL")
        self.user_specified_host = raw_host is not None
        self.base_url = normalize_host_url(raw_host)
        self.model = model or os.environ.get("LLM_MODEL", "gemma4-26b-a4b")
        self.token = token or api_key or os.environ.get("LLM_TOKEN") or os.environ.get("OPENAI_API_KEY")
        self.context_size = context_size or int(os.environ.get("LLM_CONTEXT_SIZE", "16384"))
        self.default_timeout = timeout

        self.ensure_reachable()

    def ensure_reachable(self) -> bool:
        """Check and discover reachable endpoint, keeping user-specified host intact."""
        if self._ping_url(self.base_url):
            return True

        if self.user_specified_host:
            return False

        wsl_host = self._detect_wsl_host()
        if wsl_host:
            candidate = f"http://{wsl_host}:11434/v1"
            if self._ping_url(candidate):
                self.base_url = candidate
                return True

        return False

    def _ping_url(self, url: str) -> bool:
        """Check if an endpoint is reachable via multiple candidate health endpoints."""
        candidates = [
            f"{url}/models",
            url,
            url.rsplit("/v1", 1)[0] if url.endswith("/v1") else url,
            f"{url.rsplit('/v1', 1)[0]}/api/tags" if url.endswith("/v1") else f"{url}/api/tags",
        ]
        for target in candidates:
            try:
                req = urllib.request.Request(target, method="GET")
                if self.token:
                    req.add_header("Authorization", f"Bearer {self.token}")
                with urllib.request.urlopen(req, timeout=1.5) as res:
                    if res.status in (200, 204, 401):
                        return True
            except urllib.error.HTTPError as he:
                if he.code in (200, 204, 401, 403):
                    return True
            except Exception:
                pass
        return False

    def _detect_wsl_host(self) -> Optional[str]:
        """Detect WSL default gateway host IP via ip route or resolv.conf."""
        try:
            res = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=1)
            for line in res.stdout.splitlines():
                if line.startswith("default via"):
                    return line.split()[2].strip()
        except Exception:
            pass

        try:
            resolv = Path("/etc/resolv.conf").read_text()
            for line in resolv.splitlines():
                if line.strip().startswith("nameserver"):
                    return line.split()[1].strip()
        except Exception:
            pass
        return None

    def check_availability(self) -> bool:
        """Verify server connectivity."""
        return self.ensure_reachable()

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = False,
        max_tokens: int = 1024,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> str:
        """Execute chat completion request with retry loop, token authentication, and context size limits."""
        url = f"{self.base_url}/chat/completions"
        req_timeout = timeout or self.default_timeout

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "options": {
                "num_ctx": self.context_size,
            },
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = json.dumps(payload).encode("utf-8")

        last_error = None
        for attempt in range(1, max_retries + 1):
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")

            try:
                with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    return res_data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as he:
                err_body = ""
                try:
                    err_body = he.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                detail = f": {err_body}" if err_body else ""
                last_error = f"HTTP Error {he.code}: {he.reason}{detail}"
                if he.code == 404:
                    break
                if attempt < max_retries:
                    time.sleep(1.0 * attempt)
                    continue
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    time.sleep(1.0 * attempt)
                    continue

        raise LLMError(f"LLM API call failed ({url}, model={self.model}): {last_error}")

    def explain_symbol(
        self,
        name: str,
        kind: str,
        code: str,
        signature: str,
        lang: str,
        callees: List[str],
        params: List[str],
        ret_type: str,
        callee_context: str = "",
        language: str = "English",
        allow_fallback: bool = False,
    ) -> Dict[str, str]:
        """Generate concise explanations for a symbol in JSON format in the requested natural language."""
        prompt = f"""Please analyze the following {lang} symbol `{name}` ({kind}) and output concise design intent and specifications in JSON format.
Output Language: {language} (Write all explanation text in {language}).
Be concise and avoid repetition.

### Signature / Type:
`{signature}`

### Parameters:
{', '.join(params) if params else 'None'}

### Return Type:
{ret_type or 'void / None'}

### Called Functions:
{', '.join(callees) if callees else 'None'}

{callee_context}

### Source Code:
```{lang}
{code}
```

Return ONLY a valid JSON object matching these keys (values written in {language}):
{{
  "purpose": "Core design intent and purpose (1-2 concise sentences in {language})",
  "inputs": "Input parameters description (or None)",
  "outputs": "Return value or side effects description",
  "overview": "Concise summary of implementation and role (1-3 sentences in {language})"
}}
"""
        messages = [
            {"role": "system", "content": f"You are a principal software architect. You output ONLY valid JSON in {language}."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw_res = self.chat_completion(messages, json_mode=False, max_tokens=768, timeout=60)
            parsed = extract_json_from_text(raw_res)
            return normalize_llm_json_dict(parsed)
        except Exception as e:
            if not allow_fallback:
                raise LLMError(f"Failed to analyze symbol `{name}`: {e}") from e
            is_ja = language in ("Japanese", "日本語")
            return {
                "purpose": f"`{name}` の処理を実行する。" if is_ja else f"Executes `{name}` operations.",
                "inputs": "パラメータを受け取る。" if is_ja else "Accepts input parameters.",
                "outputs": "結果値を返す。" if is_ja else "Returns result value.",
                "overview": f"`{name}` の基本処理。" if is_ja else f"Basic operation for `{name}`.",
            }

    def refine_variable_top_down(
        self,
        var_name: str,
        var_kind: str,
        var_signature: str,
        var_code: str,
        parent_functions_info: List[Dict[str, str]],
        lang: str,
        language: str = "English",
        allow_fallback: bool = False,
    ) -> Dict[str, str]:
        """Refine variable significance using top-down context in the requested language."""
        context_lines = []
        for f in parent_functions_info:
            context_lines.append(f"- Function `{f['name']}` ({f['file']}): {f['purpose']}")
            if f.get("overview"):
                context_lines.append(f"  Overview: {f['overview']}")

        prompt = f"""Please analyze the following {lang} variable/field `{var_name}` in the context of the caller/parent functions that reference it.
Output Language: {language} (Write all text in {language}).
Be concise and avoid repetition.

### Variable: `{var_name}` ({var_kind})
- Signature/Type: `{var_signature}`

### Referencing Caller Functions:
{chr(10).join(context_lines)}

Return ONLY a valid JSON object (all string values in {language}):
{{
  "significance": "Essential significance and design rationale in context of callers (1-2 sentences)",
  "usage_scenario": "Data passing lifecycle and state management role across parent functions (1-2 sentences)",
  "top_down_summary": "Overall design summary (1 sentence)"
}}
"""
        messages = [
            {"role": "system", "content": f"You are a principal software architect. You output ONLY valid JSON in {language}."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw_res = self.chat_completion(messages, json_mode=False, max_tokens=768, timeout=60)
            parsed = extract_json_from_text(raw_res)
            return normalize_llm_json_dict(parsed)
        except Exception as e:
            if not allow_fallback:
                raise LLMError(f"Failed top-down variable refinement for `{var_name}`: {e}") from e
            is_ja = language in ("Japanese", "日本語")
            return {
                "significance": f"`{var_name}` は呼び出し元で使用される状態/データ。" if is_ja else f"`{var_name}` is a state/data utilized by callers.",
                "usage_scenario": "呼び出し元関数間で受け渡される。" if is_ja else "Passed and transformed across calling functions.",
                "top_down_summary": f"`{var_name}` の設計概要。" if is_ja else f"Design summary for `{var_name}`.",
            }
