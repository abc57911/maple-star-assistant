from __future__ import annotations

import ctypes
import contextlib
import math
import hashlib
import multiprocessing as mp
import sys
import time
import winsound
from concurrent.futures import ProcessPoolExecutor
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import cv2
import mss
import numpy as np

from ..constants import (
    ASYNC_KEY_DOWN_MASK,
    AUTO_DRINK_DISABLE_HOLD_SECONDS,
    AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS,
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
    BAR_PAIR_MIN_SEARCH_ROW_RATIO,
    BAR_SEARCH_MIN_RUN_PIXELS,
    BAR_STABLE_SAMPLE_HOLD_SECONDS,
    BAR_TAIL_CHECK_MIN_WIDTH_RATIO,
    BAR_TRANSIENT_CAPTURE_ATTEMPTS,
    BAR_TRANSIENT_RETRY_DELAY_SECONDS,
    BAR_UNSTABLE_LOG_INTERVAL_SECONDS,
    BAR_VERTICAL_BODY_ROW_DENSITY,
    DEFAULT_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
    EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
    FADE_GUARD_BRIGHT_PIXEL_RATIO,
    FADE_GUARD_MEAN_LUMINANCE,
    FADE_GUARD_RECOVERY_SECONDS,
    FADE_GUARD_REQUIRED_FRAMES,
    FULL_BAR_SNAP_PERCENT,
    GAME_CONTENT_ASPECT_RATIO,
    GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS,
    BAR_FULL_WIDTH_MIN_COLUMN_RATIO,
    LOADING_GUARD_BRIGHT_PIXEL_RATIO,
    LOADING_GUARD_LOW_SATURATION_RATIO,
    LOADING_GUARD_MEAN_LUMINANCE,
    PICKUP_DISABLE_HOLD_SECONDS,
    PICKUP_HUD_REFRESH_INTERVAL_SECONDS,
    PICKUP_TOGGLE_DEBOUNCE_SECONDS,
    PM_REMOVE,
    POTION_EFFECT_AUTO_HOLD_BAR_TYPES,
    POTION_EFFECT_DAMAGE_GRACE_SECONDS,
    POTION_EFFECT_HP_STABILITY_CONFIRMATION_MIN_SAMPLES,
    POTION_EFFECT_HP_STABILITY_CONFIRMATION_SECONDS,
    POTION_EFFECT_HP_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT,
    POTION_EFFECT_NO_EFFECT_LIMIT,
    POTION_EFFECT_OBSERVATION_SECONDS,
    POTION_EFFECT_PRE_OBSERVATION_MIN_SAMPLES,
    POTION_EFFECT_PRE_OBSERVATION_SECONDS,
    POTION_EFFECT_PRE_OBSERVATION_VOLATILITY_TOLERANCE_PERCENT,
    POTION_EFFECT_STABILITY_CONFIRMATION_MIN_SAMPLES,
    POTION_EFFECT_STABILITY_CONFIRMATION_SECONDS,
    POTION_EFFECT_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT,
    POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT,
    POTION_EFFECT_WATCH_VOLATILITY_TOLERANCE_PERCENT,
    POTION_CONTINUOUS_HOLD_REFRESH_SECONDS,
    POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
    POTION_FAST_CAPTURE_INTERVAL_SECONDS,
    POTION_MIN_COOLDOWN_SECONDS,
    POTION_NEAR_THRESHOLD_FAST_MARGIN_PERCENT,
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
from ..adapters.debug_logging import log_debug, log_exception, log_experience_debug
from ..services.control_hotkey_worker import (
    CONTROL_HOTKEY_EMERGENCY_STOP,
    CONTROL_HOTKEY_EXPERIENCE_RESET,
    CONTROL_HOTKEY_EXPERIENCE_TOGGLE,
    CONTROL_HOTKEY_PICKUP_TOGGLE,
    CONTROL_HOTKEY_TOGGLE,
    ControlHotkeyWorker,
)
from ..services.potion_action_worker import PotionActionWorker
from ..services.runtime_processes import (
    ExperienceControl,
    ExperienceStatus,
    InlineExecutor,
    PotionControl,
    PotionStatus,
    RuntimeProcessCoordinator,
    WorkerCrashed,
    _experience_status_signature,
    _potion_status_signature,
)
from ..models.experience import (
    EXP_LEVEL_WRAP_HIGH_PERCENT,
    ExperienceEfficiencyTracker,
    ExperienceOcrContinuityHint,
    ExperienceOcrImage,
    ExperienceSnapshot,
    ExperienceTextReading,
    PaddleExperienceTextReader,
    read_experience_burst_frames_in_worker,
    read_experience_tooltip_in_worker,
)
from ..models.controller_state import (
    BarDetectionDebug,
    BottomHudLayout,
    ExperienceBaselineCalibration,
    ExperienceOcrBurst,
    ExperienceOcrImageSignature,
    ExperienceOcrJob,
    HudSearchArea,
    OutOfPotionHold,
    PotionEffectAttempt,
)
from ..services.bar_detection import (
    bgra_image_to_ppm_data,
    loading_screen_metrics,
    normalize_bar_percent,
    should_continue_continuous_drink,
    should_drink_for_threshold,
)
from ..views.settings_gui import AutoPotionSettingsGui, GuiConsoleWriter
from ..models.settings import AutoPotionSettings
from ..services.settings_store import load_settings, save_settings
from ..adapters.win_input import (
    BitmapInfo,
    Msg,
    PhysicalMouseActivityObserver,
    Point,
    client_to_screen_point,
    click_client_point,
    get_cursor_position,
    is_valid_window,
    is_window_minimized,
    key_down,
    key_up,
    parse_vk_key,
    set_cursor_position,
    sleep_while_pumping_messages,
    tap_hotkey,
    temporary_mouse_input_lock,
    temporarily_make_window_topmost,
    gdi32,
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
EXPERIENCE_WIDE_TEXT_LEFT_RATIO = 0.34
EXPERIENCE_WIDE_TEXT_RIGHT_PADDING_RATIO = 0.08
EXPERIENCE_WIDE_TEXT_HEIGHT_RATIO = 1.65
EXPERIENCE_TOOLTIP_SETTLE_SECONDS = 0.16
EXPERIENCE_TOOLTIP_RETRY_SETTLE_SECONDS = 0.08
EXPERIENCE_TOOLTIP_CAPTURE_ATTEMPTS = 3
EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES = 3
EXPERIENCE_TOOLTIP_CURSOR_TOLERANCE_PIXELS = 2
EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS = 5.0
EXPERIENCE_MOUSE_IDLE_STATUS_UPDATE_SECONDS = EXPERIENCE_CAPTURE_INTERVAL_SECONDS
EXPERIENCE_TOOLTIP_CURSOR_RIGHT_PADDING_RATIO = 0.08
EXPERIENCE_TOOLTIP_ROI_OFFSET_X = 8
EXPERIENCE_TOOLTIP_ROI_OFFSET_Y = -78
EXPERIENCE_TOOLTIP_ROI_WIDTH = 370
EXPERIENCE_TOOLTIP_ROI_HEIGHT = 90
EXPERIENCE_OCR_SIGNATURE_THUMB_WIDTH = 96
EXPERIENCE_OCR_SIGNATURE_THUMB_HEIGHT = 18
EXPERIENCE_OCR_SIGNATURE_CHANGED_PIXEL_DELTA = 4
EXPERIENCE_OCR_SIGNATURE_MAX_MEAN_DIFF = 0.35
EXPERIENCE_OCR_SIGNATURE_MAX_CHANGED_RATIO = 0.002
EXPERIENCE_BASELINE_CALIBRATION_MAX_ATTEMPTS = 2
EXPERIENCE_BASELINE_CALIBRATION_COOLDOWN_SECONDS = 30.0
EXPERIENCE_BASELINE_CALIBRATION_TIMEOUT_SECONDS = 4.0
EXPERIENCE_BASELINE_CALIBRATION_MENU_SETTLE_SECONDS = 0.18
EXPERIENCE_BASELINE_CALIBRATION_STATS_SETTLE_SECONDS = 0.25
EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS = 10.0 * 60.0
EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS = 10.0
EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS = 3
HUD_LABEL_MATCH_THRESHOLD = 0.42
HUD_LABEL_SCALE_MIN = 0.70
HUD_LABEL_SCALE_MAX = 1.60
HUD_LABEL_SCALE_STEP = 0.05
HUD_LABEL_SCALE_TOLERANCE = 0.16
HUD_LABEL_GEOMETRY_Y_TOLERANCE_RATIO = 1.10
HUD_LABEL_BAR_SEARCH_RIGHT_RATIO = 0.48
HUD_EXP_TEXT_RIGHT_PADDING_RATIO = 0.035
BAR_PAIR_HP_MAX_LEFT_RATIO = 0.48
BAR_PAIR_MIN_GAP_RATIO = 0.10
BAR_PAIR_MAX_GAP_RATIO = 0.24
BAR_PAIR_REUSE_MIN_GAP_RATIO = 0.06
BAR_PAIR_REUSE_MAX_GAP_RATIO = 0.34
BAR_PAIR_REUSE_MAX_CENTER_Y_DELTA_RATIO = 1.10
BAR_PAIR_REUSE_WIDTH_RATIO_MIN = 0.55
BAR_PAIR_REUSE_WIDTH_RATIO_MAX = 1.80
BAR_PAIR_REUSE_HEIGHT_RATIO_MAX = 2.40
BAR_EMPTY_TRACK_MIN_NEUTRAL_RATIO = 0.65
BAR_EMPTY_TRACK_MAX_FOREGROUND_RATIO = 0.035
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_VOLUME_PERCENT = 20
MCI_MAX_VOLUME = 1000
MCI_MEDIA_VOLUME = round(MCI_MAX_VOLUME * MEDIA_VOLUME_PERCENT / 100)
MCI_MEDIA_START_MS = 0
AUTO_DRINK_START_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-start.mp3"
AUTO_DRINK_STOP_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-stop.mp3"
AUTO_DRINK_POTION_CHECK_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-postion-check.mp3"
AUTO_PICKUP_START_SOUND_PATH = PROJECT_ROOT / "media" / "auto-pickup-start.mp3"
AUTO_PICKUP_STOP_SOUND_PATH = PROJECT_ROOT / "media" / "auto-pickup-stop.mp3"
MEDIA_SOUND_ALIASES = (
    (AUTO_DRINK_START_SOUND_PATH, "auto_drink_start"),
    (AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop"),
    (AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check"),
    (AUTO_PICKUP_START_SOUND_PATH, "pickup_start"),
    (AUTO_PICKUP_STOP_SOUND_PATH, "pickup_stop"),
)
MEDIA_SOUND_PATH_BY_ALIAS = {alias: path for path, alias in MEDIA_SOUND_ALIASES}
POTION_TIME_EPSILON_SECONDS = 1e-9
POTION_PENDING_SEND_CAPTURE_GUARD_SECONDS = 0.20
POTION_EXPERIENCE_DEFER_SECONDS = 1.0
POTION_BLOCKED_SOUND_INTERVAL_SECONDS = 3.0
POTION_CHECK_SOUND_INTERVAL_SECONDS = 10.0
RUNTIME_POTION_STATUS_TIMEOUT_SECONDS = 2.0
DIRECT_BAR_FAILURE_WARNING_ATTEMPTS = 3
RECENT_HUD_GEOMETRY_GRACE_SECONDS = 2.0
DIRECT_BAR_BIT_COUNT = 32
DIRECT_BAR_BYTES_PER_PIXEL = 4
DIB_RGB_COLORS = 0
GDI_BI_RGB = 0
GDI_SRCCOPY = 0x00CC0020
STAT_WINDOW_EXP_LABEL_TEMPLATE_MATCH_THRESHOLD = 0.80
STAT_WINDOW_EXP_LABEL_TEMPLATE_PATH = PROJECT_ROOT / "maple_star" / "assets" / "stat_window_exp_label.png"
HUD_LABEL_TEMPLATE_PATHS = {
    "hp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_hp.png",
    "mp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_mp.png",
    "exp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_exp.png",
}
_STAT_WINDOW_EXP_LABEL_TEMPLATE: np.ndarray | None = None
_HUD_LABEL_TEMPLATE_CACHE: dict[str, np.ndarray] = {}


class DirectBarCaptureContext:
    def __init__(self) -> None:
        self.screen_dc = 0
        self.memory_dc = 0
        self.bitmap = 0
        self.old_bitmap = 0
        self.size: tuple[int, int] | None = None
        self.bitmap_info = BitmapInfo()
        self.buffer: object | None = None

    def capture(self, left: int, top: int, width: int, height: int) -> np.ndarray | None:
        if width <= 0 or height <= 0:
            return None
        if not self._ensure_size(width, height):
            return None
        if not gdi32.BitBlt(self.memory_dc, 0, 0, width, height, self.screen_dc, left, top, GDI_SRCCOPY):
            return None
        assert self.buffer is not None
        copied_rows = gdi32.GetDIBits(
            self.memory_dc,
            self.bitmap,
            0,
            height,
            ctypes.byref(self.buffer),
            ctypes.byref(self.bitmap_info),
            DIB_RGB_COLORS,
        )
        if copied_rows != height:
            return None
        return np.frombuffer(self.buffer, dtype=np.uint8).reshape((height, width, DIRECT_BAR_BYTES_PER_PIXEL)).copy()

    def _ensure_size(self, width: int, height: int) -> bool:
        if not self.screen_dc:
            self.screen_dc = user32.GetDC(None)
            if not self.screen_dc:
                return False
        if not self.memory_dc:
            self.memory_dc = gdi32.CreateCompatibleDC(self.screen_dc)
            if not self.memory_dc:
                self.close()
                return False
        if self.size == (width, height) and self.bitmap and self.buffer is not None:
            return True

        self._delete_bitmap()
        bitmap = gdi32.CreateCompatibleBitmap(self.screen_dc, width, height)
        if not bitmap:
            self.close()
            return False
        old_bitmap = gdi32.SelectObject(self.memory_dc, bitmap)
        if not old_bitmap:
            gdi32.DeleteObject(bitmap)
            self.close()
            return False

        size_image = width * height * DIRECT_BAR_BYTES_PER_PIXEL
        bitmap_info = BitmapInfo()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(bitmap_info.bmiHeader)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = DIRECT_BAR_BIT_COUNT
        bitmap_info.bmiHeader.biCompression = GDI_BI_RGB
        bitmap_info.bmiHeader.biSizeImage = size_image

        self.bitmap = bitmap
        self.old_bitmap = old_bitmap
        self.size = (width, height)
        self.bitmap_info = bitmap_info
        self.buffer = (ctypes.c_ubyte * size_image)()
        return True

    def _delete_bitmap(self) -> None:
        if self.bitmap:
            if self.old_bitmap:
                gdi32.SelectObject(self.memory_dc, self.old_bitmap)
            gdi32.DeleteObject(self.bitmap)
        self.bitmap = 0
        self.old_bitmap = 0
        self.size = None
        self.buffer = None

    def close(self) -> None:
        self._delete_bitmap()
        if self.memory_dc:
            gdi32.DeleteDC(self.memory_dc)
            self.memory_dc = 0
        if self.screen_dc:
            user32.ReleaseDC(None, self.screen_dc)
            self.screen_dc = 0


class AutoPotionController:
    def __init__(
        self,
        is_target_window_active: Callable[[], bool],
        settings: AutoPotionSettings | None = None,
        target_window_provider: Callable[[], int] | None = None,
        gui: object | None = None,
        start_control_hotkey_worker: bool = True,
        start_potion_action_worker: bool = True,
        experience_executor: object | None = None,
        runtime_processes_enabled: bool = True,
        save_settings_on_cleanup: bool = True,
        experience_only_runtime: bool = False,
    ) -> None:
        self.is_target_window_active = is_target_window_active
        self.target_window_provider = target_window_provider
        self.settings = settings or load_settings()
        self.gui = gui if gui is not None else AutoPotionSettingsGui(self.settings)
        self.gui.set_bar_preview_provider(self.capture_bar_preview_images)
        self.gui.set_experience_reset_handler(self.reset_experience_statistics)
        self.sct = mss.mss()
        self.experience_only_runtime = experience_only_runtime
        self.direct_bar_capture_context = DirectBarCaptureContext()
        self.next_capture_at = 0.0
        self.next_experience_capture_at = 0.0
        self.experience_pause_started_at: float | None = None
        self.experience_total_paused_seconds = 0.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.potion_send_prevalidated_at = -999.0
        self.hp_pending_potion_send_at = -999.0
        self.mp_pending_potion_send_at = -999.0
        self.hp_pending_potion_send_percent: float | None = None
        self.mp_pending_potion_send_percent: float | None = None
        self.hp_potion_effect_attempts: list[PotionEffectAttempt] = []
        self.mp_potion_effect_attempts: list[PotionEffectAttempt] = []
        self.hp_potion_no_effect_count = 0
        self.mp_potion_no_effect_count = 0
        self.hp_potion_last_no_effect_counted_at = -999.0
        self.mp_potion_last_no_effect_counted_at = -999.0
        self.hp_potion_last_observed_percent: float | None = None
        self.mp_potion_last_observed_percent: float | None = None
        self.hp_potion_recent_samples: list[tuple[float, float]] = []
        self.mp_potion_recent_samples: list[tuple[float, float]] = []
        self.hp_potion_recent_damage_at = -999.0
        self.mp_potion_recent_damage_at = -999.0
        self.hp_potion_damage_pressure_active = False
        self.mp_potion_damage_pressure_active = False
        self.hp_out_of_potion_hold: OutOfPotionHold | None = None
        self.mp_out_of_potion_hold: OutOfPotionHold | None = None
        self.last_potion_blocked_sound_at = -999.0
        self.last_potion_check_sound_at = -999.0
        self.last_error_at = -999.0
        self.last_unstable_bar_at = -999.0
        self.direct_bar_failure_count = 0
        self.last_direct_bar_failure_warning_at = -999.0
        self.last_direct_bar_failure_reason = ""
        self.auto_drink_enabled = True
        self.scripts_enabled = True
        self.auto_drink_potion_option_snapshot: tuple[bool, bool] | None = None
        self.hotkey_registered = False
        self.emergency_hotkey_registered = False
        self.experience_toggle_hotkey_registered = False
        self.experience_reset_hotkey_registered = False
        self.pickup_toggle_hotkey_registered = False
        self.control_hotkeys_enabled = start_control_hotkey_worker
        self.control_hotkey_worker = ControlHotkeyWorker() if start_control_hotkey_worker else None
        if self.control_hotkey_worker is not None:
            self.control_hotkey_worker.start()
        start_potion_action_worker = start_potion_action_worker and not runtime_processes_enabled
        self.potion_action_worker = PotionActionWorker() if start_potion_action_worker else None
        if self.potion_action_worker is not None:
            self.potion_action_worker.start()
        self.toggle_hotkey_was_down = False
        self.emergency_stop_hotkey_was_down = False
        self.experience_toggle_hotkey_was_down = False
        self.experience_reset_hotkey_was_down = False
        self.pickup_toggle_hotkey_was_down = False
        self.registered_toggle_hotkey_vk = 0
        self.registered_emergency_stop_hotkey_vk = 0
        self.registered_experience_toggle_hotkey_vk = 0
        self.registered_experience_reset_hotkey_vk = 0
        self.registered_pickup_toggle_hotkey_vk = 0
        self.control_hotkeys_suppressed_until_release = False
        self.last_toggle_hotkey_at = -999.0
        self.last_experience_toggle_hotkey_at = -999.0
        self.last_experience_reset_hotkey_at = -999.0
        self.last_pickup_toggle_hotkey_at = -999.0
        self.auto_drink_disable_hold_started_at = -999.0
        self.pickup_disable_hold_started_at = -999.0
        self.pickup_enabled = False
        self.pickup_held_vk = 0
        self._install_gui_runtime_toggle_handlers()
        self._sync_gui_runtime_toggles()
        self.hp_potion_held_vk = 0
        self.mp_potion_held_vk = 0
        self.hp_potion_hold_refreshed_at = -999.0
        self.mp_potion_hold_refreshed_at = -999.0
        self.emergency_stop_requested = False
        self.last_action = "啟動"
        self.last_bar_debug: dict[str, BarDetectionDebug] = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        self.bottom_bar_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_track_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_regions_client: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_track_regions_client: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_client_size: tuple[int, int] | None = None
        self.bottom_hud_layout: BottomHudLayout | None = None
        self.bottom_bar_regions_at = -999.0
        self.bottom_bar_client_bounds: tuple[int, int, int, int] | None = None
        self.stable_bar_samples: dict[str, tuple[float, tuple[int, int, int, int], float]] = {}
        self.experience_text_region_bar_crop_left_ratios: list[float] = []
        self.experience_tracker = ExperienceEfficiencyTracker()
        self.experience_reader = PaddleExperienceTextReader()
        if experience_executor is not None:
            self.experience_ocr_executor = experience_executor
        elif runtime_processes_enabled:
            self.experience_ocr_executor = InlineExecutor()
        else:
            self.experience_ocr_executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=mp.get_context("spawn"),
            )
        self.experience_ocr_job: ExperienceOcrJob | None = None
        self.experience_ocr_burst: ExperienceOcrBurst | None = None
        self.experience_tooltip_ocr_failures = 0
        self.experience_baseline_calibration: ExperienceBaselineCalibration | None = None
        self.experience_baseline_ocr_job: ExperienceOcrJob | None = None
        self.experience_baseline_calibration_attempts = 0
        self.next_experience_baseline_calibration_at = 0.0
        self.experience_tooltip_baseline_failed = False
        self.experience_initial_tooltip_baseline_started_at: float | None = (
            time.monotonic() if bool(getattr(self.settings, "exp_efficiency_enabled", False)) else None
        )
        self.experience_10m_checkpoint_capture: ExperienceBaselineCalibration | None = None
        self.experience_10m_checkpoint_ocr_job: ExperienceOcrJob | None = None
        self.next_experience_10m_checkpoint_at = 0.0
        self.experience_10m_checkpoint_stopped = False
        self.experience_10m_checkpoint_attempts = 0
        self.experience_10m_checkpoint_tooltip_failed = False
        self.experience_baseline_cursor_position: tuple[int, int] | None = None
        self.mouse_activity_observer: PhysicalMouseActivityObserver | None = PhysicalMouseActivityObserver()
        try:
            self.mouse_activity_observer.start()
        except Exception:
            log_exception("滑鼠活動 observer 啟動失敗")
            self.mouse_activity_observer = None
        self.last_experience_mouse_idle_delay_log_at = -999.0
        self.last_experience_mouse_idle_status_at = -999.0
        self.last_experience_mouse_idle_status_key: tuple[str, int] | None = None
        self.last_completed_experience_ocr_signature: ExperienceOcrImageSignature | None = None
        self.last_failed_experience_ocr_signature: ExperienceOcrImageSignature | None = None
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
        self.runtime_processes_enabled = runtime_processes_enabled
        self.save_settings_on_cleanup = save_settings_on_cleanup
        self.runtime_processes: RuntimeProcessCoordinator | None = None
        self.runtime_settings_snapshot: tuple[object, ...] | None = None
        self.runtime_target_hwnd = 0
        self.runtime_control_state: tuple[bool, bool, bool] | None = None
        self.runtime_potion_generation = 0
        self.runtime_experience_generation = 0
        self.runtime_potion_crash_reported = False
        self.runtime_experience_crash_reported = False
        self.last_runtime_potion_status_at = -999.0
        self.last_runtime_experience_alert_status = ""
        self.last_applied_potion_status_signature: tuple[object, ...] | None = None
        self.last_applied_experience_status_signature: tuple[object, ...] | None = None
        self._media_alias_paths: dict[str, Path] = {}
        self._preload_media_files()
        if start_control_hotkey_worker:
            self._sync_registered_control_hotkeys()
        if runtime_processes_enabled:
            self._start_runtime_processes()

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

    def _runtime_processes_active(self) -> bool:
        return bool(getattr(self, "runtime_processes_enabled", False) and getattr(self, "runtime_processes", None) is not None)

    def _install_gui_runtime_toggle_handlers(self) -> None:
        set_auto_handler = getattr(self.gui, "set_auto_drink_toggle_handler", None)
        if callable(set_auto_handler):
            set_auto_handler(self.set_auto_drink_enabled)
        set_pickup_handler = getattr(self.gui, "set_pickup_toggle_handler", None)
        if callable(set_pickup_handler):
            set_pickup_handler(self.set_pickup_enabled)

    def _sync_gui_runtime_toggles(self) -> None:
        self._sync_gui_auto_drink_enabled()
        self._sync_gui_pickup_enabled()

    def _sync_gui_auto_drink_enabled(self) -> None:
        set_auto_enabled = getattr(self.gui, "set_auto_drink_enabled", None)
        if callable(set_auto_enabled):
            set_auto_enabled(bool(getattr(self, "auto_drink_enabled", False)))

    def _sync_gui_pickup_enabled(self) -> None:
        set_pickup_enabled = getattr(self.gui, "set_pickup_enabled", None)
        if callable(set_pickup_enabled):
            set_pickup_enabled(bool(getattr(self, "pickup_enabled", False)))

    def set_auto_drink_enabled(self, enabled: bool) -> bool:
        desired = bool(enabled)
        if desired == bool(getattr(self, "auto_drink_enabled", False)):
            self._sync_gui_auto_drink_enabled()
            return True
        if desired:
            self.toggle_auto_drink_enabled()
            return bool(getattr(self, "auto_drink_enabled", False))
        self._disable_auto_drink_from_gui()
        return not bool(getattr(self, "auto_drink_enabled", False))

    def set_pickup_enabled(self, enabled: bool) -> bool:
        desired = bool(enabled)
        if desired == bool(getattr(self, "pickup_enabled", False)):
            self._sync_gui_pickup_enabled()
            return True
        self.toggle_pickup_enabled()
        return bool(getattr(self, "pickup_enabled", False)) == desired

    def _start_runtime_processes(self) -> None:
        if getattr(self, "runtime_processes", None) is not None:
            return
        target_hwnd = self._target_window_handle()
        self.runtime_processes = RuntimeProcessCoordinator(self.settings, target_hwnd)
        self.runtime_processes.start()
        self.runtime_target_hwnd = target_hwnd
        self.runtime_settings_snapshot = None
        self.runtime_control_state = None
        self.last_runtime_potion_status_at = time.monotonic()

    def _send_runtime_settings_if_needed(self) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is None:
            return
        snapshot = self.settings.snapshot()
        if snapshot == getattr(self, "runtime_settings_snapshot", None):
            return
        self.runtime_settings_snapshot = snapshot
        runtime.send_settings(self.settings)

    def _send_runtime_target_if_needed(self) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is None:
            return
        hwnd = self._target_window_handle()
        if hwnd == getattr(self, "runtime_target_hwnd", 0):
            return
        self.runtime_target_hwnd = hwnd
        runtime.send_target_window(hwnd)

    def _send_runtime_controls_if_needed(self) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is None:
            return
        state = (
            bool(getattr(self, "auto_drink_enabled", False)),
            bool(getattr(self, "scripts_enabled", False)),
            bool(getattr(self.settings, "exp_efficiency_enabled", False)),
        )
        if state == getattr(self, "runtime_control_state", None):
            return
        previous_state = getattr(self, "runtime_control_state", None)
        if previous_state is None or state[:2] != previous_state[:2]:
            self.runtime_potion_generation = int(getattr(self, "runtime_potion_generation", 0)) + 1
            self.last_runtime_potion_status_at = time.monotonic()
        if previous_state is None or state[1:] != previous_state[1:]:
            self.runtime_experience_generation = int(getattr(self, "runtime_experience_generation", 0)) + 1
        self.runtime_control_state = state
        runtime.send_potion_control(
            PotionControl(
                enabled=state[0],
                scripts_enabled=state[1],
                generation=int(getattr(self, "runtime_potion_generation", 0)),
            )
        )
        runtime.send_experience_control(
            ExperienceControl(
                enabled=state[2] and state[1],
                resume=state[2] and state[1],
                generation=int(getattr(self, "runtime_experience_generation", 0)),
            )
        )

    def _send_runtime_release_all_potions(self) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is not None:
            runtime.send_potion_control(
                PotionControl(
                    enabled=bool(getattr(self, "auto_drink_enabled", False)),
                    scripts_enabled=bool(getattr(self, "scripts_enabled", False)),
                    release_all=True,
                    generation=int(getattr(self, "runtime_potion_generation", 0)),
                )
            )

    def _update_runtime_processes(self, now: float) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is None:
            return
        self._save_settings_when_idle(now)
        target_active = self.is_target_window_active()
        key_capture_blocking = self.is_key_capture_blocking_actions()
        if not target_active or key_capture_blocking:
            self._release_pickup_key()
            if key_capture_blocking:
                self._send_runtime_release_all_potions()
        self._send_runtime_target_if_needed()
        self._send_runtime_settings_if_needed()
        self._send_runtime_controls_if_needed()
        self._drain_runtime_statuses()
        if target_active and not key_capture_blocking:
            if self._pickup_needs_local_hud_refresh(now):
                self.next_capture_at = now + PICKUP_HUD_REFRESH_INTERVAL_SECONDS
                self._refresh_pickup_key_state_for_hud(now)
            else:
                self._sync_pickup_key_state()
        self._report_runtime_worker_failures()
        self._recover_stale_runtime_potion_process(now)

    def _drain_runtime_statuses(self) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is None:
            return
        latest_potion_status: PotionStatus | None = None
        for item in self._runtime_drain_potion_statuses(runtime):
            if isinstance(item, PotionStatus):
                if self._runtime_potion_status_is_current(item):
                    latest_potion_status = item
            elif isinstance(item, WorkerCrashed):
                self._apply_worker_crash(item)
        if latest_potion_status is not None:
            self._apply_potion_status(latest_potion_status)

        latest_experience_status: ExperienceStatus | None = None
        for item in self._runtime_drain_experience_statuses(runtime):
            if isinstance(item, ExperienceStatus):
                if self._runtime_experience_status_is_current(item):
                    latest_experience_status = item
            elif isinstance(item, WorkerCrashed):
                self._apply_worker_crash(item)
        if latest_experience_status is not None:
            self._apply_experience_status(latest_experience_status)

    def _runtime_drain_potion_statuses(self, runtime: object) -> list[object]:
        drain = getattr(runtime, "drain_potion_statuses")
        try:
            return drain(limit=512)
        except TypeError:
            return drain()

    def _runtime_drain_experience_statuses(self, runtime: object) -> list[object]:
        drain = getattr(runtime, "drain_experience_statuses")
        try:
            return drain(limit=512)
        except TypeError:
            return drain()

    def _runtime_potion_status_is_current(self, status: PotionStatus) -> bool:
        if int(getattr(status, "generation", 0)) != int(getattr(self, "runtime_potion_generation", 0)):
            return False
        if bool(status.scripts_enabled) != bool(getattr(self, "scripts_enabled", False)):
            return False
        if bool(status.auto_drink_enabled) != bool(getattr(self, "auto_drink_enabled", False)):
            return False
        return True

    def _runtime_experience_status_is_current(self, status: ExperienceStatus) -> bool:
        if int(getattr(status, "generation", 0)) != int(getattr(self, "runtime_experience_generation", 0)):
            return False
        if not bool(getattr(self, "scripts_enabled", False)):
            return False
        if not bool(getattr(self.settings, "exp_efficiency_enabled", False)):
            return False
        return True

    def _apply_experience_status(self, status: ExperienceStatus) -> None:
        signature = _experience_status_signature(status)
        if signature == getattr(self, "last_applied_experience_status_signature", None):
            return
        self.last_applied_experience_status_signature = signature
        self.gui.set_experience_snapshot(status.snapshot)
        snapshot_status = str(getattr(status.snapshot, "status", "") or "")
        if not snapshot_status.startswith("EXP-10 OCR 失敗"):
            return
        if snapshot_status == self.last_runtime_experience_alert_status:
            return
        self.last_runtime_experience_alert_status = snapshot_status
        self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)

    def _apply_potion_status(self, status: PotionStatus) -> None:
        now = time.monotonic()
        self.last_runtime_potion_status_at = now
        signature = _potion_status_signature(status)
        if (
            signature == getattr(self, "last_applied_potion_status_signature", None)
            and not status.notice
            and not status.console_lines
        ):
            return
        self.last_applied_potion_status_signature = signature
        self._set_gameplay_hud_active(status.gameplay_hud_active, now)
        self.gui.set_current_percentages(status.hp_percent, status.mp_percent)
        self.gui.set_bar_detection_debug(status.hp_debug, status.mp_debug)
        self._apply_runtime_bar_detection_region(
            "hp",
            status.hp_region,
            status.hp_percent,
            status.hp_track_region,
        )
        self._apply_runtime_bar_detection_region(
            "mp",
            status.mp_region,
            status.mp_percent,
            status.mp_track_region,
        )
        if status.gameplay_hud_active and status.hp_region is not None and status.mp_region is not None:
            self.gui.refresh_bar_preview_once()
        if status.status:
            self.gui.set_status(status.status)
        if status.notice:
            self.gui.show_toggle_notice(status.notice)
        for alias in status.media_sound_aliases:
            self._play_runtime_media_sound(alias)
        if status.action:
            self.last_action = status.action
        for line in status.console_lines:
            print(line)

    def _play_runtime_media_sound(self, alias: str) -> None:
        path = MEDIA_SOUND_PATH_BY_ALIAS.get(alias)
        if path is None:
            return
        self._play_media_file(path, alias)

    def _apply_runtime_bar_detection_region(
        self,
        bar_type: str,
        region: tuple[int, int, int, int] | None,
        percent: float | None,
        track_region: tuple[int, int, int, int] | None = None,
    ) -> None:
        if region is None:
            return
        if bar_type in ("hp", "mp"):
            self.bottom_bar_regions[bar_type] = region
            if track_region is not None:
                self.bottom_bar_track_regions[bar_type] = track_region
            self._sync_runtime_bar_region_cache_from_target()
        debug = self.last_bar_debug.get(bar_type)
        if debug is None:
            debug = BarDetectionDebug(bar_type)
            self.last_bar_debug[bar_type] = debug
        debug.source = "runtime"
        debug.region = region
        debug.track_region = track_region
        debug.percent = percent
        debug.success = percent is not None
        debug.reason = "OK" if percent is not None else debug.reason

    def _sync_runtime_bar_region_cache_from_target(self) -> None:
        if "hp" not in self.bottom_bar_regions or "mp" not in self.bottom_bar_regions:
            return
        client_bounds = self._target_client_bounds()
        if client_bounds is None:
            return
        if not self._bar_region_pair_geometry_is_valid(
            self.bottom_bar_regions,
            self.bottom_bar_track_regions,
            client_bounds,
        ):
            return
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = time.monotonic()
        self._cache_bottom_bar_client_regions(client_bounds)

    def _apply_worker_crash(self, crash: WorkerCrashed) -> None:
        if crash.worker == "potion":
            self.runtime_potion_crash_reported = True
            self.auto_drink_enabled = False
            self.gameplay_hud_active = False
            self._sync_gui_auto_drink_enabled()
            self.gui.set_status(f"喝水 process 已停止：{crash.message}")
            self.gui.show_toggle_notice("喝水 process 已停止")
        elif crash.worker == "experience":
            self.runtime_experience_crash_reported = True
            self.gui.set_status(f"EXP process 已停止：{crash.message}")

    def _report_runtime_worker_failures(self) -> None:
        runtime = getattr(self, "runtime_processes", None)
        if runtime is None:
            return
        if not runtime.potion_alive() and not getattr(self, "runtime_potion_crash_reported", False):
            self._apply_worker_crash(WorkerCrashed("potion", "process exited"))
        if not runtime.experience_alive() and not getattr(self, "runtime_experience_crash_reported", False):
            self._apply_worker_crash(WorkerCrashed("experience", "process exited"))

    def _recover_stale_runtime_potion_process(self, now: float) -> None:
        if not self._runtime_processes_active():
            return
        if not self.scripts_enabled or not self.auto_drink_enabled:
            self.last_runtime_potion_status_at = now
            return
        if getattr(self, "runtime_potion_crash_reported", False):
            return
        last_status_at = getattr(self, "last_runtime_potion_status_at", -999.0)
        if last_status_at < 0:
            self.last_runtime_potion_status_at = now
            return
        if now - last_status_at + POTION_TIME_EPSILON_SECONDS < RUNTIME_POTION_STATUS_TIMEOUT_SECONDS:
            return

        runtime = getattr(self, "runtime_processes", None)
        restart = getattr(runtime, "restart_potion", None)
        if not callable(restart):
            self._apply_worker_crash(WorkerCrashed("potion", "status timeout"))
            return
        try:
            target_hwnd = self._target_window_handle()
            restart(self.settings, target_hwnd)
        except Exception as exc:
            log_exception("喝水 process 重啟失敗")
            self._apply_worker_crash(WorkerCrashed("potion", f"restart failed: {exc}"))
            return

        self.runtime_target_hwnd = target_hwnd
        self.runtime_settings_snapshot = None
        self.runtime_control_state = None
        self.gameplay_hud_active = False
        self.last_runtime_potion_status_at = now
        self.gui.set_status("喝水 process 無回報，已自動重啟")
        self.gui.show_toggle_notice("喝水 process 已重啟")
        self._send_runtime_settings_if_needed()
        self._send_runtime_controls_if_needed()

    def _control_hotkey_vk(self, hotkey: str, fallback: str) -> int:
        try:
            return parse_vk_key(hotkey)
        except ValueError:
            return parse_vk_key(fallback)

    def _optional_control_hotkey_vk(self, hotkey: str | None) -> int:
        if not hotkey:
            return 0
        try:
            return parse_vk_key(hotkey)
        except ValueError:
            return 0

    def _sync_registered_control_hotkeys(self) -> None:
        toggle_vk = self._control_hotkey_vk(self.settings.toggle_hotkey, "F11")
        emergency_vk = self._control_hotkey_vk(self.settings.emergency_stop_hotkey, "Pause")
        experience_vk = self._control_hotkey_vk(self.settings.experience_toggle_hotkey, "F10")
        experience_reset_vk = self._control_hotkey_vk(self.settings.experience_reset_hotkey, "F9")
        pickup_toggle_vk = self._optional_control_hotkey_vk(self.settings.pickup_toggle_hotkey)
        if (
            toggle_vk == self.registered_toggle_hotkey_vk
            and emergency_vk == self.registered_emergency_stop_hotkey_vk
            and experience_vk == self.registered_experience_toggle_hotkey_vk
            and experience_reset_vk == self.registered_experience_reset_hotkey_vk
            and pickup_toggle_vk == self.registered_pickup_toggle_hotkey_vk
        ):
            return
        self._unregister_toggle_hotkey()
        self._register_toggle_hotkey(toggle_vk, emergency_vk, experience_vk, experience_reset_vk, pickup_toggle_vk)

    def _register_toggle_hotkey(
        self,
        toggle_vk: int,
        emergency_vk: int,
        experience_vk: int,
        experience_reset_vk: int = 0,
        pickup_toggle_vk: int = 0,
    ) -> None:
        self.registered_toggle_hotkey_vk = toggle_vk
        self.hotkey_registered = bool(toggle_vk)

        self.registered_emergency_stop_hotkey_vk = emergency_vk
        self.emergency_hotkey_registered = bool(emergency_vk)

        self.registered_experience_toggle_hotkey_vk = experience_vk
        self.experience_toggle_hotkey_registered = bool(experience_vk)

        self.registered_experience_reset_hotkey_vk = experience_reset_vk
        self.experience_reset_hotkey_registered = bool(experience_reset_vk)

        self.registered_pickup_toggle_hotkey_vk = pickup_toggle_vk
        self.pickup_toggle_hotkey_registered = bool(pickup_toggle_vk)
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.update_hotkeys(
                {
                    CONTROL_HOTKEY_TOGGLE: toggle_vk,
                    CONTROL_HOTKEY_EMERGENCY_STOP: emergency_vk,
                    CONTROL_HOTKEY_EXPERIENCE_TOGGLE: experience_vk,
                    CONTROL_HOTKEY_EXPERIENCE_RESET: experience_reset_vk,
                    CONTROL_HOTKEY_PICKUP_TOGGLE: pickup_toggle_vk,
                }
            )

    def _unregister_toggle_hotkey(self) -> None:
        self.hotkey_registered = False
        self.registered_toggle_hotkey_vk = 0
        self.emergency_hotkey_registered = False
        self.registered_emergency_stop_hotkey_vk = 0
        self.experience_toggle_hotkey_registered = False
        self.registered_experience_toggle_hotkey_vk = 0
        self.experience_reset_hotkey_registered = False
        self.registered_experience_reset_hotkey_vk = 0
        self.pickup_toggle_hotkey_registered = False
        self.registered_pickup_toggle_hotkey_vk = 0
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.update_hotkeys({})

    def poll_control_hotkeys(self) -> None:
        if not getattr(self, "control_hotkeys_enabled", True):
            return
        if self.gui.is_detecting_key():
            self.toggle_hotkey_was_down = False
            self.emergency_stop_hotkey_was_down = False
            self.experience_toggle_hotkey_was_down = False
            self.experience_reset_hotkey_was_down = False
            self.pickup_toggle_hotkey_was_down = False
            self.auto_drink_disable_hold_started_at = -999.0
            self.pickup_disable_hold_started_at = -999.0
            self._release_pickup_key()
            self._release_all_potion_keys()
            self.control_hotkeys_suppressed_until_release = False
            self._discard_control_hotkey_messages()
            return
        if self.gui.consume_key_detection_finished():
            self.control_hotkeys_suppressed_until_release = True
            self._release_pickup_key()
            self._release_all_potion_keys()
            self._discard_control_hotkey_messages()
            self._sync_control_hotkey_down_states()
            return
        if self.control_hotkeys_suppressed_until_release:
            self._release_pickup_key()
            self._release_all_potion_keys()
            self._discard_control_hotkey_messages()
            self._sync_control_hotkey_down_states()
            if not self._any_control_hotkey_is_down():
                self.control_hotkeys_suppressed_until_release = False
            return

        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            ensure_running = getattr(worker, "ensure_running", None)
            if callable(ensure_running):
                ensure_running()
            worker_events = self._drain_control_hotkey_worker_events()
            cached_down = self._cached_control_hotkey_worker_down_states()
            if cached_down is not None:
                self._apply_control_hotkey_down_states(cached_down)
                now = time.monotonic()
                if not self._has_control_hotkey_activity(worker_events):
                    self._maybe_reenable_control_hotkey_worker_events()
                    return
                if not self._control_hotkey_has_allowed_foreground():
                    self._suspend_control_hotkey_events_outside_foreground()
                    return
                self._set_control_hotkey_worker_events_enabled(True)
                self._process_pending_auto_drink_disable(now)
                self._process_pending_pickup_disable(now)
                if worker_events:
                    for event in worker_events:
                        self._dispatch_control_hotkey_event(event, now)
                return
            if worker_events:
                now = time.monotonic()
                if not self._control_hotkey_has_allowed_foreground():
                    self._suspend_control_hotkey_events_outside_foreground()
                    return
                self._set_control_hotkey_worker_events_enabled(True)
                self._process_pending_auto_drink_disable(now)
                self._process_pending_pickup_disable(now)
                for event in worker_events:
                    self._dispatch_control_hotkey_event(event, now)
                return

        toggle_triggered = False
        emergency_stop_triggered = False
        experience_toggle_triggered = False
        experience_reset_triggered = False
        pickup_toggle_triggered = False
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

        experience_reset_is_down = bool(
            self.registered_experience_reset_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_experience_reset_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        if experience_reset_is_down and not self.experience_reset_hotkey_was_down:
            experience_reset_triggered = True
        self.experience_reset_hotkey_was_down = experience_reset_is_down

        pickup_toggle_is_down = bool(
            self.registered_pickup_toggle_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_pickup_toggle_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        if pickup_toggle_is_down and not self.pickup_toggle_hotkey_was_down:
            pickup_toggle_triggered = True
        self.pickup_toggle_hotkey_was_down = pickup_toggle_is_down

        now = time.monotonic()
        if not (
            toggle_triggered
            or emergency_stop_triggered
            or experience_toggle_triggered
            or experience_reset_triggered
            or pickup_toggle_triggered
            or self._has_pending_control_hotkey_hold()
        ):
            return
        if not self._control_hotkey_has_allowed_foreground():
            self._suspend_control_hotkey_events_outside_foreground()
            return
        self._set_control_hotkey_worker_events_enabled(True)
        self._process_pending_auto_drink_disable(now)
        self._process_pending_pickup_disable(now)
        if emergency_stop_triggered:
            self._try_emergency_stop(now)
        elif toggle_triggered:
            self._try_toggle_scripts_enabled(now)
        elif experience_toggle_triggered:
            self._try_toggle_experience_efficiency(now)
        elif experience_reset_triggered:
            self._try_reset_experience_statistics(now)
        elif pickup_toggle_triggered:
            self._try_toggle_pickup(now)

    def _drain_control_hotkey_worker_events(self) -> list[str]:
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is None:
            return []
        return worker.drain_events()

    def _cached_control_hotkey_worker_down_states(self) -> dict[str, bool] | None:
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is None:
            return None
        cached_down_states = getattr(worker, "cached_down_states", None)
        if not callable(cached_down_states):
            return None
        down = cached_down_states()
        return down if isinstance(down, dict) else None

    def _dispatch_control_hotkey_event(self, event: str, now: float) -> None:
        if event == CONTROL_HOTKEY_EMERGENCY_STOP:
            self._try_emergency_stop(now)
        elif event == CONTROL_HOTKEY_TOGGLE:
            self._try_toggle_scripts_enabled(now)
        elif event == CONTROL_HOTKEY_EXPERIENCE_TOGGLE:
            self._try_toggle_experience_efficiency(now)
        elif event == CONTROL_HOTKEY_EXPERIENCE_RESET:
            self._try_reset_experience_statistics(now)
        elif event == CONTROL_HOTKEY_PICKUP_TOGGLE:
            self._try_toggle_pickup(now)

    def is_key_capture_blocking_actions(self) -> bool:
        return self.gui.is_detecting_key() or self.gui.is_key_detection_release_pending()

    def _sync_control_hotkey_down_states(self) -> None:
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            self._apply_control_hotkey_down_states(worker.sync_down_states())
            return
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
        self.experience_reset_hotkey_was_down = bool(
            self.registered_experience_reset_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_experience_reset_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )
        self.pickup_toggle_hotkey_was_down = bool(
            self.registered_pickup_toggle_hotkey_vk
            and user32.GetAsyncKeyState(self.registered_pickup_toggle_hotkey_vk) & ASYNC_KEY_DOWN_MASK
        )

    def _apply_control_hotkey_down_states(self, down: dict[str, bool]) -> None:
        self.toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_TOGGLE, False)
        self.emergency_stop_hotkey_was_down = down.get(CONTROL_HOTKEY_EMERGENCY_STOP, False)
        self.experience_toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_EXPERIENCE_TOGGLE, False)
        self.experience_reset_hotkey_was_down = down.get(CONTROL_HOTKEY_EXPERIENCE_RESET, False)
        self.pickup_toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_PICKUP_TOGGLE, False)

    def _any_control_hotkey_is_down(self) -> bool:
        return (
            self.toggle_hotkey_was_down
            or self.emergency_stop_hotkey_was_down
            or self.experience_toggle_hotkey_was_down
            or self.experience_reset_hotkey_was_down
            or self.pickup_toggle_hotkey_was_down
        )

    def _has_pending_control_hotkey_hold(self) -> bool:
        return (
            getattr(self, "auto_drink_disable_hold_started_at", -999.0) >= 0
            or getattr(self, "pickup_disable_hold_started_at", -999.0) >= 0
        )

    def _has_control_hotkey_activity(self, worker_events: list[str]) -> bool:
        return bool(worker_events) or self._any_control_hotkey_is_down() or self._has_pending_control_hotkey_hold()

    def _discard_control_hotkey_messages(self) -> None:
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.clear_events()
        message = Msg()
        while user32.PeekMessageW(
            ctypes.byref(message),
            None,
            WM_HOTKEY,
            WM_HOTKEY,
            PM_REMOVE,
        ):
            pass

    def _set_control_hotkey_worker_events_enabled(self, enabled: bool) -> None:
        self.control_hotkey_worker_events_enabled = enabled
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is None:
            return
        set_events_enabled = getattr(worker, "set_events_enabled", None)
        if callable(set_events_enabled):
            set_events_enabled(enabled)

    def _maybe_reenable_control_hotkey_worker_events(self) -> None:
        if getattr(self, "control_hotkey_worker_events_enabled", True):
            return
        if self._control_hotkey_has_allowed_foreground():
            self._set_control_hotkey_worker_events_enabled(True)

    def _suspend_control_hotkey_events_outside_foreground(self) -> None:
        self._set_control_hotkey_worker_events_enabled(False)
        self._discard_control_hotkey_messages()
        self._sync_control_hotkey_down_states()
        self.auto_drink_disable_hold_started_at = -999.0
        self.pickup_disable_hold_started_at = -999.0

    def consume_emergency_stop_requested(self) -> bool:
        if not self.emergency_stop_requested:
            return False
        self.emergency_stop_requested = False
        return True

    def _control_hotkey_has_allowed_foreground(self) -> bool:
        if self.is_target_window_active():
            return True
        app_foreground = getattr(self.gui, "is_app_window_foreground", None)
        if callable(app_foreground):
            try:
                return bool(app_foreground())
            except Exception:
                return False
        return False

    def _control_hotkey_requires_allowed_foreground(self, action: str) -> bool:
        if self._control_hotkey_has_allowed_foreground():
            return True
        return False

    def _try_emergency_stop(self, now: float) -> None:
        if not self._control_hotkey_requires_allowed_foreground("切換總開關"):
            return
        self.emergency_stop()

    def _try_toggle_scripts_enabled(self, now: float) -> None:
        starts_disable_hold = self.auto_drink_enabled and not self._has_out_of_potion_hold()
        if starts_disable_hold:
            if self.auto_drink_disable_hold_started_at >= 0:
                return
            if not self._control_hotkey_requires_allowed_foreground("停用自動喝水"):
                return
            self.auto_drink_disable_hold_started_at = now
            print(f"自動喝水停用確認：按住 {self.settings.toggle_hotkey} {AUTO_DRINK_DISABLE_HOLD_SECONDS:.2f} 秒")
            return
        if now - self.last_toggle_hotkey_at < AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS:
            return
        self.last_toggle_hotkey_at = now
        if not self._control_hotkey_requires_allowed_foreground("切換自動喝水"):
            return
        self.toggle_auto_drink_enabled()

    def _try_toggle_experience_efficiency(self, now: float) -> None:
        if now - self.last_experience_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_toggle_hotkey_at = now
        if not self._control_hotkey_requires_allowed_foreground("切換經驗統計"):
            return
        self.toggle_experience_efficiency()

    def _try_reset_experience_statistics(self, now: float) -> None:
        if now - self.last_experience_reset_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_reset_hotkey_at = now
        if not self._control_hotkey_requires_allowed_foreground("重置經驗統計"):
            return
        if not self.reset_experience_statistics():
            return
        self.gui.set_experience_snapshot(ExperienceSnapshot(status="已重置"))
        self.gui.set_status("經驗統計已重置")
        self.gui.show_toggle_notice("經驗統計已重置")
        self.last_action = f"{self.settings.experience_reset_hotkey} 經驗統計重置"
        print(f"{self.settings.experience_reset_hotkey}：經驗統計已重置")

    def _try_toggle_pickup(self, now: float) -> None:
        if self.pickup_enabled:
            if self.pickup_disable_hold_started_at >= 0:
                return
            if not self._control_hotkey_requires_allowed_foreground("停用拾取"):
                return
            self.pickup_disable_hold_started_at = now
            print(f"拾取停用確認：按住 {self.settings.pickup_toggle_hotkey} {PICKUP_DISABLE_HOLD_SECONDS:.2f} 秒")
            return
        if now - self.last_pickup_toggle_hotkey_at < PICKUP_TOGGLE_DEBOUNCE_SECONDS:
            return
        self.last_pickup_toggle_hotkey_at = now
        if not self._control_hotkey_requires_allowed_foreground("切換拾取"):
            return
        print(
            "拾取切換熱鍵："
            f"enabled={self.pickup_enabled} "
            f"held_vk={getattr(self, 'pickup_held_vk', 0)} "
            f"toggle_down={self.pickup_toggle_hotkey_was_down}"
        )
        self.toggle_pickup_enabled()

    def _process_pending_auto_drink_disable(self, now: float) -> None:
        started_at = getattr(self, "auto_drink_disable_hold_started_at", -999.0)
        if started_at < 0:
            return
        if not self.auto_drink_enabled or self._has_out_of_potion_hold():
            self.auto_drink_disable_hold_started_at = -999.0
            return
        if not self.toggle_hotkey_was_down:
            self.auto_drink_disable_hold_started_at = -999.0
            print("自動喝水停用取消：熱鍵未持續按住")
            return
        if now - started_at + POTION_TIME_EPSILON_SECONDS < AUTO_DRINK_DISABLE_HOLD_SECONDS:
            return
        self.auto_drink_disable_hold_started_at = -999.0
        if not self._control_hotkey_requires_allowed_foreground("停用自動喝水"):
            return
        self.toggle_auto_drink_enabled()

    def _process_pending_pickup_disable(self, now: float) -> None:
        started_at = getattr(self, "pickup_disable_hold_started_at", -999.0)
        if started_at < 0:
            return
        if not self.pickup_enabled:
            self.pickup_disable_hold_started_at = -999.0
            return
        if not self.pickup_toggle_hotkey_was_down:
            self.pickup_disable_hold_started_at = -999.0
            print("拾取停用取消：熱鍵未持續按住")
            return
        if now - started_at + POTION_TIME_EPSILON_SECONDS < PICKUP_DISABLE_HOLD_SECONDS:
            return
        self.pickup_disable_hold_started_at = -999.0
        if not self._control_hotkey_requires_allowed_foreground("停用拾取"):
            return
        self.toggle_pickup_enabled()

    def toggle_pickup_enabled(self) -> None:
        self.pickup_disable_hold_started_at = -999.0
        if self.pickup_enabled:
            self.pickup_enabled = False
            self._release_pickup_key()
            self._sync_gui_pickup_enabled()
            self._play_media_file(AUTO_PICKUP_STOP_SOUND_PATH, "pickup_stop")
            self.gui.set_status("拾取已停用")
            self.gui.show_toggle_notice("拾取已停用")
            self.last_action = "拾取停用"
            print("拾取：已停用")
            return

        pickup_key = self.settings.pickup_key
        if not pickup_key:
            self.pickup_enabled = False
            self._release_pickup_key()
            self._sync_gui_pickup_enabled()
            self.gui.set_status("拾取鍵未設定")
            self.gui.show_toggle_notice("拾取鍵未設定")
            self.last_action = "拾取鍵未設定"
            print("拾取：拾取鍵未設定")
            return

        try:
            parse_vk_key(pickup_key)
        except ValueError:
            self.pickup_enabled = False
            self._release_pickup_key()
            self._sync_gui_pickup_enabled()
            self.gui.set_status("拾取鍵設定無效")
            self.gui.show_toggle_notice("拾取鍵設定無效")
            self.last_action = "拾取鍵設定無效"
            print(f"拾取：拾取鍵設定無效：{pickup_key}")
            return

        self.pickup_enabled = True
        self._sync_pickup_key_state()
        self._sync_gui_pickup_enabled()
        self._play_media_file(AUTO_PICKUP_START_SOUND_PATH, "pickup_start")
        self.gui.set_status("拾取已啟用")
        self.gui.show_toggle_notice("拾取已啟用")
        self.last_action = "拾取啟用"
        print("拾取：已啟用")

    def _sync_pickup_key_state(self) -> None:
        if (
            not self.pickup_enabled
            or not self.scripts_enabled
            or not self.gameplay_hud_active
            or self.is_key_capture_blocking_actions()
        ):
            self._release_pickup_key()
            return

        pickup_key = self.settings.pickup_key
        if not pickup_key:
            self.pickup_enabled = False
            self._release_pickup_key()
            self._sync_gui_pickup_enabled()
            return

        try:
            pickup_vk = parse_vk_key(pickup_key)
        except ValueError:
            self.pickup_enabled = False
            self._release_pickup_key()
            self._sync_gui_pickup_enabled()
            self.gui.set_status("拾取鍵設定無效")
            self.gui.show_toggle_notice("拾取鍵設定無效")
            return

        if self.pickup_held_vk == pickup_vk:
            return
        self._release_pickup_key()
        key_down(pickup_vk)
        self.pickup_held_vk = pickup_vk

    def _pickup_needs_local_hud_refresh(self, now: float) -> bool:
        if now < getattr(self, "next_capture_at", 0.0):
            return False
        return self._pickup_requires_local_hud_refresh()

    def _pickup_requires_local_hud_refresh(self) -> bool:
        if not getattr(self, "pickup_enabled", False):
            return False
        return (
            not getattr(self, "auto_drink_enabled", False)
            or not self._has_enabled_potion_bar()
            or not getattr(self, "gameplay_hud_active", False)
        )

    def _refresh_pickup_key_state_for_hud(self, now: float) -> None:
        if not getattr(self, "pickup_enabled", False):
            return
        if self._refresh_gameplay_hud_state(now):
            self._sync_pickup_key_state()
        else:
            self._release_pickup_key()

    def _release_pickup_key(self) -> None:
        held_vk = getattr(self, "pickup_held_vk", 0)
        if not held_vk:
            return
        self.pickup_held_vk = 0
        key_up(held_vk)

    def _potion_held_vk(self, bar_type: str) -> int:
        return getattr(self, "hp_potion_held_vk" if bar_type == "hp" else "mp_potion_held_vk", 0)

    def _set_potion_held_vk(self, bar_type: str, vk_code: int) -> None:
        if bar_type == "hp":
            self.hp_potion_held_vk = vk_code
        else:
            self.mp_potion_held_vk = vk_code

    def _potion_hold_refreshed_at(self, bar_type: str) -> float:
        return getattr(self, "hp_potion_hold_refreshed_at" if bar_type == "hp" else "mp_potion_hold_refreshed_at", -999.0)

    def _set_potion_hold_refreshed_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.hp_potion_hold_refreshed_at = now
        else:
            self.mp_potion_hold_refreshed_at = now

    def _release_potion_key(self, bar_type: str) -> None:
        held_vk = self._potion_held_vk(bar_type)
        if not held_vk:
            return
        self._set_potion_held_vk(bar_type, 0)
        self._set_potion_hold_refreshed_at(bar_type, -999.0)
        worker = getattr(self, "potion_action_worker", None)
        if worker is not None:
            worker.release(bar_type, held_vk)
            return
        key_up(held_vk)

    def _release_all_potion_keys(self) -> None:
        self._clear_pending_potion_send("hp")
        self._clear_pending_potion_send("mp")
        if self._runtime_processes_active():
            self._send_runtime_release_all_potions()
            self.hp_potion_held_vk = 0
            self.mp_potion_held_vk = 0
            self.hp_potion_hold_refreshed_at = -999.0
            self.mp_potion_hold_refreshed_at = -999.0
            return
        worker = getattr(self, "potion_action_worker", None)
        if worker is not None and (self.hp_potion_held_vk or self.mp_potion_held_vk):
            worker.release_all()
            self.hp_potion_held_vk = 0
            self.mp_potion_held_vk = 0
            self.hp_potion_hold_refreshed_at = -999.0
            self.mp_potion_hold_refreshed_at = -999.0
            return
        self._release_potion_key("hp")
        self._release_potion_key("mp")

    def _hold_potion_key(self, bar_type: str, label: str, key_name: str, now: float) -> bool:
        try:
            vk_code = parse_vk_key(key_name)
        except ValueError:
            self._release_potion_key(bar_type)
            self.gui.set_status(f"{label} 喝水鍵設定無效")
            print(f"{label} 連續喝水略過：喝水鍵設定無效")
            return False

        if self._potion_held_vk(bar_type) == vk_code:
            if now - self._potion_hold_refreshed_at(bar_type) < POTION_CONTINUOUS_HOLD_REFRESH_SECONDS:
                return True
            self._refresh_potion_hold_key(bar_type, vk_code)
            self._set_potion_hold_refreshed_at(bar_type, now)
            return True
        self._release_potion_key(bar_type)
        self._refresh_potion_hold_key(bar_type, vk_code)
        self._set_potion_held_vk(bar_type, vk_code)
        self._set_potion_hold_refreshed_at(bar_type, now)
        return True

    def _refresh_potion_hold_key(self, bar_type: str, vk_code: int) -> None:
        worker = getattr(self, "potion_action_worker", None)
        if worker is not None:
            if self._potion_held_vk(bar_type) == vk_code:
                worker.refresh_hold(bar_type, vk_code)
            else:
                worker.hold(bar_type, vk_code)
        else:
            key_down(vk_code)

    def _log_potion_key_trigger_interval(self, label: str, key_name: str, previous_at: float, now: float) -> None:
        return

    def _tap_potion_key(self, bar_type: str, key_name: str) -> None:
        worker = getattr(self, "potion_action_worker", None)
        if worker is not None:
            worker.tap(bar_type, key_name)
            return
        tap_hotkey(key_name)

    def toggle_auto_drink_enabled(self) -> None:
        self.auto_drink_disable_hold_started_at = -999.0
        if self._runtime_processes_active():
            if self.auto_drink_enabled and self._has_out_of_potion_hold():
                self._clear_potion_effect_state()
                self.auto_drink_enabled = True
                self._sync_gui_auto_drink_enabled()
                notice = "自動喝水已恢復"
                action = f"{self.settings.toggle_hotkey} 自動喝水恢復"
            else:
                self.auto_drink_enabled = not self.auto_drink_enabled
                self._sync_gui_potion_options_after_auto_drink_toggle()
                self._sync_gui_auto_drink_enabled()
                notice = "自動喝水已啟用" if self.auto_drink_enabled else "自動喝水已暫停"
                action = f"{self.settings.toggle_hotkey} {'自動喝水啟用' if self.auto_drink_enabled else '自動喝水暫停'}"
            if self.auto_drink_enabled:
                self._clear_potion_effect_state()
                self._play_media_file(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")
            else:
                self._send_runtime_release_all_potions()
                self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
                self.gui.set_current_percentages(None, None)
            self.gui.set_status(notice if self.auto_drink_enabled else f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
            self.gui.show_toggle_notice(notice)
            self.last_action = action
            self.runtime_control_state = None
            self._send_runtime_controls_if_needed()
            print(f"{self.settings.toggle_hotkey}：{notice}")
            return

        if self.auto_drink_enabled and self._has_out_of_potion_hold():
            self._clear_potion_effect_state()
            self._sync_gui_auto_drink_enabled()
            self._play_media_file(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")
            self.gui.set_status("自動喝水已恢復")
            self.gui.show_toggle_notice("自動喝水已恢復")
            self.last_action = f"{self.settings.toggle_hotkey} 自動喝水恢復"
            print(f"{self.settings.toggle_hotkey}：自動喝水已恢復")
            return

        self.auto_drink_enabled = not self.auto_drink_enabled
        self._sync_gui_potion_options_after_auto_drink_toggle()
        self._sync_gui_auto_drink_enabled()
        if self.auto_drink_enabled:
            self._clear_potion_effect_state()
            self._play_media_file(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")
            self.gui.set_status("自動喝水已啟用")
            self.gui.show_toggle_notice("自動喝水已啟用")
            self.last_action = f"{self.settings.toggle_hotkey} 自動喝水啟用"
            print(f"{self.settings.toggle_hotkey}：自動喝水已啟用")
            return

        self.last_hp_drink_at = time.monotonic()
        self.last_mp_drink_at = self.last_hp_drink_at
        self._clear_potion_effect_state()
        self._release_all_potion_keys()
        self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
        self.gui.set_status(f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
        self.gui.show_toggle_notice("自動喝水已暫停")
        self.gui.set_current_percentages(None, None)
        self.last_action = f"{self.settings.toggle_hotkey} 自動喝水暫停"
        print(f"{self.settings.toggle_hotkey}：自動喝水已暫停")

    def _disable_auto_drink_from_gui(self) -> None:
        self.auto_drink_disable_hold_started_at = -999.0
        if not self.auto_drink_enabled:
            self._sync_gui_auto_drink_enabled()
            return
        self.auto_drink_enabled = False
        self._sync_gui_potion_options_after_auto_drink_toggle()
        self._sync_gui_auto_drink_enabled()
        if self._runtime_processes_active():
            self._send_runtime_release_all_potions()
            self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
            self.gui.set_current_percentages(None, None)
            self.gui.set_status(f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
            self.gui.show_toggle_notice("自動喝水已暫停")
            self.last_action = f"{self.settings.toggle_hotkey} 自動喝水暫停"
            self.runtime_control_state = None
            self._send_runtime_controls_if_needed()
            print(f"{self.settings.toggle_hotkey}：自動喝水已暫停")
            return
        self.last_hp_drink_at = time.monotonic()
        self.last_mp_drink_at = self.last_hp_drink_at
        self._clear_potion_effect_state()
        self._release_all_potion_keys()
        self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
        self.gui.set_status(f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
        self.gui.show_toggle_notice("自動喝水已暫停")
        self.gui.set_current_percentages(None, None)
        self.last_action = f"{self.settings.toggle_hotkey} 自動喝水暫停"
        print(f"{self.settings.toggle_hotkey}：自動喝水已暫停")

    def _sync_gui_potion_options_after_auto_drink_toggle(self) -> None:
        if self.auto_drink_enabled:
            restored = getattr(self, "auto_drink_potion_option_snapshot", None)
            hp_enabled, mp_enabled = restored or (self.settings.hp_enabled, self.settings.mp_enabled)
            self.auto_drink_potion_option_snapshot = None
            update_settings = True
        else:
            if getattr(self, "auto_drink_potion_option_snapshot", None) is None:
                self.auto_drink_potion_option_snapshot = (self.settings.hp_enabled, self.settings.mp_enabled)
            hp_enabled, mp_enabled = False, False
            update_settings = False

        set_potion_enabled = getattr(self.gui, "set_potion_enabled", None)
        if callable(set_potion_enabled):
            set_potion_enabled(hp_enabled, mp_enabled, update_settings=update_settings)
            return
        if update_settings:
            self.settings.hp_enabled = hp_enabled
            self.settings.mp_enabled = mp_enabled

    def toggle_scripts_enabled(self) -> None:
        self.toggle_auto_drink_enabled()

    def toggle_experience_efficiency(self) -> None:
        now = time.monotonic()
        enabled = not self.settings.exp_efficiency_enabled
        self.gui.set_exp_efficiency_enabled(enabled)
        if self._runtime_processes_active():
            runtime = getattr(self, "runtime_processes", None)
            if runtime is not None:
                self.runtime_experience_generation = int(getattr(self, "runtime_experience_generation", 0)) + 1
                runtime.send_experience_control(
                    ExperienceControl(
                        enabled=enabled and self.scripts_enabled,
                        resume=enabled,
                        pause=not enabled,
                        generation=int(getattr(self, "runtime_experience_generation", 0)),
                    )
                )
            self.runtime_control_state = (
                bool(getattr(self, "auto_drink_enabled", False)),
                bool(getattr(self, "scripts_enabled", False)),
                enabled,
            )
            if enabled:
                snapshot = ExperienceSnapshot(status="等待下一次 EXP 樣本")
                self.gui.set_experience_snapshot(snapshot)
            self._play_toggle_beep(RESUME_BEEP_PATTERN if enabled else PAUSE_BEEP_PATTERN)
            self.gui.set_status("經驗統計已啟用" if enabled else "經驗統計已停用")
            self.gui.show_toggle_notice("經驗統計已啟用" if enabled else "經驗統計已停用")
            self.last_action = f"{self.settings.experience_toggle_hotkey} {'經驗統計啟用' if enabled else '經驗統計停用'}"
            print(f"{self.settings.experience_toggle_hotkey}：{'經驗統計已啟用' if enabled else '經驗統計已停用'}")
            return
        if enabled:
            self._stop_experience_ocr_job()
            self._resume_exp_10m_checkpoint_schedule(now)
            effective_now = self._resume_experience_clock(now)
            self.next_experience_capture_at = 0.0
            if not getattr(self.experience_tracker, "samples", []):
                self._reset_experience_baseline_calibration_attempts()
                self._mark_initial_experience_tooltip_baseline_start(now)
            self.experience_tracker.clear_transient_rejection()
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "等待下一次 EXP 樣本" if snapshot.sample_count else "等待有效 EXP 樣本"
            self.gui.set_experience_snapshot(snapshot)
            self._play_toggle_beep(RESUME_BEEP_PATTERN)
            self.gui.set_status("經驗統計已啟用")
            self.gui.show_toggle_notice("經驗統計已啟用")
            self.last_action = f"{self.settings.experience_toggle_hotkey} 經驗統計啟用"
            print(f"{self.settings.experience_toggle_hotkey}：經驗統計已啟用")
            return

        self._stop_experience_ocr_job()
        self.experience_initial_tooltip_baseline_started_at = None
        effective_now = self._pause_experience_clock(now)
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
        self.gui.set_experience_snapshot(snapshot)
        self._play_toggle_beep(PAUSE_BEEP_PATTERN)
        self.gui.set_status("經驗統計已停用")
        self.gui.show_toggle_notice("經驗統計已停用")
        self.last_action = f"{self.settings.experience_toggle_hotkey} 經驗統計停用"
        print(f"{self.settings.experience_toggle_hotkey}：經驗統計已停用")

    def emergency_stop(self) -> None:
        now = time.monotonic()
        if not self.scripts_enabled:
            self.scripts_enabled = True
            self.auto_drink_enabled = True
            self._sync_gui_auto_drink_enabled()
            self._clear_potion_effect_state()
            self._sync_pickup_key_state()
            self._play_toggle_beep(RESUME_BEEP_PATTERN)
            self.gui.set_status("總開關已啟用")
            self.gui.show_toggle_notice("總開關已啟用")
            self.last_action = f"{self.settings.emergency_stop_hotkey} 總開關啟用"
            if self._runtime_processes_active():
                self.runtime_control_state = None
                self._send_runtime_controls_if_needed()
            print(f"{self.settings.emergency_stop_hotkey}：總開關已啟用")
            return

        self.scripts_enabled = False
        self.auto_drink_enabled = False
        self._sync_gui_auto_drink_enabled()
        self._release_pickup_key()
        self._release_all_potion_keys()
        if self._runtime_processes_active():
            runtime = getattr(self, "runtime_processes", None)
            if runtime is not None:
                self.runtime_potion_generation = int(getattr(self, "runtime_potion_generation", 0)) + 1
                self.runtime_experience_generation = int(getattr(self, "runtime_experience_generation", 0)) + 1
                runtime.send_potion_control(
                    PotionControl(
                        False,
                        False,
                        emergency_stop=True,
                        release_all=True,
                        generation=int(getattr(self, "runtime_potion_generation", 0)),
                    )
                )
                runtime.send_experience_control(
                    ExperienceControl(
                        False,
                        pause=True,
                        generation=int(getattr(self, "runtime_experience_generation", 0)),
                    )
                )
            self.runtime_control_state = None
        self.emergency_stop_requested = True
        self.last_hp_drink_at = now
        self.last_mp_drink_at = now
        self._clear_potion_effect_state()
        self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
        self._pause_experience_for_inactive_state(now, "總開關已暫停，保留統計")
        self.gui.set_status(f"{self.settings.emergency_stop_hotkey} 總開關：所有功能已暫停")
        self.gui.show_toggle_notice(f"{self.settings.emergency_stop_hotkey} 總開關")
        self.gui.set_current_percentages(None, None)
        self.last_action = f"{self.settings.emergency_stop_hotkey} 總開關"
        print(f"{self.settings.emergency_stop_hotkey}：總開關，所有功能已暫停")

    def _play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None:
        try:
            for frequency, duration_ms in pattern:
                winsound.Beep(frequency, duration_ms)
        except RuntimeError:
            try:
                winsound.MessageBeep()
            except RuntimeError:
                pass

    def _play_media_file(self, path: Path, alias: str) -> None:
        if not path.exists():
            self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
            return
        try:
            winmm = ctypes.windll.winmm
            buffer = ctypes.create_unicode_buffer(256)
            if not self._ensure_media_alias_opened(winmm, buffer, path, alias):
                return
            winmm.mciSendStringW(f"stop {alias}", buffer, len(buffer), None)
            if winmm.mciSendStringW(f"play {alias} from {MCI_MEDIA_START_MS}", buffer, len(buffer), None) != 0:
                self._close_media_alias(winmm, buffer, alias)
                self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
        except Exception:
            self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)

    def _play_potion_blocked_sound(self, now: float) -> None:
        if now - self.last_potion_blocked_sound_at < POTION_BLOCKED_SOUND_INTERVAL_SECONDS:
            return
        self.last_potion_blocked_sound_at = now
        self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def _play_potion_check_sound(self, now: float) -> None:
        if now - self.last_potion_check_sound_at < POTION_CHECK_SOUND_INTERVAL_SECONDS:
            return
        self.last_potion_check_sound_at = now
        self._play_media_file(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

    def _preload_media_files(self) -> None:
        try:
            winmm = ctypes.windll.winmm
            buffer = ctypes.create_unicode_buffer(256)
            for path, alias in MEDIA_SOUND_ALIASES:
                if path.exists():
                    self._ensure_media_alias_opened(winmm, buffer, path, alias)
        except Exception:
            pass

    def _ensure_media_alias_opened(self, winmm: object, buffer: object, path: Path, alias: str) -> bool:
        alias_paths = getattr(self, "_media_alias_paths", None)
        if alias_paths is None:
            alias_paths = {}
            self._media_alias_paths = alias_paths
        if alias_paths.get(alias) == path:
            return True

        self._close_media_alias(winmm, buffer, alias)
        open_command = f'open "{path}" type mpegvideo alias {alias}'
        if winmm.mciSendStringW(open_command, buffer, len(buffer), None) != 0:
            self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
            return False
        if winmm.mciSendStringW(f"setaudio {alias} volume to {MCI_MEDIA_VOLUME}", buffer, len(buffer), None) != 0:
            self._close_media_alias(winmm, buffer, alias)
            self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
            return False
        if winmm.mciSendStringW(f"set {alias} time format milliseconds", buffer, len(buffer), None) != 0:
            self._close_media_alias(winmm, buffer, alias)
            self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
            return False
        alias_paths[alias] = path
        return True

    def _close_media_alias(self, winmm: object, buffer: object, alias: str) -> None:
        winmm.mciSendStringW(f"close {alias}", buffer, len(buffer), None)
        alias_paths = getattr(self, "_media_alias_paths", None)
        if isinstance(alias_paths, dict):
            alias_paths.pop(alias, None)

    def update(self, now: float, *, pump_gui: bool = True) -> None:
        self.poll_control_hotkeys()
        gui_ready = self.gui.pump() if pump_gui else self.gui.sync_after_event_processing()
        if not gui_ready:
            self._release_all_potion_keys()
            if not self.gui.closed:
                self._set_gameplay_hud_active(False, now)
                if not self.gui.is_window_interaction_active():
                    self.gui.set_current_percentages(None, None)
            return
        if getattr(self, "control_hotkeys_enabled", True):
            self._sync_registered_control_hotkeys()
        self.poll_control_hotkeys()
        self._save_settings_when_idle(now)
        self._enforce_experience_prerequisites(now)

        if self._runtime_processes_active():
            self._update_runtime_processes(now)
            return

        if self.is_key_capture_blocking_actions():
            self._release_pickup_key()
            self._release_all_potion_keys()
            self._set_gameplay_hud_active(False, now)
            self._pause_experience_for_inactive_state(now, "設定快捷鍵中，保留統計")
            self.gui.set_current_percentages(None, None)
            return

        if not self.scripts_enabled:
            self._release_pickup_key()
            self._release_all_potion_keys()
            self._set_gameplay_hud_active(False, now)
            self._pause_experience_for_inactive_state(now, "總開關已暫停，保留統計")
            self.gui.set_status(f"總開關已關閉，按 {self.settings.emergency_stop_hotkey} 開啟")
            self.gui.set_current_percentages(None, None)
            return

        target_window_active = self.is_target_window_active()
        if getattr(self, "experience_only_runtime", False):
            self._update_experience_only_runtime(now, target_window_active)
            return

        if target_window_active:
            self._sync_pickup_key_state()
            self._process_due_potion_sends(now)
        else:
            self._release_pickup_key()
            self._release_all_potion_keys()

        next_pending_send_at = self._next_pending_potion_send_at()
        if (
            target_window_active
            and next_pending_send_at is not None
            and now + POTION_TIME_EPSILON_SECONDS < next_pending_send_at
            and next_pending_send_at - now <= POTION_PENDING_SEND_CAPTURE_GUARD_SECONDS
        ):
            return

        if now < self.next_capture_at:
            return
        self.next_capture_at = now + DEFAULT_CAPTURE_INTERVAL_SECONDS

        if not target_window_active:
            self._set_gameplay_hud_active(False, now)
            self._release_all_potion_keys()
            self._pause_experience_for_inactive_state(now, "等待楓星前景，保留統計")
            self.gui.set_status("等待楓星成為前景視窗")
            self.gui.set_current_percentages(None, None)
            return

        if not self.auto_drink_enabled:
            self._update_without_potion_bar_monitoring(
                now,
                f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復",
            )
            return

        if not self._has_enabled_potion_bar():
            self._update_without_potion_bar_monitoring(now, "未勾選紅水或藍水，暫停 HP/MP 檢查")
            return

        try:
            transition_pause_reason = self._transition_pause_reason(now)
            if transition_pause_reason:
                self._set_gameplay_hud_active(False, now)
                self._release_all_potion_keys()
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status(transition_pause_reason)
                self.gui.set_current_percentages(None, None)
                return

            if not self._refresh_gameplay_hud_state(now):
                self._release_pickup_key()
                self._release_all_potion_keys()
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status("未偵測到遊戲 HUD，暫停取樣")
                self.gui.set_current_percentages(None, None)
                self.gui.set_bar_detection_debug(
                    self._bar_detection_debug_text("hp"),
                    self._bar_detection_debug_text("mp"),
                )
                return

            self._sync_pickup_key_state()
            hp_percent, mp_percent = self._capture_bar_percents()
            self.next_capture_at = now + self._capture_interval_after_potion_sample(hp_percent, mp_percent)
            self.gui.set_current_percentages(hp_percent, mp_percent)
            self.gui.set_bar_detection_debug(
                self._bar_detection_debug_text("hp"),
                self._bar_detection_debug_text("mp"),
            )
            if hp_percent is None or mp_percent is None:
                if self.auto_drink_enabled:
                    self._clear_uncertain_potion_observations(hp_percent, mp_percent)
                if not self._emit_direct_bar_failure_warning_if_needed(now):
                    self.gui.set_status("HP/MP 條偵測不穩定，略過錯誤取樣")
            else:
                if not self.auto_drink_enabled:
                    self._release_all_potion_keys()
                    self.gui.set_status(f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
                elif self._has_out_of_potion_hold():
                    if self.hp_out_of_potion_hold is not None:
                        self._release_potion_key("hp")
                    if self.mp_out_of_potion_hold is not None:
                        self._release_potion_key("mp")
                    self.gui.set_status(self._out_of_potion_hold_status_message())
                else:
                    self.gui.set_status("自動喝水監控中")
                    self.gui.refresh_bar_preview_once()
            if self.auto_drink_enabled and hp_percent is not None and mp_percent is not None:
                self.potion_send_prevalidated_at = now
                self._maybe_drink_hp(now, hp_percent)
                self._maybe_drink_mp(now, mp_percent)
                self._update_potion_effect_watch_cycles(now, hp_percent, mp_percent)
            if self.settings.exp_efficiency_enabled:
                if self._should_defer_experience_for_potion(now, hp_percent, mp_percent):
                    self._defer_experience_for_potion_priority(now)
                else:
                    self._update_experience_efficiency(now)
            else:
                self._stop_experience_ocr_job()
                effective_now = self._pause_experience_clock(now)
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
                self.gui.set_experience_snapshot(snapshot)
        except Exception as exc:
            if now - self.last_error_at >= 2.0:
                print(f"自動喝水錯誤：{exc}")
                self.gui.set_status(f"錯誤：{exc}")
                self.last_error_at = now

    def _has_enabled_potion_bar(self) -> bool:
        return bool(getattr(self.settings, "hp_enabled", False) or getattr(self.settings, "mp_enabled", False))

    def _update_without_potion_bar_monitoring(self, now: float, status: str) -> None:
        self._release_all_potion_keys()
        self.gui.set_current_percentages(None, None)
        self.gui.set_status(status)
        if self._pickup_requires_local_hud_refresh():
            self.next_capture_at = now + PICKUP_HUD_REFRESH_INTERVAL_SECONDS
            self._refresh_pickup_key_state_for_hud(now)
        else:
            self._sync_pickup_key_state()

        try:
            if self.settings.exp_efficiency_enabled:
                if self._experience_runtime_has_cached_hud():
                    self._set_gameplay_hud_active(True, now)
                    self._update_experience_efficiency(now)
                    return

                self._set_gameplay_hud_active(False, now)
                self._pause_experience_for_missing_hud(now)
                return

            self._stop_experience_ocr_job()
            effective_now = self._pause_experience_clock(now)
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
            self.gui.set_experience_snapshot(snapshot)
        except Exception as exc:
            if now - self.last_error_at >= 2.0:
                print(f"HP/MP 監控停用更新錯誤：{exc}")
                self.gui.set_status(f"錯誤：{exc}")
                self.last_error_at = now

    def _update_experience_only_runtime(self, now: float, target_window_active: bool) -> None:
        if not target_window_active:
            self._set_gameplay_hud_active(False, now)
            self._pause_experience_for_inactive_state(now, "等待楓星前景，保留統計")
            return

        try:
            if not self.settings.exp_efficiency_enabled:
                self._stop_experience_ocr_job()
                effective_now = self._pause_experience_clock(now)
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
                self.gui.set_experience_snapshot(snapshot)
                return

            transition_pause_reason = self._transition_pause_reason(now)
            if transition_pause_reason:
                self._set_gameplay_hud_active(False, now)
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status(transition_pause_reason)
                return

            if self._experience_runtime_needs_hud_refresh(now):
                if not self._refresh_gameplay_hud_state(now):
                    self._pause_experience_for_missing_hud(now)
                    self.gui.set_status("未偵測到遊戲 HUD，暫停 EXP 取樣")
                    return
            elif self._experience_runtime_has_cached_hud():
                self._set_gameplay_hud_active(True, now)

            self._update_experience_efficiency(now)
        except Exception as exc:
            if now - self.last_error_at >= 2.0:
                print(f"EXP runtime 錯誤：{exc}")
                self.gui.set_status(f"EXP runtime 錯誤：{exc}")
                self.last_error_at = now

    def _experience_runtime_needs_hud_refresh(self, now: float) -> bool:
        if not self._experience_runtime_has_cached_hud():
            return True
        if getattr(self, "experience_ocr_job", None) is not None:
            return False
        if getattr(self, "experience_ocr_burst", None) is not None:
            return False
        if getattr(self, "experience_baseline_ocr_job", None) is not None:
            return False
        if getattr(self, "experience_10m_checkpoint_ocr_job", None) is not None:
            return False
        if now >= float(getattr(self, "next_experience_capture_at", 0.0)):
            return True
        if now >= float(getattr(self, "next_experience_baseline_calibration_at", 0.0)):
            samples = getattr(self.experience_tracker, "samples", [])
            if isinstance(samples, list) and not samples:
                return True
        checkpoint_exp = getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None)
        if isinstance(checkpoint_exp, int) and now >= float(getattr(self, "next_experience_10m_checkpoint_at", 0.0)):
            return True
        return False

    def _experience_runtime_has_cached_hud(self) -> bool:
        cached = self._cached_bottom_bar_screen_regions_for_current_client()
        if cached is None:
            return False
        regions, track_regions, client_bounds = cached
        return self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds)

    def _save_settings_when_idle(self, now: float) -> None:
        snapshot = self.settings.snapshot()
        if snapshot != self.pending_settings_snapshot:
            self.pending_settings_snapshot = snapshot
            self.next_settings_save_at = now + SETTINGS_SAVE_DEBOUNCE_SECONDS

        if self.next_settings_save_at is not None and now >= self.next_settings_save_at:
            save_settings(self.settings)
            self.next_settings_save_at = None

    def reset_experience_statistics(self) -> bool:
        if self._runtime_processes_active():
            runtime = getattr(self, "runtime_processes", None)
            if runtime is not None:
                self.runtime_experience_generation = int(getattr(self, "runtime_experience_generation", 0)) + 1
                runtime.send_experience_control(
                    ExperienceControl(
                        enabled=bool(getattr(self.settings, "exp_efficiency_enabled", False)),
                        reset=True,
                        generation=int(getattr(self, "runtime_experience_generation", 0)),
                    )
            )
            self.gui.set_experience_snapshot(ExperienceSnapshot(status="已重置"))
            return True
        self._stop_experience_ocr_job()
        self.experience_tracker.reset()
        self.next_experience_capture_at = 0.0
        self._reset_exp_10m_checkpoint_state()
        self._reset_experience_baseline_calibration_attempts()
        if getattr(self.settings, "exp_efficiency_enabled", False):
            self._mark_initial_experience_tooltip_baseline_start(time.monotonic())
        else:
            self.experience_initial_tooltip_baseline_started_at = None
        return True

    def _experience_effective_time(self, now: float) -> float:
        paused_total = float(getattr(self, "experience_total_paused_seconds", 0.0))
        paused_since = getattr(self, "experience_pause_started_at", None)
        raw_reference = paused_since if paused_since is not None else now
        return max(0.0, raw_reference - paused_total)

    def _pause_experience_clock(self, now: float) -> float:
        if getattr(self, "experience_pause_started_at", None) is None:
            self.experience_pause_started_at = now
        return self._experience_effective_time(now)

    def _resume_experience_clock(self, now: float) -> float:
        paused_since = getattr(self, "experience_pause_started_at", None)
        if paused_since is not None:
            paused_total = float(getattr(self, "experience_total_paused_seconds", 0.0))
            self.experience_total_paused_seconds = paused_total + max(0.0, now - paused_since)
            self.experience_pause_started_at = None
        return self._experience_effective_time(now)

    def _experience_clock_is_paused(self) -> bool:
        return getattr(self, "experience_pause_started_at", None) is not None

    def _enforce_experience_prerequisites(self, now: float) -> bool:
        return True

    def _set_gameplay_hud_active(self, active: bool, now: float) -> None:
        self.gameplay_hud_active = active
        if active:
            return
        self._release_pickup_key()
        self.last_hp_drink_at = now
        self.last_mp_drink_at = now

    def _refresh_gameplay_hud_state(self, now: float) -> bool:
        previous_regions = dict(getattr(self, "bottom_bar_regions", {}))
        previous_track_regions = dict(getattr(self, "bottom_bar_track_regions", {}))
        previous_client_bounds = getattr(self, "bottom_bar_client_bounds", None)
        previous_regions_at = getattr(self, "bottom_bar_regions_at", -999.0)
        previous_layout = getattr(self, "bottom_hud_layout", None)

        regions = self._find_bottom_bar_pair_regions(
            use_cache=False,
            allow_stale_on_failure=False,
        )
        active = "hp" in regions and "mp" in regions
        if active:
            self._set_gameplay_hud_active(True, now)
            return True

        if self._can_keep_recent_bottom_bar_geometry(
            previous_regions,
            previous_track_regions,
            previous_client_bounds,
            previous_regions_at,
            now,
        ):
            self._restore_bottom_bar_geometry(
                previous_regions,
                previous_track_regions,
                previous_client_bounds,
                previous_regions_at,
                previous_layout,
            )
        else:
            self._clear_bottom_bar_geometry()

        self._set_gameplay_hud_active(False, now)
        for bar_type in ("hp", "mp"):
            self._set_bar_detection_debug(
                bar_type,
                source="HUD gate",
                region=None,
                track_region=None,
                percent=None,
                success=False,
                reason="找不到包含 HP/MP 條的遊戲 HUD",
                require_clear_tail=False,
                tail_clear=None,
            )
        return False

    def _restore_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        regions_at: float,
        layout: BottomHudLayout | None,
    ) -> None:
        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = regions_at
        self.bottom_hud_layout = layout
        if client_bounds is not None:
            self._cache_bottom_bar_client_regions(client_bounds)

    def _clear_bottom_bar_geometry(self) -> None:
        self.bottom_bar_regions = {}
        self.bottom_bar_track_regions = {}
        self.bottom_bar_regions_client = {}
        self.bottom_bar_track_regions_client = {}
        self.bottom_bar_client_size = None
        self.bottom_hud_layout = None

    def _cache_bottom_bar_client_regions(self, client_bounds: tuple[int, int, int, int]) -> None:
        client_left, client_top, client_width, client_height = client_bounds
        self.bottom_bar_client_size = (client_width, client_height)
        self.bottom_bar_regions_client = {
            bar_type: self._screen_region_to_client(region, client_left, client_top)
            for bar_type, region in getattr(self, "bottom_bar_regions", {}).items()
        }
        self.bottom_bar_track_regions_client = {
            bar_type: self._screen_region_to_client(region, client_left, client_top)
            for bar_type, region in getattr(self, "bottom_bar_track_regions", {}).items()
        }

    def _screen_region_to_client(
        self,
        region: tuple[int, int, int, int],
        client_left: int,
        client_top: int,
    ) -> tuple[int, int, int, int]:
        left, top, width, height = region
        return left - client_left, top - client_top, width, height

    def _client_region_to_screen(
        self,
        region: tuple[int, int, int, int],
        client_left: int,
        client_top: int,
    ) -> tuple[int, int, int, int]:
        left, top, width, height = region
        return client_left + left, client_top + top, width, height

    def _cached_bottom_bar_screen_regions_for_current_client(
        self,
    ) -> tuple[
        dict[str, tuple[int, int, int, int]],
        dict[str, tuple[int, int, int, int]],
        tuple[int, int, int, int],
    ] | None:
        client_bounds = self._target_client_bounds()
        if client_bounds is None:
            try:
                client_bounds = self._foreground_client_bounds()
            except Exception:
                return None
        if client_bounds is None:
            return None
        client_left, client_top, client_width, client_height = client_bounds
        if getattr(self, "bottom_bar_client_size", None) != (client_width, client_height):
            return None

        client_regions = getattr(self, "bottom_bar_regions_client", {})
        if "hp" not in client_regions or "mp" not in client_regions:
            return None

        regions = {
            bar_type: self._client_region_to_screen(region, client_left, client_top)
            for bar_type, region in client_regions.items()
        }
        track_regions = {
            bar_type: self._client_region_to_screen(region, client_left, client_top)
            for bar_type, region in getattr(self, "bottom_bar_track_regions_client", {}).items()
        }
        return regions, track_regions, client_bounds

    def _reuse_cached_bottom_bar_regions_with_direct_sample(self, now: float) -> bool:
        cached = self._cached_bottom_bar_screen_regions_for_current_client()
        if cached is None:
            return False
        regions, track_regions, client_bounds = cached
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            return False
        saw_non_empty_sample = False
        for bar_type in ("mp", "hp"):
            sample_region = track_regions.get(bar_type) or regions.get(bar_type)
            if sample_region is None:
                return False
            percent, reason, _tail_clear = self._sample_direct_bar_percent_from_region(
                sample_region,
                bar_type,
                require_clear_tail=False,
            )
            if percent is None:
                return False
            if reason != "OK:EmptyTrack":
                saw_non_empty_sample = True
        if not saw_non_empty_sample:
            return False
        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = now
        return True

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
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            return False

        saw_non_empty_sample = False
        for bar_type in ("mp", "hp"):
            try:
                percent, reason, _tail_clear = self._bar_percent_from_region_snapshot(
                    regions[bar_type],
                    bar_type,
                    require_clear_tail=False,
                    track_region=track_regions.get(bar_type),
                )
            except Exception:
                return False
            if percent is None:
                return False
            if reason != "OK:EmptyTrack":
                saw_non_empty_sample = True
        return saw_non_empty_sample

    def _can_keep_current_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        if "hp" not in regions or "mp" not in regions:
            return False
        current_bounds = self._target_client_bounds()
        if current_bounds is None:
            try:
                current_bounds = self._foreground_client_bounds()
            except Exception:
                return False
        if client_bounds is None or client_bounds != current_bounds:
            return False
        return self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds)

    def _can_keep_recent_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        regions_at: float,
        now: float,
    ) -> bool:
        if now - regions_at > RECENT_HUD_GEOMETRY_GRACE_SECONDS:
            return False
        if "hp" not in regions or "mp" not in regions:
            return False
        current_bounds = self._target_client_bounds()
        if current_bounds is None:
            try:
                current_bounds = self._foreground_client_bounds()
            except Exception:
                return False
        if client_bounds is None or client_bounds != current_bounds:
            return False
        return self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds)

    def _bar_region_pair_geometry_is_valid(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]] | None = None,
        client_bounds: tuple[int, int, int, int] | None = None,
    ) -> bool:
        track_regions = track_regions or {}
        hp_region = track_regions.get("hp") or regions.get("hp")
        mp_region = track_regions.get("mp") or regions.get("mp")
        if hp_region is None or mp_region is None:
            return False
        if not self._bar_region_rect_is_valid(hp_region, client_bounds):
            return False
        if not self._bar_region_rect_is_valid(mp_region, client_bounds):
            return False

        hp_left, hp_top, hp_width, hp_height = hp_region
        mp_left, mp_top, mp_width, mp_height = mp_region
        if hp_width <= 0 or hp_height <= 0 or mp_width <= 0 or mp_height <= 0:
            return False
        width_ratio = min(hp_width, mp_width) / max(hp_width, mp_width)
        if width_ratio < BAR_PAIR_REUSE_WIDTH_RATIO_MIN:
            return False
        height_ratio = max(hp_height, mp_height) / max(1, min(hp_height, mp_height))
        if height_ratio > BAR_PAIR_REUSE_HEIGHT_RATIO_MAX:
            return False

        hp_center_y = hp_top + hp_height / 2.0
        mp_center_y = mp_top + mp_height / 2.0
        y_tolerance = max(10.0, max(hp_height, mp_height) * BAR_PAIR_REUSE_MAX_CENTER_Y_DELTA_RATIO)
        if abs(hp_center_y - mp_center_y) > y_tolerance:
            return False

        client_width = client_bounds[2] if client_bounds is not None else max(mp_left + mp_width, hp_left + hp_width)
        min_gap = max(24.0, client_width * BAR_PAIR_REUSE_MIN_GAP_RATIO)
        max_gap = max(min_gap + 1.0, client_width * BAR_PAIR_REUSE_MAX_GAP_RATIO)
        left_gap = mp_left - hp_left
        if left_gap < min_gap or left_gap > max_gap:
            return False
        hp_left_in_client = hp_left - client_bounds[0] if client_bounds is not None else hp_left
        if hp_left_in_client > client_width * (BAR_PAIR_HP_MAX_LEFT_RATIO + 0.08):
            return False
        return True

    def _bar_region_rect_is_valid(
        self,
        region: tuple[int, int, int, int],
        client_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        left, top, width, height = region
        if width <= 0 or height <= 0:
            return False
        if client_bounds is None:
            return True
        client_left, client_top, client_width, client_height = client_bounds
        return (
            left >= client_left
            and top >= client_top
            and left + width <= client_left + client_width
            and top + height <= client_top + client_height
        )

    def _pause_experience_for_missing_hud(self, now: float) -> None:
        self._pause_experience_for_inactive_state(now, "HUD 未出現，保留統計")

    def _pause_experience_for_inactive_state(self, now: float, status: str) -> None:
        if not self.settings.exp_efficiency_enabled:
            return
        effective_now = self._pause_experience_clock(now)
        self._stop_experience_ocr_job()
        if now < self.next_experience_capture_at:
            return
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = status
        self.gui.set_experience_snapshot(snapshot)

    def _update_experience_efficiency(self, now: float) -> None:
        effective_now = self._resume_experience_clock(now)
        if self._process_experience_baseline_calibration(now, effective_now=effective_now):
            return

        if self._process_exp_10m_checkpoint(now, effective_now=effective_now):
            return

        if self._process_experience_ocr_job(now, effective_now=effective_now):
            return

        if self._defer_experience_reading_for_mouse_activity(now, effective_now, phase="ocr_capture"):
            return

        if self._continue_experience_ocr_burst(now, effective_now=effective_now):
            return

        if now < self.next_experience_capture_at:
            return

        if self._start_experience_tooltip_ocr_capture(now, effective_now=effective_now):
            return

        self._start_bottom_experience_ocr_capture(now, effective_now=effective_now)

    def _defer_experience_reading_for_mouse_activity(
        self,
        now: float,
        effective_now: float,
        *,
        phase: str,
    ) -> bool:
        observer = getattr(self, "mouse_activity_observer", None)
        last_activity_at = getattr(observer, "last_activity_at", -999.0) if observer is not None else -999.0
        if self._should_ignore_initial_tooltip_baseline_mouse_activity(phase, last_activity_at):
            return False
        defer_until = float(last_activity_at) + EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS
        if now >= defer_until:
            return False

        self.next_experience_capture_at = max(self.next_experience_capture_at, defer_until)
        snapshot = self.experience_tracker.snapshot(effective_now)
        remaining = max(0.0, defer_until - now)
        remaining_seconds = int(math.ceil(remaining))
        snapshot.status = f"滑鼠操作中，延後 EXP 讀取 {remaining_seconds:d}s"
        status_key = (phase, 0)
        if self._should_publish_experience_mouse_idle_status(now, status_key):
            self.gui.set_experience_snapshot(snapshot)
        self._log_experience_mouse_idle_delay(now, effective_now, phase, last_activity_at, defer_until, snapshot)
        return True

    def _should_publish_experience_mouse_idle_status(self, now: float, status_key: tuple[str, int]) -> bool:
        last_key = getattr(self, "last_experience_mouse_idle_status_key", None)
        last_at = float(getattr(self, "last_experience_mouse_idle_status_at", -999.0))
        if status_key != last_key or now - last_at >= EXPERIENCE_MOUSE_IDLE_STATUS_UPDATE_SECONDS:
            self.last_experience_mouse_idle_status_key = status_key
            self.last_experience_mouse_idle_status_at = now
            return True
        return False

    def _log_experience_mouse_idle_delay(
        self,
        now: float,
        effective_now: float,
        phase: str,
        last_activity_at: float,
        defer_until: float,
        snapshot: ExperienceSnapshot,
    ) -> None:
        if now - float(getattr(self, "last_experience_mouse_idle_delay_log_at", -999.0)) < 0.5:
            return
        self.last_experience_mouse_idle_delay_log_at = now
        log_experience_debug(
            {
                "event": "experience_mouse_idle_delay",
                "phase": phase,
                "source": "mouse",
                "decision": "deferred",
                "completed_at": self._experience_debug_number(now),
                "effective_now": self._experience_debug_number(effective_now),
                "last_mouse_activity_at": self._experience_debug_number(last_activity_at),
                "defer_until": self._experience_debug_number(defer_until),
                "idle_delay_seconds": self._experience_debug_number(EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS),
                "tracker_status": str(getattr(self.experience_tracker, "last_status", snapshot.status)),
                "sample_count": self._experience_debug_number(snapshot.sample_count),
                "sample_attempt_count": self._experience_debug_number(snapshot.sample_attempt_count),
                "sample_accept_count": self._experience_debug_number(snapshot.sample_accept_count),
                "ocr_attempt_count": self._experience_debug_number(snapshot.ocr_attempt_count),
                "ocr_success_count": self._experience_debug_number(snapshot.ocr_success_count),
            }
        )

    def _mark_initial_experience_tooltip_baseline_start(self, now: float) -> None:
        samples = getattr(self.experience_tracker, "samples", [])
        if isinstance(samples, list) and samples:
            self.experience_initial_tooltip_baseline_started_at = None
            return
        self.experience_initial_tooltip_baseline_started_at = float(now)

    def _should_ignore_initial_tooltip_baseline_mouse_activity(
        self,
        phase: str,
        last_activity_at: float,
    ) -> bool:
        if phase != "tooltip_baseline":
            return False
        started_at = getattr(self, "experience_initial_tooltip_baseline_started_at", None)
        if started_at is None:
            return False
        samples = getattr(self.experience_tracker, "samples", [])
        if not isinstance(samples, list) or samples:
            return False
        try:
            return float(last_activity_at) <= float(started_at)
        except (TypeError, ValueError):
            return False

    def _last_experience_tooltip_skip_was_mouse_drift(self) -> bool:
        details = getattr(self, "last_experience_tooltip_capture_skip", None)
        return isinstance(details, dict) and details.get("reason") == "浮動 EXP 擷取期間滑鼠偏移"

    def _record_experience_tooltip_ocr_failure(self) -> int:
        failures = int(getattr(self, "experience_tooltip_ocr_failures", 0)) + 1
        self.experience_tooltip_ocr_failures = failures
        return failures

    def _clear_experience_tooltip_ocr_failures(self) -> None:
        self.experience_tooltip_ocr_failures = 0

    def _start_bottom_experience_ocr_capture(self, now: float, *, effective_now: float) -> bool:
        regions = self._experience_text_regions()
        if not regions:
            self._clear_failed_experience_ocr_signature()
            self._clear_completed_experience_ocr_signature()
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "找不到 EXP 區域，保留統計" if snapshot.sample_count else "找不到 EXP 區域"
            self.gui.set_experience_snapshot(snapshot)
            return False

        images = self._capture_experience_text_images(regions)
        if self._should_use_fast_experience_ocr_path():
            self._submit_experience_ocr_burst(now, [images], effective_now=effective_now, source="bottom")
            return True

        if EXPERIENCE_BURST_CAPTURE_ATTEMPTS <= 1:
            self._submit_experience_ocr_burst(now, [images], effective_now=effective_now, source="bottom")
            return True

        self.experience_ocr_burst = ExperienceOcrBurst(
            started_at=now,
            next_capture_at=now + EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
            regions=regions,
            image_frames=[images],
            capture_count=1,
        )
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = f"擷取經驗樣本中 1/{EXPERIENCE_BURST_CAPTURE_ATTEMPTS}"
        self.gui.set_experience_snapshot(snapshot)
        return True

    def _start_experience_tooltip_ocr_capture(self, now: float, *, effective_now: float) -> bool:
        ocr_image = self._capture_experience_tooltip_image()
        if ocr_image is None:
            self._log_experience_tooltip_capture_skip(
                now,
                effective_now,
                phase="ocr_capture",
            )
            if self._last_experience_tooltip_skip_was_mouse_drift():
                self.next_experience_capture_at = max(
                    self.next_experience_capture_at,
                    now + EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS,
                )
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "滑鼠操作中，延後 EXP 讀取"
                self.gui.set_experience_snapshot(snapshot)
                return True
            return False
        image_signature = self._experience_ocr_image_signature([[ocr_image]])
        continuity_hint = self._experience_ocr_continuity_hint(effective_now)
        if continuity_hint is None:
            future = self.experience_ocr_executor.submit(read_experience_tooltip_in_worker, ocr_image)
        else:
            future = self.experience_ocr_executor.submit(read_experience_tooltip_in_worker, ocr_image, continuity_hint)
        self.experience_ocr_job = ExperienceOcrJob(
            submitted_at=now,
            future=future,
            image_signature=image_signature,
            image_frames=[[ocr_image]],
            source="tooltip",
        )
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = "讀取浮動 EXP"
        self.gui.set_experience_snapshot(snapshot)
        return True

    def _should_use_fast_experience_ocr_path(self) -> bool:
        tracker_samples = getattr(self.experience_tracker, "samples", [])
        if not tracker_samples:
            return False
        return getattr(self, "last_failed_experience_ocr_signature", None) is None

    def _process_experience_baseline_calibration(
        self,
        now: float,
        *,
        effective_now: float | None = None,
    ) -> bool:
        if effective_now is None:
            effective_now = self._experience_effective_time(now)

        if self._process_experience_baseline_ocr_job(now, effective_now=effective_now):
            return True

        if not self._should_start_experience_baseline_calibration(now):
            return False
        if self._defer_experience_reading_for_mouse_activity(now, effective_now, phase="tooltip_baseline"):
            return True
        return self._try_start_experience_tooltip_baseline(now, effective_now)

    def _process_experience_baseline_ocr_job(
        self,
        now: float,
        *,
        effective_now: float,
    ) -> bool:
        job = getattr(self, "experience_baseline_ocr_job", None)
        if job is None:
            return False
        if self._experience_clock_is_paused():
            self._cancel_experience_baseline_calibration(close_ui=True)
            return True
        if not job.future.done():
            elapsed_seconds = max(0.0, now - job.submitted_at)
            if elapsed_seconds >= EXPERIENCE_CAPTURE_INTERVAL_SECONDS:
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = f"浮動 EXP baseline OCR 延遲：{elapsed_seconds:.1f}s"
                self.gui.set_experience_snapshot(snapshot)
            return True

        self.experience_baseline_ocr_job = None
        try:
            reading = job.future.result()
        except Exception as exc:
            log_exception("浮動 EXP baseline OCR 背景工作失敗")
            reading = ExperienceTextReading(reason=f"浮動 EXP baseline OCR 背景工作失敗：{exc}", source="tooltip")
        job_elapsed_ms = max(0.0, now - job.submitted_at) * 1000.0
        log_debug(
            "EXP tooltip baseline OCR job "
            f"elapsed_ms={job_elapsed_ms:.1f} result={'success' if reading.success else 'failure'} "
            f"{self._experience_reading_log_fields(reading)} | reason={reading.reason}"
        )

        if reading.success and reading.current_exp is not None:
            tracker_reading = reading
            self.experience_tracker.record_ocr_result(True)
            accepted = self.experience_tracker.add_reading(
                effective_now,
                tracker_reading.current_exp,
                tracker_reading.percent,
                confidence=tracker_reading.confidence,
            )
            snapshot = self.experience_tracker.snapshot(effective_now)
            if accepted:
                self._record_exp_10m_checkpoint(tracker_reading.current_exp, now)
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "浮動 EXP baseline 已校準"
                self.next_experience_capture_at = now + BAR_CONFIRM_RETRY_DELAY_SECONDS
                self._clear_failed_experience_ocr_signature()
                self.experience_tooltip_baseline_failed = False
                self._log_experience_baseline_calibration_event(
                    phase="ocr_baseline",
                    decision="accepted",
                    completed_at=now,
                    effective_now=effective_now,
                    snapshot=snapshot,
                    reading=tracker_reading,
                    roi_found=True,
                    closed_by_esc=False,
                    close_method="tooltip",
                    job_elapsed_ms=job_elapsed_ms,
                )
                self._clear_experience_baseline_calibration_state()
                self.gui.set_experience_snapshot(snapshot)
                return True

            self._log_experience_sample_rejection(now, self.experience_tracker.last_status, tracker_reading)
            snapshot.status = "浮動 EXP baseline 已拒絕，改用底部 EXP OCR"
            self._log_experience_baseline_calibration_event(
                phase="ocr_baseline",
                decision="rejected",
                completed_at=now,
                effective_now=effective_now,
                snapshot=snapshot,
                reading=tracker_reading,
                roi_found=True,
                closed_by_esc=False,
                close_method="tooltip",
                fallback_reason=self.experience_tracker.last_status,
                job_elapsed_ms=job_elapsed_ms,
            )
            self._finish_failed_experience_baseline_calibration(now)
            self.gui.set_experience_snapshot(snapshot)
            return False

        self.experience_tracker.record_ocr_result(False)
        self._log_experience_ocr_error(now, reading.reason, reading.text)
        snapshot = self.experience_tracker.snapshot(effective_now)
        self.experience_tooltip_baseline_failed = False
        snapshot.status = "浮動 EXP baseline 失敗，等待下一輪 EXP OCR"
        self._log_experience_baseline_calibration_event(
            phase="tooltip_baseline",
            decision="tooltip_retry",
            completed_at=now,
            effective_now=effective_now,
            snapshot=snapshot,
            reading=reading,
            roi_found=True,
            closed_by_esc=False,
            close_method="tooltip",
            fallback_reason=reading.reason,
            job_elapsed_ms=job_elapsed_ms,
        )
        self.gui.set_experience_snapshot(snapshot)
        return False

    def _try_start_experience_tooltip_baseline(self, now: float, effective_now: float) -> bool:
        ocr_image = self._capture_experience_tooltip_image()
        if ocr_image is None:
            self._log_experience_tooltip_capture_skip(
                now,
                effective_now,
                phase="tooltip_baseline",
            )
            return False
        image_signature = self._experience_ocr_image_signature([[ocr_image]])
        future = self.experience_ocr_executor.submit(read_experience_tooltip_in_worker, ocr_image)
        self.experience_baseline_ocr_job = ExperienceOcrJob(
            submitted_at=now,
            future=future,
            image_signature=image_signature,
            image_frames=[[ocr_image]],
            source="tooltip_baseline",
        )
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = "讀取浮動 EXP baseline"
        self.gui.set_experience_snapshot(snapshot)
        self._log_experience_baseline_calibration_event(
            phase="tooltip_baseline",
            decision="captured",
            completed_at=now,
            effective_now=effective_now,
            snapshot=snapshot,
            roi_found=True,
            click_step="tooltip_exp_roi",
            close_method="tooltip",
        )
        return True

    def _process_exp_10m_checkpoint(
        self,
        now: float,
        *,
        effective_now: float | None = None,
    ) -> bool:
        if effective_now is None:
            effective_now = self._experience_effective_time(now)

        if self._process_exp_10m_checkpoint_ocr_job(now, effective_now=effective_now):
            return True

        if not self._should_start_exp_10m_checkpoint(now):
            return False
        if self._defer_experience_reading_for_mouse_activity(now, effective_now, phase="tooltip_checkpoint"):
            return True
        return self._try_start_exp_10m_checkpoint_tooltip(now, effective_now)

    def _process_exp_10m_checkpoint_ocr_job(self, now: float, *, effective_now: float) -> bool:
        job = getattr(self, "experience_10m_checkpoint_ocr_job", None)
        if job is None:
            return False
        if self._experience_clock_is_paused():
            self._fail_exp_10m_checkpoint(now, effective_now, "EXP-10 擷取期間暫停", close_ui=True)
            return True
        if not job.future.done():
            elapsed_seconds = max(0.0, now - job.submitted_at)
            if elapsed_seconds >= EXPERIENCE_CAPTURE_INTERVAL_SECONDS:
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = f"EXP-10 OCR 延遲：{elapsed_seconds:.1f}s"
                self.gui.set_experience_snapshot(snapshot)
            return True

        self.experience_10m_checkpoint_ocr_job = None
        try:
            reading = job.future.result()
        except Exception as exc:
            log_exception("EXP-10 OCR 背景工作失敗")
            reading = ExperienceTextReading(reason=f"EXP-10 OCR 背景工作失敗：{exc}", source="tooltip")
        job_elapsed_ms = max(0.0, now - job.submitted_at) * 1000.0
        log_debug(
            "EXP-10 tooltip OCR job "
            f"elapsed_ms={job_elapsed_ms:.1f} result={'success' if reading.success else 'failure'} "
            f"{self._experience_reading_log_fields(reading)} | reason={reading.reason}"
        )

        if reading.success and reading.current_exp is not None:
            self.experience_tracker.record_ocr_result(True)
            self._record_exp_10m_checkpoint(reading.current_exp, now)
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "EXP-10 已更新" if snapshot.exp_10m_gain is not None else "EXP-10 升級區間略過"
            self._log_exp_10m_checkpoint_event(
                phase="ocr_checkpoint",
                decision="accepted",
                completed_at=now,
                effective_now=effective_now,
                snapshot=snapshot,
                reading=reading,
                roi_found=True,
                close_method="tooltip",
                job_elapsed_ms=job_elapsed_ms,
            )
            self._clear_exp_10m_checkpoint_capture_state()
            self.gui.set_experience_snapshot(snapshot)
            return True

        self.experience_tracker.record_ocr_result(False)
        self._log_experience_ocr_error(now, reading.reason, reading.text)
        snapshot = self.experience_tracker.snapshot(effective_now)
        self.experience_10m_checkpoint_tooltip_failed = False
        self.next_experience_10m_checkpoint_at = now + EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS
        snapshot.status = "浮動 EXP-10 失敗，稍後重試"
        self._log_exp_10m_checkpoint_event(
            phase="tooltip_checkpoint",
            decision="tooltip_retry",
            completed_at=now,
            effective_now=effective_now,
            snapshot=snapshot,
            reading=reading,
            roi_found=True,
            close_method="tooltip",
            fallback_reason=reading.reason,
            job_elapsed_ms=job_elapsed_ms,
        )
        self.gui.set_experience_snapshot(snapshot)
        return True

    def _try_start_exp_10m_checkpoint_tooltip(self, now: float, effective_now: float) -> bool:
        ocr_image = self._capture_experience_tooltip_image()
        if ocr_image is None:
            self._log_experience_tooltip_capture_skip(
                now,
                effective_now,
                phase="tooltip_checkpoint",
            )
            return False
        image_signature = self._experience_ocr_image_signature([[ocr_image]])
        future = self.experience_ocr_executor.submit(read_experience_tooltip_in_worker, ocr_image)
        self.experience_10m_checkpoint_ocr_job = ExperienceOcrJob(
            submitted_at=now,
            future=future,
            image_signature=image_signature,
            image_frames=[[ocr_image]],
            source="tooltip_checkpoint",
        )
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = self._exp_10m_checkpoint_attempt_status("讀取浮動 EXP-10")
        self.gui.set_experience_snapshot(snapshot)
        self._log_exp_10m_checkpoint_event(
            phase="tooltip_checkpoint",
            decision="captured",
            completed_at=now,
            effective_now=effective_now,
            snapshot=snapshot,
            roi_found=True,
            click_step="tooltip_exp_roi",
            close_method="tooltip",
        )
        return True

    def _should_start_exp_10m_checkpoint(self, now: float) -> bool:
        if not getattr(self.settings, "exp_efficiency_enabled", False):
            return False
        if self._experience_clock_is_paused():
            return False
        if not getattr(self, "gameplay_hud_active", False):
            return False
        if getattr(self, "experience_10m_checkpoint_stopped", False):
            return False
        checkpoint_exp = getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None)
        if not isinstance(checkpoint_exp, int):
            return False
        if now < float(getattr(self, "next_experience_10m_checkpoint_at", 0.0)):
            return False
        if getattr(self, "experience_ocr_job", None) is not None:
            return False
        if getattr(self, "experience_ocr_burst", None) is not None:
            return False
        if getattr(self, "experience_baseline_calibration", None) is not None:
            return False
        if getattr(self, "experience_baseline_ocr_job", None) is not None:
            return False
        if getattr(self, "experience_10m_checkpoint_ocr_job", None) is not None:
            return False
        return True

    def _record_exp_10m_checkpoint(self, current_exp: int, now: float) -> None:
        self.experience_tracker.record_exp_10m_checkpoint(current_exp)
        self.next_experience_10m_checkpoint_at = now + EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS
        self.experience_10m_checkpoint_stopped = False
        self.experience_10m_checkpoint_attempts = 0
        self.experience_10m_checkpoint_tooltip_failed = False

    def _seed_exp_10m_checkpoint_if_needed(self, current_exp: int, now: float) -> None:
        if isinstance(getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None), int):
            return
        self._record_exp_10m_checkpoint(current_exp, now)

    def _resume_exp_10m_checkpoint_schedule(self, now: float) -> None:
        self.experience_10m_checkpoint_stopped = False
        self.experience_10m_checkpoint_attempts = 0
        self.experience_10m_checkpoint_tooltip_failed = False
        if isinstance(getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None), int):
            self.next_experience_10m_checkpoint_at = now + EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS

    def _reset_exp_10m_checkpoint_state(self) -> None:
        self._cancel_exp_10m_checkpoint(close_ui=True)
        self.next_experience_10m_checkpoint_at = 0.0
        self.experience_10m_checkpoint_stopped = False
        self.experience_10m_checkpoint_attempts = 0
        self.experience_10m_checkpoint_tooltip_failed = False

    def _exp_10m_checkpoint_attempt_status(self, message: str, attempt: int | None = None) -> str:
        attempt = int(attempt if attempt is not None else getattr(self, "experience_10m_checkpoint_attempts", 0))
        if attempt <= 1:
            return message
        return f"{message}（第 {attempt}/{EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS} 次）"

    def _retry_or_stop_exp_10m_checkpoint_after_ocr_failure(
        self,
        now: float,
        effective_now: float,
        reason: str,
    ) -> None:
        self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
        attempt = max(1, int(getattr(self, "experience_10m_checkpoint_attempts", 0)))
        self._cancel_exp_10m_checkpoint(close_ui=False)
        if attempt < EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS:
            self.experience_10m_checkpoint_stopped = False
            self.next_experience_10m_checkpoint_at = now + EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            next_attempt = attempt + 1
            snapshot.status = (
                f"EXP-10 OCR 失敗，10 秒後重試"
                f"（第 {next_attempt}/{EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS} 次）"
            )
            self.gui.set_experience_snapshot(snapshot)
            return

        self.experience_10m_checkpoint_stopped = True
        self.next_experience_10m_checkpoint_at = 0.0
        self.experience_10m_checkpoint_attempts = 0
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = (
            f"EXP-10 OCR 失敗已達 {EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS} 次，保留上一筆統計"
        )
        self.gui.set_experience_snapshot(snapshot)

    def _fail_exp_10m_checkpoint(
        self,
        now: float,
        effective_now: float,
        reason: str,
        *,
        close_ui: bool,
    ) -> None:
        if close_ui:
            with contextlib.suppress(Exception):
                self._close_experience_baseline_calibration_ui()
        self._log_exp_10m_checkpoint_event(
            phase=getattr(getattr(self, "experience_10m_checkpoint_capture", None), "phase", "failed"),
            decision="fallback",
            completed_at=now,
            effective_now=effective_now,
            snapshot=self.experience_tracker.snapshot(effective_now),
            fallback_reason=reason,
            closed_by_esc=close_ui,
            close_method="",
        )
        self._stop_exp_10m_checkpoint(now, effective_now, reason)

    def _stop_exp_10m_checkpoint(self, now: float, effective_now: float, reason: str) -> None:
        self._cancel_exp_10m_checkpoint(close_ui=False)
        self.experience_10m_checkpoint_stopped = True
        self.next_experience_10m_checkpoint_at = 0.0
        self.experience_10m_checkpoint_attempts = 0
        if hasattr(self.experience_tracker, "exp_10m_gain"):
            self.experience_tracker.exp_10m_gain = None
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = f"EXP-10 已停止：{reason}"
        self.gui.set_experience_snapshot(snapshot)

    def _clear_exp_10m_checkpoint_capture_state(self) -> None:
        self._restore_experience_baseline_cursor()
        self.experience_10m_checkpoint_capture = None

    def _cancel_exp_10m_checkpoint(self, *, close_ui: bool) -> None:
        job = getattr(self, "experience_10m_checkpoint_ocr_job", None)
        if job is not None:
            job.future.cancel()
            self.experience_10m_checkpoint_ocr_job = None
        state = getattr(self, "experience_10m_checkpoint_capture", None)
        if close_ui and state is not None and state.opened_ui:
            with contextlib.suppress(Exception):
                self._close_experience_baseline_calibration_ui()
        self._clear_exp_10m_checkpoint_capture_state()

    def _log_exp_10m_checkpoint_event(
        self,
        *,
        phase: str,
        decision: str,
        completed_at: float,
        effective_now: float,
        snapshot: ExperienceSnapshot,
        reading: ExperienceTextReading | None = None,
        roi_found: bool = False,
        closed_by_esc: bool = False,
        click_step: str = "",
        fallback_reason: str = "",
        close_method: str = "",
        job_elapsed_ms: float | None = None,
    ) -> None:
        log_experience_debug(
            {
                "event": "experience_10m_checkpoint",
                "phase": phase,
                "source": reading.source if reading is not None and reading.source else close_method or "tooltip",
                "roi_found": bool(roi_found),
                "click_step": click_step,
                "closed_by_esc": bool(closed_by_esc),
                "close_method": close_method,
                "decision": decision,
                "fallback_reason": fallback_reason,
                "completed_at": self._experience_debug_number(completed_at),
                "effective_now": self._experience_debug_number(effective_now),
                "job_elapsed_ms": self._experience_debug_number(job_elapsed_ms),
                "success": bool(reading.success) if reading is not None else False,
                "text": reading.text if reading is not None else "",
                "raw_current_exp": reading.current_exp if reading is not None else None,
                "current_exp": reading.current_exp if reading is not None else None,
                "checkpoint_exp": self._experience_debug_number(
                    getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None)
                ),
                "exp_10m_gain": self._experience_debug_number(snapshot.exp_10m_gain),
                "confidence": self._experience_debug_number(reading.confidence if reading is not None else None),
                "reason": reading.reason if reading is not None else fallback_reason,
                "tracker_status": str(getattr(self.experience_tracker, "last_status", snapshot.status)),
                "sample_count": self._experience_debug_number(snapshot.sample_count),
                "ocr_attempt_count": self._experience_debug_number(snapshot.ocr_attempt_count),
                "ocr_success_count": self._experience_debug_number(snapshot.ocr_success_count),
            }
        )

    def _should_start_experience_baseline_calibration(self, now: float) -> bool:
        if not getattr(self.settings, "exp_efficiency_enabled", False):
            return False
        if self._experience_clock_is_paused():
            return False
        if not getattr(self, "gameplay_hud_active", False):
            return False
        samples = getattr(self.experience_tracker, "samples", [])
        if not isinstance(samples, list) or samples:
            return False
        if getattr(self, "experience_ocr_job", None) is not None:
            return False
        if getattr(self, "experience_ocr_burst", None) is not None:
            return False
        if getattr(self, "experience_baseline_ocr_job", None) is not None:
            return False
        if int(getattr(self, "experience_baseline_calibration_attempts", 0)) >= EXPERIENCE_BASELINE_CALIBRATION_MAX_ATTEMPTS:
            return False
        if now < float(getattr(self, "next_experience_baseline_calibration_at", 0.0)):
            return False
        return True

    def _capture_foreground_client_image(self) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        bounds = self._foreground_client_bounds()
        left, top, width, height = bounds
        image = np.asarray(
            self.sct.grab({"left": left, "top": top, "width": width, "height": height})
        ).copy()
        return image, bounds

    def _locate_experience_menu_button(self, image: np.ndarray) -> tuple[int, int] | None:
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return None
        crop_left = round(width * 0.45)
        crop_top = round(height * 0.88)
        crop_right = round(width * 0.88)
        crop_bottom = round(height * 0.995)
        candidates = self._blue_button_components(
            image[crop_top:crop_bottom, crop_left:crop_right],
            offset=(crop_left, crop_top),
            min_width=max(48, round(width * 0.035)),
            min_height=max(22, round(height * 0.025)),
        )
        if not candidates:
            return None
        target_x = width * 0.665
        target_y = height * 0.955
        best = min(
            candidates,
            key=lambda rect: (
                abs((rect[0] + rect[2] / 2.0) - target_x) / max(1.0, width)
                + abs((rect[1] + rect[3] / 2.0) - target_y) / max(1.0, height),
                -rect[2] * rect[3],
            ),
        )
        return self._rect_center(best)

    def _locate_experience_ability_button(self, image: np.ndarray) -> tuple[int, int] | None:
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return None
        crop_left = round(width * 0.55)
        crop_top = round(height * 0.45)
        crop_right = round(width * 0.82)
        crop_bottom = round(height * 0.93)
        candidates = self._blue_button_components(
            image[crop_top:crop_bottom, crop_left:crop_right],
            offset=(crop_left, crop_top),
            min_width=max(54, round(width * 0.04)),
            min_height=max(24, round(height * 0.025)),
        )
        if len(candidates) < 3:
            return None
        candidates.sort(key=lambda rect: (rect[1], rect[0]))
        stack = self._largest_vertical_button_stack(candidates)
        if len(stack) < 3:
            return None
        return self._rect_center(sorted(stack, key=lambda rect: rect[1])[2])

    def _locate_stat_window_exp_roi(self, image: np.ndarray) -> tuple[int, int, int, int] | None:
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return None
        crop_left = 0
        crop_top = 0
        crop_right = width
        crop_bottom = height
        crop = image[crop_top:crop_bottom, crop_left:crop_right]
        exp_label = self._locate_stat_window_exp_label_by_fixed_template(image)
        if exp_label is None:
            labels = self._stat_window_green_label_components(crop, offset=(crop_left, crop_top))
            exp_label = self._locate_stat_window_exp_label_by_template(image, labels)
            if exp_label is None:
                label_stack = self._largest_vertical_button_stack(labels, x_tolerance=max(24, round(width * 0.02)))
                if len(label_stack) < 7:
                    return None
                exp_label = sorted(label_stack, key=lambda rect: rect[1])[6]
        return self._stat_window_value_roi_from_label(image, exp_label)

    def _stat_window_value_roi_from_label(
        self,
        image: np.ndarray,
        exp_label: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        height, width = image.shape[:2]
        row_top = max(0, exp_label[1] - max(2, round(exp_label[3] * 0.12)))
        row_bottom = min(height, exp_label[1] + exp_label[3] + max(2, round(exp_label[3] * 0.12)))
        value_left = min(width - 1, exp_label[0] + exp_label[2] + max(4, round(exp_label[3] * 0.25)))
        value_right = self._stat_window_white_value_row_right(image, value_left, row_top, row_bottom)
        if value_right is None:
            value_right = min(width, value_left + max(120, round(width * 0.14)))
        roi_width = max(1, value_right - value_left)
        roi_height = max(1, row_bottom - row_top)
        if roi_width < max(60, round(width * 0.04)) or roi_height < 8:
            return None
        return value_left, row_top, roi_width, roi_height

    def _locate_stat_window_exp_label_by_fixed_template(
        self,
        image: np.ndarray,
    ) -> tuple[int, int, int, int] | None:
        template = self._stat_window_fixed_exp_label_template()
        if template is None or image.size == 0:
            return None
        search = image[:, :, :3]
        template_height, template_width = template.shape[:2]
        if search.shape[0] < template_height or search.shape[1] < template_width:
            return None
        match = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        if match.size == 0:
            return None
        _min_value, max_value, _min_location, max_location = cv2.minMaxLoc(match)
        if max_value < STAT_WINDOW_EXP_LABEL_TEMPLATE_MATCH_THRESHOLD:
            return None
        x, y = max_location
        return int(x), int(y), int(template_width), int(template_height)

    def _stat_window_fixed_exp_label_template(self) -> np.ndarray | None:
        global _STAT_WINDOW_EXP_LABEL_TEMPLATE
        if _STAT_WINDOW_EXP_LABEL_TEMPLATE is not None:
            return _STAT_WINDOW_EXP_LABEL_TEMPLATE
        try:
            decoded = cv2.imread(str(STAT_WINDOW_EXP_LABEL_TEMPLATE_PATH), cv2.IMREAD_COLOR)
        except Exception:
            return None
        if decoded is None or decoded.size == 0:
            return None
        _STAT_WINDOW_EXP_LABEL_TEMPLATE = decoded
        return _STAT_WINDOW_EXP_LABEL_TEMPLATE

    def _locate_stat_window_exp_label_by_template(
        self,
        image: np.ndarray,
        labels: list[tuple[int, int, int, int]],
    ) -> tuple[int, int, int, int] | None:
        best: tuple[float, tuple[int, int, int, int] | None] = (0.0, None)
        second_best = 0.0
        for rect in labels:
            x, y, width, height = rect
            crop = image[y : y + height, x : x + width]
            score = self._stat_window_exp_label_template_score(crop)
            if score > best[0]:
                second_best = best[0]
                best = (score, rect)
            elif score > second_best:
                second_best = score
        if best[0] < 0.55:
            return None
        if best[0] < 0.85 and best[0] - second_best < 0.12:
            return None
        return best[1]

    def _stat_window_exp_label_template_score(self, crop: np.ndarray) -> float:
        if crop.size == 0:
            return 0.0
        height, width = crop.shape[:2]
        if width < 24 or height < 12:
            return 0.0
        text_mask = self._stat_window_label_text_mask(crop)
        if text_mask.mean() < 0.01:
            return 0.0
        ys, xs = np.where(text_mask > 0)
        if xs.size == 0 or ys.size == 0:
            return 0.0
        text_width_ratio = (int(xs.max()) - int(xs.min()) + 1) / max(1, width)
        if text_width_ratio < 0.34:
            return 0.0
        match_score = 0.0
        for template in self._stat_window_exp_label_templates(width, height):
            match = cv2.matchTemplate(
                text_mask.astype(np.float32),
                template.astype(np.float32),
                cv2.TM_CCOEFF_NORMED,
            )
            if match.size:
                match_score = max(match_score, float(match[0, 0]))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(text_mask, connectivity=8)
        component_count = 0
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area >= max(2, height // 8):
                component_count += 1
        feature_bonus = 0.0
        if 0.42 <= text_width_ratio <= 0.86:
            feature_bonus += 0.12
        if 2 <= component_count <= 5:
            feature_bonus += 0.08
        return max(0.0, match_score) * 0.8 + feature_bonus

    def _stat_window_label_text_mask(self, crop: np.ndarray) -> np.ndarray:
        bgr = crop[:, :, :3].astype(np.float32)
        luminance = bgr[:, :, 2] * 0.299 + bgr[:, :, 1] * 0.587 + bgr[:, :, 0] * 0.114
        chroma = np.max(bgr, axis=2) - np.min(bgr, axis=2)
        mask = ((luminance > 170.0) & (chroma < 95.0)).astype(np.uint8) * 255
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), dtype=np.uint8))

    def _stat_window_exp_label_templates(self, width: int, height: int) -> list[np.ndarray]:
        templates: list[np.ndarray] = []
        base = min(width / 70.0, height / 28.0)
        for scale_factor in (0.56, 0.62, 0.70):
            for y_ratio in (0.74, 0.80, 0.88):
                template = np.zeros((height, width), dtype=np.uint8)
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = max(0.35, base * scale_factor)
                thickness = max(1, round(height / 16))
                text_width, text_height = cv2.getTextSize("EXP", font, scale, thickness)[0]
                x = max(0, round((width - text_width) * 0.18))
                y = min(height - 2, max(text_height + 1, round(height * y_ratio)))
                cv2.putText(template, "EXP", (x, y), font, scale, 255, thickness, cv2.LINE_AA)
                templates.append(template)
        return templates

    def _blue_button_components(
        self,
        image: np.ndarray,
        *,
        offset: tuple[int, int],
        min_width: int,
        min_height: int,
    ) -> list[tuple[int, int, int, int]]:
        if image.size == 0:
            return []
        bgr = image[:, :, :3].astype(np.int16)
        blue = bgr[:, :, 0]
        green = bgr[:, :, 1]
        red = bgr[:, :, 2]
        mask = (blue > 105) & (green > 85) & (red < 150) & (blue > red + 35)
        kernel = np.ones((max(3, min_height // 3), max(9, min_width // 4)), dtype=np.uint8)
        return self._mask_components(mask, offset=offset, kernel=kernel, min_width=min_width, min_height=min_height)

    def _stat_window_green_label_components(
        self,
        image: np.ndarray,
        *,
        offset: tuple[int, int],
    ) -> list[tuple[int, int, int, int]]:
        if image.size == 0:
            return []
        bgr = image[:, :, :3].astype(np.int16)
        blue = bgr[:, :, 0]
        green = bgr[:, :, 1]
        red = bgr[:, :, 2]
        mask = (green > 135) & (red > 70) & (blue < 145) & (green > blue + 35)
        min_width = max(34, round(image.shape[1] * 0.025))
        min_height = max(14, round(image.shape[0] * 0.02))
        kernel = np.ones((max(3, min_height // 3), max(8, min_width // 4)), dtype=np.uint8)
        return self._mask_components(mask, offset=offset, kernel=kernel, min_width=min_width, min_height=min_height)

    def _mask_components(
        self,
        mask: np.ndarray,
        *,
        offset: tuple[int, int],
        kernel: np.ndarray,
        min_width: int,
        min_height: int,
    ) -> list[tuple[int, int, int, int]]:
        if mask.size == 0:
            return []
        prepared = (mask.astype(np.uint8) * 255)
        prepared = cv2.morphologyEx(prepared, cv2.MORPH_CLOSE, kernel)
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(prepared, connectivity=8)
        components: list[tuple[int, int, int, int]] = []
        offset_x, offset_y = offset
        for index in range(1, count):
            x = int(stats[index, cv2.CC_STAT_LEFT])
            y = int(stats[index, cv2.CC_STAT_TOP])
            width = int(stats[index, cv2.CC_STAT_WIDTH])
            height = int(stats[index, cv2.CC_STAT_HEIGHT])
            area = int(stats[index, cv2.CC_STAT_AREA])
            if width < min_width or height < min_height:
                continue
            if area < max(1, width * height // 5):
                continue
            components.append((offset_x + x, offset_y + y, width, height))
        return components

    def _largest_vertical_button_stack(
        self,
        rects: list[tuple[int, int, int, int]],
        *,
        x_tolerance: int = 48,
    ) -> list[tuple[int, int, int, int]]:
        if not rects:
            return []
        best: list[tuple[int, int, int, int]] = []
        for anchor in rects:
            anchor_center = anchor[0] + anchor[2] / 2.0
            group = [
                rect
                for rect in rects
                if abs((rect[0] + rect[2] / 2.0) - anchor_center) <= x_tolerance
            ]
            if len(group) > len(best):
                best = group
        return best

    def _stat_window_white_value_row_right(
        self,
        image: np.ndarray,
        value_left: int,
        row_top: int,
        row_bottom: int,
    ) -> int | None:
        row = image[row_top:row_bottom, value_left:]
        if row.size == 0:
            return None
        bgr = row[:, :, :3].astype(np.float32)
        luminance = bgr[:, :, 2] * 0.299 + bgr[:, :, 1] * 0.587 + bgr[:, :, 0] * 0.114
        chroma = np.max(bgr, axis=2) - np.min(bgr, axis=2)
        mask = (luminance > 170.0) & (chroma < 70.0)
        column_hits = mask.mean(axis=0) >= 0.35
        runs = self._boolean_runs(column_hits)
        if not runs:
            return None
        valid_runs = [run for run in runs if run[1] - run[0] >= 40]
        if not valid_runs:
            return None
        run = valid_runs[0]
        return value_left + int(run[1])

    def _rect_center(self, rect: tuple[int, int, int, int]) -> tuple[int, int]:
        return int(rect[0] + rect[2] / 2.0), int(rect[1] + rect[3] / 2.0)

    def _boolean_runs(self, values: np.ndarray) -> list[tuple[int, int]]:
        if values.size == 0:
            return []
        padded = np.concatenate(([False], values.astype(bool), [False]))
        changes = np.flatnonzero(padded[1:] != padded[:-1])
        return [(int(start), int(end)) for start, end in zip(changes[::2], changes[1::2])]

    def _click_experience_baseline_client_point(self, x: int, y: int) -> None:
        hwnd = user32.GetForegroundWindow()
        click_client_point(int(hwnd), int(x), int(y), preserve_cursor_position=True)

    def _move_cursor_for_experience_baseline_capture(self) -> None:
        if getattr(self, "experience_baseline_cursor_position", None) is not None:
            return
        try:
            original_position = get_cursor_position()
            hwnd = self._experience_baseline_target_hwnd()
            width, height = window_client_size(hwnd)
            if width <= 0 or height <= 0:
                return
            screen_x, screen_y = client_to_screen_point(
                hwnd,
                max(0, min(width - 1, 8)),
                max(0, height - 8),
            )
            set_cursor_position(screen_x, screen_y)
            self.experience_baseline_cursor_position = original_position
        except Exception as exc:
            log_debug(f"EXP baseline cursor move skipped: {exc}")

    def _experience_baseline_target_hwnd(self) -> int:
        target_provider = getattr(self, "target_window_provider", None)
        if target_provider is not None:
            try:
                hwnd = int(target_provider() or 0)
                if hwnd:
                    self.last_target_hwnd = hwnd
                    return hwnd
            except Exception:
                pass
        hwnd = int(getattr(self, "last_target_hwnd", 0) or 0)
        if hwnd:
            return hwnd
        return int(user32.GetForegroundWindow() or 0)

    def _restore_experience_baseline_cursor(self) -> None:
        original_position = getattr(self, "experience_baseline_cursor_position", None)
        self.experience_baseline_cursor_position = None
        if original_position is None:
            return
        with contextlib.suppress(Exception):
            set_cursor_position(*original_position)

    def _close_experience_baseline_calibration_ui(self) -> None:
        return None

    def _toggle_experience_stat_window(self) -> bool:
        return False

    def _fail_experience_baseline_calibration(
        self,
        now: float,
        effective_now: float,
        reason: str,
        *,
        close_ui: bool,
    ) -> None:
        if close_ui:
            with contextlib.suppress(Exception):
                self._close_experience_baseline_calibration_ui()
        snapshot = self.experience_tracker.snapshot(effective_now)
        if snapshot.sample_count == 0:
            snapshot.status = f"{reason}，改用底部 EXP OCR"
        self._log_experience_baseline_calibration_event(
            phase=getattr(getattr(self, "experience_baseline_calibration", None), "phase", "failed"),
            decision="fallback",
            completed_at=now,
            effective_now=effective_now,
            snapshot=snapshot,
            fallback_reason=reason,
            closed_by_esc=close_ui,
            close_method="",
        )
        self._finish_failed_experience_baseline_calibration(now)
        self.gui.set_experience_snapshot(snapshot)

    def _finish_failed_experience_baseline_calibration(self, now: float) -> None:
        self._clear_experience_baseline_calibration_state()
        self.next_experience_baseline_calibration_at = now + EXPERIENCE_BASELINE_CALIBRATION_COOLDOWN_SECONDS
        self.next_experience_capture_at = 0.0

    def _clear_experience_baseline_calibration_state(self) -> None:
        self._restore_experience_baseline_cursor()
        self.experience_baseline_calibration = None

    def _cancel_experience_baseline_calibration(self, *, close_ui: bool) -> None:
        job = getattr(self, "experience_baseline_ocr_job", None)
        if job is not None:
            job.future.cancel()
            self.experience_baseline_ocr_job = None
        state = getattr(self, "experience_baseline_calibration", None)
        if close_ui and state is not None and state.opened_ui:
            with contextlib.suppress(Exception):
                self._close_experience_baseline_calibration_ui()
        self._clear_experience_baseline_calibration_state()

    def _reset_experience_baseline_calibration_attempts(self) -> None:
        self._cancel_experience_baseline_calibration(close_ui=True)
        self.experience_baseline_calibration_attempts = 0
        self.next_experience_baseline_calibration_at = 0.0
        self.experience_tooltip_baseline_failed = False

    def _log_experience_baseline_calibration_event(
        self,
        *,
        phase: str,
        decision: str,
        completed_at: float,
        effective_now: float,
        snapshot: ExperienceSnapshot,
        reading: ExperienceTextReading | None = None,
        roi_found: bool = False,
        closed_by_esc: bool = False,
        click_step: str = "",
        fallback_reason: str = "",
        close_method: str = "",
        job_elapsed_ms: float | None = None,
    ) -> None:
        log_experience_debug(
            {
                "event": "experience_baseline_calibration",
                "phase": phase,
                "source": reading.source if reading is not None and reading.source else close_method or "tooltip",
                "roi_found": bool(roi_found),
                "click_step": click_step,
                "closed_by_esc": bool(closed_by_esc),
                "close_method": close_method,
                "decision": decision,
                "fallback_reason": fallback_reason,
                "completed_at": self._experience_debug_number(completed_at),
                "effective_now": self._experience_debug_number(effective_now),
                "job_elapsed_ms": self._experience_debug_number(job_elapsed_ms),
                "success": bool(reading.success) if reading is not None else False,
                "text": reading.text if reading is not None else "",
                "current_exp": reading.current_exp if reading is not None else None,
                "percent": self._experience_debug_number(reading.percent if reading is not None else None),
                "confidence": self._experience_debug_number(reading.confidence if reading is not None else None),
                "reason": reading.reason if reading is not None else fallback_reason,
                "tracker_status": str(getattr(self.experience_tracker, "last_status", snapshot.status)),
                "sample_count": self._experience_debug_number(snapshot.sample_count),
                "sample_attempt_count": self._experience_debug_number(snapshot.sample_attempt_count),
                "sample_accept_count": self._experience_debug_number(snapshot.sample_accept_count),
                "ocr_attempt_count": self._experience_debug_number(snapshot.ocr_attempt_count),
                "ocr_success_count": self._experience_debug_number(snapshot.ocr_success_count),
                "xp_per_5m": self._experience_debug_number(snapshot.xp_per_5m),
                "xp_per_10m": self._experience_debug_number(snapshot.xp_per_10m),
                "xp_per_hour": self._experience_debug_number(snapshot.xp_per_hour),
                "eta_seconds": self._experience_debug_number(snapshot.eta_seconds),
                "rate_confidence": self._experience_debug_number(snapshot.rate_confidence),
            }
        )

    def _continue_experience_ocr_burst(self, now: float, *, effective_now: float | None = None) -> bool:
        burst = getattr(self, "experience_ocr_burst", None)
        if burst is None:
            return False
        if self._experience_clock_is_paused():
            self._stop_experience_ocr_job()
            return True
        if effective_now is None:
            effective_now = self._experience_effective_time(now)
        if now < burst.next_capture_at:
            return True

        burst.image_frames.append(self._capture_experience_text_images(burst.regions))
        burst.capture_count += 1
        if burst.capture_count < EXPERIENCE_BURST_CAPTURE_ATTEMPTS:
            burst.next_capture_at = now + EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = f"擷取經驗樣本中 {burst.capture_count}/{EXPERIENCE_BURST_CAPTURE_ATTEMPTS}"
            self.gui.set_experience_snapshot(snapshot)
            return True

        self.experience_ocr_burst = None
        self._submit_experience_ocr_burst(now, burst.image_frames, effective_now=effective_now, source="bottom")
        return True

    def _capture_experience_text_image(self, region: tuple[int, int, int, int]) -> np.ndarray:
        left, top, width, height = region
        return np.asarray(self.sct.grab({"left": left, "top": top, "width": width, "height": height})).copy()

    def _capture_experience_tooltip_image(self) -> ExperienceOcrImage | None:
        self.last_experience_tooltip_capture_skip = None
        self.last_experience_tooltip_capture_debug = None
        cursor_point = self._experience_tooltip_cursor_point()
        if cursor_point is None:
            self._remember_experience_tooltip_capture_skip("找不到 EXP track 游標目標")
            return None
        roi = self._experience_tooltip_roi(cursor_point)
        if roi is None:
            self._remember_experience_tooltip_capture_skip("浮動 EXP ROI 無效", cursor_point=cursor_point)
            return None
        capture_debug: dict[str, object] = {
            "cursor_point": cursor_point,
            "roi": roi,
            "attempts": [],
        }
        try:
            with temporary_mouse_input_lock() as original_cursor_position:
                capture_debug["original_cursor_position"] = original_cursor_position
                attempts = max(1, EXPERIENCE_TOOLTIP_CAPTURE_ATTEMPTS)
                for attempt_index in range(attempts):
                    set_cursor_position(*cursor_point)
                    sleep_seconds = (
                        EXPERIENCE_TOOLTIP_SETTLE_SECONDS
                        if attempt_index == 0
                        else EXPERIENCE_TOOLTIP_RETRY_SETTLE_SECONDS
                    )
                    sleep_while_pumping_messages(sleep_seconds)
                    cursor_before_grab = get_cursor_position()
                    attempt_debug = {
                        "attempt": attempt_index + 1,
                        "cursor_before_grab": cursor_before_grab,
                    }
                    capture_debug["attempts"].append(attempt_debug)
                    if not self._cursor_is_near(cursor_before_grab, cursor_point):
                        attempt_debug["decision"] = "cursor_moved_before_grab"
                        continue
                    image = self._capture_experience_text_image(roi)
                    cursor_after_grab = get_cursor_position()
                    attempt_debug["cursor_after_grab"] = cursor_after_grab
                    if not self._cursor_is_near(cursor_after_grab, cursor_point):
                        attempt_debug["decision"] = "cursor_moved_after_grab"
                        continue
                    attempt_debug["decision"] = "captured"
                    self.last_experience_tooltip_capture_debug = capture_debug
                    return ExperienceOcrImage(image, source_id="tooltip", roi_offset=roi)
        except Exception as exc:
            self._remember_experience_tooltip_capture_skip(
                f"浮動 EXP 擷取例外：{exc}",
                cursor_point=cursor_point,
                roi=roi,
            )
            log_debug(f"EXP tooltip capture skipped: {exc}")
            return None
        self._remember_experience_tooltip_capture_skip(
            "浮動 EXP 擷取期間滑鼠偏移",
            cursor_point=cursor_point,
            roi=roi,
            capture_debug=capture_debug,
        )
        return None

    def _remember_experience_tooltip_capture_skip(
        self,
        reason: str,
        *,
        cursor_point: tuple[int, int] | None = None,
        roi: tuple[int, int, int, int] | None = None,
        capture_debug: dict[str, object] | None = None,
    ) -> None:
        layout = getattr(self, "bottom_hud_layout", None)
        exp_track = getattr(layout, "exp_track_region", None) if layout is not None else None
        track_regions = getattr(self, "bottom_bar_track_regions", {})
        track_keys = sorted(str(key) for key in track_regions) if isinstance(track_regions, dict) else []
        self.last_experience_tooltip_capture_skip = {
            "reason": reason,
            "cursor_point": cursor_point,
            "roi": roi,
            "exp_track_region": exp_track,
            "has_bottom_hud_layout": layout is not None,
            "bottom_bar_track_keys": track_keys,
            "capture_debug": capture_debug,
        }

    def _log_experience_tooltip_capture_skip(
        self,
        now: float,
        effective_now: float,
        *,
        phase: str,
    ) -> None:
        details = getattr(self, "last_experience_tooltip_capture_skip", None)
        if not isinstance(details, dict):
            details = {"reason": "浮動 EXP 擷取未取得影像"}
        snapshot = self.experience_tracker.snapshot(effective_now)
        log_experience_debug(
            {
                "event": "experience_tooltip_capture",
                "phase": phase,
                "source": "tooltip",
                "decision": "skipped",
                "reason": details.get("reason", ""),
                "completed_at": self._experience_debug_number(now),
                "effective_now": self._experience_debug_number(effective_now),
                "cursor_point": list(details["cursor_point"]) if details.get("cursor_point") is not None else None,
                "roi": list(details["roi"]) if details.get("roi") is not None else None,
                "exp_track_region": (
                    list(details["exp_track_region"]) if details.get("exp_track_region") is not None else None
                ),
                "has_bottom_hud_layout": bool(details.get("has_bottom_hud_layout")),
                "bottom_bar_track_keys": details.get("bottom_bar_track_keys", []),
                "capture_debug": self._experience_tooltip_capture_debug_payload(details.get("capture_debug")),
                "tracker_status": str(getattr(self.experience_tracker, "last_status", snapshot.status)),
                "sample_count": self._experience_debug_number(snapshot.sample_count),
                "sample_attempt_count": self._experience_debug_number(snapshot.sample_attempt_count),
                "sample_accept_count": self._experience_debug_number(snapshot.sample_accept_count),
                "ocr_attempt_count": self._experience_debug_number(snapshot.ocr_attempt_count),
                "ocr_success_count": self._experience_debug_number(snapshot.ocr_success_count),
            }
        )

    def _cursor_is_near(self, actual: tuple[int, int], expected: tuple[int, int]) -> bool:
        return (
            abs(int(actual[0]) - int(expected[0])) <= EXPERIENCE_TOOLTIP_CURSOR_TOLERANCE_PIXELS
            and abs(int(actual[1]) - int(expected[1])) <= EXPERIENCE_TOOLTIP_CURSOR_TOLERANCE_PIXELS
        )

    def _experience_tooltip_capture_debug_payload(self, value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None

        def point_payload(point: object) -> list[int] | None:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                return None
            return [int(point[0]), int(point[1])]

        attempts = []
        for attempt in value.get("attempts", []):
            if not isinstance(attempt, dict):
                continue
            attempts.append(
                {
                    "attempt": self._experience_debug_number(attempt.get("attempt")),
                    "decision": str(attempt.get("decision", "")),
                    "cursor_before_grab": point_payload(attempt.get("cursor_before_grab")),
                    "cursor_after_grab": point_payload(attempt.get("cursor_after_grab")),
                }
            )
        return {
            "original_cursor_position": point_payload(value.get("original_cursor_position")),
            "cursor_point": point_payload(value.get("cursor_point")),
            "roi": list(value["roi"]) if isinstance(value.get("roi"), (tuple, list)) else None,
            "attempts": attempts,
        }

    def _experience_tooltip_cursor_point(self) -> tuple[int, int] | None:
        layout = getattr(self, "bottom_hud_layout", None)
        exp_track = getattr(layout, "exp_track_region", None) if layout is not None else None
        if exp_track is None:
            track_regions = getattr(self, "bottom_bar_track_regions", {})
            if isinstance(track_regions, dict):
                exp_track = track_regions.get("exp")
        if exp_track is None:
            return None
        left, top, width, height = exp_track
        if width <= 0 or height <= 0:
            return None
        x = left + width - max(2, round(height * EXPERIENCE_TOOLTIP_CURSOR_RIGHT_PADDING_RATIO))
        y = top + round(height * 0.50)
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        if client_width <= 0 or client_height <= 0:
            return None
        return (
            max(client_left, min(client_left + client_width - 1, int(x))),
            max(client_top, min(client_top + client_height - 1, int(y))),
        )

    def _experience_tooltip_roi(self, cursor_point: tuple[int, int]) -> tuple[int, int, int, int] | None:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        if client_width <= 0 or client_height <= 0:
            return None
        left = cursor_point[0] + EXPERIENCE_TOOLTIP_ROI_OFFSET_X
        top = cursor_point[1] + EXPERIENCE_TOOLTIP_ROI_OFFSET_Y
        return self._clip_rect_to_client(
            left,
            top,
            EXPERIENCE_TOOLTIP_ROI_WIDTH,
            EXPERIENCE_TOOLTIP_ROI_HEIGHT,
            (client_left, client_top, client_width, client_height),
        )

    def _clip_rect_to_client(
        self,
        left: int,
        top: int,
        width: int,
        height: int,
        client_bounds: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        client_left, client_top, client_width, client_height = client_bounds
        client_right = client_left + client_width
        client_bottom = client_top + client_height
        clipped_left = max(client_left, min(int(left), client_right - 1))
        clipped_top = max(client_top, min(int(top), client_bottom - 1))
        clipped_right = min(client_right, clipped_left + max(1, int(width)))
        clipped_bottom = min(client_bottom, clipped_top + max(1, int(height)))
        if clipped_right - clipped_left < 20 or clipped_bottom - clipped_top < 8:
            return None
        return clipped_left, clipped_top, clipped_right - clipped_left, clipped_bottom - clipped_top

    def _capture_experience_text_images(self, regions: list[tuple[int, int, int, int]]) -> list[ExperienceOcrImage]:
        images: list[ExperienceOcrImage] = []
        for index, region in enumerate(regions):
            source_id = "primary" if index == 0 else "wide"
            image = self._capture_experience_text_image(region)
            images.append(
                ExperienceOcrImage(
                    image,
                    self._experience_text_region_bar_crop_left_ratio(index),
                    source_id,
                )
            )
        return images

    def _submit_experience_ocr_burst(
        self,
        now: float,
        image_frames: list[list[np.ndarray | ExperienceOcrImage]],
        *,
        effective_now: float | None = None,
        source: str = "bottom",
    ) -> None:
        if self._experience_clock_is_paused():
            self._stop_experience_ocr_job()
            return
        if effective_now is None:
            effective_now = self._experience_effective_time(now)
        image_signature = self._experience_ocr_image_signature(image_frames)
        continuity_hint = self._experience_ocr_continuity_hint(effective_now)
        if (
            self._is_repeated_completed_experience_ocr_signature(image_signature)
            and not self._experience_level_up_recovery_expected(continuity_hint)
        ):
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "EXP ROI 未變化，保留統計"
            self.gui.set_experience_snapshot(snapshot)
            return
        if (
            self._is_repeated_failed_experience_ocr_signature(image_signature)
            and not self._experience_level_up_recovery_expected(continuity_hint)
        ):
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "OCR ROI 未變化，保留統計" if snapshot.sample_count else "OCR ROI 未變化，等待畫面更新"
            self.gui.set_experience_snapshot(snapshot)
            return

        copied_frames = [[self._copy_experience_ocr_image(image) for image in images] for images in image_frames]
        if continuity_hint is None:
            future = self.experience_ocr_executor.submit(
                read_experience_burst_frames_in_worker,
                copied_frames,
            )
        else:
            future = self.experience_ocr_executor.submit(
                read_experience_burst_frames_in_worker,
                copied_frames,
                continuity_hint,
            )
        self.experience_ocr_job = ExperienceOcrJob(
            submitted_at=now,
            future=future,
            image_signature=image_signature,
            image_frames=[[self._copy_experience_ocr_image(image) for image in images] for images in image_frames],
            source=source,
        )
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = "讀取經驗樣本中"
        self.gui.set_experience_snapshot(snapshot)

    def _experience_ocr_continuity_hint(self, effective_now: float) -> ExperienceOcrContinuityHint | None:
        samples = getattr(self.experience_tracker, "samples", [])
        if not isinstance(samples, list) or not samples:
            return None
        latest = samples[-1]
        if not hasattr(latest, "current_exp") or not hasattr(latest, "captured_at"):
            return None
        return ExperienceOcrContinuityHint(
            current_exp=latest.current_exp,
            percent=getattr(latest, "percent", None),
            captured_at=latest.captured_at,
            now=effective_now,
        )

    def _experience_level_up_recovery_expected(self, hint: ExperienceOcrContinuityHint | None) -> bool:
        if hint is None or hint.percent is None:
            return False
        return hint.percent >= EXP_LEVEL_WRAP_HIGH_PERCENT

    def _copy_experience_ocr_image(self, image: np.ndarray | ExperienceOcrImage) -> np.ndarray | ExperienceOcrImage:
        if isinstance(image, ExperienceOcrImage):
            return ExperienceOcrImage(
                image.image.copy(),
                image.bar_crop_left_ratio,
                image.source_id,
                image.roi_offset,
                image.preprocess_variant,
                image.attempt_id,
            )
        return image.copy()

    def _experience_ocr_image_array(self, image: np.ndarray | ExperienceOcrImage) -> np.ndarray:
        if isinstance(image, ExperienceOcrImage):
            return image.image
        return image

    def _experience_ocr_image_signature(self, image_frames: list[list[np.ndarray | ExperienceOcrImage]]) -> ExperienceOcrImageSignature:
        shapes: list[tuple[int, ...]] = []
        image_hashes: list[bytes] = []
        thumbnails: list[bytes] = []
        for images in image_frames:
            for image in images:
                image_array = self._experience_ocr_image_array(image)
                shapes.append(tuple(int(part) for part in image_array.shape))
                image_hashes.append(hashlib.blake2b(image_array.tobytes(), digest_size=16).digest())
                thumbnails.append(self._experience_ocr_image_thumbnail(image_array))
        return ExperienceOcrImageSignature(tuple(shapes), tuple(image_hashes), tuple(thumbnails))

    def _experience_ocr_image_thumbnail(self, image: np.ndarray) -> bytes:
        if image.size == 0:
            return b""
        if image.ndim == 2:
            luminance = image.astype(np.float32)
        else:
            sample = image[:, :, :3].astype(np.float32)
            blue = sample[:, :, 0]
            green = sample[:, :, 1]
            red = sample[:, :, 2]
            luminance = red * 0.299 + green * 0.587 + blue * 0.114
        height, width = luminance.shape[:2]
        y_indices = np.linspace(0, height - 1, EXPERIENCE_OCR_SIGNATURE_THUMB_HEIGHT).astype(np.intp)
        x_indices = np.linspace(0, width - 1, EXPERIENCE_OCR_SIGNATURE_THUMB_WIDTH).astype(np.intp)
        thumbnail = luminance[np.ix_(y_indices, x_indices)]
        return np.clip(np.rint(thumbnail), 0, 255).astype(np.uint8).tobytes()

    def _is_repeated_failed_experience_ocr_signature(self, signature: ExperienceOcrImageSignature) -> bool:
        previous = getattr(self, "last_failed_experience_ocr_signature", None)
        return self._experience_ocr_signatures_are_similar(previous, signature)

    def _is_repeated_completed_experience_ocr_signature(self, signature: ExperienceOcrImageSignature) -> bool:
        if not getattr(self.experience_tracker, "samples", []):
            return False
        previous = getattr(self, "last_completed_experience_ocr_signature", None)
        return self._experience_ocr_signatures_are_similar(previous, signature)

    def _remember_failed_experience_ocr_signature(self, job: ExperienceOcrJob) -> None:
        self.last_failed_experience_ocr_signature = job.image_signature

    def _clear_failed_experience_ocr_signature(self) -> None:
        self.last_failed_experience_ocr_signature = None

    def _remember_completed_experience_ocr_signature(self, job: ExperienceOcrJob) -> None:
        self.last_completed_experience_ocr_signature = job.image_signature

    def _clear_completed_experience_ocr_signature(self) -> None:
        self.last_completed_experience_ocr_signature = None

    def _experience_ocr_signatures_are_identical(
        self,
        first: ExperienceOcrImageSignature | None,
        second: ExperienceOcrImageSignature | None,
    ) -> bool:
        if first is None or second is None:
            return False
        return first.image_shapes == second.image_shapes and first.image_hashes == second.image_hashes

    def _experience_ocr_signatures_are_similar(
        self,
        first: ExperienceOcrImageSignature | None,
        second: ExperienceOcrImageSignature | None,
    ) -> bool:
        if first is None or second is None:
            return False
        if first.image_shapes != second.image_shapes:
            return False
        if len(first.thumbnails) != len(second.thumbnails):
            return False

        for first_thumbnail, second_thumbnail in zip(first.thumbnails, second.thumbnails):
            if len(first_thumbnail) != len(second_thumbnail):
                return False
            if not first_thumbnail and not second_thumbnail:
                continue
            first_values = np.frombuffer(first_thumbnail, dtype=np.uint8).astype(np.int16)
            second_values = np.frombuffer(second_thumbnail, dtype=np.uint8).astype(np.int16)
            diff = np.abs(first_values - second_values)
            if float(np.mean(diff)) > EXPERIENCE_OCR_SIGNATURE_MAX_MEAN_DIFF:
                return False
            changed_ratio = float(np.count_nonzero(diff > EXPERIENCE_OCR_SIGNATURE_CHANGED_PIXEL_DELTA)) / diff.size
            if changed_ratio > EXPERIENCE_OCR_SIGNATURE_MAX_CHANGED_RATIO:
                return False
        return True

    def _process_experience_ocr_job(self, now: float, *, effective_now: float | None = None) -> bool:
        if self.experience_ocr_job is None:
            return False
        if self._experience_clock_is_paused():
            self._stop_experience_ocr_job()
            return True
        if effective_now is None:
            effective_now = self._experience_effective_time(now)
        job = self.experience_ocr_job
        if not job.future.done():
            elapsed_seconds = max(0.0, now - job.submitted_at)
            if elapsed_seconds >= EXPERIENCE_CAPTURE_INTERVAL_SECONDS:
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = f"OCR 延遲：{elapsed_seconds:.1f}s"
                self.gui.set_experience_snapshot(snapshot)
            return True

        self.experience_ocr_job = None
        self.next_experience_capture_at = job.submitted_at + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        try:
            reading = job.future.result()
        except Exception as exc:
            log_exception("OCR 背景工作失敗")
            reading = ExperienceTextReading(reason=f"OCR 背景工作失敗：{exc}", source=job.source)
        job_elapsed_ms = max(0.0, now - job.submitted_at) * 1000.0
        self._log_experience_ocr_reading(reading)
        if reading.success and reading.current_exp is not None:
            if job.source == "tooltip":
                self._clear_experience_tooltip_ocr_failures()
            tracker_samples = getattr(self.experience_tracker, "samples", None)
            has_tracker_samples = not isinstance(tracker_samples, list) or bool(tracker_samples)
            if reading.needs_bar_percent_guard and not has_tracker_samples:
                self._remember_failed_experience_ocr_signature(job)
                self.experience_tracker.record_ocr_result(True)
                self._log_experience_ocr_error(now, "EXP 合併格式需既有基準確認", reading.text)
                snapshot = self.experience_tracker.snapshot(effective_now)
                if snapshot.sample_count == 0:
                    snapshot.status = "等待明確 EXP 樣本"
                self._log_experience_debug_reading(
                    job,
                    reading,
                    snapshot,
                    decision="guard_wait",
                    completed_at=now,
                    effective_now=effective_now,
                    job_elapsed_ms=job_elapsed_ms,
                )
                self.gui.set_experience_snapshot(snapshot)
                return True
            add_reading_kwargs = {"confidence": reading.confidence}
            if not has_tracker_samples:
                add_reading_kwargs["require_initial_confirmation"] = True
            if not self.experience_tracker.add_reading(
                effective_now,
                reading.current_exp,
                reading.percent,
                **add_reading_kwargs,
            ):
                self.experience_tracker.record_ocr_result(True)
                if self.experience_tracker.last_status == "等待基準二次確認":
                    self._clear_failed_experience_ocr_signature()
                    snapshot = self.experience_tracker.snapshot(effective_now)
                    snapshot.status = "等待下一次 EXP 基準確認"
                    self._log_experience_debug_reading(
                        job,
                        reading,
                        snapshot,
                        decision="baseline_wait",
                        completed_at=now,
                        effective_now=effective_now,
                        job_elapsed_ms=job_elapsed_ms,
                    )
                    self.gui.set_experience_snapshot(snapshot)
                    return True
                self._remember_failed_experience_ocr_signature(job)
                self._log_experience_sample_rejection(now, self.experience_tracker.last_status, reading)
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "樣本已拒絕，詳見 Console"
                self._log_experience_debug_reading(
                    job,
                    reading,
                    snapshot,
                    decision="rejected",
                    completed_at=now,
                    effective_now=effective_now,
                    job_elapsed_ms=job_elapsed_ms,
                )
                self.gui.set_experience_snapshot(snapshot)
                return True
            self.experience_tracker.record_ocr_result(True)
            if reading.needs_bar_percent_guard:
                self._remember_failed_experience_ocr_signature(job)
            else:
                self._clear_failed_experience_ocr_signature()
                self._remember_completed_experience_ocr_signature(job)
            self._seed_exp_10m_checkpoint_if_needed(reading.current_exp, now)
            snapshot = self.experience_tracker.snapshot(effective_now)
            self._log_experience_debug_reading(
                job,
                reading,
                snapshot,
                decision="accepted",
                completed_at=now,
                effective_now=effective_now,
                job_elapsed_ms=job_elapsed_ms,
            )
            self.gui.set_experience_snapshot(snapshot)
            return True

        if job.source == "tooltip":
            failure_count = self._record_experience_tooltip_ocr_failure()
            self.experience_tracker.record_ocr_result(False)
            snapshot = self.experience_tracker.snapshot(effective_now)
            if failure_count < EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES:
                self._log_experience_ocr_error(
                    now,
                    (
                        f"浮動 EXP 失敗，等待重試 "
                        f"{failure_count}/{EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES}：{reading.reason}"
                    ),
                    reading.text,
                )
                snapshot.status = (
                    f"浮動 EXP OCR 失敗，等待重試 "
                    f"{failure_count}/{EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES}"
                )
                self._log_experience_debug_reading(
                    job,
                    reading,
                    snapshot,
                    decision="tooltip_retry",
                    completed_at=now,
                    effective_now=effective_now,
                    job_elapsed_ms=job_elapsed_ms,
                )
                self.gui.set_experience_snapshot(snapshot)
                return True

            self._log_experience_ocr_error(
                now,
                (
                    f"浮動 EXP 連續失敗 {failure_count} 次，改用底部 EXP OCR："
                    f"{reading.reason}"
                ),
                reading.text,
            )
            snapshot.status = "浮動 EXP OCR 連續失敗，改用底部 EXP OCR"
            self._log_experience_debug_reading(
                job,
                reading,
                snapshot,
                decision="tooltip_fallback",
                completed_at=now,
                effective_now=effective_now,
                job_elapsed_ms=job_elapsed_ms,
            )
            self.gui.set_experience_snapshot(snapshot)
            self._clear_experience_tooltip_ocr_failures()
            self._start_bottom_experience_ocr_capture(now, effective_now=effective_now)
            return True

        self._remember_failed_experience_ocr_signature(job)
        self.experience_tracker.record_ocr_result(False)
        self._log_experience_ocr_error(now, reading.reason, reading.text)
        snapshot = self.experience_tracker.snapshot(effective_now)
        if snapshot.sample_count == 0:
            snapshot.status = "等待有效 EXP 樣本"
        self._log_experience_debug_reading(
            job,
            reading,
            snapshot,
            decision="ocr_failure",
            completed_at=now,
            effective_now=effective_now,
            job_elapsed_ms=job_elapsed_ms,
        )
        self.gui.set_experience_snapshot(snapshot)
        return True

    def _log_experience_debug_reading(
        self,
        job: ExperienceOcrJob,
        reading: ExperienceTextReading,
        snapshot: ExperienceSnapshot,
        *,
        decision: str,
        completed_at: float,
        effective_now: float,
        job_elapsed_ms: float,
    ) -> None:
        tracker_status = getattr(self.experience_tracker, "last_status", snapshot.status)
        log_experience_debug(
            {
                "event": "experience_ocr_job",
                "submitted_at": self._experience_debug_number(job.submitted_at),
                "completed_at": self._experience_debug_number(completed_at),
                "effective_now": self._experience_debug_number(effective_now),
                "job_elapsed_ms": self._experience_debug_number(job_elapsed_ms),
                "success": bool(reading.success),
                "text": reading.text,
                "raw_current_exp": reading.current_exp,
                "raw_percent": self._experience_debug_number(reading.percent),
                "current_exp": reading.current_exp,
                "percent": self._experience_debug_number(reading.percent),
                "snapshot_current_exp": self._experience_debug_number(snapshot.current_exp),
                "snapshot_percent": self._experience_debug_number(snapshot.current_percent),
                "confidence": self._experience_debug_number(reading.confidence),
                "reason": reading.reason,
                "needs_bar_percent_guard": bool(reading.needs_bar_percent_guard),
                "bar_percent": self._experience_debug_number(reading.bar_percent),
                "continuity_status": reading.continuity_status,
                "source": reading.source,
                "learning_case_id": reading.learning_case_id,
                "level_total_estimate": self._experience_debug_number(
                    getattr(self.experience_tracker, "estimated_level_total_exp", None)
                ),
                "level_total_deviation_ratio": self._experience_debug_number(
                    self._experience_level_total_deviation_ratio(reading)
                ),
                "decision": decision,
                "tracker_status": str(tracker_status),
                "sample_count": self._experience_debug_number(snapshot.sample_count),
                "sample_attempt_count": self._experience_debug_number(snapshot.sample_attempt_count),
                "sample_accept_count": self._experience_debug_number(snapshot.sample_accept_count),
                "ocr_attempt_count": self._experience_debug_number(snapshot.ocr_attempt_count),
                "ocr_success_count": self._experience_debug_number(snapshot.ocr_success_count),
                "xp_per_5m": self._experience_debug_number(snapshot.xp_per_5m),
                "xp_per_10m": self._experience_debug_number(snapshot.xp_per_10m),
                "xp_per_hour": self._experience_debug_number(snapshot.xp_per_hour),
                "eta_seconds": self._experience_debug_number(snapshot.eta_seconds),
                "rate_confidence": self._experience_debug_number(snapshot.rate_confidence),
            }
        )

    def _experience_level_total_deviation_ratio(self, reading: ExperienceTextReading) -> float | None:
        method = getattr(self.experience_tracker, "level_total_deviation_ratio", None)
        if not callable(method):
            return None
        try:
            value = method(reading.current_exp, reading.percent)
        except Exception:
            return None
        return value if isinstance(value, (int, float)) else None

    def _experience_debug_number(self, value: object) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return value

    def _stop_experience_ocr_job(self) -> None:
        self._cancel_experience_baseline_calibration(close_ui=True)
        self._cancel_exp_10m_checkpoint(close_ui=True)
        self.experience_ocr_burst = None
        self._clear_failed_experience_ocr_signature()
        self._clear_completed_experience_ocr_signature()
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

    def _experience_text_regions(self) -> list[tuple[int, int, int, int]]:
        regions: list[tuple[int, int, int, int]] = []
        ratios: list[float] = []
        layout = getattr(self, "bottom_hud_layout", None)
        if layout is not None and layout.exp_text_region is not None:
            regions.append(layout.exp_text_region)
            if layout.exp_track_region is not None and layout.exp_track_region[2] > 0:
                ratios.append(
                    max(
                        0.0,
                        min(
                            0.98,
                            (layout.exp_text_region[0] - layout.exp_track_region[0])
                            / layout.exp_track_region[2],
                        ),
                    )
                )
            else:
                ratios.append(0.0)
            self.experience_text_region_bar_crop_left_ratios = ratios
            return regions

        primary = self._experience_text_region()
        if primary is not None and primary not in regions:
            regions.append(primary)
            ratios.append(EXPERIENCE_TEXT_LEFT_RATIO)

        wide = self._wide_experience_text_region()
        if wide is not None and wide not in regions:
            regions.append(wide)
            ratios.append(EXPERIENCE_WIDE_TEXT_LEFT_RATIO)
        self.experience_text_region_bar_crop_left_ratios = ratios
        return regions

    def _experience_text_region_bar_crop_left_ratio(self, region_index: int) -> float:
        ratios = getattr(self, "experience_text_region_bar_crop_left_ratios", [])
        if 0 <= region_index < len(ratios):
            return ratios[region_index]
        return EXPERIENCE_WIDE_TEXT_LEFT_RATIO if region_index == 1 else EXPERIENCE_TEXT_LEFT_RATIO

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

    def _wide_experience_text_region(self) -> tuple[int, int, int, int] | None:
        bottom_bar_regions = getattr(self, "bottom_bar_regions", None)
        if not isinstance(bottom_bar_regions, dict):
            return None
        hp_region = bottom_bar_regions.get("hp")
        mp_region = bottom_bar_regions.get("mp")
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
        region_bottom = min(
            client_bottom,
            top + max(16, round(bar_height * EXPERIENCE_WIDE_TEXT_HEIGHT_RATIO)),
        )
        region_left = max(client_left, left + round(base_width * EXPERIENCE_WIDE_TEXT_LEFT_RATIO))
        region_right = min(client_right, right + round(base_width * EXPERIENCE_WIDE_TEXT_RIGHT_PADDING_RATIO))
        if region_right - region_left < 20 or region_bottom - region_top < 8:
            return None
        return (
            region_left,
            region_top,
            region_right - region_left,
            region_bottom - region_top,
        )

    def _maybe_drink_hp(self, now: float, hp_percent: float | None) -> None:
        self._maybe_drink_potion(
            "hp",
            "HP",
            now,
            hp_percent,
            self.settings.hp_enabled,
            self.settings.hp_threshold_percent,
            self.settings.hp_key,
            self.settings.hp_continuous_enabled,
            self.settings.hp_continuous_stop_margin_percent,
        )

    def _maybe_drink_mp(self, now: float, mp_percent: float | None) -> None:
        self._maybe_drink_potion(
            "mp",
            "MP",
            now,
            mp_percent,
            self.settings.mp_enabled,
            self.settings.mp_threshold_percent,
            self.settings.mp_key,
            self.settings.mp_continuous_enabled,
            self.settings.mp_continuous_stop_margin_percent,
        )

    def _maybe_drink_potion(
        self,
        bar_type: str,
        label: str,
        now: float,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
        key_name: str,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
    ) -> None:
        if not enabled:
            self._clear_potion_bar_state(bar_type)
            return
        if self._out_of_potion_hold(bar_type) is not None:
            self._release_potion_key(bar_type)
            return
        if percent is None:
            percent = self._capture_transient_bar_percent(bar_type)
            if percent is None:
                self._release_potion_key(bar_type)
                self._emit_direct_bar_failure_warning_if_needed(now)
                self._log_unstable_bar(now, label)
                return
        if not self._should_drink_for_current_mode(
            percent,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
        ):
            self._release_potion_key(bar_type)
            self._clear_potion_attempt_state(bar_type)
            return
        if not continuous_enabled:
            last_drink_at = self._last_potion_drink_at(bar_type)
            if last_drink_at > -100.0:
                elapsed_since_drink = now - last_drink_at
                if elapsed_since_drink + POTION_TIME_EPSILON_SECONDS < self._potion_cooldown_seconds(bar_type):
                    self._schedule_pending_potion_send(
                        bar_type,
                        last_drink_at + self._potion_cooldown_seconds(bar_type),
                        percent,
                    )
                    return
        if not self._is_target_window_active_before_send(label, now):
            if continuous_enabled:
                self._release_potion_key(bar_type)
            self._play_potion_blocked_sound(now)
            return

        if self._can_use_fast_repeat_potion_sample(bar_type):
            confirmed_percent = percent
        else:
            confirmed_percent = self._capture_confirmed_bar_percent(bar_type, percent)
        percent = confirmed_percent
        if percent is None:
            if continuous_enabled:
                self._release_potion_key(bar_type)
            self._emit_direct_bar_failure_warning_if_needed(now)
            self._log_unstable_bar(now, label)
            self._play_potion_blocked_sound(now)
            return
        if not self._should_drink_for_current_mode(
            percent,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
        ):
            self._release_potion_key(bar_type)
            self._clear_potion_attempt_state(bar_type)
            return
        if not self._is_target_window_active_before_send(label, now):
            if continuous_enabled:
                self._release_potion_key(bar_type)
            self._play_potion_blocked_sound(now)
            return

        if continuous_enabled:
            previous_at = self._last_potion_drink_at(bar_type)
            was_held = self._potion_held_vk(bar_type) != 0
            if not self._hold_potion_key(bar_type, label, key_name, now):
                self._play_potion_blocked_sound(now)
                return
            if not was_held:
                self._log_potion_key_trigger_interval(label, key_name, previous_at, now)
            self._set_last_potion_drink_at(bar_type, now)
            self._record_continuous_potion_effect_attempt(bar_type, now, percent)
            self.last_action = f"{label} 連續喝水：{key_name}"
            return

        previous_at = self._last_potion_drink_at(bar_type)
        self._clear_pending_potion_send(bar_type)
        self._tap_potion_key(bar_type, key_name)
        self._log_potion_key_trigger_interval(label, key_name, previous_at, now)
        self._set_last_potion_drink_at(bar_type, now)
        self._record_potion_effect_attempt(bar_type, now, percent)
        self.last_action = f"{label} 喝水：{key_name}"

    def _continuous_stop_threshold_percent(self, threshold_percent: float, margin_percent: float) -> float:
        try:
            margin = float(margin_percent)
        except (TypeError, ValueError):
            margin = 0.0
        margin = max(0.0, min(POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT, margin))
        return max(1.0, float(threshold_percent) - margin)

    def _process_due_potion_sends(self, now: float) -> None:
        if not self.auto_drink_enabled:
            self._clear_pending_potion_send("hp")
            self._clear_pending_potion_send("mp")
            return
        self._process_due_potion_send(
            "hp",
            "HP",
            now,
            self.settings.hp_enabled,
            self.settings.hp_threshold_percent,
            self.settings.hp_key,
            self.settings.hp_continuous_enabled,
        )
        self._process_due_potion_send(
            "mp",
            "MP",
            now,
            self.settings.mp_enabled,
            self.settings.mp_threshold_percent,
            self.settings.mp_key,
            self.settings.mp_continuous_enabled,
        )

    def _process_due_potion_send(
        self,
        bar_type: str,
        label: str,
        now: float,
        enabled: bool,
        threshold_percent: float,
        key_name: str,
        continuous_enabled: bool,
    ) -> None:
        due_at = self._pending_potion_send_at(bar_type)
        if due_at <= -100.0 or now + POTION_TIME_EPSILON_SECONDS < due_at:
            return
        percent = self._pending_potion_send_percent(bar_type)
        self._clear_pending_potion_send(bar_type)
        if (
            not enabled
            or continuous_enabled
            or self._out_of_potion_hold(bar_type) is not None
            or percent is None
            or not should_drink_for_threshold(percent, threshold_percent)
        ):
            return
        previous_at = self._last_potion_drink_at(bar_type)
        if previous_at > -100.0:
            cooldown_seconds = self._potion_cooldown_seconds(bar_type)
            if now - previous_at + POTION_TIME_EPSILON_SECONDS < cooldown_seconds:
                self._schedule_pending_potion_send(bar_type, previous_at + cooldown_seconds, percent)
                return
        if getattr(self, "gameplay_hud_active", False):
            self.potion_send_prevalidated_at = now
        if not self._is_target_window_active_before_send(label, now):
            return
        self._tap_potion_key(bar_type, key_name)
        self._log_potion_key_trigger_interval(label, key_name, previous_at, now)
        self._set_last_potion_drink_at(bar_type, now)
        self._record_potion_effect_attempt(bar_type, now, percent)
        self.last_action = f"{label} 喝水：{key_name}"

    def _can_use_fast_repeat_potion_sample(self, bar_type: str) -> bool:
        return self._last_potion_drink_at(bar_type) > -100.0

    def _should_defer_experience_for_potion(
        self,
        now: float,
        hp_percent: float | None,
        mp_percent: float | None,
    ) -> bool:
        if not self.auto_drink_enabled:
            return False
        return self._should_defer_experience_for_potion_bar(
            "hp",
            hp_percent,
            self.settings.hp_enabled,
            self.settings.hp_threshold_percent,
            self.settings.hp_continuous_enabled,
            self.settings.hp_continuous_stop_margin_percent,
            now,
        ) or self._should_defer_experience_for_potion_bar(
            "mp",
            mp_percent,
            self.settings.mp_enabled,
            self.settings.mp_threshold_percent,
            self.settings.mp_continuous_enabled,
            self.settings.mp_continuous_stop_margin_percent,
            now,
        )

    def _should_defer_experience_for_potion_bar(
        self,
        bar_type: str,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
        now: float,
    ) -> bool:
        if not enabled or self._out_of_potion_hold(bar_type) is not None:
            return False
        if self._potion_held_vk(bar_type):
            return True
        if percent is not None and self._should_drink_for_current_mode(
            percent,
            threshold_percent,
            continuous_enabled,
            continuous_stop_margin_percent,
        ):
            return True
        return now - self._last_potion_drink_at(bar_type) < POTION_EXPERIENCE_DEFER_SECONDS

    def _should_drink_for_current_mode(
        self,
        percent: float,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
    ) -> bool:
        if not continuous_enabled:
            return should_drink_for_threshold(percent, threshold_percent)
        return should_continue_continuous_drink(
            percent,
            self._continuous_stop_threshold_percent(threshold_percent, continuous_stop_margin_percent),
        )

    def _capture_interval_after_potion_sample(self, hp_percent: float | None, mp_percent: float | None) -> float:
        if not self._should_use_fast_potion_capture_interval(hp_percent, mp_percent):
            return DEFAULT_CAPTURE_INTERVAL_SECONDS
        return min(DEFAULT_CAPTURE_INTERVAL_SECONDS, POTION_FAST_CAPTURE_INTERVAL_SECONDS)

    def _should_use_fast_potion_capture_interval(
        self,
        hp_percent: float | None,
        mp_percent: float | None,
    ) -> bool:
        if not self.auto_drink_enabled or self._has_out_of_potion_hold():
            return False
        return self._potion_bar_near_threshold(
            hp_percent,
            self.settings.hp_enabled,
            self.settings.hp_threshold_percent,
        ) or self._potion_bar_near_threshold(
            mp_percent,
            self.settings.mp_enabled,
            self.settings.mp_threshold_percent,
        )

    def _potion_bar_near_threshold(
        self,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
    ) -> bool:
        if not enabled or percent is None:
            return False
        if threshold_percent >= 100.0 and percent >= 100.0:
            return False
        return percent <= threshold_percent + POTION_NEAR_THRESHOLD_FAST_MARGIN_PERCENT

    def _defer_experience_for_potion_priority(self, now: float) -> None:
        if self.experience_ocr_burst is not None:
            self.experience_ocr_burst = None
        self.next_experience_capture_at = max(
            self.next_experience_capture_at,
            now + POTION_EXPERIENCE_DEFER_SECONDS,
        )

    def _update_potion_effect_watch_cycles(self, now: float, hp_percent: float, mp_percent: float) -> bool:
        if self.settings.hp_enabled:
            self._update_potion_effect_watch_cycle(
                "hp",
                "HP",
                hp_percent,
                self.settings.hp_threshold_percent,
                now,
            )
        else:
            self._clear_potion_bar_state("hp")

        if self.settings.mp_enabled:
            self._update_potion_effect_watch_cycle(
                "mp",
                "MP",
                mp_percent,
                self.settings.mp_threshold_percent,
                now,
            )
        else:
            self._clear_potion_bar_state("mp")
        return True

    def _update_potion_effect_watch_cycle(
        self,
        bar_type: str,
        label: str,
        percent: float,
        threshold_percent: float,
        now: float,
    ) -> bool:
        if self._out_of_potion_hold(bar_type) is not None:
            return True
        self._record_potion_percent_sample(bar_type, now, percent)
        self._update_potion_damage_context(bar_type, percent, now)
        if not should_drink_for_threshold(percent, threshold_percent):
            self._clear_potion_attempt_state(bar_type)
            return True
        if self._potion_recent_damage_blocks_stable_confirmation(bar_type, now):
            self._reset_potion_no_effect_count(bar_type)
        bar_is_stable = self._potion_bar_is_stable_for_confirmation(bar_type, now)

        attempts = self._potion_effect_attempts(bar_type)
        if not bar_is_stable and not attempts:
            self._reset_potion_no_effect_count(bar_type)
        if not attempts:
            return True
        attempts = [attempt.with_observed_percent(percent) for attempt in attempts]
        if any(
            attempt.before_percent - percent > POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            for attempt in attempts
        ):
            self._mark_potion_recent_damage(bar_type, now)
        matured_attempts = [
            attempt
            for attempt in attempts
            if now - attempt.attempted_at >= POTION_EFFECT_OBSERVATION_SECONDS
        ]
        if not matured_attempts:
            self._set_potion_effect_attempts(bar_type, attempts)
            return True
        pending_attempts = [
            attempt
            for attempt in attempts
            if now - attempt.attempted_at < POTION_EFFECT_OBSERVATION_SECONDS
        ]
        if any(
            percent - attempt.before_percent > POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            for attempt in matured_attempts
        ):
            self._clear_potion_attempt_state(bar_type)
            return True

        has_quiet_no_effect = any(
            attempt.pre_window_is_stable
            and abs(percent - attempt.before_percent) <= POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            and attempt.min_percent >= attempt.before_percent - POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            and attempt.max_percent - attempt.min_percent <= POTION_EFFECT_WATCH_VOLATILITY_TOLERANCE_PERCENT
            for attempt in matured_attempts
        )
        self._set_potion_effect_attempts(bar_type, pending_attempts)
        if not has_quiet_no_effect:
            self._reset_potion_no_effect_count(bar_type)
            return True
        if not bar_is_stable:
            return True
        if self._potion_recent_damage_is_active(bar_type, now):
            return True
        if not self._potion_auto_hold_is_allowed(bar_type):
            self._reset_potion_no_effect_count(bar_type)
            return True
        if (
            now - self._potion_last_no_effect_counted_at(bar_type) + POTION_TIME_EPSILON_SECONDS
            < POTION_EFFECT_OBSERVATION_SECONDS
        ):
            return True

        no_effect_count = self._potion_no_effect_count(bar_type) + 1
        self._set_potion_no_effect_count(bar_type, no_effect_count)
        self._set_potion_last_no_effect_counted_at(bar_type, now)
        if no_effect_count >= POTION_EFFECT_NO_EFFECT_LIMIT:
            self._alert_suspected_no_potion(bar_type, label, percent, now)
        return True

    def _record_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        attempt = PotionEffectAttempt(
            now,
            before_percent,
            pre_window_is_stable=self._potion_pre_window_is_stable(bar_type, now, before_percent),
        )
        attempts = [*self._potion_effect_attempts(bar_type), attempt]
        self._set_potion_effect_attempts(bar_type, attempts)

    def _record_continuous_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        attempts = self._potion_effect_attempts(bar_type)
        if attempts and now - attempts[-1].attempted_at + POTION_TIME_EPSILON_SECONDS < POTION_EFFECT_OBSERVATION_SECONDS:
            return
        self._record_potion_effect_attempt(bar_type, now, before_percent)

    def _potion_effect_attempts(self, bar_type: str) -> list[PotionEffectAttempt]:
        return self.hp_potion_effect_attempts if bar_type == "hp" else self.mp_potion_effect_attempts

    def _set_potion_effect_attempts(self, bar_type: str, attempts: list[PotionEffectAttempt]) -> None:
        if bar_type == "hp":
            self.hp_potion_effect_attempts = attempts
        else:
            self.mp_potion_effect_attempts = attempts

    def _clear_potion_effect_state(self) -> None:
        self._clear_potion_bar_state("hp")
        self._clear_potion_bar_state("mp")

    def _clear_potion_bar_state(self, bar_type: str) -> None:
        self._release_potion_key(bar_type)
        self._clear_pending_potion_send(bar_type)
        self._set_potion_effect_attempts(bar_type, [])
        self._reset_potion_no_effect_count(bar_type)
        self._set_out_of_potion_hold(bar_type, None)
        self._set_potion_last_observed_percent(bar_type, None)
        self._set_potion_recent_samples(bar_type, [])
        self._set_potion_recent_damage_at(bar_type, -999.0)
        self._set_potion_damage_pressure_active(bar_type, False)

    def _clear_potion_attempt_state(self, bar_type: str) -> None:
        self._clear_pending_potion_send(bar_type)
        self._set_potion_effect_attempts(bar_type, [])
        self._reset_potion_no_effect_count(bar_type)
        self._set_potion_recent_samples(bar_type, [])
        self._set_potion_damage_pressure_active(bar_type, False)
        self._set_potion_recent_damage_at(bar_type, -999.0)

    def _clear_uncertain_potion_observations(self, hp_percent: float | None, mp_percent: float | None) -> None:
        if hp_percent is None:
            self._release_potion_key("hp")
            self._clear_pending_potion_send("hp")
            self._set_potion_effect_attempts("hp", [])
            self._set_potion_recent_samples("hp", [])
        if mp_percent is None:
            self._release_potion_key("mp")
            self._clear_pending_potion_send("mp")
            self._set_potion_effect_attempts("mp", [])
            self._set_potion_recent_samples("mp", [])

    def _potion_no_effect_count(self, bar_type: str) -> int:
        return self.hp_potion_no_effect_count if bar_type == "hp" else self.mp_potion_no_effect_count

    def _set_potion_no_effect_count(self, bar_type: str, count: int) -> None:
        if bar_type == "hp":
            self.hp_potion_no_effect_count = count
        else:
            self.mp_potion_no_effect_count = count

    def _reset_potion_no_effect_count(self, bar_type: str) -> None:
        self._set_potion_no_effect_count(bar_type, 0)
        self._set_potion_last_no_effect_counted_at(bar_type, -999.0)

    def _potion_last_no_effect_counted_at(self, bar_type: str) -> float:
        if bar_type == "hp":
            return getattr(self, "hp_potion_last_no_effect_counted_at", -999.0)
        return getattr(self, "mp_potion_last_no_effect_counted_at", -999.0)

    def _set_potion_last_no_effect_counted_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.hp_potion_last_no_effect_counted_at = now
        else:
            self.mp_potion_last_no_effect_counted_at = now

    def _pending_potion_send_at(self, bar_type: str) -> float:
        if bar_type == "hp":
            return getattr(self, "hp_pending_potion_send_at", -999.0)
        return getattr(self, "mp_pending_potion_send_at", -999.0)

    def _pending_potion_send_percent(self, bar_type: str) -> float | None:
        if bar_type == "hp":
            return getattr(self, "hp_pending_potion_send_percent", None)
        return getattr(self, "mp_pending_potion_send_percent", None)

    def _schedule_pending_potion_send(self, bar_type: str, due_at: float, percent: float) -> None:
        if bar_type == "hp":
            self.hp_pending_potion_send_at = due_at
            self.hp_pending_potion_send_percent = percent
        else:
            self.mp_pending_potion_send_at = due_at
            self.mp_pending_potion_send_percent = percent

    def _clear_pending_potion_send(self, bar_type: str) -> None:
        if bar_type == "hp":
            self.hp_pending_potion_send_at = -999.0
            self.hp_pending_potion_send_percent = None
        else:
            self.mp_pending_potion_send_at = -999.0
            self.mp_pending_potion_send_percent = None

    def _next_pending_potion_send_at(self) -> float | None:
        pending_times = [
            due_at
            for due_at in (
                self._pending_potion_send_at("hp"),
                self._pending_potion_send_at("mp"),
            )
            if due_at > -100.0
        ]
        if not pending_times:
            return None
        return min(pending_times)

    def _potion_cooldown_seconds(self, bar_type: str) -> float:
        if bar_type == "hp":
            return max(POTION_MIN_COOLDOWN_SECONDS, float(self.settings.hp_cooldown_seconds))
        return max(POTION_MIN_COOLDOWN_SECONDS, float(self.settings.mp_cooldown_seconds))

    def _last_potion_drink_at(self, bar_type: str) -> float:
        return self.last_hp_drink_at if bar_type == "hp" else self.last_mp_drink_at

    def _set_last_potion_drink_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.last_hp_drink_at = now
        else:
            self.last_mp_drink_at = now

    def _update_potion_damage_context(self, bar_type: str, percent: float, now: float) -> None:
        last_percent = self._potion_last_observed_percent(bar_type)
        self._set_potion_last_observed_percent(bar_type, percent)
        if last_percent is None:
            return
        if last_percent - percent > POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT:
            self._mark_potion_recent_damage(bar_type, now)

    def _mark_potion_recent_damage(self, bar_type: str, now: float) -> None:
        self._set_potion_recent_damage_at(bar_type, now)
        self._set_potion_damage_pressure_active(bar_type, True)
        self._reset_potion_no_effect_count(bar_type)

    def _potion_recent_damage_is_active(self, bar_type: str, now: float) -> bool:
        if now - self._potion_recent_damage_at(bar_type) <= POTION_EFFECT_DAMAGE_GRACE_SECONDS:
            return True
        self._set_potion_damage_pressure_active(bar_type, False)
        return False

    def _potion_recent_damage_blocks_stable_confirmation(self, bar_type: str, now: float) -> bool:
        return now - self._potion_recent_damage_at(bar_type) <= self._potion_stability_confirmation_seconds(bar_type)

    def _potion_auto_hold_is_allowed(self, bar_type: str) -> bool:
        return bar_type in POTION_EFFECT_AUTO_HOLD_BAR_TYPES

    def _record_potion_percent_sample(self, bar_type: str, now: float, percent: float) -> None:
        cutoff = now - self._potion_stability_confirmation_seconds(bar_type)
        samples = [
            sample
            for sample in [*self._potion_recent_samples(bar_type), (now, percent)]
            if sample[0] >= cutoff
        ]
        self._set_potion_recent_samples(bar_type, samples)

    def _potion_pre_window_is_stable(self, bar_type: str, now: float, before_percent: float) -> bool:
        if self._potion_recent_damage_is_active(bar_type, now):
            return False
        samples = [
            percent
            for observed_at, percent in self._potion_recent_samples(bar_type)
            if now - observed_at <= POTION_EFFECT_PRE_OBSERVATION_SECONDS
        ]
        if len(samples) < POTION_EFFECT_PRE_OBSERVATION_MIN_SAMPLES:
            return False
        samples = [*samples, before_percent]
        if max(samples) - min(samples) > POTION_EFFECT_PRE_OBSERVATION_VOLATILITY_TOLERANCE_PERCENT:
            return False
        return abs(samples[-2] - before_percent) <= POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT

    def _potion_bar_is_stable_for_confirmation(self, bar_type: str, now: float) -> bool:
        if self._potion_recent_damage_is_active(bar_type, now):
            return False
        confirmation_seconds = self._potion_stability_confirmation_seconds(bar_type)
        if now - self._potion_recent_damage_at(bar_type) <= confirmation_seconds:
            return False
        samples = [
            percent
            for observed_at, percent in self._potion_recent_samples(bar_type)
            if now - observed_at <= confirmation_seconds
        ]
        if len(samples) < self._potion_stability_confirmation_min_samples(bar_type):
            return False
        if max(samples) - min(samples) > self._potion_stability_confirmation_volatility_tolerance(bar_type):
            return False
        return all(
            abs(current - previous) <= POTION_EFFECT_WATCH_CHANGE_TOLERANCE_PERCENT
            for previous, current in zip(samples, samples[1:])
        )

    def _potion_stability_confirmation_seconds(self, bar_type: str) -> float:
        if bar_type == "hp":
            return POTION_EFFECT_HP_STABILITY_CONFIRMATION_SECONDS
        return POTION_EFFECT_STABILITY_CONFIRMATION_SECONDS

    def _potion_stability_confirmation_min_samples(self, bar_type: str) -> int:
        if bar_type == "hp":
            return POTION_EFFECT_HP_STABILITY_CONFIRMATION_MIN_SAMPLES
        return POTION_EFFECT_STABILITY_CONFIRMATION_MIN_SAMPLES

    def _potion_stability_confirmation_volatility_tolerance(self, bar_type: str) -> float:
        if bar_type == "hp":
            return POTION_EFFECT_HP_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT
        return POTION_EFFECT_STABILITY_CONFIRMATION_VOLATILITY_TOLERANCE_PERCENT

    def _potion_recent_samples(self, bar_type: str) -> list[tuple[float, float]]:
        if bar_type == "hp":
            return getattr(self, "hp_potion_recent_samples", [])
        return getattr(self, "mp_potion_recent_samples", [])

    def _set_potion_recent_samples(self, bar_type: str, samples: list[tuple[float, float]]) -> None:
        if bar_type == "hp":
            self.hp_potion_recent_samples = samples
        else:
            self.mp_potion_recent_samples = samples

    def _potion_last_observed_percent(self, bar_type: str) -> float | None:
        if bar_type == "hp":
            return getattr(self, "hp_potion_last_observed_percent", None)
        return getattr(self, "mp_potion_last_observed_percent", None)

    def _set_potion_last_observed_percent(self, bar_type: str, percent: float | None) -> None:
        if bar_type == "hp":
            self.hp_potion_last_observed_percent = percent
        else:
            self.mp_potion_last_observed_percent = percent

    def _potion_recent_damage_at(self, bar_type: str) -> float:
        if bar_type == "hp":
            return getattr(self, "hp_potion_recent_damage_at", -999.0)
        return getattr(self, "mp_potion_recent_damage_at", -999.0)

    def _set_potion_recent_damage_at(self, bar_type: str, now: float) -> None:
        if bar_type == "hp":
            self.hp_potion_recent_damage_at = now
        else:
            self.mp_potion_recent_damage_at = now

    def _potion_damage_pressure_active(self, bar_type: str) -> bool:
        if bar_type == "hp":
            return getattr(self, "hp_potion_damage_pressure_active", False)
        return getattr(self, "mp_potion_damage_pressure_active", False)

    def _set_potion_damage_pressure_active(self, bar_type: str, active: bool) -> None:
        if bar_type == "hp":
            self.hp_potion_damage_pressure_active = active
        else:
            self.mp_potion_damage_pressure_active = active

    def _out_of_potion_hold(self, bar_type: str) -> OutOfPotionHold | None:
        return self.hp_out_of_potion_hold if bar_type == "hp" else self.mp_out_of_potion_hold

    def _set_out_of_potion_hold(self, bar_type: str, hold: OutOfPotionHold | None) -> None:
        if bar_type == "hp":
            self.hp_out_of_potion_hold = hold
        else:
            self.mp_out_of_potion_hold = hold

    def _has_out_of_potion_hold(self) -> bool:
        return self.hp_out_of_potion_hold is not None or self.mp_out_of_potion_hold is not None

    def _out_of_potion_hold_status_message(self) -> str:
        held_labels = []
        if self.hp_out_of_potion_hold is not None:
            held_labels.append("HP")
        if self.mp_out_of_potion_hold is not None:
            held_labels.append("MP")
        label = "/".join(held_labels) if held_labels else "HP/MP"
        return f"{label} 檢查藥水"

    def _alert_suspected_no_potion(self, bar_type: str, label: str, current_percent: float, now: float) -> None:
        self._set_potion_effect_attempts(bar_type, [])
        self._set_potion_no_effect_count(bar_type, POTION_EFFECT_NO_EFFECT_LIMIT)
        message = f"{label} 檢查藥水"
        self.gui.set_status(message)
        self.gui.show_toggle_notice(message)
        self._play_potion_check_sound(now)
        self.last_action = message
        print(f"{label} 連續 {POTION_EFFECT_NO_EFFECT_LIMIT} 次喝水未見回升，提示檢查藥水：{current_percent:.0f}%")

    def _is_target_window_active_before_send(self, label: str, now: float | None = None) -> bool:
        check_at = time.monotonic() if now is None else now
        if (
            getattr(self, "gameplay_hud_active", False)
            and abs(check_at - getattr(self, "potion_send_prevalidated_at", -999.0)) <= POTION_TIME_EPSILON_SECONDS
        ):
            return True
        if self.is_target_window_active():
            if self._refresh_gameplay_hud_state(check_at):
                return True
            self.gui.set_status("未偵測到遊戲 HUD，暫停自動喝水")
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

    def _record_direct_bar_success(self) -> None:
        self.direct_bar_failure_count = 0
        self.last_direct_bar_failure_reason = ""

    def _record_direct_bar_failure(self, reason: str) -> None:
        self.direct_bar_failure_count = getattr(self, "direct_bar_failure_count", 0) + 1
        self.last_direct_bar_failure_reason = reason

    def _note_direct_bar_failure_reason(self, reason: str) -> None:
        self.last_direct_bar_failure_reason = reason

    def _direct_bar_failure_reason(self, fallback: str) -> str:
        reason = getattr(self, "last_direct_bar_failure_reason", "") or fallback
        if "略過截圖讀值" not in reason:
            reason = f"{reason}，略過截圖讀值"
        return reason

    def _emit_direct_bar_failure_warning_if_needed(self, now: float) -> bool:
        if getattr(self, "direct_bar_failure_count", 0) < DIRECT_BAR_FAILURE_WARNING_ATTEMPTS:
            return False

        status = "HP/MP 直接取色連續失敗，已暫停自動喝水"
        self.gui.set_status(status)
        last_warning_at = getattr(self, "last_direct_bar_failure_warning_at", -999.0)
        if now - last_warning_at >= BAR_UNSTABLE_LOG_INTERVAL_SECONDS:
            self.last_direct_bar_failure_warning_at = now
            reason = getattr(self, "last_direct_bar_failure_reason", "") or "原因不明"
            self.gui.show_toggle_notice("HP/MP 直接取色失敗")
            print(f"{status}：{reason}")
        return True

    def _set_direct_bar_failure_debug(
        self,
        bar_type: str,
        reason: str,
        *,
        require_clear_tail: bool = False,
    ) -> None:
        region = getattr(self, "bottom_bar_regions", {}).get(bar_type)
        track_region = getattr(self, "bottom_bar_track_regions", {}).get(bar_type)
        self._set_bar_detection_debug(
            bar_type,
            source="直接取色",
            region=region,
            track_region=track_region,
            percent=None,
            success=False,
            reason=reason,
            require_clear_tail=require_clear_tail,
            tail_clear=None,
        )

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
        direct_percent = self._capture_bar_percent_direct(bar_type, require_clear_tail=require_clear_tail)
        if direct_percent is not None:
            return direct_percent

        region = self._find_bottom_bar_pair_regions().get(bar_type)
        if region is None:
            reason = "找不到 HP/MP 定位座標，無法直接取色"
            self._record_direct_bar_failure(reason)
            self._set_bar_detection_debug(
                bar_type,
                source="自動定位",
                region=None,
                track_region=None,
                percent=None,
                success=False,
                reason=reason,
                require_clear_tail=require_clear_tail,
                tail_clear=None,
            )
            return None

        direct_percent = self._capture_bar_percent_direct(bar_type, require_clear_tail=require_clear_tail)
        if direct_percent is not None:
            return direct_percent

        reason = self._direct_bar_failure_reason("直接取色失敗")
        self._record_direct_bar_failure(reason)
        self._set_direct_bar_failure_debug(
            bar_type,
            reason,
            require_clear_tail=require_clear_tail,
        )
        return None

    def _capture_bar_percents(self) -> tuple[float | None, float | None]:
        direct = self._capture_bar_percents_direct()
        if direct is not None:
            return direct

        regions = self._find_bottom_bar_pair_regions()
        if "hp" not in regions or "mp" not in regions:
            reason = "找不到 HP/MP 定位座標，無法直接取色"
            self._record_direct_bar_failure(reason)
            for bar_type in ("hp", "mp"):
                self._set_direct_bar_failure_debug(bar_type, reason)
            return None, None

        direct = self._capture_bar_percents_direct()
        if direct is not None:
            return direct

        reason = self._direct_bar_failure_reason("直接取色失敗")
        self._record_direct_bar_failure(reason)
        for bar_type in ("hp", "mp"):
            self._set_direct_bar_failure_debug(bar_type, reason)
        return None, None

    def _capture_bar_percents_direct(self) -> tuple[float | None, float | None] | None:
        cached = self._cached_bottom_bar_screen_regions_for_current_client()
        if cached is None:
            self._note_direct_bar_failure_reason("沒有 cached HUD geometry")
            return None
        regions, track_regions, client_bounds = cached
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            self._note_direct_bar_failure_reason("HUD geometry 不可信")
            return None
        sample_regions = {
            bar_type: track_regions.get(bar_type) or regions.get(bar_type)
            for bar_type in ("hp", "mp")
        }
        if sample_regions["hp"] is None or sample_regions["mp"] is None:
            self._note_direct_bar_failure_reason("HP/MP direct 取色範圍缺失")
            return None

        union = self._union_direct_bar_regions(sample_regions["hp"], sample_regions["mp"])
        if union is None:
            self._note_direct_bar_failure_reason("HP/MP direct union 範圍無效")
            return None
        image = self._direct_bar_image_from_region(union)
        if image is None:
            self._note_direct_bar_failure_reason("direct GDI capture 失敗")
            return None

        results: dict[str, float] = {}
        for bar_type in ("hp", "mp"):
            region = sample_regions[bar_type]
            assert region is not None
            crop = self._crop_direct_bar_image(image, union, region)
            if crop is None:
                self._note_direct_bar_failure_reason(f"{bar_type.upper()} direct crop 範圍無效")
                return None
            percent, reason, tail_clear = self._sample_direct_bar_percent_from_image(crop, bar_type)
            if percent is None:
                self._note_direct_bar_failure_reason(f"{bar_type.upper()}: {reason}")
                self._set_bar_detection_debug(
                    bar_type,
                    source="直接取色",
                    region=region,
                    track_region=region,
                    percent=None,
                    success=False,
                    reason=reason,
                    require_clear_tail=False,
                    tail_clear=tail_clear,
                )
                return None
            results[bar_type] = percent
            self._remember_stable_bar_sample(bar_type, percent, region)
            self._set_bar_detection_debug(
                bar_type,
                source="直接取色",
                region=region,
                track_region=region,
                percent=percent,
                success=True,
                reason=reason,
                require_clear_tail=False,
                tail_clear=tail_clear,
            )

        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = time.monotonic()
        self._record_direct_bar_success()
        return results.get("hp"), results.get("mp")

    def _union_direct_bar_regions(
        self,
        first: tuple[int, int, int, int] | None,
        second: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, int, int] | None:
        if first is None or second is None:
            return None
        left = min(first[0], second[0])
        top = min(first[1], second[1])
        right = max(first[0] + first[2], second[0] + second[2])
        bottom = max(first[1] + first[3], second[1] + second[3])
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None
        return left, top, width, height

    def _crop_direct_bar_image(
        self,
        image: np.ndarray,
        source_region: tuple[int, int, int, int],
        target_region: tuple[int, int, int, int],
    ) -> np.ndarray | None:
        source_left, source_top, source_width, source_height = source_region
        target_left, target_top, target_width, target_height = target_region
        x = target_left - source_left
        y = target_top - source_top
        if x < 0 or y < 0 or target_width <= 0 or target_height <= 0:
            return None
        if x + target_width > source_width or y + target_height > source_height:
            return None
        return image[y : y + target_height, x : x + target_width]

    def _capture_bar_percent_direct(self, bar_type: str, *, require_clear_tail: bool = False) -> float | None:
        cached = self._cached_bottom_bar_screen_regions_for_current_client()
        if cached is None:
            self._note_direct_bar_failure_reason("沒有 cached HUD geometry")
            return None
        regions, track_regions, client_bounds = cached
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            self._note_direct_bar_failure_reason("HUD geometry 不可信")
            return None
        region = track_regions.get(bar_type) or regions.get(bar_type)
        if region is None:
            self._note_direct_bar_failure_reason(f"{bar_type.upper()} direct 取色範圍缺失")
            return None

        percent, reason, tail_clear = self._sample_direct_bar_percent_from_region(
            region,
            bar_type,
            require_clear_tail=require_clear_tail,
        )
        if percent is None:
            self._note_direct_bar_failure_reason(f"{bar_type.upper()}: {reason}")
            self._set_bar_detection_debug(
                bar_type,
                source="直接取色",
                region=region,
                track_region=region,
                percent=None,
                success=False,
                reason=reason,
                require_clear_tail=require_clear_tail,
                tail_clear=tail_clear,
            )
            return None
        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = time.monotonic()
        self._remember_stable_bar_sample(bar_type, percent, region)
        self._set_bar_detection_debug(
            bar_type,
            source="直接取色",
            region=region,
            track_region=region,
            percent=percent,
            success=True,
            reason=reason,
            require_clear_tail=require_clear_tail,
            tail_clear=tail_clear,
        )
        self._record_direct_bar_success()
        return percent

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
            and self._bar_region_pair_geometry_is_valid(
                self.bottom_bar_regions,
                self.bottom_bar_track_regions,
                client_bounds,
            )
        ):
            return self.bottom_bar_regions

        old_regions = dict(getattr(self, "bottom_bar_regions", {}))
        old_track_regions = dict(getattr(self, "bottom_bar_track_regions", {}))
        old_layout = getattr(self, "bottom_hud_layout", None)
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = now

        regions: dict[str, tuple[int, int, int, int]] = {}
        detected_layout: BottomHudLayout | None = None
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
            exp_mask = self._bar_color_mask(image, "exp")
            detected_layout = self._bottom_hud_layout_from_labels(
                image,
                hp_mask=hp_mask,
                mp_mask=mp_mask,
                exp_mask=exp_mask,
                search_area=search_area,
            )
            if detected_layout is not None:
                regions = {
                    "hp": detected_layout.hp_region,
                    "mp": detected_layout.mp_region,
                }
                self.pending_bottom_bar_track_regions = {
                    "hp": detected_layout.hp_track_region,
                    "mp": detected_layout.mp_track_region,
                }
                break

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

        if regions and self._bar_region_pair_geometry_is_valid(
            regions,
            getattr(self, "pending_bottom_bar_track_regions", {}),
            client_bounds,
        ):
            self.bottom_bar_regions = regions
            self.bottom_bar_track_regions = getattr(self, "pending_bottom_bar_track_regions", {})
            self.bottom_hud_layout = detected_layout
        elif regions:
            self.bottom_bar_regions = {}
            self.bottom_bar_track_regions = {}
            self.bottom_hud_layout = None
        elif allow_stale_on_failure and cached_client_bounds == client_bounds and old_regions:
            self.bottom_bar_regions = old_regions
            self.bottom_bar_track_regions = old_track_regions
            self.bottom_hud_layout = old_layout
        else:
            self.bottom_bar_regions = {}
            self.bottom_bar_track_regions = {}
            self.bottom_bar_regions_client = {}
            self.bottom_bar_track_regions_client = {}
            self.bottom_bar_client_size = None
            self.bottom_hud_layout = None
        if self.bottom_bar_regions:
            self._cache_bottom_bar_client_regions(client_bounds)
        return self.bottom_bar_regions

    def _bottom_bar_search_areas(self, client_bounds: tuple[int, int, int, int]) -> list[HudSearchArea]:
        areas: list[HudSearchArea] = []
        client_left, client_top, client_width, client_height = client_bounds
        areas.append(self._bottom_bar_search_area_from_content_bounds(
            client_left,
            client_top,
            client_width,
            client_height,
        ))
        gameplay_left, gameplay_top, gameplay_width, gameplay_height = self._gameplay_content_bounds(client_bounds)
        if (gameplay_left, gameplay_top, gameplay_width, gameplay_height) != client_bounds:
            areas.append(self._bottom_bar_search_area_from_content_bounds(
                gameplay_left,
                gameplay_top,
                gameplay_width,
                gameplay_height,
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

    def _bottom_hud_layout_from_labels(
        self,
        image: np.ndarray,
        *,
        hp_mask: np.ndarray,
        mp_mask: np.ndarray,
        exp_mask: np.ndarray,
        search_area: HudSearchArea,
    ) -> BottomHudLayout | None:
        matches = self._hud_label_matches(image)
        if not {"hp", "mp", "exp"}.issubset(matches):
            return None
        hp_rect, hp_scale, hp_confidence = matches["hp"]
        mp_rect, mp_scale, mp_confidence = matches["mp"]
        exp_rect, exp_scale, exp_confidence = matches["exp"]
        if max(hp_scale, mp_scale, exp_scale) - min(hp_scale, mp_scale, exp_scale) > HUD_LABEL_SCALE_TOLERANCE:
            return None
        if not self._bottom_hud_label_geometry_is_valid(hp_rect, mp_rect, exp_rect, search_area.width):
            return None

        hp_track = self._bar_track_right_of_label(
            image,
            hp_mask,
            hp_rect,
            search_area.reference_width,
            search_area.reference_height,
            "hp",
        )
        mp_track = self._bar_track_right_of_label(
            image,
            mp_mask,
            mp_rect,
            search_area.reference_width,
            search_area.reference_height,
            "mp",
        )
        exp_track = self._bar_track_right_of_label(
            image,
            exp_mask,
            exp_rect,
            search_area.reference_width,
            search_area.reference_height,
            "exp",
        )
        if hp_track is None or mp_track is None or exp_track is None:
            return None

        hp_left, hp_top, hp_width, hp_height = hp_track
        mp_left, mp_top, mp_width, mp_height = mp_track
        exp_left, exp_top, exp_width, exp_height = exp_track
        if mp_left <= hp_left or exp_left < hp_left - max(8, round(hp_rect[3] * 0.5)):
            return None

        min_width = max(48, round(search_area.reference_width * 0.07))
        max_hp_mp_height = max(10, round(max(hp_rect[3], mp_rect[3]) * 0.95))
        hp_height = min(hp_height, max_hp_mp_height)
        mp_height = min(mp_height, max_hp_mp_height)
        hp_right_limit = mp_rect[0] - max(3, round(hp_rect[3] * 0.15))
        if hp_right_limit > hp_left + min_width:
            hp_width = min(hp_width, hp_right_limit - hp_left)
        if hp_width >= min_width and mp_width >= min_width:
            if hp_width > mp_width * 1.08:
                hp_width = mp_width
            elif mp_width > hp_width * 1.08:
                mp_width = hp_width
        combined_right = max(hp_left + hp_width, mp_left + mp_width)
        exp_width = max(exp_width, combined_right - exp_left)
        exp_width = min(search_area.width - exp_left, exp_width)
        if hp_width < min_width or mp_width < min_width or exp_width < min_width:
            return None
        hp_region, hp_track_region = self._full_bar_region_and_track(
            search_area.left,
            search_area.top,
            search_area.width,
            search_area.height,
            hp_left,
            hp_top,
            hp_width,
            hp_height,
        )
        mp_region, mp_track_region = self._full_bar_region_and_track(
            search_area.left,
            search_area.top,
            search_area.width,
            search_area.height,
            mp_left,
            mp_top,
            mp_width,
            mp_height,
        )

        exp_bar_region, exp_track_region = self._full_bar_region_and_track(
            search_area.left,
            search_area.top,
            search_area.width,
            search_area.height,
            exp_left,
            exp_top,
            exp_width,
            exp_height,
        )
        exp_text_region = self._experience_text_region_from_exp_track(
            image,
            search_area.left,
            search_area.top,
            (exp_left, exp_top, exp_width, exp_height),
        )
        confidence = min(hp_confidence, mp_confidence, exp_confidence)
        scale = (hp_scale + mp_scale + exp_scale) / 3.0
        return BottomHudLayout(
            hp_label_rect=self._offset_rect(hp_rect, search_area.left, search_area.top),
            mp_label_rect=self._offset_rect(mp_rect, search_area.left, search_area.top),
            exp_label_rect=self._offset_rect(exp_rect, search_area.left, search_area.top),
            hp_region=hp_region,
            mp_region=mp_region,
            exp_bar_region=exp_bar_region,
            exp_text_region=exp_text_region,
            hp_track_region=hp_track_region,
            mp_track_region=mp_track_region,
            exp_track_region=exp_track_region,
            scale=scale,
            confidence=confidence,
        )

    def _hud_label_matches(
        self,
        image: np.ndarray,
    ) -> dict[str, tuple[tuple[int, int, int, int], float, float]]:
        mask = self._hud_label_text_mask(image)
        matches: dict[str, tuple[tuple[int, int, int, int], float, float]] = {}
        for label in ("hp", "mp", "exp"):
            match = self._hud_label_match(mask, label)
            if match is None:
                continue
            rect, scale, confidence = match
            if confidence >= HUD_LABEL_MATCH_THRESHOLD:
                matches[label] = (rect, scale, confidence)
        return matches

    def _hud_label_match(
        self,
        mask: np.ndarray,
        label: str,
    ) -> tuple[tuple[int, int, int, int], float, float] | None:
        if mask.size == 0:
            return None
        best: tuple[tuple[int, int, int, int], float, float] | None = None
        scale = HUD_LABEL_SCALE_MIN
        while scale <= HUD_LABEL_SCALE_MAX + 1e-9:
            template = self._hud_label_template(label, scale)
            template_height, template_width = template.shape[:2]
            if template_height <= mask.shape[0] and template_width <= mask.shape[1]:
                result = cv2.matchTemplate(
                    mask.astype(np.float32),
                    template.astype(np.float32),
                    cv2.TM_CCOEFF_NORMED,
                )
                _min_value, max_value, _min_loc, max_loc = cv2.minMaxLoc(result)
                rect = (int(max_loc[0]), int(max_loc[1]), int(template_width), int(template_height))
                if best is None or float(max_value) > best[2]:
                    best = (rect, float(scale), float(max_value))
            scale += HUD_LABEL_SCALE_STEP
        return best

    def _hud_label_template(self, label: str, scale: float = 1.0) -> np.ndarray:
        key = f"{label}:{scale:.2f}"
        cached = _HUD_LABEL_TEMPLATE_CACHE.get(key)
        if cached is not None:
            return cached
        canvas = self._hud_label_template_source(label)
        if abs(scale - 1.0) > 1e-9:
            width = max(1, round(canvas.shape[1] * scale))
            height = max(1, round(canvas.shape[0] * scale))
            canvas = cv2.resize(canvas, (width, height), interpolation=cv2.INTER_AREA)
        _HUD_LABEL_TEMPLATE_CACHE[key] = canvas
        return canvas

    def _hud_label_template_source(self, label: str) -> np.ndarray:
        asset_path = HUD_LABEL_TEMPLATE_PATHS.get(label)
        if asset_path is not None and asset_path.exists():
            image = cv2.imread(str(asset_path), cv2.IMREAD_GRAYSCALE)
            if image is not None and image.size:
                return image
        return self._generated_hud_label_template(label)

    def _generated_hud_label_template(self, label: str) -> np.ndarray:
        text = {"hp": "HP.", "mp": "MP.", "exp": "EXP."}[label]
        font_scale = 0.62
        thickness = 2
        (text_width, text_height), baseline = cv2.getTextSize(
            text,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            thickness,
        )
        canvas = np.zeros((text_height + baseline + 8, text_width + 8), dtype=np.uint8)
        cv2.putText(
            canvas,
            text,
            (3, text_height + 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            255,
            thickness,
            cv2.LINE_AA,
        )
        ys, xs = np.nonzero(canvas)
        if xs.size and ys.size:
            top = max(0, int(ys.min()) - 1)
            bottom = min(canvas.shape[0], int(ys.max()) + 2)
            left = max(0, int(xs.min()) - 1)
            right = min(canvas.shape[1], int(xs.max()) + 2)
            canvas = canvas[top:bottom, left:right]
        return canvas

    def _hud_label_text_mask(self, image: np.ndarray) -> np.ndarray:
        bgr = image[:, :, :3].astype(np.float32)
        blue = bgr[:, :, 0]
        green = bgr[:, :, 1]
        red = bgr[:, :, 2]
        luminance = red * 0.299 + green * 0.587 + blue * 0.114
        chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
        mask = (luminance >= 135.0) & (chroma <= 95.0)
        return mask.astype(np.uint8) * 255

    def _bottom_hud_label_geometry_is_valid(
        self,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        exp_rect: tuple[int, int, int, int],
        search_width: int,
    ) -> bool:
        hp_cx = hp_rect[0] + hp_rect[2] / 2.0
        hp_cy = hp_rect[1] + hp_rect[3] / 2.0
        mp_cx = mp_rect[0] + mp_rect[2] / 2.0
        mp_cy = mp_rect[1] + mp_rect[3] / 2.0
        exp_cx = exp_rect[0] + exp_rect[2] / 2.0
        exp_cy = exp_rect[1] + exp_rect[3] / 2.0
        y_tolerance = max(hp_rect[3], mp_rect[3]) * HUD_LABEL_GEOMETRY_Y_TOLERANCE_RATIO
        if abs(hp_cy - mp_cy) > y_tolerance:
            return False
        if mp_cx <= hp_cx + max(hp_rect[2], round(search_width * 0.06)):
            return False
        if exp_cy <= hp_cy + max(4, hp_rect[3] * 0.35):
            return False
        if exp_cy - hp_cy > max(28, hp_rect[3] * 2.8):
            return False
        if abs(exp_cx - hp_cx) > max(hp_rect[2] * 1.4, round(search_width * 0.05)):
            return False
        return True

    def _bar_run_right_of_label(
        self,
        mask: np.ndarray,
        label_rect: tuple[int, int, int, int],
        client_width: int,
    ) -> tuple[int, int, int] | None:
        if mask.size == 0:
            return None
        label_left, label_top, label_width, label_height = label_rect
        label_right = label_left + label_width
        row_top = max(0, round(label_top - label_height * 0.45))
        row_bottom = min(mask.shape[0], round(label_top + label_height * 1.55))
        if row_bottom <= row_top:
            return None
        sample = mask[row_top:row_bottom, :]
        column_filled = sample.mean(axis=0) >= max(0.10, BAR_COLUMN_FILL_MIN_RATIO * 0.55)
        runs = np.flatnonzero(np.diff(np.concatenate(([False], column_filled, [False]))))
        candidates: list[tuple[int, int, int, float]] = []
        min_length = max(4, round(client_width * 0.004))
        max_left_slack = max(6, round(label_height * 0.60))
        max_search_right = min(mask.shape[1], label_right + round(mask.shape[1] * HUD_LABEL_BAR_SEARCH_RIGHT_RATIO))
        for start, end in zip(runs[::2], runs[1::2]):
            run_length = int(end - start)
            if run_length < min_length:
                continue
            if start < label_right - max_left_slack or start >= max_search_right:
                continue
            run_sample = sample[:, start:end]
            row_densities = run_sample.mean(axis=1)
            row = row_top + int(np.argmax(row_densities))
            distance = max(0, int(start) - label_right)
            score = run_length - distance * 1.5 + float(row_densities.max()) * 20.0
            candidates.append((int(start), row, run_length, score))
        if not candidates:
            return None
        best = max(candidates, key=lambda item: item[3])
        return best[0], best[1], best[2]

    def _bar_track_right_of_label(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        label_rect: tuple[int, int, int, int],
        client_width: int,
        client_height: int,
        bar_type: str,
    ) -> tuple[int, int, int, int] | None:
        color_run = self._bar_run_right_of_label(mask, label_rect, client_width)
        if color_run is None:
            return None

        run_start, run_row, run_length = color_run
        fallback_height = max(10, min(22, round(client_height * 0.015)))
        track_top, track_height = self._bar_vertical_bounds(
            mask,
            run_start,
            run_length,
            run_row,
            image.shape[0],
            fallback_height,
        )

        sample_top = max(0, track_top - 1)
        sample_bottom = min(image.shape[0], track_top + track_height + 1)
        if sample_bottom <= sample_top:
            return None

        track_like = self._bar_track_like_mask(image, mask, bar_type)
        column_like = track_like[sample_top:sample_bottom, :].mean(axis=0) >= 0.35
        column_like = self._close_column_gaps(column_like, max(2, round(client_width * 0.003)))
        if not bool(column_like.any()):
            return None

        label_left, _label_top, label_width, label_height = label_rect
        label_right = label_left + label_width
        max_left_slack = max(6, round(label_height * 0.60))
        max_search_right = min(
            image.shape[1],
            label_right + round(image.shape[1] * HUD_LABEL_BAR_SEARCH_RIGHT_RATIO),
        )
        min_width = max(48, round(client_width * 0.07))
        max_width = max(min_width + 1, round(client_width * 0.20))
        left_expansion = max(1, round(client_width * 0.0015))

        run_edges = np.flatnonzero(np.diff(np.concatenate(([False], column_like, [False]))))
        candidates: list[tuple[int, int, float]] = []
        for start, end in zip(run_edges[::2], run_edges[1::2]):
            if end <= label_right - max_left_slack or start >= max_search_right:
                continue
            if run_start < start - max_left_slack or run_start >= end + max_left_slack:
                continue
            track_left = max(int(start), run_start - left_expansion)
            track_right = min(int(end), track_left + max_width)
            track_width = track_right - track_left
            if track_width < min_width:
                continue
            color_coverage = float(mask[sample_top:sample_bottom, track_left:track_right].mean())
            distance = max(0, track_left - label_right)
            score = track_width - distance * 0.4 + color_coverage * 120.0
            candidates.append((track_left, track_width, score))

        if not candidates:
            return None
        track_left, track_width, _score = max(candidates, key=lambda item: item[2])
        track_top, track_height = self._track_vertical_bounds_from_track_mask(
            track_like,
            track_left,
            track_width,
            track_top,
            track_height,
            client_height,
        )
        return track_left, track_top, track_width, track_height

    def _bar_track_like_mask(self, image: np.ndarray, color_mask: np.ndarray, bar_type: str) -> np.ndarray:
        bgr = image[:, :, :3].astype(np.float32)
        blue = bgr[:, :, 0]
        green = bgr[:, :, 1]
        red = bgr[:, :, 2]
        luminance = red * 0.299 + green * 0.587 + blue * 0.114
        chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
        neutral_track = (luminance >= 35.0) & (luminance <= 145.0) & (chroma <= 70.0)
        red_body = (red >= 115.0) & (red > green + 25.0) & (red > blue + 25.0)
        blue_body = (blue >= 115.0) & (blue > red + 20.0) & (green >= 45.0)
        green_body = (green >= 110.0) & (green > blue + 20.0) & (red <= 230.0)
        if bar_type == "hp":
            loose_bar_body = red_body
        elif bar_type == "mp":
            loose_bar_body = blue_body
        elif bar_type == "exp":
            loose_bar_body = green_body
        else:
            loose_bar_body = red_body | blue_body | green_body
        if color_mask.shape == neutral_track.shape:
            return neutral_track | loose_bar_body | color_mask
        return neutral_track | loose_bar_body

    def _track_vertical_bounds_from_track_mask(
        self,
        track_like: np.ndarray,
        track_left: int,
        track_width: int,
        current_top: int,
        current_height: int,
        client_height: int,
    ) -> tuple[int, int]:
        if track_like.size == 0 or track_width <= 0 or current_height <= 0:
            return current_top, current_height

        sample_left = max(0, min(track_like.shape[1] - 1, track_left))
        sample_right = max(sample_left + 1, min(track_like.shape[1], track_left + track_width))
        row_like = track_like[:, sample_left:sample_right].mean(axis=1) >= 0.28
        row_like = self._close_column_gaps(row_like, max(1, round(client_height * 0.002)))

        center = max(0, min(row_like.size - 1, current_top + current_height // 2))
        if not bool(row_like[center]):
            search_top = max(0, current_top - current_height)
            search_bottom = min(row_like.size, current_top + current_height * 2)
            nearby = np.flatnonzero(row_like[search_top:search_bottom])
            if nearby.size == 0:
                return current_top, current_height
            center = search_top + int(nearby[np.argmin(np.abs(nearby - (center - search_top)))])

        top = center
        while top > 0 and row_like[top - 1]:
            top -= 1
        bottom = center
        while bottom + 1 < row_like.size and row_like[bottom + 1]:
            bottom += 1

        expanded_height = bottom - top + 1
        max_height = max(current_height + 6, round(client_height * 0.035))
        if expanded_height > max_height:
            return current_top, current_height
        return top, max(current_height, expanded_height)

    def _close_column_gaps(self, columns: np.ndarray, max_gap: int) -> np.ndarray:
        if columns.size == 0 or max_gap <= 0:
            return columns
        closed = columns.copy()
        edges = np.flatnonzero(np.diff(np.concatenate(([False], columns, [False]))))
        for gap_start, gap_end in zip(edges[1::2], edges[2::2]):
            if gap_end - gap_start <= max_gap:
                closed[gap_start:gap_end] = True
        return closed

    def _experience_text_region_from_exp_track(
        self,
        image: np.ndarray,
        search_left: int,
        search_top: int,
        exp_track: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        track_left, track_top, track_width, track_height = exp_track
        if track_width <= 0 or track_height <= 0:
            return None
        horizontal_padding = max(6, round(track_height * 0.50))
        vertical_padding = max(3, round(track_height * 0.45))
        text_search_left = min(
            image.shape[1] - 1,
            max(0, track_left + round(track_width * 0.35)),
        )
        text_search_right = min(
            image.shape[1],
            track_left + track_width,
        )
        left = max(0, track_left)
        top = max(0, track_top - vertical_padding)
        right = text_search_right
        bottom = min(image.shape[0], track_top + track_height + vertical_padding)
        base_top = top
        if right <= text_search_left or bottom <= top:
            return None

        crop = image[top:bottom, text_search_left:text_search_right, :3].astype(np.float32)
        blue = crop[:, :, 0]
        green = crop[:, :, 1]
        red = crop[:, :, 2]
        luminance = red * 0.299 + green * 0.587 + blue * 0.114
        chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
        text_mask = (luminance >= 190.0) & (chroma <= 60.0)
        text_mask = self._exp_text_glyph_mask(text_mask, track_height)
        ys, xs = np.nonzero(text_mask)
        if not xs.size or not ys.size:
            return None

        glyph_left = text_search_left + int(xs.min())
        glyph_right = text_search_left + int(xs.max()) + 1
        left_padding = max(horizontal_padding * 2, round(track_height * 1.20))
        left = max(track_left, glyph_left - left_padding)
        right = min(text_search_right, glyph_right + horizontal_padding)
        glyph_top = top + int(ys.min())
        glyph_bottom = top + int(ys.max()) + 1
        text_vertical_padding = max(2, round(track_height * 0.20))
        top = max(base_top, glyph_top - text_vertical_padding)
        bottom = min(image.shape[0], glyph_bottom + text_vertical_padding)
        if right - left < 20 or bottom - top < 8:
            return None
        return (
            search_left + left,
            search_top + top,
            right - left,
            bottom - top,
        )

    def _exp_text_glyph_mask(self, text_mask: np.ndarray, track_height: int) -> np.ndarray:
        if text_mask.size == 0:
            return text_mask
        component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            text_mask.astype(np.uint8),
            connectivity=8,
        )
        glyph_mask = np.zeros_like(text_mask, dtype=bool)
        min_height = max(3, round(track_height * 0.25))
        min_area = max(3, round(track_height * 0.12))
        thin_line_height = max(5, round(track_height * 0.55))
        for label in range(1, component_count):
            left, top, width, height, area = (int(value) for value in stats[label])
            if area < min_area or height < min_height:
                continue
            if width <= 2 and height >= thin_line_height:
                continue
            glyph_mask[labels == label] = True
        return glyph_mask

    def _offset_rect(
        self,
        rect: tuple[int, int, int, int],
        offset_x: int,
        offset_y: int,
    ) -> tuple[int, int, int, int]:
        return rect[0] + offset_x, rect[1] + offset_y, rect[2], rect[3]

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
        min_pair_row = round(search_height * BAR_PAIR_MIN_SEARCH_ROW_RATIO)

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
                average_row = (hp_row + mp_row) / 2
                if average_row < min_pair_row:
                    continue
                gap = mp_start - hp_start
                if gap < min_gap or gap > max_gap:
                    continue
                score = hp_length + mp_length + average_row * 0.5 - y_delta * 8
                if best_pair is None or score > best_pair[2]:
                    best_pair = ((hp_start, hp_row, hp_length), (mp_start, mp_row, mp_length), score)

        if best_pair is None:
            inferred_regions = self._infer_bottom_bar_pair_regions_from_hp_candidate(
                hp_candidates,
                hp_mask=hp_mask,
                mp_mask=mp_mask,
                search_left=search_left,
                search_top=search_top,
                search_width=search_width,
                search_height=search_height,
                client_width=client_width,
                client_height=client_height,
                reference_left=reference_left,
                min_gap=min_gap,
                max_gap=max_gap,
                max_hp_left=max_hp_left,
                min_pair_row=min_pair_row,
            )
            if inferred_regions:
                return inferred_regions
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

    def _infer_bottom_bar_pair_regions_from_hp_candidate(
        self,
        hp_candidates: list[tuple[int, int, int]],
        *,
        hp_mask: np.ndarray | None,
        mp_mask: np.ndarray | None,
        search_left: int,
        search_top: int,
        search_width: int,
        search_height: int,
        client_width: int,
        client_height: int,
        reference_left: int,
        min_gap: int,
        max_gap: int,
        max_hp_left: int,
        min_pair_row: int,
    ) -> dict[str, tuple[int, int, int, int]]:
        min_infer_length = max(BAR_SEARCH_MIN_RUN_PIXELS * 2, round(client_width * 0.06))
        eligible_hp = [
            candidate
            for candidate in hp_candidates
            if candidate[1] >= min_pair_row
            and candidate[2] >= min_infer_length
            and search_left - reference_left + candidate[0] <= max_hp_left
        ]
        if not eligible_hp:
            return {}

        hp_start, hp_row, hp_length = max(
            eligible_hp,
            key=lambda candidate: (candidate[2], candidate[1], -candidate[0]),
        )
        expected_gap = max(min_gap, min(max_gap, round(client_width * 0.16)))
        mp_start = hp_start + expected_gap
        if mp_start <= hp_start or mp_start >= search_width:
            return {}

        min_width = max(48, round(client_width * 0.07))
        max_width = max(min_width + 1, round(client_width * 0.20))
        region_width = max(min_width, min(max_width, round(expected_gap * 0.82), hp_length))
        if mp_start + max(1, round(region_width * 0.35)) > search_width:
            return {}

        margin_left = max(2, round(region_width * 0.015))
        fallback_height = max(10, min(22, round(client_height * 0.015)))
        hp_top, hp_height = self._bar_vertical_bounds(
            hp_mask,
            hp_start,
            hp_length,
            hp_row,
            search_height,
            fallback_height,
        )
        mp_top, mp_height = self._bar_vertical_bounds(
            mp_mask,
            mp_start,
            region_width,
            hp_row,
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
        vertical_padding = max(2, min(3, round(track_height * BAR_FULL_REGION_VERTICAL_PADDING_RATIO)))

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
            track_region=track_region,
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
        percent, reason, tail_clear = self._percent_from_bar_mask_result(
            percent_mask,
            percent_image,
            require_clear_tail,
        )
        if (
            percent is None
            and track_region is not None
            and reason == "找不到符合顏色的填滿欄位"
            and self._bar_track_looks_empty(percent_mask, percent_image)
        ):
            return 0.0, "OK:EmptyTrack", True if require_clear_tail and percent_image is not None else tail_clear
        return percent, reason, tail_clear

    def _sample_direct_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        *,
        require_clear_tail: bool = False,
    ) -> tuple[float | None, str, bool | None]:
        image = self._direct_bar_image_from_region(region)
        if image is None:
            return None, "直接取色讀取畫面失敗", None

        return self._sample_direct_bar_percent_from_image(image, bar_type)

    def _sample_direct_bar_percent_from_image(
        self,
        image: np.ndarray,
        bar_type: str,
    ) -> tuple[float | None, str, bool | None]:
        mask = self._direct_bar_color_mask(image, bar_type)
        percent, reason, tail_clear = self._percent_from_bar_mask_result(
            mask,
            image,
            require_clear_tail=False,
        )
        if percent is None:
            clamped = self._direct_bar_track_like_crop(image, mask, bar_type)
            if clamped is not None:
                clamped_image, crop_reason = clamped
                clamped_mask = self._direct_bar_color_mask(clamped_image, bar_type)
                percent, clamped_reason, tail_clear = self._percent_from_bar_mask_result(
                    clamped_mask,
                    clamped_image,
                    require_clear_tail=False,
                )
                if percent is not None:
                    if clamped_reason == "OK":
                        return percent, f"OK:DirectClamp:{crop_reason}", tail_clear
                    if clamped_reason == "OK:FullWidth":
                        return percent, f"OK:DirectClampFullWidth:{crop_reason}", tail_clear
                else:
                    reason = f"{reason}；clamp={clamped_reason}"
        if (
            percent is None
            and reason == "找不到符合顏色的填滿欄位"
            and self._bar_track_looks_empty(mask, image)
        ):
            return 0.0, "OK:EmptyTrack", None
        if percent is None:
            return None, f"直接取色{reason}", tail_clear
        if reason == "OK":
            reason = "OK:Direct"
        elif reason == "OK:FullWidth":
            reason = "OK:DirectFullWidth"
        return percent, reason, tail_clear

    def _direct_bar_track_like_crop(
        self,
        image: np.ndarray,
        color_mask: np.ndarray,
        bar_type: str,
    ) -> tuple[np.ndarray, str] | None:
        if image.size == 0 or color_mask.size == 0 or not bool(color_mask.any()):
            return None

        height, width = color_mask.shape
        if height <= 2 or width <= 8:
            return None

        track_like = self._bar_track_like_mask(image, color_mask, bar_type)
        if track_like.shape != color_mask.shape:
            return None

        row_like = track_like.mean(axis=1) >= 0.28
        row_like = self._close_column_gaps(row_like, max(1, round(height * 0.12)))
        row_edges = np.flatnonzero(np.diff(np.concatenate(([False], row_like, [False]))))
        if row_edges.size < 2:
            return None

        min_rows = min(max(3, BAR_MIN_BODY_ROW_COUNT), height)
        row_runs: list[tuple[int, int, float]] = []
        for start, end in zip(row_edges[::2], row_edges[1::2]):
            if end - start < min_rows:
                continue
            density = float(track_like[start:end, :].mean())
            row_runs.append((int(start), int(end), density))
        if not row_runs:
            return None
        row_start, row_end, _density = max(row_runs, key=lambda item: (item[1] - item[0], item[2]))

        band_like = track_like[row_start:row_end, :]
        band_color = color_mask[row_start:row_end, :]
        column_like = band_like.mean(axis=0) >= 0.30
        column_like = self._close_column_gaps(column_like, max(2, round(width * 0.015)))
        column_edges = np.flatnonzero(np.diff(np.concatenate(([False], column_like, [False]))))
        if column_edges.size < 2:
            return None

        min_width = min(width, max(24, round(width * 0.45)))
        candidates: list[tuple[int, int, float]] = []
        for start, end in zip(column_edges[::2], column_edges[1::2]):
            run_width = int(end - start)
            if run_width < min_width:
                continue
            color_coverage = float(band_color[:, start:end].mean())
            if color_coverage <= 0.0:
                continue
            trim_score = (start / max(1, width)) + ((width - end) / max(1, width))
            score = run_width + color_coverage * 100.0 + trim_score * 20.0
            candidates.append((int(start), int(end), score))
        if not candidates:
            return None

        col_start, col_end, _score = max(candidates, key=lambda item: item[2])
        if col_start == 0 and col_end == width and row_start == 0 and row_end == height:
            return None

        cropped = image[row_start:row_end, col_start:col_end]
        if cropped.size == 0:
            return None
        return cropped, f"x={col_start}-{col_end},y={row_start}-{row_end}"

    def _direct_bar_image_from_region(self, region: tuple[int, int, int, int]) -> np.ndarray | None:
        left, top, width, height = region
        if width <= 0 or height <= 0:
            return None

        context = getattr(self, "direct_bar_capture_context", None)
        if context is None:
            context = DirectBarCaptureContext()
            self.direct_bar_capture_context = context
        return context.capture(left, top, width, height)

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

        rightmost_filled_percent = float((int(filled_indexes[-1]) + 1) / width * 100.0)
        if (
            rightmost_filled_percent >= FULL_BAR_SNAP_PERCENT
            and float(column_filled.mean()) >= BAR_FULL_WIDTH_MIN_COLUMN_RATIO
            and self._bar_run_has_horizontal_body(mask, 0, width - 1)
        ):
            return 100.0, "OK:FullWidth", True if require_clear_tail and image is not None else None

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

    def _bar_track_looks_empty(self, mask: np.ndarray, image: np.ndarray | None) -> bool:
        if mask.size == 0:
            return False
        if bool(mask.any()):
            return False
        if image is None or image.size == 0:
            return True
        bgr = image[:, :, :3].astype(np.float32)
        luminance = bgr[:, :, 2] * 0.299 + bgr[:, :, 1] * 0.587 + bgr[:, :, 0] * 0.114
        chroma = np.max(bgr, axis=2) - np.min(bgr, axis=2)
        neutral_track = (luminance < 150.0) & (chroma < 90.0)
        foreground_detail = (luminance >= 170.0) | (chroma >= 95.0)
        neutral_ratio = float(neutral_track.mean())
        foreground_ratio = float(foreground_detail.mean())
        return (
            neutral_ratio >= BAR_EMPTY_TRACK_MIN_NEUTRAL_RATIO
            and foreground_ratio <= BAR_EMPTY_TRACK_MAX_FOREGROUND_RATIO
        )

    def _set_bar_detection_debug(
        self,
        bar_type: str,
        *,
        source: str,
        region: tuple[int, int, int, int] | None,
        track_region: tuple[int, int, int, int] | None = None,
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
            track_region=track_region,
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
        source = self._compact_bar_debug_source(debug.source)
        tail = ""
        if debug.require_clear_tail:
            tail = " | tail=OK" if debug.tail_clear else " | tail=FAIL"
        return f"{label}: {source} | {percent} | {debug.reason}{tail}"

    def _compact_bar_debug_source(self, source: str) -> str:
        return {
            "直接取色": "直取",
            "自動定位": "定位",
        }.get(source, source)

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
                preview_region = debug.track_region or debug.region
                left, top, width, height = preview_region or (0, 0, 0, 0)
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
                        preview_region or (left, top, width, height),
                        mask,
                        image,
                        None if debug.track_region is not None else track_region,
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
        target_window_provider = getattr(self, "target_window_provider", None)
        if target_window_provider is not None:
            try:
                hwnd = int(target_window_provider() or 0)
                if hwnd:
                    self.last_target_hwnd = hwnd
                    return hwnd
            except Exception:
                pass
        return getattr(self, "last_target_hwnd", 0)

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
        primary = candidates[:80]
        primary_keys = set(primary)
        bottom_row_min = round(mask.shape[0] * 0.65)
        bottom_candidates = [
            candidate
            for candidate in candidates[80:]
            if candidate not in primary_keys and candidate[1] >= bottom_row_min
        ]
        bottom_candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
        return primary + bottom_candidates[:80]

    def _bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        bgra = image[:, :, :3]
        blue = bgra[:, :, 0].astype(np.int16)
        green = bgra[:, :, 1].astype(np.int16)
        red = bgra[:, :, 2].astype(np.int16)

        if bar_type == "hp":
            return (red > 150) & (green < 120) & (blue < 150) & (red > green + 40) & (red > blue + 40)
        if bar_type == "mp":
            return (blue > 140) & (green > 75) & (red < 140) & (blue > red + 35)
        return (green > 130) & (red < 170) & (blue < 170) & (green > red + 25) & (green > blue + 25)

    def _direct_bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        mask = self._bar_color_mask(image, bar_type)
        if bar_type != "hp":
            return mask

        bgra = image[:, :, :3]
        blue = bgra[:, :, 0].astype(np.int16)
        green = bgra[:, :, 1].astype(np.int16)
        red = bgra[:, :, 2].astype(np.int16)
        damage_flash = (
            (red > 180)
            & (green < 215)
            & (blue < 215)
            & (red > green + 25)
            & (red > blue + 25)
        )
        return mask | damage_flash

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
            pause_reason = "偵測到頻道切換載入頁，暫停自動操作"
        elif self._is_transition_fade_active():
            pause_reason = "偵測到地圖過場暗幕，暫停自動操作"

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
            hwnd = self._target_window_handle()
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

    def _target_client_bounds(self) -> tuple[int, int, int, int] | None:
        hwnd = self._target_window_handle()
        if not hwnd or not is_valid_window(hwnd):
            return None
        try:
            return self._client_bounds_for_window(hwnd)
        except Exception:
            return None

    def _client_bounds_for_window(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())

        client_width = rect.right - rect.left
        client_height = rect.bottom - rect.top
        if client_width <= 0 or client_height <= 0:
            raise RuntimeError("視窗 client area 尺寸無效")

        origin = Point(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise ctypes.WinError(ctypes.get_last_error())

        return origin.x, origin.y, client_width, client_height

    def cleanup(self) -> None:
        self._release_pickup_key()
        self._release_all_potion_keys()
        runtime = getattr(self, "runtime_processes", None)
        if runtime is not None:
            runtime.stop()
            self.runtime_processes = None
        self._unregister_toggle_hotkey()
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.stop()
        potion_worker = getattr(self, "potion_action_worker", None)
        if potion_worker is not None:
            potion_worker.stop()
        mouse_observer = getattr(self, "mouse_activity_observer", None)
        if mouse_observer is not None:
            stop_mouse_observer = getattr(mouse_observer, "stop", None)
            if callable(stop_mouse_observer):
                stop_mouse_observer()
            self.mouse_activity_observer = None
        self._close_media_files()
        direct_capture_context = getattr(self, "direct_bar_capture_context", None)
        if direct_capture_context is not None:
            try:
                direct_capture_context.close()
            except Exception:
                pass
        try:
            self.experience_ocr_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        if getattr(self, "save_settings_on_cleanup", True):
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

    def _close_media_files(self) -> None:
        alias_paths = getattr(self, "_media_alias_paths", None)
        if not isinstance(alias_paths, dict) or not alias_paths:
            return
        try:
            winmm = ctypes.windll.winmm
            buffer = ctypes.create_unicode_buffer(256)
            for alias in tuple(alias_paths):
                self._close_media_alias(winmm, buffer, alias)
        except Exception:
            alias_paths.clear()
