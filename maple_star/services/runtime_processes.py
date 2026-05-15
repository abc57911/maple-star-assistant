from __future__ import annotations

import multiprocessing as mp
import queue
import time
from concurrent.futures import Future
from dataclasses import dataclass, fields
from typing import Any

from ..adapters.debug_logging import log_exception
from ..adapters.win_input import foreground_window_handle, is_valid_window, is_window_minimized
from ..constants import DEFAULT_CAPTURE_INTERVAL_SECONDS
from ..models.experience import ExperienceSnapshot
from ..models.settings import AutoPotionSettings


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


@dataclass(frozen=True)
class ExperienceControl:
    enabled: bool
    reset: bool = False
    pause: bool = False
    resume: bool = False


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


@dataclass(frozen=True)
class ExperienceStatus:
    snapshot: ExperienceSnapshot
    status: str
    debug_event: dict[str, object] | None = None


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

    def refresh_bar_preview_once(self) -> None:
        return

    def set_experience_snapshot(self, snapshot: ExperienceSnapshot) -> None:
        self.experience_snapshot = snapshot
        self.status = snapshot.status

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
        settings_payload = settings.to_json_dict()
        self._potion_process = self._ctx.Process(
            target=_run_potion_runtime_process,
            args=(self._potion_commands, self._potion_statuses, settings_payload, int(target_hwnd or 0)),
            name="MapleStarPotionRuntime",
            daemon=True,
        )
        self._experience_process = self._ctx.Process(
            target=_run_experience_stats_process,
            args=(self._experience_commands, self._experience_statuses, settings_payload, int(target_hwnd or 0)),
            name="MapleStarExperienceStats",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._potion_process.start()
        self._experience_process.start()
        self._started = True

    def send_settings(self, settings: AutoPotionSettings) -> None:
        command = SettingsUpdated(settings.to_json_dict())
        self._potion_commands.put(command)
        self._experience_commands.put(command)

    def send_target_window(self, hwnd: int) -> None:
        command = TargetWindowUpdated(int(hwnd or 0))
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
    return settings


def _is_target_hwnd_active(hwnd: int) -> bool:
    return bool(hwnd and is_valid_window(hwnd) and not is_window_minimized(hwnd) and foreground_window_handle() == hwnd)


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
        controller._play_media_file = lambda *_args, **_kwargs: None
        controller._play_toggle_beep = lambda *_args, **_kwargs: None
        _install_potion_console_recorder(controller, gui)
        next_status_at = 0.0
        shutdown = False
        while not shutdown:
            for command in _drain_queue(command_queue, 128):
                if isinstance(command, Shutdown):
                    shutdown = True
                    break
                _handle_potion_command(controller, gui, target_state, command)
            now = time.monotonic()
            if not shutdown:
                controller.update(now, pump_gui=False)
                if now >= next_status_at or gui.console_lines:
                    status_queue.put(_potion_status(controller, gui))
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
        )
        controller.auto_drink_enabled = False
        controller._save_settings_when_idle = lambda _now: None
        controller._play_media_file = lambda *_args, **_kwargs: None
        controller._play_toggle_beep = lambda *_args, **_kwargs: None
        next_status_at = 0.0
        shutdown = False
        while not shutdown:
            for command in _drain_queue(command_queue, 128):
                if isinstance(command, Shutdown):
                    shutdown = True
                    break
                _handle_experience_command(controller, target_state, command)
            now = time.monotonic()
            if not shutdown:
                controller.update(now, pump_gui=False)
                if now >= next_status_at:
                    status_queue.put(ExperienceStatus(gui.experience_snapshot, gui.status))
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
        if previous_at <= -100.0:
            interval_text = "首次"
        else:
            interval_text = f"{max(0.0, now - previous_at) * 1000.0:.0f}ms"
        gui.console_lines.append(f"{label} 喝水按鍵觸發：{key_name}（間隔：{interval_text}）")
        original(label, key_name, previous_at, now)

    controller._log_potion_key_trigger_interval = record


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
            controller._resume_experience_clock(time.monotonic())


def _potion_status(controller: Any, gui: HeadlessRuntimeGui) -> PotionStatus:
    trigger_interval_ms: float | None = None
    lines = gui.consume_console_lines()
    for line in reversed(lines):
        marker = "（間隔："
        if marker not in line or not line.endswith("）"):
            continue
        value = line.split(marker, 1)[1][:-1]
        if value.endswith("ms"):
            try:
                trigger_interval_ms = float(value[:-2])
            except ValueError:
                trigger_interval_ms = None
        break
    return PotionStatus(
        hp_percent=gui.hp_percent,
        mp_percent=gui.mp_percent,
        hp_debug=gui.hp_debug,
        mp_debug=gui.mp_debug,
        status=gui.status,
        action=str(getattr(controller, "last_action", "")),
        notice=gui.notice,
        trigger_interval_ms=trigger_interval_ms,
        console_lines=lines,
        gameplay_hud_active=bool(getattr(controller, "gameplay_hud_active", False)),
        scripts_enabled=bool(getattr(controller, "scripts_enabled", False)),
        auto_drink_enabled=bool(getattr(controller, "auto_drink_enabled", False)),
    )
