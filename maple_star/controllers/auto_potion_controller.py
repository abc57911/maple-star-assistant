from __future__ import annotations

import ctypes
import hashlib
import sys
import time
import winsound
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import mss
import numpy as np

from ..constants import (
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
    EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
    EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
    FADE_GUARD_BRIGHT_PIXEL_RATIO,
    FADE_GUARD_MEAN_LUMINANCE,
    FADE_GUARD_RECOVERY_SECONDS,
    FADE_GUARD_REQUIRED_FRAMES,
    GAME_CONTENT_ASPECT_RATIO,
    GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS,
    LOADING_GUARD_BRIGHT_PIXEL_RATIO,
    LOADING_GUARD_LOW_SATURATION_RATIO,
    LOADING_GUARD_MEAN_LUMINANCE,
    MOD_NOREPEAT,
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
from ..adapters.debug_logging import log_exception
from ..services.control_hotkey_worker import (
    CONTROL_HOTKEY_EMERGENCY_STOP,
    CONTROL_HOTKEY_EXPERIENCE_RESET,
    CONTROL_HOTKEY_EXPERIENCE_TOGGLE,
    CONTROL_HOTKEY_TOGGLE,
    ControlHotkeyWorker,
)
from ..models.experience import (
    ExperienceEfficiencyTracker,
    ExperienceOcrImage,
    ExperienceSnapshot,
    ExperienceTextReading,
    PaddleExperienceTextReader,
    save_experience_ocr_learning_case,
)
from ..models.controller_state import (
    BarDetectionDebug,
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
    should_drink_for_threshold,
)
from ..views.settings_gui import AutoPotionSettingsGui, GuiConsoleWriter
from ..models.settings import AutoPotionSettings
from ..services.settings_store import load_settings, save_settings
from ..adapters.win_input import (
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
EXPERIENCE_WIDE_TEXT_LEFT_RATIO = 0.34
EXPERIENCE_WIDE_TEXT_RIGHT_PADDING_RATIO = 0.08
EXPERIENCE_WIDE_TEXT_HEIGHT_RATIO = 1.65
EXPERIENCE_OCR_SIGNATURE_THUMB_WIDTH = 96
EXPERIENCE_OCR_SIGNATURE_THUMB_HEIGHT = 18
EXPERIENCE_OCR_SIGNATURE_CHANGED_PIXEL_DELTA = 4
EXPERIENCE_OCR_SIGNATURE_MAX_MEAN_DIFF = 0.35
EXPERIENCE_OCR_SIGNATURE_MAX_CHANGED_RATIO = 0.002
BAR_PAIR_HP_MAX_LEFT_RATIO = 0.48
BAR_PAIR_MIN_GAP_RATIO = 0.10
BAR_PAIR_MAX_GAP_RATIO = 0.24
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_VOLUME_PERCENT = 15
MCI_MAX_VOLUME = 1000
MCI_MEDIA_VOLUME = round(MCI_MAX_VOLUME * MEDIA_VOLUME_PERCENT / 100)
AUTO_DRINK_START_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-start.mp3"
AUTO_DRINK_STOP_SOUND_PATH = PROJECT_ROOT / "media" / "auto-drink-stop.mp3"


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
        self.experience_pause_started_at: float | None = None
        self.experience_total_paused_seconds = 0.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.hp_potion_effect_attempts: list[PotionEffectAttempt] = []
        self.mp_potion_effect_attempts: list[PotionEffectAttempt] = []
        self.hp_potion_no_effect_count = 0
        self.mp_potion_no_effect_count = 0
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
        self.last_error_at = -999.0
        self.last_unstable_bar_at = -999.0
        self.auto_drink_enabled = True
        self.scripts_enabled = True
        self.hotkey_registered = False
        self.emergency_hotkey_registered = False
        self.experience_toggle_hotkey_registered = False
        self.experience_reset_hotkey_registered = False
        self.control_hotkey_worker = ControlHotkeyWorker()
        self.control_hotkey_worker.start()
        self.toggle_hotkey_was_down = False
        self.emergency_stop_hotkey_was_down = False
        self.experience_toggle_hotkey_was_down = False
        self.experience_reset_hotkey_was_down = False
        self.registered_toggle_hotkey_vk = 0
        self.registered_emergency_stop_hotkey_vk = 0
        self.registered_experience_toggle_hotkey_vk = 0
        self.registered_experience_reset_hotkey_vk = 0
        self.control_hotkeys_suppressed_until_release = False
        self.last_toggle_hotkey_at = -999.0
        self.last_experience_toggle_hotkey_at = -999.0
        self.last_experience_reset_hotkey_at = -999.0
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
        self.experience_ocr_burst: ExperienceOcrBurst | None = None
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
        experience_reset_vk = self._control_hotkey_vk(self.settings.experience_reset_hotkey, "F9")
        if (
            toggle_vk == self.registered_toggle_hotkey_vk
            and emergency_vk == self.registered_emergency_stop_hotkey_vk
            and experience_vk == self.registered_experience_toggle_hotkey_vk
            and experience_reset_vk == self.registered_experience_reset_hotkey_vk
        ):
            return
        self._unregister_toggle_hotkey()
        self._register_toggle_hotkey(toggle_vk, emergency_vk, experience_vk, experience_reset_vk)

    def _register_toggle_hotkey(
        self,
        toggle_vk: int,
        emergency_vk: int,
        experience_vk: int,
        experience_reset_vk: int = 0,
    ) -> None:
        self.registered_toggle_hotkey_vk = toggle_vk
        self.hotkey_registered = bool(toggle_vk)

        self.registered_emergency_stop_hotkey_vk = emergency_vk
        self.emergency_hotkey_registered = bool(emergency_vk)

        self.registered_experience_toggle_hotkey_vk = experience_vk
        self.experience_toggle_hotkey_registered = bool(experience_vk)

        self.registered_experience_reset_hotkey_vk = experience_reset_vk
        self.experience_reset_hotkey_registered = bool(experience_reset_vk)
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.update_hotkeys(
                {
                    CONTROL_HOTKEY_TOGGLE: toggle_vk,
                    CONTROL_HOTKEY_EMERGENCY_STOP: emergency_vk,
                    CONTROL_HOTKEY_EXPERIENCE_TOGGLE: experience_vk,
                    CONTROL_HOTKEY_EXPERIENCE_RESET: experience_reset_vk,
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
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.update_hotkeys({})

    def poll_control_hotkeys(self) -> None:
        if self.gui.is_detecting_key():
            self.toggle_hotkey_was_down = False
            self.emergency_stop_hotkey_was_down = False
            self.experience_toggle_hotkey_was_down = False
            self.experience_reset_hotkey_was_down = False
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

        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker_events = self._drain_control_hotkey_worker_events()
            cached_down = self._cached_control_hotkey_worker_down_states()
            if cached_down is not None:
                self._apply_control_hotkey_down_states(cached_down)
                if worker_events:
                    now = time.monotonic()
                    for event in worker_events:
                        self._dispatch_control_hotkey_event(event, now)
                return
            if worker_events:
                now = time.monotonic()
                for event in worker_events:
                    self._dispatch_control_hotkey_event(event, now)
                return

        toggle_triggered = False
        emergency_stop_triggered = False
        experience_toggle_triggered = False
        experience_reset_triggered = False
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

        if emergency_stop_triggered:
            self.emergency_stop()
        elif toggle_triggered:
            self._try_toggle_scripts_enabled(time.monotonic())
        elif experience_toggle_triggered:
            self._try_toggle_experience_efficiency(time.monotonic())
        elif experience_reset_triggered:
            self._try_reset_experience_statistics(time.monotonic())

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
            self.emergency_stop()
        elif event == CONTROL_HOTKEY_TOGGLE:
            self._try_toggle_scripts_enabled(now)
        elif event == CONTROL_HOTKEY_EXPERIENCE_TOGGLE:
            self._try_toggle_experience_efficiency(now)
        elif event == CONTROL_HOTKEY_EXPERIENCE_RESET:
            self._try_reset_experience_statistics(now)

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

    def _apply_control_hotkey_down_states(self, down: dict[str, bool]) -> None:
        self.toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_TOGGLE, False)
        self.emergency_stop_hotkey_was_down = down.get(CONTROL_HOTKEY_EMERGENCY_STOP, False)
        self.experience_toggle_hotkey_was_down = down.get(CONTROL_HOTKEY_EXPERIENCE_TOGGLE, False)
        self.experience_reset_hotkey_was_down = down.get(CONTROL_HOTKEY_EXPERIENCE_RESET, False)

    def _any_control_hotkey_is_down(self) -> bool:
        return (
            self.toggle_hotkey_was_down
            or self.emergency_stop_hotkey_was_down
            or self.experience_toggle_hotkey_was_down
            or self.experience_reset_hotkey_was_down
        )

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

    def consume_emergency_stop_requested(self) -> bool:
        if not self.emergency_stop_requested:
            return False
        self.emergency_stop_requested = False
        return True

    def _try_toggle_scripts_enabled(self, now: float) -> None:
        if now - self.last_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_toggle_hotkey_at = now
        self.toggle_auto_drink_enabled()

    def _try_toggle_experience_efficiency(self, now: float) -> None:
        if now - self.last_experience_toggle_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_toggle_hotkey_at = now
        self.toggle_experience_efficiency()

    def _try_reset_experience_statistics(self, now: float) -> None:
        if now - self.last_experience_reset_hotkey_at < TOGGLE_HOTKEY_DEBOUNCE_SECONDS:
            return
        self.last_experience_reset_hotkey_at = now
        self.reset_experience_statistics()
        self.gui.set_experience_snapshot(ExperienceSnapshot(status="已重置"))
        self.gui.set_status("經驗統計已重置")
        self.gui.show_toggle_notice("經驗統計已重置")
        self.last_action = f"{self.settings.experience_reset_hotkey} 經驗統計重置"
        print(f"{self.settings.experience_reset_hotkey}：經驗統計已重置")

    def toggle_auto_drink_enabled(self) -> None:
        if self.auto_drink_enabled and self._has_out_of_potion_hold():
            self._clear_potion_effect_state()
            self._play_media_file(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")
            self.gui.set_status("自動喝水已恢復")
            self.gui.show_toggle_notice("自動喝水已恢復")
            self.last_action = f"{self.settings.toggle_hotkey} 自動喝水恢復"
            print(f"{self.settings.toggle_hotkey}：自動喝水已恢復")
            return

        self.auto_drink_enabled = not self.auto_drink_enabled
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
        self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
        self.gui.set_status(f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
        self.gui.show_toggle_notice("自動喝水已暫停")
        self.gui.set_current_percentages(None, None)
        self.last_action = f"{self.settings.toggle_hotkey} 自動喝水暫停"
        print(f"{self.settings.toggle_hotkey}：自動喝水已暫停")

    def toggle_scripts_enabled(self) -> None:
        self.toggle_auto_drink_enabled()

    def toggle_experience_efficiency(self) -> None:
        now = time.monotonic()
        enabled = not self.settings.exp_efficiency_enabled
        self.gui.set_exp_efficiency_enabled(enabled)
        if enabled:
            self._stop_experience_ocr_job()
            effective_now = self._resume_experience_clock(now)
            self.next_experience_capture_at = 0.0
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
            self._clear_potion_effect_state()
            self._play_toggle_beep(RESUME_BEEP_PATTERN)
            self.gui.set_status("總開關已啟用")
            self.gui.show_toggle_notice("總開關已啟用")
            self.last_action = f"{self.settings.emergency_stop_hotkey} 總開關啟用"
            print(f"{self.settings.emergency_stop_hotkey}：總開關已啟用")
            return

        self.scripts_enabled = False
        self.auto_drink_enabled = False
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
            winmm.mciSendStringW(f"close {alias}", buffer, len(buffer), None)
            open_command = f'open "{path}" type mpegvideo alias {alias}'
            if winmm.mciSendStringW(open_command, buffer, len(buffer), None) != 0:
                self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
                return
            winmm.mciSendStringW(f"setaudio {alias} volume to {MCI_MEDIA_VOLUME}", buffer, len(buffer), None)
            if winmm.mciSendStringW(f"play {alias} from 0", buffer, len(buffer), None) != 0:
                winmm.mciSendStringW(f"close {alias}", buffer, len(buffer), None)
                self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)
        except Exception:
            self._play_toggle_beep(EMERGENCY_STOP_BEEP_PATTERN)

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
            self._pause_experience_for_inactive_state(now, "設定快捷鍵中，保留統計")
            self.gui.set_current_percentages(None, None)
            return

        if now < self.next_capture_at:
            return
        self.next_capture_at = now + DEFAULT_CAPTURE_INTERVAL_SECONDS

        if not self.scripts_enabled:
            self._set_gameplay_hud_active(False, now)
            self._pause_experience_for_inactive_state(now, "總開關已暫停，保留統計")
            self.gui.set_status(f"總開關已關閉，按 {self.settings.emergency_stop_hotkey} 開啟")
            self.gui.set_current_percentages(None, None)
            return

        if not self.is_target_window_active():
            self._set_gameplay_hud_active(False, now)
            self._pause_experience_for_inactive_state(now, "等待楓星前景，保留統計")
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
                if self.auto_drink_enabled:
                    self._clear_uncertain_potion_observations(hp_percent, mp_percent)
                self.gui.set_status("HP/MP 條偵測不穩定，略過錯誤取樣")
            elif not self.auto_drink_enabled:
                self.gui.set_status(f"自動喝水已暫停，按 {self.settings.toggle_hotkey} 恢復")
            elif self._has_out_of_potion_hold():
                self.gui.set_status(self._out_of_potion_hold_status_message())
            else:
                self.gui.set_status("自動喝水監控中")
                self.gui.refresh_bar_preview_once()
            if self.settings.exp_efficiency_enabled:
                self._update_experience_efficiency(now)
            else:
                self._stop_experience_ocr_job()
                effective_now = self._pause_experience_clock(now)
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "已停用，保留統計" if snapshot.sample_count else "已停用"
                self.gui.set_experience_snapshot(snapshot)
            if self.auto_drink_enabled and hp_percent is not None and mp_percent is not None:
                if self._update_potion_effect_watch_cycles(now, hp_percent, mp_percent):
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
        if self._process_experience_ocr_job(now, effective_now=effective_now):
            return

        if self._continue_experience_ocr_burst(now, effective_now=effective_now):
            return

        if now < self.next_experience_capture_at:
            return

        regions = self._experience_text_regions()
        if not regions:
            self._clear_failed_experience_ocr_signature()
            self._clear_completed_experience_ocr_signature()
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "找不到 EXP 區域，保留統計" if snapshot.sample_count else "找不到 EXP 區域"
            self.gui.set_experience_snapshot(snapshot)
            return

        images = self._capture_experience_text_images(regions)
        if EXPERIENCE_BURST_CAPTURE_ATTEMPTS <= 1:
            self._submit_experience_ocr_burst(now, [images], effective_now=effective_now)
            return

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
        self._submit_experience_ocr_burst(now, burst.image_frames, effective_now=effective_now)
        return True

    def _capture_experience_text_image(self, region: tuple[int, int, int, int]) -> np.ndarray:
        left, top, width, height = region
        return np.asarray(self.sct.grab({"left": left, "top": top, "width": width, "height": height})).copy()

    def _capture_experience_text_images(self, regions: list[tuple[int, int, int, int]]) -> list[ExperienceOcrImage]:
        return [
            ExperienceOcrImage(
                self._capture_experience_text_image(region),
                self._experience_text_region_bar_crop_left_ratio(index),
                "primary" if index == 0 else "wide",
            )
            for index, region in enumerate(regions)
        ]

    def _submit_experience_ocr_burst(
        self,
        now: float,
        image_frames: list[list[np.ndarray]],
        *,
        effective_now: float | None = None,
    ) -> None:
        if self._experience_clock_is_paused():
            self._stop_experience_ocr_job()
            return
        if effective_now is None:
            effective_now = self._experience_effective_time(now)
        image_signature = self._experience_ocr_image_signature(image_frames)
        if self._is_repeated_completed_experience_ocr_signature(image_signature):
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "EXP ROI 未變化，保留統計"
            self.gui.set_experience_snapshot(snapshot)
            return
        if self._is_repeated_failed_experience_ocr_signature(image_signature):
            self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
            snapshot = self.experience_tracker.snapshot(effective_now)
            snapshot.status = "OCR ROI 未變化，保留統計" if snapshot.sample_count else "OCR ROI 未變化，等待畫面更新"
            self.gui.set_experience_snapshot(snapshot)
            return

        self.experience_ocr_job = ExperienceOcrJob(
            submitted_at=now,
            future=self.experience_ocr_executor.submit(
                self.experience_reader.read_burst_frames,
                [[self._copy_experience_ocr_image(image) for image in images] for images in image_frames],
            ),
            image_signature=image_signature,
            image_frames=[[self._copy_experience_ocr_image(image) for image in images] for images in image_frames],
        )
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        snapshot = self.experience_tracker.snapshot(effective_now)
        snapshot.status = "讀取經驗樣本中"
        self.gui.set_experience_snapshot(snapshot)

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
            return True

        self.experience_ocr_job = None
        self.next_experience_capture_at = now + EXPERIENCE_CAPTURE_INTERVAL_SECONDS
        try:
            reading = job.future.result()
        except Exception as exc:
            log_exception("OCR 背景工作失敗")
            reading = ExperienceTextReading(reason=f"OCR 背景工作失敗：{exc}")

        self._log_experience_ocr_reading(reading)
        self._log_experience_learning_case(reading)
        if reading.success and reading.current_exp is not None:
            tracker_samples = getattr(self.experience_tracker, "samples", None)
            has_tracker_samples = not isinstance(tracker_samples, list) or bool(tracker_samples)
            if reading.needs_bar_percent_guard and not has_tracker_samples:
                self._remember_failed_experience_ocr_signature(job)
                self.experience_tracker.record_ocr_result(True)
                self._log_experience_ocr_error(now, "EXP 合併格式需既有基準確認", reading.text)
                snapshot = self.experience_tracker.snapshot(effective_now)
                if snapshot.sample_count == 0:
                    snapshot.status = "等待明確 EXP 樣本"
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
                    self.gui.set_experience_snapshot(snapshot)
                    return True
                self._remember_failed_experience_ocr_signature(job)
                self._log_experience_sample_rejection(now, self.experience_tracker.last_status, reading)
                snapshot = self.experience_tracker.snapshot(effective_now)
                snapshot.status = "樣本已拒絕，詳見 Console"
                self.gui.set_experience_snapshot(snapshot)
                return True
            self._clear_failed_experience_ocr_signature()
            self.experience_tracker.record_ocr_result(True)
            self._remember_completed_experience_ocr_signature(job)
            self.gui.set_experience_snapshot(self.experience_tracker.snapshot(effective_now))
            return True

        self._remember_failed_experience_ocr_signature(job)
        self.experience_tracker.record_ocr_result(False)
        self._log_experience_ocr_error(now, reading.reason, reading.text)
        snapshot = self.experience_tracker.snapshot(effective_now)
        if snapshot.sample_count == 0:
            snapshot.status = "等待有效 EXP 樣本"
        self.gui.set_experience_snapshot(snapshot)
        return True

    def _stop_experience_ocr_job(self) -> None:
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

    def _log_experience_learning_case(self, reading: ExperienceTextReading) -> None:
        if reading.learning_case_id:
            print(f"EXP OCR learning case: {reading.learning_case_id}")

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
        primary = self._experience_text_region()
        if primary is None:
            return []

        regions = [primary]
        wide = self._wide_experience_text_region()
        if wide is not None and wide not in regions:
            regions.append(wide)
        return regions

    def _experience_text_region_bar_crop_left_ratio(self, region_index: int) -> float:
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
        if not self.settings.hp_enabled:
            self._clear_potion_bar_state("hp")
            return
        if self._out_of_potion_hold("hp") is not None:
            return
        if hp_percent is None:
            hp_percent = self._capture_transient_bar_percent("hp")
            if hp_percent is None:
                self._log_unstable_bar(now, "HP")
                return
        if not should_drink_for_threshold(hp_percent, self.settings.hp_threshold_percent):
            self._clear_potion_attempt_state("hp")
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
            self._clear_potion_attempt_state("hp")
            return
        if not self._is_target_window_active_before_send("HP", now):
            return

        tap_hotkey(self.settings.hp_key)
        self.last_hp_drink_at = now
        self._record_potion_effect_attempt("hp", now, hp_percent)
        self.last_action = f"HP 喝水：{self.settings.hp_key}"

    def _maybe_drink_mp(self, now: float, mp_percent: float | None) -> None:
        if not self.settings.mp_enabled:
            self._clear_potion_bar_state("mp")
            return
        if self._out_of_potion_hold("mp") is not None:
            return
        if mp_percent is None:
            mp_percent = self._capture_transient_bar_percent("mp")
            if mp_percent is None:
                self._log_unstable_bar(now, "MP")
                return
        if not should_drink_for_threshold(mp_percent, self.settings.mp_threshold_percent):
            self._clear_potion_attempt_state("mp")
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
            self._clear_potion_attempt_state("mp")
            return
        if not self._is_target_window_active_before_send("MP", now):
            return

        tap_hotkey(self.settings.mp_key)
        self.last_mp_drink_at = now
        self._record_potion_effect_attempt("mp", now, mp_percent)
        self.last_action = f"MP 喝水：{self.settings.mp_key}"

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
            self._set_potion_no_effect_count(bar_type, 0)
        bar_is_stable = self._potion_bar_is_stable_for_confirmation(bar_type, now)

        attempts = self._potion_effect_attempts(bar_type)
        if not bar_is_stable and not attempts:
            self._set_potion_no_effect_count(bar_type, 0)
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
            self._set_potion_no_effect_count(bar_type, 0)
            return True
        if not bar_is_stable:
            return True
        if self._potion_recent_damage_is_active(bar_type, now):
            return True
        if not self._potion_auto_hold_is_allowed(bar_type):
            self._set_potion_no_effect_count(bar_type, 0)
            return True

        no_effect_count = self._potion_no_effect_count(bar_type) + 1
        self._set_potion_no_effect_count(bar_type, no_effect_count)
        if no_effect_count >= POTION_EFFECT_NO_EFFECT_LIMIT:
            self._enter_out_of_potion_hold(bar_type, label, percent, now)
        return True

    def _record_potion_effect_attempt(self, bar_type: str, now: float, before_percent: float) -> None:
        attempt = PotionEffectAttempt(
            now,
            before_percent,
            pre_window_is_stable=self._potion_pre_window_is_stable(bar_type, now, before_percent),
        )
        attempts = [*self._potion_effect_attempts(bar_type), attempt]
        self._set_potion_effect_attempts(bar_type, attempts)

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
        self._set_potion_effect_attempts(bar_type, [])
        self._set_potion_no_effect_count(bar_type, 0)
        self._set_out_of_potion_hold(bar_type, None)
        self._set_potion_last_observed_percent(bar_type, None)
        self._set_potion_recent_samples(bar_type, [])
        self._set_potion_recent_damage_at(bar_type, -999.0)
        self._set_potion_damage_pressure_active(bar_type, False)

    def _clear_potion_attempt_state(self, bar_type: str) -> None:
        self._set_potion_effect_attempts(bar_type, [])
        self._set_potion_no_effect_count(bar_type, 0)
        self._set_potion_recent_samples(bar_type, [])
        self._set_potion_damage_pressure_active(bar_type, False)
        self._set_potion_recent_damage_at(bar_type, -999.0)

    def _clear_uncertain_potion_observations(self, hp_percent: float | None, mp_percent: float | None) -> None:
        if hp_percent is None:
            self._set_potion_effect_attempts("hp", [])
            self._set_potion_recent_samples("hp", [])
        if mp_percent is None:
            self._set_potion_effect_attempts("mp", [])
            self._set_potion_recent_samples("mp", [])

    def _potion_no_effect_count(self, bar_type: str) -> int:
        return self.hp_potion_no_effect_count if bar_type == "hp" else self.mp_potion_no_effect_count

    def _set_potion_no_effect_count(self, bar_type: str, count: int) -> None:
        if bar_type == "hp":
            self.hp_potion_no_effect_count = count
        else:
            self.mp_potion_no_effect_count = count

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
        self._set_potion_no_effect_count(bar_type, 0)

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
        return f"{label} 疑似無藥水，已停止 {label} 喝水；按 {self.settings.toggle_hotkey} 恢復"

    def _enter_out_of_potion_hold(self, bar_type: str, label: str, current_percent: float, now: float) -> None:
        self._set_potion_effect_attempts(bar_type, [])
        self._set_potion_no_effect_count(bar_type, POTION_EFFECT_NO_EFFECT_LIMIT)
        self._set_out_of_potion_hold(bar_type, OutOfPotionHold(now, current_percent))
        message = self._out_of_potion_hold_status_message()
        self.gui.set_status(message)
        self.gui.show_toggle_notice(f"{label} 疑似無藥水")
        self._play_media_file(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
        self.last_action = f"{label} 疑似無藥水"
        print(f"{label} 連續 {POTION_EFFECT_NO_EFFECT_LIMIT} 次喝水未見回升，已停止 {label} 喝水：{current_percent:.0f}%")

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
        worker = getattr(self, "control_hotkey_worker", None)
        if worker is not None:
            worker.stop()
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
