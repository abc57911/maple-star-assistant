from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Protocol

try:
    import pygame
    import pygame._sdl2.controller as controller
except ImportError:
    print("缺少 pygame-ce，請先執行：python -m pip install -r requirements.txt")
    raise SystemExit(1)


TARGET_TITLE_KEYWORDS = ("MapleStory Worlds", "楓星")
RB_BUTTON = pygame.CONTROLLER_BUTTON_RIGHTSHOULDER
JUMP_APEX_DELAY_SECONDS = 0.2
# Fixed jump cycle period.
JUMP_TOTAL_SECONDS = 0.66
JUMP_KEY_HOLD_SECONDS = 0.05
POLL_INTERVAL_SECONDS = 0.01

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
# MapleStory Worlds key bindings:
# X = 跳躍
# C = 三連斬
VK_X = 0x58
VK_C = 0x43

BUTTON_NAMES = {
    pygame.CONTROLLER_BUTTON_A: "A",
    pygame.CONTROLLER_BUTTON_B: "B",
    pygame.CONTROLLER_BUTTON_X: "X",
    pygame.CONTROLLER_BUTTON_Y: "Y",
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "LB",
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "RB",
    pygame.CONTROLLER_BUTTON_BACK: "BACK",
    pygame.CONTROLLER_BUTTON_START: "START",
    pygame.CONTROLLER_BUTTON_GUIDE: "HOME",
    pygame.CONTROLLER_BUTTON_LEFTSTICK: "L3",
    pygame.CONTROLLER_BUTTON_RIGHTSTICK: "R3",
    pygame.CONTROLLER_BUTTON_DPAD_UP: "DPAD_UP",
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: "DPAD_DOWN",
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: "DPAD_LEFT",
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "DPAD_RIGHT",
}


class ControllerButtonBinding(Protocol):
    button: int
    name: str

    def on_button_down(self) -> None: ...

    def on_button_up(self) -> None: ...

    def update(self, now: float) -> None: ...

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
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def foreground_window_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""

    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def is_target_window_active() -> bool:
    title = foreground_window_title()
    return all(keyword in title for keyword in TARGET_TITLE_KEYWORDS)


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


def key_up(vk_code: int) -> None:
    event = keyboard_input(vk_code, KEYEVENTF_KEYUP)
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


class RBJumpSlashMacro:
    button = RB_BUTTON
    name = "RB"

    def __init__(self) -> None:
        self.rb_is_down = False
        self.active = False
        self.x_is_down = False
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

        print(f"{self.name} function 開始：每次跳躍起點後 0.2 秒按 C")
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
            key_up(VK_X)
            self.x_is_down = False
            self.x_up_at = None

        if self.active and self.next_c_at is not None and now >= self.next_c_at:
            if is_target_window_active():
                tap_key(VK_C)
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
                    key_up(VK_X)
                    self.x_is_down = False

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

    def cleanup(self) -> None:
        if self.x_is_down:
            key_up(VK_X)
            self.x_is_down = False

    def start_jump_cycle(self) -> tuple[float, float, float] | None:
        if not is_target_window_active():
            print(f"忽略 {self.name}：目前前景視窗不是 {TARGET_TITLE_KEYWORDS}")
            return None

        now = time.monotonic()
        key_down(VK_X)
        return (
            now + JUMP_KEY_HOLD_SECONDS,
            now + JUMP_APEX_DELAY_SECONDS,
            now + JUMP_TOTAL_SECONDS,
        )

    def stop(self) -> None:
        was_active = self.active or self.x_is_down
        self.cleanup()
        self.active = False
        self.first_c_pending = False
        self.rb_release_requested = False
        self.x_up_at = None
        self.next_c_at = None
        self.next_jump_at = None
        if was_active:
            print(f"停止 {self.name} function")


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

    controllers_by_id = open_connected_controllers()
    rb_macro = RBJumpSlashMacro()
    # Add future controller-button functions here, e.g.
    # pygame.CONTROLLER_BUTTON_LEFTSHOULDER: SomeOtherMacro()
    controller_button_bindings: dict[int, ControllerButtonBinding] = {
        rb_macro.button: rb_macro,
    }

    print("只在 MapleStory Worlds-楓星 為前景視窗時生效。")
    print("RB 按住時腳本每 0.66 秒短按 X 跳躍，並在每次跳躍 0.2 秒後按 C。按 Ctrl+C 結束。")

    try:
        while True:
            now = time.monotonic()
            for binding in controller_button_bindings.values():
                binding.update(now)

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
                    for binding in controller_button_bindings.values():
                        binding.stop()

                elif event.type == pygame.CONTROLLERBUTTONDOWN:
                    binding = controller_button_bindings.get(event.button)
                    if binding is not None:
                        binding.on_button_down()

                elif event.type == pygame.CONTROLLERBUTTONUP:
                    binding = controller_button_bindings.get(event.button)
                    if binding is not None:
                        binding.on_button_up()

            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        for binding in controller_button_bindings.values():
            binding.cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
        controller.quit()
        pygame.quit()
        sys.exit(0)
