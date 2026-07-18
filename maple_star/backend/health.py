from __future__ import annotations

from dataclasses import dataclass

from .worker_registry import WorkerRecord


@dataclass(frozen=True, slots=True)
class WorkerHealthPolicy:
    ready_timeout: float
    heartbeat_timeout: float
    progress_timeout: float


DEFAULT_HEALTH_POLICY = WorkerHealthPolicy(
    ready_timeout=10.0,
    heartbeat_timeout=2.0,
    progress_timeout=30.0,
)


class RestartBudget:
    def __init__(self, backoffs: tuple[float, ...] = (0.5, 2.0, 10.0)) -> None:
        self._backoffs = backoffs
        self._used = 0

    @property
    def remaining(self) -> int:
        return max(0, len(self._backoffs) - self._used)

    def consume(self) -> float | None:
        if self._used >= len(self._backoffs):
            return None
        delay = self._backoffs[self._used]
        self._used += 1
        return delay


def assess_worker_health(record: WorkerRecord, policy: WorkerHealthPolicy, *, now: float) -> str:
    if not record.ready:
        return "starting" if now - record.registered_at <= policy.ready_timeout else "ready-timeout"
    heartbeat_age = now - (record.heartbeat_at or record.ready_at or record.registered_at)
    progress_age = now - (record.progress_at or record.ready_at or record.registered_at)
    if heartbeat_age <= policy.heartbeat_timeout or progress_age <= policy.progress_timeout:
        return "healthy"
    return "stalled"


__all__ = ["DEFAULT_HEALTH_POLICY", "RestartBudget", "WorkerHealthPolicy", "assess_worker_health"]
