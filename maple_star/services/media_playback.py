from __future__ import annotations

import ctypes
from pathlib import Path
from threading import Thread
from typing import Callable

from ..constants import (
    EMERGENCY_STOP_BEEP_PATTERN,
    LIE_DETECTOR_ALERT_BEEP_PATTERN,
)
from .controller_collaborator_api import (
    ControllerModuleAdapters,
    RuntimeMediaSink,
    ToggleBeepPattern,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_VOLUME_PERCENT = 20
MCI_MAX_VOLUME = 1000
MCI_MEDIA_VOLUME = round(MCI_MAX_VOLUME * MEDIA_VOLUME_PERCENT / 100)
MCI_MEDIA_START_MS = 0
WINDOWS_MEDIA_DIR = Path("C:/Windows/Media")
MINIMAP_CRUISE_START_WAV_PATH = WINDOWS_MEDIA_DIR / "Windows Notify System Generic.wav"
MINIMAP_CRUISE_STOP_WAV_PATH = WINDOWS_MEDIA_DIR / "Windows Default.wav"
AUTO_DRINK_START_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-start.mp3"
AUTO_DRINK_STOP_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-stop.mp3"
AUTO_DRINK_POTION_CHECK_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-postion-check.mp3"
AUTO_PICKUP_START_SOUND_PATH = PROJECT_ROOT / "media" / "auto-pickup-start.mp3"
AUTO_PICKUP_STOP_SOUND_PATH = PROJECT_ROOT / "media" / "auto-pickup-stop.mp3"
LIE_DETECTOR_ALERT_SOUND_PATH = PROJECT_ROOT / "media" / "captcha.mp3"
MEDIA_SOUND_ALIASES = (
    (AUTO_DRINK_START_SOUND_PATH, "auto_drink_start"),
    (AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop"),
    (AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check"),
    (AUTO_PICKUP_START_SOUND_PATH, "pickup_start"),
    (AUTO_PICKUP_STOP_SOUND_PATH, "pickup_stop"),
)
MEDIA_SOUND_PATH_BY_ALIAS = {alias: path for path, alias in MEDIA_SOUND_ALIASES}


class MediaPlaybackService:
    def __init__(
        self,
        adapters: ControllerModuleAdapters,
        *,
        sink: RuntimeMediaSink | None = None,
    ) -> None:
        self._adapters = adapters
        self._sink = sink
        self.alias_paths: dict[str, tuple[Path, str, int]] = {}
        self.alert_thread: Thread | None = None
        self._lie_detector_volume_percent: object = 80
        self._closed = False

    def preload(self, on_failure: Callable[[], None] | None = None) -> None:
        if self._sink is not None or self._closed:
            return
        try:
            winmm = self._adapters.winmm_provider()
            buffer = ctypes.create_unicode_buffer(256)
            for path, alias in MEDIA_SOUND_ALIASES:
                if path.exists():
                    self.ensure_media_alias_opened(
                        winmm,
                        buffer,
                        path,
                        alias,
                        MCI_MEDIA_VOLUME,
                        "mpegvideo",
                        on_failure=on_failure,
                    )
        except Exception:
            return

    def play_toggle_beep(self, pattern: ToggleBeepPattern) -> None:
        if self._sink is not None:
            self._sink.play_toggle_beep(pattern)
            return
        try:
            for frequency, duration_ms in pattern:
                self._adapters.beep(frequency, duration_ms)
        except RuntimeError:
            try:
                self._adapters.message_beep()
            except RuntimeError:
                return

    def play_system_notification(self) -> None:
        if self._sink is not None:
            return
        try:
            self._adapters.message_beep(0x00000040)
        except (AttributeError, RuntimeError):
            try:
                self._adapters.message_beep()
            except RuntimeError:
                return

    def play_minimap_toggle(self, enabled: bool) -> None:
        if self._sink is not None:
            return
        path = MINIMAP_CRUISE_START_WAV_PATH if enabled else MINIMAP_CRUISE_STOP_WAV_PATH
        try:
            self._adapters.play_sound(str(path), 0x00020000 | 0x0001)
        except Exception:
            try:
                self.play_system_notification()
            except Exception:
                return

    def play_media(
        self,
        path: Path,
        alias: str,
        *,
        on_failure: Callable[[], None] | None = None,
    ) -> bool:
        return self.play_media_with_volume(
            path,
            alias,
            MCI_MEDIA_VOLUME,
            media_type="mpegvideo",
            on_failure=on_failure,
        )

    def play_media_with_volume(
        self,
        path: Path,
        alias: str,
        volume: int,
        *,
        media_type: str,
        on_failure: Callable[[], None] | None = None,
    ) -> bool:
        if self._sink is not None:
            self._sink.play_media(path, alias)
            return True
        if not path.exists():
            self._notify_failure(on_failure)
            return False
        try:
            winmm = self._adapters.winmm_provider()
            buffer = ctypes.create_unicode_buffer(256)
            if not self.ensure_media_alias_opened(
                winmm,
                buffer,
                path,
                alias,
                volume,
                media_type,
                on_failure=on_failure,
            ):
                return False
            if self.play_open_media_alias(winmm, buffer, alias, volume):
                return True
            self.close_media_alias(winmm, buffer, alias)
            if self.ensure_media_alias_opened(
                winmm,
                buffer,
                path,
                alias,
                volume,
                media_type,
                on_failure=on_failure,
            ) and self.play_open_media_alias(winmm, buffer, alias, volume):
                return True
            self._notify_failure(on_failure)
        except Exception:
            self._notify_failure(on_failure)
        return False

    def ensure_media_alias_opened(
        self,
        winmm: object,
        buffer: object,
        path: Path,
        alias: str,
        volume: int,
        media_type: str,
        *,
        on_failure: Callable[[], None] | None = None,
    ) -> bool:
        alias_state = (path, media_type, volume)
        if self.alias_paths.get(alias) == alias_state:
            return True
        self.close_media_alias(winmm, buffer, alias)
        open_command = f'open "{path}" type {media_type} alias {alias}'
        if winmm.mciSendStringW(open_command, buffer, len(buffer), None) != 0:
            self._notify_failure(on_failure)
            return False
        if winmm.mciSendStringW(f"setaudio {alias} volume to {volume}", buffer, len(buffer), None) != 0:
            self.close_media_alias(winmm, buffer, alias)
            self._notify_failure(on_failure)
            return False
        if winmm.mciSendStringW(f"set {alias} time format milliseconds", buffer, len(buffer), None) != 0:
            self.close_media_alias(winmm, buffer, alias)
            self._notify_failure(on_failure)
            return False
        self.alias_paths[alias] = alias_state
        return True

    @staticmethod
    def play_open_media_alias(winmm: object, buffer: object, alias: str, volume: int) -> bool:
        if winmm.mciSendStringW(f"stop {alias}", buffer, len(buffer), None) != 0:
            return False
        if winmm.mciSendStringW(f"setaudio {alias} volume to {volume}", buffer, len(buffer), None) != 0:
            return False
        return winmm.mciSendStringW(
            f"play {alias} from {MCI_MEDIA_START_MS}", buffer, len(buffer), None
        ) == 0

    def close_media_alias(self, winmm: object, buffer: object, alias: str) -> None:
        winmm.mciSendStringW(f"close {alias}", buffer, len(buffer), None)
        self.alias_paths.pop(alias, None)

    def start_lie_detector_alert(self, volume_percent: object) -> None:
        if self._sink is not None:
            self.play_lie_detector_alert_blocking(volume_percent)
            return
        if self.alert_thread is not None and self.alert_thread.is_alive():
            return
        self._lie_detector_volume_percent = volume_percent
        alert_thread = self._adapters.thread_factory(
            target=self.play_lie_detector_alert_blocking,
            name="maple-star-lie-detector-alert",
            daemon=True,
        )
        self.alert_thread = alert_thread
        alert_thread.start()

    def play_lie_detector_alert_blocking(self, volume_percent: object | None = None) -> None:
        percent = self._lie_detector_volume_percent if volume_percent is None else volume_percent
        volume = self.mci_volume_from_percent(percent)
        if volume <= 0:
            return
        if not LIE_DETECTOR_ALERT_SOUND_PATH.exists():
            self.play_toggle_beep(LIE_DETECTOR_ALERT_BEEP_PATTERN)
            return
        self.play_media_with_volume(
            LIE_DETECTOR_ALERT_SOUND_PATH,
            "minimap_lie_detector_alert",
            volume,
            media_type="mpegvideo",
            on_failure=lambda: self.play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN),
        )

    @staticmethod
    def mci_volume_from_percent(percent: object) -> int:
        try:
            value = int(float(percent))
        except (TypeError, ValueError):
            value = 80
        value = max(0, min(100, value))
        return round(MCI_MAX_VOLUME * value / 100)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._sink is not None:
            self.alias_paths.clear()
            return
        if not self.alias_paths:
            return
        try:
            winmm = self._adapters.winmm_provider()
            buffer = ctypes.create_unicode_buffer(256)
            for alias in tuple(self.alias_paths):
                self.close_media_alias(winmm, buffer, alias)
        except Exception:
            self.alias_paths.clear()

    @staticmethod
    def _notify_failure(callback: Callable[[], None] | None) -> None:
        if callback is not None:
            callback()


__all__ = [
    "AUTO_DRINK_POTION_CHECK_SOUND_PATH",
    "AUTO_DRINK_START_SOUND_PATH",
    "AUTO_DRINK_STOP_SOUND_PATH",
    "AUTO_PICKUP_START_SOUND_PATH",
    "AUTO_PICKUP_STOP_SOUND_PATH",
    "LIE_DETECTOR_ALERT_SOUND_PATH",
    "MCI_MAX_VOLUME",
    "MCI_MEDIA_START_MS",
    "MCI_MEDIA_VOLUME",
    "MEDIA_SOUND_ALIASES",
    "MEDIA_SOUND_PATH_BY_ALIAS",
    "MEDIA_VOLUME_PERCENT",
    "MINIMAP_CRUISE_START_WAV_PATH",
    "MINIMAP_CRUISE_STOP_WAV_PATH",
    "MediaPlaybackService",
]
