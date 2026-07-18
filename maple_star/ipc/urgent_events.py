from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class UrgentEvent:
    payload: object
    fatal: bool


class UrgentEventQueue:
    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._fatal: deque[UrgentEvent] = deque()
        self._normal: deque[UrgentEvent] = deque()
        self._lock = Lock()
        self.dropped_normal_count = 0
        self.failed_fatal_count = 0

    def put(self, payload: object, *, fatal: bool) -> bool:
        event = UrgentEvent(payload, fatal)
        with self._lock:
            size = len(self._fatal) + len(self._normal)
            if size >= self._capacity:
                if fatal and self._normal:
                    self._normal.popleft()
                    self.dropped_normal_count += 1
                elif fatal:
                    self.failed_fatal_count += 1
                    return False
                else:
                    self.dropped_normal_count += 1
                    return False
            (self._fatal if fatal else self._normal).append(event)
            return True

    def drain(self, *, limit: int | None = None) -> list[UrgentEvent]:
        with self._lock:
            available = len(self._fatal) + len(self._normal)
            count = available if limit is None else min(max(0, limit), available)
            result: list[UrgentEvent] = []
            while len(result) < count and self._fatal:
                result.append(self._fatal.popleft())
            while len(result) < count and self._normal:
                result.append(self._normal.popleft())
            return result


__all__ = ["UrgentEvent", "UrgentEventQueue"]
