from __future__ import annotations

from typing import Protocol


class SafetyPort(Protocol):
    def fatal_stop(self, reason: str) -> None: ...


__all__ = ["SafetyPort"]
