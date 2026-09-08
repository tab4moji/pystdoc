"""Performance profiler and 3rd-order polynomial regression estimator.

Models LLM generation time: t = a0 + a1 * x^1 + a2 * x^2 + a3 * x^3
where x is line count, categorized by (host, model, gen_type, symbol_kind).
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

    Samples: list of (line_count x, elapsed_time t).
    Returns list of coefficients [a0, a1, a2, a3].
    """
    if not samples:
        return [0.8, 0.02, 0.0, 0.0]

    num_coeffs = degree + 1
    if len(samples) == 1:
        x, t = samples[0]
        a0 = max(0.1, t)
        return [a0, 0.0, 0.0, 0.0]

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
    """Evaluate t = a0 + a1*x + a2*x^2 + a3*x^3 with safety bounds."""
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
    ) -> None:
        """Record an execution measurement and update regression."""
        key = self._get_key(host, model)
        cat_key = self._get_category_key(gen_type, symbol_kind)
        x_lines = max(1, int(line_count))
        t_sec = max(0.01, float(elapsed_seconds))

        with self.lock:
            if key not in self.data:
                self.data[key] = {"categories": {}}

            cat_dict = self.data[key]["categories"].setdefault(
                cat_key, {"samples": [], "coeffs": []}
            )
            samples = cat_dict.setdefault("samples", [])
            samples.append(
                {
                    "x": x_lines,
                    "t": round(t_sec, 3),
                    "timestamp": round(time.time(), 1),
                }
            )

            if len(samples) > 100:
                samples = samples[-100:]
                cat_dict["samples"] = samples

            sample_pairs = [(s["x"], s["t"]) for s in samples]
            cat_dict["coeffs"] = fit_polynomial_regression(
                sample_pairs, degree=3
            )

        self.save()

    def predict_duration(
        self,
        host: Optional[str],
        model: Optional[str],
        gen_type: str,
        symbol_kind: Optional[str],
        line_count: int,
    ) -> float:
        """Predict expected execution duration in seconds using regression."""
        key = self._get_key(host, model)
        cat_key = self._get_category_key(gen_type, symbol_kind)
        x_lines = max(1, int(line_count))

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

        return evaluate_polynomial(coeffs, x_lines)
