"""Interruption handler for graceful cancellation via Ctrl-C or 'q' key."""

import atexit
import os
import select
import sys
import threading
from typing import Any, Optional, Set


class InterruptionState:
    """Thread-safe global state for cancellation and active socket abort."""

    _interrupted: bool = False
    _lock: threading.Lock = threading.Lock()
    _active_resources: Set[Any] = set()
    _interrupt_event: threading.Event = threading.Event()

    @classmethod
    def register_resource(cls, res: Any) -> None:
        """Register an active socket/connection to abort on interrupt."""
        with cls._lock:
            if cls._interrupted:
                cls._abort_resource(res)
                return
            cls._active_resources.add(res)

    @classmethod
    def unregister_resource(cls, res: Any) -> None:
        """Unregister a finished network connection."""
        with cls._lock:
            cls._active_resources.discard(res)

    @classmethod
    def _abort_resource(cls, res: Any) -> None:
        """Forcefully shutdown and close socket or response resource."""
        try:
            sock = getattr(res, "sock", None)
            if sock is None:
                fp = getattr(res, "fp", None)
                if fp is not None:
                    raw = getattr(fp, "raw", None)
                    if raw is not None:
                        sock = getattr(raw, "_sock", None)
            if sock is None and hasattr(res, "shutdown"):
                sock = res

            if sock is not None and hasattr(sock, "shutdown"):
                import socket
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            res.close()
        except Exception:
            pass

    @classmethod
    def set_interrupted(cls) -> None:
        """Set interrupted flag and immediately close all active sockets."""
        with cls._lock:
            cls._interrupted = True
            cls._interrupt_event.set()
            for res in list(cls._active_resources):
                cls._abort_resource(res)
            cls._active_resources.clear()

    @classmethod
    def is_interrupted(cls) -> bool:
        with cls._lock:
            return cls._interrupted

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._interrupted = False
            cls._interrupt_event.clear()
            cls._active_resources.clear()

    @classmethod
    def check_interrupted(cls) -> None:
        if cls.is_interrupted():
            raise KeyboardInterrupt("Operation cancelled by user.")

    @classmethod
    def wait_interrupted(cls, timeout: Optional[float] = None) -> bool:
        """Wait until interrupted or timeout expires, with zero polling."""
        return cls._interrupt_event.wait(timeout=timeout)


def interruptible_sleep(duration: float) -> None:
    """Sleep for duration, waking immediately on interrupt without polling."""
    if is_test_environment() or duration <= 0:
        InterruptionState.check_interrupted()
        return
    interrupted = InterruptionState.wait_interrupted(timeout=duration)
    if interrupted:
        InterruptionState.check_interrupted()


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
        self._opened_file = None
        self._pipe_r: Optional[int] = None
        self._pipe_w: Optional[int] = None

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
            if not sys.stdin.isatty():
                return

            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._old_termios = termios.tcgetattr(self._fd)

            # Register atexit restoration to ensure terminal is never corrupted
            atexit.register(self._restore_terminal)

            tty.setcbreak(self._fd)
            self._stop_event.clear()

            # Create self-pipe to wake select immediately on stop
            self._pipe_r, self._pipe_w = os.pipe()

            self._thread = threading.Thread(
                target=self._watch_loop,
                daemon=True,
                name="pystdoc-key-watcher",
            )
            self._thread.start()
        except Exception:
            self._restore_terminal()
            self._cleanup_pipe()
            self._thread = None

    def _watch_loop(self) -> None:
        import _thread

        while not self._stop_event.is_set():
            if self._fd is None or self._pipe_r is None:
                break
            try:
                # Event-driven select on tty fd and control self-pipe
                rlist, _, _ = select.select([self._fd, self._pipe_r], [], [])
                if self._stop_event.is_set():
                    break
                if self._pipe_r in rlist:
                    break
                if self._fd in rlist:
                    ch = os.read(self._fd, 1)
                    if ch in (b"q", b"Q", b"\x03"):
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
        if self._opened_file is not None:
            try:
                self._opened_file.close()
            except Exception:
                pass
            self._opened_file = None

    def _cleanup_pipe(self) -> None:
        if self._pipe_w is not None:
            try:
                os.close(self._pipe_w)
            except Exception:
                pass
            self._pipe_w = None
        if self._pipe_r is not None:
            try:
                os.close(self._pipe_r)
            except Exception:
                pass
            self._pipe_r = None

    def _stop(self) -> None:
        self._stop_event.set()
        if self._pipe_w is not None:
            try:
                os.write(self._pipe_w, b"\x00")
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        self._cleanup_pipe()
        self._restore_terminal()
