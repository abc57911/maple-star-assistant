from __future__ import annotations

from collections import deque


class BoundedConsoleBuffer:
    def __init__(self, *, capacity: int = 1000) -> None:
        self._lines: deque[str] = deque(maxlen=max(1, capacity))
        self.dropped_count = 0

    def append(self, text: str) -> None:
        for line in text.splitlines() or [text]:
            if len(self._lines) == self._lines.maxlen:
                self.dropped_count += 1
            self._lines.append(line)

    def drain(self) -> list[str]:
        result = list(self._lines)
        self._lines.clear()
        return result


__all__ = ["BoundedConsoleBuffer"]
