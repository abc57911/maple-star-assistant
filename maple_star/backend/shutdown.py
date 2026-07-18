from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShutdownFailure:
    step: str
    message: str


class OrderedShutdown:
    def __init__(
        self,
        *,
        stop_commands: Callable[[], None],
        safety_release: Callable[[], None],
        stop_workers: Callable[[], None],
        close_transport: Callable[[], None],
        confirm_children: Callable[[], None],
    ) -> None:
        self._steps = (
            ("stop_commands", stop_commands),
            ("safety_release", safety_release),
            ("stop_workers", stop_workers),
            ("close_transport", close_transport),
            ("confirm_children", confirm_children),
        )
        self._result: list[ShutdownFailure] | None = None

    def run(self) -> list[ShutdownFailure]:
        if self._result is not None:
            return self._result
        failures: list[ShutdownFailure] = []
        for name, callback in self._steps:
            try:
                callback()
            except Exception as exc:
                failures.append(ShutdownFailure(name, str(exc)))
        self._result = failures
        return failures


__all__ = ["OrderedShutdown", "ShutdownFailure"]
