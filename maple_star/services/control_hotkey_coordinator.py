from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Callable

from ..adapters.win_input import Msg
from ..constants import (
    ASYNC_KEY_DOWN_MASK,
    AUTO_DRINK_DISABLE_HOLD_SECONDS,
    AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS,
    PICKUP_DISABLE_HOLD_SECONDS,
    PICKUP_TOGGLE_DEBOUNCE_SECONDS,
    PM_REMOVE,
    SCRIPT_EMERGENCY_STOP_HOTKEY_ID,
    SCRIPT_EXPERIENCE_TOGGLE_HOTKEY_ID,
    SCRIPT_TOGGLE_HOTKEY_ID,
    TOGGLE_HOTKEY_DEBOUNCE_SECONDS,
    WM_HOTKEY,
)
from .control_hotkey_worker import (
    CONTROL_HOTKEY_EMERGENCY_STOP,
    CONTROL_HOTKEY_EXPERIENCE_RESET,
    CONTROL_HOTKEY_EXPERIENCE_TOGGLE,
    CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE,
    CONTROL_HOTKEY_PICKUP_TOGGLE,
    CONTROL_HOTKEY_TOGGLE,
    ControlHotkeyWorker,
)
from .controller_collaborator_api import ControllerModuleAdapters


POTION_TIME_EPSILON_SECONDS = 1e-9


@dataclass(frozen=True)
class ControlHotkeySettingsSnapshot:
    toggle_hotkey: str
    emergency_stop_hotkey: str
    experience_toggle_hotkey: str
    experience_reset_hotkey: str
    pickup_toggle_hotkey: str | None
    minimap_cruise_toggle_hotkey: str | None


@dataclass(frozen=True)
class ControlHotkeyFeatureSnapshot:
    auto_drink_enabled: bool
    has_out_of_potion_hold: bool
    pickup_enabled: bool
    pickup_held_vk: int
    toggle_hotkey: str
    pickup_toggle_hotkey: str | None


@dataclass(frozen=True)
class ControlHotkeyCallbacks:
    is_allowed_foreground: Callable[[], bool]
    is_detecting_key: Callable[[], bool]
    consume_key_detection_finished: Callable[[], bool]
    release_pickup: Callable[[], None]
    release_potions: Callable[[], None]
    discard_messages: Callable[[], None]
    sync_down_states: Callable[[], None]
    dispatch_event: Callable[[str, float], None]
    emergency_stop: Callable[[], None]
    toggle_auto_drink: Callable[[], None]
    toggle_experience: Callable[[], None]
    reset_experience: Callable[[], None]
    toggle_pickup: Callable[[], None]
    toggle_minimap: Callable[[], None]


@dataclass(frozen=True)
class ControlHotkeyStateSnapshot:
    registered_vks: tuple[tuple[str, int], ...]
    down_states: tuple[tuple[str, bool], ...]
    suppressed_until_release: bool
    events_enabled: bool
    auto_drink_disable_hold_started_at: float
    pickup_disable_hold_started_at: float
    last_dispatch_times: tuple[tuple[str, float], ...]


class ControlHotkeyCoordinator:
    def __init__(
        self,
        adapters: ControllerModuleAdapters,
        *,
        enabled: bool = True,
        worker_factory: Callable[[], ControlHotkeyWorker] = ControlHotkeyWorker,
        start_worker: bool = True,
        logger: Callable[[str], None] = print,
    ) -> None:
        self._adapters = adapters
        self._logger = logger
        self.enabled = enabled
        self.worker = worker_factory() if enabled else None
        if self.worker is not None and start_worker:
            self.worker.start()
        self.hotkey_registered = False
        self.emergency_hotkey_registered = False
        self.experience_toggle_hotkey_registered = False
        self.experience_reset_hotkey_registered = False
        self.pickup_toggle_hotkey_registered = False
        self.registered_toggle_hotkey_vk = 0
        self.registered_emergency_stop_hotkey_vk = 0
        self.registered_experience_toggle_hotkey_vk = 0
        self.registered_experience_reset_hotkey_vk = 0
        self.registered_pickup_toggle_hotkey_vk = 0
        self.registered_minimap_cruise_toggle_hotkey_vk = 0
        self.toggle_hotkey_was_down = False
        self.emergency_stop_hotkey_was_down = False
        self.experience_toggle_hotkey_was_down = False
        self.experience_reset_hotkey_was_down = False
        self.pickup_toggle_hotkey_was_down = False
        self.minimap_cruise_toggle_hotkey_was_down = False
        self.suppressed_until_release = False
        self.events_enabled = True
        self.last_toggle_hotkey_at = -999.0
        self.last_experience_toggle_hotkey_at = -999.0
        self.last_experience_reset_hotkey_at = -999.0
        self.last_pickup_toggle_hotkey_at = -999.0
        self.last_minimap_cruise_toggle_hotkey_at = -999.0
        self.auto_drink_disable_hold_started_at = -999.0
        self.pickup_disable_hold_started_at = -999.0
        self._closed = False

    @staticmethod
    def control_hotkey_vk(
        hotkey: str,
        fallback: str,
        parse_vk: Callable[[str], int],
    ) -> int:
        try:
            return parse_vk(hotkey)
        except ValueError:
            return parse_vk(fallback)

    @staticmethod
    def optional_control_hotkey_vk(
        hotkey: str | None,
        parse_vk: Callable[[str], int],
    ) -> int:
        if not hotkey:
            return 0
        try:
            return parse_vk(hotkey)
        except ValueError:
            return 0

    def sync_hotkeys(
        self,
        settings: ControlHotkeySettingsSnapshot,
        parse_vk: Callable[[str], int],
    ) -> None:
        hotkeys = (
            self.control_hotkey_vk(settings.toggle_hotkey, "F11", parse_vk),
            self.control_hotkey_vk(settings.emergency_stop_hotkey, "Pause", parse_vk),
            self.control_hotkey_vk(settings.experience_toggle_hotkey, "F10", parse_vk),
            self.control_hotkey_vk(settings.experience_reset_hotkey, "F9", parse_vk),
            self.optional_control_hotkey_vk(settings.pickup_toggle_hotkey, parse_vk),
            self.optional_control_hotkey_vk(settings.minimap_cruise_toggle_hotkey, parse_vk),
        )
        if hotkeys == self._registered_vk_tuple():
            return
        self.unregister_hotkeys()
        self.register_hotkeys(*hotkeys)

    def register_hotkeys(
        self,
        toggle_vk: int,
        emergency_vk: int,
        experience_vk: int,
        experience_reset_vk: int = 0,
        pickup_toggle_vk: int = 0,
        minimap_cruise_toggle_vk: int = 0,
    ) -> None:
        self.registered_toggle_hotkey_vk = toggle_vk
        self.hotkey_registered = bool(toggle_vk)
        self.registered_emergency_stop_hotkey_vk = emergency_vk
        self.emergency_hotkey_registered = bool(emergency_vk)
        self.registered_experience_toggle_hotkey_vk = experience_vk
        self.experience_toggle_hotkey_registered = bool(experience_vk)
        self.registered_experience_reset_hotkey_vk = experience_reset_vk
        self.experience_reset_hotkey_registered = bool(experience_reset_vk)
        self.registered_pickup_toggle_hotkey_vk = pickup_toggle_vk
        self.pickup_toggle_hotkey_registered = bool(pickup_toggle_vk)
        self.registered_minimap_cruise_toggle_hotkey_vk = minimap_cruise_toggle_vk
        if self.worker is not None:
            self.worker.update_hotkeys(self._worker_hotkeys())

    def unregister_hotkeys(self) -> None:
        self._clear_registration_state()
        if self.worker is not None:
            self.worker.update_hotkeys({})

    def _clear_registration_state(self) -> None:
        self.hotkey_registered = False
        self.emergency_hotkey_registered = False
        self.experience_toggle_hotkey_registered = False
        self.experience_reset_hotkey_registered = False
        self.pickup_toggle_hotkey_registered = False
        self.registered_toggle_hotkey_vk = 0
        self.registered_emergency_stop_hotkey_vk = 0
        self.registered_experience_toggle_hotkey_vk = 0
        self.registered_experience_reset_hotkey_vk = 0
        self.registered_pickup_toggle_hotkey_vk = 0
        self.registered_minimap_cruise_toggle_hotkey_vk = 0

    def poll(
        self,
        features: ControlHotkeyFeatureSnapshot,
        callbacks: ControlHotkeyCallbacks,
    ) -> None:
        if self._closed or not self.enabled:
            return
        if callbacks.is_detecting_key():
            self._clear_down_states()
            self.auto_drink_disable_hold_started_at = -999.0
            self.pickup_disable_hold_started_at = -999.0
            callbacks.release_pickup()
            callbacks.release_potions()
            self.suppressed_until_release = False
            callbacks.discard_messages()
            return
        if callbacks.consume_key_detection_finished():
            self.suppressed_until_release = True
            callbacks.release_pickup()
            callbacks.release_potions()
            callbacks.discard_messages()
            callbacks.sync_down_states()
            return
        if self.suppressed_until_release:
            callbacks.release_pickup()
            callbacks.release_potions()
            callbacks.discard_messages()
            callbacks.sync_down_states()
            if not self.any_hotkey_is_down():
                self.suppressed_until_release = False
            return

        worker_events = self._poll_worker_events()
        if worker_events is not None:
            events, has_cached_down = worker_events
            now = self._adapters.monotonic()
            if has_cached_down and not self.has_activity(events):
                self.maybe_reenable_events(callbacks.is_allowed_foreground)
                return
            if (has_cached_down or events) and not callbacks.is_allowed_foreground():
                self.suspend_outside_foreground(callbacks.is_allowed_foreground)
                return
            if has_cached_down or events:
                self.set_worker_events_enabled(True)
                self.process_pending_auto_drink_disable(now, features, callbacks)
                self.process_pending_pickup_disable(now, features, callbacks)
                for event in events:
                    callbacks.dispatch_event(event, now)
                return

        triggered = self._poll_fallback_edges()
        now = self._adapters.monotonic()
        if not any(triggered.values()) and not self.has_pending_hold():
            return
        if not callbacks.is_allowed_foreground():
            self.suspend_outside_foreground(callbacks.is_allowed_foreground)
            return
        self.set_worker_events_enabled(True)
        self.process_pending_auto_drink_disable(now, features, callbacks)
        self.process_pending_pickup_disable(now, features, callbacks)
        for event in (
            CONTROL_HOTKEY_EMERGENCY_STOP,
            CONTROL_HOTKEY_TOGGLE,
            CONTROL_HOTKEY_EXPERIENCE_TOGGLE,
            CONTROL_HOTKEY_EXPERIENCE_RESET,
            CONTROL_HOTKEY_PICKUP_TOGGLE,
            CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE,
        ):
            if triggered[event]:
                callbacks.dispatch_event(event, now)
                break

    def dispatch_event(
        self,
        event: str,
        now: float,
        features: ControlHotkeyFeatureSnapshot,
        callbacks: ControlHotkeyCallbacks,
    ) -> None:
        if event == CONTROL_HOTKEY_EMERGENCY_STOP:
            self.try_emergency_stop(now, callbacks)
        elif event == CONTROL_HOTKEY_TOGGLE:
            self.try_toggle_scripts_enabled(now, features, callbacks)
        elif event == CONTROL_HOTKEY_EXPERIENCE_TOGGLE:
            self.try_toggle_experience(now, callbacks)
        elif event == CONTROL_HOTKEY_EXPERIENCE_RESET:
            self.try_reset_experience(now, callbacks)
        elif event == CONTROL_HOTKEY_PICKUP_TOGGLE:
            self.try_toggle_pickup(now, features, callbacks)
        elif event == CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE:
            self.try_toggle_minimap(now, callbacks)

    def try_emergency_stop(self, _now: float, callbacks: ControlHotkeyCallbacks) -> None:
        if callbacks.is_allowed_foreground():
            callbacks.emergency_stop()

    def try_toggle_scripts_enabled(
        self,
        now: float,
        features: ControlHotkeyFeatureSnapshot,
        callbacks: ControlHotkeyCallbacks,
    ) -> None:
        if features.auto_drink_enabled and not features.has_out_of_potion_hold:
            if self.auto_drink_disable_hold_started_at >= 0:
                return
            if not callbacks.is_allowed_foreground():
                return
            self.auto_drink_disable_hold_started_at = now
            self._logger(
                f"自動喝水停用確認：按住 {features.toggle_hotkey} "
                f"{AUTO_DRINK_DISABLE_HOLD_SECONDS:.2f} 秒"
            )
            return
        if now - self.last_toggle_hotkey_at < AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS:
            return
        self.last_toggle_hotkey_at = now
        if callbacks.is_allowed_foreground():
            callbacks.toggle_auto_drink()

    def try_toggle_experience(self, now: float, callbacks: ControlHotkeyCallbacks) -> None:
        if now - self.last_experience_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_toggle_hotkey_at = now
        if callbacks.is_allowed_foreground():
            callbacks.toggle_experience()

    def try_reset_experience(self, now: float, callbacks: ControlHotkeyCallbacks) -> None:
        if now - self.last_experience_reset_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_reset_hotkey_at = now
        if callbacks.is_allowed_foreground():
            callbacks.reset_experience()

    def try_toggle_pickup(
        self,
        now: float,
        features: ControlHotkeyFeatureSnapshot,
        callbacks: ControlHotkeyCallbacks,
    ) -> None:
        if features.pickup_enabled:
            if self.pickup_disable_hold_started_at >= 0:
                return
            if not callbacks.is_allowed_foreground():
                return
            self.pickup_disable_hold_started_at = now
            self._logger(
                f"拾取停用確認：按住 {features.pickup_toggle_hotkey} "
                f"{PICKUP_DISABLE_HOLD_SECONDS:.2f} 秒"
            )
            return
        if now - self.last_pickup_toggle_hotkey_at < PICKUP_TOGGLE_DEBOUNCE_SECONDS:
            return
        self.last_pickup_toggle_hotkey_at = now
        if not callbacks.is_allowed_foreground():
            return
        self._logger(
            "拾取切換熱鍵："
            f"enabled={features.pickup_enabled} "
            f"held_vk={features.pickup_held_vk} "
            f"toggle_down={self.pickup_toggle_hotkey_was_down}"
        )
        callbacks.toggle_pickup()

    def try_toggle_minimap(self, now: float, callbacks: ControlHotkeyCallbacks) -> None:
        if now - self.last_minimap_cruise_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_minimap_cruise_toggle_hotkey_at = now
        if callbacks.is_allowed_foreground():
            callbacks.toggle_minimap()

    def process_pending_auto_drink_disable(
        self,
        now: float,
        features: ControlHotkeyFeatureSnapshot,
        callbacks: ControlHotkeyCallbacks,
    ) -> None:
        started_at = self.auto_drink_disable_hold_started_at
        if started_at < 0:
            return
        if not features.auto_drink_enabled or features.has_out_of_potion_hold:
            self.auto_drink_disable_hold_started_at = -999.0
            return
        if not self.toggle_hotkey_was_down:
            self.auto_drink_disable_hold_started_at = -999.0
            self._logger("自動喝水停用取消：熱鍵未持續按住")
            return
        if now - started_at + POTION_TIME_EPSILON_SECONDS < AUTO_DRINK_DISABLE_HOLD_SECONDS:
            return
        self.auto_drink_disable_hold_started_at = -999.0
        if callbacks.is_allowed_foreground():
            callbacks.toggle_auto_drink()

    def process_pending_pickup_disable(
        self,
        now: float,
        features: ControlHotkeyFeatureSnapshot,
        callbacks: ControlHotkeyCallbacks,
    ) -> None:
        started_at = self.pickup_disable_hold_started_at
        if started_at < 0:
            return
        if not features.pickup_enabled:
            self.pickup_disable_hold_started_at = -999.0
            return
        if not self.pickup_toggle_hotkey_was_down:
            self.pickup_disable_hold_started_at = -999.0
            self._logger("拾取停用取消：熱鍵未持續按住")
            return
        if now - started_at + POTION_TIME_EPSILON_SECONDS < PICKUP_DISABLE_HOLD_SECONDS:
            return
        self.pickup_disable_hold_started_at = -999.0
        if callbacks.is_allowed_foreground():
            callbacks.toggle_pickup()

    def drain_worker_events(self) -> list[str]:
        return [] if self.worker is None else self.worker.drain_events()

    def cached_worker_down_states(self) -> dict[str, bool] | None:
        if self.worker is None:
            return None
        get_down = getattr(self.worker, "cached_down_states", None)
        if not callable(get_down):
            return None
        down = get_down()
        return down if isinstance(down, dict) else None

    def sync_down_states(self) -> None:
        if self.worker is not None:
            self.apply_down_states(self.worker.sync_down_states())
            return
        user32 = self._adapters.user32_provider()
        self.apply_down_states(
            {
                event: bool(vk and user32.GetAsyncKeyState(vk) & ASYNC_KEY_DOWN_MASK)
                for event, vk in self._worker_hotkeys().items()
            }
        )

    def apply_down_states(self, down: dict[str, bool]) -> None:
        self.toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_TOGGLE, False)
        self.emergency_stop_hotkey_was_down = down.get(CONTROL_HOTKEY_EMERGENCY_STOP, False)
        self.experience_toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_EXPERIENCE_TOGGLE, False)
        self.experience_reset_hotkey_was_down = down.get(CONTROL_HOTKEY_EXPERIENCE_RESET, False)
        self.pickup_toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_PICKUP_TOGGLE, False)
        self.minimap_cruise_toggle_hotkey_was_down = down.get(
            CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE, False
        )

    def any_hotkey_is_down(self) -> bool:
        return any(self._down_states().values())

    def has_pending_hold(self) -> bool:
        return (
            self.auto_drink_disable_hold_started_at >= 0
            or self.pickup_disable_hold_started_at >= 0
        )

    def has_activity(self, events: list[str]) -> bool:
        return bool(events) or self.any_hotkey_is_down() or self.has_pending_hold()

    def discard_messages(self) -> None:
        if self.worker is not None:
            self.worker.clear_events()
        message = Msg()
        user32 = self._adapters.user32_provider()
        while user32.PeekMessageW(
            ctypes.byref(message), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE
        ):
            pass

    def set_worker_events_enabled(self, enabled: bool) -> None:
        self.events_enabled = enabled
        if self.worker is not None:
            setter = getattr(self.worker, "set_events_enabled", None)
            if callable(setter):
                setter(enabled)

    def maybe_reenable_events(self, is_allowed_foreground: Callable[[], bool]) -> None:
        if not self.events_enabled and is_allowed_foreground():
            self.set_worker_events_enabled(True)

    def suspend_outside_foreground(
        self,
        _is_allowed_foreground: Callable[[], bool] | None = None,
    ) -> None:
        self.set_worker_events_enabled(False)
        self.discard_messages()
        self.sync_down_states()
        self.auto_drink_disable_hold_started_at = -999.0
        self.pickup_disable_hold_started_at = -999.0

    def snapshot(self) -> ControlHotkeyStateSnapshot:
        return ControlHotkeyStateSnapshot(
            registered_vks=tuple(self._worker_hotkeys().items()),
            down_states=tuple(self._down_states().items()),
            suppressed_until_release=self.suppressed_until_release,
            events_enabled=self.events_enabled,
            auto_drink_disable_hold_started_at=self.auto_drink_disable_hold_started_at,
            pickup_disable_hold_started_at=self.pickup_disable_hold_started_at,
            last_dispatch_times=(
                (CONTROL_HOTKEY_TOGGLE, self.last_toggle_hotkey_at),
                (CONTROL_HOTKEY_EXPERIENCE_TOGGLE, self.last_experience_toggle_hotkey_at),
                (CONTROL_HOTKEY_EXPERIENCE_RESET, self.last_experience_reset_hotkey_at),
                (CONTROL_HOTKEY_PICKUP_TOGGLE, self.last_pickup_toggle_hotkey_at),
                (CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE, self.last_minimap_cruise_toggle_hotkey_at),
            ),
        )

    def close(self) -> None:
        if self._closed:
            return
        self.enabled = False
        self._clear_registration_state()
        self._clear_down_states()
        self.suppressed_until_release = False
        self.events_enabled = False
        self.auto_drink_disable_hold_started_at = -999.0
        self.pickup_disable_hold_started_at = -999.0
        if self.worker is not None:
            self.worker.stop()
        self._closed = True

    def _poll_worker_events(self) -> tuple[list[str], bool] | None:
        if self.worker is None:
            return None
        ensure_running = getattr(self.worker, "ensure_running", None)
        if callable(ensure_running):
            ensure_running()
        events = self.drain_worker_events()
        down = self.cached_worker_down_states()
        if down is not None:
            self.apply_down_states(down)
        return events, down is not None

    def _poll_fallback_edges(self) -> dict[str, bool]:
        triggered = {event: False for event in self._worker_hotkeys()}
        message = Msg()
        user32 = self._adapters.user32_provider()
        while user32.PeekMessageW(
            ctypes.byref(message), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE
        ):
            if message.wParam == SCRIPT_TOGGLE_HOTKEY_ID:
                triggered[CONTROL_HOTKEY_TOGGLE] = True
            elif message.wParam == SCRIPT_EMERGENCY_STOP_HOTKEY_ID:
                triggered[CONTROL_HOTKEY_EMERGENCY_STOP] = True
            elif message.wParam == SCRIPT_EXPERIENCE_TOGGLE_HOTKEY_ID:
                triggered[CONTROL_HOTKEY_EXPERIENCE_TOGGLE] = True
        previous = self._down_states()
        down = {
            event: bool(vk and user32.GetAsyncKeyState(vk) & ASYNC_KEY_DOWN_MASK)
            for event, vk in self._worker_hotkeys().items()
        }
        for event, is_down in down.items():
            if is_down and not previous[event]:
                triggered[event] = True
        self.apply_down_states(down)
        return triggered

    def _registered_vk_tuple(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.registered_toggle_hotkey_vk,
            self.registered_emergency_stop_hotkey_vk,
            self.registered_experience_toggle_hotkey_vk,
            self.registered_experience_reset_hotkey_vk,
            self.registered_pickup_toggle_hotkey_vk,
            self.registered_minimap_cruise_toggle_hotkey_vk,
        )

    def _worker_hotkeys(self) -> dict[str, int]:
        return {
            CONTROL_HOTKEY_TOGGLE: self.registered_toggle_hotkey_vk,
            CONTROL_HOTKEY_EMERGENCY_STOP: self.registered_emergency_stop_hotkey_vk,
            CONTROL_HOTKEY_EXPERIENCE_TOGGLE: self.registered_experience_toggle_hotkey_vk,
            CONTROL_HOTKEY_EXPERIENCE_RESET: self.registered_experience_reset_hotkey_vk,
            CONTROL_HOTKEY_PICKUP_TOGGLE: self.registered_pickup_toggle_hotkey_vk,
            CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE: self.registered_minimap_cruise_toggle_hotkey_vk,
        }

    def _down_states(self) -> dict[str, bool]:
        return {
            CONTROL_HOTKEY_TOGGLE: self.toggle_hotkey_was_down,
            CONTROL_HOTKEY_EMERGENCY_STOP: self.emergency_stop_hotkey_was_down,
            CONTROL_HOTKEY_EXPERIENCE_TOGGLE: self.experience_toggle_hotkey_was_down,
            CONTROL_HOTKEY_EXPERIENCE_RESET: self.experience_reset_hotkey_was_down,
            CONTROL_HOTKEY_PICKUP_TOGGLE: self.pickup_toggle_hotkey_was_down,
            CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE: self.minimap_cruise_toggle_hotkey_was_down,
        }

    def _clear_down_states(self) -> None:
        self.apply_down_states({})


__all__ = [
    "ControlHotkeyCallbacks",
    "ControlHotkeyCoordinator",
    "ControlHotkeyFeatureSnapshot",
    "ControlHotkeySettingsSnapshot",
    "ControlHotkeyStateSnapshot",
]
