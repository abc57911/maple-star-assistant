from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.models.settings import AutoPotionSettings
from maple_star.views_qt.pages.cruise import CruisePage


class QtCruisePageTests(unittest.TestCase):
    def test_boundary_and_recovery_fields_are_present(self) -> None:
        ensure_application([])
        page = CruisePage(AutoPotionSettings())
        self.assertIn("minimap_cruise_left_x", page.bindings)
        self.assertIn("minimap_cruise_pre_boundary_skill_key", page.bindings)
        self.assertIn("minimap_cruise_stationary_min_forward_pixels", page.bindings)


if __name__ == "__main__":
    unittest.main()
