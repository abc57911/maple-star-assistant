from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class JobSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class CallableJob(QRunnable):
    def __init__(self, callback: Callable[[], object]) -> None:
        super().__init__()
        self._callback = callback
        self.signals = JobSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._callback()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)


__all__ = ["CallableJob", "JobSignals"]
