from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from typing import Callable, ContextManager, Literal

import numpy as np

from ..models.controller_state import (
    ExperienceBaselineCalibration,
    ExperienceOcrBurst,
    ExperienceOcrImageSignature,
    ExperienceOcrJob,
)
from ..models.experience import ExperienceOcrImage, ExperienceTextReading
from .screen_capture import ScreenCapturePort


ExperienceJobSlot = Literal["ocr", "baseline", "checkpoint"]


@dataclass(frozen=True)
class ExperienceJobPoll:
    state: Literal["missing", "pending", "completed"]
    job: ExperienceOcrJob | None = None
    reading: ExperienceTextReading | None = None
    error: Exception | None = None


@dataclass(frozen=True)
class ExperienceBurstProgress:
    state: Literal["missing", "waiting", "capturing", "completed"]
    capture_count: int = 0
    image_frames: list[list[np.ndarray | ExperienceOcrImage]] | None = None


@dataclass(frozen=True)
class ExperienceTooltipCapture:
    image: ExperienceOcrImage | None
    debug: dict[str, object]
    skip_reason: str = ""
    error: Exception | None = None


class ExperienceCaptureCoordinator:
    """Own EXP capture jobs, calibration state, and executor lifetime."""

    def __init__(
        self,
        executor: object,
        *,
        screen_capture: ScreenCapturePort | None = None,
        initial_tooltip_baseline_started_at: float | None = None,
        signature_thumbnail_width: int = 96,
        signature_thumbnail_height: int = 18,
        signature_changed_pixel_delta: int = 4,
        signature_max_mean_diff: float = 0.35,
        signature_max_changed_ratio: float = 0.002,
    ) -> None:
        self.executor = executor
        self.screen_capture = screen_capture
        self.next_capture_at = 0.0
        self.ocr_job: ExperienceOcrJob | None = None
        self.ocr_burst: ExperienceOcrBurst | None = None
        self.baseline_calibration: ExperienceBaselineCalibration | None = None
        self.baseline_ocr_job: ExperienceOcrJob | None = None
        self.baseline_calibration_attempts = 0
        self.next_baseline_calibration_at = 0.0
        self.tooltip_baseline_failed = False
        self.initial_tooltip_baseline_started_at = initial_tooltip_baseline_started_at
        self.checkpoint_capture: ExperienceBaselineCalibration | None = None
        self.checkpoint_ocr_job: ExperienceOcrJob | None = None
        self.next_checkpoint_at = 0.0
        self.checkpoint_stopped = False
        self.checkpoint_attempts = 0
        self.checkpoint_tooltip_failed = False
        self.baseline_cursor_position: tuple[int, int] | None = None
        self.last_completed_signature: ExperienceOcrImageSignature | None = None
        self.last_failed_signature: ExperienceOcrImageSignature | None = None
        self.signature_thumbnail_width = signature_thumbnail_width
        self.signature_thumbnail_height = signature_thumbnail_height
        self.signature_changed_pixel_delta = signature_changed_pixel_delta
        self.signature_max_mean_diff = signature_max_mean_diff
        self.signature_max_changed_ratio = signature_max_changed_ratio
        self._closed = False

    def schedule_next_capture(self, deadline: float) -> None:
        self.next_capture_at = deadline

    def defer_capture_until(self, deadline: float) -> None:
        self.next_capture_at = max(self.next_capture_at, deadline)

    def capture_text_image(self, region: tuple[int, int, int, int]) -> np.ndarray:
        if self.screen_capture is None:
            raise RuntimeError("EXP screen capture port is unavailable")
        left, top, width, height = region
        return self.screen_capture.grab(
            {"left": left, "top": top, "width": width, "height": height}
        )

    def capture_text_images(
        self,
        regions: list[tuple[int, int, int, int]],
        crop_left_ratios: list[float],
        *,
        capture_image: Callable[[tuple[int, int, int, int]], np.ndarray] | None = None,
    ) -> list[ExperienceOcrImage]:
        capture = capture_image or self.capture_text_image
        return [
            ExperienceOcrImage(
                capture(region),
                crop_left_ratios[index],
                "primary" if index == 0 else "wide",
            )
            for index, region in enumerate(regions)
        ]

    def capture_tooltip(
        self,
        *,
        cursor_point: tuple[int, int],
        roi: tuple[int, int, int, int],
        attempts: int,
        settle_seconds: float,
        retry_settle_seconds: float,
        mouse_lock: Callable[[], ContextManager[tuple[int, int]]],
        set_cursor: Callable[[int, int], object],
        sleep: Callable[[float], object],
        get_cursor: Callable[[], tuple[int, int]],
        cursor_is_near: Callable[[tuple[int, int], tuple[int, int]], bool],
    ) -> ExperienceTooltipCapture:
        debug: dict[str, object] = {
            "cursor_point": cursor_point,
            "roi": roi,
            "attempts": [],
        }
        try:
            with mouse_lock() as original_cursor_position:
                debug["original_cursor_position"] = original_cursor_position
                for attempt_index in range(max(1, attempts)):
                    set_cursor(*cursor_point)
                    sleep(settle_seconds if attempt_index == 0 else retry_settle_seconds)
                    cursor_before_grab = get_cursor()
                    attempt_debug: dict[str, object] = {
                        "attempt": attempt_index + 1,
                        "cursor_before_grab": cursor_before_grab,
                    }
                    debug["attempts"].append(attempt_debug)
                    if not cursor_is_near(cursor_before_grab, cursor_point):
                        attempt_debug["decision"] = "cursor_moved_before_grab"
                        continue
                    image = self.capture_text_image(roi)
                    cursor_after_grab = get_cursor()
                    attempt_debug["cursor_after_grab"] = cursor_after_grab
                    if not cursor_is_near(cursor_after_grab, cursor_point):
                        attempt_debug["decision"] = "cursor_moved_after_grab"
                        continue
                    attempt_debug["decision"] = "captured"
                    return ExperienceTooltipCapture(
                        ExperienceOcrImage(image, source_id="tooltip", roi_offset=roi),
                        debug,
                    )
        except Exception as exc:
            return ExperienceTooltipCapture(None, debug, f"浮動 EXP 擷取例外：{exc}", exc)
        return ExperienceTooltipCapture(None, debug, "浮動 EXP 擷取期間滑鼠偏移")

    def start_burst(
        self,
        *,
        now: float,
        regions: list[tuple[int, int, int, int]],
        image_frames: list[list[np.ndarray | ExperienceOcrImage]],
        capture_attempts: int,
        capture_interval: float,
    ) -> bool:
        if capture_attempts <= 1:
            return False
        self.ocr_burst = ExperienceOcrBurst(
            started_at=now,
            next_capture_at=now + capture_interval,
            regions=regions,
            image_frames=image_frames,
            capture_count=1,
        )
        return True

    def continue_burst(
        self,
        *,
        now: float,
        capture_attempts: int,
        capture_interval: float,
        crop_left_ratios: list[float],
        capture_images: Callable[
            [list[tuple[int, int, int, int]]],
            list[ExperienceOcrImage],
        ]
        | None = None,
    ) -> ExperienceBurstProgress:
        burst = self.ocr_burst
        if burst is None:
            return ExperienceBurstProgress("missing")
        if now < burst.next_capture_at:
            return ExperienceBurstProgress("waiting", burst.capture_count)
        images = (
            capture_images(burst.regions)
            if capture_images is not None
            else self.capture_text_images(burst.regions, crop_left_ratios)
        )
        burst.image_frames.append(images)
        burst.capture_count += 1
        if burst.capture_count < capture_attempts:
            burst.next_capture_at = now + capture_interval
            return ExperienceBurstProgress("capturing", burst.capture_count)
        self.ocr_burst = None
        return ExperienceBurstProgress("completed", burst.capture_count, burst.image_frames)

    def can_start_baseline(
        self,
        now: float,
        *,
        enabled: bool,
        paused: bool,
        hud_active: bool,
        has_samples: bool,
        max_attempts: int,
    ) -> bool:
        return (
            enabled
            and not paused
            and hud_active
            and not has_samples
            and self.ocr_job is None
            and self.ocr_burst is None
            and self.baseline_ocr_job is None
            and self.baseline_calibration_attempts < max_attempts
            and now >= self.next_baseline_calibration_at
        )

    def can_start_checkpoint(
        self,
        now: float,
        *,
        enabled: bool,
        paused: bool,
        hud_active: bool,
        has_checkpoint: bool,
    ) -> bool:
        return (
            enabled
            and not paused
            and hud_active
            and not self.checkpoint_stopped
            and has_checkpoint
            and now >= self.next_checkpoint_at
            and self.ocr_job is None
            and self.ocr_burst is None
            and self.baseline_calibration is None
            and self.baseline_ocr_job is None
            and self.checkpoint_ocr_job is None
        )

    def record_checkpoint(self, now: float, interval: float) -> None:
        self.next_checkpoint_at = now + interval
        self.checkpoint_stopped = False
        self.checkpoint_attempts = 0
        self.checkpoint_tooltip_failed = False

    def reset_checkpoint(self) -> None:
        self.next_checkpoint_at = 0.0
        self.checkpoint_stopped = False
        self.checkpoint_attempts = 0
        self.checkpoint_tooltip_failed = False

    def resume_checkpoint(self, now: float, interval: float, *, has_checkpoint: bool) -> None:
        self.checkpoint_stopped = False
        self.checkpoint_attempts = 0
        self.checkpoint_tooltip_failed = False
        if has_checkpoint:
            self.next_checkpoint_at = now + interval

    def retry_or_stop_checkpoint(
        self,
        now: float,
        *,
        max_attempts: int,
        retry_delay: float,
    ) -> tuple[Literal["retry", "stop"], int]:
        attempt = max(1, self.checkpoint_attempts)
        if attempt < max_attempts:
            self.checkpoint_stopped = False
            self.next_checkpoint_at = now + retry_delay
            return "retry", attempt + 1
        self.checkpoint_stopped = True
        self.next_checkpoint_at = 0.0
        self.checkpoint_attempts = 0
        return "stop", attempt

    def stop_checkpoint(self) -> None:
        self.checkpoint_stopped = True
        self.next_checkpoint_at = 0.0
        self.checkpoint_attempts = 0

    @staticmethod
    def _cancel_job(job: ExperienceOcrJob | None) -> Exception | None:
        if job is None:
            return None
        try:
            job.future.cancel()
        except Exception as exc:
            return exc
        return None

    @staticmethod
    def _job_field(slot: ExperienceJobSlot) -> str:
        return {
            "ocr": "ocr_job",
            "baseline": "baseline_ocr_job",
            "checkpoint": "checkpoint_ocr_job",
        }[slot]

    def submit(
        self,
        slot: ExperienceJobSlot,
        worker: Callable[..., ExperienceTextReading],
        *args: object,
        submitted_at: float,
        image_signature: ExperienceOcrImageSignature | None = None,
        image_frames: list[list[np.ndarray | ExperienceOcrImage]] | None = None,
        source: str = "",
    ) -> ExperienceOcrJob:
        field = self._job_field(slot)
        if getattr(self, field) is not None:
            raise RuntimeError(f"EXP {slot} OCR job already pending")
        job = ExperienceOcrJob(
            submitted_at=submitted_at,
            future=self.executor.submit(worker, *args),
            image_signature=image_signature,
            image_frames=image_frames,
            source=source,
        )
        setattr(self, field, job)
        return job

    def poll(self, slot: ExperienceJobSlot) -> ExperienceJobPoll:
        field = self._job_field(slot)
        job = getattr(self, field)
        if job is None:
            return ExperienceJobPoll("missing")
        if not job.future.done():
            return ExperienceJobPoll("pending", job=job)
        setattr(self, field, None)
        try:
            reading = job.future.result()
        except Exception as exc:
            return ExperienceJobPoll("completed", job=job, error=exc)
        return ExperienceJobPoll("completed", job=job, reading=reading)

    @staticmethod
    def _image_array(image: np.ndarray | ExperienceOcrImage) -> np.ndarray:
        return image.image if isinstance(image, ExperienceOcrImage) else image

    def _image_thumbnail(self, image: np.ndarray) -> bytes:
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
        y_indices = np.linspace(0, height - 1, self.signature_thumbnail_height).astype(np.intp)
        x_indices = np.linspace(0, width - 1, self.signature_thumbnail_width).astype(np.intp)
        thumbnail = luminance[np.ix_(y_indices, x_indices)]
        return np.clip(np.rint(thumbnail), 0, 255).astype(np.uint8).tobytes()

    def image_signature(
        self,
        image_frames: list[list[np.ndarray | ExperienceOcrImage]],
    ) -> ExperienceOcrImageSignature:
        shapes: list[tuple[int, ...]] = []
        image_hashes: list[bytes] = []
        thumbnails: list[bytes] = []
        for images in image_frames:
            for image in images:
                image_array = self._image_array(image)
                shapes.append(tuple(int(part) for part in image_array.shape))
                image_hashes.append(hashlib.blake2b(image_array.tobytes(), digest_size=16).digest())
                thumbnails.append(self._image_thumbnail(image_array))
        return ExperienceOcrImageSignature(tuple(shapes), tuple(image_hashes), tuple(thumbnails))

    @staticmethod
    def signatures_are_identical(
        first: ExperienceOcrImageSignature | None,
        second: ExperienceOcrImageSignature | None,
    ) -> bool:
        if first is None or second is None:
            return False
        return first.image_shapes == second.image_shapes and first.image_hashes == second.image_hashes

    def signatures_are_similar(
        self,
        first: ExperienceOcrImageSignature | None,
        second: ExperienceOcrImageSignature | None,
    ) -> bool:
        if first is None or second is None or first.image_shapes != second.image_shapes:
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
            if float(np.mean(diff)) > self.signature_max_mean_diff:
                return False
            changed_ratio = float(np.count_nonzero(diff > self.signature_changed_pixel_delta)) / diff.size
            if changed_ratio > self.signature_max_changed_ratio:
                return False
        return True

    def repeated_signature(
        self,
        signature: ExperienceOcrImageSignature,
        *,
        has_samples: bool,
    ) -> Literal["completed", "failed"] | None:
        if has_samples and self.signatures_are_similar(self.last_completed_signature, signature):
            return "completed"
        if self.signatures_are_similar(self.last_failed_signature, signature):
            return "failed"
        return None

    def restore_cursor(self, set_position: Callable[[int, int], object]) -> Exception | None:
        original_position = self.baseline_cursor_position
        if original_position is None:
            return None
        try:
            set_position(*original_position)
        except Exception as exc:
            return exc
        self.baseline_cursor_position = None
        return None

    @staticmethod
    def _raise_cleanup_errors(errors: list[Exception]) -> None:
        if errors:
            raise RuntimeError(f"EXP capture cleanup failed: {errors[0]}") from errors[0]

    def cancel_baseline(
        self,
        *,
        close_ui: bool,
        close_ui_action: Callable[[], object] | None = None,
        set_cursor: Callable[[int, int], object] | None = None,
    ) -> None:
        errors: list[Exception] = []
        cancel_error = self._cancel_job(self.baseline_ocr_job)
        if cancel_error is None:
            self.baseline_ocr_job = None
        else:
            errors.append(cancel_error)
        state = self.baseline_calibration
        if close_ui and state is not None and state.opened_ui and close_ui_action is not None:
            with contextlib.suppress(Exception):
                close_ui_action()
        self.baseline_calibration = None
        if set_cursor is not None:
            restore_error = self.restore_cursor(set_cursor)
            if restore_error is not None:
                errors.append(restore_error)
        self._raise_cleanup_errors(errors)

    def cancel_checkpoint(
        self,
        *,
        close_ui: bool,
        close_ui_action: Callable[[], object] | None = None,
        set_cursor: Callable[[int, int], object] | None = None,
    ) -> None:
        errors: list[Exception] = []
        cancel_error = self._cancel_job(self.checkpoint_ocr_job)
        if cancel_error is None:
            self.checkpoint_ocr_job = None
        else:
            errors.append(cancel_error)
        state = self.checkpoint_capture
        if close_ui and state is not None and state.opened_ui and close_ui_action is not None:
            with contextlib.suppress(Exception):
                close_ui_action()
        self.checkpoint_capture = None
        if set_cursor is not None:
            restore_error = self.restore_cursor(set_cursor)
            if restore_error is not None:
                errors.append(restore_error)
        self._raise_cleanup_errors(errors)

    def cancel_ocr(self) -> None:
        self.ocr_burst = None
        cancel_error = self._cancel_job(self.ocr_job)
        if cancel_error is None:
            self.ocr_job = None
            return
        raise RuntimeError(f"EXP OCR cancellation failed: {cancel_error}") from cancel_error

    def close(
        self,
        *,
        close_ui_action: Callable[[], object] | None = None,
        set_cursor: Callable[[int, int], object] | None = None,
    ) -> None:
        if self._closed:
            return
        errors: list[Exception] = []
        for action in (
            lambda: self.cancel_baseline(
                close_ui=True,
                close_ui_action=close_ui_action,
                set_cursor=set_cursor,
            ),
            lambda: self.cancel_checkpoint(
                close_ui=True,
                close_ui_action=close_ui_action,
                set_cursor=set_cursor,
            ),
            self.cancel_ocr,
        ):
            try:
                action()
            except Exception as exc:
                errors.append(exc)
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            errors.append(exc)
        self._closed = not errors
        self._raise_cleanup_errors(errors)
