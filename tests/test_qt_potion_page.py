from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.models.settings import AutoPotionSettings
from maple_star.views_qt.pages.potion import PotionPage


class QtPotionPageTests(unittest.TestCase):
    def test_programmatic_sync_is_blocked_but_user_change_emits(self) -> None:
        ensure_application([])
        changes: list[tuple[str, object]] = []
        page = PotionPage(AutoPotionSettings(), on_change=lambda name, value: changes.append((name, value)))

        page.bindings["hp_enabled"].sync(False)
        self.assertEqual(changes, [])
        page.bindings["hp_enabled"].widget.click()
        self.assertEqual(changes, [("hp_enabled", True)])


if __name__ == "__main__":
    unittest.main()
