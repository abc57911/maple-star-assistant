from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.views_qt.application_host import QtApplicationHost
from maple_star.views_qt.main_window import MainWindow


class QtApplicationHostTests(unittest.TestCase):
    def test_quit_is_idempotent_and_stops_owned_timer(self) -> None:
        app = ensure_application([])
        window = MainWindow()
        host = QtApplicationHost(app, window, tick=lambda: None, interval_seconds=0.01)
        host._timer.start(10)

        host.request_quit()
        host.request_quit()

        self.assertTrue(host.closing)
        self.assertFalse(host._timer.isActive())
        window.close()


if __name__ == "__main__":
    unittest.main()
