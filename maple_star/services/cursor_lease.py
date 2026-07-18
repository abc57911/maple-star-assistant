from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CursorMutationPort(Protocol):
    def get_cursor_position(self) -> tuple[int, int]: ...

    def set_cursor_position(self, x: int, y: int) -> None: ...


@dataclass(frozen=True, slots=True)
class CursorLease:
    token: int
    owner: str
    original_position: tuple[int, int]
    expires_at: float


class CursorLeaseManager:
    def __init__(self, cursor: CursorMutationPort) -> None:
        self._cursor = cursor
        self._next_token = 1
        self.active: CursorLease | None = None

    def acquire(self, *, owner: str, now: float, timeout: float) -> CursorLease:
        if self.active is not None:
            raise RuntimeError("cursor lease is already active")
        if not owner or timeout <= 0.0:
            raise ValueError("cursor lease requires an owner and positive timeout")
        lease = CursorLease(self._next_token, owner, self._cursor.get_cursor_position(), now + timeout)
        self._next_token += 1
        self.active = lease
        return lease

    def move(self, token: int, position: tuple[int, int]) -> bool:
        if self.active is None or self.active.token != token:
            return False
        self._cursor.set_cursor_position(*position)
        return True

    def release(self, token: int) -> bool:
        if self.active is None or self.active.token != token:
            return False
        lease = self.active
        self._cursor.set_cursor_position(*lease.original_position)
        self.active = None
        return True

    def expire(self, *, now: float) -> bool:
        return bool(self.active is not None and now > self.active.expires_at and self.release(self.active.token))

    def terminal_restore(self) -> bool:
        return bool(self.active is not None and self.release(self.active.token))


__all__ = ["CursorLease", "CursorLeaseManager", "CursorMutationPort"]
