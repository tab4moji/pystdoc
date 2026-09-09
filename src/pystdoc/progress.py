"""Progress bar and tracker utilities for pystdoc pipeline."""

import shutil
import sys
import threading
import unicodedata
from typing import Optional


def is_terminal(stream=None) -> bool:
    """Check if the given stream (default sys.stdout) is an interactive TTY."""
    if stream is None:
        stream = sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def get_display_width(text: str) -> int:
    """Calculate terminal display width considering East Asian characters."""
    width = 0
    for ch in text:
        if ch in ("\r", "\n", "\b") or ord(ch) < 32:
            continue
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def truncate_display_width(
    text: str, max_width: int, suffix: str = "..."
) -> str:
    """Truncate text to fit within max_width display columns."""
    if max_width <= 0:
        return ""
    if get_display_width(text) <= max_width:
        return text

    suffix_w = get_display_width(suffix)
    target_w = max(0, max_width - suffix_w)

    cur_w = 0
    res = []
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        cw = 2 if eaw in ("W", "F") else 1
        if cur_w + cw > target_w:
            break
        res.append(ch)
        cur_w += cw
    return "".join(res) + suffix


def render_pip_bar(current: float, total: int, width: int = 24) -> str:
    """Render a pip-style unicode progress bar: [━━━━━━━━━━          ]."""
    if total <= 0:
        filled_len = width
    else:
        ratio = max(0.0, min(1.0, float(current) / total))
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
    sub_step_ratio: float = 0.0,
) -> str:
    """Format a single progress line with step, bar, and ratio."""
    if is_tty is None:
        is_tty = is_terminal(sys.stdout)

    eff_current = current + max(0.0, min(0.99, sub_step_ratio))
    pct = (eff_current / total * 100.0) if total > 0 else 100.0
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
        bar_str = f" {render_pip_bar(eff_current, total, width=width)}"
        prefix = f"[{phase_label}]{bar_str} {ratio_str}{timing_str}"
        cols = shutil.get_terminal_size((80, 24)).columns
        max_line_w = max(20, cols - 2)

        prefix_w = get_display_width(prefix)
        if extra:
            sep = ": "
            sep_w = get_display_width(sep)
            avail_extra_w = max_line_w - prefix_w - sep_w
            if avail_extra_w > 4:
                trimmed_extra = truncate_display_width(extra, avail_extra_w)
                line = f"{prefix}{sep}{trimmed_extra}"
            else:
                line = truncate_display_width(prefix, max_line_w)
        else:
            line = truncate_display_width(prefix, max_line_w)
        return line
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
        self.sub_step_ratio = 0.0
        self.stream = stream if stream is not None else sys.stdout
        self.is_tty = is_terminal(self.stream) if is_tty is None else is_tty
        self.width = width
        self.lock = threading.Lock()
        self._finished = False
        self.est_remaining: Optional[float] = None
        self.last_rendered_len = 0

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
            sub_step_ratio=self.sub_step_ratio,
        )

    def _write_in_place(self, line: str) -> None:
        """Write line in place on TTY using BS and return carriage."""
        if self.is_tty:
            cur_w = get_display_width(line)
            prev_w = self.last_rendered_len
            if prev_w > cur_w:
                pad = prev_w - cur_w
                self.stream.write(f"\r{line}{' ' * pad}{'\b' * pad}")
            else:
                self.stream.write(f"\r{line}\033[K")
            self.last_rendered_len = cur_w
            self.stream.flush()
        else:
            self.stream.write(f"{line}\n")
            self.stream.flush()

    def update_stream(
        self,
        current_chars: int,
        predicted_chars: int,
        extra: str = "",
        est_remaining: Optional[float] = None,
    ) -> str:
        """Update in-progress streaming ratio and refresh progress line."""
        with self.lock:
            ratio = max(
                0.0, min(0.99, current_chars / max(1, predicted_chars))
            )
            self.sub_step_ratio = ratio
            if est_remaining is not None:
                self.est_remaining = est_remaining
            line = self._render(extra=extra, est_remaining=self.est_remaining)
            if self.is_tty:
                self._write_in_place(line)
        return line

    def advance(
        self,
        step: int = 1,
        extra: str = "",
        elapsed: Optional[float] = None,
        est_remaining: Optional[float] = None,
    ) -> str:
        """Advance progress and update in-place progress line on TTY."""
        with self.lock:
            self.sub_step_ratio = 0.0
            self.current = min(self.total, self.current + step)
            if est_remaining is not None:
                self.est_remaining = est_remaining
            line = self._render(
                extra=extra, elapsed=elapsed, est_remaining=self.est_remaining
            )
            self._write_in_place(line)
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
            self._write_in_place(line)
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
                self._write_in_place(line)
                self.stream.write("\n")
                self.stream.flush()
