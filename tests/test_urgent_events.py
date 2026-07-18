from __future__ import annotations

import unittest

from maple_star.ipc.urgent_events import UrgentEventQueue


class UrgentEventTests(unittest.TestCase):
    def test_fatal_event_evicts_normal_event_when_full(self) -> None:
        queue = UrgentEventQueue(capacity=2)
        self.assertTrue(queue.put("normal-1", fatal=False))
        self.assertTrue(queue.put("normal-2", fatal=False))

        self.assertTrue(queue.put("fatal", fatal=True))

        events = queue.drain()
        self.assertEqual([event.payload for event in events], ["fatal", "normal-2"])
        self.assertEqual(queue.dropped_normal_count, 1)

    def test_fatal_delivery_failure_is_observable(self) -> None:
        queue = UrgentEventQueue(capacity=1)
        queue.put("fatal-1", fatal=True)

        self.assertFalse(queue.put("fatal-2", fatal=True))
        self.assertEqual(queue.failed_fatal_count, 1)


if __name__ == "__main__":
    unittest.main()
