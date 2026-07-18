from __future__ import annotations

import unittest

from maple_star.workers.experience_ocr import ExperienceCursorTransaction


class _LeasePort:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def acquire(self, owner: str, now: float, timeout: float) -> int:
        self.events.append(("acquire", owner, now, timeout))
        return 7

    def move(self, token: int, position: tuple[int, int]) -> bool:
        self.events.append(("move", token, position))
        return True

    def release(self, token: int) -> bool:
        self.events.append(("release", token))
        return True


class ExperienceWorkerRuntimeTests(unittest.TestCase):
    def test_cursor_transaction_releases_after_ocr_failure(self) -> None:
        port = _LeasePort()
        with self.assertRaises(RuntimeError):
            with ExperienceCursorTransaction(port, now=1.0, timeout=2.0) as transaction:
                transaction.move((100, 200))
                raise RuntimeError("ocr")

        self.assertEqual(port.events[-1], ("release", 7))


if __name__ == "__main__":
    unittest.main()
