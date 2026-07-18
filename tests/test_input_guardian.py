from __future__ import annotations

import unittest

from maple_star.ipc.messages import InputAction, InputCommand
from maple_star.workers.input_guardian import GuardianState, InputGuardian


class _Adapter:
    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    def key_down(self, vk: int) -> None:
        self.events.append(("down", vk))

    def key_up(self, vk: int) -> None:
        self.events.append(("up", vk))


class InputGuardianTests(unittest.TestCase):
    def test_safety_generation_releases_and_rejects_stale_rearm(self) -> None:
        adapter = _Adapter()
        guardian = InputGuardian(adapter, foreground_check=lambda: True)
        guardian.handle(InputCommand(InputAction.KEY_DOWN, vk_code=65, safety_generation=0, expires_at=10.0), now=1.0)

        guardian.safety_fence(generation=2)

        self.assertEqual(guardian.state, GuardianState.SAFE)
        self.assertEqual(adapter.events, [("down", 65), ("up", 65)])
        self.assertFalse(guardian.rearm(generation=1))
        self.assertTrue(guardian.rearm(generation=2))
        self.assertEqual(guardian.state, GuardianState.ARMED)

    def test_terminal_stop_never_rearms_and_expired_command_is_dropped(self) -> None:
        adapter = _Adapter()
        guardian = InputGuardian(adapter, foreground_check=lambda: True)

        self.assertFalse(
            guardian.handle(InputCommand(InputAction.KEY_DOWN, vk_code=65, safety_generation=0, expires_at=1.0), now=2.0)
        )
        guardian.terminal_stop(generation=3)

        self.assertFalse(guardian.rearm(generation=4))
        self.assertEqual(guardian.state, GuardianState.SAFE)
        self.assertEqual(adapter.events, [])


if __name__ == "__main__":
    unittest.main()
