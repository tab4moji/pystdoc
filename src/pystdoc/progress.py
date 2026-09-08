"""Progress bar and tracker utilities for pystdoc pipeline."""

import shutil
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


def format_eta(seconds: Optional[float]) -> str:
    """Format seconds into a human-friendly ETA string (e.g. 00:45, 02:30)."""
    if seconds is None or seconds < 0:
        return "--:--"
    total_sec = int(round(seconds))
    if total_sec < 3600:
        mins = total_sec // 60
        secs = total_sec % 60
        return f"{mins:02d}:{secs:02d}"
    else:
        hours = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        return f"{hours:02d}:{mins:02d}:{secs:02d}"


def format_progress_line(
    phase_label: str,
    current: int,
    total: int,
    extra: str = "",
    elapsed: Optional[float] = None,
    est_remaining: Optional[float] = None,
    is_tty: Optional[bool] = None,
    width: int = 24,
) -> str:
    """Format a single progress line with step, bar, and ratio."""
    if is_tty is None:
        is_tty = is_terminal(sys.stdout)

    pct = (current / total * 100.0) if total > 0 else 100.0
    if current >= total and elapsed is not None:
        timing_str = f" [Done in {elapsed:5.1f}s]"
    elif current < total and est_remaining is not None:
        timing_str = f" [Est: {format_eta(est_remaining)}]"
    elif elapsed is not None:
        timing_str = f" [Done in {elapsed:5.1f}s]"
    else:
        timing_str = ""

    ratio_str = f"{current}/{total} ({pct:5.1f}%)"

    if is_tty:
        bar_str = f" {render_pip_bar(current, total, width=width)}"
        prefix = f"[{phase_label}]{bar_str} {ratio_str}{timing_str}"
        cols = shutil.get_terminal_size((80, 24)).columns
        max_extra = max(10, cols - len(prefix) - 4)
        if extra:
            if len(extra) > max_extra:
                trimmed = extra[: max_extra - 3] + "..."
            else:
                trimmed = extra
            return f"{prefix}: {trimmed}"
        return prefix
    else:
        bar_str = ""
        detail_str = f": {extra}" if extra else ""
        return f"[{phase_label}]{bar_str} {ratio_str}{timing_str}{detail_str}"


class PhaseProgressTracker:
    """Thread-safe pip-style in-place progress tracker with ETA prediction."""

    def __init__(
        self,
        phase_label: str,
        total: int,
        is_tty: Optional[bool] = None,
        width: int = 24,
        stream=None,
    ):
        self.phase_label = phase_label
        self.total = max(0, total)
        self.current = 0
        self.stream = stream if stream is not None else sys.stdout
        self.is_tty = is_terminal(self.stream) if is_tty is None else is_tty
        self.width = width
        self.lock = threading.Lock()
        self._finished = False
        self.est_remaining: Optional[float] = None

    def set_remaining_estimate(self, seconds: Optional[float]) -> None:
        """Update estimated remaining time in seconds."""
        with self.lock:
            self.est_remaining = seconds

    def _render(
        self,
        extra: str = "",
        elapsed: Optional[float] = None,
        est_remaining: Optional[float] = None,
    ) -> str:
        est = (
            est_remaining
            if est_remaining is not None
            else self.est_remaining
        )
        return format_progress_line(
            phase_label=self.phase_label,
            current=self.current,
            total=self.total,
            extra=extra,
            elapsed=elapsed,
            est_remaining=est,
            is_tty=self.is_tty,
            width=self.width,
        )

    def advance(
        self,
        step: int = 1,
        extra: str = "",
        elapsed: Optional[float] = None,
        est_remaining: Optional[float] = None,
    ) -> str:
        """Advance progress and update in-place progress line on TTY."""
        with self.lock:
            self.current = min(self.total, self.current + step)
            if est_remaining is not None:
                self.est_remaining = est_remaining
            line = self._render(
                extra=extra, elapsed=elapsed, est_remaining=self.est_remaining
            )
            if self.is_tty:
                self.stream.write(f"\r{line}\033[K")
                self.stream.flush()
            else:
                self.stream.write(f"{line}\n")
                self.stream.flush()
        return line

    def render_current(
        self,
        extra: str = "",
        elapsed: Optional[float] = None,
        est_remaining: Optional[float] = None,
    ) -> str:
        """Render current progress state in-place without incrementing."""
        with self.lock:
            if est_remaining is not None:
                self.est_remaining = est_remaining
            line = self._render(
                extra=extra, elapsed=elapsed, est_remaining=self.est_remaining
            )
            if self.is_tty:
                self.stream.write(f"\r{line}\033[K")
                self.stream.flush()
            else:
                self.stream.write(f"{line}\n")
                self.stream.flush()
        return line

    def finish(
        self,
        extra: str = "",
        elapsed: Optional[float] = None,
    ) -> None:
        """Finalize progress bar and write a newline on TTY."""
        with self.lock:
            if self._finished:
                return
            self._finished = True
            if self.is_tty:
                line = self._render(
                    extra=extra, elapsed=elapsed, est_remaining=None
                )
                self.stream.write(f"\r{line}\033[K\n")
                self.stream.flush()
