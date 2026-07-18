from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from maple_star.ipc.messages import InputAction, InputCommand


@dataclass(order=True, slots=True)
class _ScheduledKey:
    due_at: float
    sequence: int
    vk_code: int = field(compare=False)
    action: InputAction = field(compare=False)
    ttl: float = field(compare=False)
    interval: float | None = field(compare=False)


class RealtimeScheduler:
    def __init__(self, *, safety_generation: int = 0) -> None:
        self.safety_generation = safety_generation
        self._sequence = 0
        self._deadlines: list[_ScheduledKey] = []

    @property
    def next_deadline(self) -> float | None:
        return self._deadlines[0].due_at if self._deadlines else None

    def schedule_key(
        self,
        *,
        due_at: float,
        vk_code: int,
        action: InputAction,
        ttl: float,
        interval: float | None = None,
    ) -> None:
        if ttl <= 0.0 or (interval is not None and interval <= 0.0):
            raise ValueError("deadline ttl and interval must be positive")
        self._sequence += 1
        heapq.heappush(
            self._deadlines,
            _ScheduledKey(due_at, self._sequence, vk_code, action, ttl, interval),
        )

    def drain_due(self, *, now: float) -> list[InputCommand]:
        commands: list[InputCommand] = []
        while self._deadlines and self._deadlines[0].due_at <= now:
            entry = heapq.heappop(self._deadlines)
            effective_due = entry.due_at
            if entry.interval is not None and now > effective_due:
                skipped = math.floor((now - effective_due) / entry.interval)
                effective_due += skipped * entry.interval
            if now <= effective_due + entry.ttl:
                commands.append(
                    InputCommand(
                        entry.action,
                        vk_code=entry.vk_code,
                        safety_generation=self.safety_generation,
                        expires_at=effective_due + entry.ttl,
                    )
                )
            if entry.interval is not None:
                entry.due_at = effective_due + entry.interval
                heapq.heappush(self._deadlines, entry)
        return commands

    def fence(self) -> int:
        self.safety_generation += 1
        self._deadlines.clear()
        return self.safety_generation


__all__ = ["RealtimeScheduler"]
