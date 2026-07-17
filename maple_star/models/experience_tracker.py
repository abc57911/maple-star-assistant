from __future__ import annotations
import math

from .experience_constants import *  # noqa: F401,F403
from .experience_types import (
    ExperienceSample,
    ExperienceSnapshot,
    PendingExperienceBaseline,
    PendingExperienceRebase,
    RateEstimate,
)


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


def format_exp_10m_gain(value: int | None) -> str:
    if value is None:
        return "--"
    return f"{max(0, int(value)) / 10000.0:.2f}萬"


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
        self.exp_10m_checkpoint_exp: int | None = None
        self.exp_10m_gain: int | None = None
        self.last_level_wrap_at: float | None = None
        self.baseline_current_exp_floor: int | None = None
        self.pending_initial_baseline: PendingExperienceBaseline | None = None
        self.pending_initial_baselines: list[PendingExperienceBaseline] = []
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

    def record_exp_10m_checkpoint(self, current_exp: int) -> None:
        previous_exp = self.exp_10m_checkpoint_exp
        self.exp_10m_checkpoint_exp = current_exp
        if previous_exp is None or current_exp < previous_exp:
            self.exp_10m_gain = None
            return
        self.exp_10m_gain = current_exp - previous_exp

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
            if percent is None:
                self.baseline_current_exp_floor = current_exp
            self.started_at = now
            self.pending_initial_baseline = None
            self.pending_initial_baselines = []
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

        floor_rejection = self._below_baseline_floor_rejection_reason(current_exp, percent)
        if floor_rejection is not None:
            self.pending_rebase = None
            self._reject_sample(floor_rejection)
            return False

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
            self.last_level_wrap_at = now
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
                exp_10m_gain=self.exp_10m_gain,
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
        if self._level_wrap_rate_grace_active(now):
            xp_per_5m = self._level_wrap_grace_rate(xp_per_5m, "xp_per_5m")
            xp_per_10m = self._level_wrap_grace_rate(xp_per_10m, "xp_per_10m")
            xp_per_hour = self._level_wrap_grace_rate(xp_per_hour, "xp_per_hour")
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
            exp_10m_gain=self.exp_10m_gain,
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
        self.pending_initial_baselines = []
        self.pending_rebase = None
        if self.baseline_current_exp_floor is None and percent is None:
            self.baseline_current_exp_floor = current_exp
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

    def _below_baseline_floor_rejection_reason(self, current_exp: int, percent: float | None) -> str | None:
        floor = self.baseline_current_exp_floor
        if floor is None or current_exp >= floor:
            return None
        if self._level_wrap_delta(current_exp, percent) is not None:
            return None
        return f"EXP 低於基準值：{current_exp:,} < {floor:,}"

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
        pending_candidates = [
            pending
            for pending in getattr(self, "pending_initial_baselines", [])
            if now - pending.captured_at <= EXP_INITIAL_BASELINE_CONFIRM_SECONDS
        ]
        legacy_pending = self.pending_initial_baseline
        if legacy_pending is not None and legacy_pending not in pending_candidates:
            pending_candidates.append(legacy_pending)
        for pending in pending_candidates:
            if self._pending_initial_baseline_matches(pending, now, current_exp, percent):
                self.pending_initial_baselines = []
                self.pending_initial_baseline = None
                return True

        next_pending = PendingExperienceBaseline(now, current_exp, percent, confidence)
        pending_candidates.append(next_pending)
        self.pending_initial_baselines = pending_candidates[-EXP_INITIAL_BASELINE_MAX_CANDIDATES:]
        self.pending_initial_baseline = next_pending
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
                exp_10m_gain=self.exp_10m_gain,
                elapsed_seconds=self._elapsed_seconds(now),
                status=status,
                **self._quality_snapshot_fields(),
            )
        return ExperienceSnapshot(
            current_exp=self.last_snapshot.current_exp,
            current_percent=self.last_snapshot.current_percent,
            exp_10m_gain=self.exp_10m_gain,
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
        if self._can_accept_first_percent_after_exp_only_baseline(latest, current_exp, percent, delta):
            return None
        elapsed = 0.0 if latest is None else max(0.0, now - latest.captured_at)
        max_delta = self._max_reasonable_delta(elapsed, percent)
        if delta > max_delta:
            return f"EXP 跳動過大：+{delta:,}"
        return None

    def _can_accept_first_percent_after_exp_only_baseline(
        self,
        latest: ExperienceSample | None,
        current_exp: int,
        percent: float | None,
        delta: int,
    ) -> bool:
        if (
            latest is None
            or len(self.samples) != 1
            or self.total_gained_exp != 0
            or latest.percent is not None
            or percent is None
            or delta < 0
        ):
            return False
        tolerance = self._pending_initial_baseline_exp_tolerance(
            PendingExperienceBaseline(
                latest.captured_at,
                latest.current_exp,
                latest.percent,
                latest.confidence,
            ),
            percent,
        )
        return delta <= tolerance

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
        if (
            percent_delta >= EXP_PERCENT_UNDERGAIN_STRICT_MIN_DELTA
            and expected_delta >= EXP_PERCENT_UNDERGAIN_STRICT_MIN_EXPECTED_DELTA
            and delta < expected_delta * EXP_PERCENT_UNDERGAIN_STRICT_MIN_RATIO
        ):
            return f"EXP 增量低於百分比變化：+{delta:,} / 預期約 +{round(expected_delta):,}"
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
            rounding_tolerance = self.estimated_level_total_exp * EXP_PERCENT_ROUNDING_TOLERANCE_RATIO
            return max(
                float(EXP_GAIN_MIN_ABSOLUTE_TOLERANCE),
                rounding_tolerance,
                expected_delta * EXP_GAIN_EXPECTED_TOLERANCE_RATIO,
            )

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

    def _level_wrap_rate_grace_active(self, now: float) -> bool:
        if self.last_level_wrap_at is None or self.last_snapshot is None:
            return False
        elapsed = now - self.last_level_wrap_at
        return 0.0 <= elapsed <= EXP_LEVEL_WRAP_RATE_GRACE_SECONDS

    def _level_wrap_grace_rate(self, current: float | None, field_name: str) -> float | None:
        previous = self._previous_rate_value(field_name)
        if previous is None:
            return current
        if current is None or current < EXP_LEVEL_WRAP_RATE_DISPLAY_FLOOR:
            return previous
        return current

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

__all__ = [
    "ExperienceEfficiencyTracker",
    "format_duration",
    "format_eta",
    "format_exp",
    "format_exp_10m_gain",
    "format_exp_rate",
    "format_ocr_success_rate",
    "format_rate_confidence",
]
