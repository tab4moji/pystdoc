"""Unit tests for DNotifyWatcher and watch mode in pystdoc."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pystdoc.cli import reportgen_main, run_watch
from pystdoc.watcher import DNotifyWatcher


class TestWatcher(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmp_dir.name)
        self.src_file = self.test_dir / "main.py"
        self.src_file.write_text("def hello(): pass\n", encoding="utf-8")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_watcher_snapshot_and_change_detection(self):
        mock_callback = MagicMock()
        watcher = DNotifyWatcher(
            target_dir=self.test_dir,
            on_change=mock_callback,
            debounce_seconds=0.1,
            poll_interval=0.05,
            use_dnotify=True,
        )
        self.assertFalse(watcher.check_changes())

        # 1. Modify file
        time.sleep(0.01)
        self.src_file.write_text("def hello(): return 42\n", encoding="utf-8")
        self.assertTrue(watcher.check_changes())
        self.assertFalse(watcher.check_changes())

        # 2. Add file
        new_file = self.test_dir / "util.py"
        new_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")
        self.assertTrue(watcher.check_changes())

        # 3. Delete file
        new_file.unlink()
        self.assertTrue(watcher.check_changes())

        # 4. Modify files inside .docgen/ (should be strictly ignored)
        docgen_dir = self.test_dir / ".docgen"
        docgen_dir.mkdir(parents=True, exist_ok=True)
        (docgen_dir / "README.md").write_text("# Autogen", encoding="utf-8")
        (docgen_dir / "files.txt").write_text("main.py\n", encoding="utf-8")
        self.assertFalse(watcher.check_changes())

    def test_watcher_non_blocking_start_and_trigger(self):
        callback_called = []

        def on_change():
            callback_called.append(True)

        watcher = DNotifyWatcher(
            target_dir=self.test_dir,
            on_change=on_change,
            debounce_seconds=0.1,
            poll_interval=0.05,
            use_dnotify=True,
        )
        watcher.start(blocking=False)
        try:
            time.sleep(0.05)
            # Modify file to trigger sync
            self.src_file.write_text("x = 100\n", encoding="utf-8")
            # Wait for debounce
            time.sleep(0.3)
            self.assertGreaterEqual(len(callback_called), 1)
        finally:
            watcher.stop()

    def test_watcher_dnotify_error_handling(self):
        mock_callback = MagicMock()
        with patch("os.open", side_effect=OSError("Permission denied")):
            watcher = DNotifyWatcher(
                target_dir=self.test_dir,
                on_change=mock_callback,
                use_dnotify=True,
            )
            watcher._setup_dnotify()
            self.assertEqual(len(watcher._dir_fds), 0)

        with patch("signal.signal", side_effect=ValueError("Signal error")):
            watcher = DNotifyWatcher(
                target_dir=self.test_dir,
                on_change=mock_callback,
                use_dnotify=True,
            )
            watcher._setup_dnotify()
            self.assertFalse(watcher._sigio_supported)

    def test_run_watch_cli_execution(self):
        with patch("pystdoc.cli.run_docgen", return_value=0) as m_docgen, (
            patch("pystdoc.cli.run_design_generation", return_value=0)
        ) as m_design, patch(
            "pystdoc.cli.generate_readme_doc"
        ) as m_readme, patch(
            "pystdoc.watcher.DNotifyWatcher.start"
        ) as mock_start:

            ret = run_watch(
                target_dir=self.test_dir,
                use_llm=False,
                interval=0.5,
            )
            self.assertEqual(ret, 0)
            m_docgen.assert_called_once()
            m_design.assert_called_once()
            m_readme.assert_called_once()
            mock_start.assert_called_once()

    def test_watcher_error_branches_and_coverage(self):
        # 1. on_change raises exception
        err_called = []

        def failing_callback():
            err_called.append(True)
            raise RuntimeError("Sync failed in watcher")

        watcher = DNotifyWatcher(
            target_dir=self.test_dir,
            on_change=failing_callback,
            debounce_seconds=0.05,
            poll_interval=0.02,
            use_dnotify=False,
        )
        watcher.start(blocking=False)
        try:
            time.sleep(0.02)
            self.src_file.write_text("modified = True\n", encoding="utf-8")
            time.sleep(0.2)
            self.assertTrue(len(err_called) >= 1)
        finally:
            watcher.stop()

        # 2. _close_dnotify exception
        w2 = DNotifyWatcher(self.test_dir, lambda: None)
        w2._dir_fds["dummy"] = 999999
        with patch("os.close", side_effect=OSError("Bad FD")):
            w2._close_dnotify()
        self.assertEqual(len(w2._dir_fds), 0)

        # 3. _get_current_snapshot exception
        w3 = DNotifyWatcher(self.test_dir, lambda: None)
        with patch(
            "pystdoc.watcher.scan_files", side_effect=OSError("Scan fail")
        ):
            snap = w3._get_current_snapshot()
            self.assertEqual(snap, {})

        # 4. _setup_dnotify with use_dnotify=False
        w4 = DNotifyWatcher(self.test_dir, lambda: None, use_dnotify=False)
        w4._setup_dnotify()
        self.assertEqual(len(w4._dir_fds), 0)

        # 5. _setup_dnotify on empty directory
        with tempfile.TemporaryDirectory() as empty_dir:
            w5 = DNotifyWatcher(
                Path(empty_dir), lambda: None, use_dnotify=True
            )
            w5._setup_dnotify()
            self.assertGreaterEqual(len(w5._dir_fds), 1)
            w5._close_dnotify()

    def test_run_watch_cli_full_branches(self):
        # 1. docgen failure branch
        with patch("pystdoc.cli.run_docgen", return_value=1) as m_docgen, (
            patch("pystdoc.cli.run_design_generation")
        ) as m_design, patch(
            "pystdoc.watcher.DNotifyWatcher.start"
        ) as mock_start:

            ret = run_watch(self.test_dir, use_llm=False)
            self.assertEqual(ret, 0)
            m_docgen.assert_called_once()
            m_design.assert_not_called()
            mock_start.assert_called_once()

        # 2. designgen failure branch
        with patch("pystdoc.cli.run_docgen", return_value=0) as m_docgen, (
            patch("pystdoc.cli.run_design_generation", return_value=2)
        ) as m_design, patch(
            "pystdoc.cli.generate_readme_doc"
        ) as m_readme, patch(
            "pystdoc.watcher.DNotifyWatcher.start"
        ) as mock_start:

            ret = run_watch(self.test_dir, use_llm=False)
            self.assertEqual(ret, 0)
            m_docgen.assert_called_once()
            m_design.assert_called_once()
            m_readme.assert_not_called()
            mock_start.assert_called_once()

        # 3. with LLM client available and existing db
        (self.test_dir / ".docgen").mkdir(parents=True, exist_ok=True)
        (self.test_dir / ".docgen" / "index.db").touch()
        mock_client = MagicMock()
        mock_client.check_availability.return_value = True

        with patch("pystdoc.cli.run_docgen", return_value=0), (
            patch("pystdoc.cli.run_design_generation", return_value=0)
        ), patch(
            "pystdoc.cli.LLMClient", return_value=mock_client
        ), patch(
            "pystdoc.cli.generate_readme_doc"
        ) as m_readme, patch(
            "pystdoc.watcher.DNotifyWatcher.start"
        ) as mock_start:

            ret = run_watch(self.test_dir, use_llm=True)
            self.assertEqual(ret, 0)
            m_readme.assert_called_once()
            mock_start.assert_called_once()

    def test_run_watch_cli_subcommand(self):
        with patch("pystdoc.cli.run_watch", return_value=0) as mock_watch:
            test_args = [
                "pystdoc",
                "watch",
                "--dir", str(self.test_dir),
                "--interval", "0.5",
            ]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main()
                self.assertEqual(cm.exception.code, 0)
                mock_watch.assert_called_once()

        with patch("pystdoc.cli.run_watch", return_value=0) as mock_watch:
            test_args = [
                "pystdoc",
                "--dir", str(self.test_dir),
                "--watch",
            ]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as cm:
                    reportgen_main()
                self.assertEqual(cm.exception.code, 0)
                mock_watch.assert_called_once()

    def test_watcher_logging_options(self):
        # 1. Quiet watcher
        w_quiet = DNotifyWatcher(
            target_dir=self.test_dir,
            on_change=lambda: None,
            use_dnotify=False,
            quiet=True,
        )
        with patch("builtins.print") as mock_print:
            w_quiet._log("test message")
            mock_print.assert_not_called()

        # 2. Log to stderr
        w_stderr = DNotifyWatcher(
            target_dir=self.test_dir,
            on_change=lambda: None,
            use_dnotify=False,
            log_to_stderr=True,
        )
        with patch("sys.stderr.write") as mock_write:
            w_stderr._log("test message")
            self.assertTrue(mock_write.called)

    def test_watcher_blocking_keyboard_interrupt(self):
        watcher = DNotifyWatcher(
            target_dir=self.test_dir,
            on_change=lambda: None,
            use_dnotify=False,
        )

        def raise_keyboard_interrupt(secs):
            raise KeyboardInterrupt()

        with patch("time.sleep", side_effect=raise_keyboard_interrupt):
            watcher.start(blocking=True)
            self.assertFalse(watcher._running)


if __name__ == "__main__":
    unittest.main()
