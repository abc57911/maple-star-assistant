from __future__ import annotations

import unittest

from maple_star.services.cursor_lease import CursorLeaseManager


class _Cursor:
    def __init__(self) -> None:
        self.position = (1, 2)

    def get_cursor_position(self):
        return self.position

    def set_cursor_position(self, x, y):
        self.position = (x, y)


class CursorGuardianIntegrationTests(unittest.TestCase):
    def test_terminal_stop_restores_active_ocr_cursor_lease(self) -> None:
        cursor = _Cursor()
        leases = CursorLeaseManager(cursor)
        lease = leases.acquire(owner="ocr", now=1.0, timeout=5.0)
        leases.move(lease.token, (9, 9))

        self.assertTrue(leases.terminal_restore())
        self.assertEqual(cursor.position, (1, 2))


if __name__ == "__main__":
    unittest.main()
