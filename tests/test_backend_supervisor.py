from __future__ import annotations

import unittest

from maple_star.backend.states import SupervisorState
from maple_star.backend.supervisor import BackendSupervisor
from maple_star.ipc.identity import WorkerRole


class _SafetyPort:
    def __init__(self) -> None:
        self.fatal_reasons: list[str] = []

    def fatal_stop(self, reason: str) -> None:
        self.fatal_reasons.append(reason)


class BackendSupervisorTests(unittest.TestCase):
    def test_state_machine_reaches_ready_only_after_required_workers(self) -> None:
        supervisor = BackendSupervisor(
            session_epoch="session",
            required_roles={WorkerRole.GUARDIAN, WorkerRole.SCHEDULER, WorkerRole.POTION},
            safety_port=_SafetyPort(),
        )
        supervisor.start()
        self.assertEqual(supervisor.state, SupervisorState.STARTING)

        for role in (WorkerRole.GUARDIAN, WorkerRole.SCHEDULER, WorkerRole.POTION):
            record = supervisor.registry.register(role, pid=100 + len(supervisor.registry), creation_time=1.0, now=1.0)
            supervisor.worker_ready(record.identity, now=1.1)

        self.assertEqual(supervisor.state, SupervisorState.READY)

    def test_guardian_or_scheduler_failure_is_fatal(self) -> None:
        safety = _SafetyPort()
        supervisor = BackendSupervisor(
            session_epoch="session",
            required_roles={WorkerRole.GUARDIAN},
            safety_port=safety,
        )
        supervisor.start()
        record = supervisor.registry.register(WorkerRole.GUARDIAN, pid=10, creation_time=1.0, now=1.0)
        supervisor.worker_ready(record.identity, now=1.1)

        supervisor.worker_failed(WorkerRole.GUARDIAN, "lost")

        self.assertEqual(supervisor.state, SupervisorState.FAILED)
        self.assertEqual(safety.fatal_reasons, ["guardian: lost"])


if __name__ == "__main__":
    unittest.main()
