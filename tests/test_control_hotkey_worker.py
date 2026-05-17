import unittest
from unittest.mock import patch

from maple_star.constants import ASYNC_KEY_DOWN_MASK, WM_HOTKEY
from maple_star.services import control_hotkey_worker as hotkeys


class FakeUser32:
    def __init__(self):
        self.registered = []
        self.unregistered = []
        self.messages = []
        self.down_vks = set()
        self.register_result = True

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):
        self.registered.append((hwnd, hotkey_id, modifiers, vk))
        return self.register_result

    def UnregisterHotKey(self, hwnd, hotkey_id):
        self.unregistered.append((hwnd, hotkey_id))
        return True

    def PeekMessageW(self, message_pointer, hwnd, minimum, maximum, remove):
        if not self.messages:
            return False
        message = self.messages.pop(0)
        target = message_pointer._obj
        target.message = WM_HOTKEY
        target.wParam = message
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

    def test_registered_hotkey_message_is_dispatched(self):
        worker = hotkeys.ControlHotkeyWorker()
        worker._sync_registered_hotkeys({hotkeys.CONTROL_HOTKEY_EXPERIENCE_TOGGLE: 0x79})
        self.fake_user32.messages.append(hotkeys.CONTROL_HOTKEY_IDS[hotkeys.CONTROL_HOTKEY_EXPERIENCE_TOGGLE])

        events = worker._drain_registered_hotkey_messages()

        self.assertEqual(events, [hotkeys.CONTROL_HOTKEY_EXPERIENCE_TOGGLE])
        self.assertEqual(worker.drain_events(), [hotkeys.CONTROL_HOTKEY_EXPERIENCE_TOGGLE])

    def test_register_failure_keeps_polling_fallback_available(self):
        worker = hotkeys.ControlHotkeyWorker()
        self.fake_user32.register_result = False

        worker._sync_registered_hotkeys({hotkeys.CONTROL_HOTKEY_TOGGLE: 0x7A})
        worker._sync_registered_hotkeys({hotkeys.CONTROL_HOTKEY_TOGGLE: 0x7A})
        self.fake_user32.down_vks.add(0x7A)

        self.assertEqual(len(self.fake_user32.registered), 1)
        self.assertEqual(worker._drain_registered_hotkey_messages(), [])
        self.assertTrue(hotkeys._is_key_down(0x7A))
        self.assertEqual(worker.drain_events(), [])

    def test_hotkey_update_unregisters_previous_registration(self):
        worker = hotkeys.ControlHotkeyWorker()
        worker._sync_registered_hotkeys({hotkeys.CONTROL_HOTKEY_TOGGLE: 0x7A})

        worker._sync_registered_hotkeys({hotkeys.CONTROL_HOTKEY_EMERGENCY_STOP: 0x13})

        self.assertIn((None, hotkeys.CONTROL_HOTKEY_IDS[hotkeys.CONTROL_HOTKEY_TOGGLE]), self.fake_user32.unregistered)
        self.assertEqual(
            worker._registered_vk_by_event,
            {hotkeys.CONTROL_HOTKEY_EMERGENCY_STOP: 0x13},
        )

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
