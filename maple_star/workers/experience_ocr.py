from __future__ import annotations

from typing import Protocol


class CursorLeasePort(Protocol):
    def acquire(self, owner: str, now: float, timeout: float) -> int: ...

    def move(self, token: int, position: tuple[int, int]) -> bool: ...

    def release(self, token: int) -> bool: ...


class ExperienceCursorTransaction:
    def __init__(self, port: CursorLeasePort, *, now: float, timeout: float) -> None:
        self._port = port
        self._token = port.acquire("ocr", now, timeout)
        self._closed = False

    def move(self, position: tuple[int, int]) -> bool:
        if self._closed:
            return False
        return self._port.move(self._token, position)

    def close(self) -> bool:
        if self._closed:
            return False
        self._closed = True
        return self._port.release(self._token)

    def __enter__(self) -> "ExperienceCursorTransaction":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


__all__ = ["CursorLeasePort", "ExperienceCursorTransaction"]
