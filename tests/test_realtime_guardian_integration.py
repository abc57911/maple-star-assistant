from __future__ import annotations

import unittest

from maple_star.ipc.messages import InputAction
from maple_star.workers.input_guardian import GuardianState, InputGuardian
from maple_star.workers.realtime_scheduler import RealtimeScheduler


class _Adapter:
    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    def key_down(self, vk: int) -> None:
        self.events.append(("down", vk))

    def key_up(self, vk: int) -> None:
        self.events.append(("up", vk))


class RealtimeGuardianIntegrationTests(unittest.TestCase):
    def test_emergency_fence_cancels_deadline_and_releases_held_key(self) -> None:
        adapter = _Adapter()
        guardian = InputGuardian(adapter, foreground_check=lambda: True)
        scheduler = RealtimeScheduler()
        scheduler.schedule_key(due_at=1.0, vk_code=65, action=InputAction.KEY_DOWN, ttl=1.0)
        command = scheduler.drain_due(now=1.0)[0]
        guardian.handle(command, now=1.0)

        generation = scheduler.fence()
        guardian.safety_fence(generation=generation)

        self.assertEqual(adapter.events, [("down", 65), ("up", 65)])
        self.assertEqual(guardian.state, GuardianState.SAFE)


if __name__ == "__main__":
    unittest.main()
