from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, Protocol

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
    challenge_paused: bool | None = None
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
    hp_track_region: tuple[int, int, int, int] | None = None
    mp_track_region: tuple[int, int, int, int] | None = None
    media_sound_aliases: tuple[str, ...] = ()
    potion_action_defer_until: float = 0.0
    generation: int = 0


@dataclass(frozen=True)
class PotionWorkerProgress:
    generation: int
    heartbeat_at: float
    progress_at: float
    phase: str


@dataclass(frozen=True)
class ControlCommand:
    scripts_enabled: bool
    gameplay_hud_active: bool
    cruise_enabled: bool
    action_blocked: bool = False
    potion_action_defer_until: float = 0.0
    challenge_paused: bool = False
    release_all: bool = False
    generation: int = 0
    benchmark_deadline_interval_seconds: float = 0.0


@dataclass(frozen=True)
class ControlStatus:
    generation: int
    heartbeat_at: float
    worker_state: str
    cruise_enabled: bool
    challenge_paused: bool
    macro_status: str
    held_keys: str
    last_action: str
    notice: str = ""
    urgent_events: tuple[str, ...] = ()
    console_lines: tuple[str, ...] = ()
    timing_sample_count: int = 0
    timing_p95_lateness_ms: float = 0.0
    timing_p99_lateness_ms: float = 0.0
    timing_max_lateness_ms: float = 0.0
    held_vks: tuple[int, ...] = ()


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


class RuntimeProcessPort(Protocol):
    def start(self) -> None: ...

    def start_control(self, worker_target, *worker_args: object) -> None: ...

    def send_settings(self, settings: AutoPotionSettings) -> None: ...

    def send_target_window(self, hwnd: int) -> None: ...

    def send_potion_control(self, command: PotionControl) -> None: ...

    def send_experience_control(self, command: ExperienceControl) -> None: ...

    def send_control(self, command: ControlCommand) -> None: ...

    def request_control_release(self, command: ControlCommand) -> None: ...

    def safety_fence(self) -> int: ...

    def rearm_input(self) -> int: ...

    def drain_potion_statuses(self, limit: int = 64) -> list[object]: ...

    def drain_experience_statuses(self, limit: int = 64) -> list[object]: ...

    def drain_control_statuses(self, limit: int = 64) -> list[object]: ...

    def potion_alive(self) -> bool: ...

    def experience_alive(self) -> bool: ...

    def control_alive(self) -> bool: ...

    def guardian_alive(self) -> bool: ...

    def restart_potion(
        self,
        settings: AutoPotionSettings,
        target_hwnd: int = 0,
        timeout: float = 1.0,
    ) -> None: ...

    def stop(self, timeout: float = 1.0) -> None: ...


RuntimeProcessFactory = Callable[[AutoPotionSettings, int], RuntimeProcessPort]


def _potion_status_signature(status: PotionStatus) -> tuple[object, ...]:
    return (
        _rounded_percent(status.hp_percent),
        _rounded_percent(status.mp_percent),
        _bar_debug_signature(status.hp_debug),
        _bar_debug_signature(status.mp_debug),
        status.status,
        status.action,
        status.gameplay_hud_active,
        status.scripts_enabled,
        status.auto_drink_enabled,
        status.hp_region,
        status.mp_region,
        status.hp_track_region,
        status.mp_track_region,
        round(float(status.potion_action_defer_until or 0.0), 3),
        int(status.generation or 0),
    )


def _bar_debug_signature(debug: str) -> tuple[str, ...]:
    parts = [part.strip() for part in str(debug or "").split("|")]
    return tuple(
        part
        for part in parts
        if part
        and not _is_percent_fragment(part)
        and not _is_region_fragment(part)
        and not part.startswith(("full=", "track=", "f=", "t="))
    )


def _is_percent_fragment(value: str) -> bool:
    value = value.strip()
    if not value.endswith("%"):
        return False
    try:
        float(value[:-1])
    except ValueError:
        return False
    return True


def _is_region_fragment(value: str) -> bool:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        return False
    try:
        for part in parts:
            int(part)
    except ValueError:
        return False
    return True


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


def control_status_signature(status: ControlStatus) -> tuple[object, ...]:
    return (
        int(status.generation),
        status.worker_state,
        bool(status.cruise_enabled),
        bool(status.challenge_paused),
        status.macro_status,
        status.held_keys,
        tuple(status.held_vks),
        status.last_action,
        int(status.timing_sample_count),
        round(float(status.timing_p95_lateness_ms), 3),
        round(float(status.timing_p99_lateness_ms), 3),
        round(float(status.timing_max_lateness_ms), 3),
    )


def _rounded_percent(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _rounded_float(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


__all__ = [
    "ControlCommand",
    "ControlStatus",
    "ExperienceControl",
    "ExperienceStatus",
    "InlineExecutor",
    "PotionControl",
    "PotionStatus",
    "RuntimeProcessFactory",
    "RuntimeProcessPort",
    "SettingsUpdated",
    "Shutdown",
    "TargetWindowUpdated",
    "WorkerCrashed",
    "_experience_status_signature",
    "_potion_status_signature",
    "control_status_signature",
]
