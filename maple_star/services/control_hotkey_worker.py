from __future__ import annotations

import ctypes
import queue
import threading
import time
from dataclasses import dataclass, field

from ..constants import ASYNC_KEY_DOWN_MASK, PM_REMOVE, WM_HOTKEY
from ..adapters.win_input import Msg, user32

CONTROL_HOTKEY_TOGGLE = "toggle"
CONTROL_HOTKEY_EMERGENCY_STOP = "emergency_stop"
CONTROL_HOTKEY_EXPERIENCE_TOGGLE = "experience_toggle"
CONTROL_HOTKEY_EXPERIENCE_RESET = "experience_reset"
CONTROL_HOTKEY_PICKUP_TOGGLE = "pickup_toggle"
CONTROL_HOTKEY_POLL_INTERVAL_SECONDS = 0.01
CONTROL_HOTKEY_EVENT_SUPPRESS_SECONDS = 1.50
CONTROL_HOTKEY_REGISTER_BASE_ID = 0x6D5300
MOD_NOREPEAT = 0x4000

CONTROL_HOTKEY_IDS = {
    CONTROL_HOTKEY_TOGGLE: CONTROL_HOTKEY_REGISTER_BASE_ID + 1,
    CONTROL_HOTKEY_EMERGENCY_STOP: CONTROL_HOTKEY_REGISTER_BASE_ID + 2,
    CONTROL_HOTKEY_EXPERIENCE_TOGGLE: CONTROL_HOTKEY_REGISTER_BASE_ID + 3,
    CONTROL_HOTKEY_EXPERIENCE_RESET: CONTROL_HOTKEY_REGISTER_BASE_ID + 4,
    CONTROL_HOTKEY_PICKUP_TOGGLE: CONTROL_HOTKEY_REGISTER_BASE_ID + 5,
}


@dataclass
class ControlHotkeyWorker:
    event_queue: queue.SimpleQueue[str] = field(default_factory=queue.SimpleQueue)
    poll_interval_seconds: float = CONTROL_HOTKEY_POLL_INTERVAL_SECONDS
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _hotkeys: dict[str, int] = field(default_factory=dict)
    _down: dict[str, bool] = field(default_factory=dict)
    _registered_hotkeys: dict[int, str] = field(default_factory=dict)
    _registered_vk_by_event: dict[str, int] = field(default_factory=dict)
    _registration_attempt_vk_by_event: dict[str, int] = field(default_factory=dict)
    _last_emitted_at: dict[str, float] = field(default_factory=dict)
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

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_running(self) -> None:
        if not self.is_alive():
            self.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._registered_hotkeys = {}
        self._registered_vk_by_event = {}
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
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    hotkeys = dict(self._hotkeys)
                    previous_down = dict(self._down)

                self._sync_registered_hotkeys(hotkeys)
                emitted_events = set(self._drain_registered_hotkey_messages())

                next_down: dict[str, bool] = {}
                for event, vk in hotkeys.items():
                    is_down = _is_key_down(vk)
                    next_down[event] = is_down
                    if is_down and not previous_down.get(event, False) and event not in emitted_events:
                        self._emit_event(event)
                        emitted_events.add(event)

                with self._lock:
                    self._down = next_down
                time.sleep(self.poll_interval_seconds)
        finally:
            self._unregister_all_hotkeys()

    def _sync_registered_hotkeys(self, hotkeys: dict[str, int]) -> None:
        desired = {event: vk for event, vk in hotkeys.items() if event in CONTROL_HOTKEY_IDS and vk}
        if desired == self._registration_attempt_vk_by_event:
            return

        self._unregister_all_hotkeys(clear_attempt=False)
        registered_hotkeys: dict[int, str] = {}
        registered_vk_by_event: dict[str, int] = {}
        for event, vk in desired.items():
            hotkey_id = CONTROL_HOTKEY_IDS[event]
            if user32.RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, vk):
                registered_hotkeys[hotkey_id] = event
                registered_vk_by_event[event] = vk
        self._registered_hotkeys = registered_hotkeys
        self._registered_vk_by_event = registered_vk_by_event
        self._registration_attempt_vk_by_event = desired

    def _unregister_all_hotkeys(self, *, clear_attempt: bool = True) -> None:
        for hotkey_id in list(self._registered_hotkeys):
            user32.UnregisterHotKey(None, hotkey_id)
        self._registered_hotkeys = {}
        self._registered_vk_by_event = {}
        if clear_attempt:
            self._registration_attempt_vk_by_event = {}

    def _drain_registered_hotkey_messages(self) -> list[str]:
        events: list[str] = []
        message = Msg()
        while user32.PeekMessageW(ctypes.byref(message), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
            event = self._registered_hotkeys.get(int(message.wParam))
            if event is None:
                continue
            if self._emit_event(event):
                events.append(event)
        return events

    def _emit_event(self, event: str) -> bool:
        now = time.monotonic()
        previous_at = self._last_emitted_at.get(event, -999.0)
        if now - previous_at < CONTROL_HOTKEY_EVENT_SUPPRESS_SECONDS:
            return False
        self._last_emitted_at[event] = now
        self.event_queue.put(event)
        return True


def _is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & ASYNC_KEY_DOWN_MASK)
