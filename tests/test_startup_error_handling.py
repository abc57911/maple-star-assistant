from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class StartupErrorHandlingTests(unittest.TestCase):
    def test_logging_import_failure_preserves_original_traceback(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            shutil.copyfile(project_root / "main.pyw", root / "main.pyw")
            package = root / "maple_star"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "debug_logging.py").write_text(
                'raise RuntimeError("debug-logging-import-failed")\n',
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(root)

            result = subprocess.run(
                [sys.executable, str(root / "main.pyw")],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("debug-logging-import-failed", result.stderr)
            startup_error = root / "startup_error.log"
            self.assertTrue(startup_error.exists())
            self.assertIn("debug-logging-import-failed", startup_error.read_text(encoding="utf-8"))
            self.assertNotIn("UnboundLocalError", startup_error.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
