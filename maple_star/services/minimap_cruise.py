from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from ..adapters.win_input import key_down, key_up, parse_vk_key, tap_key
from ..models.settings import (
    AutoPotionSettings,
    MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT,
    normalize_minimap_cruise_direction,
)

MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS = 1.0
MINIMAP_CRUISE_STATIONARY_TURN_SECONDS = 1.5
MINIMAP_CRUISE_STATIONARY_X_TOLERANCE_PIXELS = 2
MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS = 0.35
MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS = 0.0
MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS = 0.30
MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS = 0.0
MINIMAP_CRUISE_CAPTURE_PADDING_PIXELS = 240
MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS = 3
MINIMAP_CRUISE_CENTER_DEADZONE_PIXELS = 3
MINIMAP_CRUISE_LIE_DETECTOR_CHECK_INTERVAL_SECONDS = 0.5
MINIMAP_CRUISE_LIE_DETECTOR_ALERT_INTERVAL_SECONDS = 1.0
MINIMAP_CRUISE_LIE_DETECTOR_MATCH_THRESHOLD = 0.82
MINIMAP_CRUISE_RED_PLAYER_CHECK_INTERVAL_SECONDS = 1.0
MINIMAP_CRUISE_RED_PLAYER_ALERT_AFTER_SECONDS = 60.0
MINIMAP_CRUISE_RED_PLAYER_ALERT_INTERVAL_SECONDS = 1.0
MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS = 2.0
MINIMAP_CRUISE_OUT_OF_BOUNDS_RECOVERY_INTERVAL_SECONDS = 0.5
MINIMAP_CRUISE_RECOVERY_STUCK_CONFIRMATIONS = 2

MINIMAP_CRUISE_STATUS_STOPPED = "stopped"
MINIMAP_CRUISE_STATUS_STARTING = "starting"
MINIMAP_CRUISE_STATUS_ATTACKING = "attacking"
MINIMAP_CRUISE_STATUS_SUSPENDED = "suspended"
MINIMAP_CRUISE_STATUS_TURNING = "turning"
MINIMAP_CRUISE_STATUS_LIE_DETECTOR = "lie_detector"
MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL = "pre_boundary_skill"
MINIMAP_CRUISE_STATUS_RECOVERING = "recovering"

LEFT_DIRECTION_VK = 0x25
RIGHT_DIRECTION_VK = 0x27
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIE_DETECTOR_BOMB_TEMPLATE_PATH = PROJECT_ROOT / "maple_star" / "assets" / "minimap_cruise_lie_detector_bomb.png"
_LIE_DETECTOR_BOMB_TEMPLATE: tuple[np.ndarray, np.ndarray | None] | None = None


class CaptureProvider(Protocol):
    def __call__(self, monitor: dict[str, int]) -> np.ndarray:
        ...


@dataclass
class MinimapCruiseRuntime:
    settings: AutoPotionSettings
    is_target_window_active: Callable[[], bool]
    can_run_actions: Callable[[], bool]
    is_action_blocked: Callable[[], bool]
    target_client_bounds_provider: Callable[[], tuple[int, int, int, int] | None]
    capture_provider: CaptureProvider
    set_status: Callable[[str], None] | None = None
    lie_detector_alert_func: Callable[[float], None] | None = None
    red_player_alert_func: Callable[[float], None] | None = None
    key_down_func: Callable[[int], None] = key_down
    key_up_func: Callable[[int], None] = key_up
    tap_key_func: Callable[[int], None] = tap_key
    parse_vk_key_func: Callable[[str], int] = parse_vk_key
    enabled: bool = False
    status: str = MINIMAP_CRUISE_STATUS_STOPPED
    current_direction: str = "right"
    attack_held_vk: int = 0
    next_detect_at: float = 0.0
    last_detected_x: int | None = None
    stationary_x: int | None = None
    stationary_started_at: float | None = None
    consecutive_detection_failures: int = 0
    last_message: str = ""
    turn_direction_vk: int = 0
    turn_held_vk: int = 0
    turn_key_down_at: float | None = None
    turn_key_up_at: float | None = None
    resume_attack_at: float | None = None
    turn_confirmation_boundary: str | None = None
    next_lie_detector_check_at: float = 0.0
    next_lie_detector_alert_at: float = 0.0
    next_red_player_check_at: float = 0.0
    next_red_player_alert_at: float = 0.0
    red_player_present_since: float | None = None
    red_player_alert_active: bool = False
    pre_boundary_skill_held_vk: int = 0
    pre_boundary_skill_key_up_at: float | None = None
    pre_boundary_skill_triggered_boundary: str | None = None
    recovery_boundary: str | None = None
    recovery_last_x: int | None = None
    recovery_direction_vk: int = 0
    recovery_held_vk: int = 0
    recovery_stuck_confirmations: int = 0
    periodic_key_next_at: dict[int, float] = field(default_factory=dict)
    _last_status_report: str = field(default="", init=False)

    def toggle(self, now: float) -> bool:
        if self.enabled:
            self.stop("小地圖巡航已停用")
            return False

        if not self._has_configured_boundaries():
            self._report_status("請先設定小地圖邊界")
            return False
        if self._configured_attack_vk() is None:
            self._report_status("小地圖巡航攻擊鍵設定無效")
            return False

        self.enabled = True
        self.status = MINIMAP_CRUISE_STATUS_STARTING
        self.next_detect_at = now
        self.next_lie_detector_check_at = now
        self.next_lie_detector_alert_at = now
        self.next_red_player_check_at = now
        self.next_red_player_alert_at = now
        self.red_player_present_since = None
        self.red_player_alert_active = False
        self.pre_boundary_skill_triggered_boundary = None
        self._reset_periodic_key_schedule(now)
        self._reset_stationary_tracking()
        self.consecutive_detection_failures = 0
        self.last_message = "小地圖巡航已啟用"
        self._report_status(self.last_message)
        return True

    def stop(self, message: str = "小地圖巡航已停用") -> None:
        self.enabled = False
        self.status = MINIMAP_CRUISE_STATUS_STOPPED
        self._cancel_turn()
        self._cancel_pre_boundary_skill()
        self._cancel_recovery()
        self._release_attack_key()
        self._reset_stationary_tracking()
        self.next_lie_detector_alert_at = 0.0
        self.pre_boundary_skill_triggered_boundary = None
        self.periodic_key_next_at.clear()
        self._reset_red_player_alert()
        self.last_message = message
        self._report_status(message)

    def update(self, now: float) -> None:
        if not self.enabled:
            return

        if self.status == MINIMAP_CRUISE_STATUS_LIE_DETECTOR:
            self._play_lie_detector_alert(now)
            return

        if not self._can_send_actions():
            self._suspend("小地圖巡航暫停")
            return

        self._update_red_player_alert(now)

        if self._lie_detector_challenge_visible(now):
            self._block_for_lie_detector(now)
            return

        self._update_periodic_keys(now)

        if self.status == MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL:
            self._update_pre_boundary_skill(now)
            return

        if self.status == MINIMAP_CRUISE_STATUS_TURNING:
            self._update_turn(now)
            return

        if now + 1e-9 < self.next_detect_at:
            return
        self.next_detect_at = now + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS

        character_x = self._capture_character_x()
        if character_x is None:
            self.consecutive_detection_failures += 1
            self._suspend("小地圖巡航：找不到角色點")
            return

        self.consecutive_detection_failures = 0
        self.last_detected_x = character_x
        self._update_stationary_tracking(character_x, now)
        self.current_direction = self._initial_or_current_direction(character_x)
        self.settings.minimap_cruise_last_direction = self.current_direction
        out_of_bounds_direction = self._direction_toward_bounds_if_outside(character_x)
        forced_direction = self._forced_direction_toward_bounds(character_x)

        if self.status == MINIMAP_CRUISE_STATUS_RECOVERING:
            if out_of_bounds_direction is None:
                self._finish_recovery(now)
            else:
                self._update_recovery(character_x, out_of_bounds_direction, now)
            return

        if out_of_bounds_direction is not None:
            if self.turn_confirmation_boundary is not None and self.current_direction == out_of_bounds_direction:
                self._update_recovery(character_x, out_of_bounds_direction, now)
            else:
                self._begin_turn(out_of_bounds_direction, self._boundary_for_out_of_bounds_direction(out_of_bounds_direction), now)
            return

        if self._needs_turn_retry(character_x):
            self._begin_turn(self.current_direction, self.turn_confirmation_boundary, now)
            return
        self.turn_confirmation_boundary = None
        if self._maybe_begin_pre_boundary_skill(character_x, now):
            return
        if self._should_turn(character_x):
            self._turn(now)
            return

        if self._stationary_too_long(now):
            self._turn(now)
            return

        self._hold_attack_key()
        self.status = MINIMAP_CRUISE_STATUS_ATTACKING
        self.last_message = "小地圖巡航中"

    def status_text(self) -> str:
        if not self.enabled:
            return "--"
        if self.status == MINIMAP_CRUISE_STATUS_LIE_DETECTOR:
            return "巡航(測謊暫停)"
        if self.status == MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL:
            return "巡航(邊界前技能)"
        if self.status == MINIMAP_CRUISE_STATUS_RECOVERING:
            return "巡航(復位中)"
        direction = "左" if self.current_direction == "left" else "右"
        x_text = "--" if self.last_detected_x is None else str(self.last_detected_x)
        return f"巡航({direction}, X={x_text})"

    def set_boundaries(self, first: tuple[int, int], second: tuple[int, int]) -> None:
        left_x, right_x = sorted((int(first[0]), int(second[0])))
        detect_y = round((int(first[1]) + int(second[1])) / 2)
        self.settings.minimap_cruise_left_x = left_x
        self.settings.minimap_cruise_right_x = right_x
        self.settings.minimap_cruise_detect_y = detect_y
        self.settings.minimap_cruise_detect_band_height = max(
            int(self.settings.minimap_cruise_detect_band_height),
            MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT,
        )

    def _has_configured_boundaries(self) -> bool:
        return (
            self.settings.minimap_cruise_left_x is not None
            and self.settings.minimap_cruise_right_x is not None
            and self.settings.minimap_cruise_detect_y is not None
        )

    def _configured_attack_vk(self) -> int | None:
        try:
            return self.parse_vk_key_func(self.settings.minimap_cruise_attack_key)
        except ValueError:
            return None

    def _can_send_actions(self) -> bool:
        return self.can_run_actions() and self.is_target_window_active() and not self.is_action_blocked()

    def _suspend(self, message: str) -> None:
        self._cancel_turn()
        self._cancel_pre_boundary_skill()
        self._cancel_recovery()
        self._release_attack_key()
        self.periodic_key_next_at.clear()
        self._reset_stationary_tracking()
        self.status = MINIMAP_CRUISE_STATUS_SUSPENDED
        self.last_message = message
        self._report_status(message)

    def _block_for_lie_detector(self, now: float) -> None:
        self._cancel_turn()
        self._cancel_pre_boundary_skill()
        self._cancel_recovery()
        self._release_attack_key()
        self._reset_stationary_tracking()
        self.status = MINIMAP_CRUISE_STATUS_LIE_DETECTOR
        self.last_message = "小地圖巡航：偵測到測謊視窗"
        self._report_status(self.last_message)
        self._play_lie_detector_alert(now)

    def _play_lie_detector_alert(self, now: float) -> None:
        if self.lie_detector_alert_func is None:
            return
        if now + 1e-9 < self.next_lie_detector_alert_at:
            return
        self.next_lie_detector_alert_at = now + MINIMAP_CRUISE_LIE_DETECTOR_ALERT_INTERVAL_SECONDS
        self.lie_detector_alert_func(now)

    def _update_red_player_alert(self, now: float) -> None:
        if now + 1e-9 >= self.next_red_player_check_at:
            self.next_red_player_check_at = now + MINIMAP_CRUISE_RED_PLAYER_CHECK_INTERVAL_SECONDS
            red_player_visible = self._minimap_red_player_visible()
            if red_player_visible:
                if self.red_player_present_since is None:
                    self.red_player_present_since = now
                if now - self.red_player_present_since >= MINIMAP_CRUISE_RED_PLAYER_ALERT_AFTER_SECONDS:
                    if not self.red_player_alert_active:
                        self.red_player_alert_active = True
                        self.last_message = "小地圖巡航：其他玩家紅點超過 1 分鐘"
                        self._report_status(self.last_message)
                    self._play_red_player_alert(now)
                return
            if self.red_player_alert_active:
                self.last_message = "小地圖巡航：其他玩家紅點已消失"
                self._report_status(self.last_message)
            self._reset_red_player_alert()
            return

        if self.red_player_alert_active:
            self._play_red_player_alert(now)

    def _play_red_player_alert(self, now: float) -> None:
        if self.red_player_alert_func is None:
            return
        if now + 1e-9 < self.next_red_player_alert_at:
            return
        self.next_red_player_alert_at = now + MINIMAP_CRUISE_RED_PLAYER_ALERT_INTERVAL_SECONDS
        self.red_player_alert_func(now)

    def _reset_red_player_alert(self) -> None:
        self.red_player_present_since = None
        self.red_player_alert_active = False
        self.next_red_player_alert_at = 0.0

    def _hold_attack_key(self) -> bool:
        attack_vk = self._configured_attack_vk()
        if attack_vk is None:
            self._suspend("小地圖巡航攻擊鍵設定無效")
            return False
        if self.attack_held_vk == attack_vk:
            return True
        self._release_attack_key()
        self.key_down_func(attack_vk)
        self.attack_held_vk = attack_vk
        return True

    def _release_attack_key(self) -> None:
        held_vk = self.attack_held_vk
        if not held_vk:
            return
        try:
            self.key_up_func(held_vk)
        finally:
            self.attack_held_vk = 0

    def _configured_pre_boundary_skill_vk(self) -> int | None:
        key = self.settings.minimap_cruise_pre_boundary_skill_key.strip()
        if not key:
            return None
        try:
            return self.parse_vk_key_func(key)
        except ValueError:
            return None

    def _periodic_key_slots(self) -> tuple[tuple[int, bool, str, float], ...]:
        return (
            (
                1,
                self.settings.minimap_cruise_periodic_key_1_enabled,
                self.settings.minimap_cruise_periodic_key_1,
                float(self.settings.minimap_cruise_periodic_key_1_interval_seconds),
            ),
            (
                2,
                self.settings.minimap_cruise_periodic_key_2_enabled,
                self.settings.minimap_cruise_periodic_key_2,
                float(self.settings.minimap_cruise_periodic_key_2_interval_seconds),
            ),
            (
                3,
                self.settings.minimap_cruise_periodic_key_3_enabled,
                self.settings.minimap_cruise_periodic_key_3,
                float(self.settings.minimap_cruise_periodic_key_3_interval_seconds),
            ),
        )

    def _configured_periodic_key_vk(self, key: str) -> int | None:
        normalized = key.strip()
        if not normalized:
            return None
        try:
            return self.parse_vk_key_func(normalized)
        except ValueError:
            return None

    def _reset_periodic_key_schedule(self, now: float) -> None:
        self.periodic_key_next_at.clear()
        for index, enabled, key, interval in self._periodic_key_slots():
            if enabled and self._configured_periodic_key_vk(key) is not None and interval > 0.0:
                self.periodic_key_next_at[index] = now + interval

    def _update_periodic_keys(self, now: float) -> None:
        active_indexes: set[int] = set()
        for index, enabled, key, interval in self._periodic_key_slots():
            active_indexes.add(index)
            vk = self._configured_periodic_key_vk(key)
            if not enabled or vk is None or interval <= 0.0:
                self.periodic_key_next_at.pop(index, None)
                continue

            next_at = self.periodic_key_next_at.get(index)
            if next_at is None:
                self.periodic_key_next_at[index] = now + interval
                continue
            if now + 1e-9 < next_at:
                continue

            self.tap_key_func(vk)
            self.periodic_key_next_at[index] = now + interval

        for index in tuple(self.periodic_key_next_at):
            if index not in active_indexes:
                self.periodic_key_next_at.pop(index, None)

    def _initial_or_current_direction(self, character_x: int) -> str:
        if self.status not in {MINIMAP_CRUISE_STATUS_STARTING, MINIMAP_CRUISE_STATUS_SUSPENDED}:
            return normalize_minimap_cruise_direction(self.current_direction, "right")
        left_x, right_x = self._normalized_bounds()
        midpoint = (left_x + right_x) / 2.0
        if character_x < midpoint - MINIMAP_CRUISE_CENTER_DEADZONE_PIXELS:
            return "right"
        if character_x > midpoint + MINIMAP_CRUISE_CENTER_DEADZONE_PIXELS:
            return "left"
        return normalize_minimap_cruise_direction(self.settings.minimap_cruise_last_direction, "right")

    def _should_turn(self, character_x: int) -> bool:
        forced_direction = self._forced_direction_toward_bounds(character_x)
        if forced_direction is not None:
            return True
        left_x, right_x = self._normalized_bounds()
        if self.current_direction == "left":
            return character_x <= left_x + MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS
        return character_x >= right_x - MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS

    def _turn(self, now: float) -> None:
        self._reset_stationary_tracking()
        self._cancel_recovery()
        self.pre_boundary_skill_triggered_boundary = None
        forced_direction = None if self.last_detected_x is None else self._forced_direction_toward_bounds(self.last_detected_x)
        boundary = "left" if self.current_direction == "left" else "right"
        next_direction = "right" if self.current_direction == "left" else "left"
        if forced_direction is not None:
            next_direction = forced_direction
            boundary = "left" if forced_direction == "right" else "right"
        self._begin_turn(next_direction, boundary, now)

    def _forced_direction_toward_bounds(self, character_x: int) -> str | None:
        left_x, right_x = self._normalized_bounds()
        if character_x < left_x - MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS:
            return "right"
        if character_x > right_x + MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS:
            return "left"
        return None

    def _direction_toward_bounds_if_outside(self, character_x: int) -> str | None:
        left_x, right_x = self._normalized_bounds()
        if character_x < left_x:
            return "right"
        if character_x > right_x:
            return "left"
        return None

    def _boundary_for_out_of_bounds_direction(self, direction: str) -> str:
        return "left" if direction == "right" else "right"

    def _maybe_begin_pre_boundary_skill(self, character_x: int, now: float) -> bool:
        if not self.settings.minimap_cruise_pre_boundary_skill_enabled:
            self.pre_boundary_skill_triggered_boundary = None
            return False
        skill_vk = self._configured_pre_boundary_skill_vk()
        if skill_vk is None:
            return False
        distance = max(0, int(self.settings.minimap_cruise_pre_boundary_distance))
        if distance <= 0:
            self.pre_boundary_skill_triggered_boundary = None
            return False

        left_x, right_x = self._normalized_bounds()
        boundary: str | None = None
        if self.current_direction == "left":
            if left_x <= character_x <= left_x + distance:
                boundary = "left"
        elif right_x - distance <= character_x <= right_x:
            boundary = "right"

        if boundary is None:
            self.pre_boundary_skill_triggered_boundary = None
            return False
        if self.pre_boundary_skill_triggered_boundary == boundary:
            return False

        self._begin_pre_boundary_skill(skill_vk, boundary, now)
        return True

    def _begin_pre_boundary_skill(self, skill_vk: int, boundary: str, now: float) -> None:
        self._cancel_turn()
        self._cancel_recovery()
        self.key_down_func(skill_vk)
        self.pre_boundary_skill_held_vk = skill_vk
        self.pre_boundary_skill_key_up_at = now + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS
        self.pre_boundary_skill_triggered_boundary = boundary
        self.status = MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL
        self.last_message = "小地圖巡航：邊界前技能"

    def _update_pre_boundary_skill(self, now: float) -> None:
        if not self._can_send_actions():
            self._suspend("小地圖巡航暫停")
            return
        if self.pre_boundary_skill_held_vk and self.pre_boundary_skill_key_up_at is not None:
            if now + 1e-9 < self.pre_boundary_skill_key_up_at:
                if self._handle_out_of_bounds_during_pre_boundary_skill(now):
                    return
                return
            self._cancel_pre_boundary_skill()
        if self._handle_boundary_after_pre_boundary_skill(now):
            return
        if not self._hold_attack_key():
            return
        self.status = MINIMAP_CRUISE_STATUS_ATTACKING
        self.last_message = "小地圖巡航中"
        self.next_detect_at = now

    def _handle_out_of_bounds_during_pre_boundary_skill(self, now: float) -> bool:
        character_x = self._capture_character_x()
        if character_x is None:
            return False

        self.consecutive_detection_failures = 0
        self.last_detected_x = character_x
        out_of_bounds_direction = self._direction_toward_bounds_if_outside(character_x)
        if out_of_bounds_direction is None:
            return False
        self._cancel_pre_boundary_skill()
        self._begin_turn(
            out_of_bounds_direction,
            self._boundary_for_out_of_bounds_direction(out_of_bounds_direction),
            now,
        )
        return True

    def _handle_boundary_after_pre_boundary_skill(self, now: float) -> bool:
        character_x = self._capture_character_x()
        if character_x is None:
            fallback_direction = self._direction_away_from_pre_boundary()
            if fallback_direction is None:
                return False
            self._begin_turn(fallback_direction, self.pre_boundary_skill_triggered_boundary, now)
            return True

        self.consecutive_detection_failures = 0
        self.last_detected_x = character_x
        self._update_stationary_tracking(character_x, now)
        self.current_direction = self._initial_or_current_direction(character_x)
        self.settings.minimap_cruise_last_direction = self.current_direction
        out_of_bounds_direction = self._direction_toward_bounds_if_outside(character_x)
        if out_of_bounds_direction is not None:
            self._begin_turn(
                out_of_bounds_direction,
                self._boundary_for_out_of_bounds_direction(out_of_bounds_direction),
                now,
            )
            return True
        if self._should_turn(character_x):
            self._turn(now)
            return True
        return False

    def _direction_away_from_pre_boundary(self) -> str | None:
        if self.pre_boundary_skill_triggered_boundary == "left":
            return "right"
        if self.pre_boundary_skill_triggered_boundary == "right":
            return "left"
        return None

    def _cancel_pre_boundary_skill(self) -> None:
        held_vk = self.pre_boundary_skill_held_vk
        if held_vk:
            try:
                self.key_up_func(held_vk)
            finally:
                self.pre_boundary_skill_held_vk = 0
        self.pre_boundary_skill_key_up_at = None

    def _update_recovery(self, character_x: int, direction: str, now: float) -> None:
        boundary = "left" if direction == "right" else "right"
        direction_vk = RIGHT_DIRECTION_VK if direction == "right" else LEFT_DIRECTION_VK

        is_new_recovery = self.status != MINIMAP_CRUISE_STATUS_RECOVERING or self.recovery_boundary != boundary
        if is_new_recovery:
            if not self._hold_attack_key():
                return
            self._cancel_turn()
            self._cancel_pre_boundary_skill()
            self._cancel_recovery()
            self.recovery_boundary = boundary
            self.recovery_last_x = character_x
            self.recovery_direction_vk = direction_vk
            self.current_direction = direction
            self.settings.minimap_cruise_last_direction = direction
            self.status = MINIMAP_CRUISE_STATUS_RECOVERING
            self.last_message = "小地圖巡航復位中"
            self.next_detect_at = now + MINIMAP_CRUISE_OUT_OF_BOUNDS_RECOVERY_INTERVAL_SECONDS
            return

        if not self.recovery_held_vk:
            if self._moving_toward_bounds(character_x):
                self.recovery_stuck_confirmations = 0
                if not self._hold_attack_key():
                    return
            else:
                self.recovery_stuck_confirmations += 1
                if self.recovery_stuck_confirmations >= MINIMAP_CRUISE_RECOVERY_STUCK_CONFIRMATIONS:
                    self._release_attack_key()
                    self.key_down_func(direction_vk)
                    self.recovery_held_vk = direction_vk
        self.recovery_last_x = character_x
        self.current_direction = direction
        self.settings.minimap_cruise_last_direction = direction
        self.status = MINIMAP_CRUISE_STATUS_RECOVERING
        self.last_message = "小地圖巡航復位中"
        self.next_detect_at = now + MINIMAP_CRUISE_OUT_OF_BOUNDS_RECOVERY_INTERVAL_SECONDS

    def _moving_toward_bounds(self, character_x: int) -> bool:
        if self.recovery_last_x is None or self.recovery_boundary is None:
            return True
        if self.recovery_boundary == "left":
            return character_x > self.recovery_last_x
        return character_x < self.recovery_last_x

    def _finish_recovery(self, now: float) -> None:
        self._cancel_recovery()
        if not self._hold_attack_key():
            return
        self.status = MINIMAP_CRUISE_STATUS_ATTACKING
        self.last_message = "小地圖巡航中"
        self.next_detect_at = now + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS

    def _cancel_recovery(self) -> None:
        held_vk = self.recovery_held_vk
        if held_vk:
            try:
                self.key_up_func(held_vk)
            finally:
                self.recovery_held_vk = 0
        self.recovery_boundary = None
        self.recovery_last_x = None
        self.recovery_direction_vk = 0
        self.recovery_stuck_confirmations = 0

    def _update_stationary_tracking(self, character_x: int, now: float) -> None:
        if (
            self.stationary_x is None
            or abs(character_x - self.stationary_x) > MINIMAP_CRUISE_STATIONARY_X_TOLERANCE_PIXELS
        ):
            self.stationary_x = character_x
            self.stationary_started_at = now
            return
        if self.stationary_started_at is None:
            self.stationary_started_at = now

    def _stationary_too_long(self, now: float) -> bool:
        return (
            self.stationary_x is not None
            and self.stationary_started_at is not None
            and now - self.stationary_started_at >= MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        )

    def _reset_stationary_tracking(self) -> None:
        self.stationary_x = None
        self.stationary_started_at = None

    def _begin_turn(self, next_direction: str, boundary: str | None, now: float) -> None:
        self._reset_stationary_tracking()
        if self.attack_held_vk:
            self._release_attack_key()
        direction_vk = RIGHT_DIRECTION_VK if next_direction == "right" else LEFT_DIRECTION_VK
        self.turn_direction_vk = direction_vk
        if MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS <= 0.0:
            self.key_down_func(direction_vk)
            self.turn_held_vk = direction_vk
            self.turn_key_down_at = None
            self.turn_key_up_at = now + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS
            self.resume_attack_at = self.turn_key_up_at + MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS
        else:
            self.turn_key_down_at = now + MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS
            self.turn_key_up_at = None
            self.resume_attack_at = None
        self.turn_confirmation_boundary = boundary
        self.current_direction = next_direction
        self.settings.minimap_cruise_last_direction = next_direction
        self.status = MINIMAP_CRUISE_STATUS_TURNING
        self.last_message = "小地圖巡航轉向中"

    def _needs_turn_retry(self, character_x: int) -> bool:
        if self.turn_confirmation_boundary is None:
            return False
        left_x, right_x = self._normalized_bounds()
        if self.turn_confirmation_boundary == "right":
            return character_x >= right_x - MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS
        if self.turn_confirmation_boundary == "left":
            return character_x <= left_x + MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS
        return False

    def _update_turn(self, now: float) -> None:
        if not self._can_send_actions():
            self._suspend("小地圖巡航暫停")
            return
        if (
            self.turn_direction_vk
            and not self.turn_held_vk
            and self.turn_key_down_at is not None
            and now >= self.turn_key_down_at
        ):
            self.key_down_func(self.turn_direction_vk)
            self.turn_held_vk = self.turn_direction_vk
            self.turn_key_down_at = None
            self.turn_key_up_at = now + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS
            self.resume_attack_at = self.turn_key_up_at + MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS
        if self.turn_held_vk and self.turn_key_up_at is not None and now >= self.turn_key_up_at:
            self._release_turn_key()
        if self.resume_attack_at is not None and now >= self.resume_attack_at:
            self.turn_key_up_at = None
            self.resume_attack_at = None
            self.turn_direction_vk = 0
            self._hold_attack_key()
            self.status = MINIMAP_CRUISE_STATUS_ATTACKING
            self.last_message = "小地圖巡航中"
            self.next_detect_at = now + MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS

    def _cancel_turn(self) -> None:
        self._release_turn_key()
        self.turn_direction_vk = 0
        self.turn_key_down_at = None
        self.resume_attack_at = None
        self.turn_confirmation_boundary = None

    def _release_turn_key(self) -> None:
        held_vk = self.turn_held_vk
        if not held_vk:
            return
        try:
            self.key_up_func(held_vk)
        finally:
            self.turn_held_vk = 0
            self.turn_key_up_at = None

    def _lie_detector_challenge_visible(self, now: float) -> bool:
        if now + 1e-9 < self.next_lie_detector_check_at:
            return False
        self.next_lie_detector_check_at = now + MINIMAP_CRUISE_LIE_DETECTOR_CHECK_INTERVAL_SECONDS
        region = self._lie_detector_capture_region()
        if region is None:
            return False
        image = self.capture_provider(region)
        return detect_lie_detector_bomb(image)

    def _lie_detector_capture_region(self) -> dict[str, int] | None:
        bounds = self.target_client_bounds_provider()
        if bounds is None:
            return None
        screen_left, screen_top, client_width, client_height = bounds
        if client_width <= 0 or client_height <= 0:
            return None

        client_left = max(0, int(client_width * 0.20))
        client_top = max(0, int(client_height * 0.15))
        client_right = min(client_width, int(client_width * 0.60))
        client_bottom = min(client_height, int(client_height * 0.55))
        width = client_right - client_left
        height = client_bottom - client_top
        if width <= 0 or height <= 0:
            return None
        return {
            "left": screen_left + client_left,
            "top": screen_top + client_top,
            "width": width,
            "height": height,
        }

    def _minimap_red_player_visible(self) -> bool:
        region = self._minimap_red_player_capture_region()
        if region is None:
            return False
        image = self.capture_provider(region)
        return detect_minimap_red_player_dot(image)

    def _minimap_red_player_capture_region(self) -> dict[str, int] | None:
        bounds = self.target_client_bounds_provider()
        if bounds is None:
            return None
        screen_left, screen_top, client_width, client_height = bounds
        if client_width <= 0 or client_height <= 0:
            return None
        width = min(client_width, max(1, int(client_width * 0.24)))
        height = min(client_height, max(1, int(client_height * 0.28)))
        return {
            "left": screen_left,
            "top": screen_top,
            "width": width,
            "height": height,
        }

    def _capture_character_x(self) -> int | None:
        region = self._capture_region()
        if region is None:
            return None
        monitor, client_left = region
        image = self.capture_provider(monitor)
        local_x = detect_yellow_character_center_x(image)
        if local_x is None:
            return None
        return client_left + local_x

    def _capture_region(self) -> tuple[dict[str, int], int] | None:
        bounds = self.target_client_bounds_provider()
        if bounds is None:
            return None
        screen_left, screen_top, client_width, client_height = bounds
        if client_width <= 0 or client_height <= 0:
            return None
        left_x, right_x = self._normalized_bounds()
        detect_y = self.settings.minimap_cruise_detect_y
        if detect_y is None:
            return None

        band_height = max(
            MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT,
            int(self.settings.minimap_cruise_detect_band_height),
        )
        half_band = max(1, band_height // 2)
        boundary_width = max(1, right_x - left_x)
        horizontal_padding = max(MINIMAP_CRUISE_CAPTURE_PADDING_PIXELS, boundary_width * 2)
        client_left = max(0, left_x - horizontal_padding)
        client_right = min(client_width, right_x + horizontal_padding + 1)
        client_top = max(0, detect_y - half_band)
        client_bottom = min(client_height, detect_y + half_band + 1)
        width = client_right - client_left
        height = client_bottom - client_top
        if width <= 0 or height <= 0:
            return None
        return (
            {
                "left": screen_left + client_left,
                "top": screen_top + client_top,
                "width": width,
                "height": height,
            },
            client_left,
        )

    def _normalized_bounds(self) -> tuple[int, int]:
        left_x = int(self.settings.minimap_cruise_left_x or 0)
        right_x = int(self.settings.minimap_cruise_right_x or 0)
        if left_x <= right_x:
            return left_x, right_x
        return right_x, left_x

    def _report_status(self, message: str) -> None:
        if self.set_status is None or message == self._last_status_report:
            return
        self._last_status_report = message
        self.set_status(message)


def detect_yellow_character_center_x(image: np.ndarray) -> int | None:
    if image is None:
        return None
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[0] <= 0 or array.shape[1] <= 0 or array.shape[2] < 3:
        return None

    bgr = array[:, :, :3]
    blue = bgr[:, :, 0].astype(np.int16)
    green = bgr[:, :, 1].astype(np.int16)
    red = bgr[:, :, 2].astype(np.int16)
    mask = (
        (red >= 210)
        & (green >= 165)
        & (green <= 245)
        & (blue <= 120)
        & (red - blue >= 110)
        & (green - blue >= 80)
    ).astype(np.uint8)
    if not bool(mask.any()):
        return None

    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best: tuple[int, float] | None = None
    image_mid_y = (array.shape[0] - 1) / 2.0
    for index in range(1, count):
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 3 or area > 600:
            continue
        if width < 2 or height < 2 or width > 40 or height > 40:
            continue
        aspect = width / max(1, height)
        if aspect < 0.35 or aspect > 2.8:
            continue
        center_x, center_y = centroids[index]
        center_distance = abs(float(center_y) - image_mid_y)
        score = area - center_distance * 0.8
        if best is None or score > best[1]:
            best = (round(float(center_x)), score)
    return None if best is None else best[0]


def detect_minimap_red_player_dot(image: np.ndarray) -> bool:
    if image is None:
        return False
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[0] <= 0 or array.shape[1] <= 0 or array.shape[2] < 3:
        return False

    bgr = array[:, :, :3]
    blue = bgr[:, :, 0].astype(np.int16)
    green = bgr[:, :, 1].astype(np.int16)
    red = bgr[:, :, 2].astype(np.int16)
    mask = (
        (red >= 180)
        & (green <= 90)
        & (blue <= 110)
        & (red - green >= 80)
        & (red - blue >= 80)
    ).astype(np.uint8)
    if not bool(mask.any()):
        return False

    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for index in range(1, count):
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 3 or area > 160:
            continue
        if width < 2 or height < 2 or width > 18 or height > 18:
            continue
        aspect = width / max(1, height)
        if 0.40 <= aspect <= 2.50:
            return True
    return False


def load_lie_detector_bomb_template() -> tuple[np.ndarray, np.ndarray | None] | None:
    global _LIE_DETECTOR_BOMB_TEMPLATE
    if _LIE_DETECTOR_BOMB_TEMPLATE is not None:
        return _LIE_DETECTOR_BOMB_TEMPLATE
    image = cv2.imread(str(LIE_DETECTOR_BOMB_TEMPLATE_PATH), cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0 or image.ndim != 3 or image.shape[2] < 3:
        return None
    template = image[:, :, :3]
    mask = None
    if image.shape[2] >= 4:
        alpha = image[:, :, 3]
        if bool(alpha.any()):
            mask = alpha
    _LIE_DETECTOR_BOMB_TEMPLATE = (template, mask)
    return _LIE_DETECTOR_BOMB_TEMPLATE


def detect_lie_detector_bomb(
    image: np.ndarray,
    template: np.ndarray | None = None,
    mask: np.ndarray | None = None,
    threshold: float = MINIMAP_CRUISE_LIE_DETECTOR_MATCH_THRESHOLD,
) -> bool:
    if image is None:
        return False
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[0] <= 0 or array.shape[1] <= 0 or array.shape[2] < 3:
        return False

    if template is None:
        loaded = load_lie_detector_bomb_template()
        if loaded is None:
            return False
        template, mask = loaded
    if template is None or template.ndim != 3 or template.shape[2] < 3:
        return False

    search = array[:, :, :3]
    base_template = template[:, :, :3]
    base_mask = mask
    if base_mask is not None and (base_mask.ndim != 2 or base_mask.shape[:2] != base_template.shape[:2]):
        base_mask = None

    for scale in (0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15):
        scaled_template = base_template
        scaled_mask = base_mask
        if abs(scale - 1.0) > 1e-9:
            width = max(1, round(base_template.shape[1] * scale))
            height = max(1, round(base_template.shape[0] * scale))
            scaled_template = cv2.resize(base_template, (width, height), interpolation=cv2.INTER_AREA)
            if base_mask is not None:
                scaled_mask = cv2.resize(base_mask, (width, height), interpolation=cv2.INTER_NEAREST)
        if scaled_template.shape[0] > search.shape[0] or scaled_template.shape[1] > search.shape[1]:
            continue
        if scaled_mask is not None and bool(scaled_mask.any()):
            result = cv2.matchTemplate(search, scaled_template, cv2.TM_CCORR_NORMED, mask=scaled_mask)
        else:
            result = cv2.matchTemplate(search, scaled_template, cv2.TM_CCOEFF_NORMED)
        _min_value, max_value, _min_loc, _max_loc = cv2.minMaxLoc(result)
        if float(max_value) >= threshold:
            return True
    return False
