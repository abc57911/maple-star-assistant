from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLineEdit, QTableView

from maple_star.app.application import ensure_application
from maple_star.models.settings import AutoPotionSettings, GLOBAL_SETTING_KEYS, PROFILE_SETTING_KEYS
from maple_star.views_qt.components import PAGE_BREAKPOINT, SettingsGrid, SwitchControl
from maple_star.views_qt.bindings import bind_widget
from maple_star.views_qt.delegates import SwitchDelegate
from maple_star.views_qt.labels import COMBO_COLUMN_LABELS, FIELD_TEXT, SCRIPT_LABELS
from maple_star.views_qt.main_window import MainWindow, WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE
from maple_star.views_qt.models.periodic_key_model import PeriodicKeyTableModel
from maple_star.views_qt.settings_gui import AutoPotionSettingsGui


class QtLocalizationLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = ensure_application([])

    def test_every_form_field_has_traditional_chinese_metadata(self) -> None:
        expected = (set(GLOBAL_SETTING_KEYS) | set(PROFILE_SETTING_KEYS)) - {"combo_slots"}
        self.assertEqual(set(FIELD_TEXT), expected)
        for text in FIELD_TEXT.values():
            self.assertFalse("_" in text.label)
            self.assertTrue(any("\u4e00" <= character <= "\u9fff" for character in text.label))
        self.assertEqual(COMBO_COLUMN_LABELS["script_id"], "執行腳本")
        self.assertEqual(SCRIPT_LABELS["hold_jump_attack_loop"], "按住跳躍攻擊循環")

    def test_all_boolean_form_bindings_use_switch_control(self) -> None:
        settings = AutoPotionSettings()
        window = MainWindow(settings)
        for page in window.pages.values():
            for name, binding in getattr(page, "bindings", {}).items():
                if isinstance(getattr(settings, name), bool):
                    self.assertIsInstance(binding.widget, SwitchControl, name)
        self.assertIsInstance(window.pages["監控"].auto_drink_toggle, SwitchControl)
        self.assertIsInstance(window.pages["監控"].pickup_toggle, SwitchControl)
        window.close()

    def test_switch_supports_keyboard_and_programmatic_signal_blocking(self) -> None:
        switch = SwitchControl()
        changes: list[bool] = []
        binding = bind_widget(switch, changes.append)
        binding.sync(True)
        self.assertEqual(changes, [])
        switch.show()
        switch.setFocus()
        QTest.keyClick(switch, Qt.Key.Key_Space)
        self.assertFalse(switch.isChecked())
        self.assertEqual(changes, [False])

    def test_every_page_changes_columns_at_exact_breakpoint_without_duplicates(self) -> None:
        window = MainWindow(AutoPotionSettings())
        for page in window.pages.values():
            grid = page.findChild(SettingsGrid)
            self.assertIsNotNone(grid)
            card_count = len(grid._cards)
            grid.layout_for_width(PAGE_BREAKPOINT - 1)
            self.assertEqual(grid.column_count, 1)
            self.assertEqual(grid.grid.count(), card_count)
            grid.layout_for_width(PAGE_BREAKPOINT)
            self.assertEqual(grid.column_count, 2)
            self.assertEqual(grid.grid.count(), card_count)
            grid.layout_for_width(PAGE_BREAKPOINT)
            self.assertEqual(grid.grid.count(), card_count)
        window.close()

    def test_input_controls_have_bounded_width(self) -> None:
        window = MainWindow(AutoPotionSettings())
        for page in window.pages.values():
            for binding in getattr(page, "bindings", {}).values():
                widget = binding.widget
                if isinstance(widget, QLineEdit):
                    self.assertLessEqual(widget.maximumWidth(), 280)
        window.close()

    def test_runtime_switches_are_not_push_buttons_with_action_text(self) -> None:
        window = MainWindow(AutoPotionSettings())
        dashboard = window.pages["監控"]
        for control in (dashboard.auto_drink_toggle, dashboard.pickup_toggle):
            self.assertIsInstance(control, QAbstractButton)
            self.assertEqual(control.text(), "")
        window.close()

    def test_dashboard_removes_global_control_and_places_auto_drink_after_hotkey(self) -> None:
        window = MainWindow(AutoPotionSettings())
        dashboard = window.pages["監控"]

        self.assertFalse(hasattr(dashboard, "global_toggle"))
        self.assertFalse(hasattr(dashboard, "reset_experience"))
        hotkey_row, _column, _row_span, _column_span = dashboard.hotkey_card.fields.getItemPosition(
            dashboard.hotkey_card.fields.indexOf(dashboard.bindings["toggle_hotkey"].widget)
        )
        toggle_row, _column, _row_span, _column_span = dashboard.hotkey_card.fields.getItemPosition(
            dashboard.hotkey_card.fields.indexOf(dashboard.auto_drink_toggle)
        )
        self.assertEqual(toggle_row, hotkey_row + 1)
        window.close()

    def test_experience_page_owns_all_experience_controls(self) -> None:
        window = MainWindow(AutoPotionSettings())
        experience = window.pages["經驗計算"]
        diagnostics = window.pages["診斷"]

        expected = {
            "experience_toggle_hotkey",
            "experience_reset_hotkey",
            "character_stat_hotkey",
            "exp_efficiency_enabled",
            "compact_experience_mode",
            "window_topmost",
            "full_panel_window_x",
            "full_panel_window_y",
            "compact_experience_window_x",
            "compact_experience_window_y",
        }
        self.assertEqual(set(experience.bindings), expected)
        self.assertTrue(hasattr(experience, "reset_experience"))
        self.assertEqual(set(diagnostics.bindings), set())
        for hidden in ("console_collapsed", "combo_group_collapsed", "minimap_cruise_group_collapsed"):
            self.assertNotIn(hidden, diagnostics.bindings)
        window.close()

    def test_experience_runtime_updates_target_the_experience_page(self) -> None:
        settings = AutoPotionSettings()
        gui = AutoPotionSettingsGui(settings)

        gui.set_exp_efficiency_enabled(True)
        gui.set_experience_snapshot(type("Snapshot", (), {"status": "統計中"})())

        self.assertTrue(settings.exp_efficiency_enabled)
        self.assertTrue(gui.experience.bindings["exp_efficiency_enabled"].widget.isChecked())
        self.assertEqual(gui.experience.status_value.text(), "統計中")
        gui.close()

    def test_bar_debug_updates_do_not_rewrite_preview_status(self) -> None:
        gui = AutoPotionSettingsGui(AutoPotionSettings())
        gui.pages["自動喝水"].preview_status.setText("HP：正常｜MP：正常")

        gui.set_bar_detection_debug("直取｜87%", "直取｜23%")

        self.assertEqual(gui.pages["自動喝水"].preview_status.text(), "HP：正常｜MP：正常")
        gui.close()

    def test_window_interaction_state_tracks_native_move_lifecycle(self) -> None:
        gui = AutoPotionSettingsGui(AutoPotionSettings())

        gui._handle_native_message(WM_ENTERSIZEMOVE)
        self.assertTrue(gui.is_window_interaction_active())
        gui._handle_native_message(WM_EXITSIZEMOVE)
        self.assertFalse(gui.is_window_interaction_active())
        gui.close()

    def test_boolean_table_columns_use_switch_delegate(self) -> None:
        window = MainWindow(AutoPotionSettings())
        cruise = window.pages["小地圖巡航"]
        combo = window.pages["手把組合"]
        self.assertIsInstance(cruise.periodic_table.itemDelegateForColumn(0), SwitchDelegate)
        self.assertIsInstance(combo.table.itemDelegateForColumn(1), SwitchDelegate)
        window.close()

    def test_table_switch_ignores_right_click_and_cell_space(self) -> None:
        changes: list[tuple[str, object]] = []
        model = PeriodicKeyTableModel(AutoPotionSettings(), on_change=lambda name, value: changes.append((name, value)))
        table = QTableView()
        table.setModel(model)
        delegate = SwitchDelegate(table)
        table.setItemDelegateForColumn(0, delegate)
        table.setColumnWidth(0, 140)
        table.resize(320, 180)
        table.show()
        self.app.processEvents()
        index = model.index(0, 0)
        cell = table.visualRect(index)
        switch_rect = delegate.switch_rect(cell)

        QTest.mouseClick(table.viewport(), Qt.MouseButton.RightButton, pos=switch_rect.center())
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell.topLeft() + table.rect().topLeft())
        self.assertEqual(changes, [])
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=switch_rect.center())
        self.assertEqual(changes, [("minimap_cruise_periodic_key_1_enabled", True)])

    def test_runtime_structured_status_values_are_translated(self) -> None:
        gui = AutoPotionSettingsGui(AutoPotionSettings())
        gui.set_runtime_info(
            scripts_enabled=True,
            target_active=True,
            foreground_title="External Game Title",
            macro_status="running",
            held_keys="none",
            last_action="--",
        )
        self.assertEqual(gui.dashboard.values["target"].text(), "作用中｜External Game Title")
        self.assertIn("組合=執行中", gui.dashboard.values["workers"].text())
        self.assertIn("按住=無", gui.dashboard.values["workers"].text())
        gui.close()

    def test_real_viewport_resize_selects_columns_without_page_horizontal_scroll(self) -> None:
        window = MainWindow(AutoPotionSettings())
        page = window.pages["監控"]
        window.resize(860, 620)
        window.show()
        self.app.processEvents()
        self.assertEqual(page.settings_grid.column_count, 1)
        scroll = page.settings_grid.parentWidget().parentWidget()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        window.resize(1180, 760)
        self.app.processEvents()
        self.assertEqual(page.settings_grid.column_count, 2)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        window.close()


if __name__ == "__main__":
    unittest.main()
