"""Interruption handler for graceful cancellation via Ctrl-C or 'q' key."""

import atexit
import os
import select
import sys
import threading
from typing import Any, Optional, Set
import time


class InterruptionState:
    """Thread-safe global state for cancellation and active socket abort."""

    _interrupted: bool = False
    _lock: threading.Lock = threading.Lock()
    _active_resources: Set[Any] = set()

    @classmethod
    def register_resource(cls, res: Any) -> None:
        """Register an active socket/connection to abort on interrupt."""
        with cls._lock:
            if cls._interrupted:
                try:
                    res.close()
                except Exception:
                    pass
                return
            cls._active_resources.add(res)

    @classmethod
    def unregister_resource(cls, res: Any) -> None:
        """Unregister a finished network connection."""
        with cls._lock:
            cls._active_resources.discard(res)

    @classmethod
    def set_interrupted(cls) -> None:
        """Set interrupted flag and immediately close all active sockets."""
        with cls._lock:
            cls._interrupted = True
            for res in list(cls._active_resources):
                try:
                    res.close()
                except Exception:
                    pass
            cls._active_resources.clear()

    @classmethod
    def is_interrupted(cls) -> bool:
        with cls._lock:
            return cls._interrupted

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._interrupted = False
            cls._active_resources.clear()

    @classmethod
    def check_interrupted(cls) -> None:
        if cls.is_interrupted():
            raise KeyboardInterrupt("Operation cancelled by user.")


def interruptible_sleep(duration: float) -> None:
    """Sleep for duration while checking for interruption every 50ms."""
    if is_test_environment() or duration <= 0:
        InterruptionState.check_interrupted()
        return
    deadline = time.time() + duration
    while time.time() < deadline:
        InterruptionState.check_interrupted()
        rem = deadline - time.time()
        if rem <= 0:
            break
        time.sleep(min(0.05, rem))


def is_test_environment() -> bool:
    """Check if code is running inside a test framework."""
    return "pytest" in sys.modules or "unittest" in sys.modules


def safe_exit(code: int = 130) -> None:
    """Exit immediately without hanging on background non-daemon threads."""
    sys.stdout.flush()
    sys.stderr.flush()
    if is_test_environment():
        sys.exit(code)
    else:
        os._exit(code)


class KeyboardInterruptWatcher:
    """Background watcher for 'q' / 'Q' key in interactive TTY mode."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._old_termios = None
        self._fd: Optional[int] = None

    def __enter__(self):
        if not self.enabled:
            return self
        InterruptionState.reset()
        self._start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop()
        return False

    def _start(self) -> None:
        try:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                return
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._old_termios = termios.tcgetattr(self._fd)

            # Register atexit restoration to ensure terminal is never corrupted
            atexit.register(self._restore_terminal)

            tty.setcbreak(self._fd)
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._watch_loop,
                daemon=True,
                name="pystdoc-key-watcher",
            )
            self._thread.start()
        except Exception:
            self._restore_terminal()
            self._thread = None

    def _watch_loop(self) -> None:
        import _thread

        while not self._stop_event.is_set():
            if self._fd is None:
                break
            try:
                rlist, _, _ = select.select([self._fd], [], [], 0.1)
                if rlist and not self._stop_event.is_set():
                    ch = os.read(self._fd, 1)
                    if ch in (b"q", b"Q"):
                        InterruptionState.set_interrupted()
                        try:
                            _thread.interrupt_main()
                        except Exception:
                            pass
                        break
                    elif ch == b"\x03":
                        InterruptionState.set_interrupted()
                        try:
                            _thread.interrupt_main()
                        except Exception:
                            pass
                        break
            except Exception:
                break

    def _restore_terminal(self) -> None:
        if self._fd is not None and self._old_termios is not None:
            try:
                import termios
                termios.tcsetattr(
                    self._fd, termios.TCSADRAIN, self._old_termios
                )
            except Exception:
                pass
            self._old_termios = None

    def _stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        self._restore_terminal()
