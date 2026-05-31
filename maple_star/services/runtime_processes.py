from __future__ import annotations

import multiprocessing as mp
import queue
import time
from concurrent.futures import Future
from dataclasses import dataclass, fields
from typing import Any

from ..adapters.debug_logging import log_exception
from ..adapters.win_input import foreground_window_handle, is_valid_window, is_window_minimized, window_ancestor_handles
from ..adapters.window_target import is_target_window
from ..constants import DEFAULT_CAPTURE_INTERVAL_SECONDS
from ..models.experience import ExperienceSnapshot
from ..models.settings import AutoPotionSettings

STATUS_HEARTBEAT_SECONDS = 1.0


@dataclass(frozen=True)
class SettingsUpdated:
    settings_payload: dict[str, object]


@dataclass(frozen=True)
class TargetWindowUpdated:
    hwnd: int


@dataclass(frozen=True)
class PotionControl:
    enabled: bool
    scripts_enabled: bool
    emergency_stop: bool = False
    release_all: bool = False
    generation: int = 0


@dataclass(frozen=True)
class ExperienceControl:
    enabled: bool
    reset: bool = False
    pause: bool = False
    resume: bool = False
    generation: int = 0


@dataclass(frozen=True)
class Shutdown:
    pass


@dataclass(frozen=True)
class PotionStatus:
    hp_percent: float | None
    mp_percent: float | None
    hp_debug: str
    mp_debug: str
    status: str
    action: str
    notice: str
    trigger_interval_ms: float | None
    console_lines: tuple[str, ...]
    gameplay_hud_active: bool
    scripts_enabled: bool
    auto_drink_enabled: bool
    hp_region: tuple[int, int, int, int] | None = None
    mp_region: tuple[int, int, int, int] | None = None
    media_sound_aliases: tuple[str, ...] = ()
    generation: int = 0


@dataclass(frozen=True)
class ExperienceStatus:
    snapshot: ExperienceSnapshot
    status: str
    debug_event: dict[str, object] | None = None
    generation: int = 0


@dataclass(frozen=True)
class WorkerCrashed:
    worker: str
    message: str


class InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        return


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
    def __init__(self, settings: AutoPotionSettings, target_hwnd: int = 0) -> None:
        self._ctx = mp.get_context("spawn")
        self._potion_commands = self._ctx.Queue()
        self._potion_statuses = self._ctx.Queue()
        self._experience_commands = self._ctx.Queue()
        self._experience_statuses = self._ctx.Queue()
        self._settings_payload = settings.to_json_dict()
        self._target_hwnd = int(target_hwnd or 0)
        self._potion_process = self._new_potion_process()
        self._experience_process = self._ctx.Process(
            target=_run_experience_stats_process,
            args=(self._experience_commands, self._experience_statuses, self._settings_payload, self._target_hwnd),
            name="MapleStarExperienceStats",
            daemon=True,
        )
        self._started = False

    def _new_potion_process(self) -> mp.Process:
        return self._ctx.Process(
            target=_run_potion_runtime_process,
            args=(self._potion_commands, self._potion_statuses, self._settings_payload, self._target_hwnd),
            name="MapleStarPotionRuntime",
            daemon=True,
        )

    def start(self) -> None:
        if self._started:
            return
        self._potion_process.start()
        self._experience_process.start()
        self._started = True

    def send_settings(self, settings: AutoPotionSettings) -> None:
        self._settings_payload = settings.to_json_dict()
        command = SettingsUpdated(self._settings_payload)
        self._potion_commands.put(command)
        self._experience_commands.put(command)

    def send_target_window(self, hwnd: int) -> None:
        self._target_hwnd = int(hwnd or 0)
        command = TargetWindowUpdated(self._target_hwnd)
        self._potion_commands.put(command)
        self._experience_commands.put(command)

    def send_potion_control(self, command: PotionControl) -> None:
        self._potion_commands.put(command)

    def send_experience_control(self, command: ExperienceControl) -> None:
        self._experience_commands.put(command)

    def drain_potion_statuses(self, limit: int = 64) -> list[object]:
        return _drain_queue(self._potion_statuses, limit)

    def drain_experience_statuses(self, limit: int = 64) -> list[object]:
        return _drain_queue(self._experience_statuses, limit)

    def potion_alive(self) -> bool:
        return self._potion_process.is_alive()

    def experience_alive(self) -> bool:
        return self._experience_process.is_alive()

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
        if not self._started:
            return
        self._potion_commands.put(PotionControl(False, False, emergency_stop=True, release_all=True))
        self._potion_commands.put(Shutdown())
        self._experience_commands.put(ExperienceControl(False, pause=True))
        self._experience_commands.put(Shutdown())
        for process in (self._potion_process, self._experience_process):
            process.join(timeout=timeout)
            if process.is_alive():
                process.terminate()
                process.join(timeout=timeout)


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


def _run_potion_runtime_process(command_queue, status_queue, settings_payload: dict[str, object], target_hwnd: int) -> None:
    try:
        from ..controllers.auto_potion_controller import AutoPotionController

        settings = _settings_from_payload(settings_payload)
        settings.exp_efficiency_enabled = False
        target_state = {"hwnd": int(target_hwnd or 0)}
        gui = HeadlessRuntimeGui(settings)
        controller = AutoPotionController(
            lambda: _is_target_hwnd_active(target_state["hwnd"]),
            settings=settings,
            target_window_provider=lambda: target_state["hwnd"],
            gui=gui,
            start_control_hotkey_worker=False,
            start_potion_action_worker=False,
            experience_executor=InlineExecutor(),
            runtime_processes_enabled=False,
            save_settings_on_cleanup=False,
        )
        controller._save_settings_when_idle = lambda _now: None
        controller._play_media_file = lambda _path, alias: gui.queue_media_sound(str(alias))
        controller._play_toggle_beep = lambda *_args, **_kwargs: None
        _install_potion_console_recorder(controller, gui)
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
                if now >= next_status_at or gui.console_lines:
                    status = _potion_status(controller, gui, generation)
                    signature = _potion_status_signature(status)
                    urgent = bool(status.notice or status.console_lines or status.media_sound_aliases)
                    if urgent or signature != last_status_signature or now >= next_heartbeat_at:
                        status_queue.put(status)
                        last_status_signature = signature
                        next_heartbeat_at = now + STATUS_HEARTBEAT_SECONDS
                    next_status_at = now + 0.10
            time.sleep(0.01)
        controller._release_all_potion_keys()
        controller.cleanup()
    except Exception as exc:
        log_exception("PotionRuntime process failed")
        status_queue.put(WorkerCrashed("potion", str(exc)))


def _run_experience_stats_process(command_queue, status_queue, settings_payload: dict[str, object], target_hwnd: int) -> None:
    try:
        from ..controllers.auto_potion_controller import AutoPotionController

        settings = _settings_from_payload(settings_payload)
        target_state = {"hwnd": int(target_hwnd or 0)}
        gui = HeadlessRuntimeGui(settings)
        controller = AutoPotionController(
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
        )
        controller.auto_drink_enabled = False
        controller._save_settings_when_idle = lambda _now: None
        controller._play_media_file = lambda *_args, **_kwargs: None
        controller._play_toggle_beep = lambda *_args, **_kwargs: None
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
        controller._cancel_experience_baseline_calibration(close_ui=True)
        controller.cleanup()
    except Exception as exc:
        log_exception("ExperienceStats process failed")
        status_queue.put(WorkerCrashed("experience", str(exc)))


def _install_potion_console_recorder(controller: Any, gui: HeadlessRuntimeGui) -> None:
    original = controller._log_potion_key_trigger_interval

    def record(label: str, key_name: str, previous_at: float, now: float) -> None:
        original(label, key_name, previous_at, now)

    controller._log_potion_key_trigger_interval = record


def _bar_debug_region(controller: Any, bar_type: str) -> tuple[int, int, int, int] | None:
    debug = getattr(controller, "last_bar_debug", {}).get(bar_type)
    region = getattr(debug, "region", None)
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
        if command.release_all or command.emergency_stop or not controller.auto_drink_enabled:
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
            controller._resume_exp_10m_checkpoint_schedule(now)
            controller._resume_experience_clock(now)


def _potion_status(controller: Any, gui: HeadlessRuntimeGui, generation: int = 0) -> PotionStatus:
    lines = gui.consume_console_lines()
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
        generation=int(generation or 0),
    )


def _experience_status(gui: HeadlessRuntimeGui, generation: int = 0) -> ExperienceStatus:
    return ExperienceStatus(gui.experience_snapshot, gui.status, generation=int(generation or 0))


def _potion_status_signature(status: PotionStatus) -> tuple[object, ...]:
    return (
        _rounded_percent(status.hp_percent),
        _rounded_percent(status.mp_percent),
        status.hp_debug,
        status.mp_debug,
        status.status,
        status.action,
        status.gameplay_hud_active,
        status.scripts_enabled,
        status.auto_drink_enabled,
        status.hp_region,
        status.mp_region,
        int(status.generation or 0),
    )


def _experience_status_signature(status: ExperienceStatus) -> tuple[object, ...]:
    snapshot = status.snapshot
    return (
        snapshot.current_exp,
        _rounded_percent(snapshot.current_percent),
        snapshot.exp_10m_gain,
        _rounded_float(snapshot.xp_per_5m),
        _rounded_float(snapshot.xp_per_10m),
        _rounded_float(snapshot.xp_per_hour),
        _rounded_float(snapshot.eta_seconds),
        _rounded_float(snapshot.elapsed_seconds),
        snapshot.sample_count,
        snapshot.sample_attempt_count,
        snapshot.sample_accept_count,
        _rounded_float(snapshot.sample_accept_rate),
        _rounded_float(snapshot.rate_confidence),
        snapshot.ocr_attempt_count,
        snapshot.ocr_success_count,
        _rounded_float(snapshot.ocr_success_rate),
        snapshot.status,
        status.status,
        int(status.generation or 0),
    )


def _rounded_percent(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _rounded_float(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)
