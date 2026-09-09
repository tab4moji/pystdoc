"""Performance profiler and regression estimator with streaming tracking.

Models LLM generation time and output volume:
- Duration: t = a0 + a1 * z^1 + a2 * z^2 + a3 * z^3
- Output Chars: chars = b0 + b1 * z^1 + b2 * z^2
where z = line_count * sqrt(complexity), categorized by
(host, model, gen_type, symbol_kind).
Persisted under ~/.config/pystdoc/perf_metrics.json.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pystdoc.config import get_perf_metrics_path


def solve_linear_system(
    matrix: List[List[float]], vector: List[float]
) -> List[float]:
    """Solve M * x = v using Gaussian elimination with partial pivoting."""
    n = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(n)]

    for col in range(n):
        max_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if max_row != col:
            augmented[col], augmented[max_row] = (
                augmented[max_row],
                augmented[col],
            )

        pivot = augmented[col][col]
        if abs(pivot) < 1e-12:
            continue

        for r in range(col + 1, n):
            factor = augmented[r][col] / pivot
            for c in range(col, n + 1):
                augmented[r][c] -= factor * augmented[col][c]

    solution = [0.0] * n
    for r in range(n - 1, -1, -1):
        pivot = augmented[r][r]
        if abs(pivot) < 1e-12:
            solution[r] = 0.0
            continue
        total = augmented[r][n] - sum(
            augmented[r][c] * solution[c] for c in range(r + 1, n)
        )
        solution[r] = total / pivot

    return solution


def fit_polynomial_regression(
    samples: List[Tuple[float, float]], degree: int = 3
) -> List[float]:
    """Fit a polynomial of given degree: t = a0 + a1*x + a2*x^2 + a3*x^3.

    Samples: list of (input_size z, target_value y).
    Returns list of coefficients [a0, a1, ...].
    """
    if not samples:
        return [0.8, 0.02, 0.0, 0.0]

    num_coeffs = degree + 1
    if len(samples) == 1:
        x, t = samples[0]
        a0 = max(0.1, t)
        return [a0] + [0.0] * degree

    max_power = 2 * degree
    s = [0.0] * (max_power + 1)
    s[0] = float(len(samples))
    t_vec = [0.0] * num_coeffs

    for x, y in samples:
        x_val = max(1.0, float(x))
        y_val = max(0.01, float(y))

        cur_x = 1.0
        for p in range(1, max_power + 1):
            cur_x *= x_val
            s[p] += cur_x

        cur_t_x = y_val
        t_vec[0] += y_val
        for p in range(1, num_coeffs):
            cur_t_x *= x_val
            t_vec[p] += cur_t_x

    matrix = [[s[r + c] for c in range(num_coeffs)] for r in range(num_coeffs)]

    for i in range(num_coeffs):
        matrix[i][i] += 1e-5

    coeffs = solve_linear_system(matrix, t_vec)
    return coeffs


def evaluate_polynomial(coeffs: List[float], x: float) -> float:
    """Evaluate polynomial with safety bounds."""
    x_val = max(1.0, float(x))
    res = 0.0
    cur_x = 1.0
    for c in coeffs:
        res += c * cur_x
        cur_x *= x_val
    return max(0.05, res)


class PerfProfileManager:
    """Manages performance metrics database per (server, model, category)."""

    _instance: Optional["PerfProfileManager"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, metrics_file: Optional[Path] = None):
        self.metrics_file = (
            metrics_file
            if metrics_file is not None
            else get_perf_metrics_path()
        )
        self.lock = threading.Lock()
        self.data: Dict[str, Any] = {}
        self.load()

    @classmethod
    def get_instance(
        cls, metrics_file: Optional[Path] = None
    ) -> "PerfProfileManager":
        """Get or create singleton instance."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(metrics_file=metrics_file)
            return cls._instance

    def _get_key(self, host: Optional[str], model: Optional[str]) -> str:
        h = (host or "default").strip().rstrip("/")
        m = (model or "default").strip()
        return f"{h}::{m}"

    def _get_category_key(
        self, gen_type: str, symbol_kind: Optional[str]
    ) -> str:
        g = gen_type.lower().strip()
        k = (symbol_kind or "general").lower().strip()
        return f"{g}::{k}"

    def load(self) -> None:
        """Load performance metrics from JSON file."""
        with self.lock:
            if not self.metrics_file.exists():
                self.data = {}
                return
            try:
                content = self.metrics_file.read_text(
                    encoding="utf-8", errors="replace"
                )
                self.data = json.loads(content)
                if not isinstance(self.data, dict):
                    self.data = {}
            except Exception:
                self.data = {}

    def save(self) -> None:
        """Save performance metrics to JSON file safely."""
        with self.lock:
            try:
                self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_file = self.metrics_file.with_suffix(".tmp")
                tmp_file.write_text(
                    json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                tmp_file.replace(self.metrics_file)
            except Exception:
                pass

    def record_measurement(
        self,
        host: Optional[str],
        model: Optional[str],
        gen_type: str,
        symbol_kind: Optional[str],
        line_count: int,
        elapsed_seconds: float,
        output_chars: Optional[int] = None,
        complexity: Optional[float] = None,
    ) -> None:
        """Record an execution measurement and update regressions."""
        key = self._get_key(host, model)
        cat_key = self._get_category_key(gen_type, symbol_kind)
        x_lines = max(1, int(line_count))
        c_val = max(1.0, float(complexity if complexity is not None else 1.0))
        z_work = x_lines * (c_val ** 0.5)
        t_sec = max(0.01, float(elapsed_seconds))
        chars_cnt = int(output_chars) if output_chars is not None else None

        with self.lock:
            if key not in self.data:
                self.data[key] = {"categories": {}}

            cat_dict = self.data[key]["categories"].setdefault(
                cat_key, {"samples": [], "coeffs": [], "chars_coeffs": []}
            )
            samples = cat_dict.setdefault("samples", [])
            sample_entry: Dict[str, Any] = {
                "x": x_lines,
                "c": round(c_val, 2),
                "z": round(z_work, 2),
                "t": round(t_sec, 3),
                "timestamp": round(time.time(), 1),
            }
            if chars_cnt is not None:
                sample_entry["chars"] = chars_cnt
            samples.append(sample_entry)

            if len(samples) > 100:
                samples = samples[-100:]
                cat_dict["samples"] = samples

            sample_pairs = [
                (s.get("z", s["x"]), s["t"]) for s in samples
            ]
            cat_dict["coeffs"] = fit_polynomial_regression(
                sample_pairs, degree=3
            )

            chars_samples = [
                (s.get("z", s["x"]), float(s["chars"]))
                for s in samples
                if "chars" in s
            ]
            if chars_samples:
                cat_dict["chars_coeffs"] = fit_polynomial_regression(
                    chars_samples, degree=2
                )

        self.save()

    def predict_duration(
        self,
        host: Optional[str],
        model: Optional[str],
        gen_type: str,
        symbol_kind: Optional[str],
        line_count: int,
        complexity: float = 1.0,
    ) -> float:
        """Predict expected execution duration in seconds using regression."""
        key = self._get_key(host, model)
        cat_key = self._get_category_key(gen_type, symbol_kind)
        x_lines = max(1, int(line_count))
        c_val = max(1.0, float(complexity))
        z_work = x_lines * (c_val ** 0.5)

        with self.lock:
            cat_data = (
                self.data.get(key, {}).get("categories", {}).get(cat_key, {})
            )
            coeffs = cat_data.get("coeffs")

            if not coeffs:
                all_cats = self.data.get(key, {}).get("categories", {})
                for c_k, c_v in all_cats.items():
                    if c_v.get("coeffs"):
                        coeffs = c_v["coeffs"]
                        break

            if not coeffs:
                coeffs = [0.8, 0.03, 0.0, 0.0]

        return evaluate_polynomial(coeffs, z_work)

    def predict_output_chars(
        self,
        host: Optional[str],
        model: Optional[str],
        gen_type: str,
        symbol_kind: Optional[str],
        line_count: int,
        complexity: float = 1.0,
    ) -> int:
        """Predict expected output characters from lines and complexity."""
        key = self._get_key(host, model)
        cat_key = self._get_category_key(gen_type, symbol_kind)
        x_lines = max(1, int(line_count))
        c_val = max(1.0, float(complexity))
        z_work = x_lines * (c_val ** 0.5)
        k = (symbol_kind or "general").lower().strip()

        with self.lock:
            cat_data = (
                self.data.get(key, {}).get("categories", {}).get(cat_key, {})
            )
            chars_coeffs = cat_data.get("chars_coeffs")
            if not chars_coeffs:
                all_cats = self.data.get(key, {}).get("categories", {})
                for c_k, c_v in all_cats.items():
                    if c_v.get("chars_coeffs"):
                        chars_coeffs = c_v["chars_coeffs"]
                        break

            if chars_coeffs:
                pred = evaluate_polynomial(chars_coeffs, z_work)
                return max(150, int(round(pred)))

        # Default heuristic based on symbol kind & complexity
        if k in (
            "function", "async_function", "method",
            "constructor", "destructor", "fn"
        ):
            base = 400 + int(round(5 * x_lines + 15 * c_val))
        elif k in ("type", "struct", "class", "data_models", "interface"):
            base = 550 + int(round(7 * x_lines + 20 * c_val))
        elif k in (
            "var", "variable", "field", "const", "enum_constant", "property"
        ):
            base = 320 + int(round(3 * x_lines + 10 * c_val))
        elif k in ("module_doc", "modules"):
            base = 850 + int(round(8 * x_lines + 25 * c_val))
        elif k == "overview":
            base = 1200 + int(round(12 * x_lines + 35 * c_val))
        elif k == "readme":
            base = 1600 + int(round(15 * x_lines + 40 * c_val))
        elif k == "execution_model":
            base = 1100 + int(round(10 * x_lines + 30 * c_val))
        else:
            base = 450 + int(round(6 * x_lines + 18 * c_val))

        return max(150, base)
