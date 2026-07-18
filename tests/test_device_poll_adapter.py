from __future__ import annotations

import unittest

from maple_star.services.device_poll_adapter import LatestDeviceState


class DevicePollAdapterTests(unittest.TestCase):
    def test_latest_state_replaces_old_poll_without_backlog(self) -> None:
        states = LatestDeviceState()
        states.publish({"A": False})
        states.publish({"A": True})

        self.assertEqual(states.take(), {"A": True})
        self.assertIsNone(states.take())
        self.assertEqual(states.replaced_count, 1)


if __name__ == "__main__":
    unittest.main()
