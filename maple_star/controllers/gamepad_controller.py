from __future__ import annotations

import ctypes
import os
import queue
import sys
import time
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np

from .auto_potion_controller import AutoPotionController
from .auto_potion_factory import _create_auto_potion_controller
from ..constants import MINIMAP_PLAYER_ALERT_BEEP_PATTERN
from ..adapters.debug_logging import log_telegram_reply
from ..adapters.win_input import (
    Point,
    is_valid_window,
    key_display_name,
    key_down as send_key_down,
    key_up as send_key_up,
    parse_vk_key,
    tap_key as send_tap_key,
    user32,
)
from ..models.settings import (
    AutoPotionSettings,
    COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP,
    COMBO_SCRIPT_REPEATING_JUMP_SKILL,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL,
    COMBO_SLOT_IDS,
    load_settings,
)
from ..services.gamepad_bindings import (
    ControllerButtonBinding,
    build_controller_button_bindings,
    first_enabled_controller_binding,
    is_controller_binding_enabled,
)
from ..services.minimap_cruise import (
    LEFT_DIRECTION_VK,
    RIGHT_DIRECTION_VK,
    MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL,
    MINIMAP_CRUISE_STATUS_STATIONARY_SKILL,
    MINIMAP_CRUISE_STATUS_SUSPENDED,
    MINIMAP_CRUISE_STATUS_TURNING,
    MinimapCruiseRuntime,
)
from ..services.telegram_bot import (
    TelegramConfigError,
    TelegramReplyListener,
    load_telegram_bot_config,
)
from ..services.control_scheduler import (
    DeadlineTimingRecorder,
    nearest_deadline,
    next_absolute_deadline,
    wait_until_next_poll,
)
from ..services.runtime_api import (
    ControlCommand,
    ControlStatus,
    SettingsUpdated,
    Shutdown,
    TargetWindowUpdated,
    WorkerCrashed,
    control_status_signature,
)
from ..services.runtime_processes import (
    _drain_queue,
    _is_target_hwnd_active,
    _settings_from_payload,
)

from ..adapters.controller_worker import (
    EVENT_BUTTON_DOWN,
    EVENT_BUTTON_UP,
    EVENT_DEVICE_ADDED,
    EVENT_DEVICE_REMOVED,
    EVENT_ERROR,
    EVENT_RELEASE_ALL,
    EVENT_STATUS,
    ControllerEventWorker,
    button_name,
    start_controller_event_worker,
    stop_controller_event_worker,
)
from ..adapters.window_target import (
    TARGET_DISPLAY_NAME,
    find_target_window,
    foreground_window_title,
    is_target_window_active,
)

JUMP_KEY_HOLD_SECONDS = 0.05
HOLD_JUMP_REASSERT_INTERVAL_SECONDS = 0.10
DEFAULT_ATTACK_KEY_HOLD_SECONDS = 1.0
POLL_INTERVAL_SECONDS = 0.01
MACRO_TIMING_GUARD_SECONDS = 0.12
WINDOW_INTERACTION_LOOP_DELAY_MS = 120
RUNTIME_INFO_REFRESH_INTERVAL_SECONDS = 0.25
TELEGRAM_LIE_DETECTOR_NOTICE_INTERVAL_SECONDS = 30.0
CONTROL_STATUS_TIMEOUT_SECONDS = 2.5

TRACKED_HELD_KEYS: set[int] = set()
BENCHMARK_INPUT_SINK_ACTIVE = False


def effective_repeating_jump_interval_seconds(slot: dict[str, object]) -> float:
    skill_delay = max(0.0, float(slot["skill_delay_seconds"]))
    configured_interval = max(0.0, float(slot["jump_interval_seconds"]))
    return max(JUMP_KEY_HOLD_SECONDS, configured_interval, skill_delay + 0.01)


def effective_hold_jump_attack_interval_seconds(slot: dict[str, object]) -> float:
    configured_interval = max(0.0, float(slot["jump_interval_seconds"]))
    attack_hold_seconds = max(0.0, float(slot.get("attack_hold_seconds", DEFAULT_ATTACK_KEY_HOLD_SECONDS)))
    return max(attack_hold_seconds + 0.01, configured_interval)


def _parse_configured_macro_key(name: str, key: str, label: str) -> int | None:
    try:
        return parse_vk_key(key)
    except ValueError as exc:
        print(f"{name} function {label} 設定錯誤：{exc}")
        return None


def key_down(vk_code: int) -> None:
    if not BENCHMARK_INPUT_SINK_ACTIVE:
        send_key_down(vk_code)
    TRACKED_HELD_KEYS.add(vk_code)


def key_up(vk_code: int) -> None:
    if not BENCHMARK_INPUT_SINK_ACTIVE:
        send_key_up(vk_code)
    TRACKED_HELD_KEYS.discard(vk_code)


def tracked_tap_key(vk_code: int) -> None:
    if BENCHMARK_INPUT_SINK_ACTIVE:
        return
    send_tap_key(vk_code)


def tracked_held_keys_text() -> str:
    if not TRACKED_HELD_KEYS:
        return "--"
    return ", ".join(key_display_name(vk_code) for vk_code in sorted(TRACKED_HELD_KEYS))


def release_tracked_keys() -> None:
    for vk_code in tuple(TRACKED_HELD_KEYS):
        try:
            key_up(vk_code)
        except Exception as exc:
            print(f"釋放按鍵 {key_display_name(vk_code)} 失敗：{exc}")
            TRACKED_HELD_KEYS.discard(vk_code)


def sync_runtime_settings_before_controller_events(
    auto_potion: AutoPotionController,
    sync_controller_button_bindings: Callable[[], None],
) -> bool:
    sync_controller_button_bindings()
    return True


class RBJumpSlashMacro:
    script_id = COMBO_SCRIPT_REPEATING_JUMP_SKILL

    def __init__(self, settings: AutoPotionSettings, slot_id: str = "A", name: str | None = None) -> None:
        self.settings = settings
        self.slot_id = slot_id
        self.name = name or f"組合{slot_id}"
        self.rb_is_down = False
        self.active = False
        self.x_is_down = False
        self.held_jump_vk: int | None = None
        self.first_c_pending = False
        self.rb_release_requested = False
        self.x_up_at: float | None = None
        self.next_c_at: float | None = None
        self.next_jump_at: float | None = None

    def on_button_down(self) -> None:
        title = foreground_window_title()
        active = is_target_window_active()
        print(f"按下 {self.name} | target_active={active} | title={title}")

        if self.active:
            print(f"忽略 {self.name}：上一個 {self.name} function 尚未完成")
            return

        slot = self._slot()
        configured_interval = float(slot["jump_interval_seconds"])
        effective_interval = effective_repeating_jump_interval_seconds(slot)
        interval_text = f"跳躍間隔={configured_interval:g} 秒"
        if abs(effective_interval - configured_interval) >= 0.001:
            interval_text += f"（實際 {effective_interval:g} 秒）"
        print(
            f"{self.name} function 開始：跳躍={slot['jump_key']}，"
            f"技能={slot['skill_key']}，技能延遲={float(slot['skill_delay_seconds']):g} 秒，"
            f"{interval_text}"
        )
        cycle = self.start_jump_cycle()
        if cycle is None:
            return

        self.rb_is_down = True
        self.active = True
        self.x_is_down = True
        self.x_up_at, self.next_c_at, self.next_jump_at = cycle
        self.first_c_pending = True
        self.rb_release_requested = False

    def on_button_up(self) -> None:
        self.rb_is_down = False

        if self.active and self.first_c_pending:
            self.rb_release_requested = True
            print(f"{self.name} 已放開：等待第一次 C 完成後釋放 X")
        elif self.active:
            self.stop()

    def update(self, now: float) -> None:
        if self.x_is_down and self.x_up_at is not None and now >= self.x_up_at:
            if self.held_jump_vk is not None:
                key_up(self.held_jump_vk)
            self.x_is_down = False
            self.held_jump_vk = None
            self.x_up_at = None

        if self.active and self.next_c_at is not None and now >= self.next_c_at:
            if is_target_window_active():
                slot = self._slot()
                skill_vk = _parse_configured_macro_key(self.name, str(slot["skill_key"]), "技能鍵")
                if skill_vk is None:
                    self.stop()
                    return
                tracked_tap_key(skill_vk)
                self.next_c_at = None

                if self.first_c_pending:
                    self.first_c_pending = False
                    if self.rb_release_requested or not self.rb_is_down:
                        self.stop()
                        self.rb_release_requested = False
            else:
                print("視窗焦點離開目標，停止 RB function")
                self.rb_is_down = False
                self.stop()

        if (
            self.active
            and self.rb_is_down
            and self.next_jump_at is not None
            and now >= self.next_jump_at
        ):
            if is_target_window_active():
                if self.x_is_down:
                    if self.held_jump_vk is not None:
                        key_up(self.held_jump_vk)
                    self.x_is_down = False
                    self.held_jump_vk = None

                cycle_deadline = self.next_jump_at
                cycle = self.start_jump_cycle()
                if cycle is None:
                    self.rb_is_down = False
                    self.stop()
                else:
                    self.x_up_at, self.next_c_at, self.next_jump_at = cycle
                    if cycle_deadline is not None:
                        self.next_jump_at = next_absolute_deadline(
                            cycle_deadline,
                            effective_repeating_jump_interval_seconds(self._slot()),
                            now,
                        )
                    self.x_is_down = True
            else:
                print("視窗焦點離開目標，停止 RB function")
                self.rb_is_down = False
                self.stop()

    def next_deadline_at(self) -> float | None:
        deadlines = [
            deadline
            for deadline in (self.x_up_at, self.next_c_at, self.next_jump_at if self.rb_is_down else None)
            if deadline is not None
        ]
        if not deadlines:
            return None
        return min(deadlines)

    def cleanup(self) -> None:
        if self.x_is_down and self.held_jump_vk is not None:
            key_up(self.held_jump_vk)
            self.x_is_down = False
            self.held_jump_vk = None

    def start_jump_cycle(self) -> tuple[float, float, float] | None:
        if not is_target_window_active():
            print(f"忽略 {self.name}：目前前景視窗不是 {TARGET_DISPLAY_NAME}")
            return None

        slot = self._slot()
        jump_vk = _parse_configured_macro_key(self.name, str(slot["jump_key"]), "跳躍鍵")
        if jump_vk is None:
            return None

        now = time.monotonic()
        key_down(jump_vk)
        self.held_jump_vk = jump_vk
        skill_delay = max(0.0, float(slot["skill_delay_seconds"]))
        jump_interval = effective_repeating_jump_interval_seconds(slot)
        return (
            now + JUMP_KEY_HOLD_SECONDS,
            now + skill_delay,
            now + jump_interval,
        )

    def _slot(self) -> dict[str, object]:
        return self.settings.combo_slot(self.slot_id)

    def stop(self) -> None:
        was_active = self.active or self.x_is_down
        self.cleanup()
        self.active = False
        self.first_c_pending = False
        self.rb_release_requested = False
        self.x_up_at = None
        self.next_c_at = None
        self.next_jump_at = None
        self.held_jump_vk = None
        if was_active:
            print(f"停止 {self.name} function")

    def status_text(self) -> str:
        if not self.active:
            return ""
        state = []
        if self.x_is_down:
            key_name = key_display_name(self.held_jump_vk) if self.held_jump_vk is not None else "jump"
            state.append(f"{key_name} down")
        if self.next_c_at is not None:
            state.append("待技能")
        if self.rb_is_down:
            state.append("循環")
        return f"{self.name}({', '.join(state) or 'active'})"


class LBJumpSkillMacro:
    script_id = COMBO_SCRIPT_SINGLE_JUMP_SKILL

    def __init__(self, settings: AutoPotionSettings, slot_id: str = "B", name: str | None = None) -> None:
        self.settings = settings
        self.slot_id = slot_id
        self.name = name or f"組合{slot_id}"
        self.active = False
        self.jump_is_down = False
        self.held_jump_vk: int | None = None
        self.jump_up_at: float | None = None
        self.skill_at: float | None = None

    def on_button_down(self) -> None:
        title = foreground_window_title()
        active = is_target_window_active()
        print(f"按下 {self.name} | target_active={active} | title={title}")

        if self.active:
            print(f"忽略 {self.name}：上一個 {self.name} function 尚未完成")
            return

        if not is_target_window_active():
            print(f"忽略 {self.name}：目前前景視窗不是 {TARGET_DISPLAY_NAME}")
            return

        slot = self._slot()
        jump_vk = _parse_configured_macro_key(self.name, str(slot["jump_key"]), "跳躍鍵")
        if jump_vk is None:
            return

        now = time.monotonic()
        key_down(jump_vk)
        self.active = True
        self.jump_is_down = True
        self.held_jump_vk = jump_vk
        self.jump_up_at = now + JUMP_KEY_HOLD_SECONDS
        self.skill_at = now + max(0.0, float(slot["skill_delay_seconds"]))
        print(
            f"{self.name} function 開始：跳躍={slot['jump_key']}，"
            f"技能={slot['skill_key']}，技能延遲={float(slot['skill_delay_seconds']):g} 秒"
        )

    def on_button_up(self) -> None:
        return

    def update(self, now: float) -> None:
        if self.jump_is_down and self.jump_up_at is not None and now >= self.jump_up_at:
            if self.held_jump_vk is not None:
                key_up(self.held_jump_vk)
            self.jump_is_down = False
            self.held_jump_vk = None
            self.jump_up_at = None

        if self.active and self.skill_at is not None and now >= self.skill_at:
            if not is_target_window_active():
                print("視窗焦點離開目標，停止 LB function")
                self.stop()
                return

            slot = self._slot()
            skill_vk = _parse_configured_macro_key(self.name, str(slot["skill_key"]), "技能鍵")
            if skill_vk is None:
                self.stop()
                return

            tracked_tap_key(skill_vk)
            self.stop()

    def next_deadline_at(self) -> float | None:
        deadlines = [
            deadline
            for deadline in (self.jump_up_at, self.skill_at)
            if deadline is not None
        ]
        if not deadlines:
            return None
        return min(deadlines)

    def stop(self) -> None:
        was_active = self.active or self.jump_is_down
        self.cleanup()
        self.active = False
        self.jump_up_at = None
        self.skill_at = None
        self.held_jump_vk = None
        if was_active:
            print(f"停止 {self.name} function")

    def cleanup(self) -> None:
        if self.jump_is_down and self.held_jump_vk is not None:
            key_up(self.held_jump_vk)
            self.jump_is_down = False
            self.held_jump_vk = None

    def status_text(self) -> str:
        if not self.active:
            return ""
        state = []
        if self.jump_is_down:
            key_name = key_display_name(self.held_jump_vk) if self.held_jump_vk is not None else "jump"
            state.append(f"{key_name} down")
        if self.skill_at is not None:
            state.append("待技能")
        return f"{self.name}({', '.join(state) or 'active'})"

    def _slot(self) -> dict[str, object]:
        return self.settings.combo_slot(self.slot_id)


class HoldJumpAttackLoopMacro:
    script_id = COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP

    def __init__(self, settings: AutoPotionSettings, slot_id: str = "A", name: str | None = None) -> None:
        self.settings = settings
        self.slot_id = slot_id
        self.name = name or f"組合{slot_id}"
        self.active = False
        self.trigger_is_down = False
        self.jump_is_down = False
        self.attack_is_down = False
        self.held_jump_vk: int | None = None
        self.held_attack_vk: int | None = None
        self.attack_up_at: float | None = None
        self.next_attack_at: float | None = None
        self.next_jump_reassert_at: float | None = None

    def on_button_down(self) -> None:
        title = foreground_window_title()
        active = is_target_window_active()
        print(f"按下 {self.name} | target_active={active} | title={title}")

        if self.active:
            print(f"忽略 {self.name}：上一個 {self.name} function 尚未完成")
            return

        if not is_target_window_active():
            print(f"忽略 {self.name}：目前前景視窗不是 {TARGET_DISPLAY_NAME}")
            return

        slot = self._slot()
        jump_vk = _parse_configured_macro_key(self.name, str(slot["jump_key"]), "跳躍鍵")
        attack_vk = _parse_configured_macro_key(self.name, str(slot["attack_key"]), "攻擊鍵")
        if jump_vk is None or attack_vk is None:
            return
        if jump_vk == attack_vk:
            print(f"{self.name} function 設定錯誤：跳躍鍵與攻擊鍵不可相同")
            return

        now = time.monotonic()
        key_down(jump_vk)
        self.active = True
        self.trigger_is_down = True
        self.jump_is_down = True
        self.held_jump_vk = jump_vk
        attack_start_delay_seconds = max(0.0, float(slot["attack_start_delay_seconds"]))
        self.next_attack_at = now + attack_start_delay_seconds
        self.next_jump_reassert_at = now + HOLD_JUMP_REASSERT_INTERVAL_SECONDS
        print(
            f"{self.name} function 開始：按住跳躍={slot['jump_key']}，"
            f"起攻延遲={attack_start_delay_seconds:g} 秒，"
            f"攻擊={slot['attack_key']}，攻擊按住={float(slot['attack_hold_seconds']):g} 秒，"
            f"攻擊間隔={float(slot['jump_interval_seconds']):g} 秒"
        )
        if attack_start_delay_seconds <= 0.0:
            self._start_attack_hold(now)

    def on_button_up(self) -> None:
        self.trigger_is_down = False
        if self.active:
            self.stop()

    def update(self, now: float) -> None:
        if self.attack_is_down and self.attack_up_at is not None and now >= self.attack_up_at:
            if self.held_attack_vk is not None:
                key_up(self.held_attack_vk)
            self.attack_is_down = False
            self.held_attack_vk = None
            self.attack_up_at = None

        if (
            self.active
            and self.trigger_is_down
            and self.jump_is_down
            and self.next_jump_reassert_at is not None
            and now >= self.next_jump_reassert_at
        ):
            if not is_target_window_active():
                print("視窗焦點離開目標，停止按住跳躍循環攻擊 function")
                self.stop()
                return
            if self.held_jump_vk is not None:
                key_down(self.held_jump_vk)
            previous_deadline = self.next_jump_reassert_at
            self.next_jump_reassert_at = next_absolute_deadline(
                previous_deadline,
                HOLD_JUMP_REASSERT_INTERVAL_SECONDS,
                now,
            )

        if (
            self.active
            and self.trigger_is_down
            and not self.attack_is_down
            and self.next_attack_at is not None
            and now >= self.next_attack_at
        ):
            if not is_target_window_active():
                print("視窗焦點離開目標，停止按住跳躍循環攻擊 function")
                self.stop()
                return
            scheduled_deadline = self.next_attack_at
            self._start_attack_hold(now)
            if scheduled_deadline is not None:
                self.next_attack_at = next_absolute_deadline(
                    scheduled_deadline,
                    effective_hold_jump_attack_interval_seconds(self._slot()),
                    now,
                )

    def next_deadline_at(self) -> float | None:
        deadlines = [
            deadline
            for deadline in (
                self.attack_up_at,
                self.next_jump_reassert_at if self.active and self.trigger_is_down and self.jump_is_down else None,
                self.next_attack_at if self.active and self.trigger_is_down and not self.attack_is_down else None,
            )
            if deadline is not None
        ]
        if not deadlines:
            return None
        return min(deadlines)

    def stop(self) -> None:
        was_active = self.active or self.jump_is_down or self.attack_is_down
        self.cleanup()
        self.active = False
        self.trigger_is_down = False
        self.attack_up_at = None
        self.next_attack_at = None
        self.next_jump_reassert_at = None
        self.held_jump_vk = None
        self.held_attack_vk = None
        if was_active:
            print(f"停止 {self.name} function")

    def cleanup(self) -> None:
        if self.attack_is_down and self.held_attack_vk is not None:
            key_up(self.held_attack_vk)
            self.attack_is_down = False
            self.held_attack_vk = None
        if self.jump_is_down and self.held_jump_vk is not None:
            key_up(self.held_jump_vk)
            self.jump_is_down = False
            self.held_jump_vk = None

    def status_text(self) -> str:
        if not self.active:
            return ""
        state = []
        if self.jump_is_down:
            key_name = key_display_name(self.held_jump_vk) if self.held_jump_vk is not None else "jump"
            state.append(f"{key_name} down")
        if self.attack_is_down:
            key_name = key_display_name(self.held_attack_vk) if self.held_attack_vk is not None else "attack"
            state.append(f"{key_name} down")
        if self.trigger_is_down:
            state.append("循環")
        return f"{self.name}({', '.join(state) or 'active'})"

    def _start_attack_hold(self, now: float) -> None:
        slot = self._slot()
        attack_vk = _parse_configured_macro_key(self.name, str(slot["attack_key"]), "攻擊鍵")
        if attack_vk is None:
            self.stop()
            return
        key_down(attack_vk)
        attack_hold_seconds = max(0.0, float(slot["attack_hold_seconds"]))
        self.attack_is_down = True
        self.held_attack_vk = attack_vk
        self.attack_up_at = now + attack_hold_seconds
        self.next_attack_at = now + effective_hold_jump_attack_interval_seconds(slot)

    def _slot(self) -> dict[str, object]:
        return self.settings.combo_slot(self.slot_id)


COMBO_SCRIPT_BINDING_CLASSES = {
    COMBO_SCRIPT_REPEATING_JUMP_SKILL: RBJumpSlashMacro,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL: LBJumpSkillMacro,
    COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP: HoldJumpAttackLoopMacro,
}


def build_combo_script_bindings(settings: AutoPotionSettings) -> tuple[ControllerButtonBinding, ...]:
    settings.normalize_combo_slots()
    bindings: list[ControllerButtonBinding] = []
    for slot_id in COMBO_SLOT_IDS:
        slot = settings.combo_slots[slot_id]
        binding_class = COMBO_SCRIPT_BINDING_CLASSES.get(str(slot["script_id"]), LBJumpSkillMacro)
        bindings.append(binding_class(settings, slot_id, f"組合{slot_id}"))
    return tuple(bindings)


def _control_target_client_bounds(target_hwnd: int) -> tuple[int, int, int, int] | None:
    hwnd = int(target_hwnd or 0)
    if not hwnd or not is_valid_window(hwnd):
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None
    origin = Point(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return origin.x, origin.y, width, height


def _minimap_next_deadline(runtime: MinimapCruiseRuntime) -> float | None:
    if getattr(runtime, "pending_release_vks", None):
        return getattr(runtime, "pending_release_retry_at", None)
    if runtime.lie_detector_challenge_active:
        return nearest_deadline(
            (runtime.next_lie_detector_check_at, runtime.next_lie_detector_alert_at)
        )
    if not runtime.enabled:
        return None
    deadlines = [
        runtime.next_lie_detector_check_at,
        runtime.next_red_player_check_at,
        *(
            deadline
            for index, deadline in runtime.periodic_key_next_at.items()
            if index not in runtime.periodic_key_pending_taps
        ),
        *(pending[1] for pending in runtime.periodic_key_pending_taps.values()),
        *(held[1] for held in getattr(runtime, "periodic_key_held", {}).values()),
    ]
    if runtime.red_player_alert_active:
        deadlines.append(runtime.next_red_player_alert_at)
    if runtime.status == MINIMAP_CRUISE_STATUS_TURNING:
        deadlines.extend((runtime.turn_key_up_at, runtime.resume_attack_at))
    elif runtime.status == MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL:
        deadlines.extend((runtime.pre_boundary_skill_key_up_at, runtime.pre_boundary_probe_at))
    elif runtime.status == MINIMAP_CRUISE_STATUS_STATIONARY_SKILL:
        deadlines.extend(
            (runtime.stationary_skill_key_up_at, runtime.stationary_skill_post_delay_until)
        )
    elif runtime.status == MINIMAP_CRUISE_STATUS_SUSPENDED:
        deadlines.append(runtime.foreground_resume_at)
    else:
        deadlines.extend((runtime.next_detect_at, runtime.stationary_tracking_delay_until))
    positive = [deadline for deadline in deadlines if deadline is not None and deadline > 0.0]
    return min(positive) if positive else None


def _put_control_status(status_queue, status: object, *, required: bool = False) -> bool:
    try:
        if required:
            status_queue.put(status, timeout=0.25)
        else:
            status_queue.put_nowait(status)
    except queue.Full:
        if required:
            drained = _drain_queue(status_queue, 256)
            if isinstance(status, ControlStatus):
                previous = [item for item in drained if isinstance(item, ControlStatus)]
                prior_notices = [item.notice for item in previous if item.notice]
                merged_console = tuple(
                    chunk
                    for item in previous
                    for chunk in item.console_lines
                )
                if prior_notices:
                    merged_console += tuple(f"[control notice] {notice}\n" for notice in prior_notices)
                merged_console += status.console_lines
                # Keep the newest bounded diagnostics if the GUI was blocked
                # long enough to saturate the status channel.
                console_text = "".join(merged_console)[-65536:]
                status = replace(
                    status,
                    notice=status.notice or (prior_notices[-1] if prior_notices else ""),
                    urgent_events=tuple(
                        event
                        for item in (*previous, status)
                        for event in item.urgent_events
                    ),
                    console_lines=(console_text,) if console_text else (),
                )
            try:
                status_queue.put(status, timeout=0.25)
            except queue.Full:
                return False
        else:
            return False
    return True


class _BoundedConsoleRecorder:
    def __init__(self, max_chars: int = 65536) -> None:
        self.max_chars = max(1024, int(max_chars))
        self._chunks: list[str] = []
        self._char_count = 0

    def write(self, value: object) -> int:
        text = str(value)
        if not text:
            return 0
        self._chunks.append(text)
        self._char_count += len(text)
        while self._chunks and self._char_count > self.max_chars:
            self._char_count -= len(self._chunks.pop(0))
        return len(text)

    def flush(self) -> None:
        return

    def consume(self) -> tuple[str, ...]:
        chunks = tuple(self._chunks)
        self._chunks.clear()
        self._char_count = 0
        return chunks

    def pending(self) -> tuple[str, ...]:
        return tuple(self._chunks)


def run_control_runtime_process(
    command_queue,
    status_queue,
    settings_payload: dict[str, object],
    target_hwnd: int,
    release_event,
    controller_event_queue,
    benchmark_workload: bool = False,
) -> None:
    """Run all GUI-loop-sensitive input state machines outside the Tk process."""
    global BENCHMARK_INPUT_SINK_ACTIVE, is_target_window_active
    BENCHMARK_INPUT_SINK_ACTIVE = bool(benchmark_workload)
    original_target_window_active = is_target_window_active
    if benchmark_workload:
        is_target_window_active = lambda: True
    minimap: MinimapCruiseRuntime | None = None
    bindings: tuple[ControllerButtonBinding, ...] = ()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    console = _BoundedConsoleRecorder()
    sys.stdout = console
    sys.stderr = console
    try:
        import mss

        settings = _settings_from_payload(settings_payload)
        target_state = {"hwnd": int(target_hwnd or 0)}
        control = ControlCommand(True, False, False)
        generation = 0
        bindings = build_combo_script_bindings(settings)
        button_bindings = build_controller_button_bindings(settings, bindings)
        timing = DeadlineTimingRecorder()
        notices: list[str] = []
        urgent_events: list[str] = []
        last_action = "control runtime 啟動"
        challenge_paused = False
        last_signature: tuple[object, ...] | None = None
        next_status_at = 0.0
        next_heartbeat_at = 0.0
        shutdown = False
        benchmark_deadline: float | None = None

        def can_run_actions() -> bool:
            return bool(
                control.scripts_enabled
                and control.gameplay_hud_active
                and not control.action_blocked
                and (benchmark_workload or _is_target_hwnd_active(target_state["hwnd"]))
            )

        def set_status(message: str) -> None:
            nonlocal last_action
            if message:
                last_action = str(message)

        def set_challenge_paused(paused: bool) -> None:
            nonlocal challenge_paused
            challenge_paused = bool(paused)
            urgent_events.append("challenge_paused" if paused else "challenge_resumed")

        with mss.mss() as sct:
            def capture_minimap(monitor: dict[str, int]) -> np.ndarray:
                if not benchmark_workload:
                    return np.asarray(sct.grab(monitor)).copy()
                height = max(1, int(monitor.get("height", 1)))
                width = max(1, int(monitor.get("width", 1)))
                image = np.zeros((height, width, 4), dtype=np.uint8)
                center_x = min(width - 1, max(0, width // 2))
                center_y = min(height - 1, max(0, height // 2))
                image[max(0, center_y - 2) : center_y + 3, max(0, center_x - 2) : center_x + 3, :3] = (
                    0,
                    210,
                    255,
                )
                return image

            minimap = MinimapCruiseRuntime(
                settings=settings,
                is_target_window_active=lambda: _is_target_hwnd_active(target_state["hwnd"]),
                can_run_actions=can_run_actions,
                is_action_blocked=lambda: bool(control.action_blocked),
                target_client_bounds_provider=(
                    (lambda: (0, 0, 800, 600))
                    if benchmark_workload
                    else lambda: _control_target_client_bounds(target_state["hwnd"])
                ),
                capture_provider=capture_minimap,
                should_defer_periodic_keys=lambda now: now < float(control.potion_action_defer_until or 0.0),
                set_status=set_status,
                lie_detector_alert_func=lambda _now: urgent_events.append("lie_detector_alert"),
                lie_detector_state_func=set_challenge_paused,
                red_player_alert_func=lambda _now: urgent_events.append("red_player_alert"),
                red_player_detected_func=lambda _now: urgent_events.append("red_player_detected"),
                key_down_func=key_down,
                key_up_func=key_up,
                tap_key_func=tracked_tap_key,
            )

            while not shutdown:
                if release_event.is_set():
                    for binding in bindings:
                        binding.stop()
                    minimap.stop("小地圖巡航已安全停止")
                    release_tracked_keys()
                    release_event.clear()

                settings_changed = False
                for command in _drain_queue(command_queue, 256):
                    if isinstance(command, Shutdown):
                        shutdown = True
                        break
                    if isinstance(command, SettingsUpdated):
                        for binding in bindings:
                            binding.stop()
                        settings = _settings_from_payload(command.settings_payload)
                        bindings = build_combo_script_bindings(settings)
                        button_bindings = build_controller_button_bindings(settings, bindings)
                        minimap.apply_settings(settings, time.perf_counter())
                        settings_changed = True
                        continue
                    if isinstance(command, TargetWindowUpdated):
                        minimap.prepare_target_window_update(time.perf_counter())
                        target_state["hwnd"] = int(command.hwnd or 0)
                        continue
                    if isinstance(command, ControlCommand):
                        previous_cruise_enabled = bool(control.cruise_enabled)
                        control = command
                        generation = int(command.generation or 0)
                        interval = max(0.0, float(command.benchmark_deadline_interval_seconds or 0.0))
                        benchmark_deadline = time.perf_counter() + interval if interval > 0.0 else None
                        if command.release_all or not command.scripts_enabled:
                            for binding in bindings:
                                binding.stop()
                            minimap.stop("小地圖巡航已停止")
                            release_tracked_keys()
                        elif command.cruise_enabled != previous_cruise_enabled:
                            if command.cruise_enabled and not minimap.enabled:
                                enabled = minimap.toggle(time.perf_counter())
                                if not enabled:
                                    notices.append(minimap.last_message or "小地圖巡航啟用失敗")
                            elif not command.cruise_enabled and minimap.enabled:
                                minimap.stop("小地圖巡航已停用")
                        continue

                if shutdown:
                    break

                for _ in range(256):
                    try:
                        event_type, event_value, event_text = controller_event_queue.get_nowait()
                    except queue.Empty:
                        break
                    if event_type == EVENT_BUTTON_DOWN and isinstance(event_value, int):
                        candidates = button_bindings.get(event_value, ())
                        binding = first_enabled_controller_binding(candidates, settings)
                        if binding is not None and can_run_actions():
                            binding.on_button_down()
                            last_action = f"按下 {button_name(event_value)}"
                    elif event_type == EVENT_BUTTON_UP and isinstance(event_value, int):
                        for binding in button_bindings.get(event_value, ()):
                            binding.on_button_up()
                    elif event_type == EVENT_RELEASE_ALL:
                        for binding in bindings:
                            binding.stop()
                        minimap.stop("手把事件同步失敗，已停止巡航")
                        release_tracked_keys()
                        if event_text:
                            notices.append(str(event_text))
                    elif event_type in (EVENT_ERROR, EVENT_DEVICE_REMOVED):
                        for binding in bindings:
                            binding.stop()
                        minimap.stop("手把監聽已停止，小地圖巡航已安全停用")
                        release_tracked_keys()
                        if event_text:
                            notices.append(str(event_text))

                now = time.perf_counter()
                binding_deadline = nearest_deadline(binding.next_deadline_at() for binding in bindings)
                minimap_deadline = _minimap_next_deadline(minimap)
                due_deadline = nearest_deadline((binding_deadline, minimap_deadline, benchmark_deadline))
                measured_deadline = benchmark_deadline if benchmark_workload else due_deadline
                if measured_deadline is not None and now >= measured_deadline:
                    timing.record(measured_deadline, now)
                if benchmark_deadline is not None and now >= benchmark_deadline:
                    interval = max(0.001, float(control.benchmark_deadline_interval_seconds))
                    benchmark_deadline = next_absolute_deadline(benchmark_deadline, interval, now)

                if can_run_actions():
                    for binding in bindings:
                        if is_controller_binding_enabled(settings, binding):
                            binding.update(now)
                        else:
                            binding.stop()
                else:
                    for binding in bindings:
                        binding.stop()
                minimap.update(now)

                macro_parts = [binding.status_text() for binding in bindings if binding.status_text()]
                cruise_text = minimap.status_text()
                if cruise_text != "--":
                    macro_parts.append(cruise_text)
                now = time.perf_counter()
                if now >= next_status_at or notices or urgent_events or settings_changed or console._chunks:
                    snapshot = timing.snapshot()
                    status = ControlStatus(
                        generation=generation,
                        heartbeat_at=now,
                        worker_state="running",
                        cruise_enabled=bool(minimap.enabled),
                        challenge_paused=challenge_paused,
                        macro_status=" / ".join(macro_parts) if macro_parts else "--",
                        held_keys=tracked_held_keys_text(),
                        last_action=last_action,
                        notice=notices[-1] if notices else "",
                        urgent_events=tuple(urgent_events),
                        console_lines=console.pending(),
                        timing_sample_count=snapshot.sample_count,
                        timing_p95_lateness_ms=snapshot.p95_lateness_ms,
                        timing_p99_lateness_ms=snapshot.p99_lateness_ms,
                        timing_max_lateness_ms=snapshot.max_lateness_ms,
                        held_vks=tuple(sorted(TRACKED_HELD_KEYS)),
                    )
                    signature = control_status_signature(status)
                    urgent = bool(status.notice or status.urgent_events or status.console_lines)
                    if urgent or signature != last_signature or now >= next_heartbeat_at:
                        delivered = _put_control_status(status_queue, status, required=urgent)
                        if delivered:
                            last_signature = signature
                            next_heartbeat_at = now + 1.0
                            notices.clear()
                            urgent_events.clear()
                            console.consume()
                    next_status_at = now + 0.1

                next_deadline = nearest_deadline(
                    (
                        nearest_deadline(binding.next_deadline_at() for binding in bindings),
                        _minimap_next_deadline(minimap),
                        benchmark_deadline,
                        next_status_at,
                    )
                )
                wait_until_next_poll(next_deadline)

    except Exception as exc:
        _put_control_status(status_queue, WorkerCrashed("control", str(exc)), required=True)
    finally:
        for binding in bindings:
            try:
                binding.cleanup()
            except Exception:
                pass
        if minimap is not None:
            try:
                minimap.stop("小地圖巡航已停止")
            except Exception:
                pass
        release_tracked_keys()
        BENCHMARK_INPUT_SINK_ACTIVE = False
        is_target_window_active = original_target_window_active
        sys.stdout = original_stdout
        sys.stderr = original_stderr


def _run_main(cleanup_actions: dict[str, Callable[[], None]]) -> None:
    startup_marker = os.environ.get("MAPLE_STAR_STARTUP_BENCHMARK_OUTPUT", "").strip()
    if startup_marker:
        from ..views_qt.settings_gui import AutoPotionSettingsGui

        benchmark_gui = AutoPotionSettingsGui(AutoPotionSettings())
        benchmark_gui.show()
        benchmark_gui.application.processEvents()
        Path(startup_marker).write_text(f"{time.perf_counter():.9f}\n", encoding="utf-8")
        benchmark_gui.close()
        return

    from ..views_qt.application_host import QtApplicationHost
    from ..views_qt.settings_gui import AutoPotionSettingsGui

    try:
        settings = load_settings()
    except Exception as exc:
        settings = AutoPotionSettings()
        gui = AutoPotionSettingsGui(settings)
        message = f"設定載入失敗；自動化未啟動。\n{type(exc).__name__}: {exc}"
        gui.set_status("設定載入失敗；自動化未啟動")
        gui.show_page("診斷")
        gui.diagnostics.append_console_batch([message])
        gui.show()
        gui.application.exec()
        return
    gui = AutoPotionSettingsGui(settings)
    auto_potion = _create_auto_potion_controller(
        is_target_window_active,
        settings=settings,
        target_window_provider=find_target_window,
        gui=gui,
    )
    cleanup_actions["auto-potion controller"] = auto_potion.cleanup
    auto_potion.install_console_redirect()
    controller_worker: ControllerEventWorker | None = start_controller_event_worker(POLL_INTERVAL_SECONDS)
    cleanup_actions["controller event worker"] = lambda: (
        stop_controller_event_worker(controller_worker) if controller_worker is not None else None
    )
    key_capture_actions_were_blocked = False
    controller_worker_dead_reported = False
    telegram_reply_listener: TelegramReplyListener | None = None
    telegram_reply_config_error_reported = False
    last_telegram_lie_detector_notice_at = -999.0
    control_cruise_enabled = False
    control_generation = 0
    control_macro_status = "--"
    control_held_keys = "--"
    control_held_vks: tuple[int, ...] = ()
    control_last_action = "control runtime 啟動中"
    control_challenge_paused = False
    last_control_command_signature: tuple[object, ...] | None = None
    last_control_status_at = time.monotonic()
    control_failure_reported = False

    def send_telegram_message(text: str) -> bool:
        if telegram_reply_listener is None:
            return False
        if not telegram_reply_listener.queue_message(text):
            print("Telegram 通知發送佇列已滿")
            return False
        return True

    def play_lie_detector_alert(now: float) -> None:
        nonlocal last_telegram_lie_detector_notice_at
        auto_potion._play_lie_detector_alert_sound()
        if now - last_telegram_lie_detector_notice_at < TELEGRAM_LIE_DETECTOR_NOTICE_INTERVAL_SECONDS:
            return
        last_telegram_lie_detector_notice_at = now
        send_telegram_message("maple-star：偵測到測謊/挑戰視窗，巡航已暫停，請回到電腦處理。")

    def notify_red_player_detected(_now: float) -> None:
        send_telegram_message("maple-star：小地圖偵測到其他玩家紅點持續超過 20 秒。")

    def toggle_minimap_cruise() -> None:
        nonlocal telegram_reply_config_error_reported, control_cruise_enabled, control_generation
        control_cruise_enabled = not control_cruise_enabled
        control_generation += 1
        send_control_state(force=True)
        message = "小地圖巡航啟用中" if control_cruise_enabled else "小地圖巡航已停用"
        auto_potion.notify_minimap_cruise_toggle(control_cruise_enabled, True, message)
        if control_cruise_enabled:
            telegram_reply_config_error_reported = start_telegram_reply_listener(
                report_missing=not telegram_reply_config_error_reported,
            )
        else:
            stop_telegram_reply_listener()

    auto_potion.set_minimap_cruise_toggle_handler(toggle_minimap_cruise)

    def start_telegram_reply_listener(*, report_missing: bool = True) -> bool:
        nonlocal telegram_reply_listener
        if telegram_reply_listener is not None and telegram_reply_listener.is_running():
            return True
        try:
            config = load_telegram_bot_config()
        except TelegramConfigError as exc:
            if report_missing:
                print(f"Telegram 回覆監聽未啟用：{exc}")
            telegram_reply_listener = None
            return True
        telegram_reply_listener = TelegramReplyListener(config)
        telegram_reply_listener.start()
        print("Telegram 回覆監聽已啟用")
        send_telegram_message("maple-star：Telegram 回覆監聽已啟用")
        return False

    def stop_telegram_reply_listener() -> None:
        nonlocal telegram_reply_listener
        if telegram_reply_listener is None:
            return
        telegram_reply_listener.stop()
        telegram_reply_listener = None
        print("Telegram 回覆監聽已停止")

    cleanup_actions["Telegram reply listener"] = stop_telegram_reply_listener

    def process_telegram_replies() -> None:
        if telegram_reply_listener is None:
            return
        for reply in telegram_reply_listener.drain_replies():
            log_telegram_reply(
                {
                    "chat_id": reply.chat_id,
                    "message_id": reply.message_id,
                    "text": reply.text,
                }
            )
            message = f"Telegram 回覆：{reply.text}"
            auto_potion.last_action = message
            auto_potion.gui.set_status(message)
            print(message)

    print("只在 MapleStory Worlds 為前景視窗且偵測到遊戲 HUD 時生效。")
    print(
        f"短按 {auto_potion.settings.toggle_hotkey} 可恢復、按住可暫停自動喝水；"
        f"按 {auto_potion.settings.emergency_stop_hotkey} 可切換總開關並釋放按鍵。按 Ctrl+C 結束。"
    )

    if controller_worker is None or not auto_potion.start_control_runtime(
        run_control_runtime_process,
        controller_worker.event_queue,
    ):
        raise RuntimeError("control runtime 無法啟動")

    def send_control_state(*, force: bool = False, release_all: bool = False) -> None:
        nonlocal last_control_command_signature
        command = ControlCommand(
            scripts_enabled=bool(auto_potion.scripts_enabled),
            gameplay_hud_active=bool(auto_potion.gameplay_hud_active),
            cruise_enabled=bool(control_cruise_enabled),
            action_blocked=bool(auto_potion.is_key_capture_blocking_actions()),
            potion_action_defer_until=float(
                getattr(auto_potion, "runtime_potion_action_defer_until", 0.0) or 0.0
            ),
            challenge_paused=bool(control_challenge_paused),
            release_all=release_all,
            generation=control_generation,
        )
        signature = (
            command.scripts_enabled,
            command.gameplay_hud_active,
            command.cruise_enabled,
            command.action_blocked,
            round(command.potion_action_defer_until, 3),
            command.challenge_paused,
            command.release_all,
            command.generation,
        )
        if not force and signature == last_control_command_signature:
            return
        if release_all:
            auto_potion.request_control_release(command)
        else:
            auto_potion.send_control_runtime(command)
        last_control_command_signature = signature

    cleanup_actions["request control key release"] = lambda: (
        send_control_state(force=True, release_all=True)
        if auto_potion.runtime_port is not None
        else None
    )

    def release_parent_known_control_keys() -> None:
        nonlocal control_held_vks, control_held_keys
        possible_vks = set(control_held_vks)
        possible_vks.update((LEFT_DIRECTION_VK, RIGHT_DIRECTION_VK))
        auto_potion.settings.normalize_combo_slots()
        key_names = [
            str(slot.get(field_name, ""))
            for slot in auto_potion.settings.combo_slots.values()
            for field_name in ("jump_key", "skill_key", "attack_key")
        ]
        key_names.extend(
            str(getattr(auto_potion.settings, field_name, "") or "")
            for field_name in (
                "minimap_cruise_attack_key",
                "minimap_cruise_pre_boundary_skill_key",
                "minimap_cruise_stationary_skill_key",
                *(f"minimap_cruise_periodic_key_{index}" for index in range(1, 6)),
            )
        )
        for key_name in key_names:
            try:
                possible_vks.add(parse_vk_key(key_name))
            except (TypeError, ValueError):
                continue
        possible_vks.discard(0)
        for vk_code in sorted(possible_vks):
            try:
                send_key_up(vk_code)
            except Exception as exc:
                print(f"主程序釋放按鍵 {key_display_name(vk_code)} 失敗：{exc}")
        control_held_vks = ()
        control_held_keys = "--"

    cleanup_actions["release parent-known control keys"] = release_parent_known_control_keys

    def drain_control_statuses() -> None:
        nonlocal control_cruise_enabled, control_macro_status, control_held_keys, control_held_vks
        nonlocal control_last_action, control_challenge_paused, telegram_reply_config_error_reported
        nonlocal last_control_status_at, control_failure_reported
        latest: ControlStatus | None = None
        for item in auto_potion.drain_control_runtime_statuses(limit=256):
            if isinstance(item, WorkerCrashed):
                if item.worker == "control":
                    release_parent_known_control_keys()
                    auto_potion.gui.set_status(f"control runtime 已停止：{item.message}")
                    auto_potion.emergency_stop()
                continue
            if isinstance(item, ControlStatus):
                if int(item.generation) == control_generation:
                    latest = item
        if latest is None:
            return
        last_control_status_at = time.monotonic()
        control_failure_reported = False
        was_cruise_enabled = control_cruise_enabled
        control_cruise_enabled = bool(latest.cruise_enabled)
        control_macro_status = latest.macro_status or "--"
        control_held_keys = latest.held_keys or "--"
        control_held_vks = tuple(latest.held_vks)
        control_last_action = latest.last_action or control_last_action
        for chunk in latest.console_lines:
            print(chunk, end="")
        if latest.notice:
            auto_potion.gui.set_status(latest.notice)
            auto_potion.gui.show_toggle_notice(latest.notice)
        if latest.challenge_paused != control_challenge_paused:
            control_challenge_paused = bool(latest.challenge_paused)
            auto_potion.set_auto_drink_challenge_paused(control_challenge_paused)
        for event in latest.urgent_events:
            if event == "lie_detector_alert":
                play_lie_detector_alert(time.monotonic())
            elif event == "red_player_alert":
                auto_potion._play_toggle_beep(MINIMAP_PLAYER_ALERT_BEEP_PATTERN)
            elif event == "red_player_detected":
                notify_red_player_detected(time.monotonic())
        if was_cruise_enabled and not control_cruise_enabled:
            stop_telegram_reply_listener()
        elif not was_cruise_enabled and control_cruise_enabled:
            telegram_reply_config_error_reported = start_telegram_reply_listener(
                report_missing=not telegram_reply_config_error_reported,
            )

    def stop_all_bindings(reason: str) -> None:
        nonlocal control_cruise_enabled, control_generation
        print(reason)
        control_cruise_enabled = False
        control_generation += 1
        send_control_state(force=True, release_all=True)
        release_parent_known_control_keys()
        stop_telegram_reply_listener()

    def macro_status_text() -> str:
        return control_macro_status

    last_runtime_info_refreshed_at = 0.0

    def refresh_runtime_info() -> None:
        title = foreground_window_title()
        active = is_target_window_active()
        auto_potion.gui.set_runtime_info(
            scripts_enabled=auto_potion.auto_drink_enabled,
            target_active=active,
            foreground_title=title,
            macro_status=macro_status_text(),
            held_keys=control_held_keys,
            last_action=control_last_action or auto_potion.last_action,
        )
        diagnostics = getattr(auto_potion.runtime_port, "diagnostics_text", None)
        apply_diagnostics = getattr(auto_potion.gui, "set_backend_diagnostics", None)
        if callable(diagnostics) and callable(apply_diagnostics):
            apply_diagnostics(diagnostics())

    def maybe_refresh_runtime_info(now: float) -> None:
        nonlocal last_runtime_info_refreshed_at
        if now - last_runtime_info_refreshed_at < RUNTIME_INFO_REFRESH_INTERVAL_SECONDS:
            return
        last_runtime_info_refreshed_at = now
        refresh_runtime_info()

    def report_controller_worker_if_dead() -> None:
        nonlocal controller_worker_dead_reported
        if controller_worker is None or controller_worker_dead_reported or controller_worker.process.is_alive():
            return
        controller_worker_dead_reported = True
        print(f"手把監聽 worker 已停止，exitcode={controller_worker.process.exitcode}")

    def poll_control_hotkeys_safely() -> None:
        auto_potion.poll_control_hotkeys()
        if auto_potion.consume_emergency_stop_requested():
            stop_all_bindings(f"{auto_potion.settings.emergency_stop_hotkey}：停止所有手把巨集並釋放按鍵")

    def next_loop_delay_ms() -> int:
        return max(1, int(POLL_INTERVAL_SECONDS * 1000))

    def loop_step() -> None:
        nonlocal key_capture_actions_were_blocked, control_failure_reported
        try:
            if auto_potion.is_closed():
                return

            poll_control_hotkeys_safely()
            window_interaction_active = auto_potion.gui.is_window_interaction_active()
            if window_interaction_active:
                if auto_potion.consume_emergency_stop_requested():
                    stop_all_bindings(
                        f"{auto_potion.settings.emergency_stop_hotkey}：停止所有手把巨集並釋放按鍵"
                    )
                return
            if not sync_runtime_settings_before_controller_events(auto_potion, lambda: None):
                return
            key_capture_actions_blocked = auto_potion.is_key_capture_blocking_actions()
            if key_capture_actions_blocked and not key_capture_actions_were_blocked:
                stop_all_bindings("快捷鍵設定中，停止所有手把巨集並釋放按鍵")
            key_capture_actions_were_blocked = key_capture_actions_blocked
            process_telegram_replies()

            now = time.monotonic()
            auto_potion.update(now, pump_gui=False)
            if auto_potion.consume_emergency_stop_requested():
                stop_all_bindings(f"{auto_potion.settings.emergency_stop_hotkey}：停止所有手把巨集並釋放按鍵")
            if auto_potion.is_closed():
                return
            send_control_state()
            drain_control_statuses()
            maybe_refresh_runtime_info(now)
            report_controller_worker_if_dead()
            control_unhealthy = (
                not auto_potion.control_runtime_alive()
                or now - last_control_status_at > CONTROL_STATUS_TIMEOUT_SECONDS
            )
            if control_unhealthy and not control_failure_reported:
                control_failure_reported = True
                reason = "已停止" if not auto_potion.control_runtime_alive() else "heartbeat timeout"
                auto_potion.gui.set_status(f"control runtime {reason}，全部自動化已停用")
                auto_potion.emergency_stop()
                release_parent_known_control_keys()
        except Exception as exc:
            print(f"主迴圈錯誤：{exc}")
            if not auto_potion.is_closed():
                auto_potion.gui.set_status(f"主迴圈錯誤：{exc}")
    host = QtApplicationHost(
        auto_potion.gui.application,
        auto_potion.gui,
        tick=loop_step,
        interval_seconds=POLL_INTERVAL_SECONDS,
    )
    auto_potion.gui.set_shutdown_handler(host.request_quit)
    host.run()


def main() -> None:
    cleanup_actions: dict[str, Callable[[], None]] = {}
    try:
        _run_main(cleanup_actions)
    finally:
        for label in (
            "request control key release",
            "release parent-known control keys",
            "auto-potion controller",
            "Telegram reply listener",
            "controller event worker",
        ):
            action = cleanup_actions.get(label)
            if action is not None:
                _run_shutdown_step(label, action)


def _run_shutdown_step(label: str, action: Callable[[], None]) -> None:
    try:
        action()
    except Exception as exc:
        try:
            print(f"主程序 cleanup 失敗（{label}）：{exc}")
        except Exception:
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
        sys.exit(0)
