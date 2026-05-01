from __future__ import annotations

import ctypes
import sys
import time
import winsound
from concurrent.futures import Future, ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

import mss
import numpy as np

from .constants import (
    ASYNC_KEY_DOWN_MASK,
    BAR_COLUMN_FILL_MIN_RATIO,
    BAR_CONFIRM_CAPTURE_ATTEMPTS,
    BAR_CONFIRM_FALLBACK_MAX_DELTA_PERCENT,
    BAR_CONFIRM_RETRY_DELAY_SECONDS,
    BAR_DYNAMIC_SEARCH_HEIGHT_RATIO,
    BAR_DYNAMIC_SEARCH_LEFT_RATIO,
    BAR_DYNAMIC_SEARCH_TOP_RATIO,
    BAR_DYNAMIC_SEARCH_WIDTH_RATIO,
    BAR_EMPTY_TAIL_MAX_CHROMA,
    BAR_EMPTY_TAIL_MAX_LUMINANCE,
    BAR_EMPTY_TAIL_MIN_RATIO,
    BAR_FULL_REGION_LEFT_PADDING_RATIO,
    BAR_FULL_REGION_RIGHT_PADDING_RATIO,
    BAR_FULL_REGION_VERTICAL_PADDING_RATIO,
    BAR_LEFT_EDGE_TOLERANCE_RATIO,
    BAR_MAX_INTERNAL_GAP_RATIO,
    BAR_MIN_BODY_ROW_COUNT,
    BAR_MIN_BODY_ROW_DENSITY,
    BAR_MIN_SEGMENT_DENSITY,
    BAR_PAIR_CACHE_SECONDS,
    BAR_SEARCH_MIN_RUN_PIXELS,
    BAR_STABLE_SAMPLE_HOLD_SECONDS,
    BAR_TAIL_CHECK_MIN_WIDTH_RATIO,
    BAR_TRANSIENT_CAPTURE_ATTEMPTS,
    BAR_TRANSIENT_RETRY_DELAY_SECONDS,
    BAR_UNSTABLE_LOG_INTERVAL_SECONDS,
    BAR_VERTICAL_BODY_ROW_DENSITY,
    DEFAULT_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
    FADE_GUARD_BRIGHT_PIXEL_RATIO,
    FADE_GUARD_MEAN_LUMINANCE,
    FADE_GUARD_RECOVERY_SECONDS,
    FADE_GUARD_REQUIRED_FRAMES,
    FULL_BAR_SNAP_PERCENT,
    GAME_CONTENT_ASPECT_RATIO,
    GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS,
    LOADING_GUARD_BRIGHT_PIXEL_RATIO,
    LOADING_GUARD_LOW_SATURATION_RATIO,
    LOADING_GUARD_MEAN_LUMINANCE,
    MOD_NOREPEAT,
    PM_REMOVE,
    EMERGENCY_STOP_BEEP_PATTERN,
    PAUSE_BEEP_PATTERN,
    RESUME_BEEP_PATTERN,
    SCRIPT_EMERGENCY_STOP_HOTKEY_ID,
    SCRIPT_EXPERIENCE_TOGGLE_HOTKEY_ID,
    SCRIPT_TOGGLE_HOTKEY_ID,
    SETTINGS_SAVE_DEBOUNCE_SECONDS,
    TOGGLE_HOTKEY_DEBOUNCE_SECONDS,
    WM_HOTKEY,
)
from .debug_logging import log_exception
from .experience import (
    ExperienceEfficiencyTracker,
    ExperienceTextReading,
    PaddleExperienceTextReader,
)
from .gui import AutoPotionSettingsGui, GuiConsoleWriter
from .settings import AutoPotionSettings, load_settings, save_settings
from .win_input import (
    Msg,
    Point,
    is_valid_window,
    is_window_minimized,
    parse_vk_key,
    tap_hotkey,
    temporarily_make_window_topmost,
    user32,
    window_client_size,
)

BAR_PREVIEW_IMAGE_SIZE = (240, 22)
BAR_PREVIEW_WINDOW_READY_TIMEOUT_SECONDS = 0.8
BAR_PREVIEW_WINDOW_POLL_SECONDS = 0.05
BAR_PREVIEW_RENDER_SETTLE_SECONDS = 0.18
EXPERIENCE_OCR_ERROR_LOG_INTERVAL_SECONDS = 10.0
EXPERIENCE_TEXT_LEFT_RATIO = 0.44
EXPERIENCE_TEXT_HEIGHT_RATIO = 1.35
BAR_PAIR_HP_MAX_LEFT_RATIO = 0.48
BAR_PAIR_MIN_GAP_RATIO = 0.10
BAR_PAIR_MAX_GAP_RATIO = 0.24


@dataclass
class BarDetectionDebug:
    bar_type: str
    source: str = "--"
    region: tuple[int, int, int, int] | None = None
    percent: float | None = None
    success: bool = False
    reason: str = "尚未偵測"
    require_clear_tail: bool = False
    tail_clear: bool | None = None


@dataclass
class ExperienceOcrJob:
    submitted_at: float
    future: Future[ExperienceTextReading]


@dataclass(frozen=True)
class HudSearchArea:
    left: int
    top: int
    width: int
    height: int
    reference_left: int
    reference_width: int
    reference_height: int


def normalize_bar_percent(percent: float) -> float:
    percent = max(0.0, min(100.0, percent))
    if percent >= FULL_BAR_SNAP_PERCENT:
        return 100.0
    return percent


def should_drink_for_threshold(percent: float, threshold_percent: float) -> bool:
    if threshold_percent >= 100.0 and percent >= 100.0:
        return False
    return percent <= threshold_percent


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


def bgra_image_to_ppm_data(
    image: np.ndarray,
    scale: int = 3,
    target_size: tuple[int, int] | None = None,
) -> bytes:
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("預覽圖片格式無效")
    scale = max(1, int(scale))
    rgb = image[:, :, :3][:, :, ::-1]
    if target_size is not None:
        target_width, target_height = target_size
        target_width = max(1, int(target_width))
        target_height = max(1, int(target_height))
        source_height, source_width, _channels = rgb.shape
        fit_scale = min(target_width / source_width, target_height / source_height)
        scaled_width = max(1, min(target_width, round(source_width * fit_scale)))
        scaled_height = max(1, min(target_height, round(source_height * fit_scale)))
        x_indexes = np.minimum(
            (np.arange(scaled_width) * source_width / scaled_width).astype(np.intp),
            source_width - 1,
        )
        y_indexes = np.minimum(
            (np.arange(scaled_height) * source_height / scaled_height).astype(np.intp),
            source_height - 1,
        )
        resized = rgb[y_indexes][:, x_indexes]
        canvas = np.full((target_height, target_width, 3), 240, dtype=np.uint8)
        left = (target_width - scaled_width) // 2
        top = (target_height - scaled_height) // 2
        canvas[top : top + scaled_height, left : left + scaled_width] = resized
        rgb = canvas
    elif scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    height, width, _channels = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + np.ascontiguousarray(rgb).tobytes()


class AutoPotionController:
    def __init__(
        self,
        is_target_window_active: Callable[[], bool],
        settings: AutoPotionSettings | None = None,
        target_window_provider: Callable[[], int] | None = None,
    ) -> None:
        self.is_target_window_active = is_target_window_active
        self.target_window_provider = target_window_provider
        self.settings = settings or load_settings()
        self.gui = AutoPotionSettingsGui(self.settings)
        self.gui.set_bar_preview_provider(self.capture_bar_preview_images)
        self.gui.set_experience_reset_handler(self.reset_experience_statistics)
        self.sct = mss.mss()
        self.next_capture_at = 0.0
        self.next_experience_capture_at = 0.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.last_error_at = -999.0
        self.last_unstable_bar_at = -999.0
        self.scripts_enabled = True
        self.hotkey_registered = False
        self.emergency_hotkey_registered = False
        self.experience_toggle_hotkey_registered = False
        self.toggle_hotkey_was_down = False
        self.emergency_stop_hotkey_was_down = False
        self.experience_toggle_hotkey_was_down = False
        self.registered_toggle_hotkey_vk = 0
        self.registered_emergency_stop_hotkey_vk = 0
        self.registered_experience_toggle_hotkey_vk = 0
        self.control_hotkeys_suppressed_until_release = False
        self.last_toggle_hotkey_at = -999.0
        self.last_experience_toggle_hotkey_at = -999.0
        self.emergency_stop_requested = False
        self.last_action = "啟動"
        self.last_bar_debug: dict[str, BarDetectionDebug] = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        self.bottom_bar_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_track_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_regions_at = -999.0
        self.bottom_bar_client_bounds: tuple[int, int, int, int] | None = None
        self.stable_bar_samples: dict[str, tuple[float, tuple[int, int, int, int], float]] = {}
        self.experience_tracker = ExperienceEfficiencyTracker()
        self.experience_reader = PaddleExperienceTextReader()
        self.experience_ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="maple-exp-ocr")
        self.experience_ocr_job: ExperienceOcrJob | None = None
        self.last_experience_ocr_error_at = -999.0
        self.last_experience_ocr_error_reason = ""
        self.last_target_hwnd: int = 0
        self.gameplay_hud_active = False
        self.fade_guard_hits = 0
        self.fade_guard_until = 0.0
        self.pending_settings_snapshot = self.settings.snapshot()
        self.next_settings_save_at: float | None = None
        self.original_stdout: object | None = None
        self.original_stderr: object | None = None
        self._sync_registered_control_hotkeys()

    def install_console_redirect(self) -> None:
        if isinstance(sys.stdout, GuiConsoleWriter):
            return
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = GuiConsoleWriter(self.gui, self.original_stdout)
        sys.stderr = GuiConsoleWriter(self.gui, self.original_stderr)

    def is_closed(self) -> bool:
        return not self.gui.exists()

    def can_run_actions(self) -> bool:
        return self.scripts_enabled and self.gameplay_hud_active

    def _control_hotkey_vk(self, hotkey: str, fallback: str) -> int:
        try:
            return parse_vk_key(hotkey)
        except ValueError:
            return parse_vk_key(fallback)

    def _sync_registered_control_hotkeys(self) -> None:
        toggle_vk = self._control_hotkey_vk(self.settings.toggle_hotkey, "F11")
        emergency_vk = self._control_hotkey_vk(self.settings.emergency_stop_hotkey, "Pause")
        experience_vk = self._control_hotkey_vk(self.settings.experience_toggle_hotkey, "F10")
        if (
            toggle_vk == self.registered_toggle_hotkey_vk
            and emergency_vk == self.registered_emergency_stop_hotkey_vk
            and experience_vk == self.registered_experience_toggle_hotkey_vk
        ):
            return
        self._unregister_toggle_hotkey()
        self._register_toggle_hotkey(toggle_vk, emergency_vk, experience_vk)

    def _register_toggle_hotkey(self, toggle_vk: int, emergency_vk: int, experience_vk: int) -> None:
        self.registered_toggle_hotkey_vk = toggle_vk
        if user32.RegisterHotKey(None, SCRIPT_TOGGLE_HOTKEY_ID, MOD_NOREPEAT, toggle_vk):
            self.hotkey_registered = True
        else:
            error_code = ctypes.get_last_error()
            print(f"註冊 {self.settings.toggle_hotkey} 總開關失敗，錯誤碼：{error_code}")

        self.registered_emergency_stop_hotkey_vk = emergency_vk
        if user32.RegisterHotKey(None, SCRIPT_EMERGENCY_STOP_HOTKEY_ID, MOD_NOREPEAT, emergency_vk):
            self.emergency_hotkey_registered = True
        else:
            error_code = ctypes.get_last_error()
            print(f"註冊 {self.settings.emergency_stop_hotkey} 硬停止失敗，錯誤碼：{error_code}")

        self.registered_experience_toggle_hotkey_vk = experience_vk
        if user32.RegisterHotKey(None, SCRIPT_EXPERIENCE_TOGGLE_HOTKEY_ID, MOD_NOREPEAT, experience_vk):
            self.experience_toggle_hotkey_registered = True
        else:
            error_code = ctypes.get_last_error()
            print(f"註冊 {self.settings.experience_toggle_hotkey} 經驗統計開關失敗，錯誤碼：{error_code}")

    def _unregister_toggle_hotkey(self) -> None:
        if self.hotkey_registered:
            if not user32.UnregisterHotKey(None, SCRIPT_TOGGLE_HOTKEY_ID):
                print(f"解除 {self.settings.toggle_hotkey} 總開關註冊失敗，錯誤碼：{ctypes.get_last_error()}")
            self.hotkey_registered = False
        self.registered_toggle_hotkey_vk = 0
        if self.emergency_hotkey_registered:
            if not user32.UnregisterHotKey(None, SCRIPT_EMERGENCY_STOP_HOTKEY_ID):
                print(f"解除 {self.settings.emergency_stop_hotkey} 硬停止註冊失敗，錯誤碼：{ctypes.get_last_error()}")
            self.emergency_hotkey_registered = False
        self.registered_emergency_stop_hotkey_vk = 0
        if self.experience_toggle_hotkey_registered:
            if not user32.UnregisterHotKey(None, SCRIPT_EXPERIENCE_TOGGLE_HOTKEY_ID):
                print(f"解除 {self.settings.experience_toggle_hotkey} 經驗統計開關註冊失敗，錯誤碼：{ctypes.get_last_error()}")
            self.experience_toggle_hotkey_registered = False
        self.registered_experience_toggle_hotkey_vk = 0

    def poll_control_hotkeys(self) -> None:
        if self.gui.is_detecting_key():
            self.toggle_hotkey_was_down = False
            self.emergency_stop_hotkey_was_down = False
            self.experience_toggle_hotkey_was_down = False
            self.control_hotkeys_suppressed_until_release = False
            self._discard_control_hotkey_messages()
            return
        if self.gui.consume_key_detection_finished():
            self.control_hotkeys_suppressed_until_release = True
            self._discard_control_hotkey_messages()
            self._sync_control_hotkey_down_states()
            return
        if self.control_hotkeys_suppressed_until_release:
            self._discard_control_hotkey_messages()
            self._sync_control_hotkey_down_states()
            if not self._any_control_hotkey_is_down():
                self.control_hotkeys_suppressed_until_release = False
            return

        toggle_triggered = False
        emergency_stop_triggered = False
        experience_toggle_triggered = False
        message = Msg()
        while user32.PeekMessageW(
            ctypes.byref(message),
            None,
            WM_HOTKEY,
            WM_HOTKEY,
            PM_REMOVE,
        ):
            if message.wParam == SCRIPT_TOGGLE_HOTKEY_ID:
                toggle_triggered = True
            elif message.wParam == SCRIPT_EMERGENCY_STOP_HOTKEY_ID:
                emergency_stop_triggered = True
            elif message.wParam == SCRIPT_EXPERIENCE_TOGGLE_HOTKEY_ID:
                experience_toggle_triggered = True

        toggle_is_down = bool(
            self.registered_toggle_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_toggle_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        if toggle_is_down and not self.toggle_hotkey_was_down:
            toggle_triggered = True
        self.toggle_hotkey_was_down = toggle_is_down

        emergency_is_down = bool(
            self.registered_emergency_stop_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_emergency_stop_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        if emergency_is_down and not self.emergency_stop_hotkey_was_down:
            emergency_stop_triggered = True
        self.emergency_stop_hotkey_was_down = emergency_is_down

        experience_is_down = bool(
            self.registered_experience_toggle_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_experience_toggle_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        if experience_is_down and not self.experience_toggle_hotkey_was_down:
            experience_toggle_triggered = True
        self.experience_toggle_hotkey_was_down = experience_is_down

        if emergency_stop_triggered:
            self.emergency_stop()
        elif toggle_triggered:
            self._try_toggle_scripts_enabled(time.monotonic())
        elif experience_toggle_triggered:
            self._try_toggle_experience_efficiency(time.monotonic())

    def is_key_capture_blocking_actions(self) -> bool:
        return self.gui.is_detecting_key() or self.gui.is_key_detection_release_pending()

    def _sync_control_hotkey_down_states(self) -> None:
        self.toggle_hotkey_was_down = bool(
            self.registered_toggle_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_toggle_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        self.emergency_stop_hotkey_was_down = bool(
            self.registered_emergency_stop_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_emergency_stop_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        self.experience_toggle_hotkey_was_down = bool(
            self.registered_experience_toggle_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_experience_toggle_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )

    def _any_control_hotkey_is_down(self) -> bool:
        return (
            self.toggle_hotkey_was_down
            or self.emergency_stop_hotkey_was_down
            or self.experience_toggle_hotkey_was_down
        )

    def _discard_control_hotkey_messages(self) -> None:
        message = Msg()
        while user32.PeekMessageW(
            ctypes.byref(message),
            None,
            WM_HOTKEY,
            WM_HOTKEY,
            PM_REMOVE,
        ):
            pass

    def consume_emergency_stop_requested(self) -> bool:
        if not self.emergency_stop_requested:
            return False
        self.emergency_stop_requested = False
        return True

    def _try_toggle_scripts_enabled(self, now: float) -> None:
        if now - self.last_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_toggle_hotkey_at = now
        self.toggle_scripts_enabled()

    def _try_toggle_experience_efficiency(self, now: float) -> None:
        if now - self.last_experience_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_toggle_hotkey_at = now
        self.toggle_experience_efficiency()

    def toggle_scripts_enabled(self) -> None:
        self.scripts_enabled = not self.scripts_enabled
        if self.scripts_enabled:
            self._play_toggle_beep(RESUME_BEEP_PATTERN)
            self.gui.set_status("腳本已啟用")
            self.gui.show_toggle_notice("腳本已啟用")
            self.last_action = f"{self.settings.toggle_hotkey} 啟用"
            print(f"{self.settings.toggle_hotkey}：腳本已啟用")
            return

        self.last_hp_drink_at = time.monotonic()
        self.last_mp_drink_at = self.last_hp_drink_at
        self._play_toggle_beep(PAUSE_BEEP_PATTERN)
        self.gui.set_status(f"腳本已暫停，按 {self.settings.toggle_hotkey} 恢復")
        self.gui.show_toggle_notice("腳本已暫停")
        self.gui.set_current_percentages(None, None)
        self.last_action = f"{self.settings.toggle_hotkey} 暫停"
        print(f"{self.settings.toggle_hotkey}：腳本已暫停")

    def toggle_experience_efficiency(self) -> None:
        enabled = not self.settings.exp_efficiency_enabled
        self.gui.set_exp_efficiency_enabled(enabled)
        if enabled:
            now = time.monotonic()
            self._stop_experience_ocr_job()
            self.next_experience_capture_at = 0.0
            self.experience_tracker.clear_transient_rejection()
            snapshot = self.experience_tracker.snapshot(now)
            snapshot.status = "等待下一次 EXP 樣本" if snapshot.sample_count else "等待有效 EXP 樣本"
            self.gui.set_experience_snapshot(snapshot)
            self._play_toggle_beep(RESUME_BEEP_PATTERN)
            self.gui.set_status("經驗統計已啟用")
            self.gui.show_toggle_notice("經驗統計已啟用")
            self.last_action = f"{self.settings.experience_toggle_hotkey} 經驗統計啟用"
            print(f"{self.settings.experience_toggle_hotkey}：經驗統計已啟用")
            return

        self._stop_experience_ocr_job()
        snapshot = self.experience_tracker.snapshot(time.monotonic())
        snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
        self.gui.set_experience_snapshot(snapshot)
        self._play_toggle_beep(PAUSE_BEEP_PATTERN)
        self.gui.set_status("經驗統計已停用")
        self.gui.show_toggle_notice("經驗統計已停用")
        self.last_action = f"{self.settings.experience_toggle_hotkey} 經驗統計停用"
        print(f"{self.settings.experience_toggle_hotkey}：經驗統計已停用")

    def emergency_stop(self) -> None:
        now = time.monotonic()
        self.scripts_enabled = False
        self.emergency_stop_requested = True
        self.last_hp_drink_at = now
        self.last_mp_drink_at = now
        self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
        self.gui.set_status(f"{self.settings.emergency_stop_hotkey} 硬停止：所有腳本已暫停")
        self.gui.show_toggle_notice(f"{self.settings.emergency_stop_hotkey} 硬停止")
        self.gui.set_current_percentages(None, None)
        self.last_action = f"{self.settings.emergency_stop_hotkey} 硬停止"
        print(f"{self.settings.emergency_stop_hotkey}：硬停止，所有腳本已暫停")

    def _play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None:
        try:
            for frequency, duration_ms in pattern:
                winsound.Beep(frequency, duration_ms)
        except RuntimeError:
            try:
                winsound.MessageBeep()
            except RuntimeError:
                pass

    def update(self, now: float, *, pump_gui: bool = True) -> None:
        self.poll_control_hotkeys()
        gui_ready = self.gui.pump() if pump_gui else self.gui.sync_after_event_processing()
        if not gui_ready:
            if not self.gui.closed:
                self._set_gameplay_hud_active(False, now)
                if not self.gui.is_window_interaction_active():
                    self.gui.set_current_percentages(None, None)
            return
        self._sync_registered_control_hotkeys()
        self.poll_control_hotkeys()
        self._save_settings_when_idle(now)

        if self.is_key_capture_blocking_actions():
            self._set_gameplay_hud_active(False, now)
            self.gui.set_current_percentages(None, None)
            return

        if now < self.next_capture_at:
            return
        self.next_capture_at = now + DEFAULT_CAPTURE_INTERVAL_SECONDS

        if not self.scripts_enabled:
            self._set_gameplay_hud_active(False, now)
            self.gui.set_status(f"腳本已暫停，按 {self.settings.toggle_hotkey} 恢復")
            self.gui.set_current_percentages(None, None)
            return

        if not self.is_target_window_active():
            self._set_gameplay_hud_active(False, now)
            self.gui.set_status("等待楓星成為前景視窗")
            self.gui.set_current_percentages(None, None)
            return

        try:
            transition_pause_reason = self._transition_pause_reason(now)
            if transition_pause_reason:
                self._set_gameplay_hud_active(False, now)
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status(transition_pause_reason)
                self.gui.set_current_percentages(None, None)
                return

            if not self._refresh_gameplay_hud_state(now):
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status("未偵測到遊戲 HUD，暫停輔助功能")
                self.gui.set_current_percentages(None, None)
                self.gui.set_bar_detection_debug(
                    self._bar_detection_debug_text("hp"),
                    self._bar_detection_debug_text("mp"),
                )
                return

            hp_percent = self._capture_bar_percent("hp")
            mp_percent = self._capture_bar_percent("mp")
            self.gui.set_current_percentages(hp_percent, mp_percent)
            self.gui.set_bar_detection_debug(
                self._bar_detection_debug_text("hp"),
                self._bar_detection_debug_text("mp"),
            )
            if hp_percent is None or mp_percent is None:
                self.gui.set_status("HP/MP 條偵測不穩定，略過錯誤取樣")
            else:
                self.gui.set_status("自動喝水監控中")
                self.gui.refresh_bar_preview_once()
            if self.settings.exp_efficiency_enabled:
                self._update_experience_efficiency(now)
            else:
                self._stop_experience_ocr_job()
                snapshot = self.experience_tracker.snapshot(now)
                snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
                self.gui.set_experience_snapshot(snapshot)
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

    def reset_experience_statistics(self) -> None:
        self._stop_experience_ocr_job()
        self.experience_tracker.reset()
        self.next_experience_capture_at = 0.0

    def _set_gameplay_hud_active(self, active: bool, now: float) -> None:
        self.gameplay_hud_active = active
        if active:
            return
        self.last_hp_drink_at = now
        self.last_mp_drink_at = now

    def _refresh_gameplay_hud_state(self, now: float) -> bool:
        previous_regions = dict(getattr(self, "bottom_bar_regions", {}))
        previous_track_regions = dict(getattr(self, "bottom_bar_track_regions", {}))
        previous_client_bounds = getattr(self, "bottom_bar_client_bounds", None)
        regions = self._find_bottom_bar_pair_regions(
            use_cache=False,
            allow_stale_on_failure=False,
        )
        active = "hp" in regions and "mp" in regions
        if active:
            self._set_gameplay_hud_active(True, now)
            return True
        if self._can_reuse_stale_bottom_bar_regions(
            previous_regions,
            previous_track_regions,
            previous_client_bounds,
        ):
            self.bottom_bar_regions = previous_regions
            self.bottom_bar_track_regions = previous_track_regions
            self.bottom_bar_client_bounds = previous_client_bounds
            self.bottom_bar_regions_at = time.monotonic()
            self._set_gameplay_hud_active(True, now)
            return True
        self._set_gameplay_hud_active(False, now)
        for bar_type in ("hp", "mp"):
            self._set_bar_detection_debug(
                bar_type,
                source="HUD gate",
                region=None,
                percent=None,
                success=False,
                reason="找不到包含 HP/MP 條的遊戲 HUD",
                require_clear_tail=False,
                tail_clear=None,
            )
        return False

    def _can_reuse_stale_bottom_bar_regions(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        if "hp" not in regions or "mp" not in regions:
            return False
        if client_bounds is None or client_bounds != self._foreground_client_bounds():
            return False

        for bar_type in ("mp", "hp"):
            try:
                percent, _reason, _tail_clear = self._bar_percent_from_region_snapshot(
                    regions[bar_type],
                    bar_type,
                    require_clear_tail=False,
                    track_region=track_regions.get(bar_type),
                )
            except Exception:
                continue
            if percent is not None:
                return True
        return False

    def _pause_experience_for_missing_hud(self, now: float) -> None:
        if not self.settings.exp_efficiency_enabled:
            return
        self._stop_experience_ocr_job()
        snapshot = self.experience_tracker.snapshot(now)
        snapshot.status = "HUD 未出現，保留統計"
        self.gui.set_experience_snapshot(snapshot)

    def _update_experience_efficiency(self, now: float) -> None:
        if self._process_experience_ocr_job(now):
            return

        if now < self.next_experience_capture_at:
            self.gui.set_experience_snapshot(self.experience_tracker.snapshot(now))
            return

        region = self._experience_text_region()
        if region is None:
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(now)
            snapshot.status = "找不到 EXP 區域，保留統計" if snapshot.sample_count else "找不到 EXP 區域"
            self.gui.set_experience_snapshot(snapshot)
            return

        left, top, width, height = region
        image = np.asarray(self.sct.grab({"left": left, "top": top, "width": width, "height": height}))
        self.experience_ocr_job = ExperienceOcrJob(
            submitted_at=now,
            future=self.experience_ocr_executor.submit(self.experience_reader.read, image.copy()),
        )
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        snapshot = self.experience_tracker.snapshot(now)
        snapshot.status = "讀取經驗樣本中"
        self.gui.set_experience_snapshot(snapshot)

    def _process_experience_ocr_job(self, now: float) -> bool:
        if self.experience_ocr_job is None:
            return False
        job = self.experience_ocr_job
        if not job.future.done():
            snapshot = self.experience_tracker.snapshot(now)
            snapshot.status = "讀取經驗樣本中"
            self.gui.set_experience_snapshot(snapshot)
            return True

        self.experience_ocr_job = None
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        try:
            reading = job.future.result()
        except Exception as exc:
            log_exception("OCR 背景工作失敗")
            reading = ExperienceTextReading(reason=f"OCR 背景工作失敗：{exc}")

        self._log_experience_ocr_reading(reading)
        if reading.success and reading.current_exp is not None:
            if not self.experience_tracker.add_reading(now, reading.current_exp, reading.percent):
                self.experience_tracker.record_ocr_result(False)
                self._log_experience_sample_rejection(now, self.experience_tracker.last_status, reading)
                snapshot = self.experience_tracker.snapshot(now)
                snapshot.status = "樣本已拒絕，詳見 Console"
                self.gui.set_experience_snapshot(snapshot)
                return True
            self.experience_tracker.record_ocr_result(True)
            self.gui.set_experience_snapshot(self.experience_tracker.snapshot(now))
            return True

        self.experience_tracker.record_ocr_result(False)
        self._log_experience_ocr_error(now, reading.reason, reading.text)
        snapshot = self.experience_tracker.snapshot(now)
        if snapshot.sample_count == 0:
            snapshot.status = "等待有效 EXP 樣本"
        self.gui.set_experience_snapshot(snapshot)
        return True

    def _stop_experience_ocr_job(self) -> None:
        if self.experience_ocr_job is None:
            return
        self.experience_ocr_job.future.cancel()
        self.experience_ocr_job = None

    def _log_experience_ocr_error(self, now: float, reason: str, text: str = "") -> None:
        log_reason = f"{reason}，OCR={text!r}" if text else reason
        if (
            log_reason == self.last_experience_ocr_error_reason
            and now - self.last_experience_ocr_error_at < EXPERIENCE_OCR_ERROR_LOG_INTERVAL_SECONDS
        ):
            return
        print(f"經驗效率 OCR 錯誤：{log_reason}")
        self.last_experience_ocr_error_reason = log_reason
        self.last_experience_ocr_error_at = now

    def _log_experience_ocr_reading(self, reading: ExperienceTextReading) -> None:
        if reading.success:
            return
        result = "成功" if reading.success else "失敗"
        print(
            "經驗效率 OCR 輸出："
            f"result={result} | {self._experience_reading_log_fields(reading)} | reason={reading.reason}"
        )

    def _log_experience_sample_rejection(
        self,
        now: float,
        reason: str,
        reading: ExperienceTextReading | None = None,
    ) -> None:
        detail = f"{reason} | {self._experience_reading_log_fields(reading)}" if reading is not None else reason
        if (
            detail == self.last_experience_ocr_error_reason
            and now - self.last_experience_ocr_error_at < EXPERIENCE_OCR_ERROR_LOG_INTERVAL_SECONDS
        ):
            return
        print(f"經驗效率 異常樣本拒絕：{detail}")
        self.last_experience_ocr_error_reason = detail
        self.last_experience_ocr_error_at = now

    def _experience_reading_log_fields(self, reading: ExperienceTextReading) -> str:
        text = reading.text if reading.text else "--"
        percent = "--" if reading.percent is None else f"{reading.percent:.2f}%"
        current_exp = "--" if reading.current_exp is None else f"{reading.current_exp:,}"
        return (
            f"text={text!r} | confidence={reading.confidence:.2f} | "
            f"exp={current_exp} | percent={percent}"
        )

    def _experience_text_region(self) -> tuple[int, int, int, int] | None:
        hp_region = self.bottom_bar_regions.get("hp")
        mp_region = self.bottom_bar_regions.get("mp")
        if hp_region is None or mp_region is None:
            return None

        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        client_right = client_left + client_width
        client_bottom = client_top + client_height
        left = min(hp_region[0], mp_region[0])
        right = max(hp_region[0] + hp_region[2], mp_region[0] + mp_region[2])
        top = max(hp_region[1] + hp_region[3], mp_region[1] + mp_region[3])
        base_width = max(1, right - left)
        bar_height = max(hp_region[3], mp_region[3])
        region_top = max(client_top, top)
        region_bottom = min(client_bottom, top + max(14, round(bar_height * EXPERIENCE_TEXT_HEIGHT_RATIO)))
        region_left = max(client_left, left + round(base_width * EXPERIENCE_TEXT_LEFT_RATIO))
        region_right = min(client_right, right)
        if region_right - region_left < 20 or region_bottom - region_top < 8:
            return None
        return (
            region_left,
            region_top,
            region_right - region_left,
            region_bottom - region_top,
        )

    def _maybe_drink_hp(self, now: float, hp_percent: float | None) -> None:
        if not self.settings.hp_enabled:
            return
        if hp_percent is None:
            hp_percent = self._capture_transient_bar_percent("hp")
            if hp_percent is None:
                self._log_unstable_bar(now, "HP")
                return
        if not should_drink_for_threshold(hp_percent, self.settings.hp_threshold_percent):
            return
        if now - self.last_hp_drink_at < self.settings.hp_cooldown_seconds:
            return
        if not self._is_target_window_active_before_send("HP", now):
            return

        hp_percent = self._capture_confirmed_bar_percent("hp", hp_percent)
        if hp_percent is None:
            self._log_unstable_bar(now, "HP")
            return
        if not should_drink_for_threshold(hp_percent, self.settings.hp_threshold_percent):
            return
        if not self._is_target_window_active_before_send("HP", now):
            return

        tap_hotkey(self.settings.hp_key)
        self.last_hp_drink_at = now
        self.last_action = f"HP 喝水：{self.settings.hp_key}"
        print(f"HP {hp_percent:.0f}% <= {self.settings.hp_threshold_percent:.0f}%，按 {self.settings.hp_key}")

    def _maybe_drink_mp(self, now: float, mp_percent: float | None) -> None:
        if not self.settings.mp_enabled:
            return
        if mp_percent is None:
            mp_percent = self._capture_transient_bar_percent("mp")
            if mp_percent is None:
                self._log_unstable_bar(now, "MP")
                return
        if not should_drink_for_threshold(mp_percent, self.settings.mp_threshold_percent):
            return
        if now - self.last_mp_drink_at < self.settings.mp_cooldown_seconds:
            return
        if not self._is_target_window_active_before_send("MP", now):
            return

        mp_percent = self._capture_confirmed_bar_percent("mp", mp_percent)
        if mp_percent is None:
            self._log_unstable_bar(now, "MP")
            return
        if not should_drink_for_threshold(mp_percent, self.settings.mp_threshold_percent):
            return
        if not self._is_target_window_active_before_send("MP", now):
            return

        tap_hotkey(self.settings.mp_key)
        self.last_mp_drink_at = now
        self.last_action = f"MP 喝水：{self.settings.mp_key}"
        print(f"MP {mp_percent:.0f}% <= {self.settings.mp_threshold_percent:.0f}%，按 {self.settings.mp_key}")

    def _is_target_window_active_before_send(self, label: str, now: float | None = None) -> bool:
        if self.is_target_window_active():
            check_at = time.monotonic() if now is None else now
            if self._refresh_gameplay_hud_state(check_at):
                return True
            self.gui.set_status("未偵測到遊戲 HUD，暫停輔助功能")
            self.gui.set_current_percentages(None, None)
            print(f"{label} 自動喝水略過：未偵測到遊戲 HUD")
            return False
        self.gui.set_status("等待楓星成為前景視窗")
        self.gui.set_current_percentages(None, None)
        print(f"{label} 自動喝水略過：楓星不在前景")
        return False

    def _log_unstable_bar(self, now: float, label: str) -> None:
        if now - self.last_unstable_bar_at < BAR_UNSTABLE_LOG_INTERVAL_SECONDS:
            return
        self.last_unstable_bar_at = now
        print(f"{label} 條偵測不穩定，略過自動喝水")

    def _capture_transient_bar_percent(self, bar_type: str) -> float | None:
        attempts = max(1, BAR_TRANSIENT_CAPTURE_ATTEMPTS)
        for attempt in range(attempts):
            percent = self._capture_bar_percent(bar_type)
            if percent is not None:
                return percent
            if attempt + 1 < attempts:
                time.sleep(BAR_TRANSIENT_RETRY_DELAY_SECONDS)
        return None

    def _capture_confirmed_bar_percent(self, bar_type: str, fallback_percent: float | None = None) -> float | None:
        attempts = max(1, BAR_CONFIRM_CAPTURE_ATTEMPTS)
        for attempt in range(attempts):
            percent = self._capture_bar_percent(bar_type, require_clear_tail=True)
            if percent is not None:
                return percent
            if attempt + 1 < attempts:
                time.sleep(BAR_CONFIRM_RETRY_DELAY_SECONDS)

        if fallback_percent is None:
            return None
        unchecked_percent = self._capture_bar_percent(bar_type, require_clear_tail=False)
        if unchecked_percent is None:
            return None
        if abs(unchecked_percent - fallback_percent) > BAR_CONFIRM_FALLBACK_MAX_DELTA_PERCENT:
            return None
        return unchecked_percent

    def _capture_bar_percent(
        self,
        bar_type: str,
        require_clear_tail: bool = False,
    ) -> float | None:
        region = self._find_bottom_bar_pair_regions().get(bar_type)
        if region is None:
            self._set_bar_detection_debug(
                bar_type,
                source="自動定位",
                region=None,
                percent=None,
                success=False,
                reason="找不到 HP/MP 成對 HUD 條",
                require_clear_tail=require_clear_tail,
                tail_clear=None,
            )
            return None

        track_region = getattr(self, "bottom_bar_track_regions", {}).get(bar_type)
        return self._capture_bar_percent_from_region(
            region,
            bar_type,
            require_clear_tail,
            "自動定位",
            track_region=track_region,
        )

    def _find_bottom_bar_pair_regions(
        self,
        *,
        use_cache: bool = True,
        allow_stale_on_failure: bool = True,
    ) -> dict[str, tuple[int, int, int, int]]:
        now = time.monotonic()
        client_bounds = self._foreground_client_bounds()
        cached_client_bounds = getattr(self, "bottom_bar_client_bounds", None)
        if (
            use_cache
            and cached_client_bounds == client_bounds
            and now - self.bottom_bar_regions_at <= BAR_PAIR_CACHE_SECONDS
        ):
            return self.bottom_bar_regions

        old_regions = dict(getattr(self, "bottom_bar_regions", {}))
        old_track_regions = dict(getattr(self, "bottom_bar_track_regions", {}))
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = now

        regions: dict[str, tuple[int, int, int, int]] = {}
        for search_area in self._bottom_bar_search_areas(client_bounds):
            image = np.asarray(
                self.sct.grab(
                    {
                        "left": search_area.left,
                        "top": search_area.top,
                        "width": search_area.width,
                        "height": search_area.height,
                    }
                )
            )
            hp_mask = self._bar_color_mask(image, "hp")
            mp_mask = self._bar_color_mask(image, "mp")
            hp_candidates = self._bar_run_candidates(hp_mask, search_area.reference_width)
            mp_candidates = self._bar_run_candidates(mp_mask, search_area.reference_width)

            regions = self._bottom_bar_pair_regions_from_candidates(
                hp_candidates,
                mp_candidates,
                hp_mask=hp_mask,
                mp_mask=mp_mask,
                search_left=search_area.left,
                search_top=search_area.top,
                search_width=search_area.width,
                search_height=search_area.height,
                client_width=search_area.reference_width,
                client_height=search_area.reference_height,
                reference_left=search_area.reference_left,
            )
            if regions:
                break

        if regions:
            self.bottom_bar_regions = regions
            self.bottom_bar_track_regions = getattr(self, "pending_bottom_bar_track_regions", {})
        elif allow_stale_on_failure and cached_client_bounds == client_bounds and old_regions:
            self.bottom_bar_regions = old_regions
            self.bottom_bar_track_regions = old_track_regions
        else:
            self.bottom_bar_regions = {}
            self.bottom_bar_track_regions = {}
        return self.bottom_bar_regions

    def _bottom_bar_search_areas(self, client_bounds: tuple[int, int, int, int]) -> list[HudSearchArea]:
        areas: list[HudSearchArea] = []
        client_left, client_top, client_width, client_height = client_bounds
        gameplay_left, gameplay_top, gameplay_width, gameplay_height = self._gameplay_content_bounds(client_bounds)
        if (gameplay_left, gameplay_top, gameplay_width, gameplay_height) != client_bounds:
            areas.append(self._bottom_bar_search_area_from_content_bounds(
                gameplay_left,
                gameplay_top,
                gameplay_width,
                gameplay_height,
            ))
        areas.append(self._bottom_bar_search_area_from_content_bounds(
            client_left,
            client_top,
            client_width,
            client_height,
        ))

        unique: list[HudSearchArea] = []
        seen: set[tuple[int, int, int, int]] = set()
        for area in areas:
            key = (area.left, area.top, area.width, area.height)
            if key in seen:
                continue
            seen.add(key)
            unique.append(area)
        return unique

    def _bottom_bar_search_area_from_content_bounds(
        self,
        content_left: int,
        content_top: int,
        content_width: int,
        content_height: int,
    ) -> HudSearchArea:
        search_left = content_left + round(content_width * BAR_DYNAMIC_SEARCH_LEFT_RATIO)
        search_top = content_top + round(content_height * BAR_DYNAMIC_SEARCH_TOP_RATIO)
        search_width = max(1, round(content_width * BAR_DYNAMIC_SEARCH_WIDTH_RATIO))
        search_height = max(1, round(content_height * BAR_DYNAMIC_SEARCH_HEIGHT_RATIO))
        return HudSearchArea(
            left=search_left,
            top=search_top,
            width=search_width,
            height=search_height,
            reference_left=content_left,
            reference_width=content_width,
            reference_height=content_height,
        )

    def _gameplay_content_bounds(self, client_bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        client_left, client_top, client_width, client_height = client_bounds
        if client_width <= 0 or client_height <= 0:
            return client_bounds

        fit_width = min(client_width, round(client_height * GAME_CONTENT_ASPECT_RATIO))
        fit_height = min(client_height, round(client_width / GAME_CONTENT_ASPECT_RATIO))
        horizontal_margin = max(0, (client_width - fit_width) // 2)
        vertical_margin = max(0, (client_height - fit_height) // 2)
        if (
            horizontal_margin < GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS
            and vertical_margin < GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS
        ):
            return client_bounds
        return (
            client_left + horizontal_margin,
            client_top + vertical_margin,
            max(1, fit_width),
            max(1, fit_height),
        )

    def _bottom_bar_pair_regions_from_candidates(
        self,
        hp_candidates: list[tuple[int, int, int]],
        mp_candidates: list[tuple[int, int, int]],
        *,
        hp_mask: np.ndarray | None = None,
        mp_mask: np.ndarray | None = None,
        search_left: int,
        search_top: int,
        search_width: int,
        search_height: int,
        client_width: int,
        client_height: int,
        reference_left: int = 0,
    ) -> dict[str, tuple[int, int, int, int]]:
        best_pair: tuple[tuple[int, int, int], tuple[int, int, int], float] | None = None
        max_y_delta = max(4, round(client_height * 0.018))
        min_gap = max(24, round(client_width * BAR_PAIR_MIN_GAP_RATIO))
        max_gap = max(min_gap + 1, round(client_width * BAR_PAIR_MAX_GAP_RATIO))
        max_hp_left = max(1, round(client_width * BAR_PAIR_HP_MAX_LEFT_RATIO))

        for hp_start, hp_row, hp_length in hp_candidates:
            hp_left_in_reference = search_left - reference_left + hp_start
            if hp_left_in_reference > max_hp_left:
                continue
            for mp_start, mp_row, mp_length in mp_candidates:
                if mp_start <= hp_start:
                    continue
                y_delta = abs(mp_row - hp_row)
                if y_delta > max_y_delta:
                    continue
                gap = mp_start - hp_start
                if gap < min_gap or gap > max_gap:
                    continue
                average_row = (hp_row + mp_row) / 2
                score = hp_length + mp_length + average_row * 0.5 - y_delta * 8
                if best_pair is None or score > best_pair[2]:
                    best_pair = ((hp_start, hp_row, hp_length), (mp_start, mp_row, mp_length), score)

        if best_pair is None:
            return {}

        hp_start, hp_row, _hp_length = best_pair[0]
        mp_start, mp_row, _mp_length = best_pair[1]
        gap = mp_start - hp_start
        min_width = max(48, round(client_width * 0.07))
        max_width = max(min_width + 1, round(client_width * 0.20))
        region_width = max(min_width, min(max_width, round(gap * 0.82)))
        margin_left = max(2, round(region_width * 0.015))
        fallback_height = max(10, min(22, round(client_height * 0.015)))
        hp_top, hp_height = self._bar_vertical_bounds(
            hp_mask,
            hp_start,
            best_pair[0][2],
            hp_row,
            search_height,
            fallback_height,
        )
        mp_top, mp_height = self._bar_vertical_bounds(
            mp_mask,
            mp_start,
            best_pair[1][2],
            mp_row,
            search_height,
            fallback_height,
        )
        hp_left = max(0, min(search_width - region_width, hp_start - margin_left))
        mp_left = max(0, min(search_width - region_width, mp_start - margin_left))
        hp_region, hp_track_region = self._full_bar_region_and_track(
            search_left,
            search_top,
            search_width,
            search_height,
            hp_left,
            hp_top,
            region_width,
            hp_height,
        )
        mp_region, mp_track_region = self._full_bar_region_and_track(
            search_left,
            search_top,
            search_width,
            search_height,
            mp_left,
            mp_top,
            region_width,
            mp_height,
        )
        self.pending_bottom_bar_track_regions = {
            "hp": hp_track_region,
            "mp": mp_track_region,
        }
        self.bottom_bar_track_regions = dict(self.pending_bottom_bar_track_regions)
        return {
            "hp": hp_region,
            "mp": mp_region,
        }

    def _full_bar_region_and_track(
        self,
        search_left: int,
        search_top: int,
        search_width: int,
        search_height: int,
        track_left: int,
        track_top: int,
        track_width: int,
        track_height: int,
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        left_padding = max(2, round(track_width * BAR_FULL_REGION_LEFT_PADDING_RATIO))
        right_padding = max(6, round(track_width * BAR_FULL_REGION_RIGHT_PADDING_RATIO))
        vertical_padding = max(2, round(track_height * BAR_FULL_REGION_VERTICAL_PADDING_RATIO))

        full_left = max(0, track_left - left_padding)
        full_top = max(0, track_top - vertical_padding)
        full_right = min(search_width, track_left + track_width + right_padding)
        full_bottom = min(search_height, track_top + track_height + vertical_padding)
        return (
            (
                search_left + full_left,
                search_top + full_top,
                max(1, full_right - full_left),
                max(1, full_bottom - full_top),
            ),
            (
                search_left + track_left,
                search_top + track_top,
                track_width,
                track_height,
            ),
        )

    def _bar_vertical_bounds(
        self,
        mask: np.ndarray | None,
        run_start: int,
        run_length: int,
        row_index: int,
        search_height: int,
        fallback_height: int,
    ) -> tuple[int, int]:
        if mask is None or mask.size == 0:
            top = max(0, min(search_height - fallback_height, row_index - fallback_height // 2))
            return top, fallback_height

        sample_width = max(8, min(run_length, round(mask.shape[1] * 0.18)))
        sample_start = max(0, min(mask.shape[1] - sample_width, run_start))
        sample = mask[:, sample_start : sample_start + sample_width]
        row_filled = sample.mean(axis=1) >= BAR_VERTICAL_BODY_ROW_DENSITY
        if not bool(row_filled[row_index]):
            top = max(0, min(search_height - fallback_height, row_index - fallback_height // 2))
            return top, fallback_height

        top = row_index
        while top > 0 and row_filled[top - 1]:
            top -= 1
        bottom = row_index
        while bottom + 1 < row_filled.size and row_filled[bottom + 1]:
            bottom += 1

        padding = 1
        top = max(0, top - padding)
        bottom = min(search_height - 1, bottom + padding)
        height = max(8, bottom - top + 1)
        max_height = max(fallback_height + 4, round(search_height * 0.18))
        if height > max_height:
            top = max(0, min(search_height - fallback_height, row_index - fallback_height // 2))
            return top, fallback_height
        return top, height

    def _capture_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        require_clear_tail: bool = False,
        source: str = "指定區域",
        *,
        track_region: tuple[int, int, int, int] | None = None,
    ) -> float | None:
        percent, reason, tail_clear = self._bar_percent_from_region_snapshot(
            region,
            bar_type,
            require_clear_tail=require_clear_tail,
            track_region=track_region,
        )
        if percent is not None:
            self._remember_stable_bar_sample(bar_type, percent, region)
        elif not require_clear_tail:
            stable_percent = self._recent_stable_bar_percent(bar_type, region)
            if stable_percent is not None:
                percent = stable_percent
                reason = "短暫失敗，沿用最近穩定取樣"
        self._set_bar_detection_debug(
            bar_type,
            source=source,
            region=region,
            percent=percent,
            success=percent is not None,
            reason=reason,
            require_clear_tail=require_clear_tail,
            tail_clear=tail_clear,
        )
        return percent

    def _bar_percent_from_region_snapshot(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        *,
        require_clear_tail: bool = False,
        track_region: tuple[int, int, int, int] | None = None,
    ) -> tuple[float | None, str, bool | None]:
        left, top, width, height = region
        image = np.asarray(self.sct.grab({"left": left, "top": top, "width": width, "height": height}))
        mask = self._bar_color_mask(image, bar_type)
        percent_mask, percent_image = self._bar_percent_inputs(region, mask, image, track_region)
        return self._percent_from_bar_mask_result(
            percent_mask,
            percent_image,
            require_clear_tail,
        )

    def _bar_percent_inputs(
        self,
        region: tuple[int, int, int, int],
        mask: np.ndarray,
        image: np.ndarray,
        track_region: tuple[int, int, int, int] | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        if track_region is None:
            return mask, image

        region_left, region_top, region_width, region_height = region
        track_left, track_top, track_width, track_height = track_region
        relative_left = track_left - region_left
        relative_top = track_top - region_top
        if (
            relative_left < 0
            or relative_top < 0
            or track_width <= 0
            or track_height <= 0
            or relative_left + track_width > region_width
            or relative_top + track_height > region_height
        ):
            return mask, image

        return (
            mask[relative_top : relative_top + track_height, relative_left : relative_left + track_width],
            image[relative_top : relative_top + track_height, relative_left : relative_left + track_width],
        )

    def _remember_stable_bar_sample(
        self,
        bar_type: str,
        percent: float,
        region: tuple[int, int, int, int],
    ) -> None:
        self.stable_bar_samples[bar_type] = (time.monotonic(), region, percent)

    def _recent_stable_bar_percent(
        self,
        bar_type: str,
        region: tuple[int, int, int, int],
    ) -> float | None:
        sampled_at, stable_region, percent = getattr(self, "stable_bar_samples", {}).get(
            bar_type,
            (-999.0, None, None),
        )
        if stable_region != region:
            return None
        if time.monotonic() - sampled_at > BAR_STABLE_SAMPLE_HOLD_SECONDS:
            return None
        return percent

    def _percent_from_bar_mask(
        self,
        mask: np.ndarray,
        image: np.ndarray | None = None,
        require_clear_tail: bool = False,
    ) -> float | None:
        percent, _reason, _tail_clear = self._percent_from_bar_mask_result(mask, image, require_clear_tail)
        return percent

    def _percent_from_bar_mask_result(
        self,
        mask: np.ndarray,
        image: np.ndarray | None = None,
        require_clear_tail: bool = False,
    ) -> tuple[float | None, str, bool | None]:
        _height, width = mask.shape
        column_filled = mask.mean(axis=0) > BAR_COLUMN_FILL_MIN_RATIO
        filled_indexes = np.flatnonzero(column_filled)
        if filled_indexes.size == 0:
            return None, "找不到符合顏色的填滿欄位", None

        left_tolerance = max(2, round(width * BAR_LEFT_EDGE_TOLERANCE_RATIO))
        first_filled = int(filled_indexes[0])
        if first_filled > left_tolerance:
            return None, f"左邊界不符：first={first_filled}", None

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
            return None, "填滿區段寬度無效", None

        segment_density = float(column_filled[start : end + 1].mean())
        if segment_density < BAR_MIN_SEGMENT_DENSITY:
            return None, f"區段密度過低：{segment_density:.2f}", None

        if not self._bar_run_has_horizontal_body(mask, start, end):
            return None, "水平 body 不足", None

        tail_clear: bool | None = None
        if require_clear_tail and image is not None:
            tail_clear = not self._bar_tail_looks_obstructed(image, end)
            if not tail_clear:
                return None, "尾段疑似被遮擋", tail_clear

        return normalize_bar_percent(float((end + 1) / width * 100.0)), "OK", tail_clear

    def _set_bar_detection_debug(
        self,
        bar_type: str,
        *,
        source: str,
        region: tuple[int, int, int, int] | None,
        percent: float | None,
        success: bool,
        reason: str,
        require_clear_tail: bool,
        tail_clear: bool | None,
    ) -> None:
        self.last_bar_debug[bar_type] = BarDetectionDebug(
            bar_type=bar_type,
            source=source,
            region=region,
            percent=percent,
            success=success,
            reason=reason,
            require_clear_tail=require_clear_tail,
            tail_clear=tail_clear,
        )

    def _bar_detection_debug_text(self, bar_type: str) -> str:
        debug = self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type))
        label = "HP" if bar_type == "hp" else "MP"
        percent = "--" if debug.percent is None else f"{debug.percent:.0f}%"
        region = "--" if debug.region is None else ",".join(str(value) for value in debug.region)
        tail = ""
        if debug.require_clear_tail:
            tail = " | tail=OK" if debug.tail_clear else " | tail=FAIL"
        return f"{label}: {debug.source} | {percent} | {region} | {debug.reason}{tail}"

    def current_bar_detection_regions(self) -> dict[str, tuple[int, int, int, int] | None]:
        return {
            "hp": self.last_bar_debug.get("hp", BarDetectionDebug("hp")).region,
            "mp": self.last_bar_debug.get("mp", BarDetectionDebug("mp")).region,
        }

    def capture_bar_preview_images(self, make_target_topmost: bool = False) -> dict[str, dict[str, object]]:
        previews: dict[str, dict[str, object]] = {}
        missing_regions = [
            bar_type
            for bar_type in ("hp", "mp")
            if self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type)).region is None
        ]
        if missing_regions:
            return {
                bar_type: {
                    "label": "HP" if bar_type == "hp" else "MP",
                    "debug": self._bar_detection_debug_text(bar_type),
                    "image": None,
                    "error": "尚無可預覽的偵測區域",
                }
                for bar_type in ("hp", "mp")
            }

        target_hwnd = self._target_window_handle() if make_target_topmost else 0
        with temporarily_make_window_topmost(target_hwnd) as target_is_ready:
            if make_target_topmost and not target_is_ready:
                return {
                    bar_type: {
                        "label": "HP" if bar_type == "hp" else "MP",
                        "debug": self._bar_detection_debug_text(bar_type),
                        "image": None,
                        "error": "無法顯示目標遊戲視窗，預覽未更新",
                    }
                    for bar_type in ("hp", "mp")
                }
            if make_target_topmost and not self._wait_for_preview_target_ready(target_hwnd):
                return {
                    bar_type: {
                        "label": "HP" if bar_type == "hp" else "MP",
                        "debug": self._bar_detection_debug_text(bar_type),
                        "image": None,
                        "error": "目標遊戲視窗尚未完成顯示，預覽未更新",
                    }
                    for bar_type in ("hp", "mp")
                }
            for bar_type in ("hp", "mp"):
                debug = self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type))
                label = "HP" if bar_type == "hp" else "MP"
                left, top, width, height = debug.region or (0, 0, 0, 0)
                try:
                    image = np.asarray(
                        self.sct.grab(
                            {
                                "left": left,
                                "top": top,
                                "width": width,
                                "height": height,
                            }
                        )
                    )
                    mask = self._bar_color_mask(image, bar_type)
                    track_region = getattr(self, "bottom_bar_track_regions", {}).get(bar_type)
                    percent_mask, percent_image = self._bar_percent_inputs(
                        debug.region or (left, top, width, height),
                        mask,
                        image,
                        track_region,
                    )
                    percent = self._percent_from_bar_mask(percent_mask, percent_image)
                    if percent is None:
                        previews[bar_type] = {
                            "label": label,
                            "debug": self._bar_detection_debug_text(bar_type),
                            "image": None,
                            "error": "預覽截圖未通過 HP/MP 色條驗證",
                        }
                        continue
                    previews[bar_type] = {
                        "label": label,
                        "debug": self._bar_detection_debug_text(bar_type),
                        "image": bgra_image_to_ppm_data(image, target_size=BAR_PREVIEW_IMAGE_SIZE),
                        "error": "",
                    }
                except Exception as exc:
                    previews[bar_type] = {
                        "label": label,
                        "debug": self._bar_detection_debug_text(bar_type),
                        "image": None,
                        "error": str(exc),
                    }
        return previews

    def _wait_for_preview_target_ready(self, target_hwnd: int) -> bool:
        deadline = time.monotonic() + BAR_PREVIEW_WINDOW_READY_TIMEOUT_SECONDS
        while time.monotonic() <= deadline:
            if not is_valid_window(target_hwnd):
                return False
            width, height = window_client_size(target_hwnd)
            if not is_window_minimized(target_hwnd) and width > 0 and height > 0:
                time.sleep(BAR_PREVIEW_RENDER_SETTLE_SECONDS)
                return True
            time.sleep(BAR_PREVIEW_WINDOW_POLL_SECONDS)
        return False

    def _target_window_handle(self) -> int:
        if self.target_window_provider is not None:
            try:
                hwnd = int(self.target_window_provider() or 0)
                if hwnd:
                    self.last_target_hwnd = hwnd
                    return hwnd
            except Exception:
                pass
        return self.last_target_hwnd

    def _bar_run_has_horizontal_body(self, mask: np.ndarray, start: int, end: int) -> bool:
        if end < start:
            return False
        segment = mask[:, start : end + 1]
        if segment.size == 0:
            return False
        row_density = segment.mean(axis=1)
        dense_row_count = int((row_density >= BAR_MIN_BODY_ROW_DENSITY).sum())
        return dense_row_count >= min(BAR_MIN_BODY_ROW_COUNT, segment.shape[0])

    def _bar_tail_looks_obstructed(self, image: np.ndarray, fill_end: int) -> bool:
        _height, width, _channels = image.shape
        margin = max(2, round(width * 0.04))
        tail_start = fill_end + 1 + margin
        min_tail_width = max(8, round(width * BAR_TAIL_CHECK_MIN_WIDTH_RATIO))
        if width - tail_start < min_tail_width:
            return False

        tail = image[:, tail_start:, :3].astype(np.float32)
        blue = tail[:, :, 0]
        green = tail[:, :, 1]
        red = tail[:, :, 2]
        luminance = red * 0.299 + green * 0.587 + blue * 0.114
        chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
        empty_slot = (
            (luminance <= BAR_EMPTY_TAIL_MAX_LUMINANCE)
            & (chroma <= BAR_EMPTY_TAIL_MAX_CHROMA)
        )
        empty_ratio = float(empty_slot.mean())
        return empty_ratio < BAR_EMPTY_TAIL_MIN_RATIO

    def _bar_run_candidates(self, mask: np.ndarray, client_width: int) -> list[tuple[int, int, int]]:
        min_run_pixels = max(BAR_SEARCH_MIN_RUN_PIXELS, round(client_width * 0.015))
        candidates: list[tuple[int, int, int]] = []
        for row_index, row in enumerate(mask):
            padded = np.concatenate(([False], row, [False]))
            changes = np.flatnonzero(padded[1:] != padded[:-1])
            for start, end in zip(changes[::2], changes[1::2]):
                run_length = int(end - start)
                if run_length >= min_run_pixels:
                    if not self._bar_run_has_horizontal_body(mask, int(start), int(end - 1)):
                        continue
                    candidates.append((int(start), int(row_index), run_length))
        candidates.sort(key=lambda item: item[2], reverse=True)
        return candidates[:80]

    def _bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        bgra = image[:, :, :3]
        blue = bgra[:, :, 0].astype(np.int16)
        green = bgra[:, :, 1].astype(np.int16)
        red = bgra[:, :, 2].astype(np.int16)

        if bar_type == "hp":
            return (red > 150) & (green < 120) & (blue < 150) & (red > green + 40) & (red > blue + 40)
        return (blue > 140) & (green > 75) & (red < 140) & (blue > red + 35)

    def _is_transition_fade_active(self) -> bool:
        gameplay_left, gameplay_top, gameplay_width, gameplay_height = self._gameplay_content_bounds(
            self._foreground_client_bounds()
        )
        sample_top = gameplay_top + round(gameplay_height * 0.88)
        sample_height = max(1, round(gameplay_height * 0.10))
        image = np.asarray(
            self.sct.grab(
                {
                    "left": gameplay_left,
                    "top": sample_top,
                    "width": gameplay_width,
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
        gameplay_left, gameplay_top, gameplay_width, gameplay_height = self._gameplay_content_bounds(
            self._foreground_client_bounds()
        )
        sample_left = gameplay_left + round(gameplay_width * 0.14)
        sample_top = gameplay_top + round(gameplay_height * 0.12)
        sample_width = max(1, round(gameplay_width * 0.72))
        sample_height = max(1, round(gameplay_height * 0.76))
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
            pause_reason = "偵測到頻道切換載入頁，暫停輔助功能"
        elif self._is_transition_fade_active():
            pause_reason = "偵測到地圖過場暗幕，暫停輔助功能"

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

    def _foreground_client_bounds(self) -> tuple[int, int, int, int]:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("找不到前景視窗")
        self.last_target_hwnd = int(hwnd)

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
            self.experience_ocr_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
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
