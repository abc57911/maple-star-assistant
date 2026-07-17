from __future__ import annotations

import ctypes
import contextlib
import math
import multiprocessing as mp
import sys
import threading
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
    BAR_COLUMN_FILL_MIN_RATIO,
    BAR_CONFIRM_CAPTURE_ATTEMPTS,
    BAR_CONFIRM_FALLBACK_MAX_DELTA_PERCENT,
    BAR_CONFIRM_RETRY_DELAY_SECONDS,
    BAR_DYNAMIC_SEARCH_HEIGHT_RATIO,
    BAR_DYNAMIC_SEARCH_LEFT_RATIO,
    BAR_DYNAMIC_SEARCH_TOP_RATIO,
    BAR_DYNAMIC_SEARCH_WIDTH_RATIO,
    BAR_FULL_REGION_LEFT_PADDING_RATIO,
    BAR_FULL_REGION_RIGHT_PADDING_RATIO,
    BAR_FULL_REGION_VERTICAL_PADDING_RATIO,
    BAR_MIN_BODY_ROW_COUNT,
    BAR_MIN_BODY_ROW_DENSITY,
    BAR_PAIR_CACHE_SECONDS,
    BAR_PAIR_MIN_SEARCH_ROW_RATIO,
    BAR_SEARCH_MIN_RUN_PIXELS,
    BAR_TRANSIENT_CAPTURE_ATTEMPTS,
    BAR_TRANSIENT_RETRY_DELAY_SECONDS,
    BAR_UNSTABLE_LOG_INTERVAL_SECONDS,
    BAR_VERTICAL_BODY_ROW_DENSITY,
    DEFAULT_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
    EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
    FADE_GUARD_RECOVERY_SECONDS,
    FADE_GUARD_REQUIRED_FRAMES,
    GAME_CONTENT_ASPECT_RATIO,
    GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS,
    PICKUP_HUD_REFRESH_INTERVAL_SECONDS,
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
    LIE_DETECTOR_ALERT_BEEP_PATTERN,
    PAUSE_BEEP_PATTERN,
    RESUME_BEEP_PATTERN,
    SETTINGS_SAVE_DEBOUNCE_SECONDS,
)
from ..adapters.debug_logging import log_debug, log_exception, log_experience_debug
from ..services.control_hotkey_worker import (
    CONTROL_HOTKEY_EMERGENCY_STOP,
    CONTROL_HOTKEY_EXPERIENCE_RESET,
    CONTROL_HOTKEY_EXPERIENCE_TOGGLE,
    CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE,
    CONTROL_HOTKEY_PICKUP_TOGGLE,
    CONTROL_HOTKEY_TOGGLE,
)
from ..services.control_hotkey_coordinator import (
    ControlHotkeyCallbacks,
    ControlHotkeyCoordinator,
    ControlHotkeyFeatureSnapshot,
    ControlHotkeySettingsSnapshot,
)
from ..services.experience_capture_coordinator import ExperienceCaptureCoordinator
from ..services.potion_action_worker import PotionAction, PotionActionWorker
from ..services.controller_collaborator_api import ControllerModuleAdapters, RuntimeMediaSink
from ..services.media_playback import (
    AUTO_DRINK_POTION_CHECK_SOUND_PATH,
    AUTO_DRINK_START_SOUND_PATH,
    AUTO_DRINK_STOP_SOUND_PATH,
    AUTO_PICKUP_START_SOUND_PATH,
    AUTO_PICKUP_STOP_SOUND_PATH,
    LIE_DETECTOR_ALERT_SOUND_PATH,
    MEDIA_SOUND_PATH_BY_ALIAS,
    MINIMAP_CRUISE_START_WAV_PATH,
    MINIMAP_CRUISE_STOP_WAV_PATH,
    MediaPlaybackService,
)
from ..services.runtime_api import (
    ControlCommand,
    ExperienceControl,
    ExperienceStatus,
    InlineExecutor,
    PotionControl,
    PotionStatus,
    RuntimeProcessFactory,
    RuntimeProcessPort,
    WorkerCrashed,
    _experience_status_signature,
    _potion_status_signature,
)
from ..services.screen_capture import ScreenCaptureService
from ..services.hud_bar_detector import DirectBarCaptureContext, HudBarDetector, HudDetectionRequest
from ..services.potion_engine import (
    PotionBarConfig,
    PotionCommand as PotionEngineCommand,
    PotionCommandResult,
    PotionEngine,
    PotionSample,
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
POTION_TIME_EPSILON_SECONDS = 1e-9
POTION_PENDING_SEND_CAPTURE_GUARD_SECONDS = 0.20
POTION_EXPERIENCE_DEFER_SECONDS = 1.0
POTION_BLOCKED_SOUND_INTERVAL_SECONDS = 3.0
POTION_CHECK_SOUND_INTERVAL_SECONDS = 10.0
RUNTIME_POTION_STATUS_TIMEOUT_SECONDS = 2.0
DIRECT_BAR_FAILURE_WARNING_ATTEMPTS = 3


def _controller_module_adapters() -> ControllerModuleAdapters:
    return ControllerModuleAdapters(
        monotonic=lambda: time.monotonic(),
        sleep=lambda seconds: time.sleep(seconds),
        thread_factory=lambda *args, **kwargs: threading.Thread(*args, **kwargs),
        winmm_provider=lambda: ctypes.windll.winmm,
        user32_provider=lambda: user32,
        beep=lambda frequency, duration_ms: winsound.Beep(frequency, duration_ms),
        message_beep=lambda *args, **kwargs: winsound.MessageBeep(*args, **kwargs),
        play_sound=lambda *args, **kwargs: winsound.PlaySound(*args, **kwargs),
        key_down=lambda vk: key_down(vk),
        key_up=lambda vk: key_up(vk),
        tap_hotkey=lambda *args, **kwargs: tap_hotkey(*args, **kwargs),
        save_settings=lambda *args, **kwargs: save_settings(*args, **kwargs),
    )
RECENT_HUD_GEOMETRY_GRACE_SECONDS = 2.0
STAT_WINDOW_EXP_LABEL_TEMPLATE_MATCH_THRESHOLD = 0.80
STAT_WINDOW_EXP_LABEL_TEMPLATE_PATH = PROJECT_ROOT / "maple_star" / "assets" / "stat_window_exp_label.png"
HUD_LABEL_TEMPLATE_PATHS = {
    "hp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_hp.png",
    "mp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_mp.png",
    "exp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_exp.png",
}
_STAT_WINDOW_EXP_LABEL_TEMPLATE: np.ndarray | None = None


class _CoordinatorField:
    def __init__(self, coordinator_name: str) -> None:
        self.coordinator_name = coordinator_name

    def __get__(self, instance: object, owner: type | None = None) -> object:
        if instance is None:
            return self
        return getattr(instance._hotkey_coordinator(), self.coordinator_name)

    def __set__(self, instance: object, value: object) -> None:
        setattr(instance._hotkey_coordinator(), self.coordinator_name, value)


class _ScreenCaptureBackendField:
    def __get__(self, instance: object, owner: type | None = None) -> object:
        if instance is None:
            return self
        return instance._screen_capture_service().backend

    def __set__(self, instance: object, value: object) -> None:
        service = getattr(instance, "screen_capture_service", None)
        if service is None:
            instance.screen_capture_service = ScreenCaptureService.from_backend(value)
            service = instance.screen_capture_service
        else:
            service.replace_backend(value)
        detector = getattr(instance, "hud_bar_detector", None)
        if detector is not None:
            detector.screen_capture = service
        experience_capture = getattr(instance, "experience_capture_coordinator", None)
        if experience_capture is not None:
            experience_capture.screen_capture = service


class _HudField:
    def __init__(self, detector_name: str) -> None:
        self.detector_name = detector_name

    def __get__(self, instance: object, owner: type | None = None) -> object:
        if instance is None:
            return self
        return getattr(instance._hud_detector(), self.detector_name)

    def __set__(self, instance: object, value: object) -> None:
        setattr(instance._hud_detector(), self.detector_name, value)


class _PotionField:
    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    def __get__(self, instance: object, owner: type | None = None) -> object:
        if instance is None:
            return self
        return getattr(instance._potion_engine(), self.engine_name)

    def __set__(self, instance: object, value: object) -> None:
        setattr(instance._potion_engine(), self.engine_name, value)


class _ExperienceCaptureField:
    def __init__(self, coordinator_name: str) -> None:
        self.coordinator_name = coordinator_name

    def __get__(self, instance: object, owner: type | None = None) -> object:
        if instance is None:
            return self
        return getattr(instance._experience_capture(), self.coordinator_name)

    def __set__(self, instance: object, value: object) -> None:
        setattr(instance._experience_capture(), self.coordinator_name, value)


class AutoPotionController:
    experience_ocr_executor = _ExperienceCaptureField("executor")
    next_experience_capture_at = _ExperienceCaptureField("next_capture_at")
    experience_ocr_job = _ExperienceCaptureField("ocr_job")
    experience_ocr_burst = _ExperienceCaptureField("ocr_burst")
    experience_baseline_calibration = _ExperienceCaptureField("baseline_calibration")
    experience_baseline_ocr_job = _ExperienceCaptureField("baseline_ocr_job")
    experience_baseline_calibration_attempts = _ExperienceCaptureField("baseline_calibration_attempts")
    next_experience_baseline_calibration_at = _ExperienceCaptureField("next_baseline_calibration_at")
    experience_tooltip_baseline_failed = _ExperienceCaptureField("tooltip_baseline_failed")
    experience_initial_tooltip_baseline_started_at = _ExperienceCaptureField(
        "initial_tooltip_baseline_started_at"
    )
    experience_10m_checkpoint_capture = _ExperienceCaptureField("checkpoint_capture")
    experience_10m_checkpoint_ocr_job = _ExperienceCaptureField("checkpoint_ocr_job")
    next_experience_10m_checkpoint_at = _ExperienceCaptureField("next_checkpoint_at")
    experience_10m_checkpoint_stopped = _ExperienceCaptureField("checkpoint_stopped")
    experience_10m_checkpoint_attempts = _ExperienceCaptureField("checkpoint_attempts")
    experience_10m_checkpoint_tooltip_failed = _ExperienceCaptureField("checkpoint_tooltip_failed")
    experience_baseline_cursor_position = _ExperienceCaptureField("baseline_cursor_position")
    last_completed_experience_ocr_signature = _ExperienceCaptureField("last_completed_signature")
    last_failed_experience_ocr_signature = _ExperienceCaptureField("last_failed_signature")
    runtime_potion_action_defer_until = _PotionField("runtime_potion_action_defer_until")
    potion_send_prevalidated_at = _PotionField("potion_send_prevalidated_at")
    last_hp_drink_at = _PotionField("last_hp_drink_at")
    last_mp_drink_at = _PotionField("last_mp_drink_at")
    hp_pending_potion_send_at = _PotionField("hp_pending_potion_send_at")
    mp_pending_potion_send_at = _PotionField("mp_pending_potion_send_at")
    hp_pending_potion_send_percent = _PotionField("hp_pending_potion_send_percent")
    mp_pending_potion_send_percent = _PotionField("mp_pending_potion_send_percent")
    hp_potion_effect_attempts = _PotionField("hp_potion_effect_attempts")
    mp_potion_effect_attempts = _PotionField("mp_potion_effect_attempts")
    hp_potion_no_effect_count = _PotionField("hp_potion_no_effect_count")
    mp_potion_no_effect_count = _PotionField("mp_potion_no_effect_count")
    hp_potion_last_no_effect_counted_at = _PotionField("hp_potion_last_no_effect_counted_at")
    mp_potion_last_no_effect_counted_at = _PotionField("mp_potion_last_no_effect_counted_at")
    hp_potion_last_observed_percent = _PotionField("hp_potion_last_observed_percent")
    mp_potion_last_observed_percent = _PotionField("mp_potion_last_observed_percent")
    hp_potion_recent_samples = _PotionField("hp_potion_recent_samples")
    mp_potion_recent_samples = _PotionField("mp_potion_recent_samples")
    hp_potion_recent_damage_at = _PotionField("hp_potion_recent_damage_at")
    mp_potion_recent_damage_at = _PotionField("mp_potion_recent_damage_at")
    hp_potion_damage_pressure_active = _PotionField("hp_potion_damage_pressure_active")
    mp_potion_damage_pressure_active = _PotionField("mp_potion_damage_pressure_active")
    hp_out_of_potion_hold = _PotionField("hp_out_of_potion_hold")
    mp_out_of_potion_hold = _PotionField("mp_out_of_potion_hold")
    hp_potion_held_vk = _PotionField("hp_potion_held_vk")
    mp_potion_held_vk = _PotionField("mp_potion_held_vk")
    hp_potion_hold_refreshed_at = _PotionField("hp_potion_hold_refreshed_at")
    mp_potion_hold_refreshed_at = _PotionField("mp_potion_hold_refreshed_at")
    last_potion_blocked_sound_at = _PotionField("last_potion_blocked_sound_at")
    last_potion_check_sound_at = _PotionField("last_potion_check_sound_at")
    sct = _ScreenCaptureBackendField()
    direct_bar_capture_context = _HudField("direct_capture_context")
    stable_bar_samples = _HudField("stable_bar_samples")
    bottom_bar_regions = _HudField("bottom_bar_regions")
    bottom_bar_track_regions = _HudField("bottom_bar_track_regions")
    bottom_bar_regions_client = _HudField("bottom_bar_regions_client")
    bottom_bar_track_regions_client = _HudField("bottom_bar_track_regions_client")
    bottom_bar_client_size = _HudField("bottom_bar_client_size")
    bottom_hud_layout = _HudField("bottom_hud_layout")
    bottom_bar_regions_at = _HudField("bottom_bar_regions_at")
    bottom_bar_client_bounds = _HudField("bottom_bar_client_bounds")
    pending_bottom_bar_track_regions = _HudField("pending_bottom_bar_track_regions")
    last_bar_debug = _HudField("last_bar_debug")
    direct_bar_failure_count = _HudField("direct_bar_failure_count")
    last_direct_bar_failure_warning_at = _HudField("last_direct_bar_failure_warning_at")
    last_direct_bar_failure_reason = _HudField("last_direct_bar_failure_reason")
    fade_guard_hits = _HudField("fade_guard_hits")
    fade_guard_until = _HudField("fade_guard_until")
    control_hotkeys_enabled = _CoordinatorField("enabled")
    control_hotkey_worker = _CoordinatorField("worker")
    control_hotkey_worker_events_enabled = _CoordinatorField("events_enabled")
    hotkey_registered = _CoordinatorField("hotkey_registered")
    emergency_hotkey_registered = _CoordinatorField("emergency_hotkey_registered")
    experience_toggle_hotkey_registered = _CoordinatorField("experience_toggle_hotkey_registered")
    experience_reset_hotkey_registered = _CoordinatorField("experience_reset_hotkey_registered")
    pickup_toggle_hotkey_registered = _CoordinatorField("pickup_toggle_hotkey_registered")
    registered_toggle_hotkey_vk = _CoordinatorField("registered_toggle_hotkey_vk")
    registered_emergency_stop_hotkey_vk = _CoordinatorField("registered_emergency_stop_hotkey_vk")
    registered_experience_toggle_hotkey_vk = _CoordinatorField("registered_experience_toggle_hotkey_vk")
    registered_experience_reset_hotkey_vk = _CoordinatorField("registered_experience_reset_hotkey_vk")
    registered_pickup_toggle_hotkey_vk = _CoordinatorField("registered_pickup_toggle_hotkey_vk")
    registered_minimap_cruise_toggle_hotkey_vk = _CoordinatorField("registered_minimap_cruise_toggle_hotkey_vk")
    toggle_hotkey_was_down = _CoordinatorField("toggle_hotkey_was_down")
    emergency_stop_hotkey_was_down = _CoordinatorField("emergency_stop_hotkey_was_down")
    experience_toggle_hotkey_was_down = _CoordinatorField("experience_toggle_hotkey_was_down")
    experience_reset_hotkey_was_down = _CoordinatorField("experience_reset_hotkey_was_down")
    pickup_toggle_hotkey_was_down = _CoordinatorField("pickup_toggle_hotkey_was_down")
    minimap_cruise_toggle_hotkey_was_down = _CoordinatorField("minimap_cruise_toggle_hotkey_was_down")
    control_hotkeys_suppressed_until_release = _CoordinatorField("suppressed_until_release")
    last_toggle_hotkey_at = _CoordinatorField("last_toggle_hotkey_at")
    last_experience_toggle_hotkey_at = _CoordinatorField("last_experience_toggle_hotkey_at")
    last_experience_reset_hotkey_at = _CoordinatorField("last_experience_reset_hotkey_at")
    last_pickup_toggle_hotkey_at = _CoordinatorField("last_pickup_toggle_hotkey_at")
    last_minimap_cruise_toggle_hotkey_at = _CoordinatorField("last_minimap_cruise_toggle_hotkey_at")
    auto_drink_disable_hold_started_at = _CoordinatorField("auto_drink_disable_hold_started_at")
    pickup_disable_hold_started_at = _CoordinatorField("pickup_disable_hold_started_at")

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
        *,
        runtime_process_factory: RuntimeProcessFactory | None = None,
        media_sink: RuntimeMediaSink | None = None,
    ) -> None:
        self.is_target_window_active = is_target_window_active
        self.target_window_provider = target_window_provider
        self.settings = settings or load_settings()
        self.gui = gui if gui is not None else AutoPotionSettingsGui(self.settings)
        self.gui.set_bar_preview_provider(self.capture_bar_preview_images)
        self.gui.set_experience_reset_handler(self.reset_experience_statistics)
        self.screen_capture_service = ScreenCaptureService(lambda: mss.mss())
        self.experience_only_runtime = experience_only_runtime
        self.hud_bar_detector = HudBarDetector(
            self.screen_capture_service,
            user32_provider=lambda: user32,
            gdi32_provider=lambda: gdi32,
            monotonic=lambda: time.monotonic(),
            normalize_percent=lambda value: normalize_bar_percent(value),
        )
        self.potion_engine = PotionEngine()
        self.next_capture_at = 0.0
        self.experience_pause_started_at: float | None = None
        self.experience_total_paused_seconds = 0.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.runtime_potion_action_defer_until = 0.0
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
        self.auto_drink_enabled = True
        self.auto_drink_challenge_paused = False
        self.scripts_enabled = True
        self.auto_drink_potion_option_snapshot: tuple[bool, bool] | None = None
        self.control_hotkey_coordinator = ControlHotkeyCoordinator(
            _controller_module_adapters(),
            enabled=start_control_hotkey_worker,
            start_worker=start_control_hotkey_worker,
        )
        start_potion_action_worker = start_potion_action_worker and not runtime_processes_enabled
        self.potion_action_worker = (
            PotionActionWorker(can_execute=self._can_execute_potion_action)
            if start_potion_action_worker
            else None
        )
        if self.potion_action_worker is not None:
            self.potion_action_worker.start()
        self.minimap_cruise_toggle_handler: Callable[[], None] | None = None
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
        self.experience_text_region_bar_crop_left_ratios: list[float] = []
        self.experience_tracker = ExperienceEfficiencyTracker()
        self.experience_reader = PaddleExperienceTextReader()
        if experience_executor is not None:
            executor = experience_executor
        elif runtime_processes_enabled:
            executor = InlineExecutor()
        else:
            executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=mp.get_context("spawn"),
            )
        self.experience_capture_coordinator = ExperienceCaptureCoordinator(
            executor,
            screen_capture=self.screen_capture_service,
            initial_tooltip_baseline_started_at=(
                time.monotonic() if bool(getattr(self.settings, "exp_efficiency_enabled", False)) else None
            ),
            signature_thumbnail_width=EXPERIENCE_OCR_SIGNATURE_THUMB_WIDTH,
            signature_thumbnail_height=EXPERIENCE_OCR_SIGNATURE_THUMB_HEIGHT,
            signature_changed_pixel_delta=EXPERIENCE_OCR_SIGNATURE_CHANGED_PIXEL_DELTA,
            signature_max_mean_diff=EXPERIENCE_OCR_SIGNATURE_MAX_MEAN_DIFF,
            signature_max_changed_ratio=EXPERIENCE_OCR_SIGNATURE_MAX_CHANGED_RATIO,
        )
        self.experience_tooltip_ocr_failures = 0
        self.mouse_activity_observer: PhysicalMouseActivityObserver | None = PhysicalMouseActivityObserver()
        try:
            self.mouse_activity_observer.start()
        except Exception:
            log_exception("滑鼠活動 observer 啟動失敗")
            self.mouse_activity_observer = None
        self.last_experience_mouse_idle_delay_log_at = -999.0
        self.last_experience_mouse_idle_status_at = -999.0
        self.last_experience_mouse_idle_status_key: tuple[str, int] | None = None
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
        self.runtime_process_factory = runtime_process_factory
        self.media_sink = media_sink
        self.save_settings_on_cleanup = save_settings_on_cleanup
        self.runtime_processes: RuntimeProcessPort | None = None
        self.runtime_settings_snapshot: tuple[object, ...] | None = None
        self.runtime_target_hwnd = 0
        self.runtime_control_state: tuple[bool, bool, bool, bool] | None = None
        self.runtime_potion_generation = 0
        self.runtime_experience_generation = 0
        self.runtime_potion_crash_reported = False
        self.runtime_experience_crash_reported = False
        self.last_runtime_potion_status_at = -999.0
        self.last_runtime_experience_alert_status = ""
        self.last_applied_potion_status_signature: tuple[object, ...] | None = None
        self.last_applied_experience_status_signature: tuple[object, ...] | None = None
        self.media_playback_service = MediaPlaybackService(
            _controller_module_adapters(),
            sink=media_sink,
        )
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

    @property
    def runtime_port(self) -> RuntimeProcessPort | None:
        return getattr(self, "runtime_processes", None)

    def start_control_runtime(self, worker_target, *worker_args: object) -> bool:
        runtime = self.runtime_port
        if runtime is None:
            return False
        runtime.start_control(worker_target, *worker_args)
        return True

    def send_control_runtime(self, command: ControlCommand) -> None:
        runtime = self.runtime_port
        if runtime is None:
            raise RuntimeError("control runtime 尚未啟動")
        runtime.send_control(command)

    def request_control_release(self, command: ControlCommand) -> None:
        runtime = self.runtime_port
        if runtime is None:
            raise RuntimeError("control runtime 尚未啟動")
        runtime.request_control_release(command)

    def drain_control_runtime_statuses(self, limit: int = 64) -> list[object]:
        runtime = self.runtime_port
        return [] if runtime is None else runtime.drain_control_statuses(limit=limit)

    def control_runtime_alive(self) -> bool:
        runtime = self.runtime_port
        return runtime is not None and runtime.control_alive()

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

    def set_auto_drink_challenge_paused(self, paused: bool) -> None:
        desired = bool(paused)
        if desired == bool(getattr(self, "auto_drink_challenge_paused", False)):
            return
        self.auto_drink_challenge_paused = desired
        if desired:
            self._release_all_potion_keys()
            self._clear_potion_attempt_state("hp")
            self._clear_potion_attempt_state("mp")
        if self._runtime_processes_active():
            self._send_runtime_controls_if_needed()

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
        factory = getattr(self, "runtime_process_factory", None)
        if factory is None:
            from .auto_potion_runtime_composition import create_runtime_process_port

            factory = create_runtime_process_port
        self.runtime_processes = factory(self.settings, target_hwnd)
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
            bool(getattr(self, "auto_drink_challenge_paused", False)),
            bool(getattr(self.settings, "exp_efficiency_enabled", False)),
        )
        if state == getattr(self, "runtime_control_state", None):
            return
        previous_state = getattr(self, "runtime_control_state", None)
        if previous_state is None or state[:3] != previous_state[:3]:
            self.runtime_potion_generation = int(getattr(self, "runtime_potion_generation", 0)) + 1
            self.last_runtime_potion_status_at = time.monotonic()
        if previous_state is None or (state[1], state[3]) != (previous_state[1], previous_state[3]):
            self.runtime_experience_generation = int(getattr(self, "runtime_experience_generation", 0)) + 1
        self.runtime_control_state = state
        runtime.send_potion_control(
            PotionControl(
                enabled=state[0],
                scripts_enabled=state[1],
                challenge_paused=state[2],
                generation=int(getattr(self, "runtime_potion_generation", 0)),
            )
        )
        runtime.send_experience_control(
            ExperienceControl(
                enabled=state[3] and state[1],
                resume=state[3] and state[1],
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
        self.runtime_potion_action_defer_until = max(
            0.0,
            float(getattr(status, "potion_action_defer_until", 0.0) or 0.0),
        )
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

    def _hotkey_coordinator(self) -> ControlHotkeyCoordinator:
        coordinator = getattr(self, "control_hotkey_coordinator", None)
        if coordinator is None:
            coordinator = ControlHotkeyCoordinator(
                _controller_module_adapters(),
                start_worker=False,
            )
            self.control_hotkey_coordinator = coordinator
        return coordinator

    def _screen_capture_service(self) -> ScreenCaptureService:
        service = getattr(self, "screen_capture_service", None)
        if service is None:
            service = ScreenCaptureService(lambda: mss.mss())
            self.screen_capture_service = service
            detector = getattr(self, "hud_bar_detector", None)
            if detector is not None:
                detector.screen_capture = service
            experience_capture = getattr(self, "experience_capture_coordinator", None)
            if experience_capture is not None:
                experience_capture.screen_capture = service
        return service

    def _hud_detector(self) -> HudBarDetector:
        detector = getattr(self, "hud_bar_detector", None)
        if detector is None:
            detector = HudBarDetector(
                getattr(self, "screen_capture_service", None),
                user32_provider=lambda: user32,
                gdi32_provider=lambda: gdi32,
                monotonic=lambda: time.monotonic(),
                normalize_percent=lambda value: normalize_bar_percent(value),
            )
            self.hud_bar_detector = detector
        return detector

    def _potion_engine(self) -> PotionEngine:
        engine = getattr(self, "potion_engine", None)
        if engine is None:
            engine = PotionEngine()
            self.potion_engine = engine
        return engine

    def _experience_capture(self) -> ExperienceCaptureCoordinator:
        coordinator = getattr(self, "experience_capture_coordinator", None)
        if coordinator is None:
            coordinator = ExperienceCaptureCoordinator(
                InlineExecutor(),
                screen_capture=getattr(self, "screen_capture_service", None),
            )
            self.experience_capture_coordinator = coordinator
        return coordinator

    def _control_hotkey_features(self) -> ControlHotkeyFeatureSnapshot:
        settings = self.settings
        return ControlHotkeyFeatureSnapshot(
            auto_drink_enabled=bool(getattr(self, "auto_drink_enabled", False)),
            has_out_of_potion_hold=self._has_out_of_potion_hold(),
            pickup_enabled=bool(getattr(self, "pickup_enabled", False)),
            pickup_held_vk=int(getattr(self, "pickup_held_vk", 0)),
            toggle_hotkey=settings.toggle_hotkey,
            pickup_toggle_hotkey=settings.pickup_toggle_hotkey,
        )

    def _control_hotkey_callbacks(self) -> ControlHotkeyCallbacks:
        return ControlHotkeyCallbacks(
            is_allowed_foreground=self._control_hotkey_has_allowed_foreground,
            is_detecting_key=self.gui.is_detecting_key,
            consume_key_detection_finished=self.gui.consume_key_detection_finished,
            release_pickup=self._release_pickup_key,
            release_potions=self._release_all_potion_keys,
            discard_messages=self._discard_control_hotkey_messages,
            sync_down_states=self._sync_control_hotkey_down_states,
            dispatch_event=self._dispatch_control_hotkey_event,
            emergency_stop=self.emergency_stop,
            toggle_auto_drink=self.toggle_auto_drink_enabled,
            toggle_experience=self.toggle_experience_efficiency,
            reset_experience=self._reset_experience_from_hotkey,
            toggle_pickup=self.toggle_pickup_enabled,
            toggle_minimap=self._toggle_minimap_from_hotkey,
        )

    def _control_hotkey_vk(self, hotkey: str, fallback: str) -> int:
        return self._hotkey_coordinator().control_hotkey_vk(hotkey, fallback, parse_vk_key)

    def _optional_control_hotkey_vk(self, hotkey: str | None) -> int:
        return self._hotkey_coordinator().optional_control_hotkey_vk(hotkey, parse_vk_key)

    def _sync_registered_control_hotkeys(self) -> None:
        self._hotkey_coordinator().sync_hotkeys(
            ControlHotkeySettingsSnapshot(
                toggle_hotkey=self.settings.toggle_hotkey,
                emergency_stop_hotkey=self.settings.emergency_stop_hotkey,
                experience_toggle_hotkey=self.settings.experience_toggle_hotkey,
                experience_reset_hotkey=self.settings.experience_reset_hotkey,
                pickup_toggle_hotkey=self.settings.pickup_toggle_hotkey,
                minimap_cruise_toggle_hotkey=self.settings.minimap_cruise_toggle_hotkey,
            ),
            parse_vk_key,
        )

    def _register_toggle_hotkey(
        self,
        toggle_vk: int,
        emergency_vk: int,
        experience_vk: int,
        experience_reset_vk: int = 0,
        pickup_toggle_vk: int = 0,
        minimap_cruise_toggle_vk: int = 0,
    ) -> None:
        self._hotkey_coordinator().register_hotkeys(
            toggle_vk,
            emergency_vk,
            experience_vk,
            experience_reset_vk,
            pickup_toggle_vk,
            minimap_cruise_toggle_vk,
        )

    def _unregister_toggle_hotkey(self) -> None:
        self._hotkey_coordinator().unregister_hotkeys()

    def poll_control_hotkeys(self) -> None:
        self._hotkey_coordinator().poll(
            self._control_hotkey_features(),
            self._control_hotkey_callbacks(),
        )

    def _drain_control_hotkey_worker_events(self) -> list[str]:
        return self._hotkey_coordinator().drain_worker_events()

    def _cached_control_hotkey_worker_down_states(self) -> dict[str, bool] | None:
        return self._hotkey_coordinator().cached_worker_down_states()

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
        elif event == CONTROL_HOTKEY_MINIMAP_CRUISE_TOGGLE:
            self._try_toggle_minimap_cruise(now)

    def is_key_capture_blocking_actions(self) -> bool:
        return self.gui.is_detecting_key() or self.gui.is_key_detection_release_pending()

    def _sync_control_hotkey_down_states(self) -> None:
        self._hotkey_coordinator().sync_down_states()

    def _apply_control_hotkey_down_states(self, down: dict[str, bool]) -> None:
        self._hotkey_coordinator().apply_down_states(down)

    def _any_control_hotkey_is_down(self) -> bool:
        return self._hotkey_coordinator().any_hotkey_is_down()

    def _has_pending_control_hotkey_hold(self) -> bool:
        return self._hotkey_coordinator().has_pending_hold()

    def _has_control_hotkey_activity(self, worker_events: list[str]) -> bool:
        return self._hotkey_coordinator().has_activity(worker_events)

    def _discard_control_hotkey_messages(self) -> None:
        self._hotkey_coordinator().discard_messages()

    def _set_control_hotkey_worker_events_enabled(self, enabled: bool) -> None:
        self._hotkey_coordinator().set_worker_events_enabled(enabled)

    def _maybe_reenable_control_hotkey_worker_events(self) -> None:
        self._hotkey_coordinator().maybe_reenable_events(
            self._control_hotkey_has_allowed_foreground
        )

    def _suspend_control_hotkey_events_outside_foreground(self) -> None:
        self._hotkey_coordinator().suspend_outside_foreground()

    def consume_emergency_stop_requested(self) -> bool:
        if not self.emergency_stop_requested:
            return False
        self.emergency_stop_requested = False
        return True

    def set_minimap_cruise_toggle_handler(self, handler: Callable[[], None] | None) -> None:
        self.minimap_cruise_toggle_handler = handler

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
        self._hotkey_coordinator().try_emergency_stop(
            now,
            self._control_hotkey_callbacks(),
        )

    def _try_toggle_scripts_enabled(self, now: float) -> None:
        self._hotkey_coordinator().try_toggle_scripts_enabled(
            now,
            self._control_hotkey_features(),
            self._control_hotkey_callbacks(),
        )

    def _try_toggle_experience_efficiency(self, now: float) -> None:
        self._hotkey_coordinator().try_toggle_experience(
            now,
            self._control_hotkey_callbacks(),
        )

    def _try_reset_experience_statistics(self, now: float) -> None:
        self._hotkey_coordinator().try_reset_experience(
            now,
            self._control_hotkey_callbacks(),
        )

    def _reset_experience_from_hotkey(self) -> None:
        if not self.reset_experience_statistics():
            return
        self.gui.set_experience_snapshot(ExperienceSnapshot(status="已重置"))
        self.gui.set_status("經驗統計已重置")
        self.gui.show_toggle_notice("經驗統計已重置")
        self.last_action = f"{self.settings.experience_reset_hotkey} 經驗統計重置"
        print(f"{self.settings.experience_reset_hotkey}：經驗統計已重置")

    def _try_toggle_pickup(self, now: float) -> None:
        self._hotkey_coordinator().try_toggle_pickup(
            now,
            self._control_hotkey_features(),
            self._control_hotkey_callbacks(),
        )

    def _try_toggle_minimap_cruise(self, now: float) -> None:
        self._hotkey_coordinator().try_toggle_minimap(
            now,
            self._control_hotkey_callbacks(),
        )

    def _toggle_minimap_from_hotkey(self) -> None:
        handler = getattr(self, "minimap_cruise_toggle_handler", None)
        if callable(handler):
            handler()
            return
        self.gui.set_status("小地圖巡航尚未初始化")

    def _process_pending_auto_drink_disable(self, now: float) -> None:
        self._hotkey_coordinator().process_pending_auto_drink_disable(
            now,
            self._control_hotkey_features(),
            self._control_hotkey_callbacks(),
        )

    def _process_pending_pickup_disable(self, now: float) -> None:
        self._hotkey_coordinator().process_pending_pickup_disable(
            now,
            self._control_hotkey_features(),
            self._control_hotkey_callbacks(),
        )

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
        return self._potion_engine()._potion_held_vk(bar_type)

    def _set_potion_held_vk(self, bar_type: str, vk_code: int) -> None:
        self._potion_engine()._set_potion_held_vk(bar_type, vk_code)

    def _potion_hold_refreshed_at(self, bar_type: str) -> float:
        return self._potion_engine()._potion_hold_refreshed_at(bar_type)

    def _set_potion_hold_refreshed_at(self, bar_type: str, now: float) -> None:
        self._potion_engine()._set_potion_hold_refreshed_at(bar_type, now)

    def _release_potion_key(self, bar_type: str) -> None:
        command = self._potion_engine().request_release_command(bar_type, time.monotonic())
        if command is None:
            return
        result = self._execute_potion_engine_command(
            command,
            "HP" if bar_type == "hp" else "MP",
            command.requested_at or time.monotonic(),
        )
        if result is not None:
            self._potion_engine().complete_command_result(
                result,
                log_trigger_interval=self._log_potion_key_trigger_interval,
                set_last_action=lambda action: setattr(self, "last_action", action),
                play_blocked_sound=lambda _now: None,
            )

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

    def _execute_potion_engine_command(
        self,
        command: PotionEngineCommand,
        label: str,
        now: float,
    ) -> PotionCommandResult | None:
        if command.action != "release" and not self._is_target_window_active_before_send(label, now):
            return PotionCommandResult(command.command_id, "rejected_foreground")
        try:
            worker = getattr(self, "potion_action_worker", None)
            if command.action == "hold":
                vk_code = parse_vk_key(command.key_name)
                same_key_is_held = self._potion_held_vk(command.bar_type) == vk_code
                if (
                    same_key_is_held
                    and now - self._potion_hold_refreshed_at(command.bar_type)
                    < POTION_CONTINUOUS_HOLD_REFRESH_SECONDS
                ):
                    return PotionCommandResult(command.command_id, "executed", now, vk_code)
                action_name = "refresh_hold" if same_key_is_held else "hold"
                action = PotionAction(
                    action_name,
                    command.bar_type,
                    vk_code=vk_code,
                    command_id=command.command_id,
                )
            elif command.action == "tap":
                parts = [part.strip() for part in command.key_name.split("+") if part.strip()]
                if not parts:
                    raise ValueError("快捷鍵不可空白")
                for part in parts:
                    parse_vk_key(part)
                action = PotionAction(
                    "tap",
                    command.bar_type,
                    key_name=command.key_name,
                    command_id=command.command_id,
                )
            else:
                action = PotionAction(
                    "release",
                    command.bar_type,
                    vk_code=command.vk_code,
                    command_id=command.command_id,
                )
            if worker is not None:
                if not worker.submit(action):
                    return PotionCommandResult(command.command_id, "queue_full")
                return None

            if action.action == "tap":
                tap_hotkey(action.key_name)
                held_vk = self._potion_held_vk(action.bar_type)
            elif action.action in {"hold", "refresh_hold"}:
                current_vk = self._potion_held_vk(action.bar_type)
                if current_vk and current_vk != action.vk_code:
                    key_up(current_vk)
                key_down(action.vk_code)
                held_vk = action.vk_code
            else:
                if action.vk_code:
                    key_up(action.vk_code)
                held_vk = 0
            return PotionCommandResult(command.command_id, "executed", now, held_vk)
        except ValueError as exc:
            if command.action == "hold":
                self.gui.set_status(f"{label} 喝水鍵設定無效")
                print(f"{label} 連續喝水略過：喝水鍵設定無效")
            return PotionCommandResult(command.command_id, "invalid_key", reason=str(exc))
        except Exception as exc:
            return PotionCommandResult(command.command_id, "failed", reason=str(exc))

    def _can_execute_potion_action(self, action: PotionAction) -> bool:
        if action.action in {"release", "release_all"}:
            return True
        if (
            not self.scripts_enabled
            or not self.auto_drink_enabled
            or bool(getattr(self, "auto_drink_challenge_paused", False))
            or not bool(getattr(self, "gameplay_hud_active", False))
        ):
            return False
        return self.is_target_window_active()

    def _drain_potion_engine_command_results(self, now: float) -> None:
        worker = getattr(self, "potion_action_worker", None)
        if worker is None:
            return
        for action_result in worker.drain_results():
            result = PotionCommandResult(
                action_result.command_id,
                action_result.outcome,
                action_result.completed_at,
                action_result.held_vk,
                action_result.reason,
            )
            self._potion_engine().complete_command_result(
                result,
                log_trigger_interval=self._log_potion_key_trigger_interval,
                set_last_action=lambda action: setattr(self, "last_action", action),
                play_blocked_sound=self._play_potion_blocked_sound,
            )

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

    def notify_minimap_cruise_toggle(self, enabled: bool, changed: bool, message: str) -> None:
        self.gui.set_status(message)
        self.gui.show_toggle_notice(message)
        self.last_action = message
        if changed:
            try:
                self._play_minimap_cruise_toggle_sound(enabled)
            except Exception:
                pass

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
                bool(getattr(self, "auto_drink_challenge_paused", False)),
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

    def _media_service(self) -> MediaPlaybackService:
        service = getattr(self, "media_playback_service", None)
        if service is None:
            service = MediaPlaybackService(
                _controller_module_adapters(),
                sink=getattr(self, "media_sink", None),
            )
            self.media_playback_service = service
        return service

    @property
    def _media_alias_paths(self) -> dict[str, tuple[Path, str, int]]:
        return self._media_service().alias_paths

    @_media_alias_paths.setter
    def _media_alias_paths(self, value: dict[str, tuple[Path, str, int]]) -> None:
        alias_paths = self._media_service().alias_paths
        if value is alias_paths:
            return
        alias_paths.clear()
        alias_paths.update(value)

    @property
    def _lie_detector_alert_thread(self) -> threading.Thread | None:
        return self._media_service().alert_thread

    @_lie_detector_alert_thread.setter
    def _lie_detector_alert_thread(self, value: threading.Thread | None) -> None:
        self._media_service().alert_thread = value

    def _play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None:
        self._media_service().play_toggle_beep(pattern)

    def _play_system_notification_sound(self) -> None:
        self._media_service().play_system_notification()

    def _play_minimap_cruise_toggle_sound(self, enabled: bool) -> None:
        self._media_service().play_minimap_toggle(enabled)

    def _play_media_file(self, path: Path, alias: str) -> None:
        self._media_service().play_media(
            path,
            alias,
            on_failure=lambda: self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN),
        )

    def _play_media_file_with_volume(
        self,
        path: Path,
        alias: str,
        volume: int,
        *,
        media_type: str,
    ) -> None:
        self._media_service().play_media_with_volume(
            path,
            alias,
            volume,
            media_type=media_type,
            on_failure=lambda: self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN),
        )

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

    def _play_lie_detector_alert_sound(self) -> None:
        settings = getattr(self, "settings", None)
        self._media_service().start_lie_detector_alert(
            getattr(settings, "minimap_cruise_lie_detector_alert_volume_percent", 80)
        )

    def _play_lie_detector_alert_sound_blocking(self) -> None:
        self._media_service().play_lie_detector_alert_blocking(
            getattr(self.settings, "minimap_cruise_lie_detector_alert_volume_percent", 80)
        )

    def _mci_volume_from_percent(self, percent: object) -> int:
        return MediaPlaybackService.mci_volume_from_percent(percent)

    def _preload_media_files(self) -> None:
        self._media_service().preload(
            on_failure=lambda: self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
        )

    def _ensure_media_alias_opened(
        self,
        winmm: object,
        buffer: object,
        path: Path,
        alias: str,
        volume: int,
        media_type: str,
    ) -> bool:
        return self._media_service().ensure_media_alias_opened(
            winmm,
            buffer,
            path,
            alias,
            volume,
            media_type,
            on_failure=lambda: self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN),
        )

    def _play_open_media_alias(self, winmm: object, buffer: object, alias: str, volume: int) -> bool:
        return self._media_service().play_open_media_alias(winmm, buffer, alias, volume)

    def _close_media_alias(self, winmm: object, buffer: object, alias: str) -> None:
        self._media_service().close_media_alias(winmm, buffer, alias)

    def update(self, now: float, *, pump_gui: bool = True) -> None:
        self._drain_potion_engine_command_results(now)
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
            if not bool(getattr(self, "auto_drink_challenge_paused", False)):
                self._process_due_potion_sends(now)
        else:
            self._release_pickup_key()
            self._release_all_potion_keys()

        if bool(getattr(self, "auto_drink_challenge_paused", False)):
            self._update_without_potion_bar_monitoring(now, "挑戰畫面中，暫停自動喝水")
            return

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
            transition_pause_reason, hud_refreshed_after_transition_probe = self._transition_pause_reason_after_hud_probe(now)
            if transition_pause_reason:
                self._set_gameplay_hud_active(False, now)
                self._release_all_potion_keys()
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status(transition_pause_reason)
                self.gui.set_current_percentages(None, None)
                return

            if not hud_refreshed_after_transition_probe and not self._refresh_gameplay_hud_state(now):
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
                self._update_potion_engine(now, hp_percent, mp_percent)
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

            transition_pause_reason, hud_refreshed_after_transition_probe = self._transition_pause_reason_after_hud_probe(now)
            if transition_pause_reason:
                self._set_gameplay_hud_active(False, now)
                self._pause_experience_for_missing_hud(now)
                self.gui.set_status(transition_pause_reason)
                return

            if self._experience_runtime_needs_hud_refresh(now):
                if not hud_refreshed_after_transition_probe and not self._refresh_gameplay_hud_state(now):
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
        client_bounds = self._target_client_bounds()
        if client_bounds is None:
            client_bounds = self._foreground_client_bounds()
        result = self._hud_detector().detect(
            HudDetectionRequest(
                now=now,
                target_hwnd=self._target_window_handle(),
                target_client_rect=client_bounds,
                detect_hp=True,
                detect_mp=True,
                require_clear_tail_hp=False,
                require_clear_tail_mp=False,
            ),
            bar_color_mask=self._bar_color_mask,
            find_regions=self._find_bottom_bar_pair_regions,
            set_debug=self._set_bar_detection_debug,
        )
        self._set_gameplay_hud_active(result.gameplay_hud_active, now)
        return result.gameplay_hud_active

    def _restore_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        regions_at: float,
        layout: BottomHudLayout | None,
    ) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._restore_bottom_bar_geometry(**arguments)
    def _clear_bottom_bar_geometry(self) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._clear_bottom_bar_geometry(**arguments)
    def _cache_bottom_bar_client_regions(self, client_bounds: tuple[int, int, int, int]) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._cache_bottom_bar_client_regions(**arguments)
    def _screen_region_to_client(
        self,
        region: tuple[int, int, int, int],
        client_left: int,
        client_top: int,
    ) -> tuple[int, int, int, int]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._screen_region_to_client(**arguments)
    def _client_region_to_screen(
        self,
        region: tuple[int, int, int, int],
        client_left: int,
        client_top: int,
    ) -> tuple[int, int, int, int]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._client_region_to_screen(**arguments)
    def _cached_bottom_bar_screen_regions_for_current_client(
        self,
    ) -> tuple[
        dict[str, tuple[int, int, int, int]],
        dict[str, tuple[int, int, int, int]],
        tuple[int, int, int, int],
    ] | None:
        arguments = dict(locals())
        arguments.pop("self")
        client_bounds = self._target_client_bounds()
        if client_bounds is None:
            try:
                client_bounds = self._foreground_client_bounds()
            except Exception:
                return None
        arguments["client_bounds"] = client_bounds
        return self._hud_detector()._cached_bottom_bar_screen_regions_for_current_client(**arguments)

    def _reuse_cached_bottom_bar_regions_with_direct_sample(self, now: float) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["cached_regions"] = self._cached_bottom_bar_screen_regions_for_current_client
        arguments["sample_direct"] = self._sample_direct_bar_percent_from_region
        return self._hud_detector()._reuse_cached_bottom_bar_regions_with_direct_sample(**arguments)

    def _can_reuse_stale_bottom_bar_regions(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["current_bounds"] = self._foreground_client_bounds()
        arguments["snapshot_reader"] = self._bar_percent_from_region_snapshot
        return self._hud_detector()._can_reuse_stale_bottom_bar_regions(**arguments)

    def _can_keep_current_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        current_bounds = self._target_client_bounds()
        if current_bounds is None:
            try:
                current_bounds = self._foreground_client_bounds()
            except Exception:
                return False
        arguments["current_bounds"] = current_bounds
        return self._hud_detector()._can_keep_current_bottom_bar_geometry(**arguments)

    def _can_keep_recent_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        regions_at: float,
        now: float,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        current_bounds = self._target_client_bounds()
        if current_bounds is None:
            try:
                current_bounds = self._foreground_client_bounds()
            except Exception:
                return False
        arguments["current_bounds"] = current_bounds
        return self._hud_detector().can_keep_recent_bottom_bar_geometry(**arguments)
    def _bar_region_pair_geometry_is_valid(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]] | None = None,
        client_bounds: tuple[int, int, int, int] | None = None,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bar_region_pair_geometry_is_valid(**arguments)
    def _bar_region_rect_is_valid(
        self,
        region: tuple[int, int, int, int],
        client_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bar_region_rect_is_valid(**arguments)
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

        if not self._experience_capture().start_burst(
            now=now,
            regions=regions,
            image_frames=[images],
            capture_attempts=EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
            capture_interval=EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
        ):
            self._submit_experience_ocr_burst(now, [images], effective_now=effective_now, source="bottom")
            return True
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
            worker_args = (ocr_image,)
        else:
            worker_args = (ocr_image, continuity_hint)
        self._experience_capture().submit(
            "ocr",
            read_experience_tooltip_in_worker,
            *worker_args,
            submitted_at=now,
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
        poll = self._experience_capture().poll("baseline")
        if poll.state == "pending":
            elapsed_seconds = max(0.0, now - job.submitted_at)
            if elapsed_seconds >= EXPERIENCE_CAPTURE_INTERVAL_SECONDS:
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = f"浮動 EXP baseline OCR 延遲：{elapsed_seconds:.1f}s"
                self.gui.set_experience_snapshot(snapshot)
            return True

        if poll.error is not None:
            log_exception("浮動 EXP baseline OCR 背景工作失敗")
            reading = ExperienceTextReading(
                reason=f"浮動 EXP baseline OCR 背景工作失敗：{poll.error}",
                source="tooltip",
            )
        else:
            assert poll.reading is not None
            reading = poll.reading
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
        self._experience_capture().submit(
            "baseline",
            read_experience_tooltip_in_worker,
            ocr_image,
            submitted_at=now,
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
        poll = self._experience_capture().poll("checkpoint")
        if poll.state == "pending":
            elapsed_seconds = max(0.0, now - job.submitted_at)
            if elapsed_seconds >= EXPERIENCE_CAPTURE_INTERVAL_SECONDS:
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = f"EXP-10 OCR 延遲：{elapsed_seconds:.1f}s"
                self.gui.set_experience_snapshot(snapshot)
            return True

        if poll.error is not None:
            log_exception("EXP-10 OCR 背景工作失敗")
            reading = ExperienceTextReading(
                reason=f"EXP-10 OCR 背景工作失敗：{poll.error}",
                source="tooltip",
            )
        else:
            assert poll.reading is not None
            reading = poll.reading
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
        self._experience_capture().submit(
            "checkpoint",
            read_experience_tooltip_in_worker,
            ocr_image,
            submitted_at=now,
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
        checkpoint_exp = getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None)
        return self._experience_capture().can_start_checkpoint(
            now,
            enabled=bool(getattr(self.settings, "exp_efficiency_enabled", False)),
            paused=self._experience_clock_is_paused(),
            hud_active=bool(getattr(self, "gameplay_hud_active", False)),
            has_checkpoint=isinstance(checkpoint_exp, int),
        )

    def _record_exp_10m_checkpoint(self, current_exp: int, now: float) -> None:
        self.experience_tracker.record_exp_10m_checkpoint(current_exp)
        self._experience_capture().record_checkpoint(now, EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS)

    def _seed_exp_10m_checkpoint_if_needed(self, current_exp: int, now: float) -> None:
        if isinstance(getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None), int):
            return
        self._record_exp_10m_checkpoint(current_exp, now)

    def _resume_exp_10m_checkpoint_schedule(self, now: float) -> None:
        self._experience_capture().resume_checkpoint(
            now,
            EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS,
            has_checkpoint=isinstance(getattr(self.experience_tracker, "exp_10m_checkpoint_exp", None), int),
        )

    def _reset_exp_10m_checkpoint_state(self) -> None:
        self._cancel_exp_10m_checkpoint(close_ui=True)
        self._experience_capture().reset_checkpoint()

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
        self._cancel_exp_10m_checkpoint(close_ui=False)
        decision, attempt = self._experience_capture().retry_or_stop_checkpoint(
            now,
            max_attempts=EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS,
            retry_delay=EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS,
        )
        if decision == "retry":
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = (
                f"EXP-10 OCR 失敗，10 秒後重試"
                f"（第 {attempt}/{EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS} 次）"
            )
            self.gui.set_experience_snapshot(snapshot)
            return

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
        self._experience_capture().stop_checkpoint()
        if hasattr(self.experience_tracker, "exp_10m_gain"):
            self.experience_tracker.exp_10m_gain = None
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = f"EXP-10 已停止：{reason}"
        self.gui.set_experience_snapshot(snapshot)

    def _clear_exp_10m_checkpoint_capture_state(self) -> None:
        self._restore_experience_baseline_cursor()
        self.experience_10m_checkpoint_capture = None

    def _cancel_exp_10m_checkpoint(self, *, close_ui: bool) -> None:
        with contextlib.suppress(Exception):
            self._experience_capture().cancel_checkpoint(
                close_ui=close_ui,
                close_ui_action=self._close_experience_baseline_calibration_ui,
                set_cursor=set_cursor_position,
            )

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
        samples = getattr(self.experience_tracker, "samples", [])
        return self._experience_capture().can_start_baseline(
            now,
            enabled=bool(getattr(self.settings, "exp_efficiency_enabled", False)),
            paused=self._experience_clock_is_paused(),
            hud_active=bool(getattr(self, "gameplay_hud_active", False)),
            has_samples=not isinstance(samples, list) or bool(samples),
            max_attempts=EXPERIENCE_BASELINE_CALIBRATION_MAX_ATTEMPTS,
        )

    def _capture_foreground_client_image(self) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        bounds = self._foreground_client_bounds()
        left, top, width, height = bounds
        image = self._screen_capture_service().grab(
            {"left": left, "top": top, "width": width, "height": height}
        )
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
        with contextlib.suppress(Exception):
            self._experience_capture().restore_cursor(set_cursor_position)

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
        with contextlib.suppress(Exception):
            self._experience_capture().cancel_baseline(
                close_ui=close_ui,
                close_ui_action=self._close_experience_baseline_calibration_ui,
                set_cursor=set_cursor_position,
            )

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
        progress = self._experience_capture().continue_burst(
            now=now,
            capture_attempts=EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
            capture_interval=EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
            crop_left_ratios=[
                self._experience_text_region_bar_crop_left_ratio(index)
                for index in range(len(burst.regions))
            ],
            capture_images=self._capture_experience_text_images,
        )
        if progress.state == "waiting":
            return True
        if progress.state == "capturing":
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = f"擷取經驗樣本中 {progress.capture_count}/{EXPERIENCE_BURST_CAPTURE_ATTEMPTS}"
            self.gui.set_experience_snapshot(snapshot)
            return True
        assert progress.image_frames is not None
        self._submit_experience_ocr_burst(
            now,
            progress.image_frames,
            effective_now=effective_now,
            source="bottom",
        )
        return True

    def _capture_experience_text_image(self, region: tuple[int, int, int, int]) -> np.ndarray:
        return self._experience_capture().capture_text_image(region)

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
        result = self._experience_capture().capture_tooltip(
            cursor_point=cursor_point,
            roi=roi,
            attempts=EXPERIENCE_TOOLTIP_CAPTURE_ATTEMPTS,
            settle_seconds=EXPERIENCE_TOOLTIP_SETTLE_SECONDS,
            retry_settle_seconds=EXPERIENCE_TOOLTIP_RETRY_SETTLE_SECONDS,
            mouse_lock=temporary_mouse_input_lock,
            set_cursor=set_cursor_position,
            sleep=sleep_while_pumping_messages,
            get_cursor=get_cursor_position,
            cursor_is_near=self._cursor_is_near,
        )
        if result.image is not None:
            self.last_experience_tooltip_capture_debug = result.debug
            return result.image
        if result.error is not None:
            self._remember_experience_tooltip_capture_skip(
                result.skip_reason,
                cursor_point=cursor_point,
                roi=roi,
            )
            log_debug(f"EXP tooltip capture skipped: {result.error}")
            return None
        self._remember_experience_tooltip_capture_skip(
            result.skip_reason,
            cursor_point=cursor_point,
            roi=roi,
            capture_debug=result.debug,
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
        return self._experience_capture().capture_text_images(
            regions,
            [self._experience_text_region_bar_crop_left_ratio(index) for index in range(len(regions))],
            capture_image=self._capture_experience_text_image,
        )

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
        repeated_signature = self._experience_capture().repeated_signature(
            image_signature,
            has_samples=bool(getattr(self.experience_tracker, "samples", [])),
        )
        if self._experience_level_up_recovery_expected(continuity_hint):
            repeated_signature = None
        if repeated_signature == "completed":
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "EXP ROI 未變化，保留統計"
            self.gui.set_experience_snapshot(snapshot)
            return
        if repeated_signature == "failed":
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "OCR ROI 未變化，保留統計" if snapshot.sample_count else "OCR ROI 未變化，等待畫面更新"
            self.gui.set_experience_snapshot(snapshot)
            return

        copied_frames = [[self._copy_experience_ocr_image(image) for image in images] for images in image_frames]
        if continuity_hint is None:
            worker_args = (copied_frames,)
        else:
            worker_args = (copied_frames, continuity_hint)
        self._experience_capture().submit(
            "ocr",
            read_experience_burst_frames_in_worker,
            *worker_args,
            submitted_at=now,
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

    def _experience_ocr_image_signature(self, image_frames: list[list[np.ndarray | ExperienceOcrImage]]) -> ExperienceOcrImageSignature:
        return self._experience_capture().image_signature(image_frames)

    def _is_repeated_failed_experience_ocr_signature(self, signature: ExperienceOcrImageSignature) -> bool:
        return self._experience_capture().signatures_are_similar(
            self.last_failed_experience_ocr_signature,
            signature,
        )

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

    def _experience_ocr_signatures_are_similar(
        self,
        first: ExperienceOcrImageSignature | None,
        second: ExperienceOcrImageSignature | None,
    ) -> bool:
        return self._experience_capture().signatures_are_similar(first, second)

    def _process_experience_ocr_job(self, now: float, *, effective_now: float | None = None) -> bool:
        if self.experience_ocr_job is None:
            return False
        if self._experience_clock_is_paused():
            self._stop_experience_ocr_job()
            return True
        if effective_now is None:
            effective_now = self._experience_effective_time(now)
        job = self.experience_ocr_job
        poll = self._experience_capture().poll("ocr")
        if poll.state == "pending":
            elapsed_seconds = max(0.0, now - job.submitted_at)
            if elapsed_seconds >= EXPERIENCE_CAPTURE_INTERVAL_SECONDS:
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = f"OCR 延遲：{elapsed_seconds:.1f}s"
                self.gui.set_experience_snapshot(snapshot)
            return True

        self.next_experience_capture_at = job.submitted_at + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        if poll.error is not None:
            log_exception("OCR 背景工作失敗")
            reading = ExperienceTextReading(reason=f"OCR 背景工作失敗：{poll.error}", source=job.source)
        else:
            assert poll.reading is not None
            reading = poll.reading
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
        self._clear_failed_experience_ocr_signature()
        self._clear_completed_experience_ocr_signature()
        self._experience_capture().cancel_ocr()

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

    def _update_potion_engine(
        self,
        now: float,
        hp_percent: float | None,
        mp_percent: float | None,
    ) -> None:
        sample = PotionSample(
            now=now,
            hp_percent=hp_percent,
            mp_percent=mp_percent,
            hp=PotionBarConfig(
                "hp",
                self.settings.hp_enabled,
                self.settings.hp_threshold_percent,
                self._potion_cooldown_seconds("hp"),
                self.settings.hp_key,
                self.settings.hp_continuous_enabled,
                self._continuous_stop_threshold_percent(
                    self.settings.hp_threshold_percent,
                    self.settings.hp_continuous_stop_margin_percent,
                ),
            ),
            mp=PotionBarConfig(
                "mp",
                self.settings.mp_enabled,
                self.settings.mp_threshold_percent,
                self._potion_cooldown_seconds("mp"),
                self.settings.mp_key,
                self.settings.mp_continuous_enabled,
                self._continuous_stop_threshold_percent(
                    self.settings.mp_threshold_percent,
                    self.settings.mp_continuous_stop_margin_percent,
                ),
            ),
            feature_enabled=self.auto_drink_enabled,
            scripts_enabled=self.scripts_enabled,
            target_active=True,
            challenge_paused=bool(getattr(self, "auto_drink_challenge_paused", False)),
            gameplay_hud_active=bool(getattr(self, "gameplay_hud_active", False)),
            action_channel_ready=True,
        )
        self._potion_engine().update(
            sample,
            release_key=self._release_potion_key,
            clear_bar_state=self._clear_potion_bar_state,
            capture_transient=self._capture_transient_bar_percent,
            emit_failure_warning=self._emit_direct_bar_failure_warning_if_needed,
            log_unstable=self._log_unstable_bar,
            is_active_before_send=self._is_target_window_active_before_send,
            play_blocked_sound=self._play_potion_blocked_sound,
            can_fast_repeat=self._can_use_fast_repeat_potion_sample,
            capture_confirmed=self._capture_confirmed_bar_percent,
            log_trigger_interval=self._log_potion_key_trigger_interval,
            execute_command=lambda command: self._execute_potion_engine_command(
                command,
                "HP" if command.bar_type == "hp" else "MP",
                now,
            ),
            set_last_action=lambda action: setattr(self, "last_action", action),
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
        return self._potion_engine()._maybe_drink_potion(
            bar_type, label, now, percent, enabled, threshold_percent, key_name,
            continuous_enabled, continuous_stop_margin_percent,
            challenge_paused=bool(getattr(self, "auto_drink_challenge_paused", False)),
            release_key=self._release_potion_key,
            clear_bar_state=self._clear_potion_bar_state,
            capture_transient=self._capture_transient_bar_percent,
            emit_failure_warning=self._emit_direct_bar_failure_warning_if_needed,
            log_unstable=self._log_unstable_bar,
            should_drink=self._should_drink_for_current_mode,
            cooldown_seconds=self._potion_cooldown_seconds,
            is_active_before_send=self._is_target_window_active_before_send,
            play_blocked_sound=self._play_potion_blocked_sound,
            can_fast_repeat=self._can_use_fast_repeat_potion_sample,
            capture_confirmed=self._capture_confirmed_bar_percent,
            log_trigger_interval=self._log_potion_key_trigger_interval,
            execute_command=lambda command: self._execute_potion_engine_command(command, label, now),
            set_last_action=lambda action: setattr(self, "last_action", action),
        )
    def _continuous_stop_threshold_percent(self, threshold_percent: float, margin_percent: float) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._continuous_stop_threshold_percent(**arguments)

    def _process_due_potion_sends(self, now: float) -> None:
        if not self.auto_drink_enabled or bool(getattr(self, "auto_drink_challenge_paused", False)):
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
        return self._potion_engine()._process_due_potion_send(
            bar_type, label, now, enabled, threshold_percent, key_name, continuous_enabled,
            gameplay_hud_active=bool(getattr(self, "gameplay_hud_active", False)),
            cooldown_seconds=self._potion_cooldown_seconds,
            is_active_before_send=self._is_target_window_active_before_send,
            execute_command=lambda command: self._execute_potion_engine_command(command, label, now),
            log_trigger_interval=self._log_potion_key_trigger_interval,
            set_last_action=lambda action: setattr(self, "last_action", action),
        )
    def _can_use_fast_repeat_potion_sample(self, bar_type: str) -> bool:
        return self._last_potion_drink_at(bar_type) > -100.0

    def _should_defer_experience_for_potion(
        self,
        now: float,
        hp_percent: float | None,
        mp_percent: float | None,
    ) -> bool:
        return self._potion_priority_defer_until(now, hp_percent, mp_percent) > now + POTION_TIME_EPSILON_SECONDS

    def should_defer_periodic_item_for_potion(self, now: float) -> bool:
        runtime_defer_until = float(getattr(self, "runtime_potion_action_defer_until", 0.0) or 0.0)
        if runtime_defer_until > now + POTION_TIME_EPSILON_SECONDS:
            return True
        return self._potion_priority_defer_until(now, None, None) > now + POTION_TIME_EPSILON_SECONDS

    def potion_priority_defer_until(
        self,
        now: float,
        hp_percent: float | None = None,
        mp_percent: float | None = None,
    ) -> float:
        runtime_defer_until = float(getattr(self, "runtime_potion_action_defer_until", 0.0) or 0.0)
        return max(runtime_defer_until, self._potion_priority_defer_until(now, hp_percent, mp_percent))

    def _potion_priority_defer_until(
        self,
        now: float,
        hp_percent: float | None,
        mp_percent: float | None,
    ) -> float:
        if not self.auto_drink_enabled:
            return 0.0
        return max(
            self._potion_priority_defer_until_for_bar(
                "hp",
                hp_percent,
                self.settings.hp_enabled,
                self.settings.hp_threshold_percent,
                self.settings.hp_continuous_enabled,
                self.settings.hp_continuous_stop_margin_percent,
                now,
            ),
            self._potion_priority_defer_until_for_bar(
                "mp",
                mp_percent,
                self.settings.mp_enabled,
                self.settings.mp_threshold_percent,
                self.settings.mp_continuous_enabled,
                self.settings.mp_continuous_stop_margin_percent,
                now,
            ),
        )

    def _potion_priority_defer_until_for_bar(
        self,
        bar_type: str,
        percent: float | None,
        enabled: bool,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
        now: float,
    ) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_priority_defer_until_for_bar(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._should_defer_experience_for_potion_bar(**arguments)

    def _should_drink_for_current_mode(
        self,
        percent: float,
        threshold_percent: float,
        continuous_enabled: bool,
        continuous_stop_margin_percent: float,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._should_drink_for_current_mode(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        arguments["alert_suspected_no_potion"] = self._alert_suspected_no_potion
        return self._potion_engine()._update_potion_effect_watch_cycle(**arguments)
    def _record_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._record_potion_effect_attempt(**arguments)

    def _record_continuous_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._record_continuous_potion_effect_attempt(**arguments)

    def _potion_effect_attempts(self, bar_type: str) -> list[PotionEffectAttempt]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_effect_attempts(**arguments)

    def _set_potion_effect_attempts(self, bar_type: str, attempts: list[PotionEffectAttempt]) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_effect_attempts(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._clear_potion_attempt_state(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_no_effect_count(**arguments)

    def _set_potion_no_effect_count(self, bar_type: str, count: int) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_no_effect_count(**arguments)

    def _reset_potion_no_effect_count(self, bar_type: str) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._reset_potion_no_effect_count(**arguments)

    def _potion_last_no_effect_counted_at(self, bar_type: str) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_last_no_effect_counted_at(**arguments)

    def _set_potion_last_no_effect_counted_at(self, bar_type: str, now: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_last_no_effect_counted_at(**arguments)

    def _pending_potion_send_at(self, bar_type: str) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._pending_potion_send_at(**arguments)

    def _pending_potion_send_percent(self, bar_type: str) -> float | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._pending_potion_send_percent(**arguments)

    def _schedule_pending_potion_send(self, bar_type: str, due_at: float, percent: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._schedule_pending_potion_send(**arguments)

    def _clear_pending_potion_send(self, bar_type: str) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._clear_pending_potion_send(**arguments)

    def _next_pending_potion_send_at(self) -> float | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._next_pending_potion_send_at(**arguments)

    def _potion_cooldown_seconds(self, bar_type: str) -> float:
        if bar_type == "hp":
            return max(POTION_MIN_COOLDOWN_SECONDS, float(self.settings.hp_cooldown_seconds))
        return max(POTION_MIN_COOLDOWN_SECONDS, float(self.settings.mp_cooldown_seconds))

    def _last_potion_drink_at(self, bar_type: str) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._last_potion_drink_at(**arguments)

    def _set_last_potion_drink_at(self, bar_type: str, now: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_last_potion_drink_at(**arguments)

    def _update_potion_damage_context(self, bar_type: str, percent: float, now: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._update_potion_damage_context(**arguments)

    def _mark_potion_recent_damage(self, bar_type: str, now: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._mark_potion_recent_damage(**arguments)

    def _potion_recent_damage_is_active(self, bar_type: str, now: float) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_recent_damage_is_active(**arguments)

    def _potion_recent_damage_blocks_stable_confirmation(self, bar_type: str, now: float) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_recent_damage_blocks_stable_confirmation(**arguments)

    def _potion_auto_hold_is_allowed(self, bar_type: str) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_auto_hold_is_allowed(**arguments)

    def _record_potion_percent_sample(self, bar_type: str, now: float, percent: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._record_potion_percent_sample(**arguments)

    def _potion_pre_window_is_stable(self, bar_type: str, now: float, before_percent: float) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_pre_window_is_stable(**arguments)

    def _potion_bar_is_stable_for_confirmation(self, bar_type: str, now: float) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_bar_is_stable_for_confirmation(**arguments)

    def _potion_stability_confirmation_seconds(self, bar_type: str) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_stability_confirmation_seconds(**arguments)

    def _potion_stability_confirmation_min_samples(self, bar_type: str) -> int:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_stability_confirmation_min_samples(**arguments)

    def _potion_stability_confirmation_volatility_tolerance(self, bar_type: str) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_stability_confirmation_volatility_tolerance(**arguments)

    def _potion_recent_samples(self, bar_type: str) -> list[tuple[float, float]]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_recent_samples(**arguments)

    def _set_potion_recent_samples(self, bar_type: str, samples: list[tuple[float, float]]) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_recent_samples(**arguments)

    def _potion_last_observed_percent(self, bar_type: str) -> float | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_last_observed_percent(**arguments)

    def _set_potion_last_observed_percent(self, bar_type: str, percent: float | None) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_last_observed_percent(**arguments)

    def _potion_recent_damage_at(self, bar_type: str) -> float:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_recent_damage_at(**arguments)

    def _set_potion_recent_damage_at(self, bar_type: str, now: float) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_recent_damage_at(**arguments)

    def _potion_damage_pressure_active(self, bar_type: str) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._potion_damage_pressure_active(**arguments)

    def _set_potion_damage_pressure_active(self, bar_type: str, active: bool) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_potion_damage_pressure_active(**arguments)

    def _out_of_potion_hold(self, bar_type: str) -> OutOfPotionHold | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._out_of_potion_hold(**arguments)

    def _set_out_of_potion_hold(self, bar_type: str, hold: OutOfPotionHold | None) -> None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._set_out_of_potion_hold(**arguments)

    def _has_out_of_potion_hold(self) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._has_out_of_potion_hold(**arguments)

    def _out_of_potion_hold_status_message(self) -> str:
        arguments = dict(locals())
        arguments.pop("self")
        return self._potion_engine()._out_of_potion_hold_status_message(**arguments)

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
        return self._hud_detector()._capture_bar_percent(
            bar_type,
            require_clear_tail,
            capture_direct=self._capture_bar_percent_direct,
            find_regions=self._find_bottom_bar_pair_regions,
            record_failure=self._record_direct_bar_failure,
            set_debug=self._set_bar_detection_debug,
            failure_reason=self._direct_bar_failure_reason,
            set_failure_debug=self._set_direct_bar_failure_debug,
        )

    def _capture_bar_percents(self) -> tuple[float | None, float | None]:
        return self._hud_detector()._capture_bar_percents(
            capture_direct=self._capture_bar_percents_direct,
            find_regions=self._find_bottom_bar_pair_regions,
            record_failure=self._record_direct_bar_failure,
            failure_reason=self._direct_bar_failure_reason,
            set_failure_debug=self._set_direct_bar_failure_debug,
        )

    def _capture_bar_percents_direct(self) -> tuple[float | None, float | None] | None:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["cached_regions"] = self._cached_bottom_bar_screen_regions_for_current_client
        arguments["image_provider"] = self._direct_bar_image_from_region
        arguments["sample_image"] = self._sample_direct_bar_percent_from_image
        return self._hud_detector()._capture_bar_percents_direct(**arguments)

    def _union_direct_bar_regions(
        self,
        first: tuple[int, int, int, int] | None,
        second: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, int, int] | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._union_direct_bar_regions(**arguments)

    def _crop_direct_bar_image(
        self,
        image: np.ndarray,
        source_region: tuple[int, int, int, int],
        target_region: tuple[int, int, int, int],
    ) -> np.ndarray | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._crop_direct_bar_image(**arguments)

    def _capture_bar_percent_direct(self, bar_type: str, *, require_clear_tail: bool = False) -> float | None:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["cached_regions"] = self._cached_bottom_bar_screen_regions_for_current_client
        arguments["sample_direct"] = self._sample_direct_bar_percent_from_region
        return self._hud_detector()._capture_bar_percent_direct(**arguments)

    def _find_bottom_bar_pair_regions(
        self,
        *,
        use_cache: bool = True,
        allow_stale_on_failure: bool = True,
    ) -> dict[str, tuple[int, int, int, int]]:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["client_bounds"] = self._foreground_client_bounds()
        arguments["bar_color_mask"] = self._bar_color_mask
        return self._hud_detector()._find_bottom_bar_pair_regions(**arguments)

    def _bottom_bar_search_areas(self, client_bounds: tuple[int, int, int, int]) -> list[HudSearchArea]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bottom_bar_search_areas(**arguments)

    def _bottom_bar_search_area_from_content_bounds(
        self,
        content_left: int,
        content_top: int,
        content_width: int,
        content_height: int,
    ) -> HudSearchArea:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bottom_bar_search_area_from_content_bounds(**arguments)

    def _gameplay_content_bounds(self, client_bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._gameplay_content_bounds(**arguments)

    def _bottom_hud_layout_from_labels(
        self,
        image: np.ndarray,
        *,
        hp_mask: np.ndarray,
        mp_mask: np.ndarray,
        exp_mask: np.ndarray,
        search_area: HudSearchArea,
    ) -> BottomHudLayout | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bottom_hud_layout_from_labels(**arguments)

    def _hud_label_matches(
        self,
        image: np.ndarray,
    ) -> dict[str, tuple[tuple[int, int, int, int], float, float]]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._hud_label_matches(**arguments)

    def _hud_label_match(
        self,
        mask: np.ndarray,
        label: str,
    ) -> tuple[tuple[int, int, int, int], float, float] | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._hud_label_match(**arguments)

    def _hud_label_template(self, label: str, scale: float = 1.0) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._hud_label_template(**arguments)

    def _hud_label_template_source(self, label: str) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._hud_label_template_source(**arguments)

    def _generated_hud_label_template(self, label: str) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._generated_hud_label_template(**arguments)

    def _hud_label_text_mask(self, image: np.ndarray) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._hud_label_text_mask(**arguments)

    def _bottom_hud_hp_mp_label_geometry_is_valid(
        self,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        search_width: int,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bottom_hud_hp_mp_label_geometry_is_valid(**arguments)

    def _bottom_hud_exp_label_geometry_is_valid(
        self,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        exp_rect: tuple[int, int, int, int],
        search_width: int,
    ) -> bool:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bottom_hud_exp_label_geometry_is_valid(**arguments)

    def _hp_mp_tracks_from_label_geometry(
        self,
        image: np.ndarray,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        client_width: int,
        client_height: int,
    ) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._hp_mp_tracks_from_label_geometry(**arguments)

    def _bar_run_right_of_label(
        self,
        mask: np.ndarray,
        label_rect: tuple[int, int, int, int],
        client_width: int,
    ) -> tuple[int, int, int] | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bar_run_right_of_label(**arguments)

    def _bar_track_right_of_label(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        label_rect: tuple[int, int, int, int],
        client_width: int,
        client_height: int,
        bar_type: str,
    ) -> tuple[int, int, int, int] | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bar_track_right_of_label(**arguments)

    def _bar_track_like_mask(self, image: np.ndarray, color_mask: np.ndarray, bar_type: str) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bar_track_like_mask(**arguments)

    def _track_vertical_bounds_from_track_mask(
        self,
        track_like: np.ndarray,
        track_left: int,
        track_width: int,
        current_top: int,
        current_height: int,
        client_height: int,
    ) -> tuple[int, int]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._track_vertical_bounds_from_track_mask(**arguments)

    def _close_column_gaps(self, columns: np.ndarray, max_gap: int) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._close_column_gaps(**arguments)

    def _experience_text_region_from_exp_track(
        self,
        image: np.ndarray,
        search_left: int,
        search_top: int,
        exp_track: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._experience_text_region_from_exp_track(**arguments)

    def _exp_text_glyph_mask(self, text_mask: np.ndarray, track_height: int) -> np.ndarray:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._exp_text_glyph_mask(**arguments)

    def _offset_rect(
        self,
        rect: tuple[int, int, int, int],
        offset_x: int,
        offset_y: int,
    ) -> tuple[int, int, int, int]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._offset_rect(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bottom_bar_pair_regions_from_candidates(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._infer_bottom_bar_pair_regions_from_hp_candidate(**arguments)

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
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._full_bar_region_and_track(**arguments)

    def _bar_vertical_bounds(
        self,
        mask: np.ndarray | None,
        run_start: int,
        run_length: int,
        row_index: int,
        search_height: int,
        fallback_height: int,
    ) -> tuple[int, int]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._bar_vertical_bounds(**arguments)
    def _capture_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        require_clear_tail: bool = False,
        source: str = "指定區域",
        *,
        track_region: tuple[int, int, int, int] | None = None,
    ) -> float | None:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["snapshot_reader"] = self._bar_percent_from_region_snapshot
        return self._hud_detector()._capture_bar_percent_from_region(**arguments)

    def _bar_percent_from_region_snapshot(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        *,
        require_clear_tail: bool = False,
        track_region: tuple[int, int, int, int] | None = None,
    ) -> tuple[float | None, str, bool | None]:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["screen_capture"] = self._screen_capture_service()
        arguments["bar_color_mask"] = self._bar_color_mask
        arguments["percent_reader"] = self._percent_from_bar_mask_result
        return self._hud_detector()._bar_percent_from_region_snapshot(**arguments)

    def _sample_direct_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        *,
        require_clear_tail: bool = False,
    ) -> tuple[float | None, str, bool | None]:
        arguments = dict(locals())
        arguments.pop("self")
        arguments["image_provider"] = self._direct_bar_image_from_region
        return self._hud_detector()._sample_direct_bar_percent_from_region(**arguments)

    def _sample_direct_bar_percent_from_image(
        self,
        image: np.ndarray,
        bar_type: str,
    ) -> tuple[float | None, str, bool | None]:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._sample_direct_bar_percent_from_image(**arguments)

    def _direct_bar_track_like_crop(
        self,
        image: np.ndarray,
        color_mask: np.ndarray,
        bar_type: str,
    ) -> tuple[np.ndarray, str] | None:
        arguments = dict(locals())
        arguments.pop("self")
        return self._hud_detector()._direct_bar_track_like_crop(**arguments)

    def _direct_bar_image_from_region(self, region: tuple[int, int, int, int]) -> np.ndarray | None:
        return self._hud_detector().direct_bar_image_from_region(region)

    def _bar_percent_inputs(
        self,
        region: tuple[int, int, int, int],
        mask: np.ndarray,
        image: np.ndarray,
        track_region: tuple[int, int, int, int] | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        return self._hud_detector().bar_percent_inputs(region, mask, image, track_region)

    def _remember_stable_bar_sample(
        self,
        bar_type: str,
        percent: float,
        region: tuple[int, int, int, int],
    ) -> None:
        self._hud_detector().remember_stable_bar_sample(bar_type, percent, region)

    def _recent_stable_bar_percent(
        self,
        bar_type: str,
        region: tuple[int, int, int, int],
    ) -> float | None:
        return self._hud_detector().recent_stable_bar_percent(bar_type, region)

    def _percent_from_bar_mask(
        self,
        mask: np.ndarray,
        image: np.ndarray | None = None,
        require_clear_tail: bool = False,
    ) -> float | None:
        return self._hud_detector().percent_from_bar_mask(mask, image, require_clear_tail)

    def _percent_from_bar_mask_result(
        self,
        mask: np.ndarray,
        image: np.ndarray | None = None,
        require_clear_tail: bool = False,
    ) -> tuple[float | None, str, bool | None]:
        return self._hud_detector().percent_from_bar_mask_result(mask, image, require_clear_tail)

    def _bar_track_looks_empty(self, mask: np.ndarray, image: np.ndarray | None) -> bool:
        return self._hud_detector().bar_track_looks_empty(mask, image)

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
        self._hud_detector().set_bar_detection_debug(
            bar_type,
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
        return self._hud_detector().bar_detection_debug_text(bar_type)

    def _compact_bar_debug_source(self, source: str) -> str:
        return self._hud_detector().compact_bar_debug_source(source)

    def current_bar_detection_regions(self) -> dict[str, tuple[int, int, int, int] | None]:
        return self._hud_detector().current_bar_detection_regions()

    def capture_bar_preview_images(self, make_target_topmost: bool = False) -> dict[str, dict[str, object]]:
        target_hwnd = self._target_window_handle() if make_target_topmost else 0
        return self._hud_detector().capture_bar_preview_images(
            make_target_topmost=make_target_topmost,
            target_hwnd=target_hwnd,
            topmost_context=lambda hwnd: temporarily_make_window_topmost(hwnd),
            wait_for_target_ready=self._wait_for_preview_target_ready,
            bar_color_mask=self._bar_color_mask,
            percent_from_bar_mask=self._percent_from_bar_mask,
        )

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
        return self._hud_detector().bar_run_has_horizontal_body(mask, start, end)

    def _bar_tail_looks_obstructed(self, image: np.ndarray, fill_end: int) -> bool:
        return self._hud_detector().bar_tail_looks_obstructed(image, fill_end)

    def _bar_run_candidates(self, mask: np.ndarray, client_width: int) -> list[tuple[int, int, int]]:
        return self._hud_detector().bar_run_candidates(mask, client_width)

    def _bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        return self._hud_detector().bar_color_mask(image, bar_type)

    def _direct_bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        return self._hud_detector().direct_bar_color_mask(image, bar_type)

    def _is_transition_fade_active(self) -> bool:
        return self._hud_detector().is_transition_fade_active(
            self._gameplay_content_bounds(self._foreground_client_bounds())
        )

    def _is_channel_loading_screen_active(self) -> bool:
        return self._hud_detector().is_channel_loading_screen_active(
            self._gameplay_content_bounds(self._foreground_client_bounds())
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

    def _transition_pause_reason_after_hud_probe(self, now: float) -> tuple[str | None, bool]:
        pause_reason = self._transition_pause_reason(now)
        if pause_reason is None:
            return None, False
        if not self._refresh_gameplay_hud_state(now):
            return pause_reason, False
        self.fade_guard_hits = 0
        self.fade_guard_until = 0.0
        return None, True

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
        if getattr(self, "_cleanup_in_progress", False) or getattr(self, "_cleanup_completed", False):
            return
        self._cleanup_in_progress = True
        completed_steps = getattr(self, "_cleanup_completed_steps", set())
        self._cleanup_completed_steps = completed_steps

        def stop_runtime_processes() -> None:
            runtime = getattr(self, "runtime_processes", None)
            if runtime is not None:
                runtime.stop()
                self.runtime_processes = None

        def stop_control_hotkey_worker() -> None:
            coordinator = getattr(self, "control_hotkey_coordinator", None)
            if coordinator is not None:
                coordinator.close()

        def stop_potion_action_worker() -> None:
            worker = getattr(self, "potion_action_worker", None)
            if worker is not None:
                worker.stop()

        def stop_mouse_activity_observer() -> None:
            observer = getattr(self, "mouse_activity_observer", None)
            stop = getattr(observer, "stop", None)
            if callable(stop):
                stop()
            self.mouse_activity_observer = None

        def close_direct_capture() -> None:
            detector = getattr(self, "hud_bar_detector", None)
            if detector is not None:
                detector.close()

        def close_experience_capture() -> None:
            coordinator = getattr(self, "experience_capture_coordinator", None)
            if coordinator is not None:
                coordinator.close(
                    close_ui_action=self._close_experience_baseline_calibration_ui,
                    set_cursor=set_cursor_position,
                )

        def save_current_settings() -> None:
            if (
                getattr(self, "_initialization_completed", True)
                and getattr(self, "save_settings_on_cleanup", True)
                and hasattr(self, "settings")
            ):
                save_settings(self.settings)

        def close_mss_capture() -> None:
            service = getattr(self, "screen_capture_service", None)
            if service is not None:
                service.close()

        def close_gui() -> None:
            gui = getattr(self, "gui", None)
            if gui is not None and not gui.closed:
                gui.close()

        def restore_stdout() -> None:
            original_stdout = getattr(self, "original_stdout", None)
            if original_stdout is not None:
                sys.stdout = original_stdout

        def restore_stderr() -> None:
            original_stderr = getattr(self, "original_stderr", None)
            if original_stderr is not None:
                sys.stderr = original_stderr

        steps = (
            ("release pickup key", self._release_pickup_key),
            ("release potion keys", self._release_all_potion_keys),
            ("stop runtime processes", stop_runtime_processes),
            ("unregister toggle hotkey", self._unregister_toggle_hotkey),
            ("stop control hotkey worker", stop_control_hotkey_worker),
            ("stop potion action worker", stop_potion_action_worker),
            ("stop mouse observer", stop_mouse_activity_observer),
            ("close media files", self._close_media_files),
            ("close direct capture", close_direct_capture),
            ("close experience capture", close_experience_capture),
            ("save settings", save_current_settings),
            ("close MSS capture", close_mss_capture),
            ("close GUI", close_gui),
            ("restore stdout", restore_stdout),
            ("restore stderr", restore_stderr),
        )
        try:
            for label, action in steps:
                if label in completed_steps:
                    continue
                try:
                    action()
                except Exception as exc:
                    self._log_cleanup_failure(label, exc)
                else:
                    completed_steps.add(label)
            self._cleanup_completed = len(completed_steps) == len(steps)
        finally:
            self._cleanup_in_progress = False

    @staticmethod
    def _log_cleanup_failure(label: str, exc: Exception) -> None:
        try:
            log_exception(f"AutoPotionController cleanup failed: {label}")
        except Exception:
            try:
                print(f"AutoPotionController cleanup failed: {label}: {exc}")
            except Exception:
                return
    def _close_media_files(self) -> None:
        self._media_service().close()


from .auto_potion_factory import _create_auto_potion_controller
