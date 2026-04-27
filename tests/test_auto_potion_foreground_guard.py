import unittest
from unittest.mock import Mock, patch

from maple_star.controller import AutoPotionController
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
        controller.last_hp_drink_at = -999.0
        controller.last_mp_drink_at = -999.0
        controller.last_unstable_bar_at = -999.0
        controller.emergency_stop_requested = False
        controller.scripts_enabled = True
        controller.last_action = "啟動"
        controller._log_unstable_bar = Mock()
        controller._play_toggle_beep = Mock()
        controller._capture_bar_percent = Mock(return_value=25.0)
        return controller

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
        self.assertEqual(controller.last_action, "F12 硬停止")
        controller.gui.set_status.assert_called_with("F12 硬停止：所有腳本已暫停")


if __name__ == "__main__":
    unittest.main()
