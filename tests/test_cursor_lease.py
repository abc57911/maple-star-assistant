from __future__ import annotations

import unittest

from maple_star.services.cursor_lease import CursorLeaseManager


class _Cursor:
    def __init__(self) -> None:
        self.position = (10, 20)
        self.moves: list[tuple[int, int]] = []

    def get_cursor_position(self) -> tuple[int, int]:
        return self.position

    def set_cursor_position(self, x: int, y: int) -> None:
        self.position = (x, y)
        self.moves.append((x, y))


class CursorLeaseTests(unittest.TestCase):
    def test_timeout_or_crash_restores_original_position(self) -> None:
        cursor = _Cursor()
        leases = CursorLeaseManager(cursor)
        lease = leases.acquire(owner="ocr", now=1.0, timeout=2.0)
        leases.move(lease.token, (100, 200))

        self.assertTrue(leases.expire(now=3.1))
        self.assertEqual(cursor.position, (10, 20))
        self.assertIsNone(leases.active)

    def test_stale_token_cannot_move_or_release_new_lease(self) -> None:
        cursor = _Cursor()
        leases = CursorLeaseManager(cursor)
        first = leases.acquire(owner="ocr", now=1.0, timeout=1.0)
        leases.release(first.token)
        second = leases.acquire(owner="ocr", now=2.0, timeout=1.0)

        self.assertFalse(leases.move(first.token, (9, 9)))
        self.assertFalse(leases.release(first.token))
        self.assertEqual(leases.active, second)


if __name__ == "__main__":
    unittest.main()
