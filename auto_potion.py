from __future__ import annotations

import ctypes
import json
import sys
import time
import tkinter as tk
import winsound
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from ctypes import wintypes
from typing import Callable

import mss
import numpy as np


BASE_CAPTURE_WIDTH = 1920
BASE_CAPTURE_HEIGHT = 1080
HP_BAR_REGION = (488, 1018, 255, 28)
MP_BAR_REGION = (798, 1018, 255, 28)
DEFAULT_CAPTURE_INTERVAL_SECONDS = 0.05
BAR_SEARCH_MIN_RUN_PIXELS = 24
FULL_BAR_SNAP_PERCENT = 98.5
BAR_COLUMN_FILL_MIN_RATIO = 0.16
BAR_LEFT_EDGE_TOLERANCE_RATIO = 0.08
BAR_MAX_INTERNAL_GAP_RATIO = 0.03
BAR_MIN_SEGMENT_DENSITY = 0.35
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_NOREPEAT = 0x4000
VK_F11 = 0x7A
ASYNC_KEY_DOWN_MASK = 0x8000
SCRIPT_TOGGLE_HOTKEY_ID = 0x4D53
PAUSE_BEEP_FREQUENCY = 440
RESUME_BEEP_FREQUENCY = 880
TOGGLE_BEEP_DURATION_MS = 90
TOGGLE_HOTKEY_DEBOUNCE_SECONDS = 0.25
FADE_GUARD_MEAN_LUMINANCE = 75.0
FADE_GUARD_BRIGHT_PIXEL_RATIO = 0.12
FADE_GUARD_REQUIRED_FRAMES = 3
FADE_GUARD_RECOVERY_SECONDS = 0.6
LOADING_GUARD_MEAN_LUMINANCE = 185.0
LOADING_GUARD_BRIGHT_PIXEL_RATIO = 0.55
LOADING_GUARD_LOW_SATURATION_RATIO = 0.45
SETTINGS_SAVE_DEBOUNCE_SECONDS = 0.5
MAX_CONSOLE_LINES = 300


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SETTINGS_PATH = app_base_dir() / "settings.json"

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

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

KEYSYM_ALIASES = {
    "Return": "Enter",
    "Escape": "Escape",
    "BackSpace": "Backspace",
    "Tab": "Tab",
    "space": "Space",
    "Delete": "Delete",
    "Insert": "Insert",
    "Home": "Home",
    "End": "End",
    "Prior": "PageUp",
    "Next": "PageDown",
    "Left": "Left",
    "Right": "Right",
    "Up": "Up",
    "Down": "Down",
    "minus": "-",
    "equal": "=",
    "bracketleft": "[",
    "bracketright": "]",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "grave": "`",
}
MODIFIER_KEYSYMS = {
    "Shift_L",
    "Shift_R",
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
}


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


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(Point)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
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
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass
class AutoPotionSettings:
    hp_enabled: bool = True
    mp_enabled: bool = True
    rb_enabled: bool = False
    hp_threshold_percent: float = 50.0
    mp_threshold_percent: float = 30.0
    hp_key: str = "Delete"
    mp_key: str = "End"
    hp_cooldown_seconds: float = 0.2
    mp_cooldown_seconds: float = 0.2
    rb_jump_key: str = "X"
    rb_skill_key: str = "C"
    rb_skill_delay_seconds: float = 0.2
    rb_jump_interval_seconds: float = 0.66
    lb_enabled: bool = False
    lb_jump_key: str = "X"
    lb_skill_key: str = "C"
    lb_skill_delay_seconds: float = 0.2

    def snapshot(self) -> tuple[bool, bool, bool, float, float, str, str, float, float, str, str, float, float, bool, str, str, float]:
        return (
            self.hp_enabled,
            self.mp_enabled,
            self.rb_enabled,
            self.hp_threshold_percent,
            self.mp_threshold_percent,
            self.hp_key,
            self.mp_key,
            self.hp_cooldown_seconds,
            self.mp_cooldown_seconds,
            self.rb_jump_key,
            self.rb_skill_key,
            self.rb_skill_delay_seconds,
            self.rb_jump_interval_seconds,
            self.lb_enabled,
            self.lb_jump_key,
            self.lb_skill_key,
            self.lb_skill_delay_seconds,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "hp_enabled": self.hp_enabled,
            "mp_enabled": self.mp_enabled,
            "rb_enabled": self.rb_enabled,
            "hp_threshold_percent": self.hp_threshold_percent,
            "mp_threshold_percent": self.mp_threshold_percent,
            "hp_key": self.hp_key,
            "mp_key": self.mp_key,
            "hp_cooldown_seconds": self.hp_cooldown_seconds,
            "mp_cooldown_seconds": self.mp_cooldown_seconds,
            "rb_jump_key": self.rb_jump_key,
            "rb_skill_key": self.rb_skill_key,
            "rb_skill_delay_seconds": self.rb_skill_delay_seconds,
            "rb_jump_interval_seconds": self.rb_jump_interval_seconds,
            "lb_enabled": self.lb_enabled,
            "lb_jump_key": self.lb_jump_key,
            "lb_skill_key": self.lb_skill_key,
            "lb_skill_delay_seconds": self.lb_skill_delay_seconds,
        }


def _read_bool(data: dict[str, object], key: str, fallback: bool) -> bool:
    value = data.get(key, fallback)
    return value if isinstance(value, bool) else fallback


def _read_float(data: dict[str, object], key: str, fallback: float, minimum: float, maximum: float) -> float:
    value = data.get(key, fallback)
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _read_string(data: dict[str, object], key: str, fallback: str) -> str:
    value = data.get(key, fallback)
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    return value or fallback


def load_settings(path: Path = SETTINGS_PATH) -> AutoPotionSettings:
    settings = AutoPotionSettings()
    if not path.exists():
        return settings

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"讀取設定失敗，使用預設值：{exc}")
        return settings

    if not isinstance(raw, dict):
        print("設定檔格式錯誤，使用預設值")
        return settings

    return AutoPotionSettings(
        hp_enabled=_read_bool(raw, "hp_enabled", settings.hp_enabled),
        mp_enabled=_read_bool(raw, "mp_enabled", settings.mp_enabled),
        rb_enabled=_read_bool(raw, "rb_enabled", settings.rb_enabled),
        hp_threshold_percent=_read_float(raw, "hp_threshold_percent", settings.hp_threshold_percent, 1.0, 100.0),
        mp_threshold_percent=_read_float(raw, "mp_threshold_percent", settings.mp_threshold_percent, 1.0, 100.0),
        hp_key=_read_string(raw, "hp_key", settings.hp_key),
        mp_key=_read_string(raw, "mp_key", settings.mp_key),
        hp_cooldown_seconds=_read_float(raw, "hp_cooldown_seconds", settings.hp_cooldown_seconds, 0.05, 60.0),
        mp_cooldown_seconds=_read_float(raw, "mp_cooldown_seconds", settings.mp_cooldown_seconds, 0.05, 60.0),
        rb_jump_key=_read_string(raw, "rb_jump_key", settings.rb_jump_key),
        rb_skill_key=_read_string(raw, "rb_skill_key", settings.rb_skill_key),
        rb_skill_delay_seconds=_read_float(raw, "rb_skill_delay_seconds", settings.rb_skill_delay_seconds, 0.0, 10.0),
        rb_jump_interval_seconds=_read_float(raw, "rb_jump_interval_seconds", settings.rb_jump_interval_seconds, 0.05, 10.0),
        lb_enabled=_read_bool(raw, "lb_enabled", settings.lb_enabled),
        lb_jump_key=_read_string(raw, "lb_jump_key", settings.lb_jump_key),
        lb_skill_key=_read_string(raw, "lb_skill_key", settings.lb_skill_key),
        lb_skill_delay_seconds=_read_float(raw, "lb_skill_delay_seconds", settings.lb_skill_delay_seconds, 0.0, 10.0),
    )


def save_settings(settings: AutoPotionSettings, path: Path = SETTINGS_PATH) -> None:
    path.write_text(
        json.dumps(settings.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def event_to_hotkey(event: tk.Event) -> str | None:
    keysym = str(event.keysym)
    if keysym in MODIFIER_KEYSYMS:
        return None

    if keysym.startswith("KP_") and len(keysym) == 4 and keysym[-1].isdigit():
        key = keysym[-1]
    elif len(keysym) == 1:
        key = keysym.upper() if keysym.isalpha() else keysym
    elif keysym.upper().startswith("F") and keysym[1:].isdigit():
        key = keysym.upper()
    else:
        key = KEYSYM_ALIASES.get(keysym, keysym)

    return key


def normalize_bar_percent(percent: float) -> float:
    percent = max(0.0, min(100.0, percent))
    if percent >= FULL_BAR_SNAP_PERCENT:
        return 100.0
    return percent


def loading_screen_metrics(image: np.ndarray) -> tuple[float, float, float]:
    sample = image[::8, ::8, :3].astype(np.float32)
    blue = sample[:, :, 0]
    green = sample[:, :, 1]
    red = sample[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    return (
        float(luminance.mean()),
        float((luminance > 210.0).mean()),
        float((chroma < 25.0).mean()),
    )


class GuiConsoleWriter:
    def __init__(self, gui: AutoPotionSettingsGui, original: object | None = None) -> None:
        self.gui = gui
        self.original = original

    def write(self, text: str) -> int:
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        self.gui.append_console(text)
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass


class AutoPotionSettingsGui:
    def __init__(self, settings: AutoPotionSettings) -> None:
        self.settings = settings
        self.closed = False
        self.root = tk.Tk()
        self.root.title("自動喝水設定")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.detecting_key_target: tk.StringVar | None = None
        self.detecting_key_label = ""
        self.key_detection_window: tk.Toplevel | None = None

        self.hp_enabled = tk.BooleanVar(value=settings.hp_enabled)
        self.mp_enabled = tk.BooleanVar(value=settings.mp_enabled)
        self.rb_enabled = tk.BooleanVar(value=settings.rb_enabled)
        self.hp_threshold = tk.DoubleVar(value=settings.hp_threshold_percent)
        self.mp_threshold = tk.DoubleVar(value=settings.mp_threshold_percent)
        self.hp_threshold_text = tk.StringVar(value=f"{settings.hp_threshold_percent:.0f}")
        self.mp_threshold_text = tk.StringVar(value=f"{settings.mp_threshold_percent:.0f}")
        self.hp_key = tk.StringVar(value=settings.hp_key)
        self.mp_key = tk.StringVar(value=settings.mp_key)
        self.hp_cooldown = tk.StringVar(value=f"{settings.hp_cooldown_seconds:g}")
        self.mp_cooldown = tk.StringVar(value=f"{settings.mp_cooldown_seconds:g}")
        self.rb_jump_key = tk.StringVar(value=settings.rb_jump_key)
        self.rb_skill_key = tk.StringVar(value=settings.rb_skill_key)
        self.rb_skill_delay = tk.StringVar(value=f"{settings.rb_skill_delay_seconds:g}")
        self.rb_jump_interval = tk.StringVar(value=f"{settings.rb_jump_interval_seconds:g}")
        self.lb_enabled = tk.BooleanVar(value=settings.lb_enabled)
        self.lb_jump_key = tk.StringVar(value=settings.lb_jump_key)
        self.lb_skill_key = tk.StringVar(value=settings.lb_skill_key)
        self.lb_skill_delay = tk.StringVar(value=f"{settings.lb_skill_delay_seconds:g}")
        self.hp_current = tk.StringVar(value="HP: --%")
        self.mp_current = tk.StringVar(value="MP: --%")
        self.status = tk.StringVar(value="只在楓星為前景視窗時生效")

        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        self._build_row(controls, 0, "紅水", self.hp_enabled, self.hp_threshold, self.hp_threshold_text, self.hp_key, self.hp_cooldown, self.hp_current)
        self._build_row(controls, 1, "藍水", self.mp_enabled, self.mp_threshold, self.mp_threshold_text, self.mp_key, self.mp_cooldown, self.mp_current)

        rb_frame = ttk.LabelFrame(frame, text="RB function")
        rb_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for column in range(8):
            rb_frame.columnconfigure(column, weight=0)
        rb_frame.columnconfigure(7, weight=1)
        ttk.Checkbutton(rb_frame, text="啟用", variable=self.rb_enabled).grid(row=0, column=0, sticky="w", padx=(8, 12), pady=6)
        self._build_key_entry(rb_frame, 0, 1, "跳躍鍵", self.rb_jump_key)
        self._build_key_entry(rb_frame, 0, 3, "技能鍵", self.rb_skill_key)
        ttk.Label(rb_frame, text="技能延遲").grid(row=0, column=5, sticky="w", padx=(12, 4), pady=6)
        ttk.Entry(rb_frame, width=6, textvariable=self.rb_skill_delay).grid(row=0, column=6, sticky="w", padx=(0, 4), pady=6)
        ttk.Label(rb_frame, text="秒").grid(row=0, column=7, sticky="w", pady=6)
        ttk.Label(rb_frame, text="跳躍間隔").grid(row=1, column=5, sticky="w", padx=(12, 4), pady=(0, 8))
        ttk.Entry(rb_frame, width=6, textvariable=self.rb_jump_interval).grid(row=1, column=6, sticky="w", padx=(0, 4), pady=(0, 8))
        ttk.Label(rb_frame, text="秒").grid(row=1, column=7, sticky="w", pady=(0, 8))

        lb_frame = ttk.LabelFrame(frame, text="LB function")
        lb_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for column in range(8):
            lb_frame.columnconfigure(column, weight=0)
        lb_frame.columnconfigure(7, weight=1)
        ttk.Checkbutton(lb_frame, text="啟用", variable=self.lb_enabled).grid(row=0, column=0, sticky="w", padx=(8, 12), pady=6)
        self._build_key_entry(lb_frame, 0, 1, "跳躍鍵", self.lb_jump_key)
        self._build_key_entry(lb_frame, 0, 3, "技能鍵", self.lb_skill_key)
        ttk.Label(lb_frame, text="技能延遲").grid(row=0, column=5, sticky="w", padx=(12, 4), pady=6)
        ttk.Entry(lb_frame, width=6, textvariable=self.lb_skill_delay).grid(row=0, column=6, sticky="w", padx=(0, 4), pady=6)
        ttk.Label(lb_frame, text="秒").grid(row=0, column=7, sticky="w", pady=6)

        ttk.Label(frame, textvariable=self.status).grid(row=3, column=0, sticky="w", pady=(10, 4))

        console_frame = ttk.LabelFrame(frame, text="Console")
        console_frame.grid(row=4, column=0, sticky="nsew")
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)
        self.console = tk.Text(console_frame, height=10, width=92, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _build_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        enabled_var: tk.BooleanVar,
        threshold_var: tk.DoubleVar,
        threshold_text: tk.StringVar,
        key_var: tk.StringVar,
        cooldown_var: tk.StringVar,
        current_var: tk.StringVar,
    ) -> None:
        ttk.Checkbutton(parent, text=label, variable=enabled_var).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        scale = ttk.Scale(
            parent,
            from_=1,
            to=100,
            orient="horizontal",
            variable=threshold_var,
            command=lambda value, text=threshold_text: text.set(f"{float(value):.0f}"),
            length=160,
        )
        scale.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, width=5, textvariable=threshold_text)
        entry.grid(row=row, column=2, sticky="w", padx=(0, 4), pady=4)
        ttk.Label(parent, text="%").grid(row=row, column=3, sticky="w", padx=(0, 10), pady=4)
        key_entry = ttk.Entry(parent, width=10, textvariable=key_var)
        key_entry.grid(row=row, column=4, sticky="w", padx=(0, 8), pady=4)
        key_entry.bind("<Button-1>", lambda _event, var=key_var, name=label: self.start_key_detection(var, name))
        ttk.Entry(parent, width=6, textvariable=cooldown_var).grid(row=row, column=5, sticky="w", padx=(0, 4), pady=4)
        ttk.Label(parent, text="秒").grid(row=row, column=6, sticky="w", pady=4)
        ttk.Label(parent, textvariable=current_var, width=9).grid(row=row, column=7, sticky="e", padx=(12, 0), pady=4)

        entry.bind("<Return>", lambda _event, var=threshold_var, text=threshold_text: self._apply_percent_text(var, text))
        entry.bind("<FocusOut>", lambda _event, var=threshold_var, text=threshold_text: self._apply_percent_text(var, text))

    def _build_key_entry(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        key_var: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 4), pady=6)
        key_entry = ttk.Entry(parent, width=9, textvariable=key_var)
        key_entry.grid(row=row, column=column + 1, sticky="w", padx=(0, 8), pady=6)
        key_entry.bind("<Button-1>", lambda _event, var=key_var, name=label: self.start_key_detection(var, name))

    def _apply_percent_text(self, value_var: tk.DoubleVar, text_var: tk.StringVar) -> None:
        try:
            value = max(1.0, min(100.0, float(text_var.get())))
        except ValueError:
            value = value_var.get()

        value_var.set(value)
        text_var.set(f"{value:.0f}")

    def close(self) -> None:
        self.cancel_key_detection()
        self.closed = True
        self.root.destroy()

    def start_key_detection(self, target: tk.StringVar, label: str) -> str:
        self.cancel_key_detection()
        self.detecting_key_target = target
        self.detecting_key_label = label
        self.set_status(f"請按下要設定為 {label} 的按鍵")
        self.key_detection_window = tk.Toplevel(self.root)
        self.key_detection_window.title("快捷鍵偵測")
        self.key_detection_window.resizable(False, False)
        self.key_detection_window.transient(self.root)
        self.key_detection_window.attributes("-topmost", True)
        self.key_detection_window.protocol("WM_DELETE_WINDOW", self.cancel_key_detection)
        ttk.Label(
            self.key_detection_window,
            text=f"請按下要設定為 {label} 的按鍵",
            padding=16,
        ).grid(row=0, column=0, sticky="nsew")
        self.key_detection_window.update_idletasks()
        x = self.root.winfo_rootx() + 80
        y = self.root.winfo_rooty() + 80
        self.key_detection_window.geometry(f"+{x}+{y}")
        self.key_detection_window.focus_force()
        self.root.bind_all("<KeyPress>", self._capture_keypress)
        return "break"

    def _capture_keypress(self, event: tk.Event) -> str:
        if self.detecting_key_target is None:
            return "break"

        hotkey = event_to_hotkey(event)
        if hotkey is None:
            self.set_status("不支援只設定修飾鍵，請按一般按鍵")
            return "break"

        self.detecting_key_target.set(hotkey)
        self.set_status(f"{self.detecting_key_label} 快捷鍵已設定為 {hotkey}")
        self.cancel_key_detection(keep_status=True)
        return "break"

    def cancel_key_detection(self, keep_status: bool = False) -> None:
        self.root.unbind_all("<KeyPress>")
        self.detecting_key_target = None
        self.detecting_key_label = ""
        if self.key_detection_window is not None:
            try:
                self.key_detection_window.destroy()
            except tk.TclError:
                pass
            self.key_detection_window = None
        if not keep_status and not self.closed:
            self.set_status("只在楓星為前景視窗時生效")

    def pump(self) -> bool:
        if self.closed:
            return False
        try:
            self.root.update_idletasks()
            self.root.update()
            self.apply_to_settings()
            return True
        except tk.TclError:
            self.closed = True
            return False

    def apply_to_settings(self) -> None:
        self._read_percent(self.hp_threshold, self.hp_threshold_text)
        self._read_percent(self.mp_threshold, self.mp_threshold_text)
        self.settings.hp_enabled = self.hp_enabled.get()
        self.settings.mp_enabled = self.mp_enabled.get()
        self.settings.rb_enabled = self.rb_enabled.get()
        self.settings.lb_enabled = self.lb_enabled.get()
        self.settings.hp_threshold_percent = self.hp_threshold.get()
        self.settings.mp_threshold_percent = self.mp_threshold.get()
        self.settings.hp_key = self.hp_key.get().strip()
        self.settings.mp_key = self.mp_key.get().strip()
        self.settings.hp_cooldown_seconds = self._read_cooldown(self.hp_cooldown, self.settings.hp_cooldown_seconds)
        self.settings.mp_cooldown_seconds = self._read_cooldown(self.mp_cooldown, self.settings.mp_cooldown_seconds)
        self.settings.rb_jump_key = self.rb_jump_key.get().strip()
        self.settings.rb_skill_key = self.rb_skill_key.get().strip()
        self.settings.rb_skill_delay_seconds = self._read_seconds(
            self.rb_skill_delay,
            self.settings.rb_skill_delay_seconds,
            0.0,
            10.0,
        )
        self.settings.rb_jump_interval_seconds = self._read_seconds(
            self.rb_jump_interval,
            self.settings.rb_jump_interval_seconds,
            0.05,
            10.0,
        )
        self.settings.lb_jump_key = self.lb_jump_key.get().strip()
        self.settings.lb_skill_key = self.lb_skill_key.get().strip()
        self.settings.lb_skill_delay_seconds = self._read_seconds(
            self.lb_skill_delay,
            self.settings.lb_skill_delay_seconds,
            0.0,
            10.0,
        )

    def _read_cooldown(self, var: tk.StringVar, fallback: float) -> float:
        return self._read_seconds(var, fallback, 0.05, 60.0)

    def _read_seconds(self, var: tk.StringVar, fallback: float, minimum: float, maximum: float) -> float:
        try:
            value = max(minimum, min(maximum, float(var.get())))
        except ValueError:
            value = fallback
        return value

    def _read_percent(self, value_var: tk.DoubleVar, text_var: tk.StringVar) -> None:
        text = text_var.get().strip()
        if not text:
            return
        try:
            value = max(1.0, min(100.0, float(text)))
        except ValueError:
            return
        value_var.set(value)

    def set_current_percentages(self, hp_percent: float | None, mp_percent: float | None) -> None:
        self.hp_current.set("HP: --%" if hp_percent is None else f"HP: {hp_percent:.0f}%")
        self.mp_current.set("MP: --%" if mp_percent is None else f"MP: {mp_percent:.0f}%")

    def set_status(self, message: str) -> None:
        self.status.set(message)

    def append_console(self, text: str) -> None:
        if self.closed or not text:
            return
        try:
            self.console.configure(state="normal")
            self.console.insert("end", text)
            line_count = int(self.console.index("end-1c").split(".")[0])
            if line_count > MAX_CONSOLE_LINES:
                self.console.delete("1.0", f"{line_count - MAX_CONSOLE_LINES}.0")
            self.console.see("end")
            self.console.configure(state="disabled")
        except tk.TclError:
            self.closed = True


class AutoPotionController:
    def __init__(
        self,
        is_target_window_active: Callable[[], bool],
        settings: AutoPotionSettings | None = None,
    ) -> None:
        self.is_target_window_active = is_target_window_active
        self.settings = settings or load_settings()
        self.gui = AutoPotionSettingsGui(self.settings)
        self.sct = mss.mss()
        self.next_capture_at = 0.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.last_error_at = -999.0
        self.last_unstable_bar_at = -999.0
        self.scripts_enabled = True
        self.hotkey_registered = False
        self.f11_was_down = False
        self.last_toggle_hotkey_at = -999.0
        self.fade_guard_hits = 0
        self.fade_guard_until = 0.0
        self.pending_settings_snapshot = self.settings.snapshot()
        self.next_settings_save_at: float | None = None
        self.original_stdout: object | None = None
        self.original_stderr: object | None = None
        self._register_toggle_hotkey()
        save_settings(self.settings)

    def install_console_redirect(self) -> None:
        if isinstance(sys.stdout, GuiConsoleWriter):
            return
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = GuiConsoleWriter(self.gui, self.original_stdout)
        sys.stderr = GuiConsoleWriter(self.gui, self.original_stderr)

    def is_closed(self) -> bool:
        return self.gui.closed

    def _register_toggle_hotkey(self) -> None:
        if user32.RegisterHotKey(None, SCRIPT_TOGGLE_HOTKEY_ID, MOD_NOREPEAT, VK_F11):
            self.hotkey_registered = True
            return

        error_code = ctypes.get_last_error()
        print(f"註冊 F11 總開關失敗，錯誤碼：{error_code}")

    def _unregister_toggle_hotkey(self) -> None:
        if not self.hotkey_registered:
            return
        if not user32.UnregisterHotKey(None, SCRIPT_TOGGLE_HOTKEY_ID):
            print(f"解除 F11 總開關註冊失敗，錯誤碼：{ctypes.get_last_error()}")
        self.hotkey_registered = False

    def _poll_toggle_hotkey(self) -> None:
        hotkey_triggered = False
        message = Msg()
        while user32.PeekMessageW(
            ctypes.byref(message),
            None,
            WM_HOTKEY,
            WM_HOTKEY,
            PM_REMOVE,
        ):
            if message.wParam == SCRIPT_TOGGLE_HOTKEY_ID:
                hotkey_triggered = True

        f11_is_down = bool(user32.GetAsyncKeyState(VK_F11) & ASYNC_KEY_DOWN_MASK)
        if f11_is_down and not self.f11_was_down:
            hotkey_triggered = True
        self.f11_was_down = f11_is_down

        if hotkey_triggered:
            self._try_toggle_scripts_enabled(time.monotonic())

    def _try_toggle_scripts_enabled(self, now: float) -> None:
        if now - self.last_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_toggle_hotkey_at = now
        self.toggle_scripts_enabled()

    def toggle_scripts_enabled(self) -> None:
        self.scripts_enabled = not self.scripts_enabled
        if self.scripts_enabled:
            self._play_toggle_beep(RESUME_BEEP_FREQUENCY)
            self.gui.set_status("腳本已啟用")
            print("F11：腳本已啟用")
            return

        self.last_hp_drink_at = time.monotonic()
        self.last_mp_drink_at = self.last_hp_drink_at
        self._play_toggle_beep(PAUSE_BEEP_FREQUENCY)
        self.gui.set_status("腳本已暫停，按 F11 恢復")
        self.gui.set_current_percentages(None, None)
        print("F11：腳本已暫停")

    def _play_toggle_beep(self, frequency: int) -> None:
        try:
            winsound.Beep(frequency, TOGGLE_BEEP_DURATION_MS)
        except RuntimeError:
            try:
                winsound.MessageBeep()
            except RuntimeError:
                pass

    def update(self, now: float) -> None:
        self._poll_toggle_hotkey()
        if not self.gui.pump():
            return
        self._poll_toggle_hotkey()
        self._save_settings_when_idle(now)

        if now < self.next_capture_at:
            return
        self.next_capture_at = now + DEFAULT_CAPTURE_INTERVAL_SECONDS

        if not self.scripts_enabled:
            self.gui.set_status("腳本已暫停，按 F11 恢復")
            self.gui.set_current_percentages(None, None)
            return

        if not self.is_target_window_active():
            self.gui.set_status("等待楓星成為前景視窗")
            self.gui.set_current_percentages(None, None)
            return

        try:
            transition_pause_reason = self._transition_pause_reason(now)
            if transition_pause_reason:
                self.gui.set_status(transition_pause_reason)
                self.gui.set_current_percentages(None, None)
                return

            hp_percent = self._capture_bar_percent(HP_BAR_REGION, "hp")
            mp_percent = self._capture_bar_percent(MP_BAR_REGION, "mp")
            self.gui.set_current_percentages(hp_percent, mp_percent)
            if hp_percent is None or mp_percent is None:
                self.gui.set_status("HP/MP 條偵測不穩定，略過錯誤取樣")
            else:
                self.gui.set_status("自動喝水監控中")
            self._maybe_drink_hp(now, hp_percent)
            self._maybe_drink_mp(now, mp_percent)
        except Exception as exc:
            if now - self.last_error_at >= 2.0:
                print(f"自動喝水錯誤：{exc}")
                self.gui.set_status(f"錯誤：{exc}")
                self.last_error_at = now

    def _save_settings_when_idle(self, now: float) -> None:
        snapshot = self.settings.snapshot()
        if snapshot != self.pending_settings_snapshot:
            self.pending_settings_snapshot = snapshot
            self.next_settings_save_at = now + SETTINGS_SAVE_DEBOUNCE_SECONDS

        if self.next_settings_save_at is not None and now >= self.next_settings_save_at:
            save_settings(self.settings)
            self.next_settings_save_at = None

    def _maybe_drink_hp(self, now: float, hp_percent: float | None) -> None:
        if not self.settings.hp_enabled:
            return
        if hp_percent is None:
            self._log_unstable_bar(now, "HP")
            return
        if hp_percent > self.settings.hp_threshold_percent:
            return
        if now - self.last_hp_drink_at < self.settings.hp_cooldown_seconds:
            return

        hp_percent = self._capture_bar_percent(HP_BAR_REGION, "hp")
        if hp_percent is None:
            self._log_unstable_bar(now, "HP")
            return
        if hp_percent > self.settings.hp_threshold_percent:
            return

        tap_hotkey(self.settings.hp_key)
        self.last_hp_drink_at = now
        print(f"HP {hp_percent:.0f}% <= {self.settings.hp_threshold_percent:.0f}%，按 {self.settings.hp_key}")

    def _maybe_drink_mp(self, now: float, mp_percent: float | None) -> None:
        if not self.settings.mp_enabled:
            return
        if mp_percent is None:
            self._log_unstable_bar(now, "MP")
            return
        if mp_percent > self.settings.mp_threshold_percent:
            return
        if now - self.last_mp_drink_at < self.settings.mp_cooldown_seconds:
            return

        mp_percent = self._capture_bar_percent(MP_BAR_REGION, "mp")
        if mp_percent is None:
            self._log_unstable_bar(now, "MP")
            return
        if mp_percent > self.settings.mp_threshold_percent:
            return

        tap_hotkey(self.settings.mp_key)
        self.last_mp_drink_at = now
        print(f"MP {mp_percent:.0f}% <= {self.settings.mp_threshold_percent:.0f}%，按 {self.settings.mp_key}")

    def _log_unstable_bar(self, now: float, label: str) -> None:
        if now - self.last_unstable_bar_at < 2.0:
            return
        self.last_unstable_bar_at = now
        print(f"{label} 條偵測不穩定，略過自動喝水")

    def _capture_bar_percent(self, base_region: tuple[int, int, int, int], bar_type: str) -> float | None:
        left, top, width, height = self._scale_region_to_foreground_client(base_region)
        percent = self._capture_bar_percent_from_region((left, top, width, height), bar_type)
        if percent is not None:
            return percent

        dynamic_region = self._find_bar_region_near_bottom(bar_type)
        if dynamic_region is None:
            return None

        percent = self._capture_bar_percent_from_region(dynamic_region, bar_type)
        return percent

    def _capture_bar_percent_from_region(self, region: tuple[int, int, int, int], bar_type: str) -> float | None:
        left, top, width, height = region
        image = np.asarray(self.sct.grab({"left": left, "top": top, "width": width, "height": height}))
        mask = self._bar_color_mask(image, bar_type)
        return self._percent_from_bar_mask(mask)

    def _percent_from_bar_mask(self, mask: np.ndarray) -> float | None:
        _height, width = mask.shape
        column_filled = mask.mean(axis=0) > BAR_COLUMN_FILL_MIN_RATIO
        filled_indexes = np.flatnonzero(column_filled)
        if filled_indexes.size == 0:
            return None

        left_tolerance = max(2, round(width * BAR_LEFT_EDGE_TOLERANCE_RATIO))
        first_filled = int(filled_indexes[0])
        if first_filled > left_tolerance:
            return None

        closed_columns = column_filled.copy()
        max_gap = max(1, round(width * BAR_MAX_INTERNAL_GAP_RATIO))
        run_edges = np.flatnonzero(np.diff(np.concatenate(([False], column_filled, [False]))))
        for gap_start, gap_end in zip(run_edges[1::2], run_edges[2::2]):
            if gap_end - gap_start <= max_gap:
                closed_columns[gap_start:gap_end] = True

        start = int(np.flatnonzero(closed_columns)[0])
        end = start
        while end + 1 < width and closed_columns[end + 1]:
            end += 1

        segment_width = end - start + 1
        if segment_width <= 0:
            return None

        segment_density = float(column_filled[start : end + 1].mean())
        if segment_density < BAR_MIN_SEGMENT_DENSITY:
            return None

        return normalize_bar_percent(float((end + 1) / width * 100.0))

    def _bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        bgra = image[:, :, :3]
        blue = bgra[:, :, 0].astype(np.int16)
        green = bgra[:, :, 1].astype(np.int16)
        red = bgra[:, :, 2].astype(np.int16)

        if bar_type == "hp":
            return (red > 150) & (green < 120) & (blue < 150) & (red > green + 40) & (red > blue + 40)
        return (blue > 140) & (green > 75) & (red < 140) & (blue > red + 35)

    def _find_bar_region_near_bottom(self, bar_type: str) -> tuple[int, int, int, int] | None:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        search_left = client_left + round(client_width * 0.18)
        search_top = client_top + round(client_height * 0.82)
        search_width = max(1, round(client_width * 0.48))
        search_height = max(1, round(client_height * 0.16))

        image = np.asarray(
            self.sct.grab(
                {
                    "left": search_left,
                    "top": search_top,
                    "width": search_width,
                    "height": search_height,
                }
            )
        )
        mask = self._bar_color_mask(image, bar_type)
        best_run: tuple[int, int, int] | None = None

        for row_index, row in enumerate(mask):
            padded = np.concatenate(([False], row, [False]))
            changes = np.flatnonzero(padded[1:] != padded[:-1])
            for start, end in zip(changes[::2], changes[1::2]):
                run_length = int(end - start)
                if run_length < BAR_SEARCH_MIN_RUN_PIXELS:
                    continue
                if best_run is None or run_length > best_run[2]:
                    best_run = (int(start), int(row_index), run_length)

        if best_run is None:
            return None

        run_start, row_index, _run_length = best_run
        expected_width = max(1, round(client_width * (HP_BAR_REGION[2] / BASE_CAPTURE_WIDTH)))
        expected_height = max(1, round(client_height * (HP_BAR_REGION[3] / BASE_CAPTURE_HEIGHT)))
        return (
            search_left + max(0, run_start - 4),
            search_top + max(0, row_index - expected_height // 2),
            expected_width,
            expected_height,
        )

    def _is_transition_fade_active(self) -> bool:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        sample_top = client_top + round(client_height * 0.88)
        sample_height = max(1, round(client_height * 0.10))
        image = np.asarray(
            self.sct.grab(
                {
                    "left": client_left,
                    "top": sample_top,
                    "width": client_width,
                    "height": sample_height,
                }
            )
        )
        bgra = image[:, :, :3].astype(np.float32)
        luminance = bgra[:, :, 2] * 0.299 + bgra[:, :, 1] * 0.587 + bgra[:, :, 0] * 0.114
        mean_luminance = float(luminance.mean())
        bright_pixel_ratio = float((luminance > 110.0).mean())
        return (
            mean_luminance < FADE_GUARD_MEAN_LUMINANCE
            and bright_pixel_ratio < FADE_GUARD_BRIGHT_PIXEL_RATIO
        )

    def _is_channel_loading_screen_active(self) -> bool:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        sample_left = client_left + round(client_width * 0.14)
        sample_top = client_top + round(client_height * 0.12)
        sample_width = max(1, round(client_width * 0.72))
        sample_height = max(1, round(client_height * 0.76))
        image = np.asarray(
            self.sct.grab(
                {
                    "left": sample_left,
                    "top": sample_top,
                    "width": sample_width,
                    "height": sample_height,
                }
            )
        )
        mean_luminance, bright_pixel_ratio, low_saturation_ratio = loading_screen_metrics(image)
        return (
            mean_luminance > LOADING_GUARD_MEAN_LUMINANCE
            and bright_pixel_ratio > LOADING_GUARD_BRIGHT_PIXEL_RATIO
            and low_saturation_ratio > LOADING_GUARD_LOW_SATURATION_RATIO
        )

    def _transition_pause_reason(self, now: float) -> str | None:
        pause_reason = None
        if self._is_channel_loading_screen_active():
            pause_reason = "偵測到頻道切換載入頁，暫停自動喝水"
        elif self._is_transition_fade_active():
            pause_reason = "偵測到地圖過場暗幕，暫停自動喝水"

        if pause_reason is not None:
            self.fade_guard_hits += 1
            self.last_hp_drink_at = now
            self.last_mp_drink_at = now
            if self.fade_guard_hits >= FADE_GUARD_REQUIRED_FRAMES:
                self.fade_guard_until = now + FADE_GUARD_RECOVERY_SECONDS
            return pause_reason

        self.fade_guard_hits = 0
        if now < self.fade_guard_until:
            self.last_hp_drink_at = now
            self.last_mp_drink_at = now
            return "過場恢復中，暫停自動喝水"
        return None

    def _scale_region_to_foreground_client(self, base_region: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        scale_x = client_width / BASE_CAPTURE_WIDTH
        scale_y = client_height / BASE_CAPTURE_HEIGHT
        x, y, width, height = base_region
        return (
            client_left + round(x * scale_x),
            client_top + round(y * scale_y),
            max(1, round(width * scale_x)),
            max(1, round(height * scale_y)),
        )

    def _foreground_client_bounds(self) -> tuple[int, int, int, int]:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("找不到前景視窗")

        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())

        client_width = rect.right - rect.left
        client_height = rect.bottom - rect.top
        if client_width <= 0 or client_height <= 0:
            raise RuntimeError("前景視窗 client area 尺寸無效")

        origin = Point(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise ctypes.WinError(ctypes.get_last_error())

        return origin.x, origin.y, client_width, client_height

    def cleanup(self) -> None:
        self._unregister_toggle_hotkey()
        try:
            save_settings(self.settings)
        except Exception as exc:
            print(f"儲存設定失敗：{exc}")
        try:
            self.sct.close()
        except Exception:
            pass
        if not self.gui.closed:
            self.gui.close()
        if self.original_stdout is not None:
            sys.stdout = self.original_stdout
        if self.original_stderr is not None:
            sys.stderr = self.original_stderr
