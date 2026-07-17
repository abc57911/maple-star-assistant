from __future__ import annotations
import contextlib
import io
import os
import subprocess
import sys
import time
import warnings
from typing import Any, Iterable

import numpy as np

from ..adapters.debug_logging import log_experience_debug
from ..constants import EXPERIENCE_BURST_CONSENSUS_MIN_COUNT
from ..models.experience_constants import *  # noqa: F401,F403
from ..models.experience_types import (
    ExperienceOcrContinuityHint,
    ExperienceOcrImage,
    ExperienceTextReading,
)
from . import experience_pixel_ocr as _experience_pixel_ocr
from . import experience_text_parsing as _experience_text_parsing
from .experience_image_processing import *  # noqa: F401,F403
from .experience_pixel_ocr import *  # noqa: F401,F403
from .experience_text_parsing import *  # noqa: F401,F403


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
        materialized_frames = [
            [_coerce_experience_ocr_image(image) for image in images]
            for images in image_frames
        ]
        frame_readings = [
            self._read_burst_frame(images, continuity_hint=continuity_hint)
            for images in materialized_frames
        ]
        return self._select_burst_reading(frame_readings, continuity_hint=continuity_hint)

    def _read_burst_frame(
        self,
        images: Iterable[np.ndarray | ExperienceOcrImage],
        *,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        materialized_images = list(images)
        if not materialized_images:
            reading = ExperienceTextReading(reason="EXP burst frame 未取得影像")
            return reading

        readings = [
            self.read(
                materialized_images[0],
                continuity_hint=continuity_hint,
            )
        ]
        primary = readings[0]
        if primary.success and primary.current_exp is not None and primary.percent is not None:
            return primary

        primary_image = _coerce_experience_ocr_image(materialized_images[0])
        secondary_images = [
            image
            for image in materialized_images[1:]
            if _experience_should_read_secondary_roi(primary_image, primary, _coerce_experience_ocr_image(image))
        ]
        readings.extend(
            self.read(image, continuity_hint=continuity_hint)
            for image in secondary_images
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
            return selected

        groups: dict[tuple[int, float], list[ExperienceTextReading]] = {}
        for reading in successes:
            assert reading.current_exp is not None
            assert reading.percent is not None
            groups.setdefault((reading.current_exp, round(reading.percent, 2)), []).append(reading)

        if len(groups) > 1:
            primary = readings[0]
            if primary.success and primary.current_exp is not None and primary.percent is not None:
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
            return selected

        if len(groups) == 1:
            selected = _select_best_success_reading(successes)
            return selected

        best_reading = _select_best_success_reading(successes)
        return ExperienceTextReading(
            text=best_reading.text,
            confidence=best_reading.confidence,
            reason="EXP burst 結果不一致",
        )

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
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        ocr_image = _coerce_experience_ocr_image(image)
        if ocr_image.source_id.startswith("tooltip"):
            return self.read_tooltip_exp(ocr_image)
        image_array = ocr_image.image
        bar_percent = estimate_experience_bar_percent(
            image_array,
            bar_crop_left_ratio=ocr_image.bar_crop_left_ratio,
        )
        pixel_reading = _experience_pixel_ocr._read_experience_pixel_font_adaptive(
            ocr_image,
            bar_percent=bar_percent,
            continuity_hint=continuity_hint,
        )
        pixel_reading = _with_experience_reading_metadata(pixel_reading, bar_percent=bar_percent, source="pixel")
        if pixel_reading.success:
            guarded_pixel_reading = _apply_experience_ocr_continuity_guard(pixel_reading, continuity_hint)
            if guarded_pixel_reading.success:
                return guarded_pixel_reading
            pixel_reading = guarded_pixel_reading

        if _experience_tight_right_roi_should_skip_paddle(ocr_image, pixel_reading):
            return pixel_reading

        paddle_reading = self._read_with_paddle(
            ocr_image,
            bar_percent=bar_percent,
            continuity_hint=continuity_hint,
        )
        paddle_reading = _with_experience_reading_metadata(paddle_reading, bar_percent=bar_percent, source="paddle")
        if paddle_reading.success:
            paddle_reading = _apply_experience_ocr_continuity_guard(paddle_reading, continuity_hint)
        if paddle_reading.success:
            return paddle_reading

        final_reading = paddle_reading if paddle_reading.confidence >= pixel_reading.confidence else pixel_reading
        return final_reading

    def read_stat_window_exp(self, image: np.ndarray | ExperienceOcrImage) -> ExperienceTextReading:
        ocr_image = _coerce_experience_ocr_image(image)
        if not self._ensure_ocr():
            return ExperienceTextReading(
                reason=self.unavailable_reason or "PaddleOCR 尚未初始化",
                source="stat_window",
            )

        best_reading: ExperienceTextReading | None = None
        predict_count = 0
        variants = prepare_stat_window_exp_ocr_images(ocr_image.image)
        for variant in variants:
            try:
                result = self._predict(variant)
                predict_count += 1
            except Exception as exc:
                reading = ExperienceTextReading(reason=f"能力值 EXP OCR 辨識失敗：{exc}", source="stat_window")
            else:
                reading = reading_from_stat_window_paddle_result(result)
            if reading.success:
                return reading
            if best_reading is None or reading.confidence > best_reading.confidence:
                best_reading = reading

        final = best_reading or ExperienceTextReading(reason="能力值 EXP OCR 未取得文字", source="stat_window")
        return final

    def read_tooltip_exp(
        self,
        image: np.ndarray | ExperienceOcrImage,
        *,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        ocr_image = _coerce_experience_ocr_image(image)
        if not self._ensure_ocr():
            return ExperienceTextReading(
                reason=self.unavailable_reason or "PaddleOCR 尚未初始化",
                source="tooltip",
            )

        best_reading: ExperienceTextReading | None = None
        selected_variant_index: int | None = None
        variant_attempts: list[dict[str, object]] = []
        predict_count = 0
        started_at = time.perf_counter()

        def read_variants(variants: list[np.ndarray], *, offset: int = 0) -> ExperienceTextReading | None:
            nonlocal best_reading, selected_variant_index, predict_count
            for local_index, variant in enumerate(variants):
                variant_index = offset + local_index
                try:
                    result = self._predict(variant)
                    predict_count += 1
                except Exception as exc:
                    reading = ExperienceTextReading(reason=f"浮動 EXP OCR 辨識失敗：{exc}", source="tooltip")
                else:
                    reading = _experience_text_parsing.reading_from_tooltip_paddle_result(
                        result,
                        continuity_hint=continuity_hint,
                    )
                if reading.success:
                    guarded = _apply_experience_ocr_continuity_guard(reading, continuity_hint)
                    variant_attempts.append(_tooltip_ocr_variant_attempt(variant_index, guarded))
                    if guarded.success:
                        selected_variant_index = variant_index
                        return guarded
                    reading = guarded
                else:
                    variant_attempts.append(_tooltip_ocr_variant_attempt(variant_index, reading))
                if best_reading is None or reading.confidence > best_reading.confidence:
                    best_reading = reading
            return None

        base_variants = prepare_experience_tooltip_ocr_images(ocr_image.image)
        full_variant_count = len(base_variants)
        reading = read_variants(base_variants)
        if reading is None:
            full_variants = prepare_experience_tooltip_ocr_images(ocr_image.image, include_retry=True)
            full_variant_count = len(full_variants)
            retry_variants = full_variants[len(base_variants) :]
            reading = read_variants(retry_variants, offset=len(base_variants))
        final = reading or best_reading or ExperienceTextReading(reason="浮動 EXP OCR 未取得文字", source="tooltip")
        self.last_tooltip_ocr_telemetry = {
            "predict_count": predict_count,
            "variant_count": full_variant_count,
            "selected_variant_index": selected_variant_index,
            "elapsed_ms": max(0.0, (time.perf_counter() - started_at) * 1000.0),
            "success": bool(final.success),
            "reason": final.reason,
        }
        if not final.success:
            self.last_tooltip_ocr_telemetry["variant_attempts"] = variant_attempts
        self._log_tooltip_ocr_telemetry(self.last_tooltip_ocr_telemetry)
        return final

    def _log_tooltip_ocr_telemetry(self, telemetry: dict[str, object]) -> None:
        payload = {
            "event": "experience_tooltip_ocr",
            "source": "tooltip",
            "predict_count": telemetry.get("predict_count"),
            "variant_count": telemetry.get("variant_count"),
            "selected_variant_index": telemetry.get("selected_variant_index"),
            "elapsed_ms": telemetry.get("elapsed_ms"),
            "success": telemetry.get("success"),
            "reason": telemetry.get("reason"),
        }
        if not telemetry.get("success") and telemetry.get("variant_attempts"):
            payload["variant_attempts"] = telemetry.get("variant_attempts")
        try:
            log_experience_debug(payload)
        except Exception:
            pass

    def _read_with_paddle(
        self,
        ocr_image: ExperienceOcrImage,
        *,
        bar_percent: float | None,
        continuity_hint: ExperienceOcrContinuityHint | None = None,
    ) -> ExperienceTextReading:
        if not self._ensure_ocr():
            return ExperienceTextReading(reason=self.unavailable_reason or "PaddleOCR 尚未初始化")

        image_array = ocr_image.image
        fallback_reading: ExperienceTextReading | None = None
        successes: list[tuple[tuple[float, float, float, float, int], int, ExperienceTextReading]] = []
        predict_count = 0

        def read_variants(variants: Iterable[tuple[int, np.ndarray]]) -> None:
            nonlocal fallback_reading, predict_count
            for variant_index, prepared in variants:
                try:
                    result = self._predict(prepared)
                    predict_count += 1
                except Exception as exc:
                    fallback_reading = ExperienceTextReading(reason=f"PaddleOCR 辨識失敗：{exc}")
                    return

                reading = _apply_experience_bar_percent_guard(
                    reading_from_paddle_result(
                        result,
                        allow_low_percent_repair=_experience_level_up_low_percent_repair_allowed(
                            continuity_hint,
                            bar_percent,
                        ),
                    ),
                    bar_percent,
                )
                if reading.success:
                    rank = _experience_reading_rank(reading, variant_index)
                    successes.append((rank, variant_index, reading))
                if fallback_reading is None or reading.confidence > fallback_reading.confidence:
                    fallback_reading = reading

        base_variants = _indexed_experience_ocr_images(image_array)
        read_variants(base_variants)
        base_reading = _selected_experience_reading_or_failure(successes, bar_percent=bar_percent)
        if base_reading is not None and base_reading.success:
            return base_reading
        if _should_retry_experience_ocr(base_reading or fallback_reading):
            retry_variants = _indexed_retry_experience_ocr_images(image_array)
            read_variants(retry_variants)
        else:
            retry_variants = []
        if successes:
            selected = _selected_experience_reading_or_failure(successes, bar_percent=bar_percent)
            if selected is not None:
                return selected
        final = fallback_reading or ExperienceTextReading(reason="EXP 數字解析失敗")
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


def _tooltip_ocr_variant_attempt(variant_index: int, reading: ExperienceTextReading) -> dict[str, object]:
    return {
        "variant_index": variant_index,
        "success": bool(reading.success),
        "text": reading.text,
        "confidence": reading.confidence,
        "reason": reading.reason,
        "continuity_status": reading.continuity_status,
    }


_EXPERIENCE_WORKER_READER: PaddleExperienceTextReader | None = None


def _experience_worker_reader() -> PaddleExperienceTextReader:
    global _EXPERIENCE_WORKER_READER
    if _EXPERIENCE_WORKER_READER is None:
        _EXPERIENCE_WORKER_READER = PaddleExperienceTextReader()
    return _EXPERIENCE_WORKER_READER


def read_experience_burst_frames_in_worker(
    image_frames: Iterable[Iterable[np.ndarray | ExperienceOcrImage]],
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> ExperienceTextReading:
    return _experience_worker_reader().read_burst_frames(
        image_frames,
        continuity_hint=continuity_hint,
    )


def read_stat_window_exp_in_worker(image: np.ndarray | ExperienceOcrImage) -> ExperienceTextReading:
    return _experience_worker_reader().read_stat_window_exp(image)


def read_experience_tooltip_in_worker(
    image: np.ndarray | ExperienceOcrImage,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> ExperienceTextReading:
    return _experience_worker_reader().read_tooltip_exp(image, continuity_hint=continuity_hint)


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


def _experience_tight_right_roi_should_skip_paddle(
    ocr_image: ExperienceOcrImage,
    pixel_reading: ExperienceTextReading,
) -> bool:
    if pixel_reading.success:
        return False
    if not _experience_is_tight_right_text_roi(ocr_image.image, ocr_image.bar_crop_left_ratio):
        return False
    return False


def _experience_should_read_secondary_roi(
    primary_image: ExperienceOcrImage,
    primary_reading: ExperienceTextReading,
    secondary_image: ExperienceOcrImage,
) -> bool:
    if secondary_image.source_id != "wide":
        return True
    primary_width = primary_image.image.shape[1] if primary_image.image.ndim >= 2 else 0
    if primary_width > EXP_OCR_TIGHT_RIGHT_ROI_MAX_WIDTH:
        return False
    if primary_width < EXP_OCR_TIGHT_RIGHT_ROI_MAX_WIDTH:
        return True
    return primary_reading.reason in {
        "EXP OCR 結構不可信",
        "EXP 數字解析失敗",
        "EXP 百分比解析失敗",
        "EXP 像素字型結構不可信",
        "EXP 像素字型信心過低",
    }


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

__all__ = [
    name
    for name, value in globals().items()
    if (
        (callable(value) and getattr(value, "__module__", None) == __name__)
        or name == "PaddleExperienceTextReader"
    )
]
