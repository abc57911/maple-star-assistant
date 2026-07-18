from __future__ import annotations

from threading import Lock


class LatestDeviceState:
    def __init__(self) -> None:
        self._state: object | None = None
        self._lock = Lock()
        self.replaced_count = 0

    def publish(self, state: object) -> None:
        with self._lock:
            if self._state is not None:
                self.replaced_count += 1
            self._state = state

    def take(self) -> object | None:
        with self._lock:
            state = self._state
            self._state = None
            return state


__all__ = ["LatestDeviceState"]
