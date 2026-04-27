from __future__ import annotations

import ctypes
import sys
import time
import winsound
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

import mss
import numpy as np

from .constants import (
    ASYNC_KEY_DOWN_MASK,
    BAR_COLUMN_FILL_MIN_RATIO,
    BAR_DYNAMIC_SEARCH_HEIGHT_RATIO,
    BAR_DYNAMIC_SEARCH_LEFT_RATIO,
    BAR_DYNAMIC_SEARCH_TOP_RATIO,
    BAR_DYNAMIC_SEARCH_WIDTH_RATIO,
    BAR_DYNAMIC_EXPECTED_Y_TOLERANCE_RATIO,
    BAR_EMPTY_TAIL_MAX_CHROMA,
    BAR_EMPTY_TAIL_MAX_LUMINANCE,
    BAR_EMPTY_TAIL_MIN_RATIO,
    BAR_LEFT_EDGE_TOLERANCE_RATIO,
    BAR_MAX_INTERNAL_GAP_RATIO,
    BAR_MIN_BODY_ROW_COUNT,
    BAR_MIN_BODY_ROW_DENSITY,
    BAR_MIN_SEGMENT_DENSITY,
    BAR_PAIR_CACHE_SECONDS,
    BAR_SEARCH_MIN_RUN_PIXELS,
    BAR_TAIL_CHECK_MIN_WIDTH_RATIO,
    BASE_CAPTURE_HEIGHT,
    BASE_CAPTURE_WIDTH,
    DEFAULT_CAPTURE_INTERVAL_SECONDS,
    FADE_GUARD_BRIGHT_PIXEL_RATIO,
    FADE_GUARD_MEAN_LUMINANCE,
    FADE_GUARD_RECOVERY_SECONDS,
    FADE_GUARD_REQUIRED_FRAMES,
    FULL_BAR_SNAP_PERCENT,
    HP_BAR_REGION,
    LOADING_GUARD_BRIGHT_PIXEL_RATIO,
    LOADING_GUARD_LOW_SATURATION_RATIO,
    LOADING_GUARD_MEAN_LUMINANCE,
    MOD_NOREPEAT,
    MP_BAR_REGION,
    PAUSE_BEEP_FREQUENCY,
    PM_REMOVE,
    EMERGENCY_STOP_BEEP_FREQUENCY,
    RESUME_BEEP_FREQUENCY,
    SCRIPT_EMERGENCY_STOP_HOTKEY_ID,
    SCRIPT_TOGGLE_HOTKEY_ID,
    SETTINGS_SAVE_DEBOUNCE_SECONDS,
    TOGGLE_BEEP_DURATION_MS,
    TOGGLE_HOTKEY_DEBOUNCE_SECONDS,
    VK_F11,
    VK_F12,
    WM_HOTKEY,
)
from .gui import AutoPotionSettingsGui, GuiConsoleWriter
from .settings import AutoPotionSettings, load_settings, save_settings
from .win_input import Msg, Point, tap_hotkey, user32


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


def bgra_image_to_ppm_data(image: np.ndarray, scale: int = 3) -> bytes:
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("預覽圖片格式無效")
    scale = max(1, int(scale))
    rgb = image[:, :, :3][:, :, ::-1]
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    height, width, _channels = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + np.ascontiguousarray(rgb).tobytes()


class AutoPotionController:
    def __init__(
        self,
        is_target_window_active: Callable[[], bool],
        settings: AutoPotionSettings | None = None,
    ) -> None:
        self.is_target_window_active = is_target_window_active
        self.settings = settings or load_settings()
        self.gui = AutoPotionSettingsGui(self.settings)
        self.gui.set_bar_preview_provider(self.capture_bar_preview_images)
        self.sct = mss.mss()
        self.next_capture_at = 0.0
        self.last_hp_drink_at = -999.0
        self.last_mp_drink_at = -999.0
        self.last_error_at = -999.0
        self.last_unstable_bar_at = -999.0
        self.scripts_enabled = True
        self.hotkey_registered = False
        self.emergency_hotkey_registered = False
        self.f11_was_down = False
        self.f12_was_down = False
        self.last_toggle_hotkey_at = -999.0
        self.emergency_stop_requested = False
        self.last_action = "啟動"
        self.last_bar_debug: dict[str, BarDetectionDebug] = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        self.bottom_bar_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_regions_at = -999.0
        self.fade_guard_hits = 0
        self.fade_guard_until = 0.0
        self.pending_settings_snapshot = self.settings.snapshot()
        self.next_settings_save_at: float | None = None
        self.original_stdout: object | None = None
        self.original_stderr: object | None = None
        self._register_toggle_hotkey()

    def install_console_redirect(self) -> None:
        if isinstance(sys.stdout, GuiConsoleWriter):
            return
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = GuiConsoleWriter(self.gui, self.original_stdout)
        sys.stderr = GuiConsoleWriter(self.gui, self.original_stderr)

    def is_closed(self) -> bool:
        return not self.gui.exists()

    def _register_toggle_hotkey(self) -> None:
        if user32.RegisterHotKey(None, SCRIPT_TOGGLE_HOTKEY_ID, MOD_NOREPEAT, VK_F11):
            self.hotkey_registered = True
        else:
            error_code = ctypes.get_last_error()
            print(f"註冊 F11 總開關失敗，錯誤碼：{error_code}")

        if user32.RegisterHotKey(None, SCRIPT_EMERGENCY_STOP_HOTKEY_ID, MOD_NOREPEAT, VK_F12):
            self.emergency_hotkey_registered = True
        else:
            error_code = ctypes.get_last_error()
            print(f"註冊 F12 硬停止失敗，錯誤碼：{error_code}")

    def _unregister_toggle_hotkey(self) -> None:
        if self.hotkey_registered:
            if not user32.UnregisterHotKey(None, SCRIPT_TOGGLE_HOTKEY_ID):
                print(f"解除 F11 總開關註冊失敗，錯誤碼：{ctypes.get_last_error()}")
            self.hotkey_registered = False
        if self.emergency_hotkey_registered:
            if not user32.UnregisterHotKey(None, SCRIPT_EMERGENCY_STOP_HOTKEY_ID):
                print(f"解除 F12 硬停止註冊失敗，錯誤碼：{ctypes.get_last_error()}")
            self.emergency_hotkey_registered = False

    def poll_control_hotkeys(self) -> None:
        toggle_triggered = False
        emergency_stop_triggered = False
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

        f11_is_down = bool(user32.GetAsyncKeyState(VK_F11) & ASYNC_KEY_DOWN_MASK)
        if f11_is_down and not self.f11_was_down:
            toggle_triggered = True
        self.f11_was_down = f11_is_down

        f12_is_down = bool(user32.GetAsyncKeyState(VK_F12) & ASYNC_KEY_DOWN_MASK)
        if f12_is_down and not self.f12_was_down:
            emergency_stop_triggered = True
        self.f12_was_down = f12_is_down

        if emergency_stop_triggered:
            self.emergency_stop()
        elif toggle_triggered:
            self._try_toggle_scripts_enabled(time.monotonic())

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

    def toggle_scripts_enabled(self) -> None:
        self.scripts_enabled = not self.scripts_enabled
        if self.scripts_enabled:
            self._play_toggle_beep(RESUME_BEEP_FREQUENCY)
            self.gui.set_status("腳本已啟用")
            self.gui.show_toggle_notice("腳本已啟用")
            self.last_action = "F11 啟用"
            print("F11：腳本已啟用")
            return

        self.last_hp_drink_at = time.monotonic()
        self.last_mp_drink_at = self.last_hp_drink_at
        self._play_toggle_beep(PAUSE_BEEP_FREQUENCY)
        self.gui.set_status("腳本已暫停，按 F11 恢復")
        self.gui.show_toggle_notice("腳本已暫停")
        self.gui.set_current_percentages(None, None)
        self.last_action = "F11 暫停"
        print("F11：腳本已暫停")

    def emergency_stop(self) -> None:
        now = time.monotonic()
        self.scripts_enabled = False
        self.emergency_stop_requested = True
        self.last_hp_drink_at = now
        self.last_mp_drink_at = now
        self._play_toggle_beep(EMERGENCY_STOP_BEEP_FREQUENCY)
        self.gui.set_status("F12 硬停止：所有腳本已暫停")
        self.gui.show_toggle_notice("F12 硬停止")
        self.gui.set_current_percentages(None, None)
        self.last_action = "F12 硬停止"
        print("F12：硬停止，所有腳本已暫停")

    def _play_toggle_beep(self, frequency: int) -> None:
        try:
            winsound.Beep(frequency, TOGGLE_BEEP_DURATION_MS)
        except RuntimeError:
            try:
                winsound.MessageBeep()
            except RuntimeError:
                pass

    def update(self, now: float) -> None:
        self.poll_control_hotkeys()
        if not self.gui.pump():
            return
        self.poll_control_hotkeys()
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
            self.gui.set_bar_detection_debug(
                self._bar_detection_debug_text("hp"),
                self._bar_detection_debug_text("mp"),
            )
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
        if not self._is_target_window_active_before_send("HP"):
            return

        hp_percent = self._capture_bar_percent(HP_BAR_REGION, "hp", require_clear_tail=True)
        if hp_percent is None:
            self._log_unstable_bar(now, "HP")
            return
        if hp_percent > self.settings.hp_threshold_percent:
            return
        if not self._is_target_window_active_before_send("HP"):
            return

        tap_hotkey(self.settings.hp_key)
        self.last_hp_drink_at = now
        self.last_action = f"HP 喝水：{self.settings.hp_key}"
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
        if not self._is_target_window_active_before_send("MP"):
            return

        mp_percent = self._capture_bar_percent(MP_BAR_REGION, "mp", require_clear_tail=True)
        if mp_percent is None:
            self._log_unstable_bar(now, "MP")
            return
        if mp_percent > self.settings.mp_threshold_percent:
            return
        if not self._is_target_window_active_before_send("MP"):
            return

        tap_hotkey(self.settings.mp_key)
        self.last_mp_drink_at = now
        self.last_action = f"MP 喝水：{self.settings.mp_key}"
        print(f"MP {mp_percent:.0f}% <= {self.settings.mp_threshold_percent:.0f}%，按 {self.settings.mp_key}")

    def _is_target_window_active_before_send(self, label: str) -> bool:
        if self.is_target_window_active():
            return True
        self.gui.set_status("等待楓星成為前景視窗")
        self.gui.set_current_percentages(None, None)
        print(f"{label} 自動喝水略過：楓星不在前景")
        return False

    def _log_unstable_bar(self, now: float, label: str) -> None:
        if now - self.last_unstable_bar_at < 2.0:
            return
        self.last_unstable_bar_at = now
        print(f"{label} 條偵測不穩定，略過自動喝水")

    def _capture_bar_percent(
        self,
        base_region: tuple[int, int, int, int],
        bar_type: str,
        require_clear_tail: bool = False,
    ) -> float | None:
        paired_region = self._find_bottom_bar_pair_regions().get(bar_type)
        if paired_region is not None:
            percent = self._capture_bar_percent_from_region(
                paired_region,
                bar_type,
                require_clear_tail,
                "成對搜尋",
            )
            if percent is not None:
                return percent

        left, top, width, height = self._scale_region_to_foreground_client(base_region)
        percent = self._capture_bar_percent_from_region(
            (left, top, width, height),
            bar_type,
            require_clear_tail,
            "client 比例縮放",
        )
        if percent is not None:
            return percent

        dynamic_region = self._find_bar_region_near_bottom(bar_type)
        if dynamic_region is not None:
            percent = self._capture_bar_percent_from_region(
                dynamic_region,
                bar_type,
                require_clear_tail,
                "底部動態搜尋",
            )
            if percent is not None:
                return percent

        left, top, width, height = self._scale_region_to_foreground_game(base_region)
        return self._capture_bar_percent_from_region(
            (left, top, width, height),
            bar_type,
            require_clear_tail,
            "game bounds fallback",
        )

    def _find_bottom_bar_pair_regions(self) -> dict[str, tuple[int, int, int, int]]:
        now = time.monotonic()
        if now - self.bottom_bar_regions_at <= BAR_PAIR_CACHE_SECONDS:
            return self.bottom_bar_regions

        self.bottom_bar_regions_at = now
        self.bottom_bar_regions = {}
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        search_left = client_left + round(client_width * BAR_DYNAMIC_SEARCH_LEFT_RATIO)
        search_top = client_top + round(client_height * BAR_DYNAMIC_SEARCH_TOP_RATIO)
        search_width = max(1, round(client_width * BAR_DYNAMIC_SEARCH_WIDTH_RATIO))
        search_height = max(1, round(client_height * BAR_DYNAMIC_SEARCH_HEIGHT_RATIO))
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
        hp_candidates = self._bar_run_candidates(self._bar_color_mask(image, "hp"), client_width)
        mp_candidates = self._bar_run_candidates(self._bar_color_mask(image, "mp"), client_width)

        best_pair: tuple[tuple[int, int, int], tuple[int, int, int], float] | None = None
        expected_gap = client_width * ((MP_BAR_REGION[0] - HP_BAR_REGION[0]) / BASE_CAPTURE_WIDTH)
        expected_row = search_height * (
            ((HP_BAR_REGION[1] + HP_BAR_REGION[3] / 2) / BASE_CAPTURE_HEIGHT - BAR_DYNAMIC_SEARCH_TOP_RATIO)
            / BAR_DYNAMIC_SEARCH_HEIGHT_RATIO
        )
        max_expected_row_delta = max(8, round(client_height * BAR_DYNAMIC_EXPECTED_Y_TOLERANCE_RATIO))
        max_y_delta = max(4, round(client_height * 0.018))
        min_gap = max(24, round(client_width * 0.08))
        max_gap = max(min_gap + 1, round(client_width * 0.28))

        for hp_start, hp_row, hp_length in hp_candidates:
            for mp_start, mp_row, mp_length in mp_candidates:
                if mp_start <= hp_start:
                    continue
                y_delta = abs(mp_row - hp_row)
                if y_delta > max_y_delta:
                    continue
                expected_row_delta = abs(((hp_row + mp_row) / 2) - expected_row)
                if expected_row_delta > max_expected_row_delta:
                    continue
                gap = mp_start - hp_start
                if gap < min_gap or gap > max_gap:
                    continue
                score = hp_length + mp_length - y_delta * 3 - expected_row_delta * 0.5 - abs(gap - expected_gap) * 0.1
                if best_pair is None or score > best_pair[2]:
                    best_pair = ((hp_start, hp_row, hp_length), (mp_start, mp_row, mp_length), score)

        if best_pair is None:
            return self.bottom_bar_regions

        expected_width = max(1, round(client_width * (HP_BAR_REGION[2] / BASE_CAPTURE_WIDTH)))
        expected_height = max(1, round(client_height * (HP_BAR_REGION[3] / BASE_CAPTURE_HEIGHT)))
        hp_start, hp_row, _hp_length = best_pair[0]
        mp_start, mp_row, _mp_length = best_pair[1]
        self.bottom_bar_regions = {
            "hp": (
                search_left + max(0, hp_start - 4),
                search_top + max(0, hp_row - expected_height // 2),
                expected_width,
                expected_height,
            ),
            "mp": (
                search_left + max(0, mp_start - 4),
                search_top + max(0, mp_row - expected_height // 2),
                expected_width,
                expected_height,
            ),
        }
        return self.bottom_bar_regions

    def _capture_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        require_clear_tail: bool = False,
        source: str = "指定區域",
    ) -> float | None:
        left, top, width, height = region
        image = np.asarray(self.sct.grab({"left": left, "top": top, "width": width, "height": height}))
        mask = self._bar_color_mask(image, bar_type)
        percent, reason, tail_clear = self._percent_from_bar_mask_result(mask, image, require_clear_tail)
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

    def capture_bar_preview_images(self) -> dict[str, dict[str, object]]:
        previews: dict[str, dict[str, object]] = {}
        for bar_type in ("hp", "mp"):
            debug = self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type))
            label = "HP" if bar_type == "hp" else "MP"
            if debug.region is None:
                previews[bar_type] = {
                    "label": label,
                    "debug": self._bar_detection_debug_text(bar_type),
                    "image": None,
                    "error": "尚無可預覽的偵測區域",
                }
                continue

            left, top, width, height = debug.region
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
                previews[bar_type] = {
                    "label": label,
                    "debug": self._bar_detection_debug_text(bar_type),
                    "image": bgra_image_to_ppm_data(image),
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
        min_run_pixels = max(BAR_SEARCH_MIN_RUN_PIXELS, round(client_width * 0.035))
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

    def _find_bar_region_near_bottom(self, bar_type: str) -> tuple[int, int, int, int] | None:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        search_left = client_left + round(client_width * BAR_DYNAMIC_SEARCH_LEFT_RATIO)
        search_top = client_top + round(client_height * BAR_DYNAMIC_SEARCH_TOP_RATIO)
        search_width = max(1, round(client_width * BAR_DYNAMIC_SEARCH_WIDTH_RATIO))
        search_height = max(1, round(client_height * BAR_DYNAMIC_SEARCH_HEIGHT_RATIO))

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
        expected_row = search_height * (
            ((HP_BAR_REGION[1] + HP_BAR_REGION[3] / 2) / BASE_CAPTURE_HEIGHT - BAR_DYNAMIC_SEARCH_TOP_RATIO)
            / BAR_DYNAMIC_SEARCH_HEIGHT_RATIO
        )
        max_expected_row_delta = max(8, round(client_height * BAR_DYNAMIC_EXPECTED_Y_TOLERANCE_RATIO))
        best_score: float | None = None

        for row_index, row in enumerate(mask):
            padded = np.concatenate(([False], row, [False]))
            changes = np.flatnonzero(padded[1:] != padded[:-1])
            for start, end in zip(changes[::2], changes[1::2]):
                run_length = int(end - start)
                if run_length < BAR_SEARCH_MIN_RUN_PIXELS:
                    continue
                if not self._bar_run_has_horizontal_body(mask, int(start), int(end - 1)):
                    continue
                expected_row_delta = abs(row_index - expected_row)
                if expected_row_delta > max_expected_row_delta:
                    continue
                score = run_length - expected_row_delta * 0.5
                if best_score is None or score > best_score:
                    best_run = (int(start), int(row_index), run_length)
                    best_score = score

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

    def _scale_region_to_foreground_game(self, base_region: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        game_left, game_top, game_width, game_height = self._foreground_game_bounds()
        scale_x = game_width / BASE_CAPTURE_WIDTH
        scale_y = game_height / BASE_CAPTURE_HEIGHT
        x, y, width, height = base_region
        return (
            game_left + round(x * scale_x),
            game_top + round(y * scale_y),
            max(1, round(width * scale_x)),
            max(1, round(height * scale_y)),
        )

    def _foreground_game_bounds(self) -> tuple[int, int, int, int]:
        client_left, client_top, client_width, client_height = self._foreground_client_bounds()
        scale = min(client_width / BASE_CAPTURE_WIDTH, client_height / BASE_CAPTURE_HEIGHT)
        game_width = max(1, round(BASE_CAPTURE_WIDTH * scale))
        game_height = max(1, round(BASE_CAPTURE_HEIGHT * scale))
        game_left = client_left + max(0, (client_width - game_width) // 2)
        game_top = client_top + max(0, (client_height - game_height) // 2)
        return game_left, game_top, game_width, game_height

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
