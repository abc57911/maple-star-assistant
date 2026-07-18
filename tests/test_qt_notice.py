from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.views_qt.notices import ToggleNotice


class QtNoticeTests(unittest.TestCase):
    def test_notice_reuses_widget_and_has_bounded_timer(self) -> None:
        ensure_application([])
        notice = ToggleNotice()
        notice.show_message("已啟用", duration_ms=100)
        self.assertEqual(notice.text(), "已啟用")
        self.assertTrue(notice._timer.isActive())
        notice.close()


if __name__ == "__main__":
    unittest.main()
