from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path
from unittest.mock import Mock

from maple_star.constants import AUTO_DRINK_DISABLE_HOLD_SECONDS
from maple_star.services.control_hotkey_coordinator import (
    ControlHotkeyCallbacks,
    ControlHotkeyCoordinator,
    ControlHotkeyFeatureSnapshot,
    ControlHotkeySettingsSnapshot,
    ControlHotkeyStateSnapshot,
)
from maple_star.services.control_hotkey_worker import (
    CONTROL_HOTKEY_EMERGENCY_STOP,
    CONTROL_HOTKEY_TOGGLE,
)
from maple_star.services.controller_collaborator_api import ControllerModuleAdapters


class _User32:
    def __init__(self) -> None:
        self.down: set[int] = set()

    def GetAsyncKeyState(self, vk: int) -> int:
        return 0x8000 if vk in self.down else 0

    def PeekMessageW(self, *_args) -> bool:
        return False


class _Worker:
    def __init__(self) -> None:
        self.hotkeys: dict[str, int] = {}
        self.events: list[str] = []
        self.down: dict[str, bool] = {}
        self.started = 0
        self.stopped = 0
        self.events_enabled: list[bool] = []
        self.clear_count = 0
        self.ensure_count = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def ensure_running(self) -> None:
        self.ensure_count += 1

    def update_hotkeys(self, hotkeys: dict[str, int]) -> None:
        self.hotkeys = {event: vk for event, vk in hotkeys.items() if vk}

    def drain_events(self) -> list[str]:
        events, self.events = self.events, []
        return events

    def cached_down_states(self) -> dict[str, bool]:
        return dict(self.down)

    def sync_down_states(self) -> dict[str, bool]:
        return dict(self.down)

    def clear_events(self) -> None:
        self.clear_count += 1
        self.events = []

    def set_events_enabled(self, enabled: bool) -> None:
        self.events_enabled.append(enabled)


def _adapters(clock: list[float], user32: _User32) -> ControllerModuleAdapters:
    noop = lambda *args, **kwargs: None
    return ControllerModuleAdapters(
        monotonic=lambda: clock[0],
        sleep=noop,
        thread_factory=noop,
        winmm_provider=lambda: object(),
        user32_provider=lambda: user32,
        beep=noop,
        message_beep=noop,
        play_sound=noop,
        key_down=noop,
        key_up=noop,
        tap_hotkey=noop,
        save_settings=noop,
    )


def _features(**overrides) -> ControlHotkeyFeatureSnapshot:
    values = {
        "auto_drink_enabled": False,
        "has_out_of_potion_hold": False,
        "pickup_enabled": False,
        "pickup_held_vk": 0,
        "toggle_hotkey": "F11",
        "pickup_toggle_hotkey": "F7",
    }
    values.update(overrides)
    return ControlHotkeyFeatureSnapshot(**values)


class ControlHotkeyCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = [100.0]
        self.user32 = _User32()
        self.worker = _Worker()
        self.coordinator = ControlHotkeyCoordinator(
            _adapters(self.clock, self.user32),
            worker_factory=lambda: self.worker,
            start_worker=False,
            logger=lambda _message: None,
        )
        self.allowed = [True]
        self.detecting = [False]
        self.detection_finished = [False]
        self.calls: list[str] = []
        self.callbacks = ControlHotkeyCallbacks(
            is_allowed_foreground=lambda: self.allowed[0],
            is_detecting_key=lambda: self.detecting[0],
            consume_key_detection_finished=lambda: self.detection_finished[0],
            release_pickup=lambda: self.calls.append("release_pickup"),
            release_potions=lambda: self.calls.append("release_potions"),
            discard_messages=self.coordinator.discard_messages,
            sync_down_states=self.coordinator.sync_down_states,
            dispatch_event=lambda event, _now: self.coordinator.dispatch_event(
                event, self.clock[0], _features(), self.callbacks
            ),
            emergency_stop=lambda: self.calls.append("emergency"),
            toggle_auto_drink=lambda: self.calls.append("toggle"),
            toggle_experience=lambda: self.calls.append("experience"),
            reset_experience=lambda: self.calls.append("reset"),
            toggle_pickup=lambda: self.calls.append("pickup"),
            toggle_minimap=lambda: self.calls.append("minimap"),
        )

    def test_module_does_not_import_controller_or_gui(self) -> None:
        path = Path(__file__).resolve().parents[1] / "maple_star" / "services" / "control_hotkey_coordinator.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        self.assertNotIn("controllers", imports)
        self.assertNotIn("gui", imports)

    def test_contract_snapshots_are_immutable(self) -> None:
        for contract in (
            ControlHotkeySettingsSnapshot,
            ControlHotkeyFeatureSnapshot,
            ControlHotkeyCallbacks,
            ControlHotkeyStateSnapshot,
        ):
            self.assertTrue(contract.__dataclass_params__.frozen)

    def test_coordinator_owns_worker_lifecycle(self) -> None:
        worker = _Worker()
        coordinator = ControlHotkeyCoordinator(
            _adapters(self.clock, self.user32),
            worker_factory=lambda: worker,
        )

        coordinator.close()
        coordinator.close()

        self.assertEqual(worker.started, 1)
        self.assertEqual(worker.stopped, 1)

    def test_poll_after_close_cannot_restart_worker(self) -> None:
        self.worker.events = [CONTROL_HOTKEY_TOGGLE]

        self.coordinator.close()
        self.coordinator.poll(_features(), self.callbacks)

        self.assertEqual(self.worker.ensure_count, 0)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.coordinator.enabled)

    def test_close_retries_worker_stop_after_failure(self) -> None:
        attempts = [RuntimeError("stop failed"), None]
        self.worker.stop = Mock(side_effect=attempts)

        with self.assertRaises(RuntimeError):
            self.coordinator.close()
        self.coordinator.close()
        self.coordinator.close()

        self.assertEqual(self.worker.stop.call_count, 2)

    def test_sync_hotkeys_normalizes_fallbacks_and_updates_worker(self) -> None:
        mapping = {"F11": 11, "Pause": 19, "F10": 10, "F9": 9, "F7": 7}
        settings = ControlHotkeySettingsSnapshot("bad", "Pause", "F10", "F9", "F7", None)

        def parse_vk(name: str) -> int:
            try:
                return mapping[name]
            except KeyError as exc:
                raise ValueError(name) from exc

        self.coordinator.sync_hotkeys(settings, parse_vk)

        self.assertEqual(self.coordinator.registered_toggle_hotkey_vk, 11)
        self.assertEqual(self.worker.hotkeys[CONTROL_HOTKEY_TOGGLE], 11)

    def test_worker_events_dispatch_in_order(self) -> None:
        self.worker.events = [CONTROL_HOTKEY_EMERGENCY_STOP, CONTROL_HOTKEY_TOGGLE]

        self.coordinator.poll(_features(), self.callbacks)

        self.assertEqual(self.calls, ["emergency", "toggle"])

    def test_outside_foreground_suspends_events_and_clears_holds(self) -> None:
        self.allowed[0] = False
        self.worker.events = [CONTROL_HOTKEY_TOGGLE]
        self.coordinator.auto_drink_disable_hold_started_at = 99.0

        self.coordinator.poll(_features(), self.callbacks)

        self.assertEqual(self.worker.events_enabled, [False])
        self.assertEqual(self.coordinator.auto_drink_disable_hold_started_at, -999.0)

    def test_key_capture_releases_actions_and_clears_down_state(self) -> None:
        self.detecting[0] = True
        self.coordinator.toggle_hotkey_was_down = True

        self.coordinator.poll(_features(), self.callbacks)

        self.assertEqual(self.calls, ["release_pickup", "release_potions"])
        self.assertFalse(self.coordinator.toggle_hotkey_was_down)

    def test_hold_to_disable_requires_continuous_down_state(self) -> None:
        features = _features(auto_drink_enabled=True)
        self.coordinator.try_toggle_scripts_enabled(100.0, features, self.callbacks)
        self.coordinator.toggle_hotkey_was_down = True

        self.coordinator.process_pending_auto_drink_disable(
            100.0 + AUTO_DRINK_DISABLE_HOLD_SECONDS,
            features,
            self.callbacks,
        )

        self.assertEqual(self.calls, ["toggle"])
        self.assertEqual(self.coordinator.auto_drink_disable_hold_started_at, -999.0)

    def test_toggle_debounce_does_not_dispatch_twice(self) -> None:
        self.coordinator.try_toggle_scripts_enabled(100.0, _features(), self.callbacks)
        self.coordinator.try_toggle_scripts_enabled(100.01, _features(), self.callbacks)

        self.assertEqual(self.calls, ["toggle"])

    def test_snapshot_reports_owned_state(self) -> None:
        self.coordinator.register_hotkeys(11, 19, 10, 9, 7, 0)
        self.coordinator.toggle_hotkey_was_down = True

        snapshot = self.coordinator.snapshot()

        self.assertIn((CONTROL_HOTKEY_TOGGLE, 11), snapshot.registered_vks)
        self.assertIn((CONTROL_HOTKEY_TOGGLE, True), snapshot.down_states)


if __name__ == "__main__":
    unittest.main()
