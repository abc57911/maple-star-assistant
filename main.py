from __future__ import annotations

import ctypes
import multiprocessing as mp
import msvcrt
import os
from ctypes import wintypes
from pathlib import Path
from tempfile import gettempdir

from maple_star.debug_logging import configure_debug_logging, configure_experience_debug_logging


configure_debug_logging()
configure_experience_debug_logging()

MB_ICONINFORMATION = 0x00000040
ERROR_ALREADY_EXISTS = 183
SINGLE_INSTANCE_MUTEX_NAME = "Local\\MapleStarScript"
SINGLE_INSTANCE_LOCK_PATH = Path(gettempdir()) / "MapleStarScript.lock"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

_single_instance_mutex: wintypes.HANDLE | None = None
_single_instance_lock_file: object | None = None

try:
    # Per-monitor v2 awareness can native-crash Tk/CustomTkinter when SDL
    # controller polling is active and the window enters the Win32 move loop.
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def acquire_single_instance() -> bool:
    global _single_instance_lock_file, _single_instance_mutex

    ctypes.set_last_error(0)
    mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())

    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return False

    _single_instance_mutex = mutex
    lock_file = SINGLE_INSTANCE_LOCK_PATH.open("a+b")
    try:
        lock_file.seek(0)
        if lock_file.read(1) != b"\0":
            lock_file.seek(0)
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_file.close()
        release_single_instance()
        return False
    _single_instance_lock_file = lock_file
    return True


def release_single_instance() -> None:
    global _single_instance_lock_file, _single_instance_mutex

    if _single_instance_lock_file is not None:
        try:
            _single_instance_lock_file.seek(0)
            msvcrt.locking(_single_instance_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            _single_instance_lock_file.close()
        except OSError:
            pass
        _single_instance_lock_file = None

    if _single_instance_mutex is not None:
        kernel32.CloseHandle(_single_instance_mutex)
        _single_instance_mutex = None


def show_already_running_message() -> None:
    user32.MessageBoxW(
        None,
        "楓星腳本已在執行中，請不要重複啟動。",
        "大雞雞專用",
        MB_ICONINFORMATION,
    )


def main() -> int:
    configure_debug_logging(reset=True)
    configure_experience_debug_logging(reset=True)
    if not acquire_single_instance():
        show_already_running_message()
        return 0

    from maple_star.controllers.gamepad_controller import main as run_all_features

    try:
        run_all_features()
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    finally:
        release_single_instance()

    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
