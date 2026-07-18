from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum


class WorkerRole(StrEnum):
    GUI = "gui"
    SUPERVISOR = "supervisor"
    GUARDIAN = "guardian"
    SCHEDULER = "scheduler"
    POTION = "potion"
    EXPERIENCE = "experience"
    NOTIFICATION = "notification"


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    session_epoch: str
    worker_role: WorkerRole
    worker_incarnation: int

    def __post_init__(self) -> None:
        if not self.session_epoch:
            raise ValueError("session_epoch must not be empty")
        if self.worker_incarnation < 1:
            raise ValueError("worker_incarnation must be positive")


@dataclass(frozen=True, slots=True)
class MessageMeta:
    session_epoch: str
    worker_role: WorkerRole
    worker_incarnation: int
    channel: str
    stream_sequence: int
    settings_generation: int
    target_generation: int
    created_at: float

    def __post_init__(self) -> None:
        if not self.session_epoch or not self.channel:
            raise ValueError("message identity and channel must not be empty")
        if self.worker_incarnation < 1 or self.stream_sequence < 1:
            raise ValueError("incarnation and sequence must be positive")
        if self.settings_generation < 0 or self.target_generation < 0:
            raise ValueError("generations must not be negative")

    def is_current(self, identity: WorkerIdentity, *, last_sequence: int) -> bool:
        return bool(
            self.session_epoch == identity.session_epoch
            and self.worker_role == identity.worker_role
            and self.worker_incarnation == identity.worker_incarnation
            and self.stream_sequence > last_sequence
        )

    def with_session(self, session_epoch: str) -> "MessageMeta":
        return replace(self, session_epoch=session_epoch)

    def with_incarnation(self, worker_incarnation: int) -> "MessageMeta":
        return replace(self, worker_incarnation=worker_incarnation)


class StreamSequencer:
    def __init__(
        self,
        identity: WorkerIdentity,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._identity = identity
        self._clock = clock
        self._sequences: dict[str, int] = {}

    def next(
        self,
        channel: str,
        *,
        settings_generation: int = 0,
        target_generation: int = 0,
    ) -> MessageMeta:
        if not channel:
            raise ValueError("channel must not be empty")
        sequence = self._sequences.get(channel, 0) + 1
        self._sequences[channel] = sequence
        return MessageMeta(
            session_epoch=self._identity.session_epoch,
            worker_role=self._identity.worker_role,
            worker_incarnation=self._identity.worker_incarnation,
            channel=channel,
            stream_sequence=sequence,
            settings_generation=settings_generation,
            target_generation=target_generation,
            created_at=self._clock(),
        )
