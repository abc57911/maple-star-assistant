from __future__ import annotations

import time
from pathlib import Path

from ..services.controller_collaborator_api import RuntimeMediaSink, ToggleBeepPattern
from ..services.runtime_api import (
    ExperienceControl,
    InlineExecutor,
    PotionControl,
    Shutdown,
    _experience_status_signature,
    _potion_status_signature,
)
from ..services.runtime_processes import (
    STATUS_HEARTBEAT_SECONDS,
    HeadlessRuntimeGui,
    _drain_queue,
    _experience_status,
    _handle_experience_command,
    _handle_potion_command,
    _is_target_hwnd_active,
    _potion_status,
    _report_worker_crash,
    _run_child_cleanup_step,
    _settings_from_payload,
)


class _PotionRuntimeMediaSink(RuntimeMediaSink):
    def __init__(self, gui: HeadlessRuntimeGui) -> None:
        self._gui = gui

    def play_media(self, path: Path, alias: str) -> None:
        self._gui.queue_media_sound(str(alias))

    def play_toggle_beep(self, pattern: ToggleBeepPattern) -> None:
        return


class _NullRuntimeMediaSink(RuntimeMediaSink):
    def play_media(self, path: Path, alias: str) -> None:
        return

    def play_toggle_beep(self, pattern: ToggleBeepPattern) -> None:
        return


def run_potion_runtime_process(
    command_queue,
    status_queue,
    settings_payload: dict[str, object],
    target_hwnd: int,
) -> None:
    controller = None
    try:
        from .auto_potion_factory import _create_auto_potion_controller

        settings = _settings_from_payload(settings_payload)
        settings.exp_efficiency_enabled = False
        target_state = {"hwnd": int(target_hwnd or 0)}
        gui = HeadlessRuntimeGui(settings)
        controller = _create_auto_potion_controller(
            lambda: _is_target_hwnd_active(target_state["hwnd"]),
            settings=settings,
            target_window_provider=lambda: target_state["hwnd"],
            gui=gui,
            start_control_hotkey_worker=False,
            start_potion_action_worker=False,
            experience_executor=InlineExecutor(),
            runtime_processes_enabled=False,
            save_settings_on_cleanup=False,
            media_sink=_PotionRuntimeMediaSink(gui),
        )
        controller._save_settings_when_idle = lambda _now: None
        next_status_at = 0.0
        next_heartbeat_at = 0.0
        last_status_signature: tuple[object, ...] | None = None
        generation = 0
        shutdown = False
        while not shutdown:
            for command in _drain_queue(command_queue, 128):
                if isinstance(command, Shutdown):
                    shutdown = True
                    break
                if isinstance(command, PotionControl):
                    generation = int(command.generation or 0)
                _handle_potion_command(controller, gui, target_state, command)
            now = time.monotonic()
            if not shutdown:
                controller.update(now, pump_gui=False)
                if now >= next_status_at:
                    status = _potion_status(controller, gui, generation)
                    signature = _potion_status_signature(status)
                    urgent = bool(status.notice or status.console_lines or status.media_sound_aliases)
                    if urgent or signature != last_status_signature or now >= next_heartbeat_at:
                        status_queue.put(status)
                        last_status_signature = signature
                        next_heartbeat_at = now + STATUS_HEARTBEAT_SECONDS
                    next_status_at = now + 0.10
            time.sleep(0.01)
    except Exception as exc:
        _report_worker_crash(status_queue, "potion", exc)
    finally:
        if controller is not None:
            _run_child_cleanup_step("potion", "release potion keys", controller._release_all_potion_keys)
            _run_child_cleanup_step("potion", "controller", controller.cleanup)


def run_experience_stats_process(
    command_queue,
    status_queue,
    settings_payload: dict[str, object],
    target_hwnd: int,
) -> None:
    controller = None
    try:
        from .auto_potion_factory import _create_auto_potion_controller

        settings = _settings_from_payload(settings_payload)
        target_state = {"hwnd": int(target_hwnd or 0)}
        gui = HeadlessRuntimeGui(settings)
        controller = _create_auto_potion_controller(
            lambda: _is_target_hwnd_active(target_state["hwnd"]),
            settings=settings,
            target_window_provider=lambda: target_state["hwnd"],
            gui=gui,
            start_control_hotkey_worker=False,
            start_potion_action_worker=False,
            experience_executor=InlineExecutor(),
            runtime_processes_enabled=False,
            save_settings_on_cleanup=False,
            experience_only_runtime=True,
            media_sink=_NullRuntimeMediaSink(),
        )
        controller.auto_drink_enabled = False
        controller._save_settings_when_idle = lambda _now: None
        next_status_at = 0.0
        next_heartbeat_at = 0.0
        last_status_signature: tuple[object, ...] | None = None
        generation = 0
        shutdown = False
        while not shutdown:
            for command in _drain_queue(command_queue, 128):
                if isinstance(command, Shutdown):
                    shutdown = True
                    break
                if isinstance(command, ExperienceControl):
                    generation = int(command.generation or 0)
                _handle_experience_command(controller, target_state, command)
            now = time.monotonic()
            if not shutdown:
                controller.update(now, pump_gui=False)
                if now >= next_status_at:
                    status = _experience_status(gui, generation)
                    signature = _experience_status_signature(status)
                    if signature != last_status_signature or now >= next_heartbeat_at:
                        status_queue.put(status)
                        last_status_signature = signature
                        next_heartbeat_at = now + STATUS_HEARTBEAT_SECONDS
                    next_status_at = now + 0.20
            time.sleep(0.01)
    except Exception as exc:
        _report_worker_crash(status_queue, "experience", exc)
    finally:
        if controller is not None:
            _run_child_cleanup_step(
                "experience",
                "cancel baseline calibration",
                lambda: controller._cancel_experience_baseline_calibration(close_ui=True),
            )
            _run_child_cleanup_step("experience", "controller", controller.cleanup)


__all__ = [
    "run_experience_stats_process",
    "run_potion_runtime_process",
]
