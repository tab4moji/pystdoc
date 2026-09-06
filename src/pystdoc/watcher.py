"""Directory and file watcher engine (dnotify & polling) for auto-sync."""

import fcntl
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Tuple

from pystdoc.scanner import scan_files


class DNotifyWatcher:
    """Watches directory for source changes and triggers sync."""

    def __init__(
        self,
        target_dir: Path,
        on_change: Callable[[], None],
        debounce_seconds: float = 1.0,
        poll_interval: float = 0.5,
        use_dnotify: bool = True,
    ):
        self.target_dir = target_dir.resolve()
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds
        self.poll_interval = poll_interval
        self.use_dnotify = use_dnotify

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._dir_fds: Dict[str, int] = {}
        self._file_snapshots: Dict[str, Tuple[int, int]] = (
            self._get_current_snapshot()
        )
        self._last_change_time: float = 0.0
        self._pending_sync: bool = False
        self._lock = threading.Lock()
        self._sigio_supported = False

    def _setup_dnotify(self) -> None:
        """Setup Linux dnotify (fcntl.F_NOTIFY) on watched directories."""
        if not self.use_dnotify or not hasattr(fcntl, "F_NOTIFY"):
            return

        dn_events = (
            getattr(fcntl, "DN_MODIFY", 1)
            | getattr(fcntl, "DN_CREATE", 2)
            | getattr(fcntl, "DN_DELETE", 4)
            | getattr(fcntl, "DN_RENAME", 8)
            | getattr(fcntl, "DN_MULTISHOT", 0x80000000)
        )

        matched_files = scan_files(self.target_dir)
        watched_dirs: Set[Path] = {self.target_dir}
        for rel in matched_files:
            watched_dirs.add((self.target_dir / rel).parent)

        for d in watched_dirs:
            d_str = str(d)
            if d_str not in self._dir_fds and d.exists() and d.is_dir():
                try:
                    fd = os.open(d_str, os.O_RDONLY)
                    fcntl.fcntl(fd, fcntl.F_NOTIFY, dn_events)
                    self._dir_fds[d_str] = fd
                except Exception:
                    pass

        try:
            def _sigio_handler(signum, frame):
                with self._lock:
                    self._last_change_time = time.time()
                    self._pending_sync = True

            signal.signal(signal.SIGIO, _sigio_handler)
            self._sigio_supported = True
        except (ValueError, AttributeError):
            self._sigio_supported = False

    def _close_dnotify(self) -> None:
        """Close opened directory file descriptors."""
        for fd in self._dir_fds.values():
            try:
                os.close(fd)
            except Exception:
                pass
        self._dir_fds.clear()

    def _get_current_snapshot(self) -> Dict[str, Tuple[int, int]]:
        """Get snapshot: rel_path -> (mtime_ns, size)."""
        snapshot: Dict[str, Tuple[int, int]] = {}
        try:
            matched_files = scan_files(self.target_dir)
            for rel in matched_files:
                full = self.target_dir / rel
                if full.exists() and full.is_file():
                    stat = full.stat()
                    snapshot[rel.as_posix()] = (
                        stat.st_mtime_ns,
                        stat.st_size,
                    )
        except Exception:
            pass
        return snapshot

    def check_changes(self) -> bool:
        """Check if source files were added, deleted, or modified."""
        current = self._get_current_snapshot()
        if current != self._file_snapshots:
            self._file_snapshots = current
            return True
        return False

    def start(self, blocking: bool = True) -> None:
        """Start watcher loop."""
        self._file_snapshots = self._get_current_snapshot()
        self._setup_dnotify()
        self._running = True

        cnt = len(self._file_snapshots)
        print(
            f"=== pystdoc Watcher Active (dnotify/mtime) ===\n"
            f"Watching: {self.target_dir} ({cnt} files)\n"
            f"Debounce: {self.debounce_seconds:.1f}s | "
            f"Poll interval: {self.poll_interval:.1f}s\n"
            f"Press Ctrl+C to stop.\n",
            flush=True,
        )

        if blocking:
            self._run_loop()
        else:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop watcher loop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_dnotify()

    def _run_loop(self) -> None:
        """Internal watcher polling and debouncing loop."""
        try:
            while self._running:
                if self.check_changes():
                    with self._lock:
                        self._last_change_time = time.time()
                        self._pending_sync = True

                with self._lock:
                    should_sync = False
                    if (
                        self._pending_sync
                        and (time.time() - self._last_change_time)
                        >= self.debounce_seconds
                    ):
                        self._pending_sync = False
                        should_sync = True

                if should_sync:
                    cur_time = time.strftime('%H:%M:%S')
                    print(
                        f"\n[{cur_time}] "
                        f"Source change detected! Starting auto-sync...",
                        flush=True,
                    )
                    try:
                        self.on_change()
                    except Exception as e:
                        print(
                            f"Error during auto-sync: {e}",
                            file=sys.stderr,
                            flush=True,
                        )
                    print(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"Auto-sync complete. Resuming watch...\n",
                        flush=True,
                    )
                    self._file_snapshots = self._get_current_snapshot()
                    self._setup_dnotify()

                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            self._running = False
        finally:
            self._close_dnotify()
