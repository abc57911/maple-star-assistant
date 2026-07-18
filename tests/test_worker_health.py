from __future__ import annotations

import unittest

from maple_star.backend.health import RestartBudget, WorkerHealthPolicy, assess_worker_health
from maple_star.backend.worker_registry import WorkerRegistry
from maple_star.ipc.identity import WorkerRole


class WorkerHealthTests(unittest.TestCase):
    def test_progress_prevents_false_timeout_during_long_capture(self) -> None:
        registry = WorkerRegistry(session_epoch="session")
        record = registry.register(WorkerRole.POTION, pid=10, creation_time=0.0, now=0.0)
        registry.mark_ready(record.identity, now=0.1)
        registry.record_heartbeat(record.identity, phase="capture", now=1.0)
        registry.record_progress(record.identity, now=2.5)
        policy = WorkerHealthPolicy(ready_timeout=2.0, heartbeat_timeout=2.0, progress_timeout=3.0)

        self.assertEqual(assess_worker_health(registry.require(WorkerRole.POTION), policy, now=4.0), "healthy")

    def test_restart_budget_uses_approved_backoff_and_caps_at_three(self) -> None:
        budget = RestartBudget()

        self.assertEqual([budget.consume() for _ in range(3)], [0.5, 2.0, 10.0])
        self.assertIsNone(budget.consume())


if __name__ == "__main__":
    unittest.main()
