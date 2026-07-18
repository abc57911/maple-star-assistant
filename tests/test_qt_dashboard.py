from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.views_qt.pages.dashboard import DashboardPage


class QtDashboardTests(unittest.TestCase):
    def test_snapshot_updates_only_supplied_values(self) -> None:
        ensure_application([])
        page = DashboardPage()
        page.apply_snapshot({"target": "MSW", "hp_mp": "90 / 80"})
        self.assertEqual(page.values["target"].text(), "MSW")
        self.assertEqual(page.values["hp_mp"].text(), "90 / 80")
        self.assertEqual(page.values["workers"].text(), "--")


if __name__ == "__main__":
    unittest.main()
