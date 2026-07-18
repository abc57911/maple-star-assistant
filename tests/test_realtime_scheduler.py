from __future__ import annotations

import unittest

from maple_star.ipc.messages import InputAction
from maple_star.workers.realtime_scheduler import RealtimeScheduler


class RealtimeSchedulerTests(unittest.TestCase):
    def test_periodic_deadline_does_not_replay_expired_backlog(self) -> None:
        scheduler = RealtimeScheduler(safety_generation=2)
        scheduler.schedule_key(
            due_at=1.0,
            vk_code=65,
            action=InputAction.TAP,
            ttl=0.5,
            interval=1.0,
        )

        first = scheduler.drain_due(now=1.1)
        second = scheduler.drain_due(now=5.2)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(scheduler.next_deadline, 6.0)

    def test_fence_cancels_all_deadlines_and_generation_advances(self) -> None:
        scheduler = RealtimeScheduler(safety_generation=1)
        scheduler.schedule_key(due_at=1.0, vk_code=65, action=InputAction.KEY_DOWN, ttl=1.0)

        generation = scheduler.fence()

        self.assertEqual(generation, 2)
        self.assertIsNone(scheduler.next_deadline)
        self.assertEqual(scheduler.drain_due(now=2.0), [])


if __name__ == "__main__":
    unittest.main()
