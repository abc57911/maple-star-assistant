from __future__ import annotations

import unittest

from maple_star.workers.notification_media import NotificationMediaQueue


class NotificationMediaWorkerTests(unittest.TestCase):
    def test_duplicate_normal_events_coalesce_and_fatal_stays_prioritized(self) -> None:
        queue = NotificationMediaQueue(capacity=3)
        self.assertTrue(queue.put("beep", "same", fatal=False))
        self.assertTrue(queue.put("beep", "same", fatal=False))
        self.assertTrue(queue.put("telegram", "alert", fatal=False))
        self.assertTrue(queue.put("error", "fatal", fatal=True))

        events = queue.drain()

        self.assertEqual([(event.kind, event.payload) for event in events], [("error", "fatal"), ("beep", "same"), ("telegram", "alert")])
        self.assertEqual(queue.coalesced_count, 1)


if __name__ == "__main__":
    unittest.main()
