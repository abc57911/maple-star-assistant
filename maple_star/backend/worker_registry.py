from __future__ import annotations

from dataclasses import dataclass

from maple_star.ipc.identity import WorkerIdentity, WorkerRole


@dataclass(slots=True)
class WorkerRecord:
    identity: WorkerIdentity
    pid: int
    creation_time: float
    registered_at: float
    ready: bool = False
    ready_at: float | None = None
    heartbeat_at: float | None = None
    progress_at: float | None = None
    phase: str | None = None
    restart_count: int = 0
    queue_depth: int = 0
    dropped_count: int = 0


class WorkerRegistry:
    def __init__(self, *, session_epoch: str) -> None:
        if not session_epoch:
            raise ValueError("session_epoch must not be empty")
        self.session_epoch = session_epoch
        self._records: dict[WorkerRole, WorkerRecord] = {}

    def register(self, role: WorkerRole, *, pid: int, creation_time: float, now: float) -> WorkerRecord:
        previous = self._records.get(role)
        incarnation = 1 if previous is None else previous.identity.worker_incarnation + 1
        restart_count = 0 if previous is None else previous.restart_count + 1
        record = WorkerRecord(
            identity=WorkerIdentity(self.session_epoch, role, incarnation),
            pid=pid,
            creation_time=creation_time,
            registered_at=now,
            restart_count=restart_count,
        )
        self._records[role] = record
        return record

    def current(self, role: WorkerRole) -> WorkerRecord | None:
        return self._records.get(role)

    def require(self, role: WorkerRole) -> WorkerRecord:
        try:
            return self._records[role]
        except KeyError as exc:
            raise KeyError(f"worker is not registered: {role.value}") from exc

    def _matching(self, identity: WorkerIdentity) -> WorkerRecord | None:
        record = self._records.get(identity.worker_role)
        return record if record is not None and record.identity == identity else None

    def mark_ready(self, identity: WorkerIdentity, *, now: float) -> bool:
        record = self._matching(identity)
        if record is None:
            return False
        record.ready = True
        record.ready_at = now
        record.heartbeat_at = now
        record.progress_at = now
        return True

    def record_heartbeat(self, identity: WorkerIdentity, *, phase: str, now: float) -> bool:
        record = self._matching(identity)
        if record is None:
            return False
        record.heartbeat_at = now
        record.phase = phase
        return True

    def record_progress(self, identity: WorkerIdentity, *, now: float) -> bool:
        record = self._matching(identity)
        if record is None:
            return False
        record.progress_at = now
        return True

    def set_queue_metrics(self, identity: WorkerIdentity, *, depth: int, dropped: int) -> bool:
        record = self._matching(identity)
        if record is None:
            return False
        record.queue_depth = max(0, depth)
        record.dropped_count = max(0, dropped)
        return True

    def records(self) -> tuple[WorkerRecord, ...]:
        return tuple(self._records.values())

    def __len__(self) -> int:
        return len(self._records)
