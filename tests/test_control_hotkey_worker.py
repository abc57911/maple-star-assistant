import unittest
import time
from unittest.mock import patch

from maple_star.constants import ASYNC_KEY_DOWN_MASK
from maple_star.services import control_hotkey_worker as hotkeys


class FakeUser32:
    def __init__(self):
        self.registered = []
        self.unregistered = []
        self.down_vks = set()

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):
        self.registered.append((hwnd, hotkey_id, modifiers, vk))
        return True

    def UnregisterHotKey(self, hwnd, hotkey_id):
        self.unregistered.append((hwnd, hotkey_id))
        return True

    def GetAsyncKeyState(self, vk):
        return ASYNC_KEY_DOWN_MASK if vk in self.down_vks else 0


class ControlHotkeyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.original_user32 = hotkeys.user32
        self.fake_user32 = FakeUser32()
        hotkeys.user32 = self.fake_user32

    def tearDown(self):
        hotkeys.user32 = self.original_user32

    def test_worker_polls_hotkeys_without_global_registration(self):
        worker = hotkeys.ControlHotkeyWorker(poll_interval_seconds=0.001)
        worker.update_hotkeys({hotkeys.CONTROL_HOTKEY_TOGGLE: 0x7A})
        worker.start()
        time.sleep(0.01)
        self.fake_user32.down_vks.add(0x7A)
        time.sleep(0.02)
        events = worker.drain_events()
        worker.stop()

        self.assertEqual(self.fake_user32.registered, [])
        self.assertEqual(self.fake_user32.unregistered, [])
        self.assertEqual(events, [hotkeys.CONTROL_HOTKEY_TOGGLE])

    def test_events_disabled_tracks_down_state_without_dispatching(self):
        worker = hotkeys.ControlHotkeyWorker(poll_interval_seconds=0.001)
        worker.update_hotkeys({hotkeys.CONTROL_HOTKEY_TOGGLE: 0x7A})
        worker.set_events_enabled(False)
        worker.start()
        self.fake_user32.down_vks.add(0x7A)
        time.sleep(0.02)
        worker.stop()

        self.assertEqual(
            worker.cached_down_states(),
            {hotkeys.CONTROL_HOTKEY_TOGGLE: True},
        )
        self.assertEqual(worker.drain_events(), [])

    def test_duplicate_event_is_suppressed_briefly(self):
        worker = hotkeys.ControlHotkeyWorker()

        with patch("maple_star.services.control_hotkey_worker.time.monotonic", side_effect=[100.0, 100.8, 101.6]):
            self.assertTrue(worker._emit_event(hotkeys.CONTROL_HOTKEY_PICKUP_TOGGLE))
            self.assertFalse(worker._emit_event(hotkeys.CONTROL_HOTKEY_PICKUP_TOGGLE))
            self.assertTrue(worker._emit_event(hotkeys.CONTROL_HOTKEY_PICKUP_TOGGLE))

        self.assertEqual(
            worker.drain_events(),
            [hotkeys.CONTROL_HOTKEY_PICKUP_TOGGLE, hotkeys.CONTROL_HOTKEY_PICKUP_TOGGLE],
        )


if __name__ == "__main__":
    unittest.main()
