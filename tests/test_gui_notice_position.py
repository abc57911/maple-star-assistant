import unittest
import tkinter as tk
from unittest.mock import Mock, patch

from maple_star.constants import MAX_CONSOLE_CHARS, MAX_CONSOLE_LINES
from maple_star.gui import AutoPotionSettingsGui
from maple_star.settings import AutoPotionSettings
from maple_star.views.settings_gui import FlowLayout
from maple_star.views.adaptive_scroll import AdaptiveScrollHost


class ToggleNoticePositionTests(unittest.TestCase):
    def make_gui(self):
        gui = AutoPotionSettingsGui.__new__(AutoPotionSettingsGui)
        gui.root = Mock()
        gui.root.winfo_screenwidth.return_value = 1920
        gui.root.winfo_screenheight.return_value = 1080
        gui.root.winfo_width.return_value = 1240
        gui.root.winfo_height.return_value = 760
        gui.root.geometry.return_value = "1240x760+0+0"
        gui.root.after_idle.return_value = "programmatic-resize"
        gui.console_flush_after_id = None
        gui.console_pending_text = []
        gui.root_was_minimized = False
        gui.restore_repaint_until = 0.0
        gui.restore_repaint_after_id = None
        gui.active_page = "監控"
        gui.compact_experience_mode = False
        gui.page_frames = {}
        gui.auto_fit_pending = True
        gui.user_resized_current_page = False
        gui.programmatic_resize_generation = 0
        gui.programmatic_resize_active = False
        gui.programmatic_resize_target = None
        gui.last_programmatic_resize_target = None
        gui.programmatic_resize_after_id = None
        gui.last_auto_fit_signature = None
        return gui

    def test_adaptive_scroll_height_converts_physical_canvas_bbox_to_logical(self):
        host = AdaptiveScrollHost.__new__(AdaptiveScrollHost)
        host._parent_canvas = Mock()
        host._parent_canvas.bbox.return_value = (0, 0, 940, 628)
        host._reverse_widget_scaling = Mock(return_value=502.4)

        self.assertEqual(host.logical_content_height(), 502)
        host._reverse_widget_scaling.assert_called_once_with(628)

    def test_current_window_logical_size_parses_coordinates_and_fails_closed(self):
        gui = self.make_gui()
        for geometry in ("992x692", "992x692+10+20", "992x692-10-20"):
            with self.subTest(geometry=geometry):
                gui.root.geometry.return_value = geometry
                self.assertEqual(gui._current_window_logical_size(), (992, 692))

        gui.root.geometry.return_value = "invalid"
        self.assertIsNone(gui._current_window_logical_size())

    def test_window_width_change_preserves_logical_height(self):
        gui = self.make_gui()
        gui.root.geometry.return_value = "992x692+0+0"

        gui._set_window_width(752)

        gui.root.geometry.assert_called_with("752x692")

    def test_height_sync_does_not_reapply_physical_125_percent_size(self):
        gui = self.make_gui()
        gui.console_collapsed = False
        gui.controls_frame = Mock()
        page = Mock()
        page.logical_content_height.return_value = 628
        gui.page_frames = {"監控": page}
        gui.root.geometry.return_value = "992x692+0+0"
        gui.root.winfo_width.return_value = 1240
        gui.root.winfo_height.return_value = 865

        with patch.object(gui, "_maximum_logical_client_height", return_value=None):
            gui._sync_full_window_height_to_left_panel()

        setter_calls = [call for call in gui.root.geometry.call_args_list if call.args]
        self.assertEqual(setter_calls, [])

    def test_user_owned_height_is_preserved_when_it_fits_work_area(self):
        gui = self.make_gui()
        gui.console_collapsed = False
        gui.controls_frame = Mock()
        gui.user_resized_current_page = True
        gui.auto_fit_pending = False
        page = Mock()
        page.logical_content_height.return_value = 502
        gui.page_frames = {"監控": page}
        gui.root.geometry.return_value = "752x600+0+0"

        with patch.object(gui, "_maximum_logical_client_height", return_value=640):
            gui._sync_full_window_height_to_left_panel()

        setter_calls = [call for call in gui.root.geometry.call_args_list if call.args]
        self.assertEqual(setter_calls, [])

    def test_user_owned_small_height_enables_overflow_without_auto_fit(self):
        gui = self.make_gui()
        gui.console_collapsed = False
        gui.controls_frame = Mock()
        gui.user_resized_current_page = True
        gui.auto_fit_pending = False
        page = Mock()
        page.logical_content_height.return_value = 502
        gui.page_frames = {"監控": page}
        gui.root.geometry.return_value = "752x400+0+0"

        with patch.object(gui, "_maximum_logical_client_height", return_value=640):
            gui._sync_full_window_height_to_left_panel()

        page.set_viewport_height.assert_called_once_with(336)
        page.set_overflow_enabled.assert_called_once_with(True)
        setter_calls = [call for call in gui.root.geometry.call_args_list if call.args]
        self.assertEqual(setter_calls, [])

    def test_user_owned_height_only_clamps_to_work_area(self):
        gui = self.make_gui()
        gui.console_collapsed = False
        gui.controls_frame = Mock()
        gui.user_resized_current_page = True
        gui.auto_fit_pending = False
        page = Mock()
        page.logical_content_height.return_value = 502
        gui.page_frames = {"監控": page}
        gui.root.geometry.return_value = "752x700+0+0"

        with patch.object(gui, "_maximum_logical_client_height", return_value=640):
            gui._sync_full_window_height_to_left_panel()

        gui.root.geometry.assert_called_with("752x640")

    def test_checkbox_label_click_toggles_variable_and_applies_settings(self):
        class FakeBooleanVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        gui = self.make_gui()
        gui.apply_to_settings = Mock()
        variable = FakeBooleanVar(False)

        result = gui._toggle_checkbox_label(variable)

        self.assertEqual(result, "break")
        self.assertTrue(variable.get())
        gui.apply_to_settings.assert_called_once()

    def test_runtime_toggle_checkbox_calls_handler_and_reverts_on_failure(self):
        class FakeBooleanVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        gui = self.make_gui()
        gui.auto_drink_enabled = FakeBooleanVar(False)
        gui.pickup_enabled = FakeBooleanVar(True)
        gui.auto_drink_toggle_handler = Mock(return_value=True)
        gui.pickup_toggle_handler = Mock(return_value=False)

        gui._toggle_auto_drink_enabled_from_checkbox()
        gui._toggle_pickup_enabled_from_checkbox()

        gui.auto_drink_toggle_handler.assert_called_once_with(False)
        gui.pickup_toggle_handler.assert_called_once_with(True)
        self.assertFalse(gui.auto_drink_enabled.get())
        self.assertFalse(gui.pickup_enabled.get())

    def test_apply_to_settings_preserves_updated_combo_jump_intervals(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        gui = self.make_gui()
        gui.settings = AutoPotionSettings()
        gui.hp_threshold = FakeVar(50)
        gui.mp_threshold = FakeVar(30)
        gui.hp_threshold_text = FakeVar("50")
        gui.mp_threshold_text = FakeVar("30")
        gui.hp_enabled = FakeVar(False)
        gui.mp_enabled = FakeVar(False)
        gui.rb_enabled = FakeVar(True)
        gui.lb_enabled = FakeVar(True)
        gui.hp_key = FakeVar("A")
        gui.mp_key = FakeVar("B")
        gui.hp_cooldown = FakeVar("0.5")
        gui.mp_cooldown = FakeVar("0.5")
        gui.hp_continuous_enabled = FakeVar(False)
        gui.mp_continuous_enabled = FakeVar(False)
        gui.hp_continuous_stop_margin = FakeVar("4")
        gui.mp_continuous_stop_margin = FakeVar("6")
        gui.rb_jump_key = FakeVar("X")
        gui.rb_skill_key = FakeVar("C")
        gui.rb_attack_key = FakeVar("A")
        gui.rb_attack_start_delay = FakeVar("0.35")
        gui.rb_attack_hold = FakeVar("1.25")
        gui.rb_controller_button = FakeVar("RB")
        gui.rb_skill_delay = FakeVar("0.05")
        gui.rb_jump_interval = FakeVar("0.01")
        gui.lb_jump_key = FakeVar("X")
        gui.lb_skill_key = FakeVar("C")
        gui.lb_attack_key = FakeVar("B")
        gui.lb_attack_start_delay = FakeVar("0.65")
        gui.lb_attack_hold = FakeVar("0.75")
        gui.lb_controller_button = FakeVar("LB")
        gui.lb_skill_delay = FakeVar("0.2")
        gui.lb_jump_interval = FakeVar("0.88")
        gui.combo_a_script = FakeVar("循環跳躍技能")
        gui.combo_b_script = FakeVar("單次跳躍技能")
        gui.exp_efficiency_enabled = FakeVar(False)
        gui.toggle_hotkey = FakeVar(gui.settings.toggle_hotkey)
        gui.emergency_stop_hotkey = FakeVar(gui.settings.emergency_stop_hotkey)
        gui.experience_toggle_hotkey = FakeVar(gui.settings.experience_toggle_hotkey)
        gui.experience_reset_hotkey = FakeVar(gui.settings.experience_reset_hotkey)
        gui.character_stat_hotkey = FakeVar(gui.settings.character_stat_hotkey)
        gui.pickup_toggle_hotkey = FakeVar(gui.settings.pickup_toggle_hotkey or "")
        gui.pickup_key = FakeVar(gui.settings.pickup_key or "")
        gui.console_collapsed = False
        gui.combo_group_collapsed = False
        gui.compact_experience_mode = False
        gui.window_topmost = False

        gui.apply_to_settings()

        self.assertEqual(gui.settings.rb_jump_interval_seconds, 0.01)
        self.assertEqual(gui.settings.combo_slots["A"]["jump_interval_seconds"], 0.01)
        self.assertEqual(gui.settings.combo_slots["A"]["attack_key"], "A")
        self.assertEqual(gui.settings.combo_slots["A"]["attack_start_delay_seconds"], 0.35)
        self.assertEqual(gui.settings.combo_slots["A"]["attack_hold_seconds"], 1.25)
        self.assertEqual(gui.settings.combo_slots["B"]["jump_interval_seconds"], 0.88)
        self.assertEqual(gui.settings.combo_slots["B"]["attack_key"], "B")
        self.assertEqual(gui.settings.combo_slots["B"]["attack_start_delay_seconds"], 0.65)
        self.assertEqual(gui.settings.combo_slots["B"]["attack_hold_seconds"], 0.75)
        self.assertEqual(gui.settings.hp_continuous_stop_margin_percent, 4.0)
        self.assertEqual(gui.settings.mp_continuous_stop_margin_percent, 6.0)

    def test_set_potion_enabled_syncs_checkbox_vars_and_settings(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        gui = self.make_gui()
        gui.settings = AutoPotionSettings(hp_enabled=True, mp_enabled=False)
        gui.hp_enabled = FakeVar(True)
        gui.mp_enabled = FakeVar(False)

        gui.set_potion_enabled(False, True)

        self.assertFalse(gui.hp_enabled.get())
        self.assertTrue(gui.mp_enabled.get())
        self.assertFalse(gui.settings.hp_enabled)
        self.assertTrue(gui.settings.mp_enabled)

        gui.set_potion_enabled(True, False, update_settings=False)

        self.assertTrue(gui.hp_enabled.get())
        self.assertFalse(gui.mp_enabled.get())
        self.assertFalse(gui.settings.hp_enabled)
        self.assertTrue(gui.settings.mp_enabled)
        self.assertEqual(gui.potion_enabled_ui_only_snapshot, (False, True, True, False))

    def test_apply_to_settings_preserves_ui_only_potion_toggle_state(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        gui = self.make_gui()
        gui.settings = AutoPotionSettings(hp_enabled=True, mp_enabled=False)
        gui.hp_threshold = FakeVar(75)
        gui.mp_threshold = FakeVar(15)
        gui.hp_threshold_text = FakeVar("75")
        gui.mp_threshold_text = FakeVar("15")
        gui.hp_enabled = FakeVar(True)
        gui.mp_enabled = FakeVar(False)
        gui.rb_enabled = FakeVar(False)
        gui.lb_enabled = FakeVar(False)
        gui.hp_key = FakeVar("9")
        gui.mp_key = FakeVar("0")
        gui.hp_cooldown = FakeVar("0.1")
        gui.mp_cooldown = FakeVar("0.3")
        gui.hp_continuous_enabled = FakeVar(False)
        gui.mp_continuous_enabled = FakeVar(False)
        gui.hp_continuous_stop_margin = FakeVar("5")
        gui.mp_continuous_stop_margin = FakeVar("5")
        gui.rb_jump_key = FakeVar("X")
        gui.rb_skill_key = FakeVar("C")
        gui.rb_attack_key = FakeVar("C")
        gui.rb_attack_start_delay = FakeVar("0.02")
        gui.rb_attack_hold = FakeVar("0.55")
        gui.rb_controller_button = FakeVar("Y")
        gui.rb_skill_delay = FakeVar("0.01")
        gui.rb_jump_interval = FakeVar("0.9")
        gui.lb_jump_key = FakeVar("X")
        gui.lb_skill_key = FakeVar("C")
        gui.lb_attack_key = FakeVar("C")
        gui.lb_attack_start_delay = FakeVar("0")
        gui.lb_attack_hold = FakeVar("1")
        gui.lb_controller_button = FakeVar("LB")
        gui.lb_skill_delay = FakeVar("0.12")
        gui.lb_jump_interval = FakeVar("0.66")
        gui.combo_a_script = FakeVar("按住跳攻")
        gui.combo_b_script = FakeVar("單次跳躍技能")
        gui.exp_efficiency_enabled = FakeVar(False)
        gui.toggle_hotkey = FakeVar("F3")
        gui.emergency_stop_hotkey = FakeVar("Pause")
        gui.experience_toggle_hotkey = FakeVar("F1")
        gui.experience_reset_hotkey = FakeVar("F2")
        gui.character_stat_hotkey = FakeVar("J")
        gui.pickup_toggle_hotkey = FakeVar("F4")
        gui.pickup_key = FakeVar("Z")
        gui.console_collapsed = False
        gui.combo_group_collapsed = True
        gui.compact_experience_mode = False
        gui.window_topmost = False

        gui.set_potion_enabled(False, False, update_settings=False)
        gui.apply_to_settings()

        self.assertTrue(gui.settings.hp_enabled)
        self.assertFalse(gui.settings.mp_enabled)

        gui.hp_enabled.set(False)
        gui.mp_enabled.set(True)
        gui.apply_to_settings()

        self.assertFalse(gui.settings.hp_enabled)
        self.assertTrue(gui.settings.mp_enabled)

    def test_bind_checkbox_label_registers_click_handler(self):
        gui = self.make_gui()
        label = Mock()
        variable = Mock()

        result = gui._bind_checkbox_label(label, variable)

        self.assertIs(result, label)
        label.configure.assert_called_once_with(cursor="hand2")
        label.bind.assert_called_once()
        self.assertEqual(label.bind.call_args.args[0], "<Button-1>")

    def test_saved_position_rejects_windows_minimized_sentinel(self):
        gui = self.make_gui()
        gui._virtual_screen_bounds = Mock(return_value=(0, 0, 1920, 1080))

        self.assertIsNone(gui._saved_position(-32000, -32000))

    def test_saved_position_accepts_visible_position(self):
        gui = self.make_gui()
        gui._virtual_screen_bounds = Mock(return_value=(0, 0, 1920, 1080))

        self.assertEqual(gui._saved_position(120, 80), (120, 80))

    def test_minimized_root_does_not_start_window_interaction_pause(self):
        gui = self.make_gui()
        gui.root.state.return_value = "iconic"
        gui.window_interaction_pause_until = 99.0
        gui.last_root_size = (1240, 760)
        gui.suppress_resize_suspend_until = 0.0
        gui._suspend_layout_for_resize = Mock()
        gui._schedule_window_interaction_finish = Mock()
        event = Mock(widget=gui.root, width=1, height=1)

        gui._on_root_configure(event)

        self.assertEqual(gui.window_interaction_pause_until, 0.0)
        self.assertEqual(gui.last_root_size, (1240, 760))
        self.assertTrue(gui.root_was_minimized)
        gui._suspend_layout_for_resize.assert_not_called()
        gui._schedule_window_interaction_finish.assert_not_called()

    def test_restore_from_minimized_does_not_suspend_layout_for_resize(self):
        gui = self.make_gui()
        gui.root.state.return_value = "normal"
        gui.window_interaction_pause_until = 99.0
        gui.last_root_size = (1240, 760)
        gui.root_was_minimized = True
        gui.resize_layout_suspended = False
        gui.console_collapsed = False
        gui.console_resize_frozen = False
        gui.console_container = Mock()
        gui.suppress_resize_suspend_until = 0.0
        gui.root.after_idle.return_value = "restore-repaint"
        gui._suspend_layout_for_resize = Mock()
        gui._restore_layout_after_resize = Mock()
        gui._unfreeze_console_resize = Mock()
        gui._schedule_console_height_sync = Mock()
        gui._schedule_window_interaction_finish = Mock()
        event = Mock(widget=gui.root, width=1200, height=760)

        with patch("maple_star.views.settings_gui.time.monotonic", return_value=100.0):
            gui._on_root_configure(event)

        self.assertEqual(gui.last_root_size, (1200, 760))
        self.assertFalse(gui.root_was_minimized)
        self.assertAlmostEqual(gui.window_interaction_pause_until, 100.22)
        self.assertAlmostEqual(gui.restore_repaint_until, 100.22)
        self.assertAlmostEqual(gui.suppress_resize_suspend_until, 100.22)
        self.assertEqual(gui.restore_repaint_after_id, "restore-repaint")
        gui._suspend_layout_for_resize.assert_not_called()
        gui._schedule_window_interaction_finish.assert_not_called()
        gui._restore_layout_after_resize.assert_called_once()
        gui._unfreeze_console_resize.assert_not_called()
        gui._schedule_console_height_sync.assert_not_called()
        gui.root.after_idle.assert_called_once_with(gui._finish_restore_repaint)

        gui._finish_restore_repaint()

        gui.root.update_idletasks.assert_called()
        gui._unfreeze_console_resize.assert_called_once()
        gui._schedule_console_height_sync.assert_called_once()

    def test_window_interaction_inactive_while_root_is_minimized(self):
        gui = self.make_gui()
        gui.root.state.return_value = "iconic"
        gui.window_interaction_pause_until = 999999.0

        self.assertFalse(gui.is_window_interaction_active())

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

    def test_auxiliary_window_is_hidden_from_shell_before_show(self):
        gui = self.make_gui()
        window = Mock()

        with patch("maple_star.views.settings_gui.ctk.CTkToplevel", return_value=window):
            created = gui._create_auxiliary_window(fg_color="#123456", overrideredirect=True)

        self.assertIs(created, window)
        window.withdraw.assert_called_once()
        window.transient.assert_called_once_with(gui.root)
        window.overrideredirect.assert_called_once_with(True)
        window.attributes.assert_any_call("-toolwindow", True)
        window.attributes.assert_any_call("-topmost", True)

    def test_show_toggle_notice_applies_background_style_before_deiconify(self):
        gui = self.make_gui()
        gui.closed = False
        gui.last_gui_error_at = -999.0
        gui.toggle_notice_window = None
        gui.toggle_notice_after_id = None
        gui._foreground_client_rect = Mock(return_value=None)
        gui._destroy_toggle_notice = Mock()
        notice = Mock()
        notice.winfo_width.return_value = 240
        notice.winfo_height.return_value = 60
        events = []
        notice.withdraw.side_effect = lambda: events.append("withdraw")
        notice.update_idletasks.side_effect = lambda: events.append("update")
        notice.deiconify.side_effect = lambda: events.append("deiconify")

        with (
            patch("maple_star.views.settings_gui.ctk.CTkToplevel", return_value=notice),
            patch("maple_star.views.settings_gui.ctk.CTkLabel") as label_cls,
            patch("maple_star.views.settings_gui.apply_background_toolwindow_style") as apply_style,
        ):
            label_cls.return_value.grid = Mock()
            apply_style.side_effect = lambda _window: events.append("style")
            gui.show_toggle_notice("測試")

        notice.withdraw.assert_called_once()
        apply_style.assert_called_once_with(notice)
        notice.deiconify.assert_called_once()
        self.assertLess(events.index("withdraw"), events.index("style"))
        self.assertLess(events.index("style"), events.index("deiconify"))
        notice.geometry.assert_called_once()
        notice.lift.assert_called_once()
        gui.root.after.assert_called_once_with(1300, gui._destroy_toggle_notice)

    def test_show_toggle_notice_reuses_active_notice_for_same_message(self):
        gui = self.make_gui()
        gui.closed = False
        gui.toggle_notice_window = Mock()
        gui.toggle_notice_after_id = "after-1"
        gui.toggle_notice_message = "HP 檢查藥水"
        gui._destroy_toggle_notice = Mock()

        gui.show_toggle_notice("HP 檢查藥水")

        gui.root.after_cancel.assert_called_once_with("after-1")
        gui.root.after.assert_called_once_with(1300, gui._destroy_toggle_notice)
        gui.toggle_notice_window.lift.assert_called_once()
        gui._destroy_toggle_notice.assert_not_called()

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
        page = Mock()
        page.logical_content_height.return_value = 610
        gui.page_frames = {"監控": page}
        gui.root.winfo_width.return_value = 752
        gui.root.winfo_height.return_value = 800
        gui.root.geometry.return_value = "752x800+0+0"

        gui.toggle_combo_group_collapsed()

        gui.root.minsize.assert_called_with(752, 228)
        gui.root.geometry.assert_called_with("752x674")

    def test_legacy_console_collapsed_setting_is_normalized_for_console_page(self):
        gui = self.make_gui()
        gui.settings = Mock()
        gui.compact_experience_mode = False
        gui.console_collapsed = False
        gui.console_resize_frozen = False
        gui.console_container = None
        gui.expanded_window_width = 1240
        gui.controls_frame = Mock()
        page = Mock()
        page.logical_content_height.return_value = 654
        gui.page_frames = {"監控": page}
        gui.content_frame = Mock()
        gui.console_section = Mock()
        gui.root.winfo_width.return_value = 1240
        gui.root.winfo_height.return_value = 835
        gui.root.geometry.return_value = "1240x835+0+0"

        gui.set_console_collapsed(True)

        self.assertFalse(gui.console_collapsed)
        self.assertFalse(gui.settings.console_collapsed)
        gui.root.minsize.assert_called_with(752, 228)
        gui.root.geometry.assert_called_with("1240x718")

    def test_console_height_sync_shrinks_to_left_panel_requested_height(self):
        gui = self.make_gui()
        gui.closed = False
        gui.compact_experience_mode = False
        gui.console_collapsed = False
        gui.console_height_after_id = "pending"
        gui.controls_frame = Mock()
        page = Mock()
        page.logical_content_height.return_value = 520
        gui.page_frames = {"監控": page}
        gui.content_frame = None
        gui.console_section = Mock()
        gui.console_container = Mock()

        gui._sync_console_height_to_left_panel()

        gui.controls_frame.configure.assert_called_once_with(height=520)
        gui.console_section.configure.assert_called_once_with(height=520)
        gui.console_container.configure.assert_called_once_with(width=416, height=466)
        gui.console_container.grid_configure.assert_called_once_with(sticky="nsew")
        gui.root.minsize.assert_called_with(752, 228)
        gui.root.geometry.assert_called_with("1240x584")

    def test_console_height_sync_keeps_left_panel_height_when_left_panel_is_taller(self):
        gui = self.make_gui()
        gui.closed = False
        gui.compact_experience_mode = False
        gui.console_collapsed = False
        gui.console_height_after_id = "pending"
        gui.controls_frame = Mock()
        page = Mock()
        page.logical_content_height.return_value = 820
        gui.page_frames = {"監控": page}
        gui.content_frame = None
        gui.console_section = Mock()
        gui.console_container = Mock()

        gui._sync_console_height_to_left_panel()

        gui.controls_frame.configure.assert_called_once_with(height=820)
        gui.console_section.configure.assert_called_once_with(height=820)
        gui.console_container.configure.assert_called_once_with(width=416, height=766)
        gui.root.minsize.assert_called_with(752, 228)
        gui.root.geometry.assert_called_with("1240x884")

    def test_append_console_trims_old_lines_and_disables_text(self):
        gui = self.make_gui()
        gui.closed = False
        gui.last_gui_error_at = -999.0
        gui.console = Mock()
        gui.console.index.side_effect = [f"{MAX_CONSOLE_LINES + 5}.0", "1.0"]

        gui.append_console("sample\n")
        gui._flush_console_buffer()

        gui.console.insert.assert_called_once_with("end", "sample\n")
        gui.console.delete.assert_called_once_with("1.0", "6.0")
        gui.console.see.assert_called_once_with("end")
        self.assertEqual(gui.console.configure.call_args_list[-1].kwargs, {"state": "disabled"})

    def test_append_console_trims_old_characters_when_line_count_is_low(self):
        gui = self.make_gui()
        gui.closed = False
        gui.last_gui_error_at = -999.0
        gui.console = Mock()
        gui.console.index.side_effect = ["1.0", "1.25"]

        gui.append_console("sample")
        gui._flush_console_buffer()

        gui.console.delete.assert_called_once_with("1.0", "1.25")
        self.assertEqual(gui.console.configure.call_args_list[-1].kwargs, {"state": "disabled"})

    def test_append_console_batches_multiple_writes_before_flush(self):
        gui = self.make_gui()
        gui.closed = False
        gui.last_gui_error_at = -999.0
        gui.console = Mock()
        gui.console.index.side_effect = ["1.0", "1.0"]
        gui.root.after.return_value = "console-flush"
        gui.active_page = "Console"

        gui.append_console("sample")
        gui.append_console("\n")

        gui.root.after.assert_called_once_with(50, gui._flush_console_buffer)
        gui.console.insert.assert_not_called()

        gui._flush_console_buffer()

        gui.console.insert.assert_called_once_with("end", "sample\n")
        self.assertEqual(gui.console_pending_text, [])

    def test_clear_console_removes_text_and_disables_text(self):
        gui = self.make_gui()
        gui.closed = False
        gui.last_gui_error_at = -999.0
        gui.console = Mock()

        gui.clear_console()

        gui.console.delete.assert_called_once_with("1.0", "end")
        self.assertEqual(gui.console.configure.call_args_list[0].kwargs, {"state": "normal"})
        self.assertEqual(gui.console.configure.call_args_list[-1].kwargs, {"state": "disabled"})

    def test_lazy_page_builder_runs_only_on_first_open(self):
        gui = self.make_gui()
        page = Mock()
        gui.page_frames = {"自動喝水": page}
        gui.page_built = {"監控"}
        gui._build_potion_page = Mock()
        gui._build_minimap_page = Mock()
        gui._build_combo_page = Mock()

        gui._ensure_page_built("自動喝水")
        gui._ensure_page_built("自動喝水")

        gui._build_potion_page.assert_called_once_with(page)
        self.assertIn("自動喝水", gui.page_built)

    def test_responsive_two_column_layout_switches_to_single_column(self):
        gui = self.make_gui()
        container = Mock()
        first = Mock()
        second = Mock()
        callbacks = []
        container.bind.side_effect = lambda _event, callback, add=None: callbacks.append(callback)
        container.winfo_width.return_value = 1200

        gui._bind_responsive_two_columns(
            container,
            first,
            second,
            wide_weights=(1, 1),
            wide_uniform="combo",
        )
        callbacks[0]()

        container.columnconfigure.assert_any_call(0, weight=1, uniform="combo")
        container.columnconfigure.assert_any_call(1, weight=1, uniform="combo")
        first.grid_configure.assert_called_with(row=0, column=0, sticky="nsew", padx=(0, 4), pady=0)
        second.grid_configure.assert_called_with(row=0, column=1, sticky="nsew", padx=(4, 0), pady=0)

        container.winfo_width.return_value = 700
        callbacks[0]()

        container.columnconfigure.assert_any_call(0, weight=1, uniform="")
        container.columnconfigure.assert_any_call(1, weight=0, uniform="")
        first.grid_configure.assert_called_with(row=0, column=0, sticky="ew", padx=0, pady=(0, 4))
        second.grid_configure.assert_called_with(row=1, column=0, sticky="ew", padx=0, pady=(4, 0))

    def test_flow_layout_does_not_regrid_unchanged_items(self):
        class FakeWidget(tk.Misc):
            def __init__(self):
                self.grid = Mock()
                self.grid_remove = Mock()

        flow = FlowLayout.__new__(FlowLayout)
        flow.frame = Mock()
        flow.frame.winfo_width.return_value = 300
        flow.gap_x = 8
        flow.gap_y = 4
        widget = FakeWidget()
        flow.items = [{"widget": widget, "min_width": 88, "visible": True}]

        flow.layout()
        flow.layout()

        widget.grid.assert_called_once_with(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))

    def test_hidden_console_keeps_bounded_buffer_without_scheduling_repaint(self):
        gui = self.make_gui()
        gui.closed = False
        gui.console = None
        gui.active_page = "監控"

        gui.append_console("x" * (MAX_CONSOLE_CHARS + 100))

        self.assertEqual(sum(len(part) for part in gui.console_pending_text), MAX_CONSOLE_CHARS)
        gui.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
