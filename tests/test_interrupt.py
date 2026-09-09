"""Tests for user interruption (Ctrl-C / 'q' key) handling."""

import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pystdoc.cli import reportgen_main, docgen_main, designgen_main
from pystdoc.design_engine import run_design_generation
from pystdoc.engine import run_docgen
from pystdoc.interrupt import InterruptionState, KeyboardInterruptWatcher
from pystdoc.report_engine import generate_readme_doc


class TestInterruptionState(unittest.TestCase):
    """Test InterruptionState class methods."""

    def setUp(self):
        InterruptionState.reset()

    def tearDown(self):
        InterruptionState.reset()

    def test_interruption_flag_lifecycle(self):
        self.assertFalse(InterruptionState.is_interrupted())
        InterruptionState.set_interrupted()
        self.assertTrue(InterruptionState.is_interrupted())

        with self.assertRaises(KeyboardInterrupt):
            InterruptionState.check_interrupted()

        InterruptionState.reset()
        self.assertFalse(InterruptionState.is_interrupted())
        # Should not raise after reset
        InterruptionState.check_interrupted()

    def test_register_and_abort_resource(self):
        mock_socket = MagicMock()
        InterruptionState.register_resource(mock_socket)
        # Setting interrupted should immediately close registered resource
        InterruptionState.set_interrupted()
        mock_socket.close.assert_called_once()

        # Registering when already interrupted should close immediately
        mock_socket2 = MagicMock()
        InterruptionState.register_resource(mock_socket2)
        mock_socket2.close.assert_called_once()

        InterruptionState.reset()
        mock_socket3 = MagicMock()
        InterruptionState.register_resource(mock_socket3)
        InterruptionState.unregister_resource(mock_socket3)
        InterruptionState.set_interrupted()
        mock_socket3.close.assert_not_called()

    def test_interruptible_sleep(self):
        from pystdoc.interrupt import interruptible_sleep
        with patch(
            "pystdoc.interrupt.is_test_environment", return_value=False
        ):
            start = time.time()
            interruptible_sleep(0.05)
            self.assertGreaterEqual(time.time() - start, 0.04)

        InterruptionState.set_interrupted()
        with self.assertRaises(KeyboardInterrupt):
            interruptible_sleep(1.0)

    def test_safe_exit_in_tests(self):
        from pystdoc.interrupt import safe_exit
        with self.assertRaises(SystemExit) as cm:
            safe_exit(130)
        self.assertEqual(cm.exception.code, 130)

        # In non-test mode, os._exit is called
        with patch(
            "pystdoc.interrupt.is_test_environment", return_value=False
        ):
            with patch("os._exit") as mock_exit:
                safe_exit(130)
                mock_exit.assert_called_once_with(130)


class TestKeyboardInterruptWatcher(unittest.TestCase):
    """Test KeyboardInterruptWatcher context manager and terminal handling."""

    def setUp(self):
        InterruptionState.reset()

    def tearDown(self):
        InterruptionState.reset()

    def test_non_tty_watcher_does_nothing(self):
        with patch("sys.stdin.isatty", return_value=False):
            with KeyboardInterruptWatcher(enabled=True) as watcher:
                self.assertIsNone(watcher._thread)
                self.assertFalse(InterruptionState.is_interrupted())

    def test_disabled_watcher(self):
        with KeyboardInterruptWatcher(enabled=False) as watcher:
            self.assertIsNone(watcher._thread)

    def test_watcher_detects_q_key(self):
        mock_termios = MagicMock()
        mock_tty = MagicMock()

        # Simulate select returning ready fd, and os.read returning b'q'
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("sys.stdin.fileno", return_value=0),
            patch.dict("sys.modules", {
                "termios": mock_termios, "tty": mock_tty
            }),
            patch("select.select", return_value=([0], [], [])),
            patch("os.read", return_value=b"q"),
            patch("_thread.interrupt_main") as mock_intr,
        ):
            mock_termios.tcgetattr.return_value = ["dummy_attr"]

            with KeyboardInterruptWatcher(enabled=True) as watcher:
                if watcher._thread:
                    watcher._thread.join(timeout=1.0)

            self.assertTrue(InterruptionState.is_interrupted())
            mock_intr.assert_called()

    def test_watcher_detects_ctrl_c_byte(self):
        mock_termios = MagicMock()
        mock_tty = MagicMock()

        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("sys.stdin.fileno", return_value=0),
            patch.dict("sys.modules", {
                "termios": mock_termios, "tty": mock_tty
            }),
            patch("select.select", return_value=([0], [], [])),
            patch("os.read", return_value=b"\x03"),
            patch("_thread.interrupt_main") as mock_intr,
        ):
            mock_termios.tcgetattr.return_value = ["dummy_attr"]

            with KeyboardInterruptWatcher(enabled=True) as watcher:
                if watcher._thread:
                    watcher._thread.join(timeout=1.0)

            self.assertTrue(InterruptionState.is_interrupted())
            mock_intr.assert_called()

    def test_watcher_exception_in_start(self):
        with patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.isatty", return_value=True), \
             patch("sys.stdin.fileno", side_effect=RuntimeError("no fileno")):
            with KeyboardInterruptWatcher(enabled=True) as watcher:
                self.assertIsNone(watcher._thread)


class TestGracefulInterruptionInEngines(unittest.TestCase):
    """Test cancellation in docgen, designgen, reportgen, and CLI."""

    def setUp(self):
        InterruptionState.reset()
        self.test_dir = Path("/tmp/test_pystdoc_interrupt")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        src_dir = self.test_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "sample.c").write_text(
            "int add(int a, int b) { return a + b; }\n"
        )
        docs_dir = self.test_dir / ".pystdoc" / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "sample.c.md").write_text("# sample.c\n")

    def tearDown(self):
        InterruptionState.reset()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_docgen_interrupted(self):
        InterruptionState.set_interrupted()
        ret = run_docgen(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
        )
        self.assertEqual(ret, 130)

    def test_designgen_interrupted(self):
        InterruptionState.set_interrupted()
        ret = run_design_generation(
            target_dir=self.test_dir,
            use_llm=False,
            allow_fallback=True,
        )
        self.assertEqual(ret, 130)

    def test_reportgen_interrupted(self):
        InterruptionState.set_interrupted()
        with self.assertRaises(KeyboardInterrupt):
            generate_readme_doc(
                target_dir=self.test_dir,
                llm_client=None,
                allow_fallback=True,
            )

    def test_cli_reportgen_main_interrupted(self):
        with patch("pystdoc.cli.run_docgen", side_effect=KeyboardInterrupt):
            with self.assertRaises(SystemExit) as cm:
                reportgen_main(
                    ["sync", "--dir", str(self.test_dir), "--no-llm"]
                )
            self.assertEqual(cm.exception.code, 130)

    def test_cli_docgen_main_interrupted(self):
        with patch("pystdoc.cli.run_docgen", side_effect=KeyboardInterrupt):
            with self.assertRaises(SystemExit) as cm:
                docgen_main(["--dir", str(self.test_dir), "--no-llm"])
            self.assertEqual(cm.exception.code, 130)

    def test_cli_designgen_main_interrupted(self):
        with patch(
            "pystdoc.cli.run_design_generation", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(SystemExit) as cm:
                designgen_main(["--dir", str(self.test_dir), "--no-llm"])
            self.assertEqual(cm.exception.code, 130)


if __name__ == "__main__":
    unittest.main()
