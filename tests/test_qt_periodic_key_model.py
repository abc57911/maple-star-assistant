from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from maple_star.app.application import ensure_application
from maple_star.models.settings import AutoPotionSettings
from maple_star.views_qt.models.periodic_key_model import PeriodicKeyTableModel


class QtPeriodicKeyModelTests(unittest.TestCase):
    def test_model_owns_five_rows_and_emits_schema_field(self) -> None:
        ensure_application([])
        changes: list[tuple[str, object]] = []
        model = PeriodicKeyTableModel(AutoPotionSettings(), on_change=lambda name, value: changes.append((name, value)))

        self.assertEqual(model.rowCount(), 5)
        self.assertTrue(model.setData(model.index(0, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole))
        self.assertEqual(changes, [("minimap_cruise_periodic_key_1_enabled", True)])

    def test_replace_from_settings_resets_rows_without_emitting_changes(self) -> None:
        ensure_application([])
        changes: list[tuple[str, object]] = []
        model = PeriodicKeyTableModel(AutoPotionSettings(), on_change=lambda name, value: changes.append((name, value)))
        settings = AutoPotionSettings()
        settings.minimap_cruise_periodic_key_1_enabled = True
        settings.minimap_cruise_periodic_key_1 = "F8"
        settings.minimap_cruise_periodic_key_1_interval_seconds = 12.5

        model.replace_from_settings(settings)

        self.assertTrue(model.rows[0].enabled)
        self.assertEqual(model.rows[0].key, "F8")
        self.assertEqual(model.rows[0].interval_seconds, 12.5)
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
