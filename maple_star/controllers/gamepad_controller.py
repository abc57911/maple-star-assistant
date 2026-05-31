from __future__ import annotations

import queue
import sys
import time
from typing import Callable

from .auto_potion_controller import AutoPotionController
from ..adapters.win_input import (
    key_display_name,
    key_down as send_key_down,
    key_up as send_key_up,
    parse_vk_key,
    tap_key,
)
from ..models.settings import (
    AutoPotionSettings,
    COMBO_SCRIPT_REPEATING_JUMP_SKILL,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL,
    COMBO_SLOT_IDS,
)
from ..services.gamepad_bindings import (
    ControllerButtonBinding,
    build_controller_button_bindings,
    first_enabled_controller_binding,
    is_controller_binding_enabled,
)

from ..adapters.controller_worker import (
    EVENT_BUTTON_DOWN,
    EVENT_BUTTON_UP,
    EVENT_DEVICE_ADDED,
    EVENT_DEVICE_REMOVED,
    EVENT_ERROR,
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
POLL_INTERVAL_SECONDS = 0.01
MACRO_TIMING_GUARD_SECONDS = 0.12
WINDOW_INTERACTION_LOOP_DELAY_MS = 120
CONTROL_HOTKEY_PUMP_DELAY_MS = 10
RUNTIME_INFO_REFRESH_INTERVAL_SECONDS = 0.25

TRACKED_HELD_KEYS: set[int] = set()


def effective_repeating_jump_interval_seconds(slot: dict[str, object]) -> float:
    skill_delay = max(0.0, float(slot["skill_delay_seconds"]))
    configured_interval = max(0.0, float(slot["jump_interval_seconds"]))
    return max(JUMP_KEY_HOLD_SECONDS, configured_interval, skill_delay + 0.01)


def key_down(vk_code: int) -> None:
    send_key_down(vk_code)
    TRACKED_HELD_KEYS.add(vk_code)


def key_up(vk_code: int) -> None:
    send_key_up(vk_code)
    TRACKED_HELD_KEYS.discard(vk_code)


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
    if not auto_potion.gui.sync_after_event_processing():
        return False
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
                skill_vk = self._parse_configured_key(str(slot["skill_key"]), "技能鍵")
                if skill_vk is None:
                    self.stop()
                    return
                tap_key(skill_vk)
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

                cycle = self.start_jump_cycle()
                if cycle is None:
                    self.rb_is_down = False
                    self.stop()
                else:
                    self.x_up_at, self.next_c_at, self.next_jump_at = cycle
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
        jump_vk = self._parse_configured_key(str(slot["jump_key"]), "跳躍鍵")
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

    def _parse_configured_key(self, key: str, label: str) -> int | None:
        try:
            return parse_vk_key(key)
        except ValueError as exc:
            print(f"{self.name} function {label} 設定錯誤：{exc}")
            return None

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
        jump_vk = self._parse_configured_key(str(slot["jump_key"]), "跳躍鍵")
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
            skill_vk = self._parse_configured_key(str(slot["skill_key"]), "技能鍵")
            if skill_vk is None:
                self.stop()
                return

            tap_key(skill_vk)
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

    def _parse_configured_key(self, key: str, label: str) -> int | None:
        try:
            return parse_vk_key(key)
        except ValueError as exc:
            print(f"{self.name} function {label} 設定錯誤：{exc}")
            return None

    def _slot(self) -> dict[str, object]:
        return self.settings.combo_slot(self.slot_id)


COMBO_SCRIPT_BINDING_CLASSES = {
    COMBO_SCRIPT_REPEATING_JUMP_SKILL: RBJumpSlashMacro,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL: LBJumpSkillMacro,
}


def build_combo_script_bindings(settings: AutoPotionSettings) -> tuple[ControllerButtonBinding, ...]:
    settings.normalize_combo_slots()
    bindings: list[ControllerButtonBinding] = []
    for slot_id in COMBO_SLOT_IDS:
        slot = settings.combo_slots[slot_id]
        binding_class = COMBO_SCRIPT_BINDING_CLASSES.get(str(slot["script_id"]), LBJumpSkillMacro)
        bindings.append(binding_class(settings, slot_id, f"組合{slot_id}"))
    return tuple(bindings)


def main() -> None:
    auto_potion = AutoPotionController(is_target_window_active, target_window_provider=find_target_window)
    auto_potion.install_console_redirect()
    controller_worker: ControllerEventWorker | None = None
    all_button_bindings: tuple[ControllerButtonBinding, ...] = build_combo_script_bindings(auto_potion.settings)
    controller_button_bindings: dict[int, tuple[ControllerButtonBinding, ...]] = {}
    current_controller_button_settings: tuple[tuple[str, object], ...] | None = None
    key_capture_actions_were_blocked = False
    controller_worker_dead_reported = False

    print("只在 MapleStory Worlds 為前景視窗且偵測到遊戲 HUD 時生效。")
    print(
        f"短按 {auto_potion.settings.toggle_hotkey} 可恢復、按住可暫停自動喝水；"
        f"按 {auto_potion.settings.emergency_stop_hotkey} 可切換總開關並釋放按鍵。按 Ctrl+C 結束。"
    )

    def sync_controller_button_bindings() -> None:
        nonlocal all_button_bindings, controller_button_bindings, current_controller_button_settings
        auto_potion.settings.normalize_combo_slots()
        new_settings = tuple(
            (f"{slot_id}:{key}", value)
            for slot_id in COMBO_SLOT_IDS
            for key, value in auto_potion.settings.combo_slots[slot_id].items()
        )
        if current_controller_button_settings == new_settings:
            return

        if current_controller_button_settings is not None:
            stop_all_bindings("組合設定已變更，停止目前巨集並重建綁定")

        all_button_bindings = build_combo_script_bindings(auto_potion.settings)
        controller_button_bindings = build_controller_button_bindings(
            auto_potion.settings,
            all_button_bindings,
        )
        current_controller_button_settings = new_settings

    def update_active_bindings() -> None:
        if auto_potion.is_key_capture_blocking_actions():
            return
        now = time.monotonic()
        for binding in all_button_bindings:
            if not auto_potion.can_run_actions():
                continue
            if not is_controller_binding_enabled(auto_potion.settings, binding):
                continue
            binding.update(now)

    def stop_all_bindings(reason: str) -> None:
        print(reason)
        for binding in all_button_bindings:
            binding.stop()
        release_tracked_keys()

    def any_combo_enabled() -> bool:
        auto_potion.settings.normalize_combo_slots()
        return any(bool(auto_potion.settings.combo_slots[slot_id]["enabled"]) for slot_id in COMBO_SLOT_IDS)

    def ensure_controller_worker_state() -> None:
        nonlocal controller_worker, controller_worker_dead_reported
        if not any_combo_enabled():
            if controller_worker is not None:
                stop_controller_event_worker(controller_worker)
                controller_worker = None
                controller_worker_dead_reported = False
            return
        if controller_worker is None:
            controller_worker = start_controller_event_worker(POLL_INTERVAL_SECONDS)
            controller_worker_dead_reported = False

    def macro_status_text() -> str:
        statuses = []
        for binding in all_button_bindings:
            status_text = getattr(binding, "status_text", lambda: "")()
            if status_text:
                statuses.append(status_text)
        return " / ".join(statuses) if statuses else "--"

    last_runtime_info_refreshed_at = 0.0

    def refresh_runtime_info() -> None:
        title = foreground_window_title()
        active = is_target_window_active()
        auto_potion.gui.set_runtime_info(
            scripts_enabled=auto_potion.auto_drink_enabled,
            target_active=active,
            foreground_title=title,
            macro_status=macro_status_text(),
            held_keys=tracked_held_keys_text(),
            last_action=auto_potion.last_action,
        )

    def maybe_refresh_runtime_info(now: float) -> None:
        nonlocal last_runtime_info_refreshed_at
        if now - last_runtime_info_refreshed_at < RUNTIME_INFO_REFRESH_INTERVAL_SECONDS:
            return
        last_runtime_info_refreshed_at = now
        refresh_runtime_info()

    def next_binding_deadline_at() -> float | None:
        if auto_potion.is_key_capture_blocking_actions():
            return None
        deadlines: list[float] = []
        for binding in all_button_bindings:
            if not auto_potion.can_run_actions():
                continue
            if not is_controller_binding_enabled(auto_potion.settings, binding):
                continue
            deadline = binding.next_deadline_at()
            if deadline is not None:
                deadlines.append(deadline)
        if not deadlines:
            return None
        return min(deadlines)

    def process_controller_events() -> None:
        if controller_worker is None:
            return
        for _ in range(128):
            try:
                event_type, event_value, event_text = controller_worker.event_queue.get_nowait()
            except queue.Empty:
                return

            if event_type == EVENT_STATUS:
                if event_text:
                    print(event_text)

            elif event_type == EVENT_ERROR:
                if event_text:
                    print(event_text)

            elif event_type == EVENT_DEVICE_ADDED:
                print(f"[C{event_value}] 已連線：{event_text}")

            elif event_type == EVENT_DEVICE_REMOVED:
                print(f"[C{event_value}] 已斷線：{event_text or 'unknown'}")
                for binding in all_button_bindings:
                    binding.stop()

            elif event_type == EVENT_BUTTON_DOWN and isinstance(event_value, int):
                button_bindings = controller_button_bindings.get(event_value, ())
                if not button_bindings:
                    continue
                binding = first_enabled_controller_binding(
                    button_bindings,
                    auto_potion.settings,
                )
                if binding is None:
                    continue
                if auto_potion.is_key_capture_blocking_actions():
                    binding.stop()
                    continue
                if not auto_potion.scripts_enabled:
                    print(f"忽略 {button_name(event_value)}：總開關已關閉")
                    continue
                if not auto_potion.gameplay_hud_active:
                    print(f"忽略 {button_name(event_value)}：未偵測到遊戲 HUD")
                    continue
                binding.on_button_down()

            elif event_type == EVENT_BUTTON_UP and isinstance(event_value, int):
                button_bindings = controller_button_bindings.get(event_value, ())
                for binding in button_bindings:
                    if auto_potion.is_key_capture_blocking_actions():
                        binding.stop()
                        continue
                    if not auto_potion.can_run_actions():
                        binding.stop()
                        continue
                    if not is_controller_binding_enabled(auto_potion.settings, binding):
                        continue
                    binding.on_button_up()

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

    def control_hotkey_pump() -> None:
        try:
            if auto_potion.is_closed():
                return
            poll_control_hotkeys_safely()
        except Exception as exc:
            print(f"控制熱鍵輪詢錯誤：{exc}")
            if not auto_potion.is_closed():
                auto_potion.gui.set_status(f"控制熱鍵輪詢錯誤：{exc}")
        finally:
            if not auto_potion.is_closed():
                auto_potion.gui.root.after(CONTROL_HOTKEY_PUMP_DELAY_MS, control_hotkey_pump)

    def next_loop_delay_ms() -> int:
        if auto_potion.gui.is_window_interaction_active():
            return WINDOW_INTERACTION_LOOP_DELAY_MS
        delay_ms = max(1, int(POLL_INTERVAL_SECONDS * 1000))
        deadline = next_binding_deadline_at()
        if deadline is None:
            return delay_ms
        remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
        return max(1, min(delay_ms, remaining_ms))

    def loop_step() -> None:
        nonlocal key_capture_actions_were_blocked
        try:
            if auto_potion.is_closed():
                return

            poll_control_hotkeys_safely()
            window_interaction_active = auto_potion.gui.is_window_interaction_active()
            if not window_interaction_active:
                if not sync_runtime_settings_before_controller_events(auto_potion, sync_controller_button_bindings):
                    return
                ensure_controller_worker_state()
            key_capture_actions_blocked = auto_potion.is_key_capture_blocking_actions()
            if key_capture_actions_blocked and not key_capture_actions_were_blocked:
                stop_all_bindings("快捷鍵設定中，停止所有手把巨集並釋放按鍵")
            key_capture_actions_were_blocked = key_capture_actions_blocked
            if window_interaction_active:
                return
            update_active_bindings()

            now = time.monotonic()
            next_deadline = next_binding_deadline_at()
            if next_deadline is None or next_deadline - now > MACRO_TIMING_GUARD_SECONDS:
                auto_potion.update(now, pump_gui=False)
                if auto_potion.consume_emergency_stop_requested():
                    stop_all_bindings(f"{auto_potion.settings.emergency_stop_hotkey}：停止所有手把巨集並釋放按鍵")
            if auto_potion.is_closed():
                return

            for binding in all_button_bindings:
                if not auto_potion.can_run_actions() or not is_controller_binding_enabled(auto_potion.settings, binding):
                    binding.stop()

            if not window_interaction_active:
                update_active_bindings()
                maybe_refresh_runtime_info(now)
                process_controller_events()
                report_controller_worker_if_dead()
        except Exception as exc:
            print(f"主迴圈錯誤：{exc}")
            if not auto_potion.is_closed():
                auto_potion.gui.set_status(f"主迴圈錯誤：{exc}")
        finally:
            if not auto_potion.is_closed():
                auto_potion.gui.root.after(next_loop_delay_ms(), loop_step)

    try:
        auto_potion.gui.root.after(0, control_hotkey_pump)
        auto_potion.gui.root.after(0, loop_step)
        auto_potion.gui.root.mainloop()
    finally:
        auto_potion.cleanup()
        for binding in all_button_bindings:
            binding.cleanup()
        release_tracked_keys()
        if controller_worker is not None:
            stop_controller_event_worker(controller_worker)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
        sys.exit(0)
