from __future__ import annotations

import unittest

from maple_star.models.settings import GLOBAL_SETTING_KEYS, PROFILE_SETTING_KEYS
from maple_star.views_qt.pages.combo import COMBO_FIELDS
from maple_star.views_qt.pages.cruise import CRUISE_FIELDS
from maple_star.views_qt.pages.dashboard import DASHBOARD_FIELDS
from maple_star.views_qt.pages.diagnostics import DIAGNOSTIC_FIELDS
from maple_star.views_qt.pages.potion import POTION_FIELDS


class QtFunctionParityTests(unittest.TestCase):
    def test_every_settings_field_has_a_qt_owner(self) -> None:
        owned = set(DASHBOARD_FIELDS) | set(POTION_FIELDS) | set(CRUISE_FIELDS) | set(COMBO_FIELDS) | set(DIAGNOSTIC_FIELDS) | {"combo_slots"}
        expected = set(GLOBAL_SETTING_KEYS) | set(PROFILE_SETTING_KEYS)

        self.assertEqual(owned, expected)


if __name__ == "__main__":
    unittest.main()
