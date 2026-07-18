from __future__ import annotations

from enum import StrEnum


class SupervisorState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


TERMINAL_SUPERVISOR_STATES = frozenset({SupervisorState.FAILED, SupervisorState.STOPPED})

__all__ = ["SupervisorState", "TERMINAL_SUPERVISOR_STATES"]
