from __future__ import annotations

import unittest

from maple_star.backend.worker_registry import WorkerRegistry
from maple_star.ipc.identity import WorkerIdentity, WorkerRole


class WorkerRegistryTests(unittest.TestCase):
    def test_restart_replaces_incarnation_and_clears_transient_state(self) -> None:
        registry = WorkerRegistry(session_epoch="session")
        first = registry.register(WorkerRole.POTION, pid=10, creation_time=1.0, now=2.0)
        registry.mark_ready(first.identity, now=3.0)
        registry.record_heartbeat(first.identity, phase="capture", now=4.0)
        registry.record_progress(first.identity, now=4.5)
        registry.set_queue_metrics(first.identity, depth=4, dropped=2)

        second = registry.register(WorkerRole.POTION, pid=11, creation_time=5.0, now=6.0)

        self.assertEqual(second.identity, WorkerIdentity("session", WorkerRole.POTION, 2))
        self.assertFalse(second.ready)
        self.assertIsNone(second.phase)
        self.assertEqual(second.queue_depth, 0)
        self.assertEqual(second.dropped_count, 0)
        self.assertEqual(second.restart_count, 1)

    def test_stale_incarnation_updates_are_rejected(self) -> None:
        registry = WorkerRegistry(session_epoch="session")
        first = registry.register(WorkerRole.EXPERIENCE, pid=10, creation_time=1.0, now=2.0)
        registry.register(WorkerRole.EXPERIENCE, pid=11, creation_time=3.0, now=4.0)

        self.assertFalse(registry.mark_ready(first.identity, now=5.0))


if __name__ == "__main__":
    unittest.main()
