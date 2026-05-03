from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass

import numpy as np

from .experience import ExperienceTextReading


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


@dataclass
class ExperienceOcrJob:
    submitted_at: float
    future: Future[ExperienceTextReading]
    image_signature: "ExperienceOcrImageSignature | None" = None


@dataclass
class ExperienceOcrBurst:
    started_at: float
    next_capture_at: float
    regions: list[tuple[int, int, int, int]]
    image_frames: list[list[np.ndarray]]
    capture_count: int


@dataclass(frozen=True)
class PotionEffectAttempt:
    attempted_at: float
    before_percent: float
    min_percent: float | None = None
    max_percent: float | None = None
    pre_window_is_stable: bool = False

    def __post_init__(self) -> None:
        if self.min_percent is None:
            object.__setattr__(self, "min_percent", self.before_percent)
        if self.max_percent is None:
            object.__setattr__(self, "max_percent", self.before_percent)

    def with_observed_percent(self, percent: float) -> "PotionEffectAttempt":
        min_percent = self.before_percent if self.min_percent is None else self.min_percent
        max_percent = self.before_percent if self.max_percent is None else self.max_percent
        return PotionEffectAttempt(
            self.attempted_at,
            self.before_percent,
            min(min_percent, percent),
            max(max_percent, percent),
            self.pre_window_is_stable,
        )


@dataclass(frozen=True)
class OutOfPotionHold:
    held_at: float
    held_percent: float


@dataclass(frozen=True)
class ExperienceOcrImageSignature:
    image_shapes: tuple[tuple[int, ...], ...]
    image_hashes: tuple[bytes, ...]
    thumbnails: tuple[bytes, ...]


@dataclass(frozen=True)
class HudSearchArea:
    left: int
    top: int
    width: int
    height: int
    reference_left: int
    reference_width: int
    reference_height: int
