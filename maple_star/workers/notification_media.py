from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    kind: str
    payload: object
    fatal: bool


class NotificationMediaQueue:
    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._fatal: deque[NotificationEvent] = deque()
        self._normal: deque[NotificationEvent] = deque()
        self._normal_signatures: set[tuple[str, str]] = set()
        self._lock = Lock()
        self.coalesced_count = 0
        self.dropped_count = 0

    @staticmethod
    def _signature(kind: str, payload: object) -> tuple[str, str]:
        return kind, repr(payload)

    def put(self, kind: str, payload: object, *, fatal: bool) -> bool:
        event = NotificationEvent(kind, payload, fatal)
        signature = self._signature(kind, payload)
        with self._lock:
            if not fatal and signature in self._normal_signatures:
                self.coalesced_count += 1
                return True
            if len(self._fatal) + len(self._normal) >= self._capacity:
                if fatal and self._normal:
                    removed = self._normal.popleft()
                    self._normal_signatures.discard(self._signature(removed.kind, removed.payload))
                    self.dropped_count += 1
                else:
                    self.dropped_count += 1
                    return False
            if fatal:
                self._fatal.append(event)
            else:
                self._normal.append(event)
                self._normal_signatures.add(signature)
            return True

    def drain(self) -> list[NotificationEvent]:
        with self._lock:
            events = [*self._fatal, *self._normal]
            self._fatal.clear()
            self._normal.clear()
            self._normal_signatures.clear()
            return events


__all__ = ["NotificationEvent", "NotificationMediaQueue"]
