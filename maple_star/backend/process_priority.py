from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000


def set_current_process_above_normal() -> bool:
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.SetPriorityClass.restype = wintypes.BOOL
    return bool(kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS))


__all__ = ["set_current_process_above_normal"]
