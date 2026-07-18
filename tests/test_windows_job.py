from __future__ import annotations

import unittest

from maple_star.backend.windows_job import WorkerJob
from maple_star.ipc.identity import WorkerRole


class _Port:
    def __init__(self) -> None:
        self.assigned: list[int] = []
        self.closed = 0

    def assign(self, pid: int) -> None:
        self.assigned.append(pid)

    def close(self) -> None:
        self.closed += 1


class WindowsJobTests(unittest.TestCase):
    def test_guardian_is_excluded_and_close_is_idempotent(self) -> None:
        port = _Port()
        job = WorkerJob(port)

        self.assertFalse(job.add(WorkerRole.GUARDIAN, 10))
        self.assertTrue(job.add(WorkerRole.POTION, 11))
        job.close()
        job.close()

        self.assertEqual(port.assigned, [11])
        self.assertEqual(port.closed, 1)


if __name__ == "__main__":
    unittest.main()
