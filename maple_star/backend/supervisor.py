from __future__ import annotations

from collections.abc import Iterable

from maple_star.ipc.identity import WorkerIdentity, WorkerRole

from .states import SupervisorState, TERMINAL_SUPERVISOR_STATES
from .worker_ports import SafetyPort
from .worker_registry import WorkerRegistry


class BackendSupervisor:
    def __init__(
        self,
        *,
        session_epoch: str,
        required_roles: Iterable[WorkerRole],
        safety_port: SafetyPort,
    ) -> None:
        self.state = SupervisorState.CREATED
        self.registry = WorkerRegistry(session_epoch=session_epoch)
        self.required_roles = frozenset(required_roles)
        self._safety_port = safety_port

    def start(self) -> None:
        if self.state is not SupervisorState.CREATED:
            raise RuntimeError(f"cannot start supervisor from {self.state.value}")
        self.state = SupervisorState.STARTING

    def worker_ready(self, identity: WorkerIdentity, *, now: float) -> bool:
        accepted = self.registry.mark_ready(identity, now=now)
        if not accepted or self.state in TERMINAL_SUPERVISOR_STATES:
            return accepted
        if all(
            (record := self.registry.current(role)) is not None and record.ready
            for role in self.required_roles
        ):
            self.state = SupervisorState.READY
        return True

    def worker_failed(self, role: WorkerRole, reason: str) -> None:
        if self.state in {SupervisorState.STOPPING, SupervisorState.STOPPED}:
            return
        if role in {WorkerRole.GUARDIAN, WorkerRole.SCHEDULER}:
            self._safety_port.fatal_stop(f"{role.value}: {reason}")
            self.state = SupervisorState.FAILED
        else:
            self.state = SupervisorState.DEGRADED

    def stop(self) -> None:
        if self.state is SupervisorState.STOPPED:
            return
        self.state = SupervisorState.STOPPING

    def stopped(self) -> None:
        if self.state is not SupervisorState.STOPPING:
            raise RuntimeError(f"cannot finish stop from {self.state.value}")
        self.state = SupervisorState.STOPPED


__all__ = ["BackendSupervisor"]
