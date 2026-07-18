from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable


CONTROL_IDLE_POLL_SECONDS = 0.005
CONTROL_FINE_WAIT_SECONDS = 0.001
CONTROL_TIMING_SAMPLE_LIMIT = 4096


@dataclass(frozen=True)
class TimingSnapshot:
    sample_count: int = 0
    p95_lateness_ms: float = 0.0
    p99_lateness_ms: float = 0.0
    max_lateness_ms: float = 0.0


class DeadlineTimingRecorder:
    def __init__(self, max_samples: int = CONTROL_TIMING_SAMPLE_LIMIT) -> None:
        self._samples_ms: deque[float] = deque(maxlen=max(1, int(max_samples)))

    def record(self, deadline: float, fired_at: float) -> None:
        self._samples_ms.append(max(0.0, (float(fired_at) - float(deadline)) * 1000.0))

    def snapshot(self) -> TimingSnapshot:
        if not self._samples_ms:
            return TimingSnapshot()
        ordered = sorted(self._samples_ms)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        p99_index = max(0, math.ceil(len(ordered) * 0.99) - 1)
        return TimingSnapshot(
            sample_count=len(ordered),
            p95_lateness_ms=ordered[p95_index],
            p99_lateness_ms=ordered[p99_index],
            max_lateness_ms=ordered[-1],
        )


def next_absolute_deadline(previous_deadline: float, interval_seconds: float, now: float) -> float:
    """Return the next cadence deadline without replaying missed intervals."""
    interval = max(0.000_001, float(interval_seconds))
    deadline = float(previous_deadline) + interval
    if deadline > now:
        return deadline
    missed = math.floor((float(now) - deadline) / interval) + 1
    return deadline + missed * interval


def nearest_deadline(deadlines: Iterable[float | None]) -> float | None:
    available = [float(deadline) for deadline in deadlines if deadline is not None]
    return min(available) if available else None


def wait_until_next_poll(
    deadline: float | None,
    *,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
    idle_poll_seconds: float = CONTROL_IDLE_POLL_SECONDS,
    fine_wait_seconds: float = CONTROL_FINE_WAIT_SECONDS,
) -> None:
    """Wait efficiently while reserving only the final millisecond for a fine wait."""
    now = clock()
    if deadline is None:
        sleep(max(0.0, idle_poll_seconds))
        return
    remaining = float(deadline) - now
    if remaining <= 0.0:
        return
    coarse_wait = min(idle_poll_seconds, max(0.0, remaining - fine_wait_seconds))
    if coarse_wait > 0.0:
        sleep(coarse_wait)
        return
    # Yield instead of a continuous spin. On Windows perf_counter provides the
    # high-resolution clock while sleep(0) keeps CPU use bounded.
    sleep(0.0)
