from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

from ..constants import ASYNC_KEY_DOWN_MASK
from ..adapters.win_input import user32

CONTROL_HOTKEY_TOGGLE = "toggle"
CONTROL_HOTKEY_EMERGENCY_STOP = "emergency_stop"
CONTROL_HOTKEY_EXPERIENCE_TOGGLE = "experience_toggle"
CONTROL_HOTKEY_EXPERIENCE_RESET = "experience_reset"
CONTROL_HOTKEY_POLL_INTERVAL_SECONDS = 0.01


@dataclass
class ControlHotkeyWorker:
    event_queue: queue.SimpleQueue[str] = field(default_factory=queue.SimpleQueue)
    poll_interval_seconds: float = CONTROL_HOTKEY_POLL_INTERVAL_SECONDS
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _hotkeys: dict[str, int] = field(default_factory=dict)
    _down: dict[str, bool] = field(default_factory=dict)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="MapleStarControlHotkeyWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.clear_events()

    def update_hotkeys(self, hotkeys: dict[str, int]) -> None:
        normalized = {event: vk for event, vk in hotkeys.items() if vk}
        with self._lock:
            self._hotkeys = normalized
            self._down = {event: _is_key_down(vk) for event, vk in normalized.items()}
        self.clear_events()

    def clear_events(self) -> None:
        while True:
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                return

    def drain_events(self, limit: int = 32) -> list[str]:
        events: list[str] = []
        for _ in range(limit):
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def sync_down_states(self) -> dict[str, bool]:
        with self._lock:
            hotkeys = dict(self._hotkeys)
        down = {event: _is_key_down(vk) for event, vk in hotkeys.items()}
        with self._lock:
            self._down = down
        return down

    def cached_down_states(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._down)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                hotkeys = dict(self._hotkeys)
                previous_down = dict(self._down)

            next_down: dict[str, bool] = {}
            for event, vk in hotkeys.items():
                is_down = _is_key_down(vk)
                next_down[event] = is_down
                if is_down and not previous_down.get(event, False):
                    self.event_queue.put(event)

            with self._lock:
                self._down = next_down
            time.sleep(self.poll_interval_seconds)


def _is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & ASYNC_KEY_DOWN_MASK)
