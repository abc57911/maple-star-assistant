from __future__ import annotations
import re
import unicodedata
from typing import Any

import numpy as np

from ..constants import EXPERIENCE_BURST_CONSENSUS_MIN_COUNT
from ..models.experience_constants import *  # noqa: F401,F403
from ..models.experience_types import (
    ExperienceOcrContinuityHint,
    ExperienceTextCandidate,
    ExperienceTextReading,
)


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
        return "compatible" if current_exp >= continuity_hint.current_exp else "incompatible"
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


def reading_from_paddle_result(
    result: object,
    *,
    allow_low_percent_repair: bool = False,
) -> ExperienceTextReading:
    text_items = extract_paddle_text_items(result)
    text = " ".join(item_text for item_text, _score in text_items).strip()
    confidence_values = [score for _item_text, score in text_items if score is not None]
    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
    if confidence_values and confidence < EXP_OCR_MIN_SCORE:
        return ExperienceTextReading(text=text, confidence=confidence, reason="PaddleOCR 信心過低")

    candidate = _best_experience_text_candidate(text, allow_low_percent_repair=allow_low_percent_repair)
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


def reading_from_stat_window_paddle_result(result: object) -> ExperienceTextReading:
    text_items = extract_paddle_text_items(result)
    text = " ".join(item_text for item_text, _score in text_items).strip()
    confidence_values = [score for _item_text, score in text_items if score is not None]
    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
    return reading_from_stat_window_text(text, confidence)


def reading_from_tooltip_paddle_result(
    result: object,
    *,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> ExperienceTextReading:
    text_items = extract_paddle_text_items(result)
    text = " ".join(item_text for item_text, _score in text_items).strip()
    confidence_values = [score for _item_text, score in text_items if score is not None]
    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
    candidates = [reading_from_tooltip_text(text, confidence, continuity_hint=continuity_hint)]
    non_empty_items = [(item_text.strip(), item_score) for item_text, item_score in text_items if item_text.strip()]
    for start_index in range(len(non_empty_items)):
        for end_index in range(start_index + 1, len(non_empty_items) + 1):
            item_slice = non_empty_items[start_index:end_index]
            item_text = " ".join(item_text for item_text, _item_score in item_slice)
            item_scores = [item_score for _item_text, item_score in item_slice if item_score is not None]
            item_confidence = float(np.mean(item_scores)) if item_scores else 0.0
            candidates.append(reading_from_tooltip_text(item_text, item_confidence, continuity_hint=continuity_hint))
    return max(candidates, key=lambda reading: (reading.success, reading.confidence))


def reading_from_stat_window_text(text: str, confidence: float = 1.0) -> ExperienceTextReading:
    parsed = parse_stat_window_exp_text(text)
    if parsed is None:
        return ExperienceTextReading(
            text=text,
            confidence=confidence,
            reason="能力值 EXP 解析失敗",
            source="stat_window",
        )
    if confidence < EXP_STAT_WINDOW_OCR_ACCEPT_CONFIDENCE:
        return ExperienceTextReading(
            text=text,
            confidence=confidence,
            reason="能力值 EXP OCR 信心未達可信門檻",
            source="stat_window",
        )
    current_exp, percent = parsed
    return ExperienceTextReading(
        current_exp=current_exp,
        percent=percent,
        text=text,
        confidence=confidence,
        success=True,
        reason="OK:StatWindow",
        source="stat_window",
    )


def reading_from_tooltip_text(
    text: str,
    confidence: float = 1.0,
    *,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> ExperienceTextReading:
    parsed = parse_experience_tooltip_text(text, continuity_hint=continuity_hint)
    if parsed is None:
        return ExperienceTextReading(
            text=text,
            confidence=confidence,
            reason="浮動 EXP 解析失敗",
            source="tooltip",
        )
    if confidence < EXP_STAT_WINDOW_OCR_ACCEPT_CONFIDENCE:
        return ExperienceTextReading(
            text=text,
            confidence=confidence,
            reason="浮動 EXP OCR 信心未達可信門檻",
            source="tooltip",
        )
    current_exp, _total_exp, percent = parsed
    return ExperienceTextReading(
        current_exp=current_exp,
        percent=percent,
        text=text,
        confidence=confidence,
        success=True,
        reason="OK:Tooltip",
        source="tooltip",
    )


def parse_stat_window_exp_text(text: str) -> tuple[int, float] | None:
    if not text:
        return None

    compact = normalize_exp_ocr_text(text)
    upper = compact.upper()
    if not upper:
        return None
    if "/" in upper or "／" in text:
        return None
    if re.search(r"(?:^|[^A-Z])(?:HP|MP)[:：]?\d", upper):
        return None

    if "EXP" in upper:
        parse_source = upper[upper.rfind("EXP") + 3 :]
    else:
        if re.search(r"[A-Z]", upper):
            return None
        parse_source = upper

    matches = list(
        re.finditer(
            r"([0-9][0-9,.]*)[\(\[]((?:[0-9]{1,2}|100)(?:[\.,][0-9]{1,2})?)(?:[%Xx])?[\)\]]",
            parse_source,
        )
    )
    for match in reversed(matches):
        exp_segment = match.group(1)
        if not _exp_number_separators_are_valid(exp_segment):
            continue
        exp_digits = "".join(char for char in exp_segment if char.isdigit())
        if not exp_digits:
            continue
        percent = float(match.group(2).replace(",", "."))
        if 0.0 <= percent <= 100.0:
            return int(exp_digits), percent
    return None


def parse_experience_tooltip_text(
    text: str,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> tuple[int, int, float] | None:
    if not text:
        return None

    preserved = unicodedata.normalize("NFKC", text)
    preserved = preserved.translate(
        str.maketrans(
            {
                "％": "%",
                "﹪": "%",
                "．": ".",
                "。": ".",
                "：": ":",
                "，": ",",
                "／": "/",
            }
        )
    )
    compact = normalize_exp_ocr_text(text)
    upper = compact.upper()
    if not upper:
        return None
    if re.search(r"(?:^|[^A-Z])(?:HP|MP)[:：]?\d", upper):
        return None

    preserved_upper = preserved.upper()

    source_pairs = _experience_tooltip_parse_sources(upper, preserved_upper)
    if not source_pairs:
        return None
    for parse_source, preserved_source in source_pairs:
        parsed = _parse_experience_tooltip_source(
            parse_source,
            preserved_source,
            continuity_hint=continuity_hint,
        )
        if parsed is not None:
            return parsed
    return None


def _experience_tooltip_parse_sources(upper: str, preserved_upper: str) -> list[tuple[str, str]]:
    marker_ends = [match.end() for match in re.finditer(r"EXP|XP", upper)]
    if marker_ends:
        preserved_marker_ends = [match.end() for match in re.finditer(r"EXP|XP", preserved_upper)]
        pairs = [
            (upper[end:], preserved_upper[preserved_marker_ends[index] :])
            for index, end in enumerate(marker_ends)
            if index < len(preserved_marker_ends)
        ]
        return [(upper, preserved_upper), *pairs]
    if re.search(r"[A-Z]", upper):
        return []
    return [(upper, preserved_upper)]


def _parse_experience_tooltip_source(
    parse_source: str,
    preserved_source: str,
    *,
    continuity_hint: ExperienceOcrContinuityHint | None = None,
) -> tuple[int, int, float] | None:
    matches = list(re.finditer(r"([0-9][0-9,.]*)/([0-9][0-9,.]*)", parse_source))
    matches.extend(re.finditer(r"([0-9][0-9,.]*)\s+7\s+([0-9][0-9,.]*)", preserved_source))
    for match in reversed(matches):
        current_segment = match.group(1)
        total_segment = match.group(2)
        if not _exp_number_separators_are_valid(current_segment):
            continue
        if not _exp_number_separators_are_valid(total_segment):
            continue
        current_digits = "".join(char for char in current_segment if char.isdigit())
        total_digits = "".join(char for char in total_segment if char.isdigit())
        if not current_digits or not total_digits:
            continue
        current_exp = int(current_digits)
        total_exp = int(total_digits)
        if total_exp <= 0 or current_exp < 0 or current_exp > total_exp:
            continue
        return current_exp, total_exp, round(current_exp / total_exp * 100.0, 2)

    digits = "".join(char for char in parse_source if char.isdigit())
    for total_length in range(7, min(12, len(digits) - 2) + 1):
        separator_index = len(digits) - total_length - 1
        if separator_index <= 0 or digits[separator_index] != "7":
            continue
        current_digits = digits[:separator_index]
        total_digits = digits[separator_index + 1 :]
        if len(current_digits) < 4 or current_digits.startswith("0"):
            continue
        current_exp = int(current_digits)
        total_exp = int(total_digits)
        if total_exp <= 0 or current_exp > total_exp:
            continue
        percent = round(current_exp / total_exp * 100.0, 2)
        leading_digit_alternative = _merged_tooltip_leading_digit_alternative(digits, separator_index, total_digits)
        if leading_digit_alternative is not None:
            if continuity_hint is None:
                return None
            alternative_current_exp, alternative_total_exp, alternative_percent = leading_digit_alternative
            if alternative_total_exp != total_exp:
                return None
            current_status = _experience_ocr_continuity_status(current_exp, percent, continuity_hint)
            alternative_status = _experience_ocr_continuity_status(
                alternative_current_exp,
                alternative_percent,
                continuity_hint,
            )
            if current_status == "compatible" and alternative_status != "compatible":
                pass
            elif _continuity_group_rank(current_exp, percent, continuity_hint) <= _continuity_group_rank(
                alternative_current_exp,
                alternative_percent,
                continuity_hint,
            ):
                return None
        return current_exp, total_exp, percent
    return None


def _merged_tooltip_leading_digit_alternative(
    digits: str,
    separator_index: int,
    total_digits: str,
) -> tuple[int, int, float] | None:
    if separator_index <= 1 or not digits:
        return None
    trimmed_digits = digits[1:]
    for total_length in range(7, min(12, len(trimmed_digits) - 2) + 1):
        trimmed_separator_index = len(trimmed_digits) - total_length - 1
        if trimmed_separator_index <= 0 or trimmed_digits[trimmed_separator_index] != "7":
            continue
        trimmed_current_digits = trimmed_digits[:trimmed_separator_index]
        trimmed_total_digits = trimmed_digits[trimmed_separator_index + 1 :]
        if trimmed_total_digits != total_digits:
            continue
        if not trimmed_current_digits or trimmed_current_digits.startswith("0"):
            continue
        trimmed_current_exp = int(trimmed_current_digits)
        trimmed_total_exp = int(trimmed_total_digits)
        if trimmed_total_exp > 0 and trimmed_current_exp <= trimmed_total_exp:
            return trimmed_current_exp, trimmed_total_exp, round(trimmed_current_exp / trimmed_total_exp * 100.0, 2)
    return None


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
    candidate = _best_experience_text_candidate(text, allow_low_percent_repair=True)
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


def _best_experience_text_candidate(
    text: str,
    *,
    allow_low_percent_repair: bool = False,
) -> ExperienceTextCandidate | None:
    candidates = _experience_text_candidates(text, allow_low_percent_repair=allow_low_percent_repair)
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


def _experience_text_candidates(
    text: str,
    *,
    allow_low_percent_repair: bool = False,
) -> list[ExperienceTextCandidate]:
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
                        needs_bar_percent_guard=tail == "",
                    )
                )
    candidates.extend(
        _missing_open_bracket_experience_text_candidates(
            compact,
            allow_low_percent_repair=allow_low_percent_repair,
        )
    )
    candidates.extend(
        _merged_exp_percent_text_candidates(
            compact,
            allow_low_percent_repair=allow_low_percent_repair,
        )
    )
    return candidates


def _has_spaced_experience_number_prefix(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    return re.search(r"\d\s+\d[0-9\s,.]*[\[\(]", normalized) is not None


def _missing_open_bracket_experience_text_candidates(
    compact: str,
    *,
    allow_low_percent_repair: bool = False,
) -> list[ExperienceTextCandidate]:
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

    percent_integer_options: list[str] = []
    if allow_low_percent_repair and before_decimal.endswith("0"):
        percent_integer_options.append("0")
    integer_digits = digit_match.group(1)
    if len(integer_digits) == 3 and int(integer_digits) > 100:
        percent_integer_options.append(integer_digits[-2:])
    elif len(integer_digits) == 3 and integer_digits != "100":
        return []
    else:
        percent_integer_options.append(integer_digits)

    candidates: list[ExperienceTextCandidate] = []
    for percent_integer_digits in dict.fromkeys(percent_integer_options):
        percent = float(f"{percent_integer_digits}.{decimals}")
        if not _repaired_experience_percent_is_allowed(percent, allow_low_percent_repair=allow_low_percent_repair):
            continue
        exp_segment = before_decimal[: len(before_decimal) - len(percent_integer_digits)]
        if not _exp_number_separators_are_valid(exp_segment):
            continue
        exp_digits = "".join(char for char in exp_segment if char.isdigit())
        if len(exp_digits) < 5:
            continue
        percent_start = len(exp_segment)
        percent_span = (percent_start, len(body))
        candidates.append(
            ExperienceTextCandidate(
                current_exp=int(exp_digits),
                percent=percent,
                percent_span=percent_span,
                structure_score=4.3 + min(len(exp_digits), 8) / 10.0,
                repaired_percent=True,
            )
        )
    return candidates


def _merged_exp_percent_text_candidates(
    compact: str,
    *,
    allow_low_percent_repair: bool = False,
) -> list[ExperienceTextCandidate]:
    body = re.sub(r"^EXP[:：]?", "", compact, flags=re.IGNORECASE)
    if any(char in body for char in "[]()%Xx"):
        return []
    match = re.fullmatch(r"([0-9]{5,})([0-9]{2})[\.,]([0-9]{2})", body)
    if match is None:
        return []

    exp_digits = match.group(1)
    percent_integer = int(match.group(2))
    percent = float(f"{percent_integer}.{match.group(3)}")
    if not _repaired_experience_percent_is_allowed(percent, allow_low_percent_repair=allow_low_percent_repair):
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


def _repaired_experience_percent_is_allowed(percent: float, *, allow_low_percent_repair: bool) -> bool:
    if 10.0 <= percent <= 100.0:
        return True
    return allow_low_percent_repair and 0.0 <= percent <= EXP_OCR_CONTINUITY_LEVEL_UP_CANDIDATE_PERCENT_MAX


def _experience_level_up_low_percent_repair_allowed(
    continuity_hint: ExperienceOcrContinuityHint | None,
    bar_percent: float | None,
) -> bool:
    if continuity_hint is None or continuity_hint.percent is None:
        return False
    if continuity_hint.percent < EXP_OCR_CONTINUITY_LEVEL_UP_PREVIOUS_PERCENT_MIN:
        return False
    if bar_percent is None:
        return True
    return 0.0 <= bar_percent <= EXP_OCR_CONTINUITY_LEVEL_UP_CANDIDATE_PERCENT_MAX


def _strict_experience_parse_failure_reason(text: str) -> str:
    if "[" not in text:
        return "EXP 百分比解析失敗"
    if re.search(r"\[(?:[0-9]{1,2}|100)[\.,][0-9]{2}[%Xx3*147Il|JjTt;:>]{0,3}[\]\)]*[;:>]*", text) is None:
        return "EXP 百分比解析失敗"
    return "EXP 數字解析失敗"


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
            "／": "/",
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

__all__ = [
    name
    for name, value in globals().items()
    if callable(value) and getattr(value, "__module__", None) == __name__
]
