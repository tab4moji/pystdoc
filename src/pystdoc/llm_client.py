"""LLM Client for LiteRT-LM, Ollama, and OpenAI-compatible endpoints with standard host/token/context/language options."""

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
        timeout: int = 180,
    ):
        raw_host = host or base_url or os.environ.get("LLM_HOST") or os.environ.get("OPENAI_BASE_URL")
        self.user_specified_host = raw_host is not None
        self.base_url = normalize_host_url(raw_host)
        self.model = model or os.environ.get("LLM_MODEL", "gemma4-26b-a4b")
        self.token = token or api_key or os.environ.get("LLM_TOKEN") or os.environ.get("OPENAI_API_KEY")
        self.context_size = context_size or int(os.environ.get("LLM_CONTEXT_SIZE", "16384"))
        self.timeout = timeout

        self.ensure_reachable()

    def ensure_reachable(self) -> bool:
        """Check and discover reachable endpoint, keeping user-specified host intact."""
        if self._ping_url(self.base_url):
            return True

        # If the user explicitly passed a host/base_url, never overwrite it with default WSL fallback
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

    def chat_completion(self, messages: List[Dict[str, str]], json_mode: bool = False, max_retries: int = 3) -> str:
        """Execute chat completion request with retry loop, token authentication, and context size limits."""
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4096,
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
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
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
                # If 404 (e.g. model not found), don't retry in vain
                if he.code == 404:
                    break
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)
                    continue
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)
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
        """Generate explanations for a symbol in JSON format in the requested natural language."""
        prompt = f"""Please analyze the following {lang} symbol `{name}` ({kind}) and output its design intent and technical specifications in JSON format.
Output Language: {language} (Write all text values in {language}).

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

Return ONLY a valid JSON object matching this schema (all string values in {language}):
{{
  "purpose": "Core design intent and fundamental purpose of this symbol (1-2 sentences)",
  "inputs": "Meaning, constraints, or pre-conditions of input arguments",
  "outputs": "Meaning of return value or side effects / state mutations",
  "overview": "Clear human-readable summary of the implementation and lifecycle (2-4 sentences)"
}}
"""
        messages = [
            {"role": "system", "content": f"You are a principal software architect. You output ONLY valid JSON in {language}."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw_res = self.chat_completion(messages, json_mode=True)
            m = re.search(r"\{[\s\S]*\}", raw_res)
            if m:
                return json.loads(m.group(0))
            return json.loads(raw_res)
        except Exception as e:
            if not allow_fallback:
                raise LLMError(f"Failed to analyze symbol `{name}`: {e}") from e
            return {
                "purpose": f"Executes `{name}` operations.",
                "inputs": "Accepts input parameters.",
                "outputs": "Returns result value.",
                "overview": f"Basic operation for `{name}`.",
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

### Variable: `{var_name}` ({var_kind})
- Signature/Type: `{var_signature}`

### Referencing Caller Functions:
{chr(10).join(context_lines)}

Return ONLY a valid JSON object matching this schema (all string values in {language}):
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
            raw_res = self.chat_completion(messages, json_mode=True)
            m = re.search(r"\{[\s\S]*\}", raw_res)
            if m:
                return json.loads(m.group(0))
            return json.loads(raw_res)
        except Exception as e:
            if not allow_fallback:
                raise LLMError(f"Failed top-down variable refinement for `{var_name}`: {e}") from e
            return {
                "significance": f"`{var_name}` is a state/data utilized by callers.",
                "usage_scenario": "Passed and transformed across calling functions.",
                "top_down_summary": f"Design summary for `{var_name}`.",
            }
