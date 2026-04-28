from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import warnings
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


EXP_SAMPLE_HISTORY_SECONDS = 3600.0
EXP_RATE_MIN_SECONDS = 5.0
EXP_RATE_5M_SECONDS = 300.0
EXP_RATE_10M_SECONDS = 600.0
EXP_RATE_1H_SECONDS = 3600.0
EXP_LEVEL_WRAP_HIGH_PERCENT = 65.0
EXP_LEVEL_WRAP_LOW_PERCENT = 35.0
EXP_OCR_MIN_SCORE = 0.45
EXP_OCR_ACCEPT_CONFIDENCE = 0.90
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
EXP_TOTAL_ESTIMATE_MAX_DEVIATION_RATIO = 0.35
EXP_SINGLE_GAIN_MAX_LEVEL_RATIO = 0.35
EXP_GAIN_EXPECTED_TOLERANCE_RATIO = 8.0
EXP_GAIN_MIN_ABSOLUTE_TOLERANCE = 5000
EXP_INITIAL_REBASE_MAX_SAMPLES = 6
EXP_GAIN_RATE_SPIKE_MULTIPLIER = 20.0
EXP_LONG_RATE_BLEND_START_SECONDS = 300.0
EXP_LONG_RATE_BLEND_FULL_SECONDS = 3600.0
PADDLEOCR_LANGUAGE = "chinese_cht"
PADDLEOCR_DETECTION_MODEL_NAME = "PP-OCRv5_mobile_det"
PADDLEOCR_RECOGNITION_MODEL_NAME = "PP-OCRv5_mobile_rec"
PADDLEOCR_MODEL_SIZE_MB = {
    PADDLEOCR_DETECTION_MODEL_NAME: 4.7,
    PADDLEOCR_RECOGNITION_MODEL_NAME: 16.0,
}
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


@dataclass
class ExperienceTextReading:
    current_exp: int | None = None
    percent: float | None = None
    text: str = ""
    confidence: float = 0.0
    success: bool = False
    reason: str = "尚未辨識"


@dataclass
class ExperienceSample:
    captured_at: float
    current_exp: int
    total_gained_exp: int
    percent: float | None


@dataclass
class ExperienceSnapshot:
    current_exp: int | None = None
    current_percent: float | None = None
    xp_per_5m: float | None = None
    xp_per_10m: float | None = None
    xp_per_hour: float | None = None
    eta_seconds: float | None = None
    sample_count: int = 0
    status: str = "尚未開始"


def format_exp(value: float | int | None) -> str:
    if value is None:
        return "--"
    return f"{round(value):,}"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--"
    total_seconds = round(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


class ExperienceEfficiencyTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.samples: list[ExperienceSample] = []
        self.last_current_exp: int | None = None
        self.total_gained_exp = 0
        self.estimated_level_total_exp: float | None = None
        self.last_snapshot: ExperienceSnapshot | None = None
        self.last_status = "等待 EXP 數字"

    def add_reading(self, now: float, current_exp: int, percent: float | None) -> bool:
        if current_exp < 0:
            self._reject_sample("EXP 數字無效")
            return False
        if percent is not None and not 0.0 <= percent <= 100.0:
            self._reject_sample(f"EXP 百分比無效：{percent:.2f}%")
            return False

        if self.last_current_exp is None:
            self.last_current_exp = current_exp
            self.samples.append(ExperienceSample(now, current_exp, self.total_gained_exp, percent))
            self._update_level_total_estimate(current_exp, percent, force=True)
            self.last_status = "校準 EXP 基準"
            return True

        delta = current_exp - self.last_current_exp
        if delta < 0:
            wrapped_delta = self._level_wrap_delta(current_exp, percent)
            if wrapped_delta is None:
                if self._can_rebase_initial_session():
                    self._restart_session(now, current_exp, percent, "基準修正：先前樣本可能誤判")
                    return True
                self._reject_sample("EXP 數字回落但不符合升級條件")
                return False
            delta = wrapped_delta
        else:
            rejection_reason = self._normal_gain_rejection_reason(now, current_exp, percent, delta)
            if rejection_reason is not None:
                if self._can_rebase_initial_session():
                    self._restart_session(now, current_exp, percent, "基準修正：先前樣本可能誤判")
                    return True
                self._reject_sample(rejection_reason)
                return False

        self.total_gained_exp += max(0, delta)
        self.last_current_exp = current_exp
        self.samples.append(ExperienceSample(now, current_exp, self.total_gained_exp, percent))
        self._update_level_total_estimate(current_exp, percent)
        self._trim_samples(now)
        self.last_status = "統計中"
        return True

    def snapshot(self, now: float) -> ExperienceSnapshot:
        if not self.samples:
            return self._snapshot_from_last(status=self.last_status)
        if self._has_only_baseline_sample():
            snapshot = self._snapshot_from_last(status=self.last_status)
            snapshot.sample_count = len(self.samples)
            self.last_snapshot = snapshot
            return snapshot

        latest = self.samples[-1]
        five_minute_rate = self._rate_per_second(EXP_RATE_5M_SECONDS)
        ten_minute_rate = self._rate_per_second(EXP_RATE_10M_SECONDS)
        session_rate = self._session_rate_per_second()
        preferred_rate = self._preferred_eta_rate_per_second(five_minute_rate, ten_minute_rate, session_rate)
        snapshot = ExperienceSnapshot(
            current_exp=latest.current_exp,
            current_percent=latest.percent,
            xp_per_5m=self._rate_or_previous(five_minute_rate, EXP_RATE_5M_SECONDS, "xp_per_5m"),
            xp_per_10m=self._rate_or_previous(ten_minute_rate, EXP_RATE_10M_SECONDS, "xp_per_10m"),
            xp_per_hour=self._rate_or_previous(session_rate, EXP_RATE_1H_SECONDS, "xp_per_hour"),
            eta_seconds=self._eta_seconds(latest, preferred_rate),
            sample_count=len(self.samples),
            status=self.last_status,
        )
        if snapshot.eta_seconds is None and self.last_snapshot is not None:
            snapshot.eta_seconds = self.last_snapshot.eta_seconds
        self.last_snapshot = snapshot
        return snapshot

    def _restart_session(self, now: float, current_exp: int, percent: float | None, status: str) -> None:
        self.samples = [ExperienceSample(now, current_exp, 0, percent)]
        self.last_current_exp = current_exp
        self.total_gained_exp = 0
        self.estimated_level_total_exp = None
        self._update_level_total_estimate(current_exp, percent, force=True)
        self.last_status = status

    def _has_only_baseline_sample(self) -> bool:
        return len(self.samples) == 1 and self.total_gained_exp == 0

    def _can_rebase_initial_session(self) -> bool:
        return (
            0 < len(self.samples) <= EXP_INITIAL_REBASE_MAX_SAMPLES
            and self.total_gained_exp <= EXP_GAIN_MIN_ABSOLUTE_TOLERANCE
        )

    def _reject_sample(self, reason: str) -> None:
        self.last_status = f"樣本拒絕：{reason}"

    def _snapshot_from_last(self, status: str) -> ExperienceSnapshot:
        if self.last_snapshot is None:
            return ExperienceSnapshot(status=status)
        return ExperienceSnapshot(
            current_exp=self.last_snapshot.current_exp,
            current_percent=self.last_snapshot.current_percent,
            xp_per_5m=self.last_snapshot.xp_per_5m,
            xp_per_10m=self.last_snapshot.xp_per_10m,
            xp_per_hour=self.last_snapshot.xp_per_hour,
            eta_seconds=self.last_snapshot.eta_seconds,
            sample_count=self.last_snapshot.sample_count,
            status=status,
        )

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

    def _max_reasonable_delta(self, elapsed: float, percent: float | None) -> float:
        tolerance = float(EXP_GAIN_MIN_ABSOLUTE_TOLERANCE)
        if self.estimated_level_total_exp is not None:
            tolerance = max(tolerance, self.estimated_level_total_exp * EXP_SINGLE_GAIN_MAX_LEVEL_RATIO)

        latest = self.samples[-1] if self.samples else None
        if (
            latest is not None
            and latest.percent is not None
            and percent is not None
            and percent >= latest.percent
            and self.estimated_level_total_exp is not None
        ):
            expected_delta = self.estimated_level_total_exp * ((percent - latest.percent) / 100.0)
            tolerance = max(tolerance, expected_delta * EXP_GAIN_EXPECTED_TOLERANCE_RATIO)

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

    def _rate_per_second(self, window_seconds: float) -> float | None:
        if len(self.samples) < 2:
            return None

        latest = self.samples[-1]
        oldest = self.samples[0]
        cutoff = latest.captured_at - window_seconds
        for sample in self.samples:
            if sample.captured_at >= cutoff:
                oldest = sample
                break

        elapsed = latest.captured_at - oldest.captured_at
        if elapsed < EXP_RATE_MIN_SECONDS:
            return None
        gained = latest.total_gained_exp - oldest.total_gained_exp
        return max(0.0, gained / elapsed)

    def _rate_or_previous(self, rate_per_second: float | None, multiplier: float, field_name: str) -> float | None:
        if rate_per_second is not None:
            return rate_per_second * multiplier
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
    ) -> float | None:
        short_rate = ten_minute_rate or five_minute_rate or session_rate
        if session_rate is None:
            return short_rate
        if short_rate is None or len(self.samples) < 2:
            return session_rate

        elapsed = self.samples[-1].captured_at - self.samples[0].captured_at
        if elapsed <= EXP_LONG_RATE_BLEND_START_SECONDS:
            return short_rate
        blend_range = EXP_LONG_RATE_BLEND_FULL_SECONDS - EXP_LONG_RATE_BLEND_START_SECONDS
        long_weight = min(0.85, max(0.0, (elapsed - EXP_LONG_RATE_BLEND_START_SECONDS) / blend_range))
        return short_rate * (1.0 - long_weight) + session_rate * long_weight

    def _eta_seconds(self, latest: ExperienceSample, rate_per_second: float | None) -> float | None:
        if rate_per_second is None or rate_per_second <= 0:
            return None
        if self.estimated_level_total_exp is None:
            return None
        remaining = self.estimated_level_total_exp - latest.current_exp
        if remaining <= 0:
            return None
        return remaining / rate_per_second


class PaddleExperienceTextReader:
    def __init__(self) -> None:
        self.ocr: Any | None = None
        self.unavailable_reason: str | None = None

    def read(self, image: np.ndarray) -> ExperienceTextReading:
        if not self._ensure_ocr():
            return ExperienceTextReading(reason=self.unavailable_reason or "PaddleOCR 尚未初始化")

        fallback_reading: ExperienceTextReading | None = None
        best_success: ExperienceTextReading | None = None
        for prepared in prepare_experience_ocr_images(image):
            try:
                result = self._predict(prepared)
            except Exception as exc:
                return ExperienceTextReading(reason=f"PaddleOCR 辨識失敗：{exc}")

            reading = reading_from_paddle_result(result)
            if reading.success and reading.confidence >= EXP_OCR_ACCEPT_CONFIDENCE:
                return reading
            if reading.success and (best_success is None or reading.confidence > best_success.confidence):
                best_success = reading
            if fallback_reading is None or reading.confidence > fallback_reading.confidence:
                fallback_reading = reading
        return best_success or fallback_reading or ExperienceTextReading(reason="EXP 數字解析失敗")

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
    bgr = image[:, :, :3]
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


def prepare_experience_binary_source_image(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3]
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
    return variants


def reading_from_paddle_result(result: object) -> ExperienceTextReading:
    text_items = extract_paddle_text_items(result)
    text = " ".join(item_text for item_text, _score in text_items).strip()
    confidence_values = [score for _item_text, score in text_items if score is not None]
    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
    if confidence_values and confidence < EXP_OCR_MIN_SCORE:
        return ExperienceTextReading(text=text, confidence=confidence, reason="PaddleOCR 信心過低")

    percent = parse_exp_percent_text(text)
    if percent is None:
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 百分比解析失敗")
    current_exp = parse_current_exp_text(text, percent)
    if current_exp is None:
        return ExperienceTextReading(text=text, confidence=confidence, reason="EXP 數字解析失敗")
    return ExperienceTextReading(
        current_exp=current_exp,
        percent=percent,
        text=text,
        confidence=confidence,
        success=True,
        reason="OK",
    )


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


def _binarize_experience_text(image: np.ndarray) -> np.ndarray | None:
    text_mask = _clean_experience_text_mask(_experience_text_mask(image))
    text_ratio = float(text_mask.mean())
    if not EXP_OCR_TEXT_MIN_RATIO <= text_ratio <= EXP_OCR_TEXT_BINARY_MAX_RATIO:
        return None

    black_text_on_white = np.full(text_mask.shape, 255, dtype=np.uint8)
    black_text_on_white[text_mask] = 0
    kernel = np.ones((2, 2), dtype=np.uint8)
    black_text_on_white = cv2.erode(black_text_on_white, kernel, iterations=1)
    return cv2.cvtColor(black_text_on_white, cv2.COLOR_GRAY2BGR)


def _experience_text_mask(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3].astype(np.float32)
    blue = bgr[:, :, 0]
    green = bgr[:, :, 1]
    red = bgr[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    return (luminance >= 130.0) & (chroma <= 65.0)


def _clean_experience_text_mask(mask: np.ndarray) -> np.ndarray:
    if mask.size == 0:
        return mask
    cleaned = mask.copy()
    row_density = cleaned.mean(axis=1)
    dense_rows = np.flatnonzero(row_density >= EXP_OCR_DENSE_BORDER_ROW_MAX_RATIO)
    for row in dense_rows:
        top = max(0, int(row) - EXP_OCR_DENSE_BORDER_ROW_PADDING)
        bottom = min(cleaned.shape[0], int(row) + EXP_OCR_DENSE_BORDER_ROW_PADDING + 1)
        cleaned[top:bottom, :] = False
    return cleaned


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
            suppress_process_output(),
            contextlib.redirect_stdout(output_sink),
            contextlib.redirect_stderr(output_sink),
        ):
            yield


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
            " ": "",
            "\t": "",
            "\n": "",
            "\r": "",
        }
    )
    return text.translate(translation)


def _exp_digits_before_percent(text: str, percent_start: int) -> str:
    prefix = text[:percent_start]
    if (
        len(prefix) >= 2
        and prefix[-1] == "1"
        and prefix[-2].isdigit()
        and "[" not in prefix
        and "(" not in prefix
    ):
        prefix = prefix[:-1]
    return "".join(char for char in prefix if char.isdigit())


def _last_exp_percent_match(text: str) -> tuple[float, tuple[int, int]] | None:
    for patterns in (
        (
            re.compile(r"(\d{1,3})[\.,](\d{1,2})%"),
            re.compile(r"[\[\(](\d{1,3})[\.,:](\d{1,2})[\]\)]?"),
            re.compile(r"(\d{1,3})[\.:](\d{1,2})"),
        ),
        (re.compile(r"(?<![\d\.,])(\d{1,3})%"),),
    ):
        candidates: list[tuple[float, tuple[int, int]]] = []
        for pattern in patterns:
            candidates.extend(_percent_matches(text, pattern))
        if candidates:
            return max(candidates, key=lambda item: (item[1][1], item[1][1] - item[1][0]))
    return None


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
