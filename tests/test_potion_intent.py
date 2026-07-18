from __future__ import annotations

import unittest

from maple_star.models.potion_intent import PotionIntent, validate_potion_intent


class PotionIntentTests(unittest.TestCase):
    def test_intent_requires_current_session_generations_and_deadline(self) -> None:
        intent = PotionIntent("session", 2, 3, "hp", 65, created_at=1.0, expires_at=1.5)

        self.assertTrue(validate_potion_intent(intent, session_epoch="session", settings_generation=2, target_generation=3, now=1.2))
        self.assertFalse(validate_potion_intent(intent, session_epoch="old", settings_generation=2, target_generation=3, now=1.2))
        self.assertFalse(validate_potion_intent(intent, session_epoch="session", settings_generation=1, target_generation=3, now=1.2))
        self.assertFalse(validate_potion_intent(intent, session_epoch="session", settings_generation=2, target_generation=3, now=2.0))


if __name__ == "__main__":
    unittest.main()
