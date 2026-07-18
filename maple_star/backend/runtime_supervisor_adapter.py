from __future__ import annotations

import time
import uuid

from maple_star.ipc.identity import WorkerRole
from maple_star.services.runtime_api import WorkerCrashed

from .supervisor import BackendSupervisor


class _CoordinatorSafetyPort:
    def __init__(self, coordinator) -> None:
        self._coordinator = coordinator
        self.reason = ""

    def fatal_stop(self, reason: str) -> None:
        self.reason = reason
        self._coordinator.safety_fence()


class SupervisedRuntimeProcessPort:
    """Production lifecycle adapter around the process coordinator."""

    def __init__(self, coordinator) -> None:
        self._coordinator = coordinator
        self._session_epoch = uuid.uuid4().hex
        self._incarnations: dict[WorkerRole, int] = {}
        self._safety = _CoordinatorSafetyPort(coordinator)
        self.supervisor = BackendSupervisor(
            session_epoch=self._session_epoch,
            required_roles=(WorkerRole.GUARDIAN, WorkerRole.POTION, WorkerRole.EXPERIENCE),
            safety_port=self._safety,
        )

    def __getattr__(self, name: str):
        return getattr(self._coordinator, name)

    def _ready(self, role: WorkerRole, pid: int) -> None:
        now = time.monotonic()
        record = self.supervisor.registry.register(
            role,
            pid=max(0, int(pid or 0)),
            creation_time=now,
            now=now,
        )
        self._incarnations[role] = record.identity.worker_incarnation
        self.supervisor.worker_ready(record.identity, now=now)

    def start(self) -> None:
        self.supervisor.start()
        try:
            self._coordinator.start()
        except BaseException:
            self.supervisor.worker_failed(WorkerRole.GUARDIAN, "startup failed")
            raise
        self._ready(WorkerRole.GUARDIAN, self._coordinator._guardian_process.pid)
        self._ready(WorkerRole.POTION, self._coordinator._potion_process.pid)
        self._ready(WorkerRole.EXPERIENCE, self._coordinator._experience_process.pid)

    def start_control(self, worker_target, *worker_args: object) -> None:
        self._coordinator.start_control(worker_target, *worker_args)
        self._ready(WorkerRole.SCHEDULER, self._coordinator._control_process.pid)

    def _observe_failures(self, items: list[object]) -> list[object]:
        for item in items:
            if not isinstance(item, WorkerCrashed):
                continue
            try:
                role = WorkerRole(item.worker)
            except ValueError:
                continue
            self.supervisor.worker_failed(role, item.message)
        return items

    def _observe_activity(self, role: WorkerRole, items: list[object]) -> list[object]:
        record = self.supervisor.registry.current(role)
        if record is None or not items:
            return items
        now = time.monotonic()
        heartbeat_at = max(
            (float(getattr(item, "heartbeat_at", now) or now) for item in items),
            default=now,
        )
        progress_at = max(
            (float(getattr(item, "progress_at", now) or now) for item in items),
            default=now,
        )
        self.supervisor.registry.record_heartbeat(record.identity, phase="status", now=heartbeat_at)
        self.supervisor.registry.record_progress(record.identity, now=progress_at)
        return items

    def drain_potion_statuses(self, limit: int = 64) -> list[object]:
        items = self._observe_failures(self._coordinator.drain_potion_statuses(limit))
        return self._observe_activity(WorkerRole.POTION, items)

    def drain_experience_statuses(self, limit: int = 64) -> list[object]:
        items = self._observe_failures(self._coordinator.drain_experience_statuses(limit))
        return self._observe_activity(WorkerRole.EXPERIENCE, items)

    def drain_control_statuses(self, limit: int = 64) -> list[object]:
        items = self._observe_failures(self._coordinator.drain_control_statuses(limit))
        return self._observe_activity(WorkerRole.SCHEDULER, items)

    def diagnostics_text(self, *, now: float | None = None) -> str:
        observed_at = time.monotonic() if now is None else now
        entries: list[str] = []
        for record in self.supervisor.registry.records():
            heartbeat_age = None if record.heartbeat_at is None else max(0.0, observed_at - record.heartbeat_at)
            progress_age = None if record.progress_at is None else max(0.0, observed_at - record.progress_at)
            heartbeat = "--" if heartbeat_age is None else f"{heartbeat_age:.1f}s"
            progress = "--" if progress_age is None else f"{progress_age:.1f}s"
            entries.append(
                f"{record.identity.worker_role.value}:pid={record.pid},inc={record.identity.worker_incarnation},"
                f"hb={heartbeat},progress={progress},queue={record.queue_depth},drop={record.dropped_count}"
            )
        return f"state={self.supervisor.state.value} | " + " | ".join(entries)

    def _alive(self, role: WorkerRole, probe) -> bool:
        alive = bool(probe())
        if not alive:
            self.supervisor.worker_failed(role, "process exited")
        return alive

    def potion_alive(self) -> bool:
        return self._alive(WorkerRole.POTION, self._coordinator.potion_alive)

    def experience_alive(self) -> bool:
        return self._alive(WorkerRole.EXPERIENCE, self._coordinator.experience_alive)

    def control_alive(self) -> bool:
        return self._alive(WorkerRole.SCHEDULER, self._coordinator.control_alive)

    def guardian_alive(self) -> bool:
        return self._alive(WorkerRole.GUARDIAN, self._coordinator.guardian_alive)

    def stop(self, timeout: float = 1.0) -> None:
        self.supervisor.stop()
        try:
            self._coordinator.stop(timeout=timeout)
        finally:
            self.supervisor.stopped()


__all__ = ["SupervisedRuntimeProcessPort"]
