"""Unit test for PEP8 compliance using flake8 / pycodestyle."""

import shutil
import subprocess
import unittest
from pathlib import Path


class TestPEP8(unittest.TestCase):
    """Ensure all python source files adhere to PEP8 guidelines."""

    @classmethod
    def setUpClass(cls):
        cls.pystdoc_dir = Path(__file__).resolve().parent.parent
        cls.src_dir = cls.pystdoc_dir / "src"
        cls.tests_dir = cls.pystdoc_dir / "tests"

        cls.linter_cmd = None
        if shutil.which("flake8"):
            cls.linter_cmd = ["flake8"]
        elif shutil.which("pycodestyle"):
            cls.linter_cmd = ["pycodestyle"]
        else:
            for candidate in (
                Path.home() / ".local" / "bin" / "flake8",
                Path.home() / ".local" / "bin" / "pycodestyle",
                Path("/usr/local/bin/flake8"),
                Path("/usr/bin/flake8"),
            ):
                if candidate.exists() and candidate.is_file():
                    cls.linter_cmd = [str(candidate)]
                    break

    def _run_linter(self, target_dir: Path):
        if not self.linter_cmd:
            self.skipTest(
                "Neither flake8 nor pycodestyle found in environment."
            )

        cmd = self.linter_cmd + [str(target_dir)]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.pystdoc_dir),
        )
        self.assertEqual(
            result.returncode,
            0,
            f"PEP8 violations detected in {target_dir}:\n{result.stdout}",
        )

    def test_src_pep8_compliance(self):
        """Verify all files under src/ pass PEP8 compliance."""
        self._run_linter(self.src_dir)

    def test_tests_pep8_compliance(self):
        """Verify all test files under tests/ pass PEP8 compliance."""
        self._run_linter(self.tests_dir)


if __name__ == "__main__":
    unittest.main()
