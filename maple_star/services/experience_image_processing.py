from __future__ import annotations

import cv2
import numpy as np

from ..models.experience_constants import *  # noqa: F401,F403
from ..models.experience_types import ExperienceOcrImage


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


def prepare_stat_window_exp_ocr_images(image: np.ndarray) -> list[np.ndarray]:
    bgr = image[:, :, :3] if image.ndim >= 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if bgr.size == 0:
        return [bgr]
    padding = max(4, round(max(1, bgr.shape[0]) * 0.20))
    padded = cv2.copyMakeBorder(
        bgr,
        padding,
        padding,
        padding,
        padding,
        borderType=cv2.BORDER_REPLICATE,
    )
    scaled = cv2.resize(
        padded,
        (
            max(1, padded.shape[1] * EXP_STAT_WINDOW_OCR_PREPARED_SCALE),
            max(1, padded.shape[0] * EXP_STAT_WINDOW_OCR_PREPARED_SCALE),
        ),
        interpolation=cv2.INTER_CUBIC,
    )
    contrast = cv2.convertScaleAbs(scaled, alpha=1.45, beta=4)
    sharpened = _sharpen_experience_text_image(contrast)
    variants = [bgr, scaled, contrast, sharpened]
    unique: list[np.ndarray] = []
    seen: set[tuple[tuple[int, ...], bytes]] = set()
    for variant in variants:
        key = (tuple(int(part) for part in variant.shape), variant.tobytes())
        if key in seen:
            continue
        seen.add(key)
        unique.append(variant)
    return unique


def prepare_experience_tooltip_ocr_images(image: np.ndarray, *, include_retry: bool = False) -> list[np.ndarray]:
    bgr = image[:, :, :3] if image.ndim >= 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if bgr.size == 0:
        return [bgr]

    cropped = _crop_experience_tooltip_text_image(bgr)
    prefix_stripped = _strip_experience_tooltip_exp_prefix_image(cropped)
    padding = max(5, round(max(1, cropped.shape[0]) * 0.24))
    padded = cv2.copyMakeBorder(
        cropped,
        padding,
        padding,
        padding,
        padding,
        borderType=cv2.BORDER_REPLICATE,
    )
    scaled = cv2.resize(
        padded,
        (
            max(1, padded.shape[1] * EXP_STAT_WINDOW_OCR_PREPARED_SCALE),
            max(1, padded.shape[0] * EXP_STAT_WINDOW_OCR_PREPARED_SCALE),
        ),
        interpolation=cv2.INTER_CUBIC,
    )
    scaled_prefix_stripped = None
    if prefix_stripped is not None:
        stripped_padding = max(5, round(max(1, prefix_stripped.shape[0]) * 0.24))
        stripped_padded = cv2.copyMakeBorder(
            prefix_stripped,
            stripped_padding,
            stripped_padding,
            stripped_padding,
            stripped_padding,
            borderType=cv2.BORDER_REPLICATE,
        )
        scaled_prefix_stripped = cv2.resize(
            stripped_padded,
            (
                max(1, stripped_padded.shape[1] * EXP_STAT_WINDOW_OCR_PREPARED_SCALE),
                max(1, stripped_padded.shape[0] * EXP_STAT_WINDOW_OCR_PREPARED_SCALE),
            ),
            interpolation=cv2.INTER_CUBIC,
        )
    binary = _binarize_experience_tooltip_text_image(scaled)
    variants = [cropped, scaled, bgr]
    if binary is not None:
        variants.append(binary)
    if include_retry:
        variants.extend(variant for variant in (prefix_stripped, scaled_prefix_stripped) if variant is not None)
        contrast = cv2.convertScaleAbs(scaled, alpha=1.55, beta=8)
        sharpened = _sharpen_experience_text_image(contrast)
        variants.extend([contrast, sharpened])

    unique: list[np.ndarray] = []
    seen: set[tuple[tuple[int, ...], bytes]] = set()
    for variant in variants:
        key = (tuple(int(part) for part in variant.shape), variant.tobytes())
        if key in seen:
            continue
        seen.add(key)
        unique.append(variant)
    return unique


def _crop_experience_tooltip_text_image(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3]
    sample = bgr.astype(np.float32)
    blue = sample[:, :, 0]
    green = sample[:, :, 1]
    red = sample[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    mask = (luminance >= 135.0) & (chroma <= 95.0)
    line_band = _experience_tooltip_exp_line_band(mask)
    if line_band is not None:
        row_top, row_bottom = line_band
        line_mask = mask[row_top:row_bottom]
        line_ys, line_xs = np.nonzero(line_mask)
        if line_xs.size and line_ys.size:
            top = max(0, row_top + int(line_ys.min()) - 4)
            bottom = min(bgr.shape[0], row_top + int(line_ys.max()) + 5)
            left_padding = max(12, round((row_bottom - row_top) * 1.2))
            left = max(0, int(line_xs.min()) - left_padding)
            right = min(bgr.shape[1], int(line_xs.max()) + 7)
            if right - left >= 20 and bottom - top >= 8:
                return bgr[top:bottom, left:right].copy()

    ys, xs = np.nonzero(mask)
    if not xs.size or not ys.size:
        return bgr
    top = max(0, int(ys.min()) - 4)
    bottom = min(bgr.shape[0], int(ys.max()) + 5)
    left_padding = max(12, round((bottom - top) * 1.2))
    left = max(0, int(xs.min()) - left_padding)
    right = min(bgr.shape[1], int(xs.max()) + 7)
    if right - left < 20 or bottom - top < 8:
        return bgr
    return bgr[top:bottom, left:right].copy()


def _strip_experience_tooltip_exp_prefix_image(image: np.ndarray) -> np.ndarray | None:
    bgr = image[:, :, :3]
    if bgr.size == 0 or bgr.shape[1] < 40:
        return None
    sample = bgr.astype(np.float32)
    blue = sample[:, :, 0]
    green = sample[:, :, 1]
    red = sample[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    mask = (luminance >= 135.0) & (chroma <= 95.0)
    ys, xs = np.nonzero(mask)
    if not xs.size or not ys.size:
        return None

    content_left = int(xs.min())
    content_right = int(xs.max()) + 1
    line_height = int(ys.max()) - int(ys.min()) + 1
    prefix_probe_right = min(mask.shape[1], content_left + max(18, round(line_height * 3.4)))
    if prefix_probe_right <= content_left:
        return None

    column_active = mask[:, content_left:prefix_probe_right].sum(axis=0) >= max(1, round(line_height * 0.12))
    edges = np.flatnonzero(np.diff(np.concatenate(([False], column_active, [False]))))
    runs = [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2]) if end - start >= 2]
    if len(runs) < 3:
        return None

    third_run_end = content_left + runs[2][1]
    min_digit_start = third_run_end + max(2, round(line_height * 0.18))
    active_after_prefix = np.flatnonzero(mask[:, min_digit_start:content_right].sum(axis=0) >= max(1, round(line_height * 0.12)))
    if active_after_prefix.size == 0:
        return None

    strip_left = max(0, min_digit_start + int(active_after_prefix[0]) - 2)
    if strip_left <= content_left or content_right - strip_left < 24:
        return None
    return bgr[:, strip_left:].copy()


def _experience_tooltip_exp_line_band(mask: np.ndarray) -> tuple[int, int] | None:
    if mask.size == 0 or mask.ndim != 2:
        return None
    row_counts = np.count_nonzero(mask, axis=1)
    min_row_pixels = max(4, round(mask.shape[1] * 0.015))
    active_rows = row_counts >= min_row_pixels
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active_rows):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            bands.append((start, index))
            start = None
    if start is not None:
        bands.append((start, len(active_rows)))

    min_line_width = max(60, round(mask.shape[1] * 0.18))
    for top, bottom in bands:
        if bottom - top < 5:
            continue
        _ys, xs = np.nonzero(mask[top:bottom])
        if not xs.size:
            continue
        if int(xs.max()) - int(xs.min()) + 1 >= min_line_width:
            return top, bottom
    return None


def _binarize_experience_tooltip_text_image(image: np.ndarray) -> np.ndarray | None:
    bgr = image[:, :, :3]
    if bgr.size == 0:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        17,
        -4,
    )
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def _contrast_experience_text_image(image: np.ndarray) -> np.ndarray:
    return cv2.convertScaleAbs(image[:, :, :3], alpha=1.35, beta=8)


def _sharpen_experience_text_image(image: np.ndarray) -> np.ndarray:
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    return cv2.filter2D(image[:, :, :3], -1, kernel)


def _experience_green_background_mask(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3]
    if bgr.size == 0:
        return np.zeros(bgr.shape[:2], dtype=bool)
    bgr_f = bgr.astype(np.float32)
    blue = bgr_f[:, :, 0]
    green = bgr_f[:, :, 1]
    red = bgr_f[:, :, 2]
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    return (
        (green >= EXP_OCR_GREEN_BACKGROUND_MIN_GREEN)
        & (chroma >= EXP_OCR_GREEN_BACKGROUND_MIN_CHROMA)
        & (green >= red + 8.0)
        & (green >= blue + 25.0)
    )


def _experience_green_background_ratio(image: np.ndarray) -> float:
    mask = _experience_green_background_mask(image)
    return float(mask.mean()) if mask.size else 0.0


def _experience_roi_bar_overlap_detected(image: np.ndarray) -> bool:
    green_mask = _experience_green_background_mask(image)
    return bool(green_mask.any() and _experience_green_background_is_relevant(image, green_mask))


def _experience_green_background_is_relevant(image: np.ndarray, green_mask: np.ndarray) -> bool:
    green_ratio = float(green_mask.mean()) if green_mask.size else 0.0
    bar_percent = estimate_experience_bar_percent(image[:, :, :3])
    if bar_percent is None:
        return green_ratio >= EXP_OCR_GREEN_BACKGROUND_MIN_RATIO
    return (
        EXP_OCR_GREEN_BACKGROUND_MIN_BAR_PERCENT
        <= bar_percent
        <= EXP_OCR_GREEN_BACKGROUND_MAX_BAR_PERCENT
    )


def _suppress_experience_green_bar_background(image: np.ndarray) -> np.ndarray:
    bgr = image[:, :, :3].copy()
    if bgr.size == 0:
        return bgr
    green_background = _experience_green_background_mask(bgr)
    if not _experience_green_background_is_relevant(bgr, green_background):
        return bgr
    if green_background.any():
        bgr[green_background] = EXP_OCR_GREEN_BACKGROUND_REPLACEMENT
    return bgr


def _erase_experience_green_bar_to_text_image(image: np.ndarray) -> np.ndarray | None:
    bgr = image[:, :, :3]
    if bgr.size == 0:
        return None
    green_background = _experience_green_background_mask(bgr)
    if not green_background.any() or not _experience_green_background_is_relevant(bgr, green_background):
        return None

    text_mask = _clean_experience_text_mask(_experience_binary_text_mask(bgr))
    erase_mask = green_background
    if erase_mask.any():
        kernel = np.ones((3, 3), dtype=np.uint8)
        erase_mask = cv2.dilate(erase_mask.astype(np.uint8), kernel, iterations=1).astype(bool)
    erase_mask &= ~text_mask

    prepared = np.zeros(bgr.shape, dtype=np.uint8)
    prepared[text_mask] = 255
    prepared[erase_mask] = 0
    return prepared


def estimate_experience_bar_percent(
    image: np.ndarray,
    *,
    bar_crop_left_ratio: float = EXP_OCR_BAR_CROP_LEFT_RATIO,
) -> float | None:
    bgr = image[:, :, :3].astype(np.float32)
    if bgr.size == 0:
        return None
    bar_crop_left_ratio = max(0.0, min(0.98, float(bar_crop_left_ratio)))
    if _experience_is_tight_right_text_roi(image, bar_crop_left_ratio):
        return None
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


def _experience_is_tight_right_text_roi(
    image: np.ndarray,
    bar_crop_left_ratio: float,
) -> bool:
    height, width = image.shape[:2]
    return (
        bar_crop_left_ratio >= EXP_OCR_TIGHT_RIGHT_ROI_MIN_BAR_CROP_LEFT_RATIO
        and width <= EXP_OCR_TIGHT_RIGHT_ROI_MAX_WIDTH
        and height <= EXP_OCR_TIGHT_RIGHT_ROI_MAX_HEIGHT
    )


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

__all__ = [
    name
    for name, value in globals().items()
    if callable(value) and getattr(value, "__module__", None) == __name__
]
