from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..constants import (
    POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
    POTION_EFFECT_AUTO_HOLD_BAR_TYPES,
    POTION_EFFECT_DAMAGE_GRACE_SECONDS,
    POTION_EFFECT_HP_STABILITY_CONFIRMATION_MIN_SAMPLES,
    POTION_EFFECT_HP_STABILITY_CONFIRMATION_SECONDS,
    POTION_EFFECT_HP_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT,
    POTION_EFFECT_NO_EFFECT_LIMIT,
    POTION_EFFECT_OBSERVATION_SECONDS,
    POTION_EFFECT_PRE_OBSERVATION_MIN_SAMPLES,
    POTION_EFFECT_PRE_OBSERVATION_SECONDS,
    POTION_EFFECT_PRE_OBSERVATION_VOLATILITY_TOLERANCE_PERCENT,
    POTION_EFFECT_STABILITY_CONFIRMATION_MIN_SAMPLES,
    POTION_EFFECT_STABILITY_CONFIRMATION_SECONDS,
    POTION_EFFECT_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT,
    POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT,
    POTION_EFFECT_WATCH_VOLATILITY_TOLERANCE_PERCENT,
)
from ..models.controller_state import OutOfPotionHold, PotionEffectAttempt
from .bar_detection import should_continue_continuous_drink, should_drink_for_threshold


BarType = Literal["hp", "mp"]
POTION_TIME_EPSILON_SECONDS = 1e-9
POTION_EXPERIENCE_DEFER_SECONDS = 1.0


@dataclass(frozen=True)
class PotionBarConfig:
    bar_type: BarType
    enabled: bool
    threshold_percent: float
    cooldown_seconds: float
    key_name: str
    continuous_enabled: bool
    continuous_stop_percent: float
    no_effect_limit: int = POTION_EFFECT_NO_EFFECT_LIMIT

    @property
    def continuous_stop_margin_percent(self) -> float:
        return max(0.0, self.threshold_percent - self.continuous_stop_percent)


@dataclass(frozen=True)
class PotionSample:
    now: float
    hp_percent: float | None
    mp_percent: float | None
    hp: PotionBarConfig
    mp: PotionBarConfig
    feature_enabled: bool
    scripts_enabled: bool
    target_active: bool
    challenge_paused: bool
    gameplay_hud_active: bool
    action_channel_ready: bool
    recent_damage_at: float | None = None


@dataclass(frozen=True)
class PotionCommand:
    command_id: int
    bar_type: BarType
    kind: Literal["tap", "hold", "release"]
    key_name: str
    sampled_percent: float | None
    requested_at: float | None = None
    previous_drink_at: float = -999.0
    continuous: bool = False
    clear_pending_on_success: bool = False
    vk_code: int = 0
    due_at: float | None = None
    reason: str = ""

    @property
    def action(self) -> Literal["tap", "hold", "release"]:
        return self.kind


@dataclass(frozen=True)
class PotionCommandResult:
    command_id: int
    outcome: Literal["executed", "rejected_foreground", "invalid_key", "queue_full", "failed"]
    completed_at: float | None = None
    held_vk: int = 0
    reason: str = ""

    @property
    def executed_at(self) -> float | None:
        return self.completed_at


@dataclass(frozen=True)
class PotionEngineSnapshot:
    hp_pending_send_at: float
    mp_pending_send_at: float
    hp_held_vk: int
    mp_held_vk: int
    has_out_of_potion_hold: bool
    next_due_at: float | None = None
    priority_defer_until: float | None = None
    hp_status: str = "idle"
    mp_status: str = "idle"
    hp_no_effect_count: int = 0
    mp_no_effect_count: int = 0


class PotionEngine:
    def __init__(self) -> None:
        self.runtime_potion_action_defer_until = 0.0
        self.potion_send_prevalidated_at = -999.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.hp_pending_potion_send_at = -999.0
        self.mp_pending_potion_send_at = -999.0
        self.hp_pending_potion_send_percent: float | None = None
        self.mp_pending_potion_send_percent: float | None = None
        self.hp_potion_effect_attempts: list[PotionEffectAttempt] = []
        self.mp_potion_effect_attempts: list[PotionEffectAttempt] = []
        self.hp_potion_no_effect_count = 0
        self.mp_potion_no_effect_count = 0
        self.hp_potion_last_no_effect_counted_at = -999.0
        self.mp_potion_last_no_effect_counted_at = -999.0
        self.hp_potion_last_observed_percent: float | None = None
        self.mp_potion_last_observed_percent: float | None = None
        self.hp_potion_recent_samples: list[tuple[float, float]] = []
        self.mp_potion_recent_samples: list[tuple[float, float]] = []
        self.hp_potion_recent_damage_at = -999.0
        self.mp_potion_recent_damage_at = -999.0
        self.hp_potion_damage_pressure_active = False
        self.mp_potion_damage_pressure_active = False
        self.hp_out_of_potion_hold: OutOfPotionHold | None = None
        self.mp_out_of_potion_hold: OutOfPotionHold | None = None
        self.hp_potion_held_vk = 0
        self.mp_potion_held_vk = 0
        self.hp_potion_hold_refreshed_at = -999.0
        self.mp_potion_hold_refreshed_at = -999.0
        self.last_potion_blocked_sound_at = -999.0
        self.last_potion_check_sound_at = -999.0
        self.next_command_id = 1
        self.pending_command_ids: set[int] = set()
        self.pending_commands: dict[int, PotionCommand] = {}
        self.pending_command_ids_by_bar: dict[str, set[int]] = {}

    def _new_command(
        self,
        bar_type: BarType,
        action: Literal["tap", "hold", "release"],
        key_name: str,
        sampled_percent: float | None,
        now: float,
        *,
        previous_drink_at: float = -999.0,
        continuous: bool = False,
        clear_pending_on_success: bool = False,
        vk_code: int = 0,
    ) -> PotionCommand:
        command = PotionCommand(
            self.next_command_id,
            bar_type,
            action,
            key_name,
            sampled_percent,
            now,
            previous_drink_at,
            continuous,
            clear_pending_on_success,
            vk_code,
        )
        self.next_command_id += 1
        self.pending_command_ids.add(command.command_id)
        self.pending_commands[command.command_id] = command
        self.pending_command_ids_by_bar.setdefault(bar_type, set()).add(command.command_id)
        return command

    def apply_result(self, result: PotionCommandResult) -> PotionCommand | None:
        if result.command_id not in self.pending_command_ids:
            return None
        command = self.pending_commands.pop(result.command_id)
        self.pending_command_ids.remove(result.command_id)
        bar_command_ids = self.pending_command_ids_by_bar.get(command.bar_type)
        if bar_command_ids is not None:
            bar_command_ids.discard(result.command_id)
            if not bar_command_ids:
                self.pending_command_ids_by_bar.pop(command.bar_type, None)
        if result.outcome != "executed":
            return command

        completed_at = result.executed_at
        if completed_at is None:
            completed_at = command.requested_at if command.requested_at is not None else -999.0
        if command.action == "release":
            self._set_potion_held_vk(command.bar_type, 0)
            self._set_potion_hold_refreshed_at(command.bar_type, -999.0)
            return command

        if command.clear_pending_on_success:
            self._clear_pending_potion_send(command.bar_type)
        self._set_last_potion_drink_at(command.bar_type, completed_at)
        if command.action == "hold":
            self._set_potion_held_vk(command.bar_type, result.held_vk)
            self._set_potion_hold_refreshed_at(command.bar_type, completed_at)
            assert command.sampled_percent is not None
            self._record_continuous_potion_effect_attempt(
                command.bar_type,
                completed_at,
                command.sampled_percent,
            )
        else:
            assert command.sampled_percent is not None
            self._record_potion_effect_attempt(
                command.bar_type,
                completed_at,
                command.sampled_percent,
            )
        return command

    def apply_command_result(self, result: PotionCommandResult) -> PotionCommand | None:
        return self.apply_result(result)

    def _bar_has_pending_command(self, bar_type: str) -> bool:
        return bool(self.pending_command_ids_by_bar.get(bar_type))

    def request_release_command(self, bar_type: BarType, now: float) -> PotionCommand | None:
        held_vk = self._potion_held_vk(bar_type)
        pending_commands = [
            self.pending_commands[command_id]
            for command_id in self.pending_command_ids_by_bar.get(bar_type, set())
        ]
        if any(command.action == "release" for command in pending_commands):
            return None
        if not held_vk and not any(command.action == "hold" for command in pending_commands):
            return None
        return self._new_command(
            bar_type,
            "release",
            "",
            None,
            now,
            vk_code=held_vk,
        )

    def complete_command_result(
        self,
        result: PotionCommandResult,
        *,
        log_trigger_interval,
        set_last_action,
        play_blocked_sound,
    ) -> bool:
        command = self.apply_result(result)
        if command is None:
            return False
        completed_at = result.executed_at
        if completed_at is None:
            completed_at = command.requested_at if command.requested_at is not None else -999.0
        if result.outcome != "executed":
            play_blocked_sound(completed_at)
            return True
        if command.action == "release":
            return True
        label = "HP" if command.bar_type == "hp" else "MP"
        if not command.continuous or command.previous_drink_at <= -100.0:
            log_trigger_interval(
                label,
                command.key_name,
                command.previous_drink_at,
                completed_at,
            )
        mode = "連續喝水" if command.continuous else "喝水"
        set_last_action(f"{label} {mode}：{command.key_name}")
        return True

    def update(
        self,
        sample: PotionSample,
        *,
        release_key,
        clear_bar_state,
        capture_transient,
        emit_failure_warning,
        log_unstable,
        is_active_before_send,
        play_blocked_sound,
        can_fast_repeat,
        capture_confirmed,
        log_trigger_interval,
        execute_command,
        set_last_action,
    ) -> None:
        if not sample.feature_enabled or not sample.scripts_enabled:
            clear_bar_state("hp")
            clear_bar_state("mp")
            return
        for config, percent, label in (
            (sample.hp, sample.hp_percent, "HP"),
            (sample.mp, sample.mp_percent, "MP"),
        ):
            self._maybe_drink_potion(
                config.bar_type,
                label,
                sample.now,
                percent,
                config.enabled,
                config.threshold_percent,
                config.key_name,
                config.continuous_enabled,
                config.continuous_stop_margin_percent,
                challenge_paused=sample.challenge_paused,
                release_key=release_key,
                clear_bar_state=clear_bar_state,
                capture_transient=capture_transient,
                emit_failure_warning=emit_failure_warning,
                log_unstable=log_unstable,
                should_drink=self._should_drink_for_current_mode,
                cooldown_seconds=lambda _bar_type, seconds=config.cooldown_seconds: seconds,
                is_active_before_send=is_active_before_send,
                play_blocked_sound=play_blocked_sound,
                can_fast_repeat=can_fast_repeat,
                capture_confirmed=capture_confirmed,
                log_trigger_interval=log_trigger_interval,
                execute_command=execute_command,
                set_last_action=set_last_action,
            )

    def clear(self, bar_type: BarType | None = None) -> None:
        bar_types = (bar_type,) if bar_type is not None else ("hp", "mp")
        for current_bar_type in bar_types:
            command_ids = self.pending_command_ids_by_bar.pop(current_bar_type, set())
            for command_id in command_ids:
                self.pending_command_ids.discard(command_id)
                self.pending_commands.pop(command_id, None)
            self._clear_potion_attempt_state(current_bar_type)
            self._set_potion_held_vk(current_bar_type, 0)
            self._set_potion_hold_refreshed_at(current_bar_type, -999.0)
            self._set_potion_last_observed_percent(current_bar_type, None)
            self._set_out_of_potion_hold(current_bar_type, None)

    def _potion_held_vk(self, bar_type: str) -> int:
        return self.hp_potion_held_vk if bar_type == "hp" else self.mp_potion_held_vk

    def _set_potion_held_vk(self, bar_type: str, vk_code: int) -> None:
        if bar_type == "hp":
            self.hp_potion_held_vk = vk_code
        else:
            self.mp_potion_held_vk = vk_code

    def _potion_hold_refreshed_at(self, bar_type: str) -> float:
        return self.hp_potion_hold_refreshed_at if bar_type == "hp" else self.mp_potion_hold_refreshed_at

    def _set_potion_hold_refreshed_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.hp_potion_hold_refreshed_at = now
        else:
            self.mp_potion_hold_refreshed_at = now

    def _record_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        attempt = PotionEffectAttempt(
            now,
            before_percent,
            pre_window_is_stable=self._potion_pre_window_is_stable(bar_type, now, before_percent),
        )
        attempts = [*self._potion_effect_attempts(bar_type), attempt]
        self._set_potion_effect_attempts(bar_type, attempts)

    def _record_continuous_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        attempts = self._potion_effect_attempts(bar_type)
        if attempts and now - attempts[-1].attempted_at + POTION_TIME_EPSILON_SECONDS < POTION_EFFECT_OBSERVATION_SECONDS:
            return
        self._record_potion_effect_attempt(bar_type, now, before_percent)

    def _potion_effect_attempts(self, bar_type: str) -> list[PotionEffectAttempt]:
        return self.hp_potion_effect_attempts if bar_type == "hp" else self.mp_potion_effect_attempts

    def _set_potion_effect_attempts(self, bar_type: str, attempts: list[PotionEffectAttempt]) -> None:
        if bar_type == "hp":
            self.hp_potion_effect_attempts = attempts
        else:
            self.mp_potion_effect_attempts = attempts

    def _clear_potion_attempt_state(self, bar_type: str) -> None:
        self._clear_pending_potion_send(bar_type)
        self._set_potion_effect_attempts(bar_type, [])
        self._reset_potion_no_effect_count(bar_type)
        self._set_potion_recent_samples(bar_type, [])
        self._set_potion_damage_pressure_active(bar_type, False)
        self._set_potion_recent_damage_at(bar_type, -999.0)

    def _potion_no_effect_count(self, bar_type: str) -> int:
        return self.hp_potion_no_effect_count if bar_type == "hp" else self.mp_potion_no_effect_count

    def _set_potion_no_effect_count(self, bar_type: str, count: int) -> None:
        if bar_type == "hp":
            self.hp_potion_no_effect_count = count
        else:
            self.mp_potion_no_effect_count = count

    def _reset_potion_no_effect_count(self, bar_type: str) -> None:
        self._set_potion_no_effect_count(bar_type, 0)
        self._set_potion_last_no_effect_counted_at(bar_type, -999.0)

    def _potion_last_no_effect_counted_at(self, bar_type: str) -> float:
        if bar_type == "hp":
            return getattr(self, "hp_potion_last_no_effect_counted_at", -999.0)
        return getattr(self, "mp_potion_last_no_effect_counted_at", -999.0)

    def _set_potion_last_no_effect_counted_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.hp_potion_last_no_effect_counted_at = now
        else:
            self.mp_potion_last_no_effect_counted_at = now

    def _pending_potion_send_at(self, bar_type: str) -> float:
        if bar_type == "hp":
            return getattr(self, "hp_pending_potion_send_at", -999.0)
        return getattr(self, "mp_pending_potion_send_at", -999.0)

    def _pending_potion_send_percent(self, bar_type: str) -> float | None:
        if bar_type == "hp":
            return getattr(self, "hp_pending_potion_send_percent", None)
        return getattr(self, "mp_pending_potion_send_percent", None)

    def _schedule_pending_potion_send(self, bar_type: str, due_at: float, percent: float) -> None:
        if bar_type == "hp":
            self.hp_pending_potion_send_at = due_at
            self.hp_pending_potion_send_percent = percent
        else:
            self.mp_pending_potion_send_at = due_at
            self.mp_pending_potion_send_percent = percent

    def _clear_pending_potion_send(self, bar_type: str) -> None:
        if bar_type == "hp":
            self.hp_pending_potion_send_at = -999.0
            self.hp_pending_potion_send_percent = None
        else:
            self.mp_pending_potion_send_at = -999.0
            self.mp_pending_potion_send_percent = None

    def _next_pending_potion_send_at(self) -> float | None:
        pending_times = [
            due_at
            for due_at in (
                self._pending_potion_send_at("hp"),
                self._pending_potion_send_at("mp"),
            )
            if due_at > -100.0
        ]
        if not pending_times:
            return None
        return min(pending_times)

    def _last_potion_drink_at(self, bar_type: str) -> float:
        return self.last_hp_drink_at if bar_type == "hp" else self.last_mp_drink_at

    def _set_last_potion_drink_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.last_hp_drink_at = now
        else:
            self.last_mp_drink_at = now

    def _update_potion_damage_context(self, bar_type: str, percent: float, now: float) -> None:
        last_percent = self._potion_last_observed_percent(bar_type)
        self._set_potion_last_observed_percent(bar_type, percent)
        if last_percent is None:
            return
        if last_percent - percent > POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT:
            self._mark_potion_recent_damage(bar_type, now)

    def _mark_potion_recent_damage(self, bar_type: str, now: float) -> None:
        self._set_potion_recent_damage_at(bar_type, now)
        self._set_potion_damage_pressure_active(bar_type, True)
        self._reset_potion_no_effect_count(bar_type)

    def _potion_recent_damage_is_active(self, bar_type: str, now: float) -> bool:
        if now - self._potion_recent_damage_at(bar_type) <= POTION_EFFECT_DAMAGE_GRACE_SECONDS:
            return True
        self._set_potion_damage_pressure_active(bar_type, False)
        return False

    def _potion_recent_damage_blocks_stable_confirmation(self, bar_type: str, now: float) -> bool:
        return now - self._potion_recent_damage_at(bar_type) <= self._potion_stability_confirmation_seconds(bar_type)

    def _potion_auto_hold_is_allowed(self, bar_type: str) -> bool:
        return bar_type in POTION_EFFECT_AUTO_HOLD_BAR_TYPES

    def _record_potion_percent_sample(self, bar_type: str, now: float, percent: float) -> None:
        cutoff = now - self._potion_stability_confirmation_seconds(bar_type)
        samples = [
            sample
            for sample in [*self._potion_recent_samples(bar_type), (now, percent)]
            if sample[0] >= cutoff
        ]
        self._set_potion_recent_samples(bar_type, samples)

    def _potion_pre_window_is_stable(self, bar_type: str, now: float, before_percent: float) -> bool:
        if self._potion_recent_damage_is_active(bar_type, now):
            return False
        samples = [
            percent
            for observed_at, percent in self._potion_recent_samples(bar_type)
            if now - observed_at <= POTION_EFFECT_PRE_OBSERVATION_SECONDS
        ]
        if len(samples) < POTION_EFFECT_PRE_OBSERVATION_MIN_SAMPLES:
            return False
        samples = [*samples, before_percent]
        if max(samples) - min(samples) > POTION_EFFECT_PRE_OBSERVATION_VOLATILITY_TOLERANCE_PERCENT:
            return False
        return abs(samples[-2] - before_percent) <= POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT

    def _potion_bar_is_stable_for_confirmation(self, bar_type: str, now: float) -> bool:
        if self._potion_recent_damage_is_active(bar_type, now):
            return False
        confirmation_seconds = self._potion_stability_confirmation_seconds(bar_type)
        if now - self._potion_recent_damage_at(bar_type) <= confirmation_seconds:
            return False
        samples = [
            percent
            for observed_at, percent in self._potion_recent_samples(bar_type)
            if now - observed_at <= confirmation_seconds
        ]
        if len(samples) < self._potion_stability_confirmation_min_samples(bar_type):
            return False
        if max(samples) - min(samples) > self._potion_stability_confirmation_volatility_tolerance(bar_type):
            return False
        return all(
            abs(current - previous) <= POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            for previous, current in zip(samples, samples[1:])
        )

    def _potion_stability_confirmation_seconds(self, bar_type: str) -> float:
        if bar_type == "hp":
            return POTION_EFFECT_HP_STABILITY_CONFIRMATION_SECONDS
        return POTION_EFFECT_STABILITY_CONFIRMATION_SECONDS

    def _potion_stability_confirmation_min_samples(self, bar_type: str) -> int:
        if bar_type == "hp":
            return POTION_EFFECT_HP_STABILITY_CONFIRMATION_MIN_SAMPLES
        return POTION_EFFECT_STABILITY_CONFIRMATION_MIN_SAMPLES

    def _potion_stability_confirmation_volatility_tolerance(self, bar_type: str) -> float:
        if bar_type == "hp":
            return POTION_EFFECT_HP_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT
        return POTION_EFFECT_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT

    def _potion_recent_samples(self, bar_type: str) -> list[tuple[float, float]]:
        if bar_type == "hp":
            return getattr(self, "hp_potion_recent_samples", [])
        return getattr(self, "mp_potion_recent_samples", [])

    def _set_potion_recent_samples(self, bar_type: str, samples: list[tuple[float, float]]) -> None:
        if bar_type == "hp":
            self.hp_potion_recent_samples = samples
        else:
            self.mp_potion_recent_samples = samples

    def _potion_last_observed_percent(self, bar_type: str) -> float | None:
        if bar_type == "hp":
            return getattr(self, "hp_potion_last_observed_percent", None)
        return getattr(self, "mp_potion_last_observed_percent", None)

    def _set_potion_last_observed_percent(self, bar_type: str, percent: float | None) -> None:
        if bar_type == "hp":
            self.hp_potion_last_observed_percent = percent
        else:
            self.mp_potion_last_observed_percent = percent

    def _potion_recent_damage_at(self, bar_type: str) -> float:
        if bar_type == "hp":
            return getattr(self, "hp_potion_recent_damage_at", -999.0)
        return getattr(self, "mp_potion_recent_damage_at", -999.0)

    def _set_potion_recent_damage_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.hp_potion_recent_damage_at = now
        else:
            self.mp_potion_recent_damage_at = now

    def _potion_damage_pressure_active(self, bar_type: str) -> bool:
        if bar_type == "hp":
            return getattr(self, "hp_potion_damage_pressure_active", False)
        return getattr(self, "mp_potion_damage_pressure_active", False)

    def _set_potion_damage_pressure_active(self, bar_type: str, active: bool) -> None:
        if bar_type == "hp":
            self.hp_potion_damage_pressure_active = active
        else:
            self.mp_potion_damage_pressure_active = active

    def _out_of_potion_hold(self, bar_type: str) -> OutOfPotionHold | None:
        return self.hp_out_of_potion_hold if bar_type == "hp" else self.mp_out_of_potion_hold

    def _set_out_of_potion_hold(self, bar_type: str, hold: OutOfPotionHold | None) -> None:
        if bar_type == "hp":
            self.hp_out_of_potion_hold = hold
        else:
            self.mp_out_of_potion_hold = hold

    def _has_out_of_potion_hold(self) -> bool:
        return self.hp_out_of_potion_hold is not None or self.mp_out_of_potion_hold is not None

    def _out_of_potion_hold_status_message(self) -> str:
        held_labels = []
        if self.hp_out_of_potion_hold is not None:
            held_labels.append("HP")
        if self.mp_out_of_potion_hold is not None:
            held_labels.append("MP")
        label = "/".join(held_labels) if held_labels else "HP/MP"
        return f"{label} 檢查藥水"

    def _update_potion_effect_watch_cycle(
        self,
        bar_type: str,
        label: str,
        percent: float,
        threshold_percent: float,
        now: float,
        *,
        alert_suspected_no_potion,
    ) -> bool:
        if self._out_of_potion_hold(bar_type) is not None:
            return True
        self._record_potion_percent_sample(bar_type, now, percent)
        self._update_potion_damage_context(bar_type, percent, now)
        if not should_drink_for_threshold(percent, threshold_percent):
            self._clear_potion_attempt_state(bar_type)
            return True
        if self._potion_recent_damage_blocks_stable_confirmation(bar_type, now):
            self._reset_potion_no_effect_count(bar_type)
        bar_is_stable = self._potion_bar_is_stable_for_confirmation(bar_type, now)

        attempts = self._potion_effect_attempts(bar_type)
        if not bar_is_stable and not attempts:
            self._reset_potion_no_effect_count(bar_type)
        if not attempts:
            return True
        attempts = [attempt.with_observed_percent(percent) for attempt in attempts]
        if any(
            attempt.before_percent - percent > POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            for attempt in attempts
        ):
            self._mark_potion_recent_damage(bar_type, now)
        matured_attempts = [
            attempt
            for attempt in attempts
            if now - attempt.attempted_at >= POTION_EFFECT_OBSERVATION_SECONDS
        ]
        if not matured_attempts:
            self._set_potion_effect_attempts(bar_type, attempts)
            return True
        pending_attempts = [
            attempt
            for attempt in attempts
            if now - attempt.attempted_at < POTION_EFFECT_OBSERVATION_SECONDS
        ]
        if any(
            percent - attempt.before_percent > POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            for attempt in matured_attempts
        ):
            self._clear_potion_attempt_state(bar_type)
            return True

        has_quiet_no_effect = any(
            attempt.pre_window_is_stable
            and abs(percent - attempt.before_percent) <= POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            and attempt.min_percent >= attempt.before_percent - POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            and attempt.max_percent - attempt.min_percent <= POTION_EFFECT_WATCH_VOLATILITY_TOLERANCE_PERCENT
            for attempt in matured_attempts
        )
        self._set_potion_effect_attempts(bar_type, pending_attempts)
        if not has_quiet_no_effect:
            self._reset_potion_no_effect_count(bar_type)
            return True
        if not bar_is_stable:
            return True
        if self._potion_recent_damage_is_active(bar_type, now):
            return True
        if not self._potion_auto_hold_is_allowed(bar_type):
            self._reset_potion_no_effect_count(bar_type)
            return True
        if (
            now - self._potion_last_no_effect_counted_at(bar_type) + POTION_TIME_EPSILON_SECONDS
            < POTION_EFFECT_OBSERVATION_SECONDS
        ):
            return True

        no_effect_count = self._potion_no_effect_count(bar_type) + 1
        self._set_potion_no_effect_count(bar_type, no_effect_count)
        self._set_potion_last_no_effect_counted_at(bar_type, now)
        if no_effect_count >= POTION_EFFECT_NO_EFFECT_LIMIT:
            alert_suspected_no_potion(bar_type, label, percent, now)
        return True



    def _maybe_drink_potion(
        self,
        bar_type: str,
        label: str,
        now: float,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
        key_name: str,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
        *,
        challenge_paused: bool,
        release_key,
        clear_bar_state,
        capture_transient,
        emit_failure_warning,
        log_unstable,
        should_drink,
        cooldown_seconds,
        is_active_before_send,
        play_blocked_sound,
        can_fast_repeat,
        capture_confirmed,
        log_trigger_interval,
        execute_command,
        set_last_action,
    ) -> None:
        if challenge_paused:
            release_key(bar_type)
            self._clear_pending_potion_send(bar_type)
            return
        if not enabled:
            clear_bar_state(bar_type)
            return
        if self._out_of_potion_hold(bar_type) is not None:
            release_key(bar_type)
            return
        if self._bar_has_pending_command(bar_type):
            return
        if percent is None:
            percent = capture_transient(bar_type)
            if percent is None:
                release_key(bar_type)
                emit_failure_warning(now)
                log_unstable(now, label)
                return
        if not should_drink(
            percent,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
        ):
            release_key(bar_type)
            self._clear_potion_attempt_state(bar_type)
            return
        if not continuous_enabled:
            last_drink_at = self._last_potion_drink_at(bar_type)
            if last_drink_at > -100.0:
                elapsed_since_drink = now - last_drink_at
                if elapsed_since_drink + POTION_TIME_EPSILON_SECONDS < cooldown_seconds(bar_type):
                    self._schedule_pending_potion_send(
                        bar_type,
                        last_drink_at + cooldown_seconds(bar_type),
                        percent,
                    )
                    return
        if not is_active_before_send(label, now):
            if continuous_enabled:
                release_key(bar_type)
            play_blocked_sound(now)
            return

        if can_fast_repeat(bar_type):
            confirmed_percent = percent
        else:
            confirmed_percent = capture_confirmed(bar_type, percent)
        percent = confirmed_percent
        if percent is None:
            if continuous_enabled:
                release_key(bar_type)
            emit_failure_warning(now)
            log_unstable(now, label)
            play_blocked_sound(now)
            return
        if not should_drink(
            percent,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
        ):
            release_key(bar_type)
            self._clear_potion_attempt_state(bar_type)
            return
        if continuous_enabled:
            previous_at = self._last_potion_drink_at(bar_type)
            command = self._new_command(
                bar_type,
                "hold",
                key_name,
                percent,
                now,
                previous_drink_at=previous_at,
                continuous=True,
            )
            result = execute_command(command)
            if result is not None:
                self.complete_command_result(
                    result,
                    log_trigger_interval=log_trigger_interval,
                    set_last_action=set_last_action,
                    play_blocked_sound=play_blocked_sound,
                )
                if result.outcome == "invalid_key":
                    release_key(bar_type)
            return

        previous_at = self._last_potion_drink_at(bar_type)
        command = self._new_command(
            bar_type,
            "tap",
            key_name,
            percent,
            now,
            previous_drink_at=previous_at,
            clear_pending_on_success=True,
        )
        result = execute_command(command)
        if result is not None:
            self.complete_command_result(
                result,
                log_trigger_interval=log_trigger_interval,
                set_last_action=set_last_action,
                play_blocked_sound=play_blocked_sound,
            )



    def _continuous_stop_threshold_percent(self, threshold_percent: float, margin_percent: float) -> float:
        try:
            margin = float(margin_percent)
        except (TypeError, ValueError):
            margin = 0.0
        margin = max(0.0, min(POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT, margin))
        return max(1.0, float(threshold_percent) - margin)

    def _potion_priority_defer_until_for_bar(
        self,
        bar_type: str,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
        now: float,
    ) -> float:
        if not self._should_defer_experience_for_potion_bar(
            bar_type,
            percent,
            enabled,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
            now,
        ):
            return 0.0
        defer_until = now + POTION_EXPERIENCE_DEFER_SECONDS
        last_drink_at = self._last_potion_drink_at(bar_type)
        if last_drink_at > -100.0:
            defer_until = max(defer_until, last_drink_at + POTION_EXPERIENCE_DEFER_SECONDS)
        pending_send_at = self._pending_potion_send_at(bar_type)
        if pending_send_at > -100.0 and now + POTION_TIME_EPSILON_SECONDS >= pending_send_at:
            defer_until = max(defer_until, now + POTION_EXPERIENCE_DEFER_SECONDS)
        return defer_until

    def _should_defer_experience_for_potion_bar(
        self,
        bar_type: str,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
        now: float,
    ) -> bool:
        if not enabled or self._out_of_potion_hold(bar_type) is not None:
            return False
        if self._potion_held_vk(bar_type):
            return True
        pending_send_at = self._pending_potion_send_at(bar_type)
        if pending_send_at > -100.0 and now + POTION_TIME_EPSILON_SECONDS >= pending_send_at:
            return True
        if percent is not None and self._should_drink_for_current_mode(
            percent,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
        ):
            return True
        return now - self._last_potion_drink_at(bar_type) < POTION_EXPERIENCE_DEFER_SECONDS

    def _should_drink_for_current_mode(
        self,
        percent: float,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
    ) -> bool:
        if not continuous_enabled:
            return should_drink_for_threshold(percent, threshold_percent)
        return should_continue_continuous_drink(
            percent,
            self._continuous_stop_threshold_percent(threshold_percent, continuous_stop_margin_percent),
        )

    def _process_due_potion_send(
        self,
        bar_type: str,
        label: str,
        now: float,
        enabled: bool,
        threshold_percent: float,
        key_name: str,
        continuous_enabled: bool,
        *,
        gameplay_hud_active: bool,
        cooldown_seconds,
        is_active_before_send,
        execute_command,
        log_trigger_interval,
        set_last_action,
    ) -> None:
        due_at = self._pending_potion_send_at(bar_type)
        if due_at <= -100.0 or now + POTION_TIME_EPSILON_SECONDS < due_at:
            return
        if self._bar_has_pending_command(bar_type):
            return
        percent = self._pending_potion_send_percent(bar_type)
        if (
            not enabled
            or continuous_enabled
            or self._out_of_potion_hold(bar_type) is not None
            or percent is None
            or not should_drink_for_threshold(percent, threshold_percent)
        ):
            self._clear_pending_potion_send(bar_type)
            return
        previous_at = self._last_potion_drink_at(bar_type)
        if previous_at > -100.0:
            cooldown_seconds = cooldown_seconds(bar_type)
            if now - previous_at + POTION_TIME_EPSILON_SECONDS < cooldown_seconds:
                self._schedule_pending_potion_send(bar_type, previous_at + cooldown_seconds, percent)
                return
        if gameplay_hud_active:
            self.potion_send_prevalidated_at = now
        command = self._new_command(
            bar_type,
            "tap",
            key_name,
            percent,
            now,
            previous_drink_at=previous_at,
            clear_pending_on_success=True,
        )
        result = execute_command(command)
        if result is not None:
            self.complete_command_result(
                result,
                log_trigger_interval=log_trigger_interval,
                set_last_action=set_last_action,
                play_blocked_sound=lambda _completed_at: None,
            )



    def snapshot(self) -> PotionEngineSnapshot:
        return PotionEngineSnapshot(
            hp_pending_send_at=self.hp_pending_potion_send_at,
            mp_pending_send_at=self.mp_pending_potion_send_at,
            hp_held_vk=self.hp_potion_held_vk,
            mp_held_vk=self.mp_potion_held_vk,
            has_out_of_potion_hold=(
                self.hp_out_of_potion_hold is not None or self.mp_out_of_potion_hold is not None
            ),
            next_due_at=self._next_pending_potion_send_at(),
            priority_defer_until=(self.runtime_potion_action_defer_until or None),
            hp_status=self._bar_status("hp"),
            mp_status=self._bar_status("mp"),
            hp_no_effect_count=self.hp_potion_no_effect_count,
            mp_no_effect_count=self.mp_potion_no_effect_count,
        )

    def _bar_status(self, bar_type: BarType) -> str:
        if self._out_of_potion_hold(bar_type) is not None:
            return "out_of_potion"
        if self._potion_held_vk(bar_type):
            return "held"
        if self._bar_has_pending_command(bar_type):
            return "command_pending"
        if self._pending_potion_send_at(bar_type) > -100.0:
            return "scheduled"
        return "idle"


__all__ = [
    "PotionBarConfig",
    "PotionCommand",
    "PotionCommandResult",
    "PotionEngine",
    "PotionEngineSnapshot",
    "PotionSample",
]
