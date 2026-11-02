"""LLM Client for LiteRT-LM, Ollama, and OpenAI-compatible endpoints."""

import datetime
import http.client
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from pystdoc.interrupt import InterruptionState, interruptible_sleep
from pystdoc.perf import PerfProfileManager


class _InterruptibleHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection registering socket to InterruptionState on connect."""

    def connect(self) -> None:
        InterruptionState.check_interrupted()
        super().connect()
        if self.sock is not None:
            InterruptionState.register_resource(self.sock)

    def close(self) -> None:
        if self.sock is not None:
            InterruptionState.unregister_resource(self.sock)
        super().close()


class _InterruptibleHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection registering socket to InterruptionState on connect."""

    def connect(self) -> None:
        InterruptionState.check_interrupted()
        super().connect()
        if self.sock is not None:
            InterruptionState.register_resource(self.sock)

    def close(self) -> None:
        if self.sock is not None:
            InterruptionState.unregister_resource(self.sock)
        super().close()


class _InterruptibleHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request):
        return self.do_open(_InterruptibleHTTPConnection, req)


class _InterruptibleHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request):
        return self.do_open(_InterruptibleHTTPSConnection, req)


_interruptible_opener = urllib.request.build_opener(
    _InterruptibleHTTPHandler, _InterruptibleHTTPSHandler
)
urllib.request.install_opener(_interruptible_opener)

_debug_log_lock = threading.Lock()
DEBUG_LOG_PATH = Path(os.environ.get("PYSTDOC_DEBUG_LOG", "tmp.debug.log"))
_debug_mode: bool = os.environ.get(
    "PYSTDOC_DEBUG", "0"
).lower() in ("1", "true", "yes")


def set_debug_mode(enabled: bool = True) -> None:
    """Enable or disable realtime debug logging to tmp.debug.log."""
    global _debug_mode
    _debug_mode = enabled
    if enabled:
        os.environ["PYSTDOC_DEBUG"] = "1"
    else:
        os.environ.pop("PYSTDOC_DEBUG", None)


def is_debug_mode() -> bool:
    """Return whether realtime debug logging is enabled."""
    return _debug_mode or os.environ.get(
        "PYSTDOC_DEBUG", "0"
    ).lower() in ("1", "true", "yes")


def _log_debug_request(
    messages: List[Dict[str, str]],
    model: str,
    attempt: int,
    max_retries: int,
) -> None:
    if not is_debug_mode():
        return
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _debug_log_lock:
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write(
                    f"[{now_str}] >>> LLM REQUEST (Attempt {attempt}/"
                    f"{max_retries}, Model: {model})\n"
                )
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    f.write(f"--- [{role}] ---\n")
                    f.write(content.rstrip() + "\n")
                f.write("-" * 80 + "\n")
                f.write(f"[{now_str}] <<< LLM RESPONSE STREAM START:\n")
                f.flush()
        except Exception:
            pass


def _log_debug_chunk(piece: str) -> None:
    if not is_debug_mode():
        return
    with _debug_log_lock:
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(piece)
                f.flush()
        except Exception:
            pass


def _log_debug_response_end(elapsed: float, total_chars: int) -> None:
    if not is_debug_mode():
        return
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _debug_log_lock:
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("\n" + "-" * 80 + "\n")
                f.write(
                    f"[{now_str}] <<< LLM RESPONSE END "
                    f"(Elapsed: {elapsed:.2f}s, Total Chars: {total_chars})\n"
                )
                f.write("=" * 80 + "\n\n")
                f.flush()
        except Exception:
            pass


def _log_debug_error(error_msg: str) -> None:
    if not is_debug_mode():
        return
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _debug_log_lock:
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n[{now_str}] [!] LLM ERROR / RETRY: {error_msg}\n")
                f.flush()
        except Exception:
            pass


class LLMError(RuntimeError):
    """Exception raised when LLM generation fails in strict mode."""


def normalize_host_url(host: Optional[str]) -> str:
    """Normalize user-provided host string into a standard base URL."""
    if not host:
        return "http://127.0.0.1:11434/v1"

    h = host.strip().rstrip("/")
    if not h.startswith(("http://", "https://")):
        h = f"http://{h}"

    if not h.endswith("/v1"):
        h = f"{h}/v1"

    return h


def normalize_llm_json_dict(data: Dict[str, Any]) -> Dict[str, str]:
    """Normalize JSON dictionary keys from any language to standard keys."""
    normalized: Dict[str, str] = {}

    for k in (
        "purpose",
        "目的",
        "設計意図",
        "意図",
        "description",
        "target",
        "機能",
    ):
        if k in data and data[k]:
            normalized["purpose"] = str(data[k]).strip()
            break

    for k in (
        "inputs",
        "入力",
        "引数",
        "パラメータ",
        "input",
        "arguments",
        "parameters",
    ):
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

    for k in ("role", "役割", "significance", "重要性", "意義"):
        if k in data and data[k]:
            normalized["role"] = str(data[k]).strip()
            normalized["significance"] = str(data[k]).strip()
            break

    for k in (
        "usage_scenario",
        "利用シナリオ",
        "使用シナリオ",
        "データフロー",
        "データ受け渡し",
        "scenario",
    ):
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
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty response text cannot be parsed as JSON")

    clean = raw_text.strip()
    # 1. Try markdown code block extraction
    m_code = re.search(
        r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE
    )
    if m_code:
        try:
            res = json.loads(m_code.group(1).strip())
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    # 2. Try outermost curly braces
    m_brace = re.search(r"\{[\s\S]*\}", clean)
    if m_brace:
        try:
            res = json.loads(m_brace.group(0).strip())
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    # 3. Try repairing truncated JSON by closing unclosed brackets/quotes
    idx_brace = clean.find("{")
    if idx_brace != -1:
        partial = clean[idx_brace:].strip()
        partial = re.sub(r"```*$", "", partial).rstrip()
        candidates = [
            partial + "}",
            partial + '"}',
            partial + '"}}',
            partial + '"\n}',
        ]
        for cand in candidates:
            try:
                res = json.loads(cand)
                if isinstance(res, dict):
                    return res
            except Exception:
                continue

    # 4. Direct parse (for valid non-dict JSON primitives)
    res = json.loads(clean)
    raise ValueError(f"Extracted JSON is not a dictionary: {type(res)}")


def sanitize_architectural_context(
    text: Optional[str], fallback_text: str = ""
) -> str:
    """Filter out accidental LLM persona self-identification."""
    if not text:
        return fallback_text
    cleaned = text.strip()
    persona_tokens = {
        "ソフトウェアアーキテクト",
        "ソフトウェア・アーキテクト",
        "アーキテクト",
        "software architect",
        "principal software architect",
        "principal architect",
        "ai assistant",
        "assistant",
    }
    if cleaned.lower() in persona_tokens or cleaned in persona_tokens:
        return fallback_text
    return cleaned


class LLMClient:
    """OpenAI-compatible LLM client with multi-step fallback."""

    def __init__(
        self,
        host: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gemma4-26b-a4b",
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        context_size: Optional[int] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
    ):
        self.user_specified_host = bool(
            host or base_url or os.environ.get("LLM_HOST")
        )
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            resolved_host = (
                host or os.environ.get("LLM_HOST") or "localhost:11434"
            )
            if not resolved_host.startswith("http://") and \
               not resolved_host.startswith("https://"):
                resolved_host = f"http://{resolved_host}"
            if not resolved_host.endswith("/v1"):
                resolved_host = f"{resolved_host.rstrip('/')}/v1"
            self.base_url = resolved_host

        self.model = model or os.environ.get("LLM_MODEL", "gemma4-26b-a4b")
        self.token = (
            token
            or api_key
            or os.environ.get("LLM_TOKEN")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.context_size = context_size or int(
            os.environ.get("LLM_CONTEXT_SIZE", "16384")
        )
        self.max_tokens = max_tokens or int(
            os.environ.get("LLM_MAX_TOKENS", "16384")
        )
        env_to = os.environ.get("LLM_TIMEOUT")
        if timeout is not None:
            self.default_timeout = timeout
        elif env_to and env_to.isdigit():
            self.default_timeout = int(env_to)
        else:
            self.default_timeout = 120

        self._is_first_request: bool = True
        self._last_request_time: Optional[float] = None

        self.ensure_reachable()

    def ensure_reachable(self) -> bool:
        """Check and discover reachable endpoint, keeping host intact."""
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
        """Check if an endpoint is reachable via multiple candidate URLs."""
        base_without_v1 = (
            url.rsplit("/v1", 1)[0] if url.endswith("/v1") else url
        )
        candidates = [
            f"{url}/models",
            url,
            base_without_v1,
            f"{base_without_v1}/api/tags",
        ]
        for target in candidates:
            try:
                req = urllib.request.Request(target, method="GET")
                if self.token:
                    req.add_header("Authorization", f"Bearer {self.token}")
                with urllib.request.urlopen(req, timeout=3.0) as res:
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
            res = subprocess.run(
                ["ip", "route"], capture_output=True, text=True, timeout=1,
                check=False
            )
            for line in res.stdout.splitlines():
                if line.startswith("default via"):
                    return line.split()[2].strip()
        except Exception:
            pass

        try:
            resolv = Path("/etc/resolv.conf").read_text(encoding="utf-8")
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
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        max_retries: int = 3,
        temperature: float = 0.2,
        seed: Optional[int] = None,
        stream: bool = True,
        on_chunk: Optional[Any] = None,
    ) -> str:
        """Execute chat completion request with synchronous or SSE stream."""
        url = f"{self.base_url}/chat/completions"
        effective_max_tokens = (
            max_tokens if max_tokens is not None else self.max_tokens
        )
        now = time.time()
        idle_before = (
            (now - self._last_request_time)
            if self._last_request_time is not None
            else None
        )
        is_first = self._is_first_request
        self._is_first_request = False
        self._last_request_time = now

        input_chars = sum(len(m.get("content", "")) for m in messages)
        perf_mgr = PerfProfileManager.get_instance()
        req_timeout = timeout or perf_mgr.get_adaptive_timeout(
            host=self.base_url,
            model=self.model,
            input_chars=input_chars,
            is_first_in_session=is_first,
            default_timeout=self.default_timeout,
        )
        base_seed = seed if seed is not None else 42

        def _record_success(content_text: str, start_t: float) -> str:
            elapsed = time.time() - start_t
            perf_mgr.record_server_timing(
                host=self.base_url,
                model=self.model,
                input_chars=input_chars,
                output_chars=len(content_text),
                elapsed_seconds=elapsed,
                is_first_in_session=is_first,
                idle_seconds_before=idle_before,
            )
            return content_text

        last_error = None
        for attempt in range(1, max_retries + 1):
            req_start_time = time.time()
            current_seed = base_seed + (attempt - 1) * 17
            current_temp = min(0.7, temperature + (attempt - 1) * 0.1)

            _log_debug_request(messages, self.model, attempt, max_retries)

            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": current_temp,
                "max_tokens": effective_max_tokens,
                "seed": current_seed,
                "stream": stream,
                "options": {
                    "num_ctx": self.context_size,
                    "seed": current_seed,
                    "temperature": current_temp,
                },
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")

            try:
                InterruptionState.check_interrupted()
                resp = urllib.request.urlopen(req, timeout=req_timeout)
                InterruptionState.register_resource(resp)
                try:
                    if not stream:
                        InterruptionState.check_interrupted()
                        raw_bytes = resp.read()
                        if raw_bytes:
                            try:
                                res_data = json.loads(
                                    raw_bytes.decode("utf-8", errors="replace")
                                )
                                content = res_data["choices"][0]["message"][
                                    "content"
                                ]
                                if content and content.strip():
                                    _log_debug_chunk(content)
                                    _log_debug_response_end(
                                        time.time() - req_start_time,
                                        len(content),
                                    )
                                    if on_chunk:
                                        on_chunk(content, len(content))
                                    return _record_success(
                                        content, req_start_time
                                    )
                            except Exception as parse_e:
                                last_error = (
                                    f"Failed to parse response: {parse_e}"
                                )
                    else:
                        accumulated: List[str] = []
                        current_chars = 0
                        consecutive_ws_chars = 0
                        is_sse = False
                        raw_lines: List[bytes] = []

                        while True:
                            InterruptionState.check_interrupted()
                            line = resp.readline()
                            if not line:
                                break
                            raw_lines.append(line)
                            line_str = line.decode(
                                "utf-8", errors="replace"
                            ).strip()
                            if not line_str:
                                continue
                            if line_str.startswith("data:"):
                                is_sse = True
                                data_part = line_str[5:].strip()
                                if data_part == "[DONE]":
                                    break
                                try:
                                    chunk_json = json.loads(data_part)
                                    choices = chunk_json.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content_piece = delta.get("content")
                                        if content_piece:
                                            accumulated.append(content_piece)
                                            current_chars += len(content_piece)
                                            _log_debug_chunk(content_piece)
                                            if on_chunk:
                                                on_chunk(
                                                    content_piece,
                                                    current_chars,
                                                )
                                            # Guard against whitespace runaway
                                            if content_piece.isspace():
                                                consecutive_ws_chars += (
                                                    len(content_piece)
                                                )
                                                if consecutive_ws_chars >= 50:
                                                    cnt = consecutive_ws_chars
                                                    last_error = (
                                                        f"LLM whitespace loop "
                                                        f"detected ({cnt} "
                                                        "chars). Aborting."
                                                    )
                                                    break
                                            else:
                                                trailing_ws = (
                                                    len(content_piece)
                                                    - len(
                                                        content_piece.rstrip()
                                                    )
                                                )
                                                consecutive_ws_chars = (
                                                    trailing_ws
                                                )
                                except Exception:
                                    pass

                        if is_sse:
                            full_content = "".join(accumulated)
                            if full_content and full_content.strip():
                                _log_debug_response_end(
                                    time.time() - req_start_time,
                                    len(full_content),
                                )
                                return _record_success(
                                    full_content, req_start_time
                                )
                        else:
                            full_raw = b"".join(raw_lines)
                            if full_raw:
                                try:
                                    res_data = json.loads(
                                        full_raw.decode(
                                            "utf-8", errors="replace"
                                        )
                                    )
                                    content = res_data["choices"][0][
                                        "message"
                                    ]["content"]
                                    if content and content.strip():
                                        _log_debug_chunk(content)
                                        _log_debug_response_end(
                                            time.time() - req_start_time,
                                            len(content),
                                        )
                                        if on_chunk:
                                            on_chunk(content, len(content))
                                        return _record_success(
                                            content, req_start_time
                                        )
                                except Exception:
                                    pass

                    if not last_error:
                        last_error = "Received empty response content from LLM"
                    _log_debug_error(last_error)
                    if attempt < max_retries:
                        interruptible_sleep(1.0 * attempt)
                        continue
                finally:
                    InterruptionState.unregister_resource(resp)
                    try:
                        resp.close()
                    except Exception:
                        pass
            except urllib.error.HTTPError as he:
                err_body = ""
                try:
                    err_body = he.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                detail = f": {err_body}" if err_body else ""
                last_error = f"HTTP Error {he.code}: {he.reason}{detail}"
                _log_debug_error(last_error)
                if he.code == 404:
                    break
                if attempt < max_retries:
                    interruptible_sleep(1.0 * attempt)
                    continue
            except KeyboardInterrupt:
                InterruptionState.set_interrupted()
                _log_debug_error("Interrupted by user (KeyboardInterrupt)")
                raise
            except Exception as e:
                InterruptionState.check_interrupted()
                last_error = str(e)
                _log_debug_error(last_error)
                if attempt < max_retries:
                    interruptible_sleep(1.0 * attempt)
                    continue

        raise LLMError(
            f"LLM API call failed ({url}, model={self.model}): {last_error}"
        )

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
        max_attempts: int = 3,
        on_chunk: Optional[Any] = None,
    ) -> Dict[str, str]:
        """Generate concise explanations for a symbol in JSON with retry."""
        prompt = f"""Please analyze {lang} symbol `{name}` ({kind})
and output concise design intent and specifications in JSON format.
Output Language: {language} (Write all explanation text in {language}).
Be concise and avoid repetition.

### Signature / Type:
`{signature}`

### Parameters:
{", ".join(params) if params else "None"}

### Return Type:
{ret_type or "void / None"}

### Called Functions:
{", ".join(callees) if callees else "None"}

{callee_context}

### Source Code:
```{lang}
{code}
```

Return a JSON object with these keys (write explanation in {language}):
```json
{{
  "architectural_context": "<Role among callers in {language}>",
  "purpose": "<Core design intent and purpose in {language}>",
  "inputs": "<Input parameters description in {language}>",
  "outputs": "<Return value or side effects description in {language}>",
  "overview": "<Concise summary in {language}>"
}}
```
"""
        sys_msg = (
            "You are a principal software architect analyzing code symbols. "
            f"Output concise factual design specifications in {language} as "
            "JSON."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                def _wrap_chunk(piece: str, total_chars: int) -> None:
                    if on_chunk:
                        try:
                            on_chunk(piece, total_chars, attempt)
                        except TypeError:
                            on_chunk(piece, total_chars)

                raw_res = self.chat_completion(
                    messages,
                    json_mode=False,
                    max_tokens=self.max_tokens,
                    timeout=self.default_timeout,
                    max_retries=1,
                    seed=42 + (attempt - 1) * 100,
                    temperature=0.15 + (attempt - 1) * 0.1,
                    stream=True,
                    on_chunk=_wrap_chunk if on_chunk else None,
                )
                parsed = extract_json_from_text(raw_res)
                norm = normalize_llm_json_dict(parsed)
                has_content = any(
                    norm.get(k)
                    for k in (
                        "purpose",
                        "overview",
                        "role",
                        "architectural_context",
                    )
                )
                if not has_content:
                    raise ValueError(
                        f"Empty explanation from LLM: {raw_res[:100]}"
                    )
                raw_arch = (
                    norm.get("architectural_context")
                    or norm.get("role")
                )
                clean_arch = sanitize_architectural_context(
                    raw_arch, fallback_text=norm.get("purpose", "")
                )
                norm["architectural_context"] = clean_arch
                norm["role"] = clean_arch
                return norm
            except Exception as e:
                last_exc = e
                if attempt < max_attempts:
                    interruptible_sleep(0.5 * attempt)
                    continue

        if not allow_fallback:
            raise LLMError(
                f"Failed to analyze symbol `{name}`: {last_exc}"
            ) from last_exc
        is_ja = language in ("Japanese", "日本語")
        fallback_role = (
            f"プログラムの `{name}` 処理を実行する。"
            if is_ja
            else f"Executes `{name}` operations."
        )
        fallback_purpose = (
            f"`{name}` の処理を実行する。"
            if is_ja
            else f"Executes `{name}` operations."
        )
        return {
            "architectural_context": fallback_role,
            "role": fallback_role,
            "purpose": fallback_purpose,
            "inputs": "パラメータを受け取る。"
            if is_ja
            else "Accepts input parameters.",
            "outputs": "結果値を返す。" if is_ja else "Returns result.",
            "overview": f"`{name}` の基本処理。"
            if is_ja
            else f"Basic operation for `{name}`.",
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
        parent_container_info: Optional[Dict[str, str]] = None,
        max_attempts: int = 3,
        on_chunk: Optional[Any] = None,
    ) -> Dict[str, str]:
        """Refine variable significance using top-down context with retry."""
        context_lines = []
        if parent_container_info:
            c_name = parent_container_info.get("name", "")
            c_kind = parent_container_info.get("kind", "data model")
            c_purp = parent_container_info.get("purpose", "")
            c_line = f"- Parent Container/Model: `{c_name}` ({c_kind})"
            if c_purp:
                c_line += f" - Purpose: {c_purp}"
            context_lines.append(c_line)

        for f in parent_functions_info:
            context_lines.append(
                f"- Referencing Function `{f['name']}` ({f.get('file', '')}): "
                f"{f.get('purpose', '')}"
            )
            if f.get("overview"):
                context_lines.append(f"  Overview: {f['overview']}")

        ctx_str = "\n".join(context_lines) if context_lines else "None"
        prompt = f"""Please analyze {lang} {var_kind} `{var_name}`
based on its parent data model/class and referencing caller functions.
Output Language: {language} (Write all text in {language}).
Tone rule: Strictly objective and concise. No promotional buzzwords.

### Target Symbol: `{var_name}` ({var_kind})
- Signature/Type: `{var_signature or var_name}`

### Architectural & Caller Context:
{ctx_str}

Return a JSON object with these keys (write explanation in {language}):
```json
{{
  "architectural_context": "<Role of `{var_name}` in {language}>",
  "purpose": "<Precise functional purpose of `{var_name}` in {language}>",
  "overview": "<Detailed overview of `{var_name}` in {language}>",
  "usage_scenario": "<Data flow across modules in {language}>"
}}
```
"""
        sys_msg = (
            "You are a principal software architect analyzing code symbols. "
            f"Output concise factual design specifications in {language} as "
            "JSON."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                def _wrap_var_chunk(piece: str, total_chars: int) -> None:
                    if on_chunk:
                        try:
                            on_chunk(piece, total_chars, attempt)
                        except TypeError:
                            on_chunk(piece, total_chars)

                raw_res = self.chat_completion(
                    messages,
                    json_mode=False,
                    max_tokens=self.max_tokens,
                    timeout=self.default_timeout,
                    max_retries=1,
                    seed=42 + (attempt - 1) * 100,
                    temperature=0.15 + (attempt - 1) * 0.1,
                    stream=True,
                    on_chunk=_wrap_var_chunk if on_chunk else None,
                )
                parsed = extract_json_from_text(raw_res)
                norm = normalize_llm_json_dict(parsed)
                has_content = any(
                    norm.get(k)
                    for k in (
                        "purpose",
                        "overview",
                        "significance",
                        "architectural_context",
                        "role",
                        "top_down_summary",
                    )
                )
                if not has_content:
                    raise ValueError(
                        f"Empty explanation from LLM: {raw_res[:100]}"
                    )
                raw_arch = (
                    norm.get("architectural_context")
                    or norm.get("role")
                    or norm.get("significance")
                    or norm.get("top_down_summary")
                )
                clean_arch = sanitize_architectural_context(
                    raw_arch, fallback_text=norm.get("purpose", "")
                )
                norm["architectural_context"] = clean_arch
                norm["role"] = clean_arch
                norm["significance"] = clean_arch
                return norm
            except Exception as e:
                last_exc = e
                if attempt < max_attempts:
                    interruptible_sleep(0.5 * attempt)
                    continue

        if not allow_fallback:
            raise LLMError(
                f"Failed top-down variable refinement for "
                f"`{var_name}`: {last_exc}"
            ) from last_exc
        is_ja = language in ("Japanese", "日本語")
        p_name = (
            parent_container_info.get("name") if parent_container_info else ""
        )
        sig_val = var_signature or var_kind
        if p_name:
            role = (
                f"「{p_name}」における `{var_name}` のデータ保持および連携。"
                if is_ja
                else f"Maintains `{var_name}` data in `{p_name}`."
            )
            purpose = (
                f"データモデル「{p_name}」において、`{var_name}` "
                f"({sig_val}) の値を保持・伝達する。"
                if is_ja
                else (
                    f"Holds and passes `{var_name}` ({sig_val}) "
                    f"within `{p_name}`."
                )
            )
            overview = (
                f"「{p_name}」のプロパティとして、関連処理関数における"
                f"状態管理やモジュール間データ受渡しに使用されます。"
                if is_ja
                else (
                    f"Utilized as a property of `{p_name}` for state "
                    "management and inter-module data transfer."
                )
            )
        else:
            role = (
                f"呼び出し元やモジュールで使用される `{var_name}` の状態/データ。"
                if is_ja
                else f"`{var_name}` is a state/data utilized by callers."
            )
            purpose = (
                f"`{var_name}` ({sig_val}) の状態データを保持する。"
                if is_ja
                else f"Holds state data for `{var_name}` ({sig_val})."
            )
            overview = (
                "関連する各処理関数から参照・更新され、"
                "処理状態や設定データを伝達します。"
                if is_ja
                else (
                    "Referenced and updated across related processing "
                    "functions to communicate state data."
                )
            )

        return {
            "role": role,
            "significance": role,
            "purpose": purpose,
            "overview": overview,
            "usage_scenario": (
                "呼び出し元関数間で受け渡される。"
                if is_ja
                else "Passed and transformed across calling functions."
            ),
            "top_down_summary": overview,
        }
