from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from maple_star.app.application import ensure_application
from maple_star.views_qt.models.combo_model import ComboTableModel


class QtComboPageTests(unittest.TestCase):
    def test_table_model_edits_without_per_cell_widgets(self) -> None:
        ensure_application([])
        changes: list[dict[str, dict[str, object]]] = []
        model = ComboTableModel({"A": {"enabled": False}}, on_change=changes.append)
        index = model.index(0, 1)

        self.assertTrue(model.setData(index, True, Qt.ItemDataRole.EditRole))
        self.assertTrue(changes[-1]["A"]["enabled"])


if __name__ == "__main__":
    unittest.main()
