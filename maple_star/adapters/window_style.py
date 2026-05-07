from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def background_toolwindow_exstyle(exstyle: int) -> int:
    return (int(exstyle) | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        _get_window_long_ptr = user32.GetWindowLongPtrW
        _set_window_long_ptr = user32.SetWindowLongPtrW
    except AttributeError:
        _get_window_long_ptr = user32.GetWindowLongW
        _set_window_long_ptr = user32.SetWindowLongW
    _get_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_window_long_ptr.restype = ctypes.c_longlong
    _set_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    _set_window_long_ptr.restype = ctypes.c_longlong
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
else:
    user32 = None
    _get_window_long_ptr = None
    _set_window_long_ptr = None


def apply_background_toolwindow_style(window: Any) -> bool:
    if os.name != "nt" or _get_window_long_ptr is None or _set_window_long_ptr is None:
        return False
    try:
        hwnd = int(window.winfo_id())
    except Exception:
        return False
    return apply_background_toolwindow_style_to_hwnd(hwnd)


def apply_background_toolwindow_style_to_hwnd(hwnd: int) -> bool:
    if os.name != "nt" or user32 is None or _get_window_long_ptr is None or _set_window_long_ptr is None:
        return False
    if not hwnd:
        return False
    try:
        current = int(_get_window_long_ptr(hwnd, GWL_EXSTYLE))
        updated = background_toolwindow_exstyle(current)
        if updated == current:
            return True
        ctypes.set_last_error(0)
        previous = _set_window_long_ptr(hwnd, GWL_EXSTYLE, updated)
        if previous == 0 and ctypes.get_last_error() != 0:
            return False
        user32.SetWindowPos(
            hwnd,
            wintypes.HWND(0),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception:
        return False
