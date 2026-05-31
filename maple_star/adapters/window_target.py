from __future__ import annotations

from pathlib import Path

from .win_input import (
    enum_top_level_windows,
    foreground_window_handle,
    is_valid_window,
    process_executable_name,
    window_ancestor_handles,
    window_client_size,
    window_process_id,
    window_title,
)

TARGET_PROCESS_NAMES = frozenset({"msw.exe"})
TARGET_DISPLAY_NAME = "MapleStory Worlds"


def normalize_process_name(process_name: str) -> str:
    name = Path(process_name.strip()).name.lower()
    if name and not name.endswith(".exe"):
        name = f"{name}.exe"
    return name


def is_target_process_name(process_name: str) -> bool:
    return normalize_process_name(process_name) in TARGET_PROCESS_NAMES


def is_target_window(hwnd: int) -> bool:
    for candidate in window_ancestor_handles(hwnd):
        if not is_valid_window(candidate):
            continue
        if is_target_process_name(process_executable_name(window_process_id(candidate))):
            return True
    return False


def is_target_window_active() -> bool:
    return is_target_window(foreground_window_handle())


def foreground_window_title() -> str:
    return window_title(foreground_window_handle())


def find_target_window() -> int:
    foreground_hwnd = foreground_window_handle()
    if is_target_window(foreground_hwnd):
        return foreground_hwnd

    candidates: list[tuple[int, int]] = []
    for hwnd in enum_top_level_windows():
        if not is_target_window(hwnd):
            continue
        width, height = window_client_size(hwnd)
        area = width * height
        if area <= 0:
            continue
        candidates.append((area, hwnd))

    if not candidates:
        return 0
    candidates.sort(reverse=True)
    return candidates[0][1]
