"""Progress bar and tracker utilities for pystdoc pipeline."""

import sys
import threading
from typing import Optional


def is_terminal(stream=None) -> bool:
    """Check if the given stream (default sys.stdout) is an interactive TTY."""
    if stream is None:
        stream = sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def render_pip_bar(current: int, total: int, width: int = 24) -> str:
    """Render a pip-style unicode progress bar: [━━━━━━━━━━          ]."""
    if total <= 0:
        filled_len = width
    else:
        ratio = max(0.0, min(1.0, current / total))
        filled_len = int(ratio * width)
    empty_len = width - filled_len
    bar = "━" * filled_len + " " * empty_len
    return f"[{bar}]"


def format_progress_line(
    phase_label: str,
    current: int,
    total: int,
    extra: str = "",
    elapsed: Optional[float] = None,
    is_tty: Optional[bool] = None,
    width: int = 24,
) -> str:
    """Format a single progress line with step, bar, and ratio."""
    if is_tty is None:

        is_tty = is_terminal(sys.stdout)

    pct = (current / total * 100.0) if total > 0 else 100.0
    elapsed_str = f" [Done in {elapsed:5.1f}s]" if elapsed is not None else ""
    ratio_str = f"{current}/{total} ({pct:5.1f}%)"

    if is_tty:
        bar_str = f" {render_pip_bar(current, total, width=width)}"
    else:
        bar_str = ""

    detail_str = f": {extra}" if extra else ""
    return f"[{phase_label}]{bar_str} {ratio_str}{elapsed_str}{detail_str}"


class PhaseProgressTracker:
    """Thread-safe progress tracker for unified pipeline phases."""

    def __init__(
        self,
        phase_label: str,
        total: int,
        is_tty: Optional[bool] = None,
        width: int = 24,
    ):
        self.phase_label = phase_label
        self.total = max(0, total)
        self.current = 0
        self.is_tty = is_terminal(sys.stdout) if is_tty is None else is_tty
        self.width = width
        self.lock = threading.Lock()

    def advance(
        self,
        step: int = 1,
        extra: str = "",
        elapsed: Optional[float] = None,
    ) -> str:
        """Advance progress and return the formatted progress line."""
        with self.lock:
            self.current = min(self.total, self.current + step)
            line = format_progress_line(
                phase_label=self.phase_label,
                current=self.current,
                total=self.total,
                extra=extra,
                elapsed=elapsed,
                is_tty=self.is_tty,
                width=self.width,
            )
        return line

    def render_current(
        self,
        extra: str = "",
        elapsed: Optional[float] = None,
    ) -> str:
        """Render current progress state without incrementing."""
        with self.lock:
            return format_progress_line(
                phase_label=self.phase_label,
                current=self.current,
                total=self.total,
                extra=extra,
                elapsed=elapsed,
                is_tty=self.is_tty,
                width=self.width,
            )
