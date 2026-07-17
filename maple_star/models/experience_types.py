from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .experience_constants import EXP_OCR_BAR_CROP_LEFT_RATIO


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
    exp_10m_gain: int | None = None
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


__all__ = [
    "ExperienceOcrContinuityHint",
    "ExperienceOcrImage",
    "ExperiencePixelFontAttempt",
    "ExperienceSample",
    "ExperienceSnapshot",
    "ExperienceTextCandidate",
    "ExperienceTextReading",
    "PendingExperienceBaseline",
    "PendingExperienceRebase",
    "RateEstimate",
]
