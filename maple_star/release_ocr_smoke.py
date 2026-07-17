from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

import cv2

from .models.experience_types import ExperienceOcrImage
from .services.experience_paddle_reader import PaddleExperienceTextReader


SMOKE_IMAGE_ENV = "MAPLE_STAR_RELEASE_OCR_SMOKE_IMAGE"
SMOKE_OUTPUT_ENV = "MAPLE_STAR_RELEASE_OCR_SMOKE_OUTPUT"
EXPECTED_CURRENT_EXP = 3796880
EXPECTED_PERCENT = 99.08


def run_release_ocr_smoke_if_requested() -> int | None:
    image_path = os.environ.get(SMOKE_IMAGE_ENV, "").strip()
    output_path = os.environ.get(SMOKE_OUTPUT_ENV, "").strip()
    if not image_path or not output_path:
        return None
    return run_release_ocr_smoke(Path(image_path), Path(output_path))


def run_release_ocr_smoke(image_path: Path, output_path: Path) -> int:
    started_at = time.perf_counter()
    marker: dict[str, object] = {
        "backend": "paddle",
        "initialization": False,
        "paddle_predict_executed": False,
        "success": False,
        "reading": None,
        "elapsed_seconds": 0.0,
        "traceback": "",
    }
    try:
        image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise FileNotFoundError(f"無法讀取 OCR smoke fixture：{image_path}")
        reader = PaddleExperienceTextReader()
        if not reader._ensure_ocr():
            raise RuntimeError(reader.unavailable_reason or "PaddleOCR 初始化失敗")
        marker["initialization"] = True
        reading = reader._read_with_paddle(
            ExperienceOcrImage(image=image, source_id="release-smoke"),
            bar_percent=None,
        )
        marker["paddle_predict_executed"] = True
        marker["reading"] = {
            "current_exp": reading.current_exp,
            "percent": reading.percent,
            "text": reading.text,
            "confidence": reading.confidence,
            "reason": reading.reason,
        }
        marker["success"] = bool(
            reading.current_exp == EXPECTED_CURRENT_EXP
            and reading.percent is not None
            and round(reading.percent, 2) == EXPECTED_PERCENT
        )
    except Exception:
        marker["traceback"] = traceback.format_exc()
    finally:
        marker["elapsed_seconds"] = time.perf_counter() - started_at
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if marker["success"] else 1
