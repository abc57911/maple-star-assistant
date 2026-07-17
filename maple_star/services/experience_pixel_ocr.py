from __future__ import annotations

import itertools
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from ..models.experience_constants import *  # noqa: F401,F403
from ..models.experience_types import (
    ExperienceOcrContinuityHint,
    ExperienceOcrImage,
    ExperiencePixelFontAttempt,
    ExperienceTextReading,
)
from .experience_image_processing import *  # noqa: F401,F403
from .experience_text_parsing import *  # noqa: F401,F403


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
    successes: list[tuple[tuple[float, float, float, int], ExperienceTextReading]] = []
    best_failure = ExperienceTextReading(reason="EXP 像素字型解析失敗")

    def finish(reading: ExperienceTextReading) -> ExperienceTextReading:
        return reading

    for attempt_index, attempt in enumerate(_experience_pixel_font_runtime_attempts(ocr_image)):
        attempt_bar_percent = estimate_experience_bar_percent(
            attempt.image,
            bar_crop_left_ratio=attempt.bar_crop_left_ratio,
        )
        effective_bar_percent = bar_percent if bar_percent is not None else attempt_bar_percent
        candidates = _decode_experience_pixel_font_text_candidates(
            attempt.image,
            bar_percent=effective_bar_percent,
        )
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
        time.sleep(0)

    selected = _select_pixel_font_success(successes, bar_percent, continuity_hint=continuity_hint)
    return finish(selected if selected is not None else best_failure)


def _experience_pixel_font_attempts(ocr_image: ExperienceOcrImage) -> list[ExperiencePixelFontAttempt]:
    image = ocr_image.image
    variants: list[tuple[str, tuple[int, int, int, int], np.ndarray]] = []

    def add_variant(name: str, offset: tuple[int, int, int, int], variant: np.ndarray) -> None:
        if variant.size:
            variants.append((name, offset, variant))

    green_bar_erased = _erase_experience_green_bar_to_text_image(image[:, :, :3])
    if green_bar_erased is not None:
        add_variant("green_bar_erased_text", (0, 0, 0, 0), green_bar_erased)
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


def _experience_pixel_font_runtime_attempts(ocr_image: ExperienceOcrImage) -> list[ExperiencePixelFontAttempt]:
    attempts = _experience_pixel_font_attempts(ocr_image)
    if not _experience_is_tight_right_text_roi(ocr_image.image, ocr_image.bar_crop_left_ratio):
        return attempts

    preferred_order = (
        "green_bar_erased_text",
        "raw",
        "green_suppressed",
        "low_threshold_closed",
        "shift_left_2",
        "shift_right_2",
        "tight_right_4",
    )
    preferred: list[ExperiencePixelFontAttempt] = []
    for name in preferred_order:
        preferred.extend(attempt for attempt in attempts if attempt.preprocess_variant == name)
    return preferred or attempts[:6]


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
        if (
            (best_rank[0] >= 0.98 and best_rank[0] - second_rank[0] >= 0.004)
            or (
                best_rank[0] >= EXP_PIXEL_FONT_CONFLICT_ACCEPT_CONFIDENCE
                and best_rank[0] - second_rank[0] >= EXP_PIXEL_FONT_CONFLICT_ACCEPT_GAP
            )
        ):
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
    raw_text = "".join(characters)
    if not candidates or any(text == raw_text for text, _confidence in candidates):
        candidates.append((raw_text, float(np.mean(confidences))))

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
        base = _pixel_font_candidate_from_layout(alternatives, segments, layout, open_index, integer_digit_count)
        if base is not None:
            results.append(base)
            results.extend(_pixel_font_exp_alternative_candidates(alternatives, segments, layout, open_index))
    results.extend(_split_percent_marker_pixel_font_candidates(alternatives, segments))
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
    segments: list[np.ndarray],
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
        if role == "percent_digit":
            return _first_pixel_font_percent_digit_alternative(glyph_alternatives, segments[index])
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
        role = role_by_index.get(index, "percent_digit")
        selected = select(index, role)
        if selected is None:
            return None
        selected_characters.append(selected[0])
        selected_confidences.append(selected[1])

    text = "".join(selected_characters)
    if re.fullmatch(r"[0-9]+\[(?:[0-9]{1,2}|100)\.[0-9]{2}%\]", text) is None:
        return None
    return text, float(np.mean(selected_confidences))


def _split_percent_marker_pixel_font_candidates(
    alternatives: list[list[tuple[str, float]]],
    segments: list[np.ndarray],
) -> list[tuple[str, float]]:
    if len(alternatives) != len(segments) or len(alternatives) < 10:
        return []

    results: list[tuple[str, float]] = []
    close_index = len(alternatives) - 1
    close = _first_character_alternative(alternatives[close_index], lambda character: character == "]")
    if close is None or close[1] < 0.70:
        return []

    for open_index, glyph_alternatives in enumerate(alternatives[:-1]):
        opening = _first_character_alternative(glyph_alternatives, lambda character: character == "[")
        if opening is None or opening[1] < 0.80:
            continue
        exp_digits = _pixel_font_selected_digit_prefix(alternatives, segments, open_index)
        if exp_digits is None:
            continue
        exp_text, exp_confidences = exp_digits
        for integer_digit_count in (2, 1, 3):
            dot_index = open_index + 1 + integer_digit_count
            decimal_start = dot_index + 1
            decimal_end = decimal_start + 2
            suffix_start = decimal_end
            if dot_index >= close_index or decimal_end > close_index:
                continue
            if suffix_start >= close_index:
                continue
            if close_index - suffix_start not in (2, 3, 4):
                continue
            dot = _first_character_alternative(alternatives[dot_index], lambda character: character == ".")
            if dot is None or dot[1] < 0.70:
                continue
            percent_digits: list[str] = []
            percent_confidences: list[float] = []
            valid_digits = True
            for index in range(open_index + 1, decimal_end):
                if index == dot_index:
                    continue
                selected = _split_percent_digit_alternative(alternatives[index], segments[index])
                if selected is None:
                    valid_digits = False
                    break
                percent_digits.append(selected[0])
                percent_confidences.append(selected[1])
            if not valid_digits or len(percent_digits) != integer_digit_count + 2:
                continue
            if not _split_percent_marker_segments_look_valid(segments[suffix_start:close_index], alternatives[suffix_start:close_index]):
                continue
            percent_integer = "".join(percent_digits[:integer_digit_count])
            percent_decimals = "".join(percent_digits[integer_digit_count:])
            text = f"{exp_text}[{percent_integer}.{percent_decimals}%]"
            if re.fullmatch(r"[0-9]+\[(?:[0-9]{1,2}|100)\.[0-9]{2}%\]", text) is None:
                continue
            confidence = max(
                EXP_PIXEL_FONT_SPLIT_PERCENT_REPAIR_CONFIDENCE,
                float(np.mean(exp_confidences + percent_confidences + [opening[1], dot[1], close[1]])),
            )
            results.append((text, min(1.0, confidence)))
    return results


def _split_percent_digit_alternative(
    alternatives: list[tuple[str, float]],
    glyph_mask: np.ndarray,
) -> tuple[str, float] | None:
    digit_alternatives = _pixel_font_digit_alternatives(alternatives, decimal_digit=True, glyph_mask=glyph_mask)
    if _split_percent_digit_has_unresolved_zero_eight_three_ambiguity(digit_alternatives):
        return None
    return _first_character_alternative(digit_alternatives, str.isdigit)


def _split_percent_digit_has_unresolved_zero_eight_three_ambiguity(
    digit_alternatives: list[tuple[str, float]],
) -> bool:
    if not digit_alternatives or digit_alternatives[0][0] not in {"0", "8", "3"}:
        return False
    scores = {character: confidence for character, confidence in digit_alternatives if character in {"0", "8", "3"}}
    if len(scores) < 2:
        return False
    top_character, top_confidence = max(scores.items(), key=lambda item: item[1])
    return any(
        character != top_character and top_confidence - confidence < EXP_PIXEL_FONT_SPLIT_PERCENT_AMBIGUITY_GAP
        for character, confidence in scores.items()
    )


def _pixel_font_selected_digit_prefix(
    alternatives: list[list[tuple[str, float]]],
    segments: list[np.ndarray],
    end_index: int,
) -> tuple[str, list[float]] | None:
    if end_index < 5:
        return None
    digits: list[str] = []
    confidences: list[float] = []
    for index in range(end_index):
        selected = _first_character_alternative(
            _pixel_font_digit_alternatives(alternatives[index], decimal_digit=False, glyph_mask=segments[index]),
            str.isdigit,
        )
        if selected is None or selected[1] < EXP_PIXEL_FONT_SPLIT_PERCENT_MIN_EXP_CONFIDENCE:
            return None
        digits.append(selected[0])
        confidences.append(selected[1])
    if float(np.mean(confidences)) < EXP_PIXEL_FONT_SPLIT_PERCENT_MIN_EXP_AVERAGE_CONFIDENCE:
        return None
    return "".join(digits), confidences


def _split_percent_marker_segments_look_valid(
    segments: list[np.ndarray],
    alternatives: list[list[tuple[str, float]]],
) -> bool:
    if len(segments) not in (2, 3, 4):
        return False
    widths = [segment.shape[1] for segment in segments if segment.ndim >= 2]
    heights = [segment.shape[0] for segment in segments if segment.ndim >= 2]
    if len(widths) != len(segments) or not heights:
        return False
    max_height = max(heights)
    if any(width <= 0 or width > max(8, round(max_height * 0.45)) for width in widths):
        return False
    if sum(widths) < max(10, round(max_height * 0.35)):
        return False
    for glyph_alternatives in alternatives:
        top = glyph_alternatives[0][0] if glyph_alternatives else ""
        if top in {"[", "]"}:
            return False
    return True


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
        if role == "digit":
            selected = _first_pixel_font_percent_digit_alternative(alternatives[index], segments[index])
        else:
            selected = _first_character_alternative(
                alternatives[index],
                lambda character, expected=role: character == expected,
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
        per_digit_alternatives.append(_pixel_font_percent_digit_alternatives(digit_alternatives, glyph_mask=segments[index]))

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


def _first_pixel_font_percent_digit_alternative(
    alternatives: list[tuple[str, float]],
    glyph_mask: np.ndarray,
) -> tuple[str, float] | None:
    digit_alternatives = _pixel_font_digit_alternatives(alternatives, decimal_digit=True, glyph_mask=glyph_mask)
    digit_alternatives = _pixel_font_percent_digit_alternatives(digit_alternatives, glyph_mask=glyph_mask)
    return digit_alternatives[0] if digit_alternatives else None


def _pixel_font_percent_digit_alternatives(
    digit_alternatives: list[tuple[str, float]],
    *,
    glyph_mask: np.ndarray,
) -> list[tuple[str, float]]:
    if not digit_alternatives:
        return []
    best_confidence = digit_alternatives[0][1]
    kept = [
        item
        for item in digit_alternatives
        if item[1] >= best_confidence - EXP_PIXEL_FONT_PERCENT_ALTERNATIVE_SCORE_WINDOW
    ]
    kept = kept[:EXP_PIXEL_FONT_PERCENT_MAX_ALTERNATIVES]
    preference = _experience_pixel_font_percent_digit_topology_preference(glyph_mask, kept)
    if preference is None:
        if _experience_pixel_font_has_unresolved_percent_digit_ambiguity(kept):
            return []
        return kept

    adjusted: list[tuple[str, float]] = []
    for character, confidence in kept:
        if character == preference:
            confidence = max(confidence, min(1.0, best_confidence + 0.018, EXP_PIXEL_FONT_PERCENT_TOPOLOGY_CONFIDENCE))
        elif {character, preference} in ({"6", "8"}, {"0", "8"}):
            confidence = min(confidence, EXP_PIXEL_FONT_PERCENT_TOPOLOGY_DEMOTED_CONFIDENCE)
        adjusted.append((character, confidence))
    return sorted(adjusted, key=lambda item: item[1], reverse=True)


def _experience_pixel_font_percent_digit_topology_preference(
    glyph_mask: np.ndarray,
    digit_alternatives: list[tuple[str, float]],
) -> str | None:
    features = _experience_pixel_font_glyph_features(glyph_mask)
    if features is None:
        return None
    characters = {character for character, _confidence in digit_alternatives}
    scores = {character: confidence for character, confidence in digit_alternatives}
    best_confidence = digit_alternatives[0][1] if digit_alternatives else 0.0
    if (
        {"6", "8"}.issubset(characters)
        and max(scores["6"], scores["8"]) >= best_confidence - 0.08
        and _experience_pixel_font_glyph_prefers_six_over_eight(features)
    ):
        return "6"
    if (
        {"0", "8"}.issubset(characters)
        and max(scores["0"], scores["8"]) >= best_confidence - 0.08
        and _experience_pixel_font_glyph_prefers_zero_over_eight(features)
    ):
        return "0"
    return None


def _experience_pixel_font_glyph_prefers_six_over_eight(features: dict[str, float]) -> bool:
    six_signal = (
        max(0.0, features["left_mid_edge"] - 0.55) * 1.4
        + max(0.0, 0.34 - features["ur"]) * 0.9
        + max(0.0, features["left_edge"] - features["right_edge"] - 0.15) * 0.8
        + max(0.0, features["mid"] - 0.42) * 0.45
    )
    eight_signal = (
        max(0.0, features["ur"] - 0.30) * 0.8
        + max(0.0, features["right_mid_edge"] - 0.25) * 0.8
        + max(0.0, 0.18 - abs(features["left_edge"] - features["right_edge"])) * 0.6
    )
    return six_signal - eight_signal >= 0.22


def _experience_pixel_font_glyph_prefers_zero_over_eight(features: dict[str, float]) -> bool:
    zero_signal = (
        max(0.0, 0.06 - features["inner"]) * 3.0
        + max(0.0, 0.38 - features["mid"]) * 0.8
        + min(features["left_edge"], features["right_edge"]) * 0.45
    )
    eight_signal = (
        max(0.0, features["inner"] - 0.08) * 1.4
        + max(0.0, features["mid"] - 0.34) * 0.7
        + max(0.0, features["area"] - 0.32) * 0.8
    )
    return zero_signal - eight_signal >= 0.16


def _experience_pixel_font_has_unresolved_percent_digit_ambiguity(
    digit_alternatives: list[tuple[str, float]],
) -> bool:
    scores = {character: confidence for character, confidence in digit_alternatives}
    for left, right in (("6", "8"), ("0", "8")):
        if left in scores and right in scores and abs(scores[left] - scores[right]) <= EXP_PIXEL_FONT_PERCENT_UNRESOLVED_AMBIGUITY_GAP:
            return True
    return False


def _experience_pixel_font_glyph_ambiguity(
    alternatives: list[tuple[str, float]],
) -> dict[str, Any] | None:
    digits = [(character, confidence) for character, confidence in alternatives if character.isdigit()]
    if len(digits) < 2:
        return None
    scores = {character: confidence for character, confidence in digits}
    for left, right in (("6", "8"), ("0", "8"), ("3", "8"), ("5", "6"), ("6", "9"), ("0", "9")):
        if left not in scores or right not in scores:
            continue
        gap = abs(scores[left] - scores[right])
        if gap <= 0.05:
            ranked = sorted(((left, scores[left]), (right, scores[right])), key=lambda item: item[1], reverse=True)
            return {
                "characters": [ranked[0][0], ranked[1][0]],
                "confidence_gap": gap,
                "top_confidence": ranked[0][1],
            }
    return None


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
        from ..models.experience_pixel_templates import TEMPLATES
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
        return _merge_experience_pixel_font_split_percent_runs([[start, end] for start, end in column_runs])
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
    return _merge_experience_pixel_font_split_percent_runs(merged)


def _merge_experience_pixel_font_split_percent_runs(merged: list[list[int]]) -> list[list[int]]:
    for index in range(max(0, len(merged) - 4), len(merged) - 1):
        start, end = merged[index]
        next_start, next_end = merged[index + 1]
        width = end - start
        next_width = next_end - next_start
        gap = next_start - end
        if width <= 4 and next_width >= 12 and gap <= 8 and len(merged) - index <= 3:
            return merged[:index] + [[start, next_end]] + merged[index + 2 :]
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

__all__ = [
    name
    for name, value in globals().items()
    if callable(value) and getattr(value, "__module__", None) == __name__
]
