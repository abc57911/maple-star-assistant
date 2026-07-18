from __future__ import annotations

import unittest

from maple_star.services.input_ownership import InputOwnershipLedger


class _Adapter:
    def __init__(self, *, fail_down: bool = False) -> None:
        self.fail_down = fail_down
        self.events: list[tuple[str, int]] = []

    def key_down(self, vk: int) -> None:
        self.events.append(("down", vk))
        if self.fail_down:
            raise OSError("send failed")

    def key_up(self, vk: int) -> None:
        self.events.append(("up", vk))


class InputOwnershipTests(unittest.TestCase):
    def test_failed_key_down_remains_may_be_held_until_release(self) -> None:
        adapter = _Adapter(fail_down=True)
        ledger = InputOwnershipLedger()

        with self.assertRaises(OSError):
            ledger.key_down(65, adapter)
        self.assertEqual(ledger.may_be_held, frozenset({65}))
        self.assertEqual(ledger.confirmed_held, frozenset())

        ledger.release_all(adapter)

        self.assertEqual(adapter.events, [("down", 65), ("up", 65)])
        self.assertEqual(ledger.may_be_held, frozenset())

    def test_successful_down_confirms_and_up_clears(self) -> None:
        adapter = _Adapter()
        ledger = InputOwnershipLedger()

        ledger.key_down(65, adapter)
        ledger.key_up(65, adapter)

        self.assertEqual(adapter.events, [("down", 65), ("up", 65)])
        self.assertEqual(ledger.confirmed_held, frozenset())


if __name__ == "__main__":
    unittest.main()
