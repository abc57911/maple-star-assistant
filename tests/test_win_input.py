import unittest
from unittest.mock import patch

from maple_star.adapters import win_input


class KeyboardInputTests(unittest.TestCase):
    def test_extended_keys_include_extended_flag(self):
        event = win_input.keyboard_input(win_input.parse_vk_key("PageUp"))
        key_up_event = win_input.keyboard_input(win_input.parse_vk_key("PageUp"), win_input.KEYEVENTF_KEYUP)

        self.assertEqual(event.union.ki.dwFlags, win_input.KEYEVENTF_EXTENDEDKEY)
        self.assertEqual(
            key_up_event.union.ki.dwFlags,
            win_input.KEYEVENTF_EXTENDEDKEY | win_input.KEYEVENTF_KEYUP,
        )

    def test_regular_keys_do_not_include_extended_flag(self):
        event = win_input.keyboard_input(win_input.parse_vk_key("C"))

        self.assertEqual(event.union.ki.dwFlags, 0)


class TemporaryMouseInputLockTests(unittest.TestCase):
    def test_physical_mouse_activity_observer_records_only_non_injected_events(self):
        times = iter([10.0, 11.0])
        observer = win_input.PhysicalMouseActivityObserver(clock=lambda: next(times))

        self.assertTrue(observer.record_mouse_event(0))
        self.assertEqual(observer.last_activity_at, 10.0)
        self.assertFalse(observer.record_mouse_event(win_input.LLMHF_INJECTED))
        self.assertEqual(observer.last_activity_at, 10.0)

    def test_physical_mouse_activity_observer_poll_detects_cursor_and_button_changes(self):
        times = iter([10.0, 11.0, 12.0])
        observer = win_input.PhysicalMouseActivityObserver(clock=lambda: next(times))

        with (
            patch("maple_star.adapters.win_input.get_cursor_position", side_effect=[(100, 200), (101, 200), (101, 200)]),
            patch("maple_star.adapters.win_input.user32.GetAsyncKeyState", side_effect=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, win_input.MOUSE_ACTIVITY_ASYNC_DOWN_MASK, 0, 0, 0, 0]),
        ):
            self.assertFalse(observer.poll_once())
            self.assertTrue(observer.poll_once())
            self.assertTrue(observer.poll_once())

        self.assertEqual(observer.last_activity_at, 12.0)

    def test_physical_mouse_activity_observer_poll_ignores_programmatic_cursor_changes(self):
        times = iter([10.0, 10.1])
        observer = win_input.PhysicalMouseActivityObserver(clock=lambda: next(times))

        with (
            patch("maple_star.adapters.win_input.get_cursor_position", side_effect=[(100, 200), (120, 200)]),
            patch("maple_star.adapters.win_input.user32.GetAsyncKeyState", return_value=0),
            patch("maple_star.adapters.win_input.programmatic_mouse_input_is_recent", return_value=True),
        ):
            self.assertFalse(observer.poll_once())
            self.assertFalse(observer.poll_once())

        self.assertEqual(observer.last_activity_at, -999.0)

    def test_temporary_mouse_input_lock_restores_before_and_after_unlock(self):
        events = []

        class FakeLowLevelMouseInputLock:
            def start(self):
                events.append("start")

            def stop(self):
                events.append("stop")

        with (
            patch("maple_star.adapters.win_input.get_cursor_position", side_effect=lambda: events.append("get") or (123, 456)),
            patch("maple_star.adapters.win_input.set_cursor_position", side_effect=lambda x, y: events.append(f"set:{x},{y}")),
            patch("maple_star.adapters.win_input.time.sleep", side_effect=lambda _seconds: events.append("drain")),
            patch("maple_star.adapters.win_input._LowLevelMouseInputLock", return_value=FakeLowLevelMouseInputLock()),
        ):
            with win_input.temporary_mouse_input_lock() as original_position:
                self.assertEqual(original_position, (123, 456))
                events.append("inside")

        self.assertEqual(
            events,
            [
                "get",
                "start",
                "inside",
                "set:123,456",
                "drain",
                "set:123,456",
                "stop",
                "set:123,456",
            ],
        )


if __name__ == "__main__":
    unittest.main()
