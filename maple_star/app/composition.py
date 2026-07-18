from __future__ import annotations

from collections.abc import Callable


class ShutdownOnce:
    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._done = False

    def __call__(self) -> None:
        if self._done:
            return
        self._done = True
        self._callback()


__all__ = ["ShutdownOnce"]
