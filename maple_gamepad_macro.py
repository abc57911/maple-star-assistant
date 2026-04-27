from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Protocol

from auto_potion import AutoPotionController, AutoPotionSettings, parse_vk_key

try:
    import pygame
    import pygame._sdl2.controller as controller
except ImportError:
    print("缺少 pygame-ce，請先執行：python -m pip install -r requirements.txt")
    raise SystemExit(1)


from maple_star.window_target import (
    TARGET_DISPLAY_NAME,
    find_target_window,
    foreground_window_title,
    is_target_window_active,
)

JUMP_KEY_HOLD_SECONDS = 0.05
POLL_INTERVAL_SECONDS = 0.01
MACRO_TIMING_GUARD_SECONDS = 0.12

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_DISPLAY_NAMES = {
    0x2E: "Delete",
    0x23: "End",
}
for code in range(0x30, 0x3A):
    VK_DISPLAY_NAMES[code] = chr(code)
for code in range(0x41, 0x5B):
    VK_DISPLAY_NAMES[code] = chr(code)
for index in range(1, 25):
    VK_DISPLAY_NAMES[0x70 + index - 1] = f"F{index}"
TRACKED_HELD_KEYS: set[int] = set()
CONTROLLER_BUTTONS_BY_NAME = {
    "A": pygame.CONTROLLER_BUTTON_A,
    "B": pygame.CONTROLLER_BUTTON_B,
    "X": pygame.CONTROLLER_BUTTON_X,
    "Y": pygame.CONTROLLER_BUTTON_Y,
    "LB": pygame.CONTROLLER_BUTTON_LEFTSHOULDER,
    "RB": pygame.CONTROLLER_BUTTON_RIGHTSHOULDER,
    "BACK": pygame.CONTROLLER_BUTTON_BACK,
    "START": pygame.CONTROLLER_BUTTON_START,
    "HOME": pygame.CONTROLLER_BUTTON_GUIDE,
    "L3": pygame.CONTROLLER_BUTTON_LEFTSTICK,
    "R3": pygame.CONTROLLER_BUTTON_RIGHTSTICK,
    "DPAD_UP": pygame.CONTROLLER_BUTTON_DPAD_UP,
    "DPAD_DOWN": pygame.CONTROLLER_BUTTON_DPAD_DOWN,
    "DPAD_LEFT": pygame.CONTROLLER_BUTTON_DPAD_LEFT,
    "DPAD_RIGHT": pygame.CONTROLLER_BUTTON_DPAD_RIGHT,
}
BUTTON_NAMES = {button: name for name, button in CONTROLLER_BUTTONS_BY_NAME.items()}


class ControllerButtonBinding(Protocol):
    name: str

    def on_button_down(self) -> None: ...

    def on_button_up(self) -> None: ...

    def update(self, now: float) -> None: ...

    def next_deadline_at(self) -> float | None: ...

    def stop(self) -> None: ...

    def cleanup(self) -> None: ...


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", InputUnion),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def button_name(button: int) -> str:
    return BUTTON_NAMES.get(button, f"BUTTON_{button}")


def keyboard_input(vk_code: int, flags: int = 0) -> Input:
    return Input(
        type=INPUT_KEYBOARD,
        union=InputUnion(
            ki=KeyBdInput(
                wVk=vk_code,
                wScan=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=None,
            )
        ),
    )


def tap_key(vk_code: int) -> None:
    events = (Input * 2)(
        keyboard_input(vk_code),
        keyboard_input(vk_code, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(2, events, ctypes.sizeof(Input))
    if sent != 2:
        raise ctypes.WinError(ctypes.get_last_error())


def key_down(vk_code: int) -> None:
    event = keyboard_input(vk_code)
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())
    TRACKED_HELD_KEYS.add(vk_code)


def key_up(vk_code: int) -> None:
    event = keyboard_input(vk_code, KEYEVENTF_KEYUP)
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())
    TRACKED_HELD_KEYS.discard(vk_code)


def key_display_name(vk_code: int) -> str:
    return VK_DISPLAY_NAMES.get(vk_code, f"VK{vk_code}")


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


class RBJumpSlashMacro:
    name = "RB"

    def __init__(self, settings: AutoPotionSettings) -> None:
        self.settings = settings
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

        print(
            f"{self.name} function 開始：跳躍={self.settings.rb_jump_key}，"
            f"技能={self.settings.rb_skill_key}，技能延遲={self.settings.rb_skill_delay_seconds:g} 秒，"
            f"跳躍間隔={self.settings.rb_jump_interval_seconds:g} 秒"
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
                skill_vk = self._parse_configured_key(self.settings.rb_skill_key, "技能鍵")
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

        jump_vk = self._parse_configured_key(self.settings.rb_jump_key, "跳躍鍵")
        if jump_vk is None:
            return None

        now = time.monotonic()
        key_down(jump_vk)
        self.held_jump_vk = jump_vk
        skill_delay = max(0.0, self.settings.rb_skill_delay_seconds)
        jump_interval = max(JUMP_KEY_HOLD_SECONDS, self.settings.rb_jump_interval_seconds, skill_delay + 0.01)
        return (
            now + JUMP_KEY_HOLD_SECONDS,
            now + skill_delay,
            now + jump_interval,
        )

    def _parse_configured_key(self, key: str, label: str) -> int | None:
        try:
            return parse_vk_key(key)
        except ValueError as exc:
            print(f"RB function {label} 設定錯誤：{exc}")
            return None

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
    name = "LB"

    def __init__(self, settings: AutoPotionSettings) -> None:
        self.settings = settings
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

        jump_vk = self._parse_configured_key(self.settings.lb_jump_key, "跳躍鍵")
        if jump_vk is None:
            return

        now = time.monotonic()
        key_down(jump_vk)
        self.active = True
        self.jump_is_down = True
        self.held_jump_vk = jump_vk
        self.jump_up_at = now + JUMP_KEY_HOLD_SECONDS
        self.skill_at = now + max(0.0, self.settings.lb_skill_delay_seconds)
        print(
            f"{self.name} function 開始：跳躍={self.settings.lb_jump_key}，"
            f"技能={self.settings.lb_skill_key}，技能延遲={self.settings.lb_skill_delay_seconds:g} 秒"
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

            skill_vk = self._parse_configured_key(self.settings.lb_skill_key, "技能鍵")
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
            print(f"LB function {label} 設定錯誤：{exc}")
            return None


def open_connected_controllers() -> dict[int, controller.Controller]:
    controllers: dict[int, controller.Controller] = {}
    count = controller.get_count()
    print(f"偵測到 {count} 個 SDL Controller。")

    for index in range(count):
        if controller.is_controller(index):
            pad = controller.Controller(index)
            controllers[pad.id] = pad
            print(f"[C{pad.id}] {pad.name}")

    return controllers


def main() -> None:
    pygame.init()
    pygame.joystick.init()
    controller.init()

    auto_potion = AutoPotionController(is_target_window_active, target_window_provider=find_target_window)
    auto_potion.install_console_redirect()
    controllers_by_id = open_connected_controllers()
    rb_macro = RBJumpSlashMacro(auto_potion.settings)
    lb_macro = LBJumpSkillMacro(auto_potion.settings)
    all_button_bindings: tuple[ControllerButtonBinding, ...] = (rb_macro, lb_macro)
    controller_button_bindings: dict[int, ControllerButtonBinding] = {}
    current_controller_button_settings: tuple[str, str, bool, bool] | None = None
    key_capture_actions_were_blocked = False

    print("只在 MapleStory Worlds 為前景視窗時生效。")
    print(
        f"RB function 由 {auto_potion.settings.rb_controller_button} 觸發，每 "
        f"{auto_potion.settings.rb_jump_interval_seconds:g} 秒短按 "
        f"{auto_potion.settings.rb_jump_key} 跳躍，並在每次跳躍 "
        f"{auto_potion.settings.rb_skill_delay_seconds:g} 秒後按 {auto_potion.settings.rb_skill_key}。"
    )
    print(f"LB function 由 {auto_potion.settings.lb_controller_button} 觸發，按下時腳本跳躍一次，並在設定延遲後按技能鍵。")
    print("自動喝水設定視窗已開啟，可即時調整 HP/MP 閾值、快捷鍵與冷卻時間。")
    print(
        f"按 {auto_potion.settings.toggle_hotkey} 可暫停/恢復所有腳本功能；"
        f"按 {auto_potion.settings.emergency_stop_hotkey} 可硬停止並釋放按鍵。按 Ctrl+C 結束。"
    )

    def configured_controller_button(button_name_value: str) -> int | None:
        return CONTROLLER_BUTTONS_BY_NAME.get(button_name_value)

    def sync_controller_button_bindings() -> None:
        nonlocal controller_button_bindings, current_controller_button_settings
        new_settings = (
            auto_potion.settings.rb_controller_button,
            auto_potion.settings.lb_controller_button,
            auto_potion.settings.rb_enabled,
            auto_potion.settings.lb_enabled,
        )
        if current_controller_button_settings == new_settings:
            return

        if current_controller_button_settings is not None:
            stop_all_bindings("手把觸發鍵設定已變更，停止目前巨集並重建綁定")

        bindings: dict[int, ControllerButtonBinding] = {}
        rb_button = configured_controller_button(auto_potion.settings.rb_controller_button)
        lb_button = configured_controller_button(auto_potion.settings.lb_controller_button)
        if auto_potion.settings.rb_enabled and rb_button is not None:
            bindings[rb_button] = rb_macro
        if auto_potion.settings.lb_enabled and lb_button is not None:
            if lb_button in bindings:
                lb_macro.stop()
                print(
                    f"LB function 觸發鍵 {auto_potion.settings.lb_controller_button} "
                    "與 RB function 重複，已略過 LB 綁定"
                )
            else:
                bindings[lb_button] = lb_macro
        controller_button_bindings = bindings
        current_controller_button_settings = new_settings

    def update_active_bindings() -> None:
        if auto_potion.is_key_capture_blocking_actions():
            return
        now = time.monotonic()
        for binding in all_button_bindings:
            if not auto_potion.scripts_enabled:
                continue
            if binding is rb_macro and not auto_potion.settings.rb_enabled:
                continue
            if binding is lb_macro and not auto_potion.settings.lb_enabled:
                continue
            binding.update(now)

    def stop_all_bindings(reason: str) -> None:
        print(reason)
        for binding in all_button_bindings:
            binding.stop()
        release_tracked_keys()

    def macro_status_text() -> str:
        statuses = []
        for binding in all_button_bindings:
            status_text = getattr(binding, "status_text", lambda: "")()
            if status_text:
                statuses.append(status_text)
        return " / ".join(statuses) if statuses else "--"

    def refresh_runtime_info() -> None:
        title = foreground_window_title()
        active = is_target_window_active()
        auto_potion.gui.set_runtime_info(
            scripts_enabled=auto_potion.scripts_enabled,
            target_active=active,
            foreground_title=title,
            macro_status=macro_status_text(),
            held_keys=tracked_held_keys_text(),
            last_action=auto_potion.last_action,
        )

    def next_binding_deadline_at() -> float | None:
        if auto_potion.is_key_capture_blocking_actions():
            return None
        deadlines: list[float] = []
        for binding in all_button_bindings:
            if not auto_potion.scripts_enabled:
                continue
            if binding is rb_macro and not auto_potion.settings.rb_enabled:
                continue
            if binding is lb_macro and not auto_potion.settings.lb_enabled:
                continue
            deadline = binding.next_deadline_at()
            if deadline is not None:
                deadlines.append(deadline)
        if not deadlines:
            return None
        return min(deadlines)

    try:
        while True:
            sync_controller_button_bindings()
            auto_potion.poll_control_hotkeys()
            key_capture_actions_blocked = auto_potion.is_key_capture_blocking_actions()
            if key_capture_actions_blocked and not key_capture_actions_were_blocked:
                stop_all_bindings("快捷鍵設定中，停止所有手把巨集並釋放按鍵")
            key_capture_actions_were_blocked = key_capture_actions_blocked
            if auto_potion.consume_emergency_stop_requested():
                stop_all_bindings(f"{auto_potion.settings.emergency_stop_hotkey}：停止所有手把巨集並釋放按鍵")
            update_active_bindings()

            now = time.monotonic()
            next_deadline = next_binding_deadline_at()
            if next_deadline is None or next_deadline - now > MACRO_TIMING_GUARD_SECONDS:
                auto_potion.update(now)
                if auto_potion.consume_emergency_stop_requested():
                    stop_all_bindings(f"{auto_potion.settings.emergency_stop_hotkey}：停止所有手把巨集並釋放按鍵")
            if auto_potion.is_closed():
                break

            if not auto_potion.scripts_enabled or not auto_potion.settings.rb_enabled:
                rb_macro.stop()
            if not auto_potion.scripts_enabled or not auto_potion.settings.lb_enabled:
                lb_macro.stop()

            update_active_bindings()
            refresh_runtime_info()

            for event in pygame.event.get():
                if event.type == pygame.CONTROLLERDEVICEADDED:
                    if controller.is_controller(event.device_index):
                        pad = controller.Controller(event.device_index)
                        controllers_by_id[pad.id] = pad
                        print(f"[C{pad.id}] 已連線：{pad.name}")

                elif event.type == pygame.CONTROLLERDEVICEREMOVED:
                    controller_id = getattr(event, "instance_id", getattr(event, "which", -1))
                    pad = controllers_by_id.pop(controller_id, None)
                    name = pad.name if pad else "unknown"
                    print(f"[C{controller_id}] 已斷線：{name}")
                    for binding in all_button_bindings:
                        binding.stop()

                elif event.type == pygame.CONTROLLERBUTTONDOWN:
                    binding = controller_button_bindings.get(event.button)
                    if binding is not None:
                        if auto_potion.is_key_capture_blocking_actions():
                            binding.stop()
                            continue
                        if not auto_potion.scripts_enabled:
                            print(f"忽略 {button_name(event.button)}：腳本已暫停")
                            continue
                        if binding is rb_macro and not auto_potion.settings.rb_enabled:
                            print("忽略 RB：RB function 未啟用")
                            continue
                        if binding is lb_macro and not auto_potion.settings.lb_enabled:
                            print("忽略 LB：LB function 未啟用")
                            continue
                        binding.on_button_down()

                elif event.type == pygame.CONTROLLERBUTTONUP:
                    binding = controller_button_bindings.get(event.button)
                    if binding is not None:
                        if auto_potion.is_key_capture_blocking_actions():
                            binding.stop()
                            continue
                        if not auto_potion.scripts_enabled:
                            binding.stop()
                            continue
                        if binding is rb_macro and not auto_potion.settings.rb_enabled:
                            binding.stop()
                            continue
                        if binding is lb_macro and not auto_potion.settings.lb_enabled:
                            binding.stop()
                            continue
                        binding.on_button_up()

            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        auto_potion.cleanup()
        for binding in all_button_bindings:
            binding.cleanup()
        release_tracked_keys()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
        controller.quit()
        pygame.quit()
        sys.exit(0)
