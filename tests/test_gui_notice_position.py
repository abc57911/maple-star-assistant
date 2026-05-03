import unittest
from unittest.mock import Mock

from maple_star.gui import AutoPotionSettingsGui


class ToggleNoticePositionTests(unittest.TestCase):
    def make_gui(self):
        gui = AutoPotionSettingsGui.__new__(AutoPotionSettingsGui)
        gui.root = Mock()
        gui.root.winfo_screenwidth.return_value = 1920
        gui.root.winfo_screenheight.return_value = 1080
        gui.root.winfo_width.return_value = 1240
        gui.root.winfo_height.return_value = 760
        return gui

    def test_saved_position_rejects_windows_minimized_sentinel(self):
        gui = self.make_gui()
        gui._virtual_screen_bounds = Mock(return_value=(0, 0, 1920, 1080))

        self.assertIsNone(gui._saved_position(-32000, -32000))

    def test_saved_position_accepts_visible_position(self):
        gui = self.make_gui()
        gui._virtual_screen_bounds = Mock(return_value=(0, 0, 1920, 1080))

        self.assertEqual(gui._saved_position(120, 80), (120, 80))

    def test_store_window_position_clears_invisible_position(self):
        gui = self.make_gui()
        gui.settings = Mock()
        gui._virtual_screen_bounds = Mock(return_value=(0, 0, 1920, 1080))

        gui._store_full_panel_window_position((-32000, -32000))

        self.assertIsNone(gui.settings.full_panel_window_x)
        self.assertIsNone(gui.settings.full_panel_window_y)

    def test_toggle_notice_uses_foreground_client_center_area(self):
        gui = self.make_gui()

        position = gui._toggle_notice_position(240, 60, (100, 200, 1700, 1100))

        self.assertEqual(position, (780, 575))

    def test_toggle_notice_falls_back_to_screen_center_area(self):
        gui = self.make_gui()

        position = gui._toggle_notice_position(240, 60, None)

        self.assertEqual(position, (840, 456))

    def test_toggle_notice_position_is_clamped_inside_bounds(self):
        gui = self.make_gui()

        position = gui._toggle_notice_position(240, 80, (0, 0, 200, 120))

        self.assertEqual(position, (16, 16))

    def test_combo_group_collapse_toggles_body_and_title_text(self):
        gui = self.make_gui()
        gui.settings = Mock()
        gui.combo_group_collapsed = False
        gui.combo_group_body = Mock()
        gui.combo_group_title_label = Mock()
        gui.controls_frame = None
        gui.console_container = None
        gui._sync_console_height_to_left_panel = Mock()

        gui.toggle_combo_group_collapsed()

        self.assertTrue(gui.combo_group_collapsed)
        self.assertTrue(gui.settings.combo_group_collapsed)
        gui.combo_group_body.grid_remove.assert_called_once()
        gui.combo_group_title_label.configure.assert_called_with(text="組合設定（已收合）")
        gui._sync_console_height_to_left_panel.assert_called_once()

        gui.toggle_combo_group_collapsed()

        self.assertFalse(gui.combo_group_collapsed)
        self.assertFalse(gui.settings.combo_group_collapsed)
        gui.combo_group_body.grid.assert_called_once()
        gui.combo_group_title_label.configure.assert_called_with(text="組合設定")
        self.assertEqual(gui._sync_console_height_to_left_panel.call_count, 2)

    def test_key_detection_focus_guard_captures_focused_entry_before_class_insert(self):
        gui = self.make_gui()
        gui.key_detection_focus_bindings = []
        gui._capture_keypress = Mock()
        focused_widget = Mock()
        focused_widget.bind.return_value = "focused-bind"
        source_widget = Mock()
        source_widget.bind.return_value = "source-bind"
        gui.root.focus_get.return_value = focused_widget

        gui._install_key_detection_focus_guards(source_widget)

        focused_widget.bind.assert_called_once_with("<KeyPress>", gui._capture_keypress, add="+")
        source_widget.bind.assert_called_once_with("<KeyPress>", gui._capture_keypress, add="+")
        self.assertEqual(
            gui.key_detection_focus_bindings,
            [(focused_widget, "focused-bind"), (source_widget, "source-bind")],
        )

    def test_key_detection_focus_guard_unbinds_when_capture_ends(self):
        gui = self.make_gui()
        focused_widget = Mock()
        source_widget = Mock()
        gui.key_detection_focus_bindings = [
            (focused_widget, "focused-bind"),
            (source_widget, "source-bind"),
        ]

        gui._clear_key_detection_focus_guards()

        focused_widget.unbind.assert_called_once_with("<KeyPress>", "focused-bind")
        source_widget.unbind.assert_called_once_with("<KeyPress>", "source-bind")
        self.assertEqual(gui.key_detection_focus_bindings, [])

    def test_combo_group_collapse_resizes_collapsed_console_window_height(self):
        gui = self.make_gui()
        gui.settings = Mock()
        gui.combo_group_collapsed = False
        gui.combo_group_body = Mock()
        gui.combo_group_title_label = Mock()
        gui.console_collapsed = True
        gui.compact_experience_mode = False
        gui.controls_frame = Mock()
        gui.controls_frame.grid_bbox.return_value = (0, 0, 720, 610)
        gui.controls_frame.winfo_reqheight.return_value = 610
        gui.root.winfo_width.return_value = 752
        gui.root.winfo_height.return_value = 800

        gui.toggle_combo_group_collapsed()

        gui.root.minsize.assert_called_with(752, 634)
        gui.root.geometry.assert_called_with("752x634")

    def test_console_collapse_resizes_window_to_left_panel_height(self):
        gui = self.make_gui()
        gui.settings = Mock()
        gui.compact_experience_mode = False
        gui.console_collapsed = False
        gui.console_resize_frozen = False
        gui.console_container = None
        gui.expanded_window_width = 1240
        gui.controls_frame = Mock()
        gui.controls_frame.grid_bbox.return_value = (0, 0, 720, 654)
        gui.controls_frame.winfo_reqheight.return_value = 654
        gui.content_frame = Mock()
        gui.console_section = Mock()
        gui.console_restore_button = Mock()
        gui.root.winfo_width.return_value = 1240
        gui.root.winfo_height.return_value = 835

        gui.set_console_collapsed(True)

        self.assertTrue(gui.console_collapsed)
        self.assertTrue(gui.settings.console_collapsed)
        gui.console_section.grid_remove.assert_called_once()
        gui.console_restore_button.grid.assert_called_once()
        gui.root.minsize.assert_called_with(752, 678)
        gui.root.geometry.assert_called_with("752x678")

    def test_console_height_sync_shrinks_to_left_panel_requested_height(self):
        gui = self.make_gui()
        gui.closed = False
        gui.compact_experience_mode = False
        gui.console_collapsed = False
        gui.console_height_after_id = "pending"
        gui.controls_frame = Mock()
        gui.controls_frame.winfo_reqheight.return_value = 520
        gui.controls_frame.winfo_height.return_value = 760
        gui.controls_frame.grid_bbox.return_value = (0, 0, 720, 520)
        gui.content_frame = None
        gui.console_section = Mock()
        gui.console_container = Mock()

        gui._sync_console_height_to_left_panel()

        gui.controls_frame.configure.assert_called_once_with(height=520)
        gui.console_section.configure.assert_called_once_with(height=520)
        gui.console_container.configure.assert_called_once_with(width=416, height=466)
        gui.console_container.grid_configure.assert_called_once_with(sticky="nsew")
        gui.root.minsize.assert_called_with(1176, 544)
        gui.root.geometry.assert_called_with("1240x544")

    def test_console_height_sync_keeps_left_panel_height_when_left_panel_is_taller(self):
        gui = self.make_gui()
        gui.closed = False
        gui.compact_experience_mode = False
        gui.console_collapsed = False
        gui.console_height_after_id = "pending"
        gui.controls_frame = Mock()
        gui.controls_frame.winfo_reqheight.return_value = 240
        gui.controls_frame.winfo_height.return_value = 760
        gui.controls_frame.grid_bbox.return_value = (0, 0, 720, 820)
        gui.content_frame = None
        gui.console_section = Mock()
        gui.console_container = Mock()

        gui._sync_console_height_to_left_panel()

        gui.controls_frame.configure.assert_called_once_with(height=820)
        gui.console_section.configure.assert_called_once_with(height=820)
        gui.console_container.configure.assert_called_once_with(width=416, height=766)
        gui.root.minsize.assert_called_with(1176, 844)
        gui.root.geometry.assert_called_with("1240x844")


if __name__ == "__main__":
    unittest.main()
