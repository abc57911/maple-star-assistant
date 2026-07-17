from __future__ import annotations

import multiprocessing as mp
import queue
import time
from dataclasses import fields
from typing import Any, Callable

from ..adapters.debug_logging import log_exception
from ..adapters.win_input import foreground_window_handle, is_valid_window, is_window_minimized, window_ancestor_handles
from ..adapters.window_target import is_target_window
from ..constants import DEFAULT_CAPTURE_INTERVAL_SECONDS
from ..models.experience import ExperienceSnapshot
from ..models.settings import AutoPotionSettings
from .runtime_api import (
    ControlCommand,
    ControlStatus,
    ExperienceControl,
    ExperienceStatus,
    InlineExecutor,
    PotionControl,
    PotionStatus,
    SettingsUpdated,
    Shutdown,
    TargetWindowUpdated,
    WorkerCrashed,
    _experience_status_signature,
    _potion_status_signature,
    control_status_signature,
)

STATUS_HEARTBEAT_SECONDS = 1.0
CONTROL_QUEUE_MAXSIZE = 256


class HeadlessRuntimeGui:
    closed = False

    def __init__(self, settings: AutoPotionSettings) -> None:
        self.settings = settings
        self.hp_percent: float | None = None
        self.mp_percent: float | None = None
        self.hp_debug = "--"
        self.mp_debug = "--"
        self.status = ""
        self.notice = ""
        self.media_sound_aliases: list[str] = []
        self.experience_snapshot = ExperienceSnapshot(status="已停用")
        self.console_lines: list[str] = []

    def exists(self) -> bool:
        return True

    def pump(self) -> bool:
        return True

    def sync_after_event_processing(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    def set_bar_preview_provider(self, _provider) -> None:
        return

    def set_experience_reset_handler(self, _handler) -> None:
        return

    def set_current_percentages(self, hp_percent: float | None, mp_percent: float | None) -> None:
        self.hp_percent = hp_percent
        self.mp_percent = mp_percent

    def set_bar_detection_debug(self, hp_debug: str, mp_debug: str) -> None:
        self.hp_debug = hp_debug
        self.mp_debug = mp_debug

    def set_status(self, message: str) -> None:
        self.status = message

    def show_toggle_notice(self, message: str) -> None:
        self.notice = message

    def consume_notice(self) -> str:
        notice = self.notice
        self.notice = ""
        return notice

    def queue_media_sound(self, alias: str) -> None:
        self.media_sound_aliases.append(alias)

    def consume_media_sound_aliases(self) -> tuple[str, ...]:
        aliases = tuple(self.media_sound_aliases)
        self.media_sound_aliases.clear()
        return aliases

    def refresh_bar_preview_once(self) -> None:
        return

    def set_experience_snapshot(self, snapshot: ExperienceSnapshot) -> None:
        self.experience_snapshot = snapshot

    def set_exp_efficiency_enabled(self, enabled: bool) -> None:
        self.settings.exp_efficiency_enabled = enabled

    def is_detecting_key(self) -> bool:
        return False

    def consume_key_detection_finished(self) -> bool:
        return False

    def is_key_detection_release_pending(self) -> bool:
        return False

    def is_window_interaction_active(self) -> bool:
        return False

    def consume_console_lines(self) -> tuple[str, ...]:
        lines = tuple(self.console_lines)
        self.console_lines.clear()
        return lines


class RuntimeProcessCoordinator:
    def __init__(
        self,
        settings: AutoPotionSettings,
        target_hwnd: int = 0,
        *,
        potion_worker_target: Callable[..., None],
        experience_worker_target: Callable[..., None],
    ) -> None:
        self._ctx = mp.get_context("spawn")
        self._potion_worker_target = potion_worker_target
        self._experience_worker_target = experience_worker_target
        self._potion_commands = self._ctx.Queue()
        self._potion_statuses = self._ctx.Queue()
        self._experience_commands = self._ctx.Queue()
        self._experience_statuses = self._ctx.Queue()
        self._control_commands = self._ctx.Queue(maxsize=CONTROL_QUEUE_MAXSIZE)
        self._control_statuses = self._ctx.Queue(maxsize=CONTROL_QUEUE_MAXSIZE)
        self._control_release_event = self._ctx.Event()
        self._settings_payload = settings.to_json_dict()
        self._target_hwnd = int(target_hwnd or 0)
        self._potion_process = self._new_potion_process()
        self._experience_process = self._ctx.Process(
            target=self._experience_worker_target,
            args=(self._experience_commands, self._experience_statuses, self._settings_payload, self._target_hwnd),
            name="MapleStarExperienceStats",
            daemon=True,
        )
        self._started = False
        self._stopped = False
        self._control_process: mp.Process | None = None
        self._pending_control_command: ControlCommand | None = None
        self._pending_control_settings: SettingsUpdated | None = None
        self._pending_control_target: TargetWindowUpdated | None = None

    def _new_potion_process(self) -> mp.Process:
        return self._ctx.Process(
            target=self._potion_worker_target,
            args=(self._potion_commands, self._potion_statuses, self._settings_payload, self._target_hwnd),
            name="MapleStarPotionRuntime",
            daemon=True,
        )

    def start(self) -> None:
        if self._started:
            return
        if self._stopped:
            raise RuntimeError("runtime processes already stopped")
        self._started = True
        try:
            self._potion_process.start()
            self._experience_process.start()
        except BaseException:
            self.stop()
            raise

    def start_control(self, worker_target, *worker_args: object) -> None:
        if self._control_process is not None:
            return
        self._control_process = self._ctx.Process(
            target=worker_target,
            args=(
                self._control_commands,
                self._control_statuses,
                self._settings_payload,
                self._target_hwnd,
                self._control_release_event,
                *worker_args,
            ),
            name="MapleStarControlRuntime",
            daemon=True,
        )
        self._control_process.start()

    def send_settings(self, settings: AutoPotionSettings) -> None:
        self._settings_payload = settings.to_json_dict()
        command = SettingsUpdated(self._settings_payload)
        self._potion_commands.put(command)
        self._experience_commands.put(command)
        if self._control_process is not None:
            self._pending_control_settings = command
            self._flush_pending_control_messages()

    def send_target_window(self, hwnd: int) -> None:
        self._target_hwnd = int(hwnd or 0)
        command = TargetWindowUpdated(self._target_hwnd)
        self._potion_commands.put(command)
        self._experience_commands.put(command)
        if self._control_process is not None:
            self._pending_control_target = command
            self._flush_pending_control_messages()

    def send_potion_control(self, command: PotionControl) -> None:
        self._potion_commands.put(command)

    def send_experience_control(self, command: ExperienceControl) -> None:
        self._experience_commands.put(command)

    def send_control(self, command: ControlCommand) -> None:
        self._pending_control_command = command
        self._flush_pending_control_messages()

    def request_control_release(self, command: ControlCommand) -> None:
        self._control_release_event.set()
        self._pending_control_command = None
        self._pending_control_settings = SettingsUpdated(self._settings_payload)
        self._pending_control_target = TargetWindowUpdated(self._target_hwnd)
        if not self._put_control_command(command, required=True):
            raise RuntimeError("control release command enqueue failed")

    def _flush_pending_control_messages(self) -> None:
        for attribute in (
            "_pending_control_settings",
            "_pending_control_target",
            "_pending_control_command",
        ):
            command = getattr(self, attribute, None)
            if command is None:
                continue
            if not self._put_control_command(command, required=False):
                return
            setattr(self, attribute, None)

    def _put_control_command(self, command: object, *, required: bool) -> bool:
        try:
            if required:
                self._control_commands.put(command, timeout=0.25)
            else:
                self._control_commands.put_nowait(command)
            return True
        except queue.Full:
            if required:
                # Release/shutdown commands take precedence over coalescible
                # settings/state snapshots when the bounded queue is saturated.
                _drain_queue(self._control_commands, CONTROL_QUEUE_MAXSIZE)
                try:
                    self._control_commands.put(command, timeout=0.25)
                    return True
                except queue.Full:
                    return False
            return False

    def drain_potion_statuses(self, limit: int = 64) -> list[object]:
        return _drain_queue(self._potion_statuses, limit)

    def drain_experience_statuses(self, limit: int = 64) -> list[object]:
        return _drain_queue(self._experience_statuses, limit)

    def drain_control_statuses(self, limit: int = 64) -> list[object]:
        self._flush_pending_control_messages()
        return _drain_queue(self._control_statuses, limit)

    def potion_alive(self) -> bool:
        return self._potion_process.is_alive()

    def experience_alive(self) -> bool:
        return self._experience_process.is_alive()

    def control_alive(self) -> bool:
        return self._control_process is not None and self._control_process.is_alive()

    def restart_potion(self, settings: AutoPotionSettings, target_hwnd: int = 0, timeout: float = 1.0) -> None:
        self._settings_payload = settings.to_json_dict()
        self._target_hwnd = int(target_hwnd or 0)
        self._potion_commands.put(PotionControl(False, False, emergency_stop=True, release_all=True))
        self._potion_commands.put(Shutdown())
        self._potion_process.join(timeout=timeout)
        if self._potion_process.is_alive():
            self._potion_process.terminate()
            self._potion_process.join(timeout=timeout)
        self._potion_commands = self._ctx.Queue()
        self._potion_statuses = self._ctx.Queue()
        self._potion_process = self._new_potion_process()
        self._potion_process.start()

    def stop(self, timeout: float = 1.0) -> None:
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self._started = False
        cleanup_steps = (
            (
                "request potion key release",
                lambda: self._potion_commands.put(
                    PotionControl(False, False, emergency_stop=True, release_all=True)
                ),
            ),
            ("shutdown potion runtime", lambda: self._potion_commands.put(Shutdown())),
            (
                "pause experience runtime",
                lambda: self._experience_commands.put(ExperienceControl(False, pause=True)),
            ),
            ("shutdown experience runtime", lambda: self._experience_commands.put(Shutdown())),
        )
        for label, action in cleanup_steps:
            _run_coordinator_cleanup_step(label, action)
        if self._control_process is not None:
            _run_coordinator_cleanup_step("signal control key release", self._control_release_event.set)
            _run_coordinator_cleanup_step(
                "shutdown control runtime",
                lambda: self._put_control_command(Shutdown(), required=True),
            )
        processes = [self._potion_process, self._experience_process]
        if self._control_process is not None:
            processes.append(self._control_process)
        for process in processes:
            _stop_owned_process(process, timeout)


def _run_coordinator_cleanup_step(label: str, action: Callable[[], object]) -> None:
    try:
        action()
    except Exception:
        try:
            log_exception(f"RuntimeProcessCoordinator cleanup failed: {label}")
        except Exception:
            return


def _stop_owned_process(process, timeout: float) -> None:
    name = getattr(process, "name", "unknown")
    _run_coordinator_cleanup_step(f"join {name}", lambda: process.join(timeout=timeout))
    try:
        alive = process.is_alive()
    except Exception:
        try:
            log_exception(f"RuntimeProcessCoordinator cleanup failed: inspect {name}")
        except Exception:
            pass
        return
    if not alive:
        return
    _run_coordinator_cleanup_step(f"terminate {name}", process.terminate)
    _run_coordinator_cleanup_step(f"join terminated {name}", lambda: process.join(timeout=timeout))


def _drain_queue(source, limit: int) -> list[object]:
    items: list[object] = []
    for _ in range(limit):
        try:
            items.append(source.get_nowait())
        except queue.Empty:
            break
    return items


def _settings_from_payload(payload: dict[str, object]) -> AutoPotionSettings:
    settings = AutoPotionSettings()
    known_fields = {field.name for field in fields(AutoPotionSettings)}
    for key, value in payload.items():
        if key in known_fields:
            setattr(settings, key, value)
    settings.normalize_combo_slots()
    return settings


def _is_target_hwnd_active(hwnd: int) -> bool:
    foreground_hwnd = foreground_window_handle()
    if not foreground_hwnd:
        return False
    foreground_handles = window_ancestor_handles(foreground_hwnd)
    if hwnd and is_valid_window(hwnd) and not is_window_minimized(hwnd):
        if any(candidate == hwnd for candidate in foreground_handles):
            return True
    return is_target_window(foreground_hwnd)


def _run_child_cleanup_step(worker: str, label: str, action: Callable[[], None]) -> None:
    try:
        action()
    except Exception as exc:
        try:
            log_exception(f"{worker} runtime cleanup failed: {label}")
        except Exception:
            try:
                print(f"{worker} runtime cleanup failed ({label}): {exc}")
            except Exception:
                return


def _report_worker_crash(status_queue, worker: str, exc: Exception) -> None:
    try:
        log_exception(f"{worker} runtime process failed")
    except Exception:
        pass
    try:
        status_queue.put(WorkerCrashed(worker, str(exc)))
    except Exception:
        pass


def _bar_debug_region(controller: Any, bar_type: str) -> tuple[int, int, int, int] | None:
    debug = getattr(controller, "last_bar_debug", {}).get(bar_type)
    region = getattr(debug, "region", None)
    if region is None or len(region) != 4:
        return None
    try:
        return tuple(int(value) for value in region)
    except (TypeError, ValueError):
        return None


def _bar_debug_track_region(controller: Any, bar_type: str) -> tuple[int, int, int, int] | None:
    debug = getattr(controller, "last_bar_debug", {}).get(bar_type)
    region = getattr(debug, "track_region", None)
    if region is None or len(region) != 4:
        return None
    try:
        return tuple(int(value) for value in region)
    except (TypeError, ValueError):
        return None


def _handle_potion_command(
    controller: Any,
    gui: HeadlessRuntimeGui,
    target_state: dict[str, int],
    command: object,
) -> None:
    if isinstance(command, SettingsUpdated):
        settings = _settings_from_payload(command.settings_payload)
        settings.exp_efficiency_enabled = False
        controller.settings = settings
        gui.settings = settings
        controller.pending_settings_snapshot = settings.snapshot()
        return
    if isinstance(command, TargetWindowUpdated):
        target_state["hwnd"] = int(command.hwnd or 0)
        controller.last_target_hwnd = target_state["hwnd"]
        return
    if isinstance(command, PotionControl):
        was_enabled = bool(getattr(controller, "auto_drink_enabled", False))
        controller.scripts_enabled = command.scripts_enabled
        controller.auto_drink_enabled = command.enabled and command.scripts_enabled
        if command.challenge_paused is not None:
            controller.auto_drink_challenge_paused = command.challenge_paused
            if command.challenge_paused:
                controller._clear_potion_attempt_state("hp")
                controller._clear_potion_attempt_state("mp")
        if (
            command.release_all
            or command.emergency_stop
            or not controller.auto_drink_enabled
            or bool(getattr(controller, "auto_drink_challenge_paused", False))
        ):
            controller._release_all_potion_keys()
        if controller.auto_drink_enabled and not was_enabled:
            controller._clear_potion_effect_state()


def _handle_experience_command(controller: Any, target_state: dict[str, int], command: object) -> None:
    if isinstance(command, SettingsUpdated):
        settings = _settings_from_payload(command.settings_payload)
        controller.settings = settings
        controller.gui.settings = settings
        controller.pending_settings_snapshot = settings.snapshot()
        return
    if isinstance(command, TargetWindowUpdated):
        target_state["hwnd"] = int(command.hwnd or 0)
        controller.last_target_hwnd = target_state["hwnd"]
        return
    if isinstance(command, ExperienceControl):
        controller.settings.exp_efficiency_enabled = command.enabled
        if command.reset:
            controller.reset_experience_statistics()
            controller.gui.set_experience_snapshot(ExperienceSnapshot(status="已重置"))
        if command.pause:
            controller._pause_experience_clock(time.monotonic())
        if command.resume:
            now = time.monotonic()
            if not getattr(controller.experience_tracker, "samples", []):
                controller._reset_experience_baseline_calibration_attempts()
                controller._mark_initial_experience_tooltip_baseline_start(now)
            controller._resume_exp_10m_checkpoint_schedule(now)
            controller._resume_experience_clock(now)


def _potion_status(controller: Any, gui: HeadlessRuntimeGui, generation: int = 0) -> PotionStatus:
    lines = gui.consume_console_lines()
    now = time.monotonic()
    potion_action_defer_until = 0.0
    if hasattr(controller, "potion_priority_defer_until"):
        potion_action_defer_until = float(
            controller.potion_priority_defer_until(now, gui.hp_percent, gui.mp_percent) or 0.0
        )
    return PotionStatus(
        hp_percent=gui.hp_percent,
        mp_percent=gui.mp_percent,
        hp_debug=gui.hp_debug,
        mp_debug=gui.mp_debug,
        status=gui.status,
        action=str(getattr(controller, "last_action", "")),
        notice=gui.consume_notice(),
        media_sound_aliases=gui.consume_media_sound_aliases(),
        trigger_interval_ms=None,
        console_lines=lines,
        gameplay_hud_active=bool(getattr(controller, "gameplay_hud_active", False)),
        scripts_enabled=bool(getattr(controller, "scripts_enabled", False)),
        auto_drink_enabled=bool(getattr(controller, "auto_drink_enabled", False)),
        hp_region=_bar_debug_region(controller, "hp"),
        mp_region=_bar_debug_region(controller, "mp"),
        hp_track_region=_bar_debug_track_region(controller, "hp"),
        mp_track_region=_bar_debug_track_region(controller, "mp"),
        potion_action_defer_until=potion_action_defer_until,
        generation=int(generation or 0),
    )


def _experience_status(gui: HeadlessRuntimeGui, generation: int = 0) -> ExperienceStatus:
    return ExperienceStatus(gui.experience_snapshot, gui.status, generation=int(generation or 0))
