from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from maple_star.app.application import ensure_application
from maple_star.views_qt.main_window import MainWindow


class QtApplicationTests(unittest.TestCase):
    def test_application_and_six_page_shell_close_cleanly(self) -> None:
        app = ensure_application([])
        window = MainWindow()

        self.assertIs(QApplication.instance(), app)
        self.assertEqual(window.page_names, ("監控", "自動喝水", "小地圖巡航", "手把組合", "經驗計算", "診斷"))
        self.assertEqual(window.stack.count(), 6)
        window.close()
        app.processEvents()
        self.assertTrue(window.closed)


if __name__ == "__main__":
    unittest.main()
