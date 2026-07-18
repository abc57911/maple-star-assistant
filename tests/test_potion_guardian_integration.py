from __future__ import annotations

import unittest

from maple_star.models.potion_intent import PotionIntent
from maple_star.workers.input_guardian import InputGuardian
from maple_star.workers.potion_vision import intent_to_input_command


class _Adapter:
    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    def key_down(self, vk: int) -> None:
        self.events.append(("down", vk))

    def key_up(self, vk: int) -> None:
        self.events.append(("up", vk))


class PotionGuardianIntegrationTests(unittest.TestCase):
    def test_valid_intent_becomes_expiring_guardian_tap(self) -> None:
        adapter = _Adapter()
        guardian = InputGuardian(adapter, foreground_check=lambda: True)
        intent = PotionIntent("session", 1, 1, "hp", 65, created_at=1.0, expires_at=1.5)

        command = intent_to_input_command(
            intent,
            session_epoch="session",
            settings_generation=1,
            target_generation=1,
            safety_generation=0,
            now=1.1,
        )

        self.assertIsNotNone(command)
        self.assertTrue(guardian.handle(command, now=1.1))
        self.assertEqual(adapter.events, [("down", 65), ("up", 65)])


if __name__ == "__main__":
    unittest.main()
