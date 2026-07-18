from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class BackendReceiverThread(QThread):
    batch_ready = Signal(list)

    def __init__(self, *, poll: Callable[[], list[object]], poll_interval_ms: int = 10) -> None:
        super().__init__()
        self._poll = poll
        self._poll_interval_ms = max(1, poll_interval_ms)

    def run(self) -> None:
        while not self.isInterruptionRequested():
            batch = self._poll()
            if batch:
                self.batch_ready.emit(batch)
            self.msleep(self._poll_interval_ms)

    def close(self, *, timeout_ms: int = 2000) -> bool:
        self.requestInterruption()
        return self.wait(max(0, timeout_ms))


class BackendSenderThread(QThread):
    send_failed = Signal(str)

    def __init__(self, *, flush: Callable[[], None], poll_interval_ms: int = 5) -> None:
        super().__init__()
        self._flush = flush
        self._poll_interval_ms = max(1, poll_interval_ms)

    def run(self) -> None:
        while not self.isInterruptionRequested():
            try:
                self._flush()
            except Exception as exc:
                self.send_failed.emit(str(exc))
            self.msleep(self._poll_interval_ms)

    def close(self, *, timeout_ms: int = 2000) -> bool:
        self.requestInterruption()
        return self.wait(max(0, timeout_ms))


__all__ = ["BackendReceiverThread", "BackendSenderThread"]
