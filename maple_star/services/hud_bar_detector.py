from __future__ import annotations

import ctypes
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from ..adapters.win_input import BitmapInfo, gdi32, user32
from ..constants import (
    BAR_COLUMN_FILL_MIN_RATIO,
    BAR_DYNAMIC_SEARCH_HEIGHT_RATIO,
    BAR_DYNAMIC_SEARCH_LEFT_RATIO,
    BAR_DYNAMIC_SEARCH_TOP_RATIO,
    BAR_DYNAMIC_SEARCH_WIDTH_RATIO,
    BAR_EMPTY_TAIL_MAX_CHROMA,
    BAR_EMPTY_TAIL_MAX_LUMINANCE,
    BAR_EMPTY_TAIL_MIN_RATIO,
    BAR_FULL_WIDTH_MIN_COLUMN_RATIO,
    BAR_FULL_REGION_LEFT_PADDING_RATIO,
    BAR_FULL_REGION_RIGHT_PADDING_RATIO,
    BAR_FULL_REGION_VERTICAL_PADDING_RATIO,
    BAR_LEFT_EDGE_TOLERANCE_RATIO,
    BAR_MAX_INTERNAL_GAP_RATIO,
    BAR_PAIR_CACHE_SECONDS,
    BAR_PAIR_MIN_SEARCH_ROW_RATIO,
    BAR_MIN_BODY_ROW_COUNT,
    BAR_MIN_BODY_ROW_DENSITY,
    BAR_MIN_SEGMENT_DENSITY,
    BAR_SEARCH_MIN_RUN_PIXELS,
    BAR_STABLE_SAMPLE_HOLD_SECONDS,
    BAR_TAIL_CHECK_MIN_WIDTH_RATIO,
    BAR_VERTICAL_BODY_ROW_DENSITY,
    FADE_GUARD_BRIGHT_PIXEL_RATIO,
    FADE_GUARD_MEAN_LUMINANCE,
    FULL_BAR_SNAP_PERCENT,
    GAME_CONTENT_ASPECT_RATIO,
    GAME_CONTENT_LETTERBOX_MIN_MARGIN_PIXELS,
    LOADING_GUARD_BRIGHT_PIXEL_RATIO,
    LOADING_GUARD_LOW_SATURATION_RATIO,
    LOADING_GUARD_MEAN_LUMINANCE,
)
from ..models.controller_state import BarDetectionDebug, BottomHudLayout, HudSearchArea
from .bar_detection import bgra_image_to_ppm_data, loading_screen_metrics, normalize_bar_percent
from .hud_bar_detection_algorithms import HudBarDetectionAlgorithms
from .screen_capture import ScreenCapturePort


DIRECT_BAR_BIT_COUNT = 32
DIRECT_BAR_BYTES_PER_PIXEL = 4
DIB_RGB_COLORS = 0
GDI_BI_RGB = 0
GDI_SRCCOPY = 0x00CC0020
BAR_EMPTY_TRACK_MIN_NEUTRAL_RATIO = 0.65
BAR_EMPTY_TRACK_MAX_FOREGROUND_RATIO = 0.035
BAR_PREVIEW_IMAGE_SIZE = (240, 22)
HUD_LABEL_MATCH_THRESHOLD = 0.42
HUD_LABEL_SCALE_MIN = 0.70
HUD_LABEL_SCALE_MAX = 1.60
HUD_LABEL_SCALE_STEP = 0.05
HUD_LABEL_SCALE_TOLERANCE = 0.16
HUD_LABEL_GEOMETRY_Y_TOLERANCE_RATIO = 1.10
HUD_LABEL_BAR_SEARCH_RIGHT_RATIO = 0.48
BAR_PAIR_HP_MAX_LEFT_RATIO = 0.48
BAR_PAIR_MIN_GAP_RATIO = 0.10
BAR_PAIR_MAX_GAP_RATIO = 0.24
BAR_PAIR_REUSE_MIN_GAP_RATIO = 0.06
BAR_PAIR_REUSE_MAX_GAP_RATIO = 0.34
BAR_PAIR_REUSE_MAX_CENTER_Y_DELTA_RATIO = 1.10
BAR_PAIR_REUSE_WIDTH_RATIO_MIN = 0.55
BAR_PAIR_REUSE_HEIGHT_RATIO_MAX = 2.40
RECENT_HUD_GEOMETRY_GRACE_SECONDS = 2.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HUD_LABEL_TEMPLATE_PATHS = {
    "hp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_hp.png",
    "mp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_mp.png",
    "exp": PROJECT_ROOT / "maple_star" / "assets" / "hud_label_exp.png",
}


@dataclass(frozen=True)
class HudDetectionRequest:
    now: float
    target_hwnd: int
    target_client_rect: tuple[int, int, int, int] | None
    detect_hp: bool
    detect_mp: bool
    require_clear_tail_hp: bool
    require_clear_tail_mp: bool
    preview_requested: bool = False


@dataclass(frozen=True)
class HudDetectionResult:
    hp_percent: float | None
    mp_percent: float | None
    layout: BottomHudLayout | None
    hp_region: tuple[int, int, int, int] | None
    mp_region: tuple[int, int, int, int] | None
    exp_region: tuple[int, int, int, int] | None
    gameplay_hud_active: bool
    transition_kind: Literal["none", "loading", "fade"]
    preview_images: Mapping[str, np.ndarray]
    debug: Mapping[str, BarDetectionDebug]


class DirectBarCaptureContext:
    def __init__(
        self,
        *,
        user32_provider: Callable[[], object] = lambda: user32,
        gdi32_provider: Callable[[], object] = lambda: gdi32,
    ) -> None:
        self._user32_provider = user32_provider
        self._gdi32_provider = gdi32_provider
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
        gdi = self._gdi32_provider()
        if not gdi.BitBlt(
            self.memory_dc,
            0,
            0,
            width,
            height,
            self.screen_dc,
            left,
            top,
            GDI_SRCCOPY,
        ):
            return None
        assert self.buffer is not None
        copied_rows = gdi.GetDIBits(
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
        return np.frombuffer(self.buffer, dtype=np.uint8).reshape(
            (height, width, DIRECT_BAR_BYTES_PER_PIXEL)
        ).copy()

    def _ensure_size(self, width: int, height: int) -> bool:
        user = self._user32_provider()
        gdi = self._gdi32_provider()
        if not self.screen_dc:
            self.screen_dc = user.GetDC(None)
            if not self.screen_dc:
                return False
        if not self.memory_dc:
            self.memory_dc = gdi.CreateCompatibleDC(self.screen_dc)
            if not self.memory_dc:
                self.close()
                return False
        if self.size == (width, height) and self.bitmap and self.buffer is not None:
            return True

        self._delete_bitmap()
        bitmap = gdi.CreateCompatibleBitmap(self.screen_dc, width, height)
        if not bitmap:
            self.close()
            return False
        old_bitmap = gdi.SelectObject(self.memory_dc, bitmap)
        if not old_bitmap:
            gdi.DeleteObject(bitmap)
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
        gdi = self._gdi32_provider()
        if self.bitmap:
            if self.old_bitmap:
                gdi.SelectObject(self.memory_dc, self.old_bitmap)
            gdi.DeleteObject(self.bitmap)
        self.bitmap = 0
        self.old_bitmap = 0
        self.size = None
        self.buffer = None

    def close(self) -> None:
        self._delete_bitmap()
        gdi = self._gdi32_provider()
        if self.memory_dc:
            gdi.DeleteDC(self.memory_dc)
            self.memory_dc = 0
        if self.screen_dc:
            self._user32_provider().ReleaseDC(None, self.screen_dc)
            self.screen_dc = 0


class HudBarDetector(HudBarDetectionAlgorithms):
    def __init__(
        self,
        screen_capture: ScreenCapturePort | None,
        *,
        user32_provider: Callable[[], object] = lambda: user32,
        gdi32_provider: Callable[[], object] = lambda: gdi32,
        monotonic: Callable[[], float] = time.monotonic,
        normalize_percent: Callable[[float], float] = normalize_bar_percent,
    ) -> None:
        self.screen_capture = screen_capture
        self._user32_provider = user32_provider
        self._gdi32_provider = gdi32_provider
        self._monotonic = monotonic
        self._normalize_percent = normalize_percent
        self.direct_capture_context = self.create_direct_capture_context()
        self.template_cache: dict[str, np.ndarray] = {}
        self.stable_bar_samples: dict[
            str,
            tuple[float, tuple[int, int, int, int], float],
        ] = {}
        self.bottom_bar_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_track_regions: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_regions_client: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_track_regions_client: dict[str, tuple[int, int, int, int]] = {}
        self.bottom_bar_client_size: tuple[int, int] | None = None
        self.bottom_hud_layout: BottomHudLayout | None = None
        self.bottom_bar_regions_at = -999.0
        self.bottom_bar_client_bounds: tuple[int, int, int, int] | None = None
        self.pending_bottom_bar_track_regions: dict[str, tuple[int, int, int, int]] = {}
        self.last_bar_debug: dict[str, BarDetectionDebug] = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        self.direct_bar_failure_count = 0
        self.last_direct_bar_failure_warning_at = -999.0
        self.last_direct_bar_failure_reason = ""
        self.fade_guard_hits = 0
        self.fade_guard_until = 0.0
        self._closed = False

    def direct_bar_image_from_region(
        self,
        region: tuple[int, int, int, int],
    ) -> np.ndarray | None:
        left, top, width, height = region
        if width <= 0 or height <= 0:
            return None
        return self.direct_capture_context.capture(left, top, width, height)

    @staticmethod
    def bar_percent_inputs(
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

    def remember_stable_bar_sample(
        self,
        bar_type: str,
        percent: float,
        region: tuple[int, int, int, int],
    ) -> None:
        self.stable_bar_samples[bar_type] = (self._monotonic(), region, percent)

    def recent_stable_bar_percent(
        self,
        bar_type: str,
        region: tuple[int, int, int, int],
    ) -> float | None:
        sampled_at, stable_region, percent = self.stable_bar_samples.get(
            bar_type,
            (-999.0, None, None),
        )
        if stable_region != region:
            return None
        if self._monotonic() - sampled_at > BAR_STABLE_SAMPLE_HOLD_SECONDS:
            return None
        return percent

    def percent_from_bar_mask(
        self,
        mask: np.ndarray,
        image: np.ndarray | None = None,
        require_clear_tail: bool = False,
    ) -> float | None:
        percent, _reason, _tail_clear = self.percent_from_bar_mask_result(
            mask,
            image,
            require_clear_tail,
        )
        return percent

    def percent_from_bar_mask_result(
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
            and self.bar_run_has_horizontal_body(mask, 0, width - 1)
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
        if not self.bar_run_has_horizontal_body(mask, start, end):
            return None, "水平 body 不足", None

        tail_clear: bool | None = None
        if require_clear_tail and image is not None:
            tail_clear = not self.bar_tail_looks_obstructed(image, end)
            if not tail_clear:
                return None, "尾段疑似被遮擋", tail_clear

        return self._normalize_percent(float((end + 1) / width * 100.0)), "OK", tail_clear

    @staticmethod
    def bar_track_looks_empty(mask: np.ndarray, image: np.ndarray | None) -> bool:
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
        return (
            float(neutral_track.mean()) >= BAR_EMPTY_TRACK_MIN_NEUTRAL_RATIO
            and float(foreground_detail.mean()) <= BAR_EMPTY_TRACK_MAX_FOREGROUND_RATIO
        )

    def set_bar_detection_debug(
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

    def bar_detection_debug_text(self, bar_type: str) -> str:
        debug = self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type))
        label = "HP" if bar_type == "hp" else "MP"
        percent = "--" if debug.percent is None else f"{debug.percent:.0f}%"
        source = self.compact_bar_debug_source(debug.source)
        tail = ""
        if debug.require_clear_tail:
            tail = " | tail=OK" if debug.tail_clear else " | tail=FAIL"
        return f"{label}: {source} | {percent} | {debug.reason}{tail}"

    @staticmethod
    def compact_bar_debug_source(source: str) -> str:
        return {"直接取色": "直取", "自動定位": "定位"}.get(source, source)

    def current_bar_detection_regions(self) -> dict[str, tuple[int, int, int, int] | None]:
        return {
            bar_type: self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type)).region
            for bar_type in ("hp", "mp")
        }

    def capture_bar_preview_images(
        self,
        *,
        make_target_topmost: bool,
        target_hwnd: int,
        topmost_context: Callable[[int], AbstractContextManager[bool]],
        wait_for_target_ready: Callable[[int], bool],
        bar_color_mask: Callable[[np.ndarray, str], np.ndarray] | None = None,
        percent_from_bar_mask: Callable[[np.ndarray, np.ndarray | None], float | None] | None = None,
    ) -> dict[str, dict[str, object]]:
        missing_regions = [
            bar_type
            for bar_type in ("hp", "mp")
            if self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type)).region is None
        ]
        if missing_regions:
            return self._preview_error_results("尚無可預覽的偵測區域")

        with topmost_context(target_hwnd) as target_is_ready:
            if make_target_topmost and not target_is_ready:
                return self._preview_error_results("無法顯示目標遊戲視窗，預覽未更新")
            if make_target_topmost and not wait_for_target_ready(target_hwnd):
                return self._preview_error_results("目標遊戲視窗尚未完成顯示，預覽未更新")

            previews: dict[str, dict[str, object]] = {}
            for bar_type in ("hp", "mp"):
                debug = self.last_bar_debug.get(bar_type, BarDetectionDebug(bar_type))
                label = "HP" if bar_type == "hp" else "MP"
                preview_region = debug.track_region or debug.region
                left, top, width, height = preview_region or (0, 0, 0, 0)
                try:
                    if self.screen_capture is None:
                        raise RuntimeError("HUD detector 尚未連接畫面擷取服務")
                    image = self.screen_capture.grab(
                        {"left": left, "top": top, "width": width, "height": height}
                    )
                    mask = (bar_color_mask or self.bar_color_mask)(image, bar_type)
                    track_region = self.bottom_bar_track_regions.get(bar_type)
                    percent_mask, percent_image = self.bar_percent_inputs(
                        preview_region or (left, top, width, height),
                        mask,
                        image,
                        None if debug.track_region is not None else track_region,
                    )
                    percent_reader = percent_from_bar_mask or self.percent_from_bar_mask
                    if percent_reader(percent_mask, percent_image) is None:
                        previews[bar_type] = self._preview_result(
                            bar_type,
                            error="預覽截圖未通過 HP/MP 色條驗證",
                        )
                        continue
                    previews[bar_type] = self._preview_result(
                        bar_type,
                        image=bgra_image_to_ppm_data(image, target_size=BAR_PREVIEW_IMAGE_SIZE),
                    )
                except Exception as exc:
                    previews[bar_type] = self._preview_result(bar_type, error=str(exc))
            return previews

    def _preview_error_results(self, error: str) -> dict[str, dict[str, object]]:
        return {bar_type: self._preview_result(bar_type, error=error) for bar_type in ("hp", "mp")}

    def _preview_result(
        self,
        bar_type: str,
        *,
        image: object | None = None,
        error: str = "",
    ) -> dict[str, object]:
        return {
            "label": "HP" if bar_type == "hp" else "MP",
            "debug": self.bar_detection_debug_text(bar_type),
            "image": image,
            "error": error,
        }

    @staticmethod
    def bar_run_has_horizontal_body(mask: np.ndarray, start: int, end: int) -> bool:
        if end < start:
            return False
        segment = mask[:, start : end + 1]
        if segment.size == 0:
            return False
        row_density = segment.mean(axis=1)
        dense_row_count = int((row_density >= BAR_MIN_BODY_ROW_DENSITY).sum())
        return dense_row_count >= min(BAR_MIN_BODY_ROW_COUNT, segment.shape[0])

    @staticmethod
    def bar_tail_looks_obstructed(image: np.ndarray, fill_end: int) -> bool:
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
        empty_slot = (luminance <= BAR_EMPTY_TAIL_MAX_LUMINANCE) & (chroma <= BAR_EMPTY_TAIL_MAX_CHROMA)
        return float(empty_slot.mean()) < BAR_EMPTY_TAIL_MIN_RATIO

    def bar_run_candidates(self, mask: np.ndarray, client_width: int) -> list[tuple[int, int, int]]:
        min_run_pixels = max(BAR_SEARCH_MIN_RUN_PIXELS, round(client_width * 0.015))
        candidates: list[tuple[int, int, int]] = []
        for row_index, row in enumerate(mask):
            padded = np.concatenate(([False], row, [False]))
            changes = np.flatnonzero(padded[1:] != padded[:-1])
            for start, end in zip(changes[::2], changes[1::2]):
                run_length = int(end - start)
                if run_length < min_run_pixels:
                    continue
                if not self.bar_run_has_horizontal_body(mask, int(start), int(end - 1)):
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

    @staticmethod
    def bar_color_mask(image: np.ndarray, bar_type: str) -> np.ndarray:
        bgra = image[:, :, :3]
        blue = bgra[:, :, 0].astype(np.int16)
        green = bgra[:, :, 1].astype(np.int16)
        red = bgra[:, :, 2].astype(np.int16)
        if bar_type == "hp":
            return (red > 150) & (green < 120) & (blue < 150) & (red > green + 40) & (red > blue + 40)
        if bar_type == "mp":
            return (blue > 140) & (green > 75) & (red < 140) & (blue > red + 35)
        return (green > 130) & (red < 170) & (blue < 170) & (green > red + 25) & (green > blue + 25)

    def direct_bar_color_mask(self, image: np.ndarray, bar_type: str) -> np.ndarray:
        mask = self.bar_color_mask(image, bar_type)
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

    _bar_color_mask = bar_color_mask
    _direct_bar_color_mask = direct_bar_color_mask
    _bar_percent_inputs = bar_percent_inputs
    _percent_from_bar_mask_result = percent_from_bar_mask_result
    _bar_track_looks_empty = bar_track_looks_empty
    _remember_stable_bar_sample = remember_stable_bar_sample
    _recent_stable_bar_percent = recent_stable_bar_percent
    _set_bar_detection_debug = set_bar_detection_debug
    _direct_bar_image_from_region = direct_bar_image_from_region

    def _record_direct_bar_success(self) -> None:
        self.direct_bar_failure_count = 0
        self.last_direct_bar_failure_reason = ""

    def _note_direct_bar_failure_reason(self, reason: str) -> None:
        self.last_direct_bar_failure_reason = reason

    def is_transition_fade_active(
        self,
        gameplay_bounds: tuple[int, int, int, int],
    ) -> bool:
        if self.screen_capture is None:
            raise RuntimeError("HUD detector 尚未連接畫面擷取服務")
        gameplay_left, gameplay_top, gameplay_width, gameplay_height = gameplay_bounds
        sample_top = gameplay_top + round(gameplay_height * 0.88)
        sample_height = max(1, round(gameplay_height * 0.10))
        image = self.screen_capture.grab(
            {
                "left": gameplay_left,
                "top": sample_top,
                "width": gameplay_width,
                "height": sample_height,
            }
        )
        bgra = image[:, :, :3].astype(np.float32)
        luminance = bgra[:, :, 2] * 0.299 + bgra[:, :, 1] * 0.587 + bgra[:, :, 0] * 0.114
        return (
            float(luminance.mean()) < FADE_GUARD_MEAN_LUMINANCE
            and float((luminance > 110.0).mean()) < FADE_GUARD_BRIGHT_PIXEL_RATIO
        )

    def is_channel_loading_screen_active(
        self,
        gameplay_bounds: tuple[int, int, int, int],
    ) -> bool:
        if self.screen_capture is None:
            raise RuntimeError("HUD detector 尚未連接畫面擷取服務")
        gameplay_left, gameplay_top, gameplay_width, gameplay_height = gameplay_bounds
        image = self.screen_capture.grab(
            {
                "left": gameplay_left + round(gameplay_width * 0.14),
                "top": gameplay_top + round(gameplay_height * 0.12),
                "width": max(1, round(gameplay_width * 0.72)),
                "height": max(1, round(gameplay_height * 0.76)),
            }
        )
        mean_luminance, bright_pixel_ratio, low_saturation_ratio = loading_screen_metrics(image)
        return (
            mean_luminance > LOADING_GUARD_MEAN_LUMINANCE
            and bright_pixel_ratio > LOADING_GUARD_BRIGHT_PIXEL_RATIO
            and low_saturation_ratio > LOADING_GUARD_LOW_SATURATION_RATIO
        )

    def detect(
        self,
        request: HudDetectionRequest,
        *,
        bar_color_mask: Callable[[np.ndarray, str], np.ndarray] | None = None,
        find_regions: Callable[..., dict[str, tuple[int, int, int, int]]] | None = None,
        set_debug: Callable[..., None] | None = None,
    ) -> HudDetectionResult:
        client_bounds = request.target_client_rect
        if client_bounds is None:
            raise RuntimeError("HUD detector 缺少目標 client bounds")
        previous_regions = dict(self.bottom_bar_regions)
        previous_track_regions = dict(self.bottom_bar_track_regions)
        previous_client_bounds = self.bottom_bar_client_bounds
        previous_regions_at = self.bottom_bar_regions_at
        previous_layout = self.bottom_hud_layout
        if find_regions is None:
            regions = self._find_bottom_bar_pair_regions(
                client_bounds,
                bar_color_mask=bar_color_mask,
                use_cache=False,
                allow_stale_on_failure=False,
            )
        else:
            regions = find_regions(use_cache=False, allow_stale_on_failure=False)
        active = "hp" in regions and "mp" in regions
        if not active:
            if (
                request.now - previous_regions_at <= RECENT_HUD_GEOMETRY_GRACE_SECONDS
                and previous_client_bounds == client_bounds
                and self._bar_region_pair_geometry_is_valid(
                    previous_regions,
                    previous_track_regions,
                    client_bounds,
                )
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
            for bar_type in ("hp", "mp"):
                (set_debug or self.set_bar_detection_debug)(
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
        return HudDetectionResult(
            hp_percent=None,
            mp_percent=None,
            layout=self.bottom_hud_layout,
            hp_region=self.bottom_bar_regions.get("hp"),
            mp_region=self.bottom_bar_regions.get("mp"),
            exp_region=(self.bottom_hud_layout.exp_text_region if self.bottom_hud_layout else None),
            gameplay_hud_active=active,
            transition_kind="none",
            preview_images={},
            debug=dict(self.last_bar_debug),
        )

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

    def _cache_bottom_bar_client_regions(
        self,
        client_bounds: tuple[int, int, int, int],
    ) -> None:
        client_left, client_top, client_width, client_height = client_bounds
        self.bottom_bar_client_size = (client_width, client_height)
        self.bottom_bar_regions_client = {
            bar_type: self._screen_region_to_client(region, client_left, client_top)
            for bar_type, region in self.bottom_bar_regions.items()
        }
        self.bottom_bar_track_regions_client = {
            bar_type: self._screen_region_to_client(region, client_left, client_top)
            for bar_type, region in self.bottom_bar_track_regions.items()
        }

    @staticmethod
    def _screen_region_to_client(
        region: tuple[int, int, int, int],
        client_left: int,
        client_top: int,
    ) -> tuple[int, int, int, int]:
        left, top, width, height = region
        return left - client_left, top - client_top, width, height

    @staticmethod
    def _client_region_to_screen(
        region: tuple[int, int, int, int],
        client_left: int,
        client_top: int,
    ) -> tuple[int, int, int, int]:
        left, top, width, height = region
        return client_left + left, client_top + top, width, height

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
        client_width = client_bounds[2] if client_bounds is not None else max(
            mp_left + mp_width,
            hp_left + hp_width,
        )
        min_gap = max(24.0, client_width * BAR_PAIR_REUSE_MIN_GAP_RATIO)
        max_gap = max(min_gap + 1.0, client_width * BAR_PAIR_REUSE_MAX_GAP_RATIO)
        left_gap = mp_left - hp_left
        if left_gap < min_gap or left_gap > max_gap:
            return False
        hp_left_in_client = hp_left - client_bounds[0] if client_bounds is not None else hp_left
        return hp_left_in_client <= client_width * (BAR_PAIR_HP_MAX_LEFT_RATIO + 0.08)

    def can_keep_recent_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        regions_at: float,
        now: float,
        current_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        return (
            now - regions_at <= RECENT_HUD_GEOMETRY_GRACE_SECONDS
            and "hp" in regions
            and "mp" in regions
            and client_bounds is not None
            and client_bounds == current_bounds
            and self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds)
        )

    @staticmethod
    def _bar_region_rect_is_valid(
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

    def _find_bottom_bar_pair_regions(
        self,
        client_bounds: tuple[int, int, int, int],
        *,
        bar_color_mask: Callable[[np.ndarray, str], np.ndarray] | None = None,
        use_cache: bool = True,
        allow_stale_on_failure: bool = True,
    ) -> dict[str, tuple[int, int, int, int]]:
        if self.screen_capture is None:
            raise RuntimeError("HUD detector 尚未連接畫面擷取服務")
        now = self._monotonic()
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
            image = self.screen_capture.grab(
                {
                    "left": search_area.left,
                    "top": search_area.top,
                    "width": search_area.width,
                    "height": search_area.height,
                }
            )
            hp_mask = (bar_color_mask or self.bar_color_mask)(image, "hp")
            mp_mask = (bar_color_mask or self.bar_color_mask)(image, "mp")
            exp_mask = (bar_color_mask or self.bar_color_mask)(image, "exp")
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
        if not {"hp", "mp"}.issubset(matches):
            return None
        hp_rect, hp_scale, hp_confidence = matches["hp"]
        mp_rect, mp_scale, mp_confidence = matches["mp"]
        exp_match = matches.get("exp")
        if abs(hp_scale - mp_scale) > HUD_LABEL_SCALE_TOLERANCE:
            return None
        if not self._bottom_hud_hp_mp_label_geometry_is_valid(hp_rect, mp_rect, search_area.width):
            return None
        exp_rect: tuple[int, int, int, int] | None = None
        exp_scale: float | None = None
        exp_confidence: float | None = None
        if exp_match is not None:
            candidate_exp_rect, candidate_exp_scale, candidate_exp_confidence = exp_match
            if (
                max(hp_scale, mp_scale, candidate_exp_scale) - min(hp_scale, mp_scale, candidate_exp_scale)
                <= HUD_LABEL_SCALE_TOLERANCE
                and self._bottom_hud_exp_label_geometry_is_valid(
                    hp_rect,
                    mp_rect,
                    candidate_exp_rect,
                    search_area.width,
                )
            ):
                exp_rect = candidate_exp_rect
                exp_scale = candidate_exp_scale
                exp_confidence = candidate_exp_confidence

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
        if hp_track is None or mp_track is None:
            inferred_hp_track, inferred_mp_track = self._hp_mp_tracks_from_label_geometry(
                image,
                hp_rect,
                mp_rect,
                search_area.reference_width,
                search_area.reference_height,
            )
            hp_track = hp_track or inferred_hp_track
            mp_track = mp_track or inferred_mp_track
        if hp_track is None or mp_track is None:
            return None

        hp_left, hp_top, hp_width, hp_height = hp_track
        mp_left, mp_top, mp_width, mp_height = mp_track
        if mp_left <= hp_left:
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

        exp_track: tuple[int, int, int, int] | None = None
        if exp_rect is not None:
            exp_track = self._bar_track_right_of_label(
                image,
                exp_mask,
                exp_rect,
                search_area.reference_width,
                search_area.reference_height,
                "exp",
            )
        if exp_track is None:
            exp_left = hp_left
            exp_height = max(8, min(max_hp_mp_height, max(hp_height, mp_height)))
            if exp_rect is None:
                label_height = max(hp_rect[3], mp_rect[3])
                exp_rect = (
                    hp_rect[0],
                    hp_rect[1] + round(label_height * 1.65),
                    max(hp_rect[2], round(label_height * 2.1)),
                    label_height,
                )
                exp_scale = (hp_scale + mp_scale) / 2.0
                exp_confidence = min(hp_confidence, mp_confidence)
            exp_top = exp_rect[1] + max(1, round((exp_rect[3] - exp_height) / 2))
            exp_top = max(0, min(search_area.height - exp_height, exp_top))
            exp_width = combined_right - exp_left
        else:
            exp_left, exp_top, exp_width, exp_height = exp_track
            if exp_left < hp_left - max(8, round(hp_rect[3] * 0.5)):
                return None
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
        confidence = min(hp_confidence, mp_confidence, exp_confidence if exp_confidence is not None else 1.0)
        scale = (
            (hp_scale + mp_scale + exp_scale) / 3.0
            if exp_scale is not None
            else (hp_scale + mp_scale) / 2.0
        )
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
        cache = self.template_cache
        cached = cache.get(key)
        if cached is not None:
            return cached
        canvas = self._hud_label_template_source(label)
        if abs(scale - 1.0) > 1e-9:
            width = max(1, round(canvas.shape[1] * scale))
            height = max(1, round(canvas.shape[0] * scale))
            canvas = cv2.resize(canvas, (width, height), interpolation=cv2.INTER_AREA)
        cache[key] = canvas
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

    def _bottom_hud_hp_mp_label_geometry_is_valid(
        self,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        search_width: int,
    ) -> bool:
        hp_cx = hp_rect[0] + hp_rect[2] / 2.0
        hp_cy = hp_rect[1] + hp_rect[3] / 2.0
        mp_cx = mp_rect[0] + mp_rect[2] / 2.0
        mp_cy = mp_rect[1] + mp_rect[3] / 2.0
        y_tolerance = max(hp_rect[3], mp_rect[3]) * HUD_LABEL_GEOMETRY_Y_TOLERANCE_RATIO
        if abs(hp_cy - mp_cy) > y_tolerance:
            return False
        if mp_cx <= hp_cx + max(hp_rect[2], round(search_width * 0.06)):
            return False
        return True

    def _bottom_hud_exp_label_geometry_is_valid(
        self,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        exp_rect: tuple[int, int, int, int],
        search_width: int,
    ) -> bool:
        hp_cx = hp_rect[0] + hp_rect[2] / 2.0
        hp_cy = hp_rect[1] + hp_rect[3] / 2.0
        exp_cx = exp_rect[0] + exp_rect[2] / 2.0
        exp_cy = exp_rect[1] + exp_rect[3] / 2.0
        if exp_cy <= hp_cy + max(4, hp_rect[3] * 0.35):
            return False
        if exp_cy - hp_cy > max(28, hp_rect[3] * 2.8):
            return False
        if abs(exp_cx - hp_cx) > max(hp_rect[2] * 1.4, round(search_width * 0.05)):
            return False
        return True

    def _hp_mp_tracks_from_label_geometry(
        self,
        image: np.ndarray,
        hp_rect: tuple[int, int, int, int],
        mp_rect: tuple[int, int, int, int],
        client_width: int,
        client_height: int,
    ) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
        hp_label_right = hp_rect[0] + hp_rect[2]
        mp_label_left = mp_rect[0]
        mp_label_right = mp_rect[0] + mp_rect[2]
        label_height = max(hp_rect[3], mp_rect[3])
        label_gap = max(4, round(label_height * 0.55))
        min_width = max(48, round(client_width * 0.07))
        max_width = max(min_width + 1, round(client_width * 0.20))

        hp_left = hp_label_right + label_gap
        hp_right_limit = mp_label_left - max(3, round(label_height * 0.15))
        hp_width = min(max_width, hp_right_limit - hp_left)
        if hp_width < min_width:
            return None, None

        mp_left = mp_label_right + label_gap
        mp_width = min(hp_width, max_width, image.shape[1] - mp_left)
        if mp_width < min_width:
            return None, None

        track_height = max(10, min(22, round(client_height * 0.015), label_height))
        label_top = round((hp_rect[1] + mp_rect[1]) / 2)
        track_top = label_top + max(0, round((label_height - track_height) / 2))
        track_top = max(0, min(image.shape[0] - track_height, track_top))
        return (
            (hp_left, track_top, hp_width, track_height),
            (mp_left, track_top, mp_width, track_height),
        )

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


    def create_direct_capture_context(self) -> DirectBarCaptureContext:
        return DirectBarCaptureContext(
            user32_provider=self._user32_provider,
            gdi32_provider=self._gdi32_provider,
        )

    def close(self) -> None:
        if self._closed:
            return
        self.direct_capture_context.close()
        self._closed = True


__all__ = [
    "DirectBarCaptureContext",
    "HudBarDetector",
    "HudDetectionRequest",
    "HudDetectionResult",
]
