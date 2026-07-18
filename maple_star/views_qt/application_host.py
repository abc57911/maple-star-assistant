from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget


WINDOW_INTERACTION_TICK_SECONDS = 0.05


class QtApplicationHost:
    """Owns the Qt tick timer and guarantees a single shutdown transition."""

    def __init__(
        self,
        application: QApplication,
        window: QWidget,
        *,
        tick: Callable[[], None],
        interval_seconds: float,
    ) -> None:
        self.application = application
        self.window = window
        self._tick = tick
        self._interval = max(0.001, float(interval_seconds))
        self._next_deadline = 0.0
        self._closing = False
        self._timer = QTimer(window)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_tick)

    @property
    def closing(self) -> bool:
        return self._closing

    def run(self) -> int:
        self.window.show()
        self._next_deadline = time.monotonic()
        self._schedule()
        return self.application.exec()

    def request_quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self.application.quit()

    def _run_tick(self) -> None:
        if self._closing:
            return
        self._tick()
        if self._closing:
            return
        now = time.monotonic()
        self._next_deadline += self._interval
        if self._next_deadline <= now:
            skipped = int((now - self._next_deadline) // self._interval) + 1
            self._next_deadline += skipped * self._interval
        self._schedule()

    def _schedule(self) -> None:
        delay_ms = self._schedule_delay_ms()
        self._timer.start(delay_ms)

    def _schedule_delay_ms(self) -> int:
        delay_ms = max(0, round((self._next_deadline - time.monotonic()) * 1000.0))
        interaction_active = getattr(self.window, "is_window_interaction_active", None)
        if callable(interaction_active) and interaction_active():
            delay_ms = max(delay_ms, round(WINDOW_INTERACTION_TICK_SECONDS * 1000.0))
        return delay_ms


__all__ = ["QtApplicationHost", "WINDOW_INTERACTION_TICK_SECONDS"]
