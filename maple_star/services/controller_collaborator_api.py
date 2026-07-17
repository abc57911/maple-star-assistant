from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Callable, Protocol


ToggleBeepPattern = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ControllerModuleAdapters:
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    thread_factory: Callable[..., Thread]
    winmm_provider: Callable[[], object]
    user32_provider: Callable[[], object]
    beep: Callable[[int, int], None]
    message_beep: Callable[..., None]
    play_sound: Callable[..., None]
    key_down: Callable[[int], None]
    key_up: Callable[[int], None]
    tap_hotkey: Callable[..., None]
    save_settings: Callable[..., None]


class RuntimeMediaSink(Protocol):
    def play_media(self, path: Path, alias: str) -> None: ...

    def play_toggle_beep(self, pattern: ToggleBeepPattern) -> None: ...


__all__ = [
    "ControllerModuleAdapters",
    "RuntimeMediaSink",
    "ToggleBeepPattern",
]
