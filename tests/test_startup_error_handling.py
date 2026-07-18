from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from maple_star.controllers import gamepad_controller


class StartupErrorHandlingTests(unittest.TestCase):
    def test_production_startup_loads_settings_before_starting_automation(self) -> None:
        shown_messages: list[str] = []

        class FakeApplication:
            def exec(self) -> None:
                return None

        class FakeDiagnostics:
            def append_console_batch(self, messages: list[str]) -> None:
                shown_messages.extend(messages)

        class FakeGui:
            def __init__(self, _settings: object) -> None:
                self.application = FakeApplication()
                self.diagnostics = FakeDiagnostics()

            def set_status(self, _message: str) -> None:
                return None

            def show_page(self, _page_name: str) -> None:
                return None

            def show(self) -> None:
                return None

        application_host = types.ModuleType("maple_star.views_qt.application_host")
        application_host.QtApplicationHost = object
        settings_gui = types.ModuleType("maple_star.views_qt.settings_gui")
        settings_gui.AutoPotionSettingsGui = FakeGui

        with (
            patch.dict(
                sys.modules,
                {
                    "maple_star.views_qt.application_host": application_host,
                    "maple_star.views_qt.settings_gui": settings_gui,
                },
            ),
            patch.dict(os.environ, {"MAPLE_STAR_STARTUP_BENCHMARK_OUTPUT": ""}),
            patch.object(
                gamepad_controller,
                "load_settings",
                side_effect=RuntimeError("settings-load-sentinel"),
            ),
        ):
            gamepad_controller._run_main({})

        self.assertEqual(len(shown_messages), 1)
        self.assertIn("settings-load-sentinel", shown_messages[0])

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
