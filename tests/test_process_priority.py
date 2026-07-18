from __future__ import annotations

import unittest

from maple_star.backend.process_priority import set_current_process_above_normal


class ProcessPriorityTests(unittest.TestCase):
    def test_windows_priority_request_is_non_fatal(self) -> None:
        self.assertIsInstance(set_current_process_above_normal(), bool)


if __name__ == "__main__":
    unittest.main()
