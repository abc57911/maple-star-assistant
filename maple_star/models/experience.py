from __future__ import annotations

import contextlib
import hashlib
import io
import itertools
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from ..adapters.debug_logging import log_debug
from ..constants import EXPERIENCE_BURST_CONSENSUS_MIN_COUNT


EXP_SAMPLE_HISTORY_SECONDS = 3600.0
EXP_RATE_MIN_SECONDS = 5.0
EXP_RATE_5M_SECONDS = 300.0
EXP_RATE_10M_SECONDS = 600.0
EXP_RATE_1H_SECONDS = 3600.0
EXP_RATE_5M_HALF_LIFE_SECONDS = 45.0
EXP_RATE_10M_HALF_LIFE_SECONDS = 180.0
EXP_RATE_1H_HALF_LIFE_SECONDS = 600.0
EXP_RATE_5M_SMOOTHING_ALPHA = 0.65
EXP_RATE_10M_SMOOTHING_ALPHA = 0.45
EXP_RATE_1H_SMOOTHING_ALPHA = 0.25
EXP_RATE_FAST_CONVERGENCE_SAMPLE_COUNT = 8
EXP_RATE_FAST_CHANGE_RATIO = 0.20
EXP_RATE_FAST_SMOOTHING_ALPHA = 0.70
EXP_ETA_MIN_CONFIDENCE = 0.25
EXP_ETA_MIN_RATE_PER_SECOND = 1.0
EXP_ETA_MAX_SECONDS = 9999.0 * 3600.0
EXP_LEVEL_WRAP_HIGH_PERCENT = 65.0
EXP_LEVEL_WRAP_LOW_PERCENT = 35.0
EXP_OCR_MIN_SCORE = 0.70
EXP_OCR_ACCEPT_CONFIDENCE = 0.85
EXP_OCR_IMAGE_SCALE = 2
EXP_OCR_PREPARED_SCALE = 3
EXP_OCR_TARGET_HEIGHT = 72
EXP_OCR_MAX_SCALE = 5
EXP_OCR_CONTEXT_PADDING_RATIO = 0.40
EXP_OCR_CONTEXT_MIN_PADDING = 8
EXP_OCR_CONTEXT_MAX_PADDING = 18
EXP_OCR_TEXT_MIN_RATIO = 0.001
EXP_OCR_TEXT_MAX_RATIO = 0.35
EXP_OCR_TEXT_BINARY_MAX_RATIO = 0.90
EXP_OCR_TEXT_ROW_MIN_RATIO = 0.01
EXP_OCR_TEXT_COLUMN_MIN_RATIO = 0.03
EXP_OCR_TEXT_CROP_PADDING_RATIO = 0.18
EXP_OCR_DENSE_BORDER_ROW_MAX_RATIO = 0.72
EXP_OCR_DENSE_BORDER_ROW_PADDING = 1
EXP_OCR_TOP_BORDER_ROW_MAX_RATIO = 0.45
EXP_OCR_TOP_BORDER_MAX_HEIGHT_RATIO = 0.28
EXP_OCR_BINARY_LUMINANCE_MIN = 200.0
EXP_OCR_BINARY_MAX_CHROMA = 65.0
EXP_OCR_GREEN_BACKGROUND_MIN_GREEN = 120.0
EXP_OCR_GREEN_BACKGROUND_MIN_CHROMA = 35.0
EXP_OCR_GREEN_BACKGROUND_MIN_BAR_PERCENT = 20.0
EXP_OCR_GREEN_BACKGROUND_MAX_BAR_PERCENT = 97.5
EXP_OCR_GREEN_BACKGROUND_REPLACEMENT = 28
EXP_OCR_MIN_STRUCTURE_SCORE = 1.0
EXP_OCR_TRUSTED_NONBINARY_EXACT_CONFIDENCE = 0.95
EXP_OCR_REPAIRED_PERCENT_MAX_DISAGREEMENT = 0.35
EXP_OCR_REPAIRED_PERCENT_CONFIDENCE_TOLERANCE = 0.05
EXP_OCR_BAR_CROP_LEFT_RATIO = 0.44
EXP_OCR_BAR_GREEN_COLUMN_MIN_RATIO = 0.18
EXP_OCR_BAR_MIN_GREEN_SPAN_RATIO = 0.25
EXP_OCR_BAR_MIN_PARTIAL_GREEN_SPAN_RATIO = 0.025
EXP_OCR_BAR_LEFT_TOUCH_RATIO = 0.04
EXP_OCR_BAR_PERCENT_TOLERANCE = 12.0
EXP_PIXEL_FONT_RECOGNIZER_MIN_CONFIDENCE = 0.95
EXP_PIXEL_FONT_RECOGNIZER_BAR_PERCENT_TOLERANCE = 6.0
EXP_PIXEL_FONT_RECOGNIZER_MAX_ATTEMPTS = 18
EXP_PIXEL_FONT_TEMPLATE_SIZE = (48, 32)
EXP_PIXEL_FONT_PERCENT_ALTERNATIVE_SCORE_WINDOW = 0.30
EXP_PIXEL_FONT_PERCENT_MAX_ALTERNATIVES = 8
EXP_PIXEL_FONT_EXP_ALTERNATIVE_SCORE_WINDOW = 0.18
EXP_PIXEL_FONT_EXP_MAX_ALTERNATIVE_POSITIONS = 3
EXP_PIXEL_FONT_EXP_MAX_ALTERNATIVE_CANDIDATES = 24
EXP_PIXEL_FONT_FULL_BAR_PERCENT_MIN = 98.0
EXP_PIXEL_FONT_FULL_BAR_MIN_CONFIDENCE = 0.97
EXP_PIXEL_FONT_NO_BAR_LOW_PERCENT_MAX = 2.0
EXP_PIXEL_FONT_NO_BAR_LOW_PERCENT_MIN_CONFIDENCE = 0.84
EXP_PIXEL_FONT_ZERO_THREE_TOPOLOGY_MARGIN = 0.10
EXP_PIXEL_FONT_ZERO_THREE_TOPOLOGY_BONUS = 0.12
EXP_PIXEL_LEARNING_MAX_ATTEMPTS_SAVED = 8
EXP_PIXEL_LEARNING_MIN_TEXT_SEGMENTS = 4
EXP_TOTAL_ESTIMATE_MAX_DEVIATION_RATIO = 0.35
EXP_SINGLE_GAIN_MAX_LEVEL_RATIO = 0.35
EXP_OCR_CONTINUITY_MAX_PERCENT_GAIN_PER_SECOND = 10.0
EXP_OCR_CONTINUITY_MIN_JUMP_PERCENT = 2.0
EXP_OCR_CONTINUITY_LEVEL_UP_PREVIOUS_PERCENT_MIN = 95.0
EXP_OCR_CONTINUITY_LEVEL_UP_CANDIDATE_PERCENT_MAX = 5.0
EXP_GAIN_EXPECTED_TOLERANCE_RATIO = 3.0
EXP_GAIN_MIN_ABSOLUTE_TOLERANCE = 5000
EXP_INITIAL_REBASE_MAX_SAMPLES = 6
EXP_GAIN_RATE_SPIKE_MULTIPLIER = 20.0
EXP_PERCENT_REGRESSION_TOLERANCE = 0.03
EXP_PERCENT_DELTA_TOLERANCE_RATIO = 1.25
EXP_PERCENT_ROUNDING_TOLERANCE_RATIO = 0.0002
EXP_PERCENT_DELTA_MIN_ABSOLUTE_TOLERANCE = 1000
EXP_REBASE_CONFIRM_SECONDS = 20.0
EXP_REBASE_CONFIRM_MAX_PERCENT_DELTA = 0.30
EXP_REBASE_CONFIRM_MAX_LEVEL_RATIO = 0.03
EXP_REBASE_CONFIRM_MIN_ABSOLUTE_DELTA = 8000
EXP_REBASE_TRUSTED_CONFLICT_MIN_CONFIDENCE = 0.90
EXP_REBASE_CONFIRM_MAX_TOTAL_DEVIATION_RATIO = 0.005
EXP_INITIAL_BASELINE_CONFIRM_SECONDS = 20.0
EXP_INITIAL_BASELINE_CONFIRM_MAX_PERCENT_DELTA = 0.30
EXP_INITIAL_BASELINE_CONFIRM_MIN_ABSOLUTE_DELTA = 8000
EXP_INITIAL_BASELINE_CONFIRM_MAX_LEVEL_RATIO = 0.003
EXP_OUTLIER_REPAIR_MAX_REMOVED_SAMPLES = 3
EXP_OUTLIER_REPAIR_MAX_AGE_SECONDS = 60.0
EXP_OUTLIER_REPAIR_REASON_PREFIX = "離群修正候選"
EXP_RATE_MIN_ACCEPTED_SAMPLE_INTERVAL_SECONDS = 1.0
EXP_LONG_RATE_BLEND_START_SECONDS = 300.0
EXP_LONG_RATE_BLEND_FULL_SECONDS = 3600.0
PADDLEOCR_LANGUAGE = "chinese_cht"
PADDLEOCR_DETECTION_MODEL_NAME = "PP-OCRv5_mobile_det"
PADDLEOCR_RECOGNITION_MODEL_NAME = "PP-OCRv5_mobile_rec"
PADDLEOCR_ENV_DEFAULTS = {
    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
    "GLOG_minloglevel": "2",
    "FLAGS_minloglevel": "2",
    "FLAGS_cpu_math_library_num_threads": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
EXP_PIXEL_FONT_DIGIT_PROTOTYPES: dict[str, dict[str, float]] = {
    "0": {"top": 0.36, "mid": 0.26, "bot": 0.29, "ul": 0.35, "ur": 0.36, "ll": 0.35, "lr": 0.32, "area": 0.29},
    "1": {"top": 0.60, "mid": 0.32, "bot": 0.31, "ul": 0.17, "ur": 0.76, "ll": 0.00, "lr": 0.67, "area": 0.40},
    "2": {"top": 0.36, "mid": 0.08, "bot": 0.58, "ul": 0.18, "ur": 0.31, "ll": 0.30, "lr": 0.25, "area": 0.27},
    "3": {"top": 0.35, "mid": 0.16, "bot": 0.28, "ul": 0.14, "ur": 0.27, "ll": 0.08, "lr": 0.27, "area": 0.22},
    "4": {"top": 0.29, "mid": 0.26, "bot": 0.08, "ul": 0.07, "ur": 0.40, "ll": 0.27, "lr": 0.45, "area": 0.27},
    "5": {"top": 0.45, "mid": 0.28, "bot": 0.36, "ul": 0.35, "ur": 0.11, "ll": 0.23, "lr": 0.30, "area": 0.27},
    "6": {"top": 0.38, "mid": 0.34, "bot": 0.32, "ul": 0.34, "ur": 0.22, "ll": 0.34, "lr": 0.26, "area": 0.29},
    "7": {"top": 0.58, "mid": 0.07, "bot": 0.10, "ul": 0.22, "ur": 0.46, "ll": 0.00, "lr": 0.08, "area": 0.19},
    "8": {"top": 0.43, "mid": 0.35, "bot": 0.31, "ul": 0.39, "ur": 0.37, "ll": 0.36, "lr": 0.34, "area": 0.35},
    "9": {"top": 0.41, "mid": 0.46, "bot": 0.32, "ul": 0.37, "ur": 0.42, "ll": 0.21, "lr": 0.38, "area": 0.34},
}
EXP_PIXEL_FONT_FEATURE_WEIGHTS: dict[str, float] = {
    "top": 1.1,
    "mid": 1.0,
    "bot": 1.1,
    "ul": 0.9,
    "ur": 0.9,
    "ll": 0.9,
    "lr": 0.9,
    "area": 0.6,
}
_EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE: dict[str, list[np.ndarray]] | None = None


@dataclass
class ExperienceTextReading:
    current_exp: int | None = None
    percent: float | None = None
    text: str = ""
    confidence: float = 0.0
    success: bool = False
    reason: str = "尚未辨識"
    needs_bar_percent_guard: bool = False
    learning_case_id: str = ""
    bar_percent: float | None = None
    continuity_status: str = "unknown"
    source: str = ""


@dataclass(frozen=True)
class ExperienceOcrImage:
    image: np.ndarray
    bar_crop_left_ratio: float = EXP_OCR_BAR_CROP_LEFT_RATIO
    source_id: str = ""
    roi_offset: tuple[int, int, int, int] = (0, 0, 0, 0)
    preprocess_variant: str = "capture"
    attempt_id: str = ""


@dataclass(frozen=True)
class ExperienceOcrContinuityHint:
    current_exp: int
    percent: float | None
    captured_at: float
    now: float


@dataclass(frozen=True)
class ExperiencePixelFontAttempt:
    image: np.ndarray
    bar_crop_left_ratio: float
    source_id: str
    roi_offset: tuple[int, int, int, int]
    preprocess_variant: str
    attempt_id: str


@dataclass(frozen=True)
class ExperienceTextCandidate:
    current_exp: int
    percent: float
    percent_span: tuple[int, int]
    structure_score: float
    repaired_percent: bool = False
    needs_bar_percent_guard: bool = False


@dataclass
class ExperienceSample:
    captured_at: float
    current_exp: int
    total_gained_exp: int
    percent: float | None
    confidence: float | None = None


@dataclass(frozen=True)
class RateEstimate:
    rate_per_second: float
    sample_count: int
    elapsed_seconds: float
    confidence: float


@dataclass
class PendingExperienceRebase:
    captured_at: float
    current_exp: int
    percent: float | None
    reason: str
    confidence: float | None = None


@dataclass
class PendingExperienceBaseline:
    captured_at: float
    current_exp: int
    percent: float | None
    confidence: float | None = None


@dataclass
class ExperienceSnapshot:
    current_exp: int | None = None
    current_percent: float | None = None
    xp_per_5m: float | None = None
    xp_per_10m: float | None = None
    xp_per_hour: float | None = None
    eta_seconds: float | None = None
    elapsed_seconds: float | None = None
    sample_count: int = 0
    sample_attempt_count: int = 0
    sample_accept_count: int = 0
    sample_accept_rate: float | None = None
    rate_confidence: float | None = None
    ocr_attempt_count: int = 0
    ocr_success_count: int = 0
    ocr_success_rate: float | None = None
    status: str = "尚未開始"


def format_exp(value: float | int | None) -> str:
    if value is None:
        return "--"
    return f"{round(value):,}"


def format_exp_rate(value: float | int | None) -> str:
    if value is None:
        return "--"
    whole = max(0, int(value))
    if whole < 10000:
        return f"{whole:,}"
    ten_thousands, remainder = divmod(whole, 10000)
    thousands = remainder // 1000
    if thousands:
        return f"{ten_thousands:,}萬{thousands}"
    return f"{ten_thousands:,}萬"


def format_ocr_success_rate(success_count: int, attempt_count: int) -> str:
    if attempt_count <= 0:
        return "--"
    success_count = max(0, min(success_count, attempt_count))
    rate = success_count / attempt_count * 100.0
    if abs(rate - round(rate)) < 0.05:
        rate_text = f"{rate:.0f}%"
    else:
        rate_text = f"{rate:.1f}%"
    return f"{rate_text} ({success_count}/{attempt_count})"


def format_rate_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "--"
    confidence = max(0.0, min(1.0, confidence))
    if confidence >= 0.75:
        return "高"
    if confidence >= 0.40:
        return "中"
    return "低"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or not math.isfinite(seconds) or seconds > EXP_ETA_MAX_SECONDS:
        return "--"
    return format_duration(seconds)


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or not math.isfinite(seconds):
        return "--"
    total_seconds = round(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"00:{minutes:02d}:{secs:02d}"


class ExperienceEfficiencyTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.samples: list[ExperienceSample] = []
        self.last_current_exp: int | None = None
        self.total_gained_exp = 0
        self.estimated_level_total_exp: float | None = None
        self.last_snapshot: ExperienceSnapshot | None = None
        self.last_rate_sample_at: float | None = None
        self.pending_initial_baseline: PendingExperienceBaseline | None = None
        self.started_at: float | None = None
        self.pending_rebase: PendingExperienceRebase | None = None
        self.ocr_attempt_count = 0
        self.ocr_success_count = 0
        self.sample_attempt_count = 0
        self.sample_accept_count = 0
        self.last_status = "等待 EXP 數字"

    def clear_transient_rejection(self) -> None:
        self.pending_rebase = None
        if not self.last_status.startswith("樣本拒絕"):
            return
        self.last_status = "等待下一次 EXP 樣本" if self.samples else "等待 EXP 數字"

    def record_ocr_result(self, success: bool) -> None:
        self.ocr_attempt_count += 1
        if success:
            self.ocr_success_count += 1

    def add_reading(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
        *,
        confidence: float | None = None,
        require_initial_confirmation: bool = False,
    ) -> bool:
        self.sample_attempt_count += 1
        accepted = self._add_reading(
            now,
            current_exp,
            percent,
            confidence=confidence,
            require_initial_confirmation=require_initial_confirmation,
        )
        if accepted:
            self.sample_accept_count += 1
        return accepted

    def _add_reading(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
        *,
        confidence: float | None = None,
        require_initial_confirmation: bool = False,
    ) -> bool:
        confidence = self._normalized_confidence(confidence)
        if current_exp < 0:
            self._reject_sample("EXP 數字無效")
            return False
        if percent is not None and not 0.0 <= percent <= 100.0:
            self._reject_sample(f"EXP 百分比無效：{percent:.2f}%")
            return False

        if self.last_current_exp is None:
            if require_initial_confirmation and not self._confirm_initial_baseline(now, current_exp, percent, confidence):
                return False
            self.last_current_exp = current_exp
            self.started_at = now
            self.pending_initial_baseline = None
            self.samples.append(ExperienceSample(now, current_exp, self.total_gained_exp, percent, confidence))
            self._update_level_total_estimate(current_exp, percent, force=True)
            self.last_status = "校準 EXP 基準"
            return True

        if self.pending_rebase is not None:
            if self._pending_rebase_matches(now, current_exp, percent):
                pending = self.pending_rebase
                self.pending_rebase = None
                if self._pending_rebase_level_total_deviation(pending, current_exp, percent) is not None:
                    self._reject_sample("基準修正拒絕：總經驗估算不一致")
                    return False
                if self._is_pending_outlier_repair(pending):
                    if self._repair_recent_outlier_history(now, current_exp, percent):
                        return self._add_reading(now, current_exp, percent, confidence=confidence)
                    self._reject_sample("離群修正失敗：候選不再符合")
                    return False
                self._restart_session(
                    pending.captured_at,
                    pending.current_exp,
                    pending.percent,
                    pending.confidence,
                    "基準修正：可疑樣本已二次確認",
                )
                return self._add_reading(now, current_exp, percent, confidence=confidence)
            if self._pending_rebase_expired_or_conflicts(now, current_exp, percent):
                self.pending_rebase = None

        delta = current_exp - self.last_current_exp
        if delta < 0:
            wrapped_delta = self._level_wrap_delta(current_exp, percent)
            if wrapped_delta is None:
                if self._can_rebase_initial_session():
                    self._queue_pending_rebase(
                        now,
                        current_exp,
                        percent,
                        confidence,
                        "基準修正候選：EXP 回落但需二次確認",
                    )
                    return False
                if self._recent_outlier_repair_anchor_index(now, current_exp, percent) is not None:
                    self._queue_pending_rebase(
                        now,
                        current_exp,
                        percent,
                        confidence,
                        f"{EXP_OUTLIER_REPAIR_REASON_PREFIX}：可疑錯值需二次確認",
                    )
                    return False
                self._reject_sample("EXP 數字回落但不符合升級條件")
                return False
            delta = wrapped_delta
        else:
            corrected_exp = self._correct_green_bar_three_as_eight_ocr(current_exp, percent)
            if corrected_exp is not None:
                current_exp = corrected_exp
                delta = current_exp - self.last_current_exp
            rejection_reason = self._normal_gain_rejection_reason(now, current_exp, percent, delta)
            if rejection_reason is not None:
                if self._should_queue_confirmed_rebase_for_rejection(
                    current_exp,
                    percent,
                    confidence,
                    rejection_reason,
                ):
                    self._queue_pending_rebase(
                        now,
                        current_exp,
                        percent,
                        confidence,
                        f"基準修正候選：{rejection_reason}",
                    )
                    return False
                self._reject_sample(rejection_reason)
                return False

        self.pending_rebase = None
        self.total_gained_exp += max(0, delta)
        self.last_current_exp = current_exp
        self.samples.append(ExperienceSample(now, current_exp, self.total_gained_exp, percent, confidence))
        self._update_level_total_estimate(current_exp, percent)
        self._trim_samples(now)
        self.last_status = "統計中"
        return True

    def snapshot(self, now: float) -> ExperienceSnapshot:
        if self.last_status.startswith("樣本拒絕") and self.last_snapshot is not None:
            return self._snapshot_from_last(now, status=self.last_status)
        if not self.samples:
            return self._snapshot_from_last(now, status=self.last_status)
        if self._has_only_baseline_sample():
            latest = self.samples[-1]
            snapshot = ExperienceSnapshot(
                current_exp=latest.current_exp,
                current_percent=latest.percent,
                elapsed_seconds=self._elapsed_seconds(now),
                sample_count=len(self.samples),
                **self._quality_snapshot_fields(),
                status=self.last_status,
            )
            self.last_snapshot = snapshot
            return snapshot

        latest = self.samples[-1]
        rate_samples = self._samples_with_current_time(now)
        rate_latest = rate_samples[-1]
        stale_seconds = max(0.0, rate_latest.captured_at - latest.captured_at)
        update_smoothed_rates = self.last_rate_sample_at != rate_latest.captured_at
        suppress_rate_update = (
            update_smoothed_rates
            and rate_latest.captured_at == latest.captured_at
            and self._latest_real_sample_interval_seconds() is not None
            and (self._latest_real_sample_interval_seconds() or 0.0) < EXP_RATE_MIN_ACCEPTED_SAMPLE_INTERVAL_SECONDS
        )
        five_minute_estimate = self._weighted_rate_estimate(
            EXP_RATE_5M_SECONDS,
            EXP_RATE_5M_HALF_LIFE_SECONDS,
            rate_samples,
            add_stale_anchor=rate_latest.captured_at > latest.captured_at,
        )
        ten_minute_estimate = self._weighted_rate_estimate(
            EXP_RATE_10M_SECONDS,
            EXP_RATE_10M_HALF_LIFE_SECONDS,
            rate_samples,
            add_stale_anchor=rate_latest.captured_at > latest.captured_at,
        )
        long_estimate = self._weighted_rate_estimate(
            EXP_RATE_1H_SECONDS,
            EXP_RATE_1H_HALF_LIFE_SECONDS,
            rate_samples,
            add_stale_anchor=rate_latest.captured_at > latest.captured_at,
        )
        if suppress_rate_update:
            five_minute_estimate = None
            ten_minute_estimate = None
            long_estimate = None
        five_minute_rate = self._rate_per_second(five_minute_estimate)
        ten_minute_rate = self._rate_per_second(ten_minute_estimate)
        long_rate = self._rate_per_second(long_estimate)
        xp_per_5m = self._smoothed_rate_or_previous(
            five_minute_rate,
            EXP_RATE_5M_SECONDS,
            "xp_per_5m",
            EXP_RATE_5M_SMOOTHING_ALPHA,
            update_smoothed_rates,
            len(self.samples),
            stale_seconds,
        )
        xp_per_10m = self._smoothed_rate_or_previous(
            ten_minute_rate,
            EXP_RATE_10M_SECONDS,
            "xp_per_10m",
            EXP_RATE_10M_SMOOTHING_ALPHA,
            update_smoothed_rates,
            len(self.samples),
            stale_seconds,
        )
        xp_per_hour = self._smoothed_rate_or_previous(
            long_rate,
            EXP_RATE_1H_SECONDS,
            "xp_per_hour",
            EXP_RATE_1H_SMOOTHING_ALPHA,
            update_smoothed_rates,
            len(self.samples),
            stale_seconds,
        )
        preferred_rate = self._preferred_eta_rate_per_second(
            self._window_rate_per_second(xp_per_5m, EXP_RATE_5M_SECONDS),
            self._window_rate_per_second(xp_per_10m, EXP_RATE_10M_SECONDS),
            self._window_rate_per_second(xp_per_hour, EXP_RATE_1H_SECONDS),
            rate_samples,
        )
        eta_rate = preferred_rate
        rate_confidence = self._preferred_eta_confidence(
            five_minute_estimate,
            ten_minute_estimate,
            long_estimate,
            rate_samples,
        )
        eta_seconds = self._eta_seconds(rate_latest, eta_rate)
        if (
            self.last_snapshot is not None
            and rate_confidence is not None
            and rate_confidence < EXP_ETA_MIN_CONFIDENCE
        ):
            eta_seconds = self.last_snapshot.eta_seconds
        snapshot = ExperienceSnapshot(
            current_exp=latest.current_exp,
            current_percent=latest.percent,
            xp_per_5m=xp_per_5m,
            xp_per_10m=xp_per_10m,
            xp_per_hour=xp_per_hour,
            eta_seconds=eta_seconds,
            elapsed_seconds=self._elapsed_seconds(now),
            sample_count=len(self.samples),
            rate_confidence=rate_confidence,
            **self._quality_snapshot_fields(),
            status=self.last_status,
        )
        if snapshot.eta_seconds is None and preferred_rate is None and self.last_snapshot is not None:
            snapshot.eta_seconds = self.last_snapshot.eta_seconds
        self.last_snapshot = snapshot
        self.last_rate_sample_at = rate_latest.captured_at
        return snapshot

    def _restart_session(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
        confidence: float | None,
        status: str,
    ) -> None:
        self.samples = [ExperienceSample(now, current_exp, 0, percent, self._normalized_confidence(confidence))]
        self.last_current_exp = current_exp
        self.total_gained_exp = 0
        self.estimated_level_total_exp = None
        self.last_rate_sample_at = None
        self.started_at = now
        self.pending_initial_baseline = None
        self.pending_rebase = None
        self._update_level_total_estimate(current_exp, percent, force=True)
        self.last_status = status

    def _has_only_baseline_sample(self) -> bool:
        return len(self.samples) == 1 and self.total_gained_exp == 0

    def _elapsed_seconds(self, now: float) -> float | None:
        if self.started_at is None:
            return None
        return max(0.0, now - self.started_at)

    def _can_rebase_initial_session(self) -> bool:
        return (
            0 < len(self.samples) <= EXP_INITIAL_REBASE_MAX_SAMPLES
            and self.total_gained_exp <= EXP_GAIN_MIN_ABSOLUTE_TOLERANCE
        )

    def _reject_sample(self, reason: str) -> None:
        self.last_status = f"樣本拒絕：{reason}"

    def _queue_pending_rebase(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
        confidence: float | None,
        reason: str,
    ) -> None:
        self.pending_rebase = PendingExperienceRebase(now, current_exp, percent, reason, confidence)
        self._reject_sample(reason)

    def _confirm_initial_baseline(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
        confidence: float | None,
    ) -> bool:
        pending = self.pending_initial_baseline
        if pending is not None and self._pending_initial_baseline_matches(pending, now, current_exp, percent):
            return True
        self.pending_initial_baseline = PendingExperienceBaseline(now, current_exp, percent, confidence)
        self.last_status = "等待基準二次確認"
        return False

    def _pending_initial_baseline_matches(
        self,
        pending: PendingExperienceBaseline,
        now: float,
        current_exp: int,
        percent: float | None,
    ) -> bool:
        if now - pending.captured_at > EXP_INITIAL_BASELINE_CONFIRM_SECONDS:
            return False
        if pending.percent is not None and percent is not None:
            if percent < pending.percent - EXP_PERCENT_REGRESSION_TOLERANCE:
                return False
            if abs(percent - pending.percent) > EXP_INITIAL_BASELINE_CONFIRM_MAX_PERCENT_DELTA:
                return False
        elif pending.percent != percent:
            return False

        delta = current_exp - pending.current_exp
        if delta < 0:
            return False
        tolerance = self._pending_initial_baseline_exp_tolerance(pending, percent)
        if pending.percent is not None and percent is not None and percent >= pending.percent:
            estimate = self._level_total_estimate(pending.current_exp, pending.percent)
            current_estimate = self._level_total_estimate(current_exp, percent)
            estimates = [value for value in (estimate, current_estimate) if value is not None]
            if estimates:
                expected_delta = max(estimates) * ((percent - pending.percent) / 100.0)
                tolerance = max(tolerance, abs(expected_delta) * EXP_PERCENT_DELTA_TOLERANCE_RATIO)
        return delta <= tolerance

    def _pending_initial_baseline_exp_tolerance(
        self,
        pending: PendingExperienceBaseline,
        percent: float | None,
    ) -> float:
        estimates = [
            value
            for value in (
                self._level_total_estimate(pending.current_exp, pending.percent),
                self._level_total_estimate(pending.current_exp, percent),
            )
            if value is not None
        ]
        if estimates:
            return max(
                float(EXP_INITIAL_BASELINE_CONFIRM_MIN_ABSOLUTE_DELTA),
                max(estimates) * EXP_INITIAL_BASELINE_CONFIRM_MAX_LEVEL_RATIO,
            )
        return max(float(EXP_INITIAL_BASELINE_CONFIRM_MIN_ABSOLUTE_DELTA), pending.current_exp * 0.003)

    def _should_queue_confirmed_rebase_for_rejection(
        self,
        current_exp: int,
        percent: float | None,
        confidence: float | None,
        reason: str,
    ) -> bool:
        return False

    def level_total_deviation_ratio(self, current_exp: int | None, percent: float | None) -> float | None:
        if current_exp is None:
            return None
        estimate = self._level_total_estimate(current_exp, percent)
        if estimate is None or self.estimated_level_total_exp is None or self.estimated_level_total_exp <= 0:
            return None
        return abs(estimate - self.estimated_level_total_exp) / self.estimated_level_total_exp

    def _normalized_confidence(self, confidence: float | None) -> float | None:
        if confidence is None:
            return None
        return max(0.0, min(1.0, float(confidence)))

    def _is_pending_outlier_repair(self, pending: PendingExperienceRebase) -> bool:
        return pending.reason.startswith(EXP_OUTLIER_REPAIR_REASON_PREFIX)

    def _recent_outlier_repair_anchor_index(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
    ) -> int | None:
        if len(self.samples) < 2:
            return None
        max_removed = min(EXP_OUTLIER_REPAIR_MAX_REMOVED_SAMPLES, len(self.samples) - 1)
        for removed_count in range(1, max_removed + 1):
            anchor_index = len(self.samples) - removed_count - 1
            anchor = self.samples[anchor_index]
            first_removed = self.samples[anchor_index + 1]
            if now - first_removed.captured_at > EXP_OUTLIER_REPAIR_MAX_AGE_SECONDS:
                continue
            if self._reading_matches_repair_anchor(anchor, now, current_exp, percent):
                return anchor_index
        return None

    def _reading_matches_repair_anchor(
        self,
        anchor: ExperienceSample,
        now: float,
        current_exp: int,
        percent: float | None,
    ) -> bool:
        delta = current_exp - anchor.current_exp
        if delta < 0:
            return False

        anchor_estimate = self._level_total_estimate(anchor.current_exp, anchor.percent)
        current_estimate = self._level_total_estimate(current_exp, percent)
        if anchor_estimate is not None and current_estimate is not None:
            deviation = abs(current_estimate - anchor_estimate) / anchor_estimate
            if deviation > EXP_TOTAL_ESTIMATE_MAX_DEVIATION_RATIO:
                return False

        estimate = anchor_estimate or current_estimate or self.estimated_level_total_exp
        if anchor.percent is not None and percent is not None:
            percent_delta = percent - anchor.percent
            if percent_delta < -EXP_PERCENT_REGRESSION_TOLERANCE:
                return False
            if estimate is not None and estimate > 0:
                expected_delta = estimate * (percent_delta / 100.0)
                tolerance = max(
                    float(EXP_PERCENT_DELTA_MIN_ABSOLUTE_TOLERANCE),
                    estimate * EXP_PERCENT_ROUNDING_TOLERANCE_RATIO,
                    abs(expected_delta) * EXP_PERCENT_DELTA_TOLERANCE_RATIO,
                )
                if delta > expected_delta + tolerance:
                    return False
                if expected_delta > tolerance and delta + tolerance < expected_delta:
                    return False
                return True

        elapsed = max(0.0, now - anchor.captured_at)
        max_delta = float(EXP_GAIN_MIN_ABSOLUTE_TOLERANCE)
        if estimate is not None and estimate > 0:
            max_delta = max(max_delta, estimate * 0.03)
        session_rate = self._session_rate_per_second()
        if session_rate is not None and elapsed > 0:
            max_delta = max(max_delta, session_rate * elapsed * EXP_GAIN_RATE_SPIKE_MULTIPLIER)
        return delta <= max_delta

    def _repair_recent_outlier_history(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
    ) -> bool:
        anchor_index = self._recent_outlier_repair_anchor_index(now, current_exp, percent)
        if anchor_index is None:
            return False
        self.samples = self.samples[: anchor_index + 1]
        latest = self.samples[-1]
        self.last_current_exp = latest.current_exp
        self.total_gained_exp = latest.total_gained_exp
        self.estimated_level_total_exp = None
        for index, sample in enumerate(self.samples):
            self._update_level_total_estimate(sample.current_exp, sample.percent, force=index == 0)
        self.last_snapshot = None
        self.last_rate_sample_at = None
        self.last_status = "離群修正：已移除短暫錯值"
        return True

    def _pending_rebase_matches(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
    ) -> bool:
        pending = self.pending_rebase
        if pending is None:
            return False
        if now - pending.captured_at > EXP_REBASE_CONFIRM_SECONDS:
            return False
        if pending.percent is not None and percent is not None:
            if abs(percent - pending.percent) > EXP_REBASE_CONFIRM_MAX_PERCENT_DELTA:
                return False
        elif pending.percent != percent:
            return False

        tolerance = self._pending_rebase_exp_tolerance(pending, percent)
        delta = current_exp - pending.current_exp
        return -tolerance <= delta <= tolerance

    def _pending_rebase_level_total_deviation(
        self,
        pending: PendingExperienceRebase,
        current_exp: int,
        percent: float | None,
    ) -> float | None:
        if self._is_pending_outlier_repair(pending) or self._can_rebase_initial_session():
            return None
        deviation = self.level_total_deviation_ratio(current_exp, percent)
        if deviation is None or deviation <= EXP_REBASE_CONFIRM_MAX_TOTAL_DEVIATION_RATIO:
            return None
        return deviation

    def _pending_rebase_expired_or_conflicts(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
    ) -> bool:
        pending = self.pending_rebase
        if pending is None:
            return False
        if now - pending.captured_at > EXP_REBASE_CONFIRM_SECONDS:
            return True
        if pending.percent is not None and percent is not None:
            if abs(percent - pending.percent) > EXP_REBASE_CONFIRM_MAX_PERCENT_DELTA:
                return True
        elif pending.percent != percent:
            return True

        tolerance = self._pending_rebase_exp_tolerance(pending, percent)
        return abs(current_exp - pending.current_exp) > tolerance

    def _pending_rebase_exp_tolerance(
        self,
        pending: PendingExperienceRebase,
        percent: float | None,
    ) -> float:
        estimates = [
            value
            for value in (
                self._level_total_estimate(pending.current_exp, pending.percent),
                self._level_total_estimate(pending.current_exp, percent),
                self.estimated_level_total_exp,
            )
            if value is not None
        ]
        if estimates:
            return max(
                float(EXP_REBASE_CONFIRM_MIN_ABSOLUTE_DELTA),
                max(estimates) * EXP_REBASE_CONFIRM_MAX_LEVEL_RATIO,
            )
        return max(float(EXP_REBASE_CONFIRM_MIN_ABSOLUTE_DELTA), pending.current_exp * 0.03)

    def _snapshot_from_last(self, now: float, status: str) -> ExperienceSnapshot:
        if self.last_snapshot is None:
            return ExperienceSnapshot(
                elapsed_seconds=self._elapsed_seconds(now),
                status=status,
                **self._quality_snapshot_fields(),
            )
        return ExperienceSnapshot(
            current_exp=self.last_snapshot.current_exp,
            current_percent=self.last_snapshot.current_percent,
            xp_per_5m=self.last_snapshot.xp_per_5m,
            xp_per_10m=self.last_snapshot.xp_per_10m,
            xp_per_hour=self.last_snapshot.xp_per_hour,
            eta_seconds=self.last_snapshot.eta_seconds,
            elapsed_seconds=self._elapsed_seconds(now),
            sample_count=self.last_snapshot.sample_count,
            rate_confidence=self.last_snapshot.rate_confidence,
            **self._quality_snapshot_fields(),
            status=status,
        )

    def _quality_snapshot_fields(self) -> dict[str, int | float | None]:
        ocr_rate = None
        if self.ocr_attempt_count > 0:
            ocr_rate = self.ocr_success_count / self.ocr_attempt_count
        sample_rate = None
        if self.sample_attempt_count > 0:
            sample_rate = self.sample_accept_count / self.sample_attempt_count
        return {
            "ocr_attempt_count": self.ocr_attempt_count,
            "ocr_success_count": self.ocr_success_count,
            "ocr_success_rate": ocr_rate,
            "sample_attempt_count": self.sample_attempt_count,
            "sample_accept_count": self.sample_accept_count,
            "sample_accept_rate": sample_rate,
        }

    def _trim_samples(self, now: float) -> None:
        cutoff = now - EXP_SAMPLE_HISTORY_SECONDS
        while len(self.samples) > 1 and self.samples[0].captured_at < cutoff:
            self.samples.pop(0)

    def _update_level_total_estimate(self, current_exp: int, percent: float | None, force: bool = False) -> None:
        estimate = self._level_total_estimate(current_exp, percent)
        if estimate is None:
            return
        if self.estimated_level_total_exp is None or force:
            self.estimated_level_total_exp = estimate
        else:
            self.estimated_level_total_exp = self.estimated_level_total_exp * 0.85 + estimate * 0.15

    def _level_total_estimate(self, current_exp: int, percent: float | None) -> float | None:
        if percent is None or percent <= 0.01 or percent >= 99.99:
            return None
        estimate = current_exp / (percent / 100.0)
        if estimate <= current_exp:
            return None
        return estimate

    def _normal_gain_rejection_reason(
        self,
        now: float,
        current_exp: int,
        percent: float | None,
        delta: int,
    ) -> str | None:
        if delta > 0:
            percent_delta_reason = self._percent_delta_rejection_reason(percent, delta)
            if percent_delta_reason is not None:
                return percent_delta_reason

        estimate = self._level_total_estimate(current_exp, percent)
        if (
            estimate is not None
            and self.estimated_level_total_exp is not None
            and self.estimated_level_total_exp > 0
        ):
            deviation = abs(estimate - self.estimated_level_total_exp) / self.estimated_level_total_exp
            if deviation > EXP_TOTAL_ESTIMATE_MAX_DEVIATION_RATIO:
                return f"總經驗估算偏離過大：{deviation:.0%}"

        if delta <= 0:
            return None

        latest = self.samples[-1] if self.samples else None
        elapsed = 0.0 if latest is None else max(0.0, now - latest.captured_at)
        max_delta = self._max_reasonable_delta(elapsed, percent)
        if delta > max_delta:
            return f"EXP 跳動過大：+{delta:,}"
        return None

    def _correct_green_bar_three_as_eight_ocr(self, current_exp: int, percent: float | None) -> int | None:
        latest = self.samples[-1] if self.samples else None
        if (
            latest is None
            or self.last_current_exp is None
            or latest.percent is None
            or percent is None
            or self.estimated_level_total_exp is None
            or self.estimated_level_total_exp <= 0
            or current_exp <= self.last_current_exp
        ):
            return None

        original_delta = current_exp - self.last_current_exp
        original_rejection = self._percent_delta_rejection_reason(percent, original_delta)
        if original_rejection is None or not original_rejection.startswith("EXP 跳動與百分比不一致"):
            return None

        exp_digits = str(current_exp)
        candidates: list[tuple[float, int]] = []
        for index, char in enumerate(exp_digits):
            if char != "8":
                continue
            repaired_exp = int(f"{exp_digits[:index]}3{exp_digits[index + 1:]}")
            if repaired_exp < self.last_current_exp:
                continue
            repaired_delta = repaired_exp - self.last_current_exp
            if self._percent_delta_rejection_reason(percent, repaired_delta) is not None:
                continue
            percent_delta = max(0.0, percent - latest.percent)
            if percent_delta <= EXP_PERCENT_REGRESSION_TOLERANCE or repaired_delta <= 0:
                continue
            expected_delta = self.estimated_level_total_exp * (percent_delta / 100.0)
            candidates.append((abs(repaired_delta - expected_delta), repaired_exp))
        if not candidates:
            return None
        return min(candidates)[1]

    def _percent_delta_rejection_reason(self, percent: float | None, delta: int) -> str | None:
        latest = self.samples[-1] if self.samples else None
        if (
            latest is None
            or latest.percent is None
            or percent is None
            or self.estimated_level_total_exp is None
            or self.estimated_level_total_exp <= 0
        ):
            return None

        percent_delta = percent - latest.percent
        if percent_delta < -EXP_PERCENT_REGRESSION_TOLERANCE:
            return f"EXP 百分比回落但數字增加：{latest.percent:.2f}% -> {percent:.2f}%"
        if percent_delta < 0:
            return None

        expected_delta = self.estimated_level_total_exp * (percent_delta / 100.0)
        tolerance = max(
            float(EXP_PERCENT_DELTA_MIN_ABSOLUTE_TOLERANCE),
            self.estimated_level_total_exp * EXP_PERCENT_ROUNDING_TOLERANCE_RATIO,
            abs(expected_delta) * EXP_PERCENT_DELTA_TOLERANCE_RATIO,
        )
        if delta > expected_delta + tolerance:
            return f"EXP 跳動與百分比不一致：+{delta:,} / 預期約 +{round(expected_delta):,}"
        if expected_delta > tolerance and delta + tolerance < expected_delta:
            return f"EXP 增量低於百分比變化：+{delta:,} / 預期約 +{round(expected_delta):,}"
        return None

    def _max_reasonable_delta(self, elapsed: float, percent: float | None) -> float:
        latest = self.samples[-1] if self.samples else None
        if (
            latest is not None
            and latest.percent is not None
            and percent is not None
            and percent >= latest.percent
            and self.estimated_level_total_exp is not None
        ):
            expected_delta = self.estimated_level_total_exp * ((percent - latest.percent) / 100.0)
            return max(float(EXP_GAIN_MIN_ABSOLUTE_TOLERANCE), expected_delta * EXP_GAIN_EXPECTED_TOLERANCE_RATIO)

        tolerance = float(EXP_GAIN_MIN_ABSOLUTE_TOLERANCE)
        if self.estimated_level_total_exp is not None:
            tolerance = max(tolerance, self.estimated_level_total_exp * EXP_SINGLE_GAIN_MAX_LEVEL_RATIO)

        session_rate = self._session_rate_per_second()
        if session_rate is not None and elapsed > 0:
            tolerance = max(tolerance, session_rate * elapsed * EXP_GAIN_RATE_SPIKE_MULTIPLIER)
        return tolerance

    def _level_wrap_delta(self, current_exp: int, percent: float | None) -> int | None:
        if self.last_current_exp is None or self.estimated_level_total_exp is None:
            return None
        previous_percent = self.samples[-1].percent if self.samples else None
        if previous_percent is not None and previous_percent < EXP_LEVEL_WRAP_HIGH_PERCENT:
            return None
        if percent is not None and percent > EXP_LEVEL_WRAP_LOW_PERCENT:
            return None
        remaining_previous_level = max(0, round(self.estimated_level_total_exp - self.last_current_exp))
        return remaining_previous_level + current_exp

    def _weighted_rate_per_second(
        self,
        window_seconds: float,
        half_life_seconds: float,
        samples: list[ExperienceSample] | None = None,
        *,
        add_stale_anchor: bool = False,
    ) -> float | None:
        estimate = self._weighted_rate_estimate(
            window_seconds,
            half_life_seconds,
            samples,
            add_stale_anchor=add_stale_anchor,
        )
        return self._rate_per_second(estimate)

    def _weighted_rate_estimate(
        self,
        window_seconds: float,
        half_life_seconds: float,
        samples: list[ExperienceSample] | None = None,
        *,
        add_stale_anchor: bool = False,
    ) -> RateEstimate | None:
        samples = self._window_samples(window_seconds, samples, add_stale_anchor=add_stale_anchor)
        if len(samples) < 2:
            return None

        latest = samples[-1]
        elapsed = latest.captured_at - samples[0].captured_at
        if elapsed < EXP_RATE_MIN_SECONDS:
            return None

        weight_sum = 0.0
        weighted_time_sum = 0.0
        weighted_exp_sum = 0.0
        weighted_samples: list[tuple[float, float, float]] = []
        reading_confidence_sum = 0.0
        for sample in samples:
            age = max(0.0, latest.captured_at - sample.captured_at)
            time_weight = 0.5 ** (age / half_life_seconds) if half_life_seconds > 0 else 1.0
            reading_confidence = sample.confidence if sample.confidence is not None else 1.0
            weight = time_weight * max(0.20, reading_confidence)
            time_offset = sample.captured_at - latest.captured_at
            exp_value = float(sample.total_gained_exp)
            weighted_samples.append((weight, time_offset, exp_value))
            weight_sum += weight
            weighted_time_sum += weight * time_offset
            weighted_exp_sum += weight * exp_value
            reading_confidence_sum += reading_confidence

        if weight_sum <= 0:
            return None

        mean_time = weighted_time_sum / weight_sum
        mean_exp = weighted_exp_sum / weight_sum
        covariance = 0.0
        variance = 0.0
        for weight, time_offset, exp_value in weighted_samples:
            time_delta = time_offset - mean_time
            covariance += weight * time_delta * (exp_value - mean_exp)
            variance += weight * time_delta * time_delta

        if variance <= 0:
            return None
        rate_per_second = max(0.0, covariance / variance)
        mean_reading_confidence = reading_confidence_sum / len(samples)
        sample_score = min(1.0, max(0.0, (len(samples) - 1) / 4.0))
        coverage_score = min(1.0, max(0.0, elapsed / window_seconds)) if window_seconds > 0 else 1.0
        confidence = mean_reading_confidence * (sample_score * 0.60 + coverage_score * 0.40)
        return RateEstimate(
            rate_per_second=rate_per_second,
            sample_count=len(samples),
            elapsed_seconds=elapsed,
            confidence=max(0.0, min(1.0, confidence)),
        )

    def _window_samples(
        self,
        window_seconds: float,
        samples: list[ExperienceSample] | None = None,
        *,
        add_stale_anchor: bool = False,
    ) -> list[ExperienceSample]:
        samples = self.samples if samples is None else samples
        if not samples:
            return []

        latest = samples[-1]
        cutoff = latest.captured_at - window_seconds
        window_samples = [sample for sample in samples if sample.captured_at >= cutoff]
        if not window_samples:
            return []
        if (
            not add_stale_anchor
            or len(window_samples) != 1
            or window_samples[0] is not samples[-1]
            or window_samples[0].captured_at <= cutoff
        ):
            return window_samples

        previous = None
        for sample in samples:
            if sample.captured_at >= cutoff:
                break
            previous = sample
        if previous is None:
            return window_samples
        anchor = ExperienceSample(
            cutoff,
            previous.current_exp,
            previous.total_gained_exp,
            previous.percent,
            previous.confidence,
        )
        return [anchor, *window_samples]

    def _samples_with_current_time(self, now: float) -> list[ExperienceSample]:
        if not self.samples:
            return []
        latest = self.samples[-1]
        if now <= latest.captured_at:
            return list(self.samples)
        return [
            *self.samples,
            ExperienceSample(
                now,
                latest.current_exp,
                latest.total_gained_exp,
                latest.percent,
                latest.confidence,
            ),
        ]

    def _latest_real_sample_interval_seconds(self) -> float | None:
        if len(self.samples) < 2:
            return None
        return max(0.0, self.samples[-1].captured_at - self.samples[-2].captured_at)

    def _rate_per_second(self, estimate: RateEstimate | None) -> float | None:
        return None if estimate is None else estimate.rate_per_second

    def _window_rate_per_second(self, value: float | None, window_seconds: float) -> float | None:
        if value is None or window_seconds <= 0:
            return None
        return value / window_seconds

    def _smoothed_rate_or_previous(
        self,
        rate_per_second: float | None,
        multiplier: float,
        field_name: str,
        smoothing_alpha: float,
        update_smoothed_rate: bool,
        sample_count: int,
        stale_seconds: float = 0.0,
    ) -> float | None:
        previous = self._previous_rate_value(field_name)
        if rate_per_second is not None:
            current = rate_per_second * multiplier
            if not update_smoothed_rate:
                return previous if previous is not None else current
            if previous is None:
                return current
            if sample_count <= EXP_RATE_FAST_CONVERGENCE_SAMPLE_COUNT:
                smoothing_alpha = max(smoothing_alpha, EXP_RATE_FAST_SMOOTHING_ALPHA)
            elif previous > 0:
                change_ratio = abs(current - previous) / previous
                if change_ratio >= EXP_RATE_FAST_CHANGE_RATIO:
                    smoothing_alpha = max(smoothing_alpha, EXP_RATE_FAST_SMOOTHING_ALPHA)
            if stale_seconds > 0.0:
                decay_span = max(EXP_RATE_MIN_SECONDS, multiplier * 0.25)
                stale_alpha = 1.0 - math.pow(0.5, stale_seconds / decay_span)
                smoothing_alpha = max(smoothing_alpha, min(0.98, stale_alpha))
            return previous * (1.0 - smoothing_alpha) + current * smoothing_alpha
        return previous

    def _previous_rate_value(self, field_name: str) -> float | None:
        if self.last_snapshot is None:
            return None
        value = getattr(self.last_snapshot, field_name)
        return value if isinstance(value, (int, float)) else None

    def _session_rate_per_second(self) -> float | None:
        if len(self.samples) < 2:
            return None
        elapsed = self.samples[-1].captured_at - self.samples[0].captured_at
        if elapsed < EXP_RATE_MIN_SECONDS:
            return None
        gained = self.samples[-1].total_gained_exp - self.samples[0].total_gained_exp
        return max(0.0, gained / elapsed)

    def _preferred_eta_rate_per_second(
        self,
        five_minute_rate: float | None,
        ten_minute_rate: float | None,
        session_rate: float | None,
        samples: list[ExperienceSample] | None = None,
    ) -> float | None:
        short_rate = ten_minute_rate or five_minute_rate or session_rate
        if session_rate is None:
            return short_rate
        samples = self.samples if samples is None else samples
        if short_rate is None or len(samples) < 2:
            return session_rate

        elapsed = samples[-1].captured_at - samples[0].captured_at
        if elapsed <= EXP_LONG_RATE_BLEND_START_SECONDS:
            return short_rate
        blend_range = EXP_LONG_RATE_BLEND_FULL_SECONDS - EXP_LONG_RATE_BLEND_START_SECONDS
        long_weight = min(0.85, max(0.0, (elapsed - EXP_LONG_RATE_BLEND_START_SECONDS) / blend_range))
        return short_rate * (1.0 - long_weight) + session_rate * long_weight

    def _preferred_eta_confidence(
        self,
        five_minute_estimate: RateEstimate | None,
        ten_minute_estimate: RateEstimate | None,
        long_estimate: RateEstimate | None,
        samples: list[ExperienceSample] | None = None,
    ) -> float | None:
        short_estimate = ten_minute_estimate or five_minute_estimate or long_estimate
        if long_estimate is None:
            return None if short_estimate is None else short_estimate.confidence
        samples = self.samples if samples is None else samples
        if short_estimate is None or len(samples) < 2:
            return long_estimate.confidence

        elapsed = samples[-1].captured_at - samples[0].captured_at
        if elapsed <= EXP_LONG_RATE_BLEND_START_SECONDS:
            return short_estimate.confidence
        blend_range = EXP_LONG_RATE_BLEND_FULL_SECONDS - EXP_LONG_RATE_BLEND_START_SECONDS
        long_weight = min(0.85, max(0.0, (elapsed - EXP_LONG_RATE_BLEND_START_SECONDS) / blend_range))
        return short_estimate.confidence * (1.0 - long_weight) + long_estimate.confidence * long_weight

    def _eta_seconds(self, latest: ExperienceSample, rate_per_second: float | None) -> float | None:
        if (
            rate_per_second is None
            or not math.isfinite(rate_per_second)
            or rate_per_second < EXP_ETA_MIN_RATE_PER_SECOND
        ):
            return None
        if self.estimated_level_total_exp is None:
            return None
        remaining = self.estimated_level_total_exp - latest.current_exp
        if remaining <= 0 or not math.isfinite(remaining):
            return None
        eta_seconds = remaining / rate_per_second
        if not math.isfinite(eta_seconds) or eta_seconds > EXP_ETA_MAX_SECONDS:
            return None
        return eta_seconds


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000.0


def _experience_timing_shape(image: np.ndarray) -> str:
    height, width = image.shape[:2]
    return f"{width}x{height}"


def _experience_timing_result(reading: ExperienceTextReading) -> str:
    result = "success" if reading.success else "failure"
    current_exp = "--" if reading.current_exp is None else str(reading.current_exp)
    percent = "--" if reading.percent is None else f"{reading.percent:.2f}"
    text = reading.text if reading.text else "--"
    return (
        f"{result} exp={current_exp} percent={percent} "
        f"conf={reading.confidence:.2f} text={text!r} reason={reading.reason}"
    )


class PaddleExperienceTextReader:
    def __init__(self) -> None:
        self.ocr: Any | None = None
        self.unavailable_reason: str | None = None

    def read_burst(
        self,
        images: Iterable[np.ndarray | ExperienceOcrImage],
        *,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        return self.read_burst_frames([[image] for image in images], continuity_hint=continuity_hint)

    def read_burst_frames(
        self,
        image_frames: Iterable[Iterable[np.ndarray | ExperienceOcrImage]],
        *,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        started_at = time.perf_counter()
        materialized_frames = [
            [_coerce_experience_ocr_image(image) for image in images]
            for images in image_frames
        ]
        frame_readings = [
            self._read_burst_frame(images, record_learning=False, continuity_hint=continuity_hint)
            for images in materialized_frames
        ]
        reading = self._select_burst_reading(frame_readings, continuity_hint=continuity_hint)
        self._attach_burst_learning_case(materialized_frames, reading)
        log_debug(
            "EXP OCR timing burst "
            f"frames={len(materialized_frames)} rois={sum(len(images) for images in materialized_frames)} "
            f"total_ms={_elapsed_ms(started_at):.1f} result={_experience_timing_result(reading)}"
        )
        return reading

    def _read_burst_frame(
        self,
        images: Iterable[np.ndarray | ExperienceOcrImage],
        *,
        record_learning: bool = True,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        started_at = time.perf_counter()
        materialized_images = list(images)
        if not materialized_images:
            reading = ExperienceTextReading(reason="EXP burst frame 未取得影像")
            log_debug(
                "EXP OCR timing frame "
                f"rois=0 used_rois=0 total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(reading)}"
            )
            return reading

        readings = [
            self.read(
                materialized_images[0],
                record_learning=record_learning,
                continuity_hint=continuity_hint,
            )
        ]
        primary = readings[0]
        if primary.success and primary.current_exp is not None and primary.percent is not None:
            log_debug(
                "EXP OCR timing frame "
                f"rois={len(materialized_images)} used_rois=1 total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(primary)}"
            )
            return primary

        readings.extend(
            self.read(image, record_learning=record_learning, continuity_hint=continuity_hint)
            for image in materialized_images[1:]
        )
        if not readings:
            return ExperienceTextReading(reason="EXP burst frame 未取得影像")

        successes = [
            reading
            for reading in readings
            if reading.success and reading.current_exp is not None and reading.percent is not None
        ]
        if not successes:
            selected = max(readings, key=lambda reading: reading.confidence)
            log_debug(
                "EXP OCR timing frame "
                f"rois={len(materialized_images)} used_rois={len(readings)} total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(selected)}"
            )
            return selected

        groups: dict[tuple[int, float], list[ExperienceTextReading]] = {}
        for reading in successes:
            assert reading.current_exp is not None
            assert reading.percent is not None
            groups.setdefault((reading.current_exp, round(reading.percent, 2)), []).append(reading)

        if len(groups) > 1:
            primary = readings[0]
            if primary.success and primary.current_exp is not None and primary.percent is not None:
                log_debug(
                    "EXP OCR timing frame "
                    f"rois={len(materialized_images)} used_rois={len(readings)} total_ms={_elapsed_ms(started_at):.1f} "
                    f"result={_experience_timing_result(primary)} conflict=1"
                )
                return primary

        consensus_groups = [
            group
            for group in groups.values()
            if len(group) >= EXPERIENCE_BURST_CONSENSUS_MIN_COUNT
        ]
        if consensus_groups:
            ranked_groups = sorted(
                consensus_groups,
                key=lambda group: (len(group), max(reading.confidence for reading in group)),
                reverse=True,
            )
            best_group = ranked_groups[0]
            if len(ranked_groups) > 1 and len(best_group) == len(ranked_groups[1]):
                best_reading = max(
                    (reading for group in ranked_groups for reading in group),
                    key=lambda reading: reading.confidence,
                )
                return ExperienceTextReading(
                    text=best_reading.text,
                    confidence=best_reading.confidence,
                    reason="EXP burst 結果不一致",
                )
            selected = _select_best_success_reading(best_group)
            log_debug(
                "EXP OCR timing frame "
                f"rois={len(materialized_images)} used_rois={len(readings)} total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(selected)}"
            )
            return selected

        if len(groups) == 1:
            selected = _select_best_success_reading(successes)
            log_debug(
                "EXP OCR timing frame "
                f"rois={len(materialized_images)} used_rois={len(readings)} total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(selected)}"
            )
            return selected

        best_reading = _select_best_success_reading(successes)
        result = ExperienceTextReading(
            text=best_reading.text,
            confidence=best_reading.confidence,
            reason="EXP burst 結果不一致",
        )
        log_debug(
            "EXP OCR timing frame "
            f"rois={len(materialized_images)} used_rois={len(readings)} total_ms={_elapsed_ms(started_at):.1f} "
            f"result={_experience_timing_result(result)}"
        )
        return result

    def _select_burst_reading(
        self,
        readings: list[ExperienceTextReading],
        *,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        if not readings:
            return ExperienceTextReading(reason="EXP burst 未取得影像")

        successes = [
            reading
            for reading in readings
            if reading.success and reading.current_exp is not None and reading.percent is not None
        ]
        if not successes:
            return max(readings, key=lambda reading: reading.confidence)

        groups: dict[tuple[int, float], list[ExperienceTextReading]] = {}
        for reading in successes:
            assert reading.current_exp is not None
            assert reading.percent is not None
            groups.setdefault((reading.current_exp, round(reading.percent, 2)), []).append(reading)

        if len(groups) > 1:
            continuity_group = _select_continuity_compatible_reading_group(groups, continuity_hint)
            if continuity_group is not None:
                return _select_best_success_reading(continuity_group)
            progression = self._burst_progression_reading(successes)
            if progression is not None:
                return progression
        if len(groups) == 1:
            return max(successes, key=lambda reading: reading.confidence)

        consensus_groups = [
            group
            for group in groups.values()
            if len(group) >= EXPERIENCE_BURST_CONSENSUS_MIN_COUNT
        ]
        if consensus_groups:
            ranked_groups = sorted(
                consensus_groups,
                key=lambda group: (len(group), max(reading.confidence for reading in group)),
                reverse=True,
            )
            best_group = ranked_groups[0]
            if len(ranked_groups) == 1 or len(best_group) > len(ranked_groups[1]):
                return _select_best_success_reading(best_group)

        best_reading = _select_best_success_reading(successes)
        return ExperienceTextReading(
            text=best_reading.text,
            confidence=best_reading.confidence,
            reason="EXP burst 結果不一致",
        )

    def _burst_progression_reading(self, readings: list[ExperienceTextReading]) -> ExperienceTextReading | None:
        if not readings:
            return None
        if len(readings) == 1:
            return readings[0]

        previous: ExperienceTextReading | None = None
        estimates: list[float] = []
        for reading in readings:
            if reading.current_exp is None or reading.percent is None:
                return None
            if previous is not None:
                if previous.current_exp is None or previous.percent is None:
                    return None
                if reading.current_exp < previous.current_exp:
                    return None
                if reading.percent < previous.percent - EXP_PERCENT_REGRESSION_TOLERANCE:
                    return None
            if reading.percent >= 0.5:
                estimates.append(reading.current_exp / max(0.01, reading.percent / 100.0))
            previous = reading

        if len(estimates) >= 2:
            low = min(estimates)
            high = max(estimates)
            if low <= 0 or (high - low) / low > EXP_TOTAL_ESTIMATE_MAX_DEVIATION_RATIO:
                return None

        return readings[-1]

    def read(
        self,
        image: np.ndarray | ExperienceOcrImage,
        *,
        record_learning: bool = True,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        started_at = time.perf_counter()
        ocr_image = _coerce_experience_ocr_image(image)
        image_array = ocr_image.image
        bar_started_at = time.perf_counter()
        bar_percent = estimate_experience_bar_percent(
            image_array,
            bar_crop_left_ratio=ocr_image.bar_crop_left_ratio,
        )
        bar_ms = _elapsed_ms(bar_started_at)
        pixel_started_at = time.perf_counter()
        pixel_reading = _read_experience_pixel_font_adaptive(
            ocr_image,
            bar_percent=bar_percent,
            continuity_hint=continuity_hint,
        )
        pixel_reading = _with_experience_reading_metadata(pixel_reading, bar_percent=bar_percent, source="pixel")
        pixel_ms = _elapsed_ms(pixel_started_at)
        if pixel_reading.success:
            guarded_pixel_reading = _apply_experience_ocr_continuity_guard(pixel_reading, continuity_hint)
            if guarded_pixel_reading.success:
                log_debug(
                    "EXP OCR timing read "
                    f"source={ocr_image.source_id or 'roi'} shape={_experience_timing_shape(image_array)} "
                    f"bar_ms={bar_ms:.1f} pixel_ms={pixel_ms:.1f} paddle_ms=0.0 total_ms={_elapsed_ms(started_at):.1f} "
                    f"result={_experience_timing_result(guarded_pixel_reading)}"
                )
                return guarded_pixel_reading
            pixel_reading = guarded_pixel_reading
            log_debug(
                "EXP OCR timing read "
                f"source={ocr_image.source_id or 'roi'} shape={_experience_timing_shape(image_array)} "
                f"bar_ms={bar_ms:.1f} pixel_ms={pixel_ms:.1f} paddle_ms=0.0 total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(pixel_reading)}"
            )

        paddle_started_at = time.perf_counter()
        paddle_reading = self._read_with_paddle(ocr_image, bar_percent=bar_percent)
        paddle_reading = _with_experience_reading_metadata(paddle_reading, bar_percent=bar_percent, source="paddle")
        if paddle_reading.success:
            paddle_reading = _apply_experience_ocr_continuity_guard(paddle_reading, continuity_hint)
        paddle_ms = _elapsed_ms(paddle_started_at)
        if paddle_reading.success:
            log_debug(
                "EXP OCR timing read "
                f"source={ocr_image.source_id or 'roi'} shape={_experience_timing_shape(image_array)} "
                f"bar_ms={bar_ms:.1f} pixel_ms={pixel_ms:.1f} paddle_ms={paddle_ms:.1f} total_ms={_elapsed_ms(started_at):.1f} "
                f"result={_experience_timing_result(paddle_reading)} pixel_reason={pixel_reading.reason}"
            )
            return paddle_reading

        final_reading = paddle_reading if paddle_reading.confidence >= pixel_reading.confidence else pixel_reading
        if record_learning:
            case_id = save_experience_ocr_learning_case(
                [[ocr_image]],
                trigger=_experience_ocr_learning_trigger_for_reading(final_reading),
                pixel_reading=pixel_reading,
                paddle_reading=paddle_reading,
                final_reading=final_reading,
                bar_percent=bar_percent,
            )
            final_reading.learning_case_id = case_id
        log_debug(
            "EXP OCR timing read "
            f"source={ocr_image.source_id or 'roi'} shape={_experience_timing_shape(image_array)} "
            f"bar_ms={bar_ms:.1f} pixel_ms={pixel_ms:.1f} paddle_ms={paddle_ms:.1f} total_ms={_elapsed_ms(started_at):.1f} "
            f"result={_experience_timing_result(final_reading)} pixel_reason={pixel_reading.reason}"
        )
        return final_reading

    def _attach_burst_learning_case(
        self,
        image_frames: list[list[ExperienceOcrImage]],
        reading: ExperienceTextReading,
    ) -> None:
        if reading.learning_case_id:
            return
        if reading.success:
            return
        if not image_frames:
            return

        case_id = save_experience_ocr_learning_case(
            image_frames,
            trigger=_experience_ocr_learning_trigger_for_reading(reading),
            pixel_reading=None,
            paddle_reading=None,
            final_reading=reading,
        )
        reading.learning_case_id = case_id

    def _read_with_paddle(
        self,
        ocr_image: ExperienceOcrImage,
        *,
        bar_percent: float | None,
    ) -> ExperienceTextReading:
        started_at = time.perf_counter()
        ensure_started_at = time.perf_counter()
        if not self._ensure_ocr():
            log_debug(
                "EXP OCR timing paddle "
                f"source={ocr_image.source_id or 'roi'} ensure_ms={_elapsed_ms(ensure_started_at):.1f} "
                f"total_ms={_elapsed_ms(started_at):.1f} result=unavailable reason={self.unavailable_reason or '--'}"
            )
            return ExperienceTextReading(reason=self.unavailable_reason or "PaddleOCR 尚未初始化")
        ensure_ms = _elapsed_ms(ensure_started_at)

        image_array = ocr_image.image
        fallback_reading: ExperienceTextReading | None = None
        successes: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]] = []
        predict_count = 0
        predict_ms = 0.0

        def read_variants(variants: Iterable[tuple[int, np.ndarray]]) -> None:
            nonlocal fallback_reading, predict_count, predict_ms
            for variant_index, prepared in variants:
                try:
                    predict_started_at = time.perf_counter()
                    result = self._predict(prepared)
                    predict_ms += _elapsed_ms(predict_started_at)
                    predict_count += 1
                except Exception as exc:
                    fallback_reading = ExperienceTextReading(reason=f"PaddleOCR 辨識失敗：{exc}")
                    return

                reading = _apply_experience_bar_percent_guard(
                    reading_from_paddle_result(result),
                    bar_percent,
                )
                if reading.success:
                    rank = _experience_reading_rank(reading, variant_index)
                    successes.append((rank, variant_index, reading))
                if fallback_reading is None or reading.confidence > fallback_reading.confidence:
                    fallback_reading = reading

        base_prepare_started_at = time.perf_counter()
        base_variants = _indexed_experience_ocr_images(image_array)
        base_prepare_ms = _elapsed_ms(base_prepare_started_at)
        read_variants(base_variants)
        base_reading = _selected_experience_reading_or_failure(successes, bar_percent=bar_percent)
        if base_reading is not None and base_reading.success:
            log_debug(
                "EXP OCR timing paddle "
                f"source={ocr_image.source_id or 'roi'} variants={len(base_variants)} retry_variants=0 "
                f"ensure_ms={ensure_ms:.1f} prepare_ms={base_prepare_ms:.1f} predict_ms={predict_ms:.1f} "
                f"predict_count={predict_count} total_ms={_elapsed_ms(started_at):.1f} result={_experience_timing_result(base_reading)}"
            )
            return base_reading
        if _should_retry_experience_ocr(base_reading or fallback_reading):
            retry_prepare_started_at = time.perf_counter()
            retry_variants = _indexed_retry_experience_ocr_images(image_array)
            retry_prepare_ms = _elapsed_ms(retry_prepare_started_at)
            read_variants(retry_variants)
        else:
            retry_variants = []
            retry_prepare_ms = 0.0
        if successes:
            selected = _selected_experience_reading_or_failure(successes, bar_percent=bar_percent)
            if selected is not None:
                log_debug(
                    "EXP OCR timing paddle "
                    f"source={ocr_image.source_id or 'roi'} variants={len(base_variants)} retry_variants={len(retry_variants)} "
                    f"ensure_ms={ensure_ms:.1f} prepare_ms={(base_prepare_ms + retry_prepare_ms):.1f} predict_ms={predict_ms:.1f} "
                    f"predict_count={predict_count} total_ms={_elapsed_ms(started_at):.1f} result={_experience_timing_result(selected)}"
                )
                return selected
        final = fallback_reading or ExperienceTextReading(reason="EXP 數字解析失敗")
        log_debug(
            "EXP OCR timing paddle "
            f"source={ocr_image.source_id or 'roi'} variants={len(base_variants)} retry_variants={len(retry_variants)} "
            f"ensure_ms={ensure_ms:.1f} prepare_ms={(base_prepare_ms + retry_prepare_ms):.1f} predict_ms={predict_ms:.1f} "
            f"predict_count={predict_count} total_ms={_elapsed_ms(started_at):.1f} result={_experience_timing_result(final)}"
        )
        return final

    def _ensure_ocr(self) -> bool:
        if self.ocr is not None:
            return True
        if self.unavailable_reason is not None:
            return False

        configure_paddleocr_runtime()
        with suppress_paddleocr_output():
            try:
                from paddleocr import PaddleOCR
            except Exception as exc:
                self.unavailable_reason = f"未安裝 PaddleOCR：{exc}"
                return False

            return self._build_ocr(PaddleOCR)

    def _build_ocr(self, paddle_ocr_factory: Any) -> bool:
        try:
            self.ocr = paddle_ocr_factory(
                text_detection_model_name=PADDLEOCR_DETECTION_MODEL_NAME,
                text_recognition_model_name=PADDLEOCR_RECOGNITION_MODEL_NAME,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except TypeError:
            try:
                self.ocr = paddle_ocr_factory(lang=PADDLEOCR_LANGUAGE, use_angle_cls=False, show_log=False)
            except Exception as exc:
                self.unavailable_reason = f"PaddleOCR 初始化失敗：{exc}"
                return False
        except Exception as exc:
            self.unavailable_reason = f"PaddleOCR 初始化失敗：{exc}"
            return False
        return True

    def _predict(self, image: np.ndarray) -> object:
        if hasattr(self.ocr, "predict"):
            return self.ocr.predict(input=image)
        return self.ocr.ocr(image, cls=False)


def prepare_experience_ocr_image(image: np.ndarray) -> np.ndarray:
    bgr = _suppress_experience_green_bar_background(image[:, :, :3])
    height, width = bgr.shape[:2]
    if height <= 0 or width <= 0:
        return bgr
    padding = max(
        EXP_OCR_CONTEXT_MIN_PADDING,
        min(EXP_OCR_CONTEXT_MAX_PADDING, round(height * EXP_OCR_CONTEXT_PADDING_RATIO)),
    )
    padded = cv2.copyMakeBorder(
        bgr,
        padding,
        padding,
        padding,
        padding,
        borderType=cv2.BORDER_REPLICATE,
    )
    return cv2.resize(
        padded,
        (
            max(1, padded.shape[1] * EXP_OCR_PREPARED_SCALE),
            max(1, padded.shape[0] * EXP_OCR_PREPARED_SCALE),
        ),
        interpolation=cv2.INTER_LINEAR,
    )


def _coerce_experience_ocr_image(image: np.ndarray | ExperienceOcrImage) -> ExperienceOcrImage:
    if isinstance(image, ExperienceOcrImage):
        return image
    return ExperienceOcrImage(image=image)


def _indexed_experience_ocr_images(image: np.ndarray) -> list[tuple[int, np.ndarray]]:
    return list(enumerate(prepare_experience_ocr_images(image)))


def _indexed_retry_experience_ocr_images(image: np.ndarray) -> list[tuple[int, np.ndarray]]:
    # Variant index 1 keeps these retry images in the non-binary candidate class.
    return [(1, variant) for variant in prepare_experience_retry_ocr_images(image)]


def prepare_experience_binary_source_image(image: np.ndarray) -> np.ndarray:
    bgr = _suppress_experience_green_bar_background(image[:, :, :3])
    source_height = max(1, bgr.shape[0])
    scale = max(EXP_OCR_IMAGE_SCALE, min(EXP_OCR_MAX_SCALE, round(EXP_OCR_TARGET_HEIGHT / source_height)))
    resized = cv2.resize(
        bgr,
        (max(1, bgr.shape[1] * scale), max(1, bgr.shape[0] * scale)),
        interpolation=cv2.INTER_CUBIC,
    )
    text_crop = crop_experience_text_image(resized)
    text_crop = resize_experience_text_crop(text_crop)
    return text_crop


def prepare_experience_ocr_images(image: np.ndarray) -> list[np.ndarray]:
    original = image[:, :, :3]
    primary = prepare_experience_ocr_image(image)
    variants = [original, primary]
    binary_source = prepare_experience_binary_source_image(image)
    binary = _binarize_experience_text(binary_source)
    if binary is not None:
        variants.append(binary)
    bold_binary = _binarize_experience_text(binary_source, text_expansion_iterations=2)
    if bold_binary is not None:
        variants.append(bold_binary)
    return variants


def prepare_experience_retry_ocr_images(image: np.ndarray) -> list[np.ndarray]:
    bgr = _suppress_experience_green_bar_background(image[:, :, :3])
    source_height = max(1, bgr.shape[0])
    scale = max(EXP_OCR_IMAGE_SCALE, min(EXP_OCR_MAX_SCALE, round(EXP_OCR_TARGET_HEIGHT / source_height)))
    resized = cv2.resize(
        bgr,
        (max(1, bgr.shape[1] * scale), max(1, bgr.shape[0] * scale)),
        interpolation=cv2.INTER_CUBIC,
    )
    cropped = resize_experience_text_crop(crop_experience_text_image(resized))
    contrast = _contrast_experience_text_image(cropped)
    sharpened = _sharpen_experience_text_image(contrast)
    variants = [cropped, contrast, sharpened]
    unique: list[np.ndarray] = []
    seen: set[tuple[tuple[int, ...], bytes]] = set()
    for variant in variants:
        key = (tuple(int(part) for part in variant.shape), variant.tobytes())
        if key in seen:
            continue
        seen.add(key)
        unique.append(variant)
    return unique


def _contrast_experience_text_image(image: np.ndarray) -> np.ndarray:
    return cv2.convertScaleAbs(image[:, :, :3], alpha=1.35, beta=8)


def _sharpen_experience_text_image(image: np.ndarray) -> np.ndarray:
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    return cv2.filter2D(image[:, :, :3], -1, kernel)


def _suppress_experience_green_bar_background(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3].copy()
    if bgr.size == 0:
        return bgr
    bar_percent = estimate_experience_bar_percent(bgr)
    if (
        bar_percent is None
        or bar_percent < EXP_OCR_GREEN_BACKGROUND_MIN_BAR_PERCENT
        or bar_percent > EXP_OCR_GREEN_BACKGROUND_MAX_BAR_PERCENT
    ):
        return bgr
    bgr_f = bgr.astype(np.float32)
    blue = bgr_f[:, :, 0]
    green = bgr_f[:, :, 1]
    red = bgr_f[:, :, 2]
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    green_background = (
        (green >= EXP_OCR_GREEN_BACKGROUND_MIN_GREEN)
        & (chroma >= EXP_OCR_GREEN_BACKGROUND_MIN_CHROMA)
        & (green >= red + 8.0)
        & (green >= blue + 25.0)
    )
    if green_background.any():
        bgr[green_background] = EXP_OCR_GREEN_BACKGROUND_REPLACEMENT
    return bgr


def estimate_experience_bar_percent(
    image: np.ndarray,
    *,
    bar_crop_left_ratio: float = EXP_OCR_BAR_CROP_LEFT_RATIO,
) -> float | None:
    bgr = image[:, :, :3].astype(np.float32)
    if bgr.size == 0:
        return None
    bar_crop_left_ratio = max(0.0, min(0.98, float(bar_crop_left_ratio)))
    blue = bgr[:, :, 0]
    green = bgr[:, :, 1]
    red = bgr[:, :, 2]
    green_mask = (green >= 120.0) & (green - red >= 40.0) & (green - blue >= 20.0)
    column_density = green_mask.mean(axis=0)
    width = bgr.shape[1]
    left_touch_pixels = max(2, round(width * EXP_OCR_BAR_LEFT_TOUCH_RATIO))
    green_runs = _boolean_runs(column_density >= EXP_OCR_BAR_GREEN_COLUMN_MIN_RATIO)
    if not green_runs:
        return None
    left_runs = [run for run in green_runs if run[0] <= left_touch_pixels]
    if left_runs:
        first_green, run_end = _merged_left_experience_bar_green_run(green_runs, left_touch_pixels, width)
    else:
        first_green, run_end = max(green_runs, key=lambda run: run[1] - run[0])
    last_green = run_end - 1
    span_ratio = (last_green - first_green + 1) / max(1, width)
    touches_left = first_green <= left_touch_pixels
    min_span_ratio = (
        EXP_OCR_BAR_MIN_PARTIAL_GREEN_SPAN_RATIO
        if touches_left and bar_crop_left_ratio > 0.0
        else EXP_OCR_BAR_MIN_GREEN_SPAN_RATIO
    )
    if span_ratio < min_span_ratio:
        return None
    cropped_fill_ratio = (last_green + 1) / max(1, width)
    full_fill_ratio = bar_crop_left_ratio + cropped_fill_ratio * (1.0 - bar_crop_left_ratio)
    return max(0.0, min(100.0, full_fill_ratio * 100.0))


def _merged_left_experience_bar_green_run(
    green_runs: list[tuple[int, int]],
    left_touch_pixels: int,
    width: int,
) -> tuple[int, int]:
    merge_gap = max(8, round(width * 0.04))
    first_green = 0
    run_end = 0
    for start, end in green_runs:
        if run_end == 0:
            if start > left_touch_pixels:
                continue
            first_green = start
            run_end = end
            continue
        if start - run_end > merge_gap:
            break
        run_end = end
    return first_green, run_end


def _apply_experience_bar_percent_guard(
    reading: ExperienceTextReading,
    bar_percent: float | None,
) -> ExperienceTextReading:
    reading = _with_experience_reading_metadata(reading, bar_percent=bar_percent)
    if not reading.success or reading.percent is None or bar_percent is None:
        if reading.success and reading.needs_bar_percent_guard:
            return ExperienceTextReading(
                current_exp=reading.current_exp,
                percent=reading.percent,
                text=reading.text,
                confidence=reading.confidence,
                reason="EXP 百分比需要綠條確認",
                needs_bar_percent_guard=reading.needs_bar_percent_guard,
                bar_percent=bar_percent,
                continuity_status=reading.continuity_status,
                source=reading.source,
            )
        return reading
    if abs(reading.percent - bar_percent) <= EXP_OCR_BAR_PERCENT_TOLERANCE:
        return reading
    return ExperienceTextReading(
        current_exp=reading.current_exp,
        percent=reading.percent,
        text=reading.text,
        confidence=reading.confidence,
        reason="EXP 百分比與綠條不一致",
        needs_bar_percent_guard=reading.needs_bar_percent_guard,
        bar_percent=bar_percent,
        continuity_status=reading.continuity_status,
        source=reading.source,
    )


def _with_experience_reading_metadata(
    reading: ExperienceTextReading,
    *,
    bar_percent: float | None = None,
    continuity_status: str | None = None,
    source: str | None = None,
) -> ExperienceTextReading:
    if bar_percent is not None:
        reading.bar_percent = bar_percent
    if continuity_status is not None:
        reading.continuity_status = continuity_status
    if source is not None and not reading.source:
        reading.source = source
    return reading


def _apply_experience_ocr_continuity_guard(
    reading: ExperienceTextReading,
    continuity_hint: ExperienceOcrContinuityHint | None,
) -> ExperienceTextReading:
    status = _experience_ocr_continuity_status(reading.current_exp, reading.percent, continuity_hint)
    reading.continuity_status = status
    if status != "incompatible":
        return reading
    return ExperienceTextReading(
        current_exp=reading.current_exp,
        percent=reading.percent,
        text=reading.text,
        confidence=reading.confidence,
        reason="EXP OCR 連續性不可信",
        needs_bar_percent_guard=reading.needs_bar_percent_guard,
        learning_case_id=reading.learning_case_id,
        bar_percent=reading.bar_percent,
        continuity_status=status,
        source=reading.source,
    )


def _read_experience_pixel_font_adaptive(
    ocr_image: ExperienceOcrImage,
    *,
    bar_percent: float | None,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> ExperienceTextReading:
    started_at = time.perf_counter()
    successes: list[tuple[tuple[float, float, float, int], ExperienceTextReading]] = []
    best_failure = ExperienceTextReading(reason="EXP 像素字型解析失敗")
    attempt_count = 0
    candidate_count = 0

    def finish(reading: ExperienceTextReading) -> ExperienceTextReading:
        log_debug(
            "EXP OCR timing pixel "
            f"source={ocr_image.source_id or 'roi'} attempts={attempt_count} candidates={candidate_count} "
            f"total_ms={_elapsed_ms(started_at):.1f} result={_experience_timing_result(reading)}"
        )
        return reading

    for attempt_index, attempt in enumerate(_experience_pixel_font_attempts(ocr_image)):
        attempt_count += 1
        attempt_bar_percent = estimate_experience_bar_percent(
            attempt.image,
            bar_crop_left_ratio=attempt.bar_crop_left_ratio,
        )
        effective_bar_percent = bar_percent if bar_percent is not None else attempt_bar_percent
        candidates = _decode_experience_pixel_font_text_candidates(
            attempt.image,
            bar_percent=effective_bar_percent,
        )
        candidate_count += len(candidates)
        if not candidates:
            continue
        for text, confidence in candidates:
            reading = _pixel_font_text_reading(
                text,
                confidence,
                bar_percent=effective_bar_percent,
                attempt=attempt,
            )
            if reading.success:
                successes.append((_pixel_font_reading_rank(reading, attempt_index, effective_bar_percent), reading))
            elif reading.confidence >= best_failure.confidence:
                best_failure = reading

        selected = _select_pixel_font_success(successes, effective_bar_percent, continuity_hint=continuity_hint)
        if selected is not None and selected.success:
            return finish(selected)

    selected = _select_pixel_font_success(successes, bar_percent, continuity_hint=continuity_hint)
    return finish(selected if selected is not None else best_failure)


def _experience_pixel_font_attempts(ocr_image: ExperienceOcrImage) -> list[ExperiencePixelFontAttempt]:
    image = ocr_image.image
    variants: list[tuple[str, tuple[int, int, int, int], np.ndarray]] = []

    def add_variant(name: str, offset: tuple[int, int, int, int], variant: np.ndarray) -> None:
        if variant.size:
            variants.append((name, offset, variant))

    add_variant("raw", (0, 0, 0, 0), image)
    add_variant("green_suppressed", (0, 0, 0, 0), _suppress_experience_green_bar_background(image[:, :, :3]))
    add_variant("low_threshold_mask", (0, 0, 0, 0), _experience_pixel_font_mask_source_image(image, luminance_min=170.0, close_iterations=0))
    add_variant("low_threshold_closed", (0, 0, 0, 0), _experience_pixel_font_mask_source_image(image, luminance_min=170.0, close_iterations=1))

    height, width = image.shape[:2]
    crop_specs = [
        ("shift_left_2", (0, 0, -2, 0), (0, 0, max(1, width - 2), height)),
        ("shift_right_2", (2, 0, 0, 0), (2, 0, width, height)),
        ("shift_up_1", (0, 0, 0, -1), (0, 0, width, max(1, height - 1))),
        ("shift_down_1", (0, 1, 0, 0), (0, 1, width, height)),
        ("tight_left_4", (4, 0, 0, 0), (4, 0, width, height)),
        ("tight_right_4", (0, 0, -4, 0), (0, 0, max(1, width - 4), height)),
        ("trim_vertical", (0, 1, 0, -1), (0, 1, width, max(1, height - 1))),
    ]
    for name, offset, (left, top, right, bottom) in crop_specs:
        if right > left and bottom > top:
            add_variant(name, offset, image[top:bottom, left:right])

    unique: list[ExperiencePixelFontAttempt] = []
    seen: set[tuple[tuple[int, ...], bytes]] = set()
    for index, (name, offset, variant) in enumerate(variants):
        key = (tuple(int(part) for part in variant.shape), variant[:, :, :3].tobytes())
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            ExperiencePixelFontAttempt(
                image=variant,
                bar_crop_left_ratio=ocr_image.bar_crop_left_ratio,
                source_id=ocr_image.source_id,
                roi_offset=offset,
                preprocess_variant=name,
                attempt_id=f"{ocr_image.attempt_id or ocr_image.source_id or 'roi'}:{index}:{name}",
            )
        )
        if len(unique) >= EXP_PIXEL_FONT_RECOGNIZER_MAX_ATTEMPTS:
            break
    return unique


def _experience_pixel_font_mask_source_image(
    image: np.ndarray,
    *,
    luminance_min: float,
    close_iterations: int,
) -> np.ndarray:
    bgr = _suppress_experience_green_bar_background(image[:, :, :3])
    bgr_f = bgr.astype(np.float32)
    blue = bgr_f[:, :, 0]
    green = bgr_f[:, :, 1]
    red = bgr_f[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    mask = (luminance >= luminance_min) & (chroma <= max(70.0, EXP_OCR_BINARY_MAX_CHROMA))
    mask = _clean_experience_text_mask(mask)
    if close_iterations > 0 and mask.any():
        kernel = np.ones((2, 2), dtype=np.uint8)
        mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel, iterations=close_iterations).astype(bool)
    prepared = np.zeros(bgr.shape, dtype=np.uint8)
    prepared[mask] = 255
    return prepared


def _pixel_font_text_reading(
    text: str,
    confidence: float,
    *,
    bar_percent: float | None,
    attempt: ExperiencePixelFontAttempt,
) -> ExperienceTextReading:
    compact = normalize_exp_ocr_text(text)
    match = re.fullmatch(r"([0-9]+)\[((?:[0-9]{1,2}|100)\.[0-9]{2})%\]", compact)
    if match is None:
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 像素字型結構不可信")
    if confidence < EXP_PIXEL_FONT_RECOGNIZER_MIN_CONFIDENCE:
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 像素字型信心過低")

    current_exp = int(match.group(1))
    percent = float(match.group(2))
    if bar_percent is not None and abs(percent - bar_percent) > EXP_PIXEL_FONT_RECOGNIZER_BAR_PERCENT_TOLERANCE:
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 百分比與綠條不一致")
    if _pixel_font_full_bar_reading_needs_higher_confidence(percent, confidence=confidence, bar_percent=bar_percent):
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 滿條像素字型信心不足")
    if bar_percent is None and not _pixel_font_no_bar_percent_is_acceptable(percent, confidence=confidence, attempt=attempt):
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 百分比缺少綠條確認")

    source = attempt.preprocess_variant
    if attempt.roi_offset != (0, 0, 0, 0):
        source = f"{source}@{attempt.roi_offset}"
    return ExperienceTextReading(
        current_exp=current_exp,
        percent=percent,
        text=text,
        confidence=confidence,
        success=True,
        reason="OK:Pixel" if source == "raw" else f"OK:Pixel:{source}",
    )


def _pixel_font_full_bar_reading_needs_higher_confidence(
    percent: float,
    *,
    confidence: float,
    bar_percent: float | None,
) -> bool:
    near_full_percent = percent >= EXP_PIXEL_FONT_FULL_BAR_PERCENT_MIN
    near_full_bar = bar_percent is not None and bar_percent >= EXP_PIXEL_FONT_FULL_BAR_PERCENT_MIN
    return (near_full_percent or near_full_bar) and confidence < EXP_PIXEL_FONT_FULL_BAR_MIN_CONFIDENCE


def _pixel_font_no_bar_percent_is_acceptable(
    percent: float,
    *,
    confidence: float,
    attempt: ExperiencePixelFontAttempt,
) -> bool:
    if confidence >= 0.98:
        return True
    return (
        percent <= EXP_PIXEL_FONT_NO_BAR_LOW_PERCENT_MAX
        and confidence >= EXP_PIXEL_FONT_NO_BAR_LOW_PERCENT_MIN_CONFIDENCE
        and attempt.roi_offset == (0, 0, 0, 0)
    )


def _pixel_font_reading_rank(
    reading: ExperienceTextReading,
    attempt_index: int,
    bar_percent: float | None,
) -> tuple[float, float, float, int]:
    bar_score = 0.0
    if reading.percent is not None and bar_percent is not None:
        bar_score = max(0.0, 1.0 - abs(reading.percent - bar_percent) / EXP_PIXEL_FONT_RECOGNIZER_BAR_PERCENT_TOLERANCE)
    return (
        reading.confidence,
        bar_score,
        1.0 if reading.reason == "OK:Pixel" else 0.0,
        -attempt_index,
    )


def _select_pixel_font_success(
    successes: list[tuple[tuple[float, float, float, int], ExperienceTextReading]],
    bar_percent: float | None,
    *,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> ExperienceTextReading | None:
    if not successes:
        return None
    groups: dict[tuple[int, float], list[tuple[tuple[float, float, float, int], ExperienceTextReading]]] = {}
    for item in successes:
        _rank, reading = item
        if reading.current_exp is None or reading.percent is None:
            continue
        groups.setdefault((reading.current_exp, round(reading.percent, 2)), []).append(item)
    if not groups:
        return None

    same_percent_exps: dict[float, set[int]] = {}
    for current_exp, percent in groups:
        same_percent_exps.setdefault(percent, set()).add(current_exp)
    if any(len(exps) > 1 for exps in same_percent_exps.values()):
        continuity_group = _select_continuity_compatible_reading_group(groups, continuity_hint)
        if continuity_group is not None:
            return max(continuity_group, key=lambda item: item[0])[1]
        ranked = sorted(successes, key=lambda item: item[0], reverse=True)
        best_rank, best = ranked[0]
        second_rank = ranked[1][0] if len(ranked) > 1 else (0.0, 0.0, 0.0, 0)
        if best_rank[0] >= 0.98 and best_rank[0] - second_rank[0] >= 0.004:
            return best
        return ExperienceTextReading(text=best.text, confidence=best.confidence, reason="EXP OCR 模糊數字候選不一致")

    if len(groups) > 1 and bar_percent is None:
        continuity_group = _select_continuity_compatible_reading_group(groups, continuity_hint)
        if continuity_group is not None:
            return max(continuity_group, key=lambda item: item[0])[1]
        best = max(successes, key=lambda item: item[0])[1]
        return ExperienceTextReading(text=best.text, confidence=best.confidence, reason="EXP OCR 候選不一致")

    if bar_percent is not None:
        viable = [
            (key, group)
            for key, group in groups.items()
            if abs(key[1] - bar_percent) <= EXP_PIXEL_FONT_RECOGNIZER_BAR_PERCENT_TOLERANCE
        ]
        if viable:
            _key, selected_group = max(
                viable,
                key=lambda item: (
                    _continuity_group_rank(item[0][0], item[0][1], continuity_hint),
                    max(group_item[0][0] for group_item in item[1]),
                    max(group_item[0][2] for group_item in item[1]),
                    -abs(item[0][1] - bar_percent),
                    max(group_item[0][3] for group_item in item[1]),
                ),
            )
            return max(selected_group, key=lambda item: item[0])[1]

    selected_group = max(
        groups.values(),
        key=lambda group: (
            _continuity_group_rank(group[0][1].current_exp, group[0][1].percent, continuity_hint),
            max(item[0] for item in group),
        ),
    )
    return max(selected_group, key=lambda item: item[0])[1]


def _select_continuity_compatible_reading_group(
    groups: dict[tuple[int, float], list[Any]],
    continuity_hint: ExperienceOcrContinuityHint | None,
) -> list[Any] | None:
    if continuity_hint is None or not groups:
        return None
    ranked_groups = sorted(
        groups.items(),
        key=lambda item: _continuity_group_rank(item[0][0], item[0][1], continuity_hint),
        reverse=True,
    )
    best_key, best_group = ranked_groups[0]
    best_rank = _continuity_group_rank(best_key[0], best_key[1], continuity_hint)
    if best_rank < 2:
        return None
    second_rank = -1 if len(ranked_groups) == 1 else _continuity_group_rank(
        ranked_groups[1][0][0],
        ranked_groups[1][0][1],
        continuity_hint,
    )
    if best_rank <= second_rank:
        return None
    return best_group


def _continuity_group_rank(
    current_exp: int | None,
    percent: float | None,
    continuity_hint: ExperienceOcrContinuityHint | None,
) -> int:
    status = _experience_ocr_continuity_status(current_exp, percent, continuity_hint)
    if status in {"compatible", "level_up"}:
        return 3
    if status == "unknown":
        return 1
    if status == "suspicious_jump":
        return 0
    return -1


def _experience_ocr_continuity_status(
    current_exp: int | None,
    percent: float | None,
    continuity_hint: ExperienceOcrContinuityHint | None,
) -> str:
    if continuity_hint is None or current_exp is None:
        return "unknown"
    previous_percent = continuity_hint.percent
    if previous_percent is None or percent is None:
        return "compatible" if current_exp >= continuity_hint.current_exp else "unknown"
    if current_exp < continuity_hint.current_exp:
        if (
            previous_percent >= EXP_OCR_CONTINUITY_LEVEL_UP_PREVIOUS_PERCENT_MIN
            and percent <= EXP_OCR_CONTINUITY_LEVEL_UP_CANDIDATE_PERCENT_MAX
        ):
            return "level_up"
        return "incompatible"
    if percent < previous_percent - EXP_PERCENT_REGRESSION_TOLERANCE:
        return "incompatible"
    elapsed_seconds = max(0.0, continuity_hint.now - continuity_hint.captured_at)
    allowed_gain = max(
        EXP_OCR_CONTINUITY_MIN_JUMP_PERCENT,
        elapsed_seconds * EXP_OCR_CONTINUITY_MAX_PERCENT_GAIN_PER_SECOND,
    )
    if percent - previous_percent > allowed_gain:
        return "suspicious_jump"
    return "compatible"


def _decode_experience_pixel_font_text_candidates(
    image: np.ndarray,
    *,
    bar_percent: float | None,
) -> list[tuple[str, float]]:
    mask = _experience_pixel_font_mask(image)
    segments = _experience_pixel_font_segments(mask)
    if len(segments) < 4 or len(segments) > 24:
        return []

    alternatives = [_experience_pixel_font_glyph_alternatives(segment) for segment in segments]
    if any(not item for item in alternatives):
        return []

    candidates = _structured_pixel_font_text_candidates(alternatives, segments, bar_percent)
    characters = [item[0][0] for item in alternatives]
    confidences = [item[0][1] for item in alternatives]
    candidates.append(("".join(characters), float(np.mean(confidences))))
    candidates.extend(_bar_guided_pixel_font_percent_candidates(characters, alternatives, segments, bar_percent))

    unique: dict[str, float] = {}
    for text, confidence in candidates:
        if confidence > unique.get(text, -1.0):
            unique[text] = confidence
    return sorted(unique.items(), key=lambda item: item[1], reverse=True)


def _structured_pixel_font_text_candidates(
    alternatives: list[list[tuple[str, float]]],
    segments: list[np.ndarray],
    bar_percent: float | None,
) -> list[tuple[str, float]]:
    segment_count = len(alternatives)
    results: list[tuple[str, float]] = []
    for integer_digit_count in (2, 1, 3):
        tail_length = integer_digit_count + 6
        open_index = segment_count - tail_length
        if open_index <= 0:
            continue
        layout = _pixel_font_percent_layout(open_index, integer_digit_count)
        if layout is None:
            continue
        base = _pixel_font_candidate_from_layout(alternatives, layout, open_index, integer_digit_count)
        if base is not None:
            results.append(base)
            results.extend(_pixel_font_exp_alternative_candidates(alternatives, segments, layout, open_index))
            results.extend(_bar_guided_pixel_font_percent_candidates(list(base[0]), alternatives, segments, bar_percent))
    return results


def _pixel_font_percent_layout(open_index: int, integer_digit_count: int) -> dict[str, int] | None:
    if integer_digit_count not in (1, 2, 3):
        return None
    dot_index = open_index + 1 + integer_digit_count
    percent_index = dot_index + 3
    close_index = percent_index + 1
    return {"open": open_index, "dot": dot_index, "percent": percent_index, "close": close_index}


def _pixel_font_candidate_from_layout(
    alternatives: list[list[tuple[str, float]]],
    layout: dict[str, int],
    open_index: int,
    integer_digit_count: int,
) -> tuple[str, float] | None:
    selected_characters: list[str] = []
    selected_confidences: list[float] = []

    def select(index: int, role: str) -> tuple[str, float] | None:
        glyph_alternatives = alternatives[index]
        if role == "digit":
            return _first_character_alternative(glyph_alternatives, str.isdigit)
        return _first_character_alternative(glyph_alternatives, lambda character: character == role)

    for index in range(0, open_index):
        selected = select(index, "digit")
        if selected is None:
            return None
        selected_characters.append(selected[0])
        selected_confidences.append(selected[1])

    role_by_index = {
        layout["open"]: "[",
        layout["dot"]: ".",
        layout["percent"]: "%",
        layout["close"]: "]",
    }
    percent_digit_indices = [
        index
        for index in range(layout["open"] + 1, layout["percent"])
        if index != layout["dot"]
    ]
    if len(percent_digit_indices) != integer_digit_count + 2:
        return None

    for index in range(open_index, len(alternatives)):
        role = role_by_index.get(index, "digit")
        selected = select(index, role)
        if selected is None:
            return None
        selected_characters.append(selected[0])
        selected_confidences.append(selected[1])

    text = "".join(selected_characters)
    if re.fullmatch(r"[0-9]+\[(?:[0-9]{1,2}|100)\.[0-9]{2}%\]", text) is None:
        return None
    return text, float(np.mean(selected_confidences))


def _pixel_font_exp_alternative_candidates(
    alternatives: list[list[tuple[str, float]]],
    segments: list[np.ndarray],
    layout: dict[str, int],
    open_index: int,
) -> list[tuple[str, float]]:
    if open_index <= 0:
        return []

    base_digits: list[str] = []
    base_confidences: list[float] = []
    variant_positions: list[tuple[int, list[tuple[str, float]]]] = []
    for index in range(open_index):
        glyph_alternatives = _pixel_font_digit_alternatives(alternatives[index], decimal_digit=False, glyph_mask=segments[index])
        if not glyph_alternatives:
            return []
        best_digit, best_confidence = glyph_alternatives[0]
        base_digits.append(best_digit)
        base_confidences.append(best_confidence)
        kept = _pixel_font_exp_digit_alternatives(glyph_alternatives)
        if len(kept) > 1:
            variant_positions.append((index, kept))

    if not variant_positions:
        return []
    variant_positions.sort(key=lambda item: item[1][0][1] - item[1][1][1])
    variant_positions = variant_positions[:EXP_PIXEL_FONT_EXP_MAX_ALTERNATIVE_POSITIONS]

    fixed_tail: list[str] = []
    fixed_tail_confidences: list[float] = []
    role_by_index = {
        layout["open"]: "[",
        layout["dot"]: ".",
        layout["percent"]: "%",
        layout["close"]: "]",
    }
    for index in range(open_index, len(alternatives)):
        role = role_by_index.get(index, "digit")
        selected = _first_character_alternative(
            alternatives[index],
            str.isdigit if role == "digit" else lambda character, expected=role: character == expected,
        )
        if selected is None:
            return []
        fixed_tail.append(selected[0])
        fixed_tail_confidences.append(selected[1])

    results: list[tuple[str, float]] = []
    base_by_index = {index: [(base_digits[index], base_confidences[index])] for index in range(open_index)}
    for index, kept in variant_positions:
        base_by_index[index] = kept

    for replacement in itertools.product(*(base_by_index[index] for index in range(open_index))):
        candidate_digits = [character for character, _confidence in replacement]
        text = "".join(candidate_digits + fixed_tail)
        if re.fullmatch(r"[0-9]+\[(?:[0-9]{1,2}|100)\.[0-9]{2}%\]", text) is None:
            continue
        confidences = [confidence for _character, confidence in replacement] + fixed_tail_confidences
        results.append((text, float(np.mean(confidences))))
        if len(results) >= EXP_PIXEL_FONT_EXP_MAX_ALTERNATIVE_CANDIDATES:
            break
    return results


def _pixel_font_exp_digit_alternatives(digit_alternatives: list[tuple[str, float]]) -> list[tuple[str, float]]:
    if not digit_alternatives:
        return []
    best_confidence = digit_alternatives[0][1]
    kept = [
        item
        for item in digit_alternatives
        if item[1] >= best_confidence - EXP_PIXEL_FONT_EXP_ALTERNATIVE_SCORE_WINDOW
    ]
    kept_characters = {character for character, _confidence in kept}
    if not {"0", "3"}.issubset(kept_characters):
        return kept[:1]
    if kept[0][0] not in ("0", "3") and max(
        confidence for character, confidence in kept if character in ("0", "3")
    ) < best_confidence - 0.03:
        return kept[:1]
    return kept[:EXP_PIXEL_FONT_PERCENT_MAX_ALTERNATIVES]


def _first_character_alternative(alternatives: list[tuple[str, float]], predicate) -> tuple[str, float] | None:
    for character, confidence in alternatives:
        if predicate(character):
            return character, confidence
    return None


def _bar_guided_pixel_font_percent_candidates(
    characters: list[str],
    alternatives: list[list[tuple[str, float]]],
    segments: list[np.ndarray],
    bar_percent: float | None,
) -> list[tuple[str, float]]:
    if bar_percent is None:
        return []
    try:
        open_index = characters.index("[")
        dot_index = characters.index(".", open_index + 1)
        percent_index = characters.index("%", dot_index + 1)
        close_index = characters.index("]", percent_index + 1)
    except ValueError:
        return []
    if close_index != len(characters) - 1 or percent_index - dot_index != 3:
        return []

    digit_indices = [
        index
        for index in range(open_index + 1, percent_index)
        if index != dot_index
    ]
    if len(digit_indices) not in (3, 4):
        return []

    per_digit_alternatives: list[list[tuple[str, float]]] = []
    for index in digit_indices:
        decimal_digit = dot_index < index < percent_index
        digit_alternatives = _pixel_font_digit_alternatives(alternatives[index], decimal_digit=decimal_digit, glyph_mask=segments[index])
        if not digit_alternatives:
            return []
        per_digit_alternatives.append(_pixel_font_percent_digit_alternatives(digit_alternatives))

    results: list[tuple[str, float]] = []
    for replacement in itertools.product(*per_digit_alternatives):
        candidate_chars = list(characters)
        for index, (character, _confidence) in zip(digit_indices, replacement):
            candidate_chars[index] = character
        text = "".join(candidate_chars)
        match = re.fullmatch(r"[0-9]+\[((?:[0-9]{1,2}|100)\.[0-9]{2})%\]", text)
        if match is None:
            continue
        percent = float(match.group(1))
        if abs(percent - bar_percent) > EXP_PIXEL_FONT_RECOGNIZER_BAR_PERCENT_TOLERANCE:
            continue
        selected_confidences = [item[0][1] for item in alternatives]
        for index, (_character, confidence) in zip(digit_indices, replacement):
            selected_confidences[index] = confidence
        # Bar-guided alternatives are useful fallback candidates, but the visible
        # percent text remains primary when the direct glyph sequence is valid.
        results.append((text, max(0.0, float(np.mean(selected_confidences)) - 0.004)))
    return results


def _pixel_font_digit_alternatives(
    alternatives: list[tuple[str, float]],
    *,
    decimal_digit: bool,
    glyph_mask: np.ndarray,
) -> list[tuple[str, float]]:
    digits = {character: confidence for character, confidence in alternatives if character.isdigit()}
    if not decimal_digit and "0" in digits and "3" in digits:
        best_character, best_confidence = max(digits.items(), key=lambda item: item[1])
        if best_character in ("0", "3") or max(digits["0"], digits["3"]) >= best_confidence - 0.03:
            features = _experience_pixel_font_glyph_features(glyph_mask)
            preference = None if features is None else _experience_pixel_font_zero_three_preference(features)
            if preference == best_character:
                digits[preference] = min(1.0, best_confidence + EXP_PIXEL_FONT_ZERO_THREE_TOPOLOGY_BONUS * 0.25)
    return sorted(digits.items(), key=lambda item: item[1], reverse=True)


def _pixel_font_percent_digit_alternatives(digit_alternatives: list[tuple[str, float]]) -> list[tuple[str, float]]:
    if not digit_alternatives:
        return []
    best_confidence = digit_alternatives[0][1]
    kept = [
        item
        for item in digit_alternatives
        if item[1] >= best_confidence - EXP_PIXEL_FONT_PERCENT_ALTERNATIVE_SCORE_WINDOW
    ]
    return kept[:EXP_PIXEL_FONT_PERCENT_MAX_ALTERNATIVES]


def _experience_pixel_font_zero_three_preference(features: dict[str, float]) -> str | None:
    left_stroke = (features["left_edge"] + features["upper_left_edge"] + features["lower_left_edge"]) / 3.0
    right_stroke = (features["right_edge"] + features["upper_right_edge"] + features["lower_right_edge"]) / 3.0
    zero_score = (
        left_stroke * 0.45
        + min(features["upper_left_edge"], features["lower_left_edge"]) * 0.25
        + features["left_mid_edge"] * 0.15
        + min(features["top"], features["bot"]) * 0.10
        + (1.0 - abs(left_stroke - right_stroke)) * 0.05
    )
    three_score = (
        right_stroke * 0.30
        + max(features["upper_right_edge"], features["lower_right_edge"]) * 0.20
        + (1.0 - left_stroke) * 0.25
        + (1.0 - features["left_mid_edge"]) * 0.15
        + features["mid"] * 0.10
    )
    if zero_score - three_score >= EXP_PIXEL_FONT_ZERO_THREE_TOPOLOGY_MARGIN:
        return "0"
    if three_score - zero_score >= EXP_PIXEL_FONT_ZERO_THREE_TOPOLOGY_MARGIN:
        return "3"
    return None


def _experience_pixel_font_glyph_alternatives(glyph_mask: np.ndarray) -> list[tuple[str, float]]:
    character, confidence = _classify_experience_pixel_font_glyph(glyph_mask)
    template_alternatives = _experience_pixel_font_template_alternatives(glyph_mask)
    combined: dict[str, float] = {}
    if character:
        combined[character] = max(combined.get(character, -1.0), confidence)
    for template_character, template_confidence in template_alternatives:
        combined[template_character] = max(combined.get(template_character, -1.0), template_confidence)
    features = _experience_pixel_font_glyph_features(glyph_mask)
    if features is not None:
        total_weight = sum(EXP_PIXEL_FONT_FEATURE_WEIGHTS.values())
        for digit, prototype in EXP_PIXEL_FONT_DIGIT_PROTOTYPES.items():
            distance = sum(
                EXP_PIXEL_FONT_FEATURE_WEIGHTS[key] * abs(features[key] - prototype[key])
                for key in EXP_PIXEL_FONT_FEATURE_WEIGHTS
            ) / total_weight
            digit_confidence = max(0.0, min(0.95, 1.0 - distance * 2.4))
            combined[digit] = max(combined.get(digit, -1.0), digit_confidence)
    if not combined:
        return []
    ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)
    best_confidence = ranked[0][1]
    return [
        (glyph_character, glyph_confidence)
        for glyph_character, glyph_confidence in ranked
        if glyph_confidence >= 0.50 or best_confidence - glyph_confidence <= 0.25
    ]


def _experience_pixel_font_template_alternatives(glyph_mask: np.ndarray) -> list[tuple[str, float]]:
    templates = _experience_pixel_font_templates()
    if not templates:
        return []
    normalized = _normalize_experience_pixel_font_template(glyph_mask)
    if normalized is None:
        return []
    results: list[tuple[str, float]] = []
    for character, character_templates in templates.items():
        best_score = max(_experience_pixel_font_template_score(normalized, template) for template in character_templates)
        if best_score >= 0.34:
            results.append((character, min(0.98, best_score)))
    return sorted(results, key=lambda item: item[1], reverse=True)[:8]


def _experience_pixel_font_templates() -> dict[str, list[np.ndarray]]:
    global _EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE
    if _EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE is not None:
        return _EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE

    templates: dict[str, list[np.ndarray]] = {}
    try:
        from .experience_pixel_templates import TEMPLATES
    except Exception:
        _EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE = templates
        return templates

    for character, encoded_templates in TEMPLATES.items():
        for encoded in encoded_templates:
            if not isinstance(encoded, str):
                continue
            rows = [row for row in encoded.split("/") if row]
            if not rows:
                continue
            templates.setdefault(character, []).append(np.array([[value == "1" for value in row] for row in rows], dtype=bool))
    _EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE = templates
    return templates


def _experience_pixel_font_templates_from_fixture(
    fixture_dir: Path,
    *,
    sample_ids: set[str] | None = None,
) -> dict[str, list[np.ndarray]]:
    manifest_path = fixture_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    templates: dict[str, list[np.ndarray]] = {}
    for sample in manifest.get("samples", []):
        if sample_ids is not None and sample.get("id") not in sample_ids:
            continue
        text = sample.get("text")
        filename = sample.get("file")
        if not isinstance(text, str) or not isinstance(filename, str):
            continue
        image = cv2.imread(str(fixture_dir / filename), cv2.IMREAD_UNCHANGED)
        if image is None:
            continue
        mask = _experience_pixel_font_mask(image)
        segments = _experience_pixel_font_segments(mask)
        if len(segments) != len(text):
            continue
        for character, segment in zip(text, segments):
            if character not in "0123456789[]%.":
                continue
            normalized = _normalize_experience_pixel_font_template(segment)
            if normalized is None:
                continue
            templates.setdefault(character, []).append(normalized)
    return templates


def _encode_experience_pixel_font_template(template: np.ndarray) -> str:
    return "/".join("".join("1" if value else "0" for value in row) for row in template.astype(bool))


def _normalize_experience_pixel_font_template(glyph_mask: np.ndarray) -> np.ndarray | None:
    rows = np.flatnonzero(glyph_mask.any(axis=1))
    columns = np.flatnonzero(glyph_mask.any(axis=0))
    if rows.size == 0 or columns.size == 0:
        return None
    cropped = glyph_mask[rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
    height, width = cropped.shape
    if height <= 0 or width <= 0:
        return None
    target_height, target_width = EXP_PIXEL_FONT_TEMPLATE_SIZE
    scale = min(target_width / width, target_height / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    resized = cv2.resize(
        cropped.astype(np.uint8),
        (resized_width, resized_height),
        interpolation=cv2.INTER_NEAREST,
    ).astype(bool)
    canvas = np.zeros((target_height, target_width), dtype=bool)
    top = (target_height - resized_height) // 2
    left = (target_width - resized_width) // 2
    canvas[top : top + resized_height, left : left + resized_width] = resized
    return canvas


def _experience_pixel_font_template_score(candidate: np.ndarray, template: np.ndarray) -> float:
    intersection = int(np.logical_and(candidate, template).sum())
    union = int(np.logical_or(candidate, template).sum())
    total = int(candidate.sum() + template.sum())
    if union <= 0 or total <= 0:
        return 0.0
    iou = intersection / union
    dice = 2.0 * intersection / total
    return float(iou * 0.45 + dice * 0.55)


def _experience_pixel_font_mask(image: np.ndarray) -> np.ndarray:
    source = prepare_experience_binary_source_image(image)
    mask = _clean_experience_text_mask(_experience_binary_text_mask(source))
    if mask.size == 0 or not mask.any():
        return mask
    row_runs = _boolean_runs(mask.mean(axis=1) >= EXP_OCR_TEXT_ROW_MIN_RATIO)
    if not row_runs:
        return mask
    top, bottom = max(
        row_runs,
        key=lambda run: (int(mask[run[0] : run[1], :].sum()), run[1] - run[0], run[1]),
    )
    mask = mask[top:bottom, :]
    column_runs = _boolean_runs(mask.mean(axis=0) >= 0.01)
    if not column_runs:
        return mask
    return mask[:, column_runs[0][0] : column_runs[-1][1]]


def _experience_pixel_font_segments(mask: np.ndarray) -> list[np.ndarray]:
    if mask.size == 0 or not mask.any():
        return []
    column_runs = _boolean_runs(mask.mean(axis=0) >= 0.01)
    if not column_runs:
        return []
    merged_runs = _merge_experience_pixel_font_column_runs(column_runs)
    segments: list[np.ndarray] = []
    for start, end in merged_runs:
        glyph_mask = mask[:, start:end]
        if end - start >= 2 and int(glyph_mask.sum()) >= 3:
            segments.append(glyph_mask)
    return segments


def _merge_experience_pixel_font_column_runs(column_runs: list[tuple[int, int]]) -> list[list[int]]:
    if 10 <= len(column_runs) <= 18:
        return [[start, end] for start, end in column_runs]
    merged: list[list[int]] = []
    for start, end in column_runs:
        if merged and start - merged[-1][1] <= 2:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    while len(merged) > 18:
        compacted: list[list[int]] = []
        index = 0
        changed = False
        while index < len(merged):
            start, end = merged[index]
            width = end - start
            if width <= 5 and index + 1 < len(merged) and merged[index + 1][0] - end <= 3:
                compacted.append([start, merged[index + 1][1]])
                index += 2
                changed = True
            elif width <= 5 and compacted and start - compacted[-1][1] <= 3:
                compacted[-1][1] = end
                index += 1
                changed = True
            else:
                compacted.append([start, end])
                index += 1
        merged = compacted
        if not changed:
            break
    return merged


def _classify_experience_pixel_font_glyph(glyph_mask: np.ndarray) -> tuple[str, float]:
    features = _experience_pixel_font_glyph_features(glyph_mask)
    if features is None:
        return "", 0.0
    width = features["width"]
    height = features["height"]
    aspect = width / max(1.0, height)
    area = features["area"]
    if height <= 9 and width <= 8:
        return ".", 0.92
    if height >= 36 and aspect <= 0.35:
        if features["ul"] >= 0.55 and features["ll"] >= 0.45 and features["ur"] <= 0.20 and features["lr"] <= 0.25:
            return "[", 0.90
        if features["ur"] >= 0.55 and features["lr"] >= 0.45 and features["ul"] <= 0.20 and features["ll"] <= 0.25:
            return "]", 0.90
    if height < 36 and aspect <= 0.35 and features["ur"] >= 0.35 and features["ll"] <= 0.05:
        return "1", 0.88
    if aspect >= 0.85 and area <= 0.30 and features["mid"] <= 0.34:
        return "%", 0.85

    best_digit = ""
    best_distance = float("inf")
    total_weight = sum(EXP_PIXEL_FONT_FEATURE_WEIGHTS.values())
    for digit, prototype in EXP_PIXEL_FONT_DIGIT_PROTOTYPES.items():
        distance = sum(
            EXP_PIXEL_FONT_FEATURE_WEIGHTS[key] * abs(features[key] - prototype[key])
            for key in EXP_PIXEL_FONT_FEATURE_WEIGHTS
        ) / total_weight
        if distance < best_distance:
            best_distance = distance
            best_digit = digit
    confidence = max(0.0, min(0.95, 1.0 - best_distance * 2.4))
    return best_digit, confidence


def _experience_pixel_font_glyph_features(glyph_mask: np.ndarray) -> dict[str, float] | None:
    rows = np.flatnonzero(glyph_mask.any(axis=1))
    columns = np.flatnonzero(glyph_mask.any(axis=0))
    if rows.size == 0 or columns.size == 0:
        return None
    cropped = glyph_mask[rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
    height, width = cropped.shape

    def density(row_start: int, row_end: int, col_start: int, col_end: int) -> float:
        row_start = max(0, min(height, row_start))
        row_end = max(0, min(height, row_end))
        col_start = max(0, min(width, col_start))
        col_end = max(0, min(width, col_end))
        if row_end <= row_start or col_end <= col_start:
            return 0.0
        return float(cropped[row_start:row_end, col_start:col_end].mean())

    return {
        "top": density(0, max(1, round(height * 0.22)), 0, width),
        "mid": density(round(height * 0.40), round(height * 0.62), 0, width),
        "bot": density(round(height * 0.78), height, 0, width),
        "ul": density(0, round(height * 0.50), 0, max(1, round(width * 0.32))),
        "ur": density(0, round(height * 0.50), round(width * 0.68), width),
        "ll": density(round(height * 0.50), height, 0, max(1, round(width * 0.32))),
        "lr": density(round(height * 0.50), height, round(width * 0.68), width),
        "left_edge": density(0, height, 0, max(1, round(width * 0.20))),
        "right_edge": density(0, height, round(width * 0.80), width),
        "upper_left_edge": density(round(height * 0.15), round(height * 0.45), 0, max(1, round(width * 0.25))),
        "upper_right_edge": density(round(height * 0.15), round(height * 0.45), round(width * 0.75), width),
        "left_mid_edge": density(round(height * 0.38), round(height * 0.62), 0, max(1, round(width * 0.25))),
        "right_mid_edge": density(round(height * 0.38), round(height * 0.62), round(width * 0.75), width),
        "lower_left_edge": density(round(height * 0.55), round(height * 0.85), 0, max(1, round(width * 0.25))),
        "lower_right_edge": density(round(height * 0.55), round(height * 0.85), round(width * 0.75), width),
        "inner": density(round(height * 0.25), round(height * 0.75), round(width * 0.25), round(width * 0.75)),
        "area": float(cropped.mean()),
        "height": float(height),
        "width": float(width),
    }


def experience_ocr_learning_pending_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "MapleStar" / "experience_ocr_pending"
    return Path.cwd() / ".maplestar" / "experience_ocr_pending"


def _experience_ocr_learning_trigger_for_reading(reading: ExperienceTextReading) -> str:
    if reading.continuity_status == "incompatible" or reading.reason == "EXP OCR 連續性不可信":
        return "ocr_continuity_rejected"
    return "ocr_failure"


def save_experience_ocr_learning_case(
    image_frames: Iterable[Iterable[np.ndarray | ExperienceOcrImage]],
    *,
    trigger: str,
    pixel_reading: ExperienceTextReading | None,
    paddle_reading: ExperienceTextReading | None,
    final_reading: ExperienceTextReading | None,
    bar_percent: float | None = None,
) -> str:
    try:
        materialized_frames = [
            [_coerce_experience_ocr_image(image) for image in images]
            for images in image_frames
        ]
        if not _experience_ocr_learning_has_visual_content(materialized_frames):
            return ""
        if not _experience_ocr_learning_is_actionable_exp_case(
            materialized_frames,
            bar_percent=bar_percent,
            pixel_reading=pixel_reading,
            paddle_reading=paddle_reading,
            final_reading=final_reading,
        ):
            return ""
        image_hashes = _experience_ocr_learning_image_hashes(materialized_frames)
        reading_key = _experience_ocr_learning_reading_key(final_reading, paddle_reading, pixel_reading)
        pixel_reason = "" if pixel_reading is None else pixel_reading.reason
        dedupe_key = _experience_ocr_learning_dedupe_key(
            trigger=trigger,
            reading_key=reading_key,
            pixel_reason=pixel_reason,
            image_hashes=image_hashes,
        )
        pending_dir = experience_ocr_learning_pending_dir()
        pending_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        existing_case_id = _find_existing_experience_ocr_learning_case(
            pending_dir,
            dedupe_key=dedupe_key,
            trigger=trigger,
            reading_key=reading_key,
            pixel_reason=pixel_reason,
        )
        if existing_case_id:
            return existing_case_id

        case_prefix = f"exp-{now:%Y%m%d}"
        existing_numbers = []
        for existing in pending_dir.glob(f"{case_prefix}-*"):
            match = re.fullmatch(rf"{re.escape(case_prefix)}-(\d+)", existing.name)
            if match is not None:
                existing_numbers.append(int(match.group(1)))
        case_id = f"{case_prefix}-{(max(existing_numbers, default=0) + 1):03d}"
        case_dir = pending_dir / case_id
        while case_dir.exists():
            next_number = int(case_dir.name.rsplit("-", 1)[-1]) + 1
            case_dir = pending_dir / f"{case_prefix}-{next_number:03d}"
        case_dir.mkdir(parents=True, exist_ok=False)

        metadata: dict[str, Any] = {
            "id": case_dir.name,
            "created_at": now.isoformat(timespec="seconds"),
            "trigger": trigger,
            "bar_percent": bar_percent,
            "pixel_reading": _experience_reading_metadata(pixel_reading),
            "paddle_reading": _experience_reading_metadata(paddle_reading),
            "final_reading": _experience_reading_metadata(final_reading),
            "dedupe_key": dedupe_key,
            "reading_key": reading_key,
            "pixel_reason": pixel_reason,
            "image_hashes": image_hashes,
            "frames": [],
        }

        for frame_index, images in enumerate(materialized_frames):
            frame_items: list[dict[str, Any]] = []
            for image_index, image in enumerate(images):
                ocr_image = image
                roi_name = f"frame{frame_index}_roi{image_index}_{ocr_image.source_id or 'roi'}.png"
                roi_path = case_dir / roi_name
                cv2.imwrite(str(roi_path), ocr_image.image)
                attempts = []
                for attempt_index, attempt in enumerate(_experience_pixel_font_attempts(ocr_image)[:EXP_PIXEL_LEARNING_MAX_ATTEMPTS_SAVED]):
                    attempt_bar = estimate_experience_bar_percent(
                        attempt.image,
                        bar_crop_left_ratio=attempt.bar_crop_left_ratio,
                    )
                    effective_bar = bar_percent if bar_percent is not None else attempt_bar
                    candidates = _decode_experience_pixel_font_text_candidates(attempt.image, bar_percent=effective_bar)
                    attempt_name = f"frame{frame_index}_roi{image_index}_attempt{attempt_index}_{attempt.preprocess_variant}.png"
                    cv2.imwrite(str(case_dir / attempt_name), attempt.image)
                    mask = _experience_pixel_font_mask(attempt.image)
                    mask_name = f"frame{frame_index}_roi{image_index}_attempt{attempt_index}_{attempt.preprocess_variant}_mask.png"
                    cv2.imwrite(str(case_dir / mask_name), mask.astype(np.uint8) * 255)
                    segments = []
                    for segment_index, segment in enumerate(_experience_pixel_font_segments(mask)):
                        segment_name = (
                            f"frame{frame_index}_roi{image_index}_attempt{attempt_index}_"
                            f"{attempt.preprocess_variant}_segment{segment_index}.png"
                        )
                        cv2.imwrite(str(case_dir / segment_name), segment.astype(np.uint8) * 255)
                        segments.append(
                            {
                                "file": segment_name,
                                "shape": list(segment.shape),
                            }
                        )
                    attempts.append(
                        {
                            "file": attempt_name,
                            "mask_file": mask_name,
                            "variant": attempt.preprocess_variant,
                            "offset": list(attempt.roi_offset),
                            "bar_percent": effective_bar,
                            "segments": segments,
                            "candidates": [
                                {"text": text, "confidence": confidence}
                                for text, confidence in candidates[:6]
                            ],
                        }
                    )
                frame_items.append(
                    {
                        "file": roi_name,
                        "source_id": ocr_image.source_id,
                        "bar_crop_left_ratio": ocr_image.bar_crop_left_ratio,
                        "roi_offset": list(ocr_image.roi_offset),
                        "preprocess_variant": ocr_image.preprocess_variant,
                        "attempt_id": ocr_image.attempt_id,
                        "attempts": attempts,
                    }
                )
            metadata["frames"].append(frame_items)

        (case_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return case_dir.name
    except Exception:
        return ""


def _experience_ocr_learning_image_hashes(image_frames: list[list[ExperienceOcrImage]]) -> list[str]:
    hashes: list[str] = []
    for images in image_frames:
        for ocr_image in images:
            image = np.ascontiguousarray(ocr_image.image)
            digest = hashlib.sha256()
            digest.update(str(tuple(int(part) for part in image.shape)).encode("ascii"))
            digest.update(image.tobytes())
            hashes.append(digest.hexdigest())
    return hashes


def _experience_ocr_learning_has_visual_content(image_frames: list[list[ExperienceOcrImage]]) -> bool:
    for images in image_frames:
        for ocr_image in images:
            image = ocr_image.image
            if image.size == 0:
                continue
            channels = image[:, :, :3] if image.ndim == 3 else image
            if channels.size and (float(channels.max()) > 8.0 or float(channels.std()) > 1.0):
                return True
    return False


def _experience_ocr_learning_is_actionable_exp_case(
    image_frames: list[list[ExperienceOcrImage]],
    *,
    bar_percent: float | None,
    pixel_reading: ExperienceTextReading | None,
    paddle_reading: ExperienceTextReading | None,
    final_reading: ExperienceTextReading | None,
) -> bool:
    if bar_percent is not None:
        return True
    for reading in (final_reading, paddle_reading, pixel_reading):
        if reading is None:
            continue
        if reading.current_exp is not None and reading.percent is not None:
            return True
        if _best_experience_text_candidate(reading.text) is not None:
            return True
    for images in image_frames:
        for ocr_image in images:
            if _experience_ocr_learning_image_looks_like_exp_roi(ocr_image):
                return True
    return False


def _experience_ocr_learning_image_looks_like_exp_roi(ocr_image: ExperienceOcrImage) -> bool:
    image = ocr_image.image
    if image.size == 0:
        return False
    if estimate_experience_bar_percent(image, bar_crop_left_ratio=ocr_image.bar_crop_left_ratio) is not None:
        return True
    for attempt in _experience_pixel_font_attempts(ocr_image)[:EXP_PIXEL_LEARNING_MAX_ATTEMPTS_SAVED]:
        mask = _experience_pixel_font_mask(attempt.image)
        segments = _experience_pixel_font_segments(mask)
        if len(segments) < EXP_PIXEL_LEARNING_MIN_TEXT_SEGMENTS:
            continue
        candidates = _decode_experience_pixel_font_text_candidates(attempt.image, bar_percent=None)
        if any(_best_experience_text_candidate(text) is not None for text, _confidence in candidates[:6]):
            return True
    return False


def _experience_ocr_learning_reading_key(
    final_reading: ExperienceTextReading | None,
    paddle_reading: ExperienceTextReading | None,
    pixel_reading: ExperienceTextReading | None,
) -> str:
    for reading in (final_reading, paddle_reading, pixel_reading):
        if reading is None:
            continue
        if reading.current_exp is not None and reading.percent is not None:
            return f"{reading.current_exp}[{reading.percent:.2f}%]"
        compact = normalize_exp_ocr_text(reading.text)
        if compact:
            return compact
    return ""


def _experience_ocr_learning_dedupe_key(
    *,
    trigger: str,
    reading_key: str,
    pixel_reason: str,
    image_hashes: list[str],
) -> str:
    payload = {
        "trigger": trigger,
        "reading_key": reading_key,
        "pixel_reason": pixel_reason,
        "image_hashes": image_hashes,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _find_existing_experience_ocr_learning_case(
    pending_dir: Path,
    *,
    dedupe_key: str,
    trigger: str,
    reading_key: str,
    pixel_reason: str,
) -> str:
    for metadata_path in sorted(pending_dir.glob("*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if metadata.get("dedupe_key") == dedupe_key:
            return metadata_path.parent.name
        if reading_key and metadata.get("trigger") == trigger:
            metadata_reading_key = metadata.get("reading_key") or _experience_ocr_learning_metadata_reading_key(metadata)
            if metadata_reading_key == reading_key:
                return metadata_path.parent.name
    return ""


def _experience_ocr_learning_metadata_reading_key(metadata: dict[str, Any]) -> str:
    for name in ("final_reading", "paddle_reading", "pixel_reading"):
        reading = metadata.get(name) or {}
        current_exp = reading.get("current_exp")
        percent = reading.get("percent")
        if current_exp is not None and percent is not None:
            try:
                return f"{int(current_exp)}[{float(percent):.2f}%]"
            except (TypeError, ValueError):
                pass
        compact = normalize_exp_ocr_text(str(reading.get("text") or ""))
        if compact:
            return compact
    return ""


def _experience_reading_metadata(reading: ExperienceTextReading | None) -> dict[str, Any] | None:
    if reading is None:
        return None
    return {
        "success": reading.success,
        "text": reading.text,
        "confidence": reading.confidence,
        "current_exp": reading.current_exp,
        "percent": reading.percent,
        "reason": reading.reason,
        "needs_bar_percent_guard": reading.needs_bar_percent_guard,
        "bar_percent": reading.bar_percent,
        "continuity_status": reading.continuity_status,
        "source": reading.source,
    }


def reading_from_paddle_result(result: object) -> ExperienceTextReading:
    text_items = extract_paddle_text_items(result)
    text = " ".join(item_text for item_text, _score in text_items).strip()
    confidence_values = [score for _item_text, score in text_items if score is not None]
    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
    if confidence_values and confidence < EXP_OCR_MIN_SCORE:
        return ExperienceTextReading(text=text, confidence=confidence, reason="PaddleOCR 信心過低")

    candidate = _best_experience_text_candidate(text)
    if candidate is None:
        return ExperienceTextReading(
            text=text,
            confidence=confidence,
            reason=_strict_experience_parse_failure_reason(normalize_exp_ocr_text(text)),
        )
    if not confidence_values or confidence < EXP_OCR_ACCEPT_CONFIDENCE:
        return ExperienceTextReading(text=text, confidence=confidence, reason="PaddleOCR 信心未達可信門檻")
    return ExperienceTextReading(
        current_exp=candidate.current_exp,
        percent=candidate.percent,
        text=text,
        confidence=confidence,
        success=True,
        reason="OK",
        needs_bar_percent_guard=candidate.needs_bar_percent_guard,
    )


def _experience_reading_rank(reading: ExperienceTextReading, variant_index: int) -> tuple[float, float, float, float, int]:
    structure_score, exact_percent_score = _experience_text_candidate_rank(reading.text)
    return (
        structure_score,
        exact_percent_score,
        1.0 if variant_index >= 2 else 0.0,
        reading.confidence,
        -variant_index,
    )


def _selected_experience_reading_or_failure(
    successes: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
    *,
    bar_percent: float | None = None,
) -> ExperienceTextReading | None:
    if not successes:
        return None
    rank, reading = _select_best_experience_reading(successes, bar_percent=bar_percent)
    if rank[0] < EXP_OCR_MIN_STRUCTURE_SCORE:
        return ExperienceTextReading(
            text=reading.text,
            confidence=reading.confidence,
            reason="EXP OCR 結構不可信",
        )
    return reading


def _should_retry_experience_ocr(reading: ExperienceTextReading | None) -> bool:
    if reading is None:
        return True
    return reading.reason in {
        "EXP OCR 候選不一致",
        "EXP OCR 結構不可信",
        "EXP 數字解析失敗",
        "EXP 百分比解析失敗",
        "PaddleOCR 信心未達可信門檻",
        "PaddleOCR 信心過低",
    }


def _select_best_success_reading(readings: list[ExperienceTextReading]) -> ExperienceTextReading:
    return max(
        readings,
        key=lambda reading: (
            *_experience_text_candidate_rank(reading.text),
            0.0 if reading.needs_bar_percent_guard else 1.0,
            reading.confidence,
        ),
    )


def _experience_text_candidate_rank(text: str) -> tuple[float, float]:
    candidate = _best_experience_text_candidate(text)
    if candidate is None:
        return 0.0, 0.0
    return candidate.structure_score, 0.0 if candidate.repaired_percent else 1.0


def _select_best_experience_reading(
    successes: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
    *,
    bar_percent: float | None = None,
) -> tuple[tuple[float, float, float, float, int], ExperienceTextReading]:
    groups: dict[tuple[int | None, float | None], list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]]] = {}
    for item in successes:
        _rank, _variant_index, reading = item
        percent = None if reading.percent is None else round(reading.percent, 2)
        groups.setdefault((reading.current_exp, percent), []).append(item)

    trusted_nonbinary = _trusted_nonbinary_exact_success(successes)
    if trusted_nonbinary is not None:
        trusted_percent = trusted_nonbinary[2].percent
        trusted_key = (
            trusted_nonbinary[2].current_exp,
            None if trusted_percent is None else round(trusted_percent, 2),
        )
        supported_conflict = _supported_conflicting_group(groups, trusted_key, trusted_nonbinary[2].confidence)
        if supported_conflict is not None:
            conflict_rank, _variant_index, conflict_reading = max(supported_conflict, key=lambda item: item[0])
            return conflict_rank, conflict_reading
        if (
            bar_percent is None
            or trusted_percent is None
            or abs(trusted_percent - bar_percent) <= EXP_OCR_BAR_PERCENT_TOLERANCE
        ):
            return trusted_nonbinary[0], trusted_nonbinary[2]

    bar_group = _select_bar_percent_group(groups, bar_percent)
    if bar_group is not None:
        best_key, best_group = bar_group
    else:
        best_key, best_group = max(
            groups.items(),
            key=lambda item: _experience_group_score(item[1]),
        )
    best_key, best_group = _resolve_exact_percent_marker_disagreement(groups, best_key, best_group)
    resolved_group = _resolve_binary_percent_disagreement(groups, best_key, best_group)
    if resolved_group is None:
        best_item = max(best_group, key=lambda item: item[0])
        return best_item[0], ExperienceTextReading(
            text=best_item[2].text,
            confidence=best_item[2].confidence,
            reason="EXP OCR 候選不一致",
        )
    best_item = max(resolved_group, key=lambda item: item[0])
    return best_item[0], best_item[2]


def _experience_group_score(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> tuple[float, int, float, float]:
    max_confidence = max(item[2].confidence for item in group)
    is_binary_only = all(variant_index >= 2 for _rank, variant_index, _reading in group)
    variant_support_bonus = min(0.06, len(group) * 0.02)
    binary_bonus = 0.04 if is_binary_only else 0.0
    max_rank = max(group, key=lambda item: item[0])[0]
    return (max_confidence + binary_bonus + variant_support_bonus, len(group), max_rank[0], max_rank[1])


def _select_bar_percent_group(
    groups: dict[tuple[int | None, float | None], list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]]],
    bar_percent: float | None,
) -> tuple[
    tuple[int | None, float | None],
    list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
] | None:
    if bar_percent is None:
        return None
    candidates = [
        (key, group)
        for key, group in groups.items()
        if key[1] is not None and abs(key[1] - bar_percent) <= EXP_OCR_BAR_PERCENT_TOLERANCE
    ]
    if not candidates:
        return None
    closest_key, closest_group = min(
        candidates,
        key=lambda item: (
            abs((item[0][1] or 0.0) - bar_percent),
            -_experience_group_score(item[1])[0],
        ),
    )
    best_key, best_group = max(candidates, key=lambda item: _experience_group_score(item[1]))
    if closest_key == best_key:
        return closest_key, closest_group

    closest_diff = abs((closest_key[1] or 0.0) - bar_percent)
    best_diff = abs((best_key[1] or 0.0) - bar_percent)
    if (
        _experience_group_has_exact_percent_marker(best_group)
        and not _experience_group_has_exact_percent_marker(closest_group)
        and _experience_group_max_confidence(best_group) >= _experience_group_max_confidence(closest_group) - 0.08
    ):
        return best_key, best_group
    if closest_diff + 0.75 < best_diff:
        return closest_key, closest_group
    return best_key, best_group


def _trusted_nonbinary_exact_success(
    successes: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> tuple[tuple[float, float, float, float, int], int, ExperienceTextReading] | None:
    trusted = [
        item
        for item in successes
        if item[1] < 2
        and item[2].confidence >= EXP_OCR_TRUSTED_NONBINARY_EXACT_CONFIDENCE
        and _experience_text_candidate_rank(item[2].text)[1] > 0
    ]
    if not trusted:
        return None

    groups: dict[tuple[int | None, float | None], list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]]] = {}
    for item in trusted:
        reading = item[2]
        percent = None if reading.percent is None else round(reading.percent, 2)
        groups.setdefault((reading.current_exp, percent), []).append(item)
    if len(groups) != 1:
        return None
    return max(trusted, key=lambda item: item[0])


def _supported_conflicting_group(
    groups: dict[tuple[int | None, float | None], list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]]],
    trusted_key: tuple[int | None, float | None],
    trusted_confidence: float,
) -> list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]] | None:
    _trusted_exp, trusted_percent = trusted_key
    conflicts = [
        group
        for key, group in groups.items()
        if key != trusted_key
        and key[1] == trusted_percent
        and len(group) >= EXPERIENCE_BURST_CONSENSUS_MIN_COUNT
        and _experience_group_max_confidence(group) >= trusted_confidence - 0.05
    ]
    if not conflicts:
        return None
    return max(conflicts, key=_experience_group_score)


def _resolve_exact_percent_marker_disagreement(
    groups: dict[tuple[int | None, float | None], list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]]],
    best_key: tuple[int | None, float | None],
    best_group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> tuple[
    tuple[int | None, float | None],
    list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
]:
    current_exp, percent = best_key
    if current_exp is None or percent is None:
        return best_key, best_group

    best_confidence = _experience_group_max_confidence(best_group)
    exact_groups = [
        (key, group)
        for key, group in groups.items()
        if key[0] == current_exp
        and key[1] is not None
        and abs(key[1] - percent) <= EXP_OCR_REPAIRED_PERCENT_MAX_DISAGREEMENT
        and _experience_group_has_exact_percent_marker(group)
        and _experience_group_max_confidence(group) >= best_confidence - EXP_OCR_REPAIRED_PERCENT_CONFIDENCE_TOLERANCE
    ]
    if not exact_groups:
        return best_key, best_group

    exact_groups.sort(
        key=lambda item: (
            _experience_group_exact_percent_quality(item[1]),
            _experience_group_score(item[1]),
        ),
        reverse=True,
    )
    top_key, top_group = exact_groups[0]
    if top_key == best_key:
        return best_key, best_group
    if not _experience_group_has_exact_percent_marker(best_group):
        return top_key, top_group
    top_quality = _experience_group_exact_percent_quality(top_group)
    best_quality = _experience_group_exact_percent_quality(best_group)
    if top_quality > best_quality:
        return top_key, top_group
    return best_key, best_group


def _resolve_binary_percent_disagreement(
    groups: dict[tuple[int | None, float | None], list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]]],
    best_key: tuple[int | None, float | None],
    best_group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]] | None:
    current_exp, percent = best_key
    if current_exp is None or percent is None:
        return best_group
    if not _experience_group_is_binary_only(best_group):
        return best_group

    best_confidence = _experience_group_max_confidence(best_group)
    alternatives = [
        group
        for key, group in groups.items()
        if key[0] == current_exp
        and key[1] is not None
        and abs(key[1] - percent) >= 0.5
        and _experience_group_has_nonbinary_vote(group)
        and _experience_group_max_confidence(group) >= best_confidence - 0.08
    ]
    if not alternatives:
        return best_group
    original_alternatives = [
        group
        for group in alternatives
        if _experience_group_min_nonbinary_variant_index(group) == 0
    ]
    if len(original_alternatives) == 1:
        original_confidence = _experience_group_max_nonbinary_confidence(original_alternatives[0])
        if original_confidence >= best_confidence - 0.08:
            return original_alternatives[0]
    alternatives.sort(
        key=lambda group: (
            _experience_group_max_nonbinary_confidence(group),
            _experience_group_score(group),
        ),
        reverse=True,
    )
    if len(alternatives) == 1:
        return alternatives[0]
    top_confidence = _experience_group_max_nonbinary_confidence(alternatives[0])
    next_confidence = _experience_group_max_nonbinary_confidence(alternatives[1])
    if top_confidence - next_confidence >= 0.05:
        return alternatives[0]
    return None


def _experience_group_is_binary_only(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> bool:
    return all(variant_index >= 2 for _rank, variant_index, _reading in group)


def _experience_group_has_nonbinary_vote(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> bool:
    return any(variant_index < 2 for _rank, variant_index, _reading in group)


def _experience_group_has_exact_percent_marker(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> bool:
    return any(_experience_text_candidate_rank(reading.text)[1] > 0 for _rank, _variant_index, reading in group)


def _experience_group_exact_percent_quality(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> tuple[float, float]:
    return max(
        (
            _experience_text_candidate_rank(reading.text)[0],
            reading.confidence,
        )
        for _rank, _variant_index, reading in group
        if _experience_text_candidate_rank(reading.text)[1] > 0
    )


def _experience_group_max_confidence(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> float:
    return max(reading.confidence for _rank, _variant_index, reading in group)


def _experience_group_max_nonbinary_confidence(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> float:
    return max(
        (reading.confidence for _rank, variant_index, reading in group if variant_index < 2),
        default=0.0,
    )


def _experience_group_min_nonbinary_variant_index(
    group: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]],
) -> int | None:
    indexes = [variant_index for _rank, variant_index, _reading in group if variant_index < 2]
    return min(indexes) if indexes else None


def _experience_text_structure_score(text: str) -> float:
    candidate = _best_experience_text_candidate(text)
    if candidate is None:
        return 0.0
    return candidate.structure_score


def _best_experience_text_candidate(text: str) -> ExperienceTextCandidate | None:
    candidates = _experience_text_candidates(text)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: (
            candidate.structure_score,
            candidate.percent_span[1],
            -int(candidate.repaired_percent),
        ),
    )


def _experience_text_candidates(text: str) -> list[ExperienceTextCandidate]:
    compact = normalize_exp_ocr_text(text)
    if _has_spaced_experience_number_prefix(text):
        return []
    candidates: list[ExperienceTextCandidate] = []
    match = re.fullmatch(
        r"(?:EXP[:：]?)?([0-9][0-9,.]*)\[((?:[0-9]{1,2}|100)[\.,][0-9]{2})([%Xx3*147Il|JjTt;:>]*)([\]\)]*)[;:>]*",
        compact,
        flags=re.IGNORECASE,
    )
    if match is not None:
        exp_segment = match.group(1)
        if _exp_number_separators_are_valid(exp_segment):
            exp_digits = "".join(char for char in exp_segment if char.isdigit())
            percent = float(match.group(2).replace(",", "."))
            tail = match.group(3)
            closers = match.group(4)
            if (
                exp_digits
                and 0.0 <= percent <= 100.0
                and len(tail) <= 3
                and (tail or closers)
            ):
                candidates.append(
                    ExperienceTextCandidate(
                        current_exp=int(exp_digits),
                        percent=percent,
                        percent_span=match.span(2),
                        structure_score=5.0 + min(len(exp_digits), 8) / 10.0,
                        repaired_percent=tail not in ("", "%"),
                    )
                )
    candidates.extend(_missing_open_bracket_experience_text_candidates(compact))
    candidates.extend(_merged_exp_percent_text_candidates(compact))
    return candidates


def _has_spaced_experience_number_prefix(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    return re.search(r"\d\s+\d[0-9\s,.]*[\[\(]", normalized) is not None


def _missing_open_bracket_experience_text_candidates(compact: str) -> list[ExperienceTextCandidate]:
    if "[" in compact or "(" in compact:
        return []
    match = re.fullmatch(
        r"(?:EXP[:：]?)?([0-9][0-9,.]*)([%Xx3*147Il|JjTt;:>]+)([\]\)])[;:>]*",
        compact,
        flags=re.IGNORECASE,
    )
    if match is None:
        return []

    body = match.group(1)
    decimal_index = body.rfind(".")
    if decimal_index < 0 or decimal_index + 3 != len(body):
        return []
    decimals = body[decimal_index + 1 :]
    before_decimal = body[:decimal_index]
    digit_match = re.search(r"(\d{1,3})$", before_decimal)
    if digit_match is None:
        return []

    integer_digits = digit_match.group(1)
    if len(integer_digits) == 3 and int(integer_digits) > 100:
        integer_digits = integer_digits[-2:]
    elif len(integer_digits) == 3 and integer_digits != "100":
        return []

    percent = float(f"{integer_digits}.{decimals}")
    if not 10.0 <= percent <= 100.0:
        return []
    exp_segment = before_decimal[: len(before_decimal) - len(integer_digits)]
    if not _exp_number_separators_are_valid(exp_segment):
        return []
    exp_digits = "".join(char for char in exp_segment if char.isdigit())
    if len(exp_digits) < 5:
        return []
    percent_start = len(exp_segment)
    percent_span = (percent_start, len(body))
    return [
        ExperienceTextCandidate(
            current_exp=int(exp_digits),
            percent=percent,
            percent_span=percent_span,
            structure_score=4.3 + min(len(exp_digits), 8) / 10.0,
            repaired_percent=True,
        )
    ]


def _merged_exp_percent_text_candidates(compact: str) -> list[ExperienceTextCandidate]:
    body = re.sub(r"^EXP[:：]?", "", compact, flags=re.IGNORECASE)
    if any(char in body for char in "[]()%Xx"):
        return []
    match = re.fullmatch(r"([0-9]{5,})([0-9]{2})[\.,]([0-9]{2})", body)
    if match is None:
        return []

    exp_digits = match.group(1)
    percent_integer = int(match.group(2))
    percent = float(f"{percent_integer}.{match.group(3)}")
    if not 10.0 <= percent <= 99.99:
        return []
    candidates: list[ExperienceTextCandidate] = []
    if exp_digits.endswith("1") and len(exp_digits) >= 6:
        repaired_exp_digits = exp_digits[:-1]
        candidates.append(
            ExperienceTextCandidate(
                current_exp=int(repaired_exp_digits),
                percent=percent,
                percent_span=match.span(2),
                structure_score=4.4 + min(len(repaired_exp_digits), 8) / 10.0,
                repaired_percent=True,
                needs_bar_percent_guard=True,
            )
        )
    candidates.append(
        ExperienceTextCandidate(
            current_exp=int(exp_digits),
            percent=percent,
            percent_span=match.span(2),
            structure_score=3.6 + min(len(exp_digits), 8) / 10.0,
            repaired_percent=True,
            needs_bar_percent_guard=True,
        )
    )
    return candidates


def _strict_experience_parse_failure_reason(text: str) -> str:
    if "[" not in text:
        return "EXP 百分比解析失敗"
    if re.search(r"\[(?:[0-9]{1,2}|100)[\.,][0-9]{2}[%Xx3*147Il|JjTt;:>]{0,3}[\]\)]*[;:>]*", text) is None:
        return "EXP 百分比解析失敗"
    return "EXP 數字解析失敗"


def resize_experience_text_crop(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0 or height >= EXP_OCR_TARGET_HEIGHT:
        return image
    scale = EXP_OCR_TARGET_HEIGHT / height
    return cv2.resize(
        image,
        (max(1, round(width * scale)), EXP_OCR_TARGET_HEIGHT),
        interpolation=cv2.INTER_CUBIC,
    )


def crop_experience_text_image(image: np.ndarray) -> np.ndarray:
    text_mask = _clean_experience_text_mask(_experience_text_mask(image))
    text_ratio = float(text_mask.mean())
    if not EXP_OCR_TEXT_MIN_RATIO <= text_ratio <= EXP_OCR_TEXT_MAX_RATIO:
        return image

    row_has_text = text_mask.mean(axis=1) >= EXP_OCR_TEXT_ROW_MIN_RATIO
    row_runs = _boolean_runs(row_has_text)
    if not row_runs:
        return image

    image_height, image_width = text_mask.shape
    best_top, best_bottom = max(
        row_runs,
        key=lambda run: (
            int(text_mask[run[0] : run[1], :].sum()),
            run[1],
        ),
    )
    row_padding = max(2, round((best_bottom - best_top) * EXP_OCR_TEXT_CROP_PADDING_RATIO))
    crop_top = max(0, best_top - row_padding)
    crop_bottom = min(image_height, best_bottom + row_padding)

    band_mask = text_mask[crop_top:crop_bottom, :]
    column_has_text = band_mask.mean(axis=0) >= EXP_OCR_TEXT_COLUMN_MIN_RATIO
    column_runs = _boolean_runs(column_has_text)
    if not column_runs:
        return image[crop_top:crop_bottom, :]

    best_left, best_right = _merged_text_columns(column_runs, image_width)
    column_padding = max(4, round((best_right - best_left) * EXP_OCR_TEXT_CROP_PADDING_RATIO))
    crop_left = max(0, best_left - column_padding)
    crop_right = min(image_width, best_right + column_padding)
    return image[crop_top:crop_bottom, crop_left:crop_right]


def _binarize_experience_text(image: np.ndarray, *, text_expansion_iterations: int = 1) -> np.ndarray | None:
    text_mask = _clean_experience_text_mask(_experience_binary_text_mask(image))
    text_ratio = float(text_mask.mean())
    if not EXP_OCR_TEXT_MIN_RATIO <= text_ratio <= EXP_OCR_TEXT_BINARY_MAX_RATIO:
        return None

    black_text_on_white = np.full(text_mask.shape, 255, dtype=np.uint8)
    black_text_on_white[text_mask] = 0
    kernel = np.ones((2, 2), dtype=np.uint8)
    if text_expansion_iterations > 0:
        black_text_on_white = cv2.erode(
            black_text_on_white,
            kernel,
            iterations=text_expansion_iterations,
        )
    return cv2.cvtColor(black_text_on_white, cv2.COLOR_GRAY2BGR)


def _experience_text_mask(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3].astype(np.float32)
    blue = bgr[:, :, 0]
    green = bgr[:, :, 1]
    red = bgr[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    return (luminance >= 130.0) & (chroma <= 65.0)


def _experience_binary_text_mask(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3].astype(np.float32)
    blue = bgr[:, :, 0]
    green = bgr[:, :, 1]
    red = bgr[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    return (luminance >= EXP_OCR_BINARY_LUMINANCE_MIN) & (chroma <= EXP_OCR_BINARY_MAX_CHROMA)


def _clean_experience_text_mask(mask: np.ndarray) -> np.ndarray:
    if mask.size == 0:
        return mask
    cleaned = mask.copy()
    _remove_experience_top_border_noise(cleaned)
    row_density = cleaned.mean(axis=1)
    dense_runs = _boolean_runs(row_density >= EXP_OCR_DENSE_BORDER_ROW_MAX_RATIO)
    midpoint = cleaned.shape[0] / 2
    for start, end in dense_runs:
        run_center = (start + end) / 2
        if run_center < midpoint:
            top = max(0, start - EXP_OCR_DENSE_BORDER_ROW_PADDING)
            bottom = end
        else:
            top = max(0, start - EXP_OCR_DENSE_BORDER_ROW_PADDING)
            bottom = min(cleaned.shape[0], end + EXP_OCR_DENSE_BORDER_ROW_PADDING)
        cleaned[top:bottom, :] = False
    return cleaned


def _remove_experience_top_border_noise(mask: np.ndarray) -> None:
    if mask.size == 0:
        return
    top_limit = max(1, round(mask.shape[0] * EXP_OCR_TOP_BORDER_MAX_HEIGHT_RATIO))
    row_density = mask[:top_limit, :].mean(axis=1)
    top_border_runs = _boolean_runs(row_density >= EXP_OCR_TOP_BORDER_ROW_MAX_RATIO)
    for start, end in top_border_runs:
        top = max(0, start - EXP_OCR_DENSE_BORDER_ROW_PADDING)
        bottom = min(mask.shape[0], end + EXP_OCR_DENSE_BORDER_ROW_PADDING)
        mask[top:bottom, :] = False


def _boolean_runs(values: np.ndarray) -> list[tuple[int, int]]:
    if values.size == 0:
        return []
    padded = np.concatenate(([False], values.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2]) if end > start]


def _merged_text_columns(column_runs: list[tuple[int, int]], image_width: int) -> tuple[int, int]:
    if not column_runs:
        return 0, image_width
    max_gap = max(6, round(image_width * 0.08))
    merged: list[list[int]] = []
    for start, end in column_runs:
        if merged and start - merged[-1][1] <= max_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    best_start, best_end = max(
        merged,
        key=lambda run: (
            run[1] - run[0],
            run[1],
        ),
    )
    return best_start, best_end


def configure_paddleocr_runtime() -> None:
    for name, value in PADDLEOCR_ENV_DEFAULTS.items():
        os.environ.setdefault(name, value)


@contextlib.contextmanager
def suppress_paddleocr_output():
    output_sink = io.StringIO()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="No ccache found.*")
        with (
            suppress_subprocess_windows(),
            suppress_process_output(),
            contextlib.redirect_stdout(output_sink),
            contextlib.redirect_stderr(output_sink),
        ):
            yield


@contextlib.contextmanager
def suppress_subprocess_windows():
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        yield
        return

    original_popen = subprocess.Popen

    def hidden_popen_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        creationflags = int(kwargs.get("creationflags", 0) or 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        kwargs["creationflags"] = creationflags

        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        return kwargs

    if isinstance(original_popen, type):
        class HiddenPopen(original_popen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **hidden_popen_kwargs(kwargs))

        replacement_popen = HiddenPopen
    else:
        def hidden_popen(*args, **kwargs):
            return original_popen(*args, **hidden_popen_kwargs(kwargs))

        replacement_popen = hidden_popen

    subprocess.Popen = replacement_popen
    try:
        yield
    finally:
        subprocess.Popen = original_popen


@contextlib.contextmanager
def suppress_process_output():
    saved_fds: list[tuple[int, int]] = []
    devnull_fd: int | None = None
    try:
        for stream in (sys.stdout, sys.stderr):
            flush = getattr(stream, "flush", None)
            if flush is not None:
                flush()
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        for fd in (1, 2):
            try:
                saved_fd = os.dup(fd)
                os.dup2(devnull_fd, fd)
                saved_fds.append((fd, saved_fd))
            except OSError:
                continue
        yield
    finally:
        for fd, saved_fd in reversed(saved_fds):
            try:
                os.dup2(saved_fd, fd)
            finally:
                os.close(saved_fd)
        if devnull_fd is not None:
            os.close(devnull_fd)


def extract_paddle_text_items(result: object) -> list[tuple[str, float | None]]:
    items: list[tuple[str, float | None]] = []
    _collect_paddle_text_items(result, items)
    return items


def _collect_paddle_text_items(value: object, items: list[tuple[str, float | None]]) -> None:
    if value is None:
        return

    json_value = getattr(value, "json", None)
    if isinstance(json_value, dict):
        _collect_paddle_text_items(json_value, items)
        return

    if isinstance(value, dict):
        if "rec_texts" in value:
            texts = value.get("rec_texts") or []
            scores = value.get("rec_scores") or []
            for index, text in enumerate(texts):
                if isinstance(text, str):
                    score = scores[index] if index < len(scores) and isinstance(scores[index], (int, float)) else None
                    items.append((text, None if score is None else float(score)))
            return
        if "text" in value and isinstance(value.get("text"), str):
            score_value = value.get("score", value.get("confidence"))
            score = float(score_value) if isinstance(score_value, (int, float)) else None
            items.append((value["text"], score))
            return
        for child in value.values():
            _collect_paddle_text_items(child, items)
        return

    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], (int, float)):
            items.append((value[0], float(value[1])))
            return
        if len(value) == 2 and isinstance(value[1], (list, tuple)) and len(value[1]) >= 2:
            text, score = value[1][0], value[1][1]
            if isinstance(text, str) and isinstance(score, (int, float)):
                items.append((text, float(score)))
                return
        for child in value:
            _collect_paddle_text_items(child, items)


def parse_current_exp_text(text: str, percent_hint: float | None = None) -> int | None:
    if not text:
        return None

    compact = normalize_exp_ocr_text(text)
    percent_match = _last_exp_percent_match(compact)
    if percent_match is not None and percent_match[1][0] > 0:
        digits = _exp_digits_before_percent(compact, percent_match[1][0])
        return int(digits) if digits else None

    digits = "".join(char for char in compact if char.isdigit())
    if percent_hint is not None:
        suffix_lengths = _percent_digit_suffix_lengths(percent_hint)
        for suffix_length in suffix_lengths:
            if len(digits) > suffix_length:
                return int(digits[:-suffix_length])

    prefix_digits = []
    for char in compact:
        if char.isdigit():
            prefix_digits.append(char)
            continue
        if prefix_digits:
            break
    if prefix_digits and len(prefix_digits) != sum(char.isdigit() for char in compact):
        return int("".join(prefix_digits))

    if not digits:
        return None
    return int(digits)


def parse_exp_percent_text(text: str) -> float | None:
    if not text:
        return None
    match = _last_exp_percent_match(normalize_exp_ocr_text(text))
    return None if match is None else match[0]


def normalize_exp_ocr_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    translation = str.maketrans(
        {
            "％": "%",
            "﹪": "%",
            "．": ".",
            "。": ".",
            "：": ":",
            "，": ",",
            "【": "[",
            "】": "]",
            "（": "(",
            "）": ")",
            "×": "X",
            " ": "",
            "\t": "",
            "\n": "",
            "\r": "",
        }
    )
    return text.translate(translation)


def _exp_digits_before_percent(text: str, percent_start: int) -> str:
    prefix = text[:percent_start]
    exp_segment = _exp_number_segment_from_prefix(prefix)
    if exp_segment is None:
        return ""
    if (
        len(exp_segment) >= 2
        and exp_segment[-1] == "1"
        and exp_segment[-2].isdigit()
        and "[" not in prefix
        and "(" not in prefix
    ):
        exp_segment = exp_segment[:-1]
    return "".join(char for char in exp_segment if char.isdigit())


def _exp_number_segment_from_prefix(prefix: str) -> str | None:
    prefix = prefix.rstrip("[(")
    segment = _raw_exp_number_segment_from_prefix(prefix)
    noisy_segment = _raw_exp_number_segment_from_prefix(prefix, allow_closing_bracket_noise=True)
    if len(noisy_segment) > len(segment):
        segment = noisy_segment.replace("]", "").replace(")", "")
    if not segment:
        return ""

    if segment.upper().startswith("EXP"):
        segment = segment[3:]
    if not segment:
        return ""
    if any(char.isalpha() for char in segment):
        return None
    if not all(char.isdigit() or char in ",." for char in segment):
        return None
    if not _exp_number_separators_are_valid(segment):
        return None
    return segment


def _raw_exp_number_segment_from_prefix(prefix: str, *, allow_closing_bracket_noise: bool = False) -> str:
    start = len(prefix)
    while start > 0:
        char = prefix[start - 1]
        if char.isalnum() or char in ",." or (allow_closing_bracket_noise and char in "])"):
            start -= 1
            continue
        break
    return prefix[start:]


def _exp_number_separators_are_valid(segment: str) -> bool:
    if "," in segment and "." in segment:
        return False
    separator = "," if "," in segment else "." if "." in segment else ""
    if not separator:
        return segment.isdigit()

    parts = segment.split(separator)
    if len(parts[0]) < 1 or len(parts[0]) > 3:
        return False
    return all(part.isdigit() for part in parts) and all(len(part) == 3 for part in parts[1:])


def _last_exp_percent_match(text: str) -> tuple[float, tuple[int, int]] | None:
    candidates = _exp_percent_matches(text)
    if not candidates:
        return None
    percent, span, _repaired = max(
        candidates,
        key=lambda item: (
            item[1][1],
            item[1][1] - item[1][0],
            -int(item[2]),
        ),
    )
    return percent, span


def _exp_percent_matches(text: str) -> list[tuple[float, tuple[int, int], bool]]:
    structured_patterns = (
        re.compile(r"(\d{1,3})[\.,](\d{1,2})%"),
        re.compile(r"[\[\(](\d{1,3})[\.,:](\d{1,2})[\]\)]?"),
        re.compile(r"(\d{1,3})[\.:](\d{1,2})"),
    )
    matches: list[tuple[float, tuple[int, int], bool]] = []
    for pattern in structured_patterns:
        matches.extend((percent, span, False) for percent, span in _percent_matches(text, pattern))
    matches.extend(_repaired_bracket_percent_matches(text))
    if matches:
        return _unique_percent_matches(matches)

    bare_percent = re.compile(r"(?<![\d\.,])(\d{1,3})%")
    return _unique_percent_matches(
        (percent, span, False)
        for percent, span in _percent_matches(text, bare_percent)
    )


def _repaired_bracket_percent_matches(text: str) -> list[tuple[float, tuple[int, int], bool]]:
    matches: list[tuple[float, tuple[int, int], bool]] = []
    pattern = re.compile(r"[\[\(](\d{3,4})(?:[%XxTtJj\]\)]|$)")
    for start in range(len(text)):
        match = pattern.match(text, start)
        if match is None:
            continue
        digits = match.group(1)
        if len(digits) == 4:
            value = float(f"{digits[:2]}.{digits[2:]}")
        elif len(digits) == 3:
            value = float(f"{digits[:1]}.{digits[1:]}")
        else:
            continue
        if 0.0 <= value <= 100.0:
            matches.append((value, match.span(), True))
    return matches


def _unique_percent_matches(
    matches: Iterable[tuple[float, tuple[int, int], bool]],
) -> list[tuple[float, tuple[int, int], bool]]:
    unique: dict[tuple[tuple[int, int], float], tuple[float, tuple[int, int], bool]] = {}
    for percent, span, repaired in matches:
        key = (span, percent)
        existing = unique.get(key)
        if existing is None or (existing[2] and not repaired):
            unique[key] = (percent, span, repaired)
    values = list(unique.values())
    earliest_start_by_end: dict[int, int] = {}
    for _percent, span, _repaired in values:
        end = span[1]
        earliest_start_by_end[end] = min(span[0], earliest_start_by_end.get(end, span[0]))
    return [
        item
        for item in values
        if item[1][0] == earliest_start_by_end[item[1][1]]
    ]


def _percent_matches(text: str, pattern: re.Pattern[str]) -> list[tuple[float, tuple[int, int]]]:
    matches: list[tuple[float, tuple[int, int]]] = []
    for start in range(len(text)):
        match = pattern.match(text, start)
        if match is None:
            continue
        integer = match.group(1)
        decimals = match.group(2) if match.lastindex and match.lastindex >= 2 else None
        try:
            value = float(integer if decimals is None else f"{integer}.{decimals}")
        except ValueError:
            continue
        if 0.0 <= value <= 100.0:
            matches.append((value, match.span()))
    return matches


def _percent_digit_suffix_lengths(percent: float) -> list[int]:
    candidates = {
        len(f"{percent:.2f}".replace(".", "").lstrip("0")),
        len(f"{percent:.1f}".replace(".", "").lstrip("0")),
        len(f"{round(percent):.0f}"),
    }
    return sorted((value for value in candidates if value > 0), reverse=True)
