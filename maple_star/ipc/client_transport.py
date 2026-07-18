from __future__ import annotations

from collections import deque
from threading import Lock

from .mailbox import BoundedFifo, LatestWinsMailbox


class ClientTransport:
    def __init__(self, *, command_capacity: int, snapshot_keys: int, console_capacity: int) -> None:
        if console_capacity < 1:
            raise ValueError("console_capacity must be positive")
        self._commands = BoundedFifo[object](maxsize=command_capacity)
        self._snapshots = LatestWinsMailbox[str, object](max_keys=snapshot_keys)
        self._console: deque[str] = deque()
        self._console_capacity = console_capacity
        self._console_lock = Lock()
        self.console_dropped_count = 0

    @property
    def command_dropped_count(self) -> int:
        return self._commands.dropped_count

    def enqueue_command(self, command: object) -> bool:
        return self._commands.put(command)

    def drain_commands(self, *, limit: int | None = None) -> list[object]:
        return self._commands.drain(limit=limit)

    def publish_snapshot(self, producer: str, snapshot: object) -> None:
        self._snapshots.put(producer, snapshot)

    def drain_snapshots(self) -> list[tuple[str, object]]:
        return self._snapshots.drain()

    def publish_console(self, message: str) -> None:
        with self._console_lock:
            if len(self._console) >= self._console_capacity:
                self._console.popleft()
                self.console_dropped_count += 1
            self._console.append(message)

    def drain_console(self, *, limit: int | None = None) -> list[str]:
        with self._console_lock:
            count = len(self._console) if limit is None else min(max(0, limit), len(self._console))
            return [self._console.popleft() for _ in range(count)]


__all__ = ["ClientTransport"]
