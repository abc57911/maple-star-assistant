import unittest
from unittest.mock import Mock, patch

import numpy as np

from maple_star.controller import AutoPotionController, ExperienceOcrJob
from maple_star.constants import ASYNC_KEY_DOWN_MASK, BAR_CONFIRM_CAPTURE_ATTEMPTS, BAR_TRANSIENT_CAPTURE_ATTEMPTS
from maple_star.experience import ExperienceSnapshot, ExperienceTextReading
from maple_star.settings import AutoPotionSettings


class AutoPotionForegroundGuardTests(unittest.TestCase):
    def make_controller(self, active_sequence):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.settings = AutoPotionSettings(
            hp_enabled=True,
            mp_enabled=True,
            hp_threshold_percent=50.0,
            mp_threshold_percent=50.0,
            hp_key="Delete",
            mp_key="End",
            hp_cooldown_seconds=0.0,
            mp_cooldown_seconds=0.0,
        )
        controller.is_target_window_active = Mock(side_effect=active_sequence)
        controller.gui = Mock()
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = False
        controller.gui.is_key_detection_release_pending.return_value = False
        controller.last_hp_drink_at = -999.0
        controller.last_mp_drink_at = -999.0
        controller.last_unstable_bar_at = -999.0
        controller.last_experience_ocr_error_at = -999.0
        controller.last_experience_ocr_error_reason = ""
        controller.emergency_stop_requested = False
        controller.scripts_enabled = True
        controller.gameplay_hud_active = False
        controller.control_hotkeys_suppressed_until_release = False
        controller.last_action = "啟動"
        controller._log_unstable_bar = Mock()
        controller._play_toggle_beep = Mock()
        controller._capture_bar_percent = Mock(return_value=25.0)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        return controller

    def test_actions_require_scripts_enabled_and_gameplay_hud(self):
        controller = self.make_controller([])

        self.assertFalse(controller.can_run_actions())

        controller.gameplay_hud_active = True
        self.assertTrue(controller.can_run_actions())

        controller.scripts_enabled = False
        self.assertFalse(controller.can_run_actions())

    def test_gameplay_hud_gate_clears_stale_bar_regions_on_fresh_failure(self):
        controller = self.make_controller([])
        del controller._refresh_gameplay_hud_state
        controller.bottom_bar_regions = {
            "hp": (100, 900, 200, 16),
            "mp": (360, 900, 200, 16),
        }
        controller.bottom_bar_track_regions = dict(controller.bottom_bar_regions)
        controller.bottom_bar_client_bounds = (0, 0, 1000, 800)
        controller.bottom_bar_regions_at = 0.0
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((128, 700, 4), dtype=np.uint8)
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 800))
        controller._bar_color_mask = Mock(return_value=np.zeros((128, 700), dtype=bool))
        controller._bar_run_candidates = Mock(return_value=[])
        controller._set_bar_detection_debug = Mock()

        self.assertFalse(controller._refresh_gameplay_hud_state(10.0))

        self.assertFalse(controller.gameplay_hud_active)
        self.assertEqual(controller.bottom_bar_regions, {})
        self.assertEqual(controller.bottom_bar_track_regions, {})
        self.assertEqual(controller.last_hp_drink_at, 10.0)
        self.assertEqual(controller.last_mp_drink_at, 10.0)
        self.assertEqual(controller._set_bar_detection_debug.call_count, 2)

    def test_hp_does_not_tap_if_target_loses_focus_before_send(self):
        controller = self.make_controller([True, False])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        controller.gui.set_status.assert_called_with("等待楓星成為前景視窗")

    def test_hp_retries_initial_transient_failure_before_logging(self):
        controller = self.make_controller([])
        controller._capture_bar_percent = Mock(return_value=80.0)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, None)

        tap_hotkey.assert_not_called()
        controller._log_unstable_bar.assert_not_called()
        controller._capture_bar_percent.assert_called_once_with("hp")
        sleep.assert_not_called()

    def test_hp_logs_unstable_only_after_initial_transient_retries_fail(self):
        controller = self.make_controller([])
        controller._capture_bar_percent = Mock(return_value=None)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, None)

        tap_hotkey.assert_not_called()
        controller._log_unstable_bar.assert_called_once_with(100.0, "HP")
        self.assertEqual(controller._capture_bar_percent.call_count, BAR_TRANSIENT_CAPTURE_ATTEMPTS)
        self.assertEqual(sleep.call_count, BAR_TRANSIENT_CAPTURE_ATTEMPTS - 1)

    def test_hp_does_not_tap_if_gameplay_hud_disappears_before_send(self):
        controller = self.make_controller([True])
        controller._refresh_gameplay_hud_state.return_value = False

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        controller.gui.set_status.assert_called_with("未偵測到遊戲 HUD，暫停輔助功能")

    def test_hp_confirm_capture_retries_transient_failure_before_tapping(self):
        controller = self.make_controller([True, True])
        controller._capture_bar_percent = Mock(side_effect=[None, 25.0])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        self.assertEqual(controller._capture_bar_percent.call_count, 2)
        sleep.assert_called_once()
        controller._log_unstable_bar.assert_not_called()

    def test_hp_confirm_capture_logs_unstable_after_retries_fail(self):
        controller = self.make_controller([True])
        controller._capture_bar_percent = Mock(return_value=None)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller._capture_bar_percent.call_count, BAR_CONFIRM_CAPTURE_ATTEMPTS + 1)
        self.assertEqual(sleep.call_count, BAR_CONFIRM_CAPTURE_ATTEMPTS - 1)
        controller._log_unstable_bar.assert_called_once_with(100.0, "HP")

    def test_hp_confirm_capture_uses_matching_unchecked_fallback(self):
        controller = self.make_controller([True, True])
        controller._capture_bar_percent = Mock(
            side_effect=[None] * BAR_CONFIRM_CAPTURE_ATTEMPTS + [26.0]
        )

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep"),
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        controller._log_unstable_bar.assert_not_called()

    def test_hp_confirm_capture_rejects_mismatched_unchecked_fallback(self):
        controller = self.make_controller([True])
        controller._capture_bar_percent = Mock(
            side_effect=[None] * BAR_CONFIRM_CAPTURE_ATTEMPTS + [80.0]
        )

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep"),
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        controller._log_unstable_bar.assert_called_once_with(100.0, "HP")

    def test_unstable_bar_log_is_throttled(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.last_unstable_bar_at = -999.0

        with patch("builtins.print") as print_mock:
            controller._log_unstable_bar(100.0, "HP")
            controller._log_unstable_bar(107.0, "HP")
            controller._log_unstable_bar(108.1, "HP")

        self.assertEqual(print_mock.call_count, 2)

    def test_mp_does_not_tap_if_target_loses_focus_after_confirm_capture(self):
        controller = self.make_controller([True, False])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_mp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_mp_drink_at, -999.0)
        controller.gui.set_current_percentages.assert_called_with(None, None)

    def test_emergency_stop_pauses_scripts_and_requests_macro_stop(self):
        controller = self.make_controller([])

        with patch("builtins.print"):
            controller.emergency_stop()

        self.assertFalse(controller.scripts_enabled)
        self.assertTrue(controller.consume_emergency_stop_requested())
        self.assertFalse(controller.consume_emergency_stop_requested())
        self.assertEqual(controller.last_action, "Pause 硬停止")
        controller.gui.set_status.assert_called_with("Pause 硬停止：所有腳本已暫停")

    def test_control_hotkeys_are_ignored_while_key_capture_is_active(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = True
        controller.toggle_hotkey_was_down = True
        controller.emergency_stop_hotkey_was_down = True
        controller.experience_toggle_hotkey_was_down = True
        controller._discard_control_hotkey_messages = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()

        controller.poll_control_hotkeys()

        controller._discard_control_hotkey_messages.assert_called_once()
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()
        self.assertFalse(controller.toggle_hotkey_was_down)
        self.assertFalse(controller.emergency_stop_hotkey_was_down)
        self.assertFalse(controller.experience_toggle_hotkey_was_down)

    def test_control_hotkeys_are_ignored_once_after_key_capture_finishes(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = True
        controller._discard_control_hotkey_messages = Mock()
        controller._sync_control_hotkey_down_states = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()

        controller.poll_control_hotkeys()

        controller._discard_control_hotkey_messages.assert_called_once()
        controller._sync_control_hotkey_down_states.assert_called_once()
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()

    def test_control_hotkeys_stay_ignored_until_captured_key_is_released(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.side_effect = [True, False, False]
        controller.registered_toggle_hotkey_vk = 0x7A
        controller.registered_emergency_stop_hotkey_vk = 0x13
        controller.registered_experience_toggle_hotkey_vk = 0x79
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller.experience_toggle_hotkey_was_down = False
        controller._discard_control_hotkey_messages = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()

        with patch("maple_star.controller.user32.GetAsyncKeyState", return_value=ASYNC_KEY_DOWN_MASK):
            controller.poll_control_hotkeys()
            controller.poll_control_hotkeys()

        self.assertTrue(controller.control_hotkeys_suppressed_until_release)
        self.assertTrue(controller.toggle_hotkey_was_down)
        self.assertTrue(controller.experience_toggle_hotkey_was_down)
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()

        with patch("maple_star.controller.user32.GetAsyncKeyState", return_value=0):
            controller.poll_control_hotkeys()

        self.assertFalse(controller.control_hotkeys_suppressed_until_release)
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()

    def test_experience_hotkey_toggles_exp_efficiency(self):
        controller = self.make_controller([])
        controller.registered_toggle_hotkey_vk = 0x7A
        controller.registered_emergency_stop_hotkey_vk = 0x13
        controller.registered_experience_toggle_hotkey_vk = 0x79
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller.experience_toggle_hotkey_was_down = False
        controller.last_experience_toggle_hotkey_at = -999.0
        controller._try_toggle_scripts_enabled = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_experience_efficiency = Mock()

        def key_state(vk_code):
            return ASYNC_KEY_DOWN_MASK if vk_code == 0x79 else 0

        with patch("maple_star.controller.user32.GetAsyncKeyState", side_effect=key_state):
            controller.poll_control_hotkeys()

        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_called_once()

    def test_toggle_experience_efficiency_preserves_statistics_when_disabling(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.next_experience_capture_at = 999.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2)
        controller._stop_experience_ocr_job = Mock()

        with patch("builtins.print"):
            controller.toggle_experience_efficiency()

        controller.gui.set_exp_efficiency_enabled.assert_called_once_with(False)
        controller._stop_experience_ocr_job.assert_called_once()
        controller.gui.set_experience_snapshot.assert_called_once()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "已停用，保留統計")
        self.assertEqual(controller.last_action, "F10 經驗統計停用")

    def test_experience_ocr_uses_ui_percent_from_reading(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=132553,
                    percent=18.36,
                    text="132553[18.36%]",
                    confidence=0.98,
                    success=True,
                )

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=DoneFuture())
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.add_reading.return_value = True
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1)

        with patch("builtins.print") as print_mock:
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        controller.experience_tracker.add_reading.assert_called_once_with(8.0, 132553, 18.36)
        controller.gui.set_experience_snapshot.assert_called_once()
        print_mock.assert_not_called()

    def test_experience_ocr_failure_keeps_business_status_and_logs_raw_text(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    text="1325531836",
                    confidence=0.91,
                    reason="EXP 百分比解析失敗",
                )

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=DoneFuture())
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        with patch("builtins.print") as print_mock:
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "統計中")
        printed = "\n".join(call.args[0] for call in print_mock.call_args_list)
        self.assertIn("1325531836", printed)
        self.assertIn("經驗效率 OCR 錯誤", printed)

    def test_experience_rejected_ocr_sample_logs_raw_text_and_values(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=288900,
                    percent=27.08,
                    text="288900[27.08%]",
                    confidence=0.98,
                    success=True,
                    reason="OK",
                )

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=DoneFuture())
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.add_reading.return_value = False
        controller.experience_tracker.last_status = "樣本拒絕：EXP 跳動與百分比不一致"
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        with patch("builtins.print") as print_mock:
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        printed = "\n".join(call.args[0] for call in print_mock.call_args_list)
        self.assertIn("經驗效率 異常樣本拒絕", printed)
        self.assertIn("288900[27.08%]", printed)
        self.assertIn("exp=288,900", printed)
        self.assertIn("percent=27.08%", printed)

    def test_missing_experience_region_preserves_last_statistics(self):
        controller = self.make_controller([])
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller._experience_text_region = Mock(return_value=None)
        preserved = ExperienceSnapshot(
            current_exp=718035,
            current_percent=58.37,
            xp_per_5m=84965,
            xp_per_10m=169929,
            xp_per_hour=1019576,
            eta_seconds=1808,
            sample_count=3,
            status="統計中",
        )
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = preserved

        controller._update_experience_efficiency(12.0)

        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.current_exp, 718035)
        self.assertEqual(snapshot.xp_per_5m, 84965)
        self.assertEqual(snapshot.xp_per_10m, 169929)
        self.assertEqual(snapshot.xp_per_hour, 1019576)
        self.assertEqual(snapshot.status, "找不到 EXP 區域，保留統計")
        self.assertGreater(controller.next_experience_capture_at, 12.0)

    def test_experience_text_region_crops_to_right_side_text_band(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (486, 1025, 253, 28),
            "mp": (795, 1025, 253, 28),
        }
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1920, 1080))

        region = controller._experience_text_region()

        self.assertIsNotNone(region)
        assert region is not None
        left, top, width, height = region
        self.assertGreater(left, 486)
        self.assertGreaterEqual(top, 1053)
        self.assertLess(width, 1048 - 486)
        self.assertGreaterEqual(height, 14)

    def test_bottom_bar_pair_rejects_right_side_shortcut_colors(self):
        controller = self.make_controller([])

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(761, 100, 134), (179, 118, 220)],
            mp_candidates=[(906, 100, 134), (488, 118, 220)],
            hp_mask=None,
            mp_mask=None,
            search_left=307,
            search_top=900,
            search_width=1344,
            search_height=180,
            client_width=1920,
            client_height=1080,
        )

        self.assertLess(regions["hp"][0], 700)
        self.assertLess(regions["mp"][0], 1000)


if __name__ == "__main__":
    unittest.main()
