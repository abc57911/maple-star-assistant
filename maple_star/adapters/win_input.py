from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from ctypes import wintypes
from typing import Callable

from ..constants import (
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
)

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTUP = 0x0010
WH_MOUSE_LL = 14
HC_ACTION = 0
LLMHF_INJECTED = 0x00000001
PM_REMOVE = 0x0001
MOUSE_LOCK_DRAIN_SECONDS = 0.02
MOUSE_LOCK_THREAD_JOIN_SECONDS = 0.5
MOUSE_ACTIVITY_THREAD_JOIN_SECONDS = 0.5
MOUSE_ACTIVITY_POLL_SECONDS = 0.05
MOUSE_PROGRAMMATIC_IGNORE_SECONDS = 0.25
MOUSE_ACTIVITY_BUTTON_VKS = (0x01, 0x02, 0x04, 0x05, 0x06)
MOUSE_ACTIVITY_ASYNC_DOWN_MASK = 0x8000
_PROGRAMMATIC_MOUSE_IGNORE_UNTIL = 0.0
_PROGRAMMATIC_MOUSE_LOCK = threading.Lock()

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
GA_ROOT = 2
GA_ROOTOWNER = 3
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
SW_RESTORE = 9

VK_NAMED_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
}

for index in range(1, 25):
    VK_NAMED_KEYS[f"f{index}"] = 0x70 + index - 1

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


class Point(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
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


class Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", Point),
    ]


class LowLevelMouseHookStruct(ctypes.Structure):
    _fields_ = [
        ("pt", Point),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BitmapInfoHeader),
        ("bmiColors", wintypes.DWORD * 3),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
kernel32.Process32NextW.restype = wintypes.BOOL

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(Point)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(Point)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
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
try:
    _get_window_long_ptr = user32.GetWindowLongPtrW
except AttributeError:
    _get_window_long_ptr = user32.GetWindowLongW
_get_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int]
_get_window_long_ptr.restype = ctypes.c_longlong
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(Msg),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(Msg)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(Msg)]
user32.DispatchMessageW.restype = wintypes.LPARAM
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_long
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(Msg),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(BitmapInfo),
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
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


def mouse_input(flags: int) -> Input:
    return Input(
        type=INPUT_MOUSE,
        union=InputUnion(
            mi=MouseInput(
                dx=0,
                dy=0,
                mouseData=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=None,
            )
        ),
    )


def release_mouse_buttons() -> None:
    events = (Input * 2)(
        mouse_input(MOUSEEVENTF_LEFTUP),
        mouse_input(MOUSEEVENTF_RIGHTUP),
    )
    sent = user32.SendInput(2, events, ctypes.sizeof(Input))
    if sent != 2:
        raise ctypes.WinError(ctypes.get_last_error())
    mark_programmatic_mouse_input()


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


def tap_key(vk_code: int) -> None:
    events = (Input * 2)(
        keyboard_input(vk_code),
        keyboard_input(vk_code, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(2, events, ctypes.sizeof(Input))
    if sent != 2:
        raise ctypes.WinError(ctypes.get_last_error())


def get_cursor_position() -> tuple[int, int]:
    point = Point()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(point.x), int(point.y)


def set_cursor_position(x: int, y: int) -> None:
    if not user32.SetCursorPos(int(x), int(y)):
        raise ctypes.WinError(ctypes.get_last_error())
    mark_programmatic_mouse_input()


def mark_programmatic_mouse_input() -> None:
    global _PROGRAMMATIC_MOUSE_IGNORE_UNTIL
    with _PROGRAMMATIC_MOUSE_LOCK:
        _PROGRAMMATIC_MOUSE_IGNORE_UNTIL = time.monotonic() + MOUSE_PROGRAMMATIC_IGNORE_SECONDS


def programmatic_mouse_input_is_recent(now: float | None = None) -> bool:
    check_at = time.monotonic() if now is None else float(now)
    with _PROGRAMMATIC_MOUSE_LOCK:
        return check_at <= _PROGRAMMATIC_MOUSE_IGNORE_UNTIL


def pump_pending_windows_messages() -> int:
    processed = 0
    message = Msg()
    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
        processed += 1
    return processed


def sleep_while_pumping_messages(seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        pump_pending_windows_messages()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.005, remaining))


class _LowLevelMouseInputLock:
    def __init__(self) -> None:
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="maple-star-mouse-lock", daemon=True)
        self._hook_handle = wintypes.HHOOK()
        self._proc: LowLevelMouseProc | None = None
        self._error: BaseException | None = None

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(MOUSE_LOCK_THREAD_JOIN_SECONDS):
            self.stop()
            raise RuntimeError("滑鼠鎖定 hook 啟動逾時")
        if self._error is not None:
            raise self._error
        if not self._hook_handle:
            raise RuntimeError("滑鼠鎖定 hook 未啟動")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(MOUSE_LOCK_THREAD_JOIN_SECONDS)

    def _run(self) -> None:
        hook_handle = wintypes.HHOOK()

        @LowLevelMouseProc
        def mouse_proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == HC_ACTION:
                event = ctypes.cast(l_param, ctypes.POINTER(LowLevelMouseHookStruct)).contents
                if not (int(event.flags) & LLMHF_INJECTED):
                    return 1
            return user32.CallNextHookEx(hook_handle, n_code, w_param, l_param)

        self._proc = mouse_proc
        hook_handle = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, kernel32.GetModuleHandleW(None), 0)
        if not hook_handle:
            self._error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return
        self._hook_handle = hook_handle
        self._ready.set()
        try:
            while not self._stop.is_set():
                pump_pending_windows_messages()
                time.sleep(0.001)
            pump_pending_windows_messages()
        finally:
            user32.UnhookWindowsHookEx(hook_handle)
            self._hook_handle = wintypes.HHOOK()


@contextmanager
def temporary_mouse_input_lock():
    original_position = get_cursor_position()
    mouse_lock = _LowLevelMouseInputLock()
    mouse_lock.start()
    try:
        yield original_position
    finally:
        try:
            set_cursor_position(*original_position)
            time.sleep(MOUSE_LOCK_DRAIN_SECONDS)
            set_cursor_position(*original_position)
        finally:
            mouse_lock.stop()
            set_cursor_position(*original_position)


class PhysicalMouseActivityObserver:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._last_activity_at = -999.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cursor_position: tuple[int, int] | None = None
        self._last_button_state: tuple[bool, ...] | None = None

    @property
    def last_activity_at(self) -> float:
        with self._lock:
            return self._last_activity_at

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="maple-star-mouse-activity", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(MOUSE_ACTIVITY_THREAD_JOIN_SECONDS)
        self._thread = None

    def record_mouse_event(self, flags: int) -> bool:
        if int(flags) & LLMHF_INJECTED:
            return False
        self._record_activity(self._clock())
        return True

    def poll_once(self) -> bool:
        now = self._clock()
        try:
            cursor_position = get_cursor_position()
            button_state = self._mouse_button_state()
        except Exception:
            return False
        if self._last_cursor_position is None or self._last_button_state is None:
            self._last_cursor_position = cursor_position
            self._last_button_state = button_state
            return False

        changed = cursor_position != self._last_cursor_position or button_state != self._last_button_state
        self._last_cursor_position = cursor_position
        self._last_button_state = button_state
        if not changed:
            return False
        if programmatic_mouse_input_is_recent(now):
            return False
        self._record_activity(now)
        return True

    def _record_activity(self, observed_at: float) -> None:
        with self._lock:
            self._last_activity_at = observed_at

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            time.sleep(MOUSE_ACTIVITY_POLL_SECONDS)

    def _mouse_button_state(self) -> tuple[bool, ...]:
        return tuple(
            bool(user32.GetAsyncKeyState(vk_code) & MOUSE_ACTIVITY_ASYNC_DOWN_MASK)
            for vk_code in MOUSE_ACTIVITY_BUTTON_VKS
        )


def client_to_screen_point(hwnd: int, x: int, y: int) -> tuple[int, int]:
    if not is_valid_window(hwnd):
        raise RuntimeError("目標視窗無效")
    point = Point(int(x), int(y))
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(point.x), int(point.y)


def click_screen_point(x: int, y: int, *, preserve_cursor_position: bool = True) -> None:
    original_position: tuple[int, int] | None = None
    if preserve_cursor_position:
        original_position = get_cursor_position()
    try:
        set_cursor_position(x, y)
        events = (Input * 2)(
            mouse_input(MOUSEEVENTF_LEFTDOWN),
            mouse_input(MOUSEEVENTF_LEFTUP),
        )
        sent = user32.SendInput(2, events, ctypes.sizeof(Input))
        if sent != 2:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if original_position is not None:
            set_cursor_position(*original_position)


def click_client_point(
    hwnd: int,
    x: int,
    y: int,
    *,
    preserve_cursor_position: bool = True,
) -> None:
    screen_x, screen_y = client_to_screen_point(hwnd, x, y)
    click_screen_point(screen_x, screen_y, preserve_cursor_position=preserve_cursor_position)


def key_display_name(vk_code: int) -> str:
    return VK_DISPLAY_NAMES.get(vk_code, f"VK{vk_code}")


def is_valid_window(hwnd: int) -> bool:
    return bool(hwnd and user32.IsWindow(hwnd))


def foreground_window_handle() -> int:
    return int(user32.GetForegroundWindow() or 0)


def window_ancestor_handles(hwnd: int) -> tuple[int, ...]:
    handles: list[int] = []
    for candidate in (
        int(hwnd or 0),
        int(user32.GetAncestor(hwnd, GA_ROOT) or 0) if hwnd else 0,
        int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0) if hwnd else 0,
    ):
        if candidate and candidate not in handles:
            handles.append(candidate)
    return tuple(handles)


def window_title(hwnd: int) -> str:
    if not is_valid_window(hwnd):
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def is_window_minimized(hwnd: int) -> bool:
    return bool(is_valid_window(hwnd) and user32.IsIconic(hwnd))


def restore_window(hwnd: int) -> bool:
    if not is_valid_window(hwnd):
        return False
    if not is_window_minimized(hwnd):
        return True
    user32.ShowWindow(hwnd, SW_RESTORE)
    return not is_window_minimized(hwnd)


def set_foreground_window(hwnd: int) -> bool:
    return bool(is_valid_window(hwnd) and user32.SetForegroundWindow(hwnd))


def window_client_size(hwnd: int) -> tuple[int, int]:
    if not is_valid_window(hwnd):
        return 0, 0
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return 0, 0
    return max(0, rect.right - rect.left), max(0, rect.bottom - rect.top)


def window_process_id(hwnd: int) -> int:
    if not is_valid_window(hwnd):
        return 0
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value)


def process_image_path(process_id: int) -> str:
    if process_id <= 0:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def _process_snapshot_exe_name(process_id: int) -> str:
    if process_id <= 0:
        return ""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if int(snapshot) == INVALID_HANDLE_VALUE:
        return ""
    try:
        entry = ProcessEntry32()
        entry.dwSize = ctypes.sizeof(ProcessEntry32)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if int(entry.th32ProcessID) == process_id:
                return entry.szExeFile
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return ""
    finally:
        kernel32.CloseHandle(snapshot)


def process_executable_name(process_id: int) -> str:
    image_path = process_image_path(process_id)
    if image_path:
        return Path(image_path).name
    return _process_snapshot_exe_name(process_id)


def enum_top_level_windows() -> list[int]:
    windows: list[int] = []

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        windows.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def is_window_topmost(hwnd: int) -> bool:
    if not is_valid_window(hwnd):
        return False
    return bool(_get_window_long_ptr(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def set_window_topmost(hwnd: int, enabled: bool) -> bool:
    if not is_valid_window(hwnd):
        return False
    insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
    return bool(
        user32.SetWindowPos(
            hwnd,
            insert_after,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    )


@contextmanager
def temporarily_make_window_topmost(hwnd: int):
    was_topmost = is_window_topmost(hwnd)
    restored = False
    changed = False
    if is_valid_window(hwnd):
        restored = restore_window(hwnd)
        if restored:
            set_foreground_window(hwnd)
        if not was_topmost:
            changed = set_window_topmost(hwnd, True)
    try:
        yield restored
    finally:
        if changed and is_valid_window(hwnd):
            set_window_topmost(hwnd, False)


def parse_vk_key(key_name: str) -> int:
    key = key_name.strip()
    if not key:
        raise ValueError("按鍵不可空白")

    normalized = key.lower().replace(" ", "")
    if normalized in VK_NAMED_KEYS:
        return VK_NAMED_KEYS[normalized]

    if len(key) == 1:
        result = user32.VkKeyScanW(key)
        if result == -1:
            raise ValueError(f"不支援的按鍵：{key_name}")
        return result & 0xFF

    raise ValueError(f"不支援的按鍵：{key_name}")


def tap_hotkey(hotkey: str) -> None:
    parts = [part.strip() for part in hotkey.split("+") if part.strip()]
    if not parts:
        raise ValueError("快捷鍵不可空白")

    modifier_codes = [parse_vk_key(part) for part in parts[:-1]]
    main_code = parse_vk_key(parts[-1])

    for code in modifier_codes:
        key_down(code)

    try:
        key_down(main_code)
        key_up(main_code)
    finally:
        for code in reversed(modifier_codes):
            key_up(code)
