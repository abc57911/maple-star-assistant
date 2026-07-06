from __future__ import annotations

from dataclasses import dataclass, field
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
MINIMAP_CRUISE_STATIONARY_TURN_SECONDS = 2.0
MINIMAP_CRUISE_STATIONARY_X_TOLERANCE_PIXELS = 2
MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS = 0.35
MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS = 0.0
MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS = 0.35
MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS = 0.0
MINIMAP_CRUISE_CAPTURE_PADDING_PIXELS = 240
MINIMAP_CRUISE_BOUNDARY_TOLERANCE_PIXELS = 3
MINIMAP_CRUISE_CENTER_DEADZONE_PIXELS = 3

MINIMAP_CRUISE_STATUS_STOPPED = "stopped"
MINIMAP_CRUISE_STATUS_STARTING = "starting"
MINIMAP_CRUISE_STATUS_ATTACKING = "attacking"
MINIMAP_CRUISE_STATUS_SUSPENDED = "suspended"
MINIMAP_CRUISE_STATUS_TURNING = "turning"

LEFT_DIRECTION_VK = 0x25
RIGHT_DIRECTION_VK = 0x27


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
        self._reset_stationary_tracking()
        self.consecutive_detection_failures = 0
        self.last_message = "小地圖巡航已啟用"
        self._report_status(self.last_message)
        return True

    def stop(self, message: str = "小地圖巡航已停用") -> None:
        self.enabled = False
        self.status = MINIMAP_CRUISE_STATUS_STOPPED
        self._cancel_turn()
        self._release_attack_key()
        self._reset_stationary_tracking()
        self.last_message = message
        self._report_status(message)

    def update(self, now: float) -> None:
        if not self.enabled:
            return

        if self.status == MINIMAP_CRUISE_STATUS_TURNING:
            self._update_turn(now)
            return

        if not self._can_send_actions():
            self._suspend("小地圖巡航暫停")
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

        if self._needs_turn_retry(character_x):
            self._begin_turn(self.current_direction, self.turn_confirmation_boundary, now)
            return

        self.turn_confirmation_boundary = None
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
        self._release_attack_key()
        self._reset_stationary_tracking()
        self.status = MINIMAP_CRUISE_STATUS_SUSPENDED
        self.last_message = message
        self._report_status(message)

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
