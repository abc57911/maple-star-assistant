from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x00000040
MUTEX_NAME = "Local\\MapleStarScript"
_single_instance_mutex: int | None = None

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def acquire_single_instance() -> bool:
    global _single_instance_mutex

    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    _single_instance_mutex = int(handle)
    return True


def release_single_instance() -> None:
    global _single_instance_mutex

    if _single_instance_mutex is None:
        return
    kernel32.CloseHandle(_single_instance_mutex)
    _single_instance_mutex = None


def show_already_running_message() -> None:
    user32.MessageBoxW(
        None,
        "楓星腳本已在執行中，請不要重複啟動。",
        "楓星腳本",
        MB_ICONINFORMATION,
    )


def main() -> int:
    if not acquire_single_instance():
        show_already_running_message()
        return 0

    import pygame
    import pygame._sdl2.controller as controller

    from maple_gamepad_macro import main as run_all_features

    try:
        run_all_features()
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    finally:
        controller.quit()
        pygame.quit()
        release_single_instance()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
