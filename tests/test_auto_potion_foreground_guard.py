import unittest
from unittest.mock import Mock, patch

from maple_star.controller import AutoPotionController
from maple_star.constants import ASYNC_KEY_DOWN_MASK
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
        controller.emergency_stop_requested = False
        controller.scripts_enabled = True
        controller.control_hotkeys_suppressed_until_release = False
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
        self.assertEqual(controller.last_action, "Pause 硬停止")
        controller.gui.set_status.assert_called_with("Pause 硬停止：所有腳本已暫停")

    def test_control_hotkeys_are_ignored_while_key_capture_is_active(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = True
        controller.toggle_hotkey_was_down = True
        controller.emergency_stop_hotkey_was_down = True
        controller._discard_control_hotkey_messages = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()

        controller.poll_control_hotkeys()

        controller._discard_control_hotkey_messages.assert_called_once()
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        self.assertFalse(controller.toggle_hotkey_was_down)
        self.assertFalse(controller.emergency_stop_hotkey_was_down)

    def test_control_hotkeys_are_ignored_once_after_key_capture_finishes(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = True
        controller._discard_control_hotkey_messages = Mock()
        controller._sync_control_hotkey_down_states = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()

        controller.poll_control_hotkeys()

        controller._discard_control_hotkey_messages.assert_called_once()
        controller._sync_control_hotkey_down_states.assert_called_once()
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()

    def test_control_hotkeys_stay_ignored_until_captured_key_is_released(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.side_effect = [True, False, False]
        controller.registered_toggle_hotkey_vk = 0x7A
        controller.registered_emergency_stop_hotkey_vk = 0x13
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller._discard_control_hotkey_messages = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()

        with patch("maple_star.controller.user32.GetAsyncKeyState", return_value=ASYNC_KEY_DOWN_MASK):
            controller.poll_control_hotkeys()
            controller.poll_control_hotkeys()

        self.assertTrue(controller.control_hotkeys_suppressed_until_release)
        self.assertTrue(controller.toggle_hotkey_was_down)
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()

        with patch("maple_star.controller.user32.GetAsyncKeyState", return_value=0):
            controller.poll_control_hotkeys()

        self.assertFalse(controller.control_hotkeys_suppressed_until_release)
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()


if __name__ == "__main__":
    unittest.main()
