from __future__ import annotations

import numpy as np

from ..constants import FULL_BAR_SNAP_PERCENT


def normalize_bar_percent(percent: float) -> float:
    percent = max(0.0, min(100.0, percent))
    if percent >= FULL_BAR_SNAP_PERCENT:
        return 100.0
    return percent


def should_drink_for_threshold(percent: float, threshold_percent: float) -> bool:
    if threshold_percent >= 100.0 and percent >= 100.0:
        return False
    return percent <= threshold_percent


def loading_screen_metrics(image: np.ndarray) -> tuple[float, float, float]:
    sample = image[::8, ::8, :3].astype(np.float32)
    blue = sample[:, :, 0]
    green = sample[:, :, 1]
    red = sample[:, :, 2]
    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    chroma = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])
    return (
        float(luminance.mean()),
        float((luminance > 210.0).mean()),
        float((chroma < 25.0).mean()),
    )


def bgra_image_to_ppm_data(
    image: np.ndarray,
    scale: int = 3,
    target_size: tuple[int, int] | None = None,
) -> bytes:
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("預覽圖片格式無效")
    scale = max(1, int(scale))
    rgb = image[:, :, :3][:, :, ::-1]
    if target_size is not None:
        target_width, target_height = target_size
        target_width = max(1, int(target_width))
        target_height = max(1, int(target_height))
        source_height, source_width, _channels = rgb.shape
        fit_scale = min(target_width / source_width, target_height / source_height)
        scaled_width = max(1, min(target_width, round(source_width * fit_scale)))
        scaled_height = max(1, min(target_height, round(source_height * fit_scale)))
        x_indexes = np.minimum(
            (np.arange(scaled_width) * source_width / scaled_width).astype(np.intp),
            source_width - 1,
        )
        y_indexes = np.minimum(
            (np.arange(scaled_height) * source_height / scaled_height).astype(np.intp),
            source_height - 1,
        )
        resized = rgb[y_indexes][:, x_indexes]
        canvas = np.full((target_height, target_width, 3), 240, dtype=np.uint8)
        left = (target_width - scaled_width) // 2
        top = (target_height - scaled_height) // 2
        canvas[top : top + scaled_height, left : left + scaled_width] = resized
        rgb = canvas
    elif scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    height, width, _channels = rgb.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + np.ascontiguousarray(rgb).tobytes()

