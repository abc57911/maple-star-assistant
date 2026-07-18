from __future__ import annotations

from typing import Protocol


class BackendClientPort(Protocol):
    def enqueue_command(self, command: object) -> bool: ...

    def drain_snapshots(self) -> list[tuple[str, object]]: ...

    def drain_console(self) -> list[str]: ...


__all__ = ["BackendClientPort"]
