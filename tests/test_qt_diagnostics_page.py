from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.models.settings import AutoPotionSettings
from maple_star.views_qt.settings_gui import AutoPotionSettingsGui
from maple_star.views_qt.pages.diagnostics import DiagnosticsPage


class QtDiagnosticsPageTests(unittest.TestCase):
    def test_console_has_bounded_blocks(self) -> None:
        ensure_application([])
        page = DiagnosticsPage()
        page.append_console_batch([str(index) for index in range(1100)])
        self.assertLessEqual(page.console.document().blockCount(), 1000)

    def test_backend_diagnostics_replaces_placeholder_metrics(self) -> None:
        ensure_application([])
        gui = AutoPotionSettingsGui(AutoPotionSettings())
        gui.set_backend_diagnostics("guardian:pid=10,inc=1,hb=0.1s")
        self.assertEqual(gui.diagnostics.metrics.text(), "guardian:pid=10,inc=1,hb=0.1s")
        gui.close()


if __name__ == "__main__":
    unittest.main()
