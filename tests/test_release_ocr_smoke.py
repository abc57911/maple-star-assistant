from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from maple_star.release_ocr_smoke import (
    SMOKE_IMAGE_ENV,
    SMOKE_OUTPUT_ENV,
    run_release_ocr_smoke,
    run_release_ocr_smoke_if_requested,
)
from tools.verify_release_ocr import _validate_marker, _validate_paddlex_model_cache


class ReleaseOcrSmokeTests(unittest.TestCase):
    def test_normal_startup_does_not_enter_smoke(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(run_release_ocr_smoke_if_requested())

    def test_smoke_writes_success_marker_after_paddle_read(self) -> None:
        reading = SimpleNamespace(
            current_exp=3796880,
            percent=99.08,
            text="3796880[99.08%]",
            confidence=0.95,
            reason="OK",
        )
        reader = Mock()
        reader._ensure_ocr.return_value = True
        reader._read_with_paddle.return_value = reading
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "marker.json"
            with (
                patch("maple_star.release_ocr_smoke.cv2.imread", return_value=np.zeros((10, 10, 3), dtype=np.uint8)),
                patch("maple_star.release_ocr_smoke.PaddleExperienceTextReader", return_value=reader),
            ):
                exit_code = run_release_ocr_smoke(Path("fixture.png"), output)

            marker = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertTrue(marker["paddle_predict_executed"])
        self.assertEqual(_validate_marker(marker), [])
        reader._read_with_paddle.assert_called_once()
        self.assertIsNone(reader._read_with_paddle.call_args.kwargs["bar_percent"])

    def test_initialization_failure_writes_failure_marker_without_predict(self) -> None:
        reader = Mock()
        reader._ensure_ocr.return_value = False
        reader.unavailable_reason = "missing model"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "marker.json"
            with (
                patch("maple_star.release_ocr_smoke.cv2.imread", return_value=np.zeros((10, 10, 3), dtype=np.uint8)),
                patch("maple_star.release_ocr_smoke.PaddleExperienceTextReader", return_value=reader),
            ):
                exit_code = run_release_ocr_smoke(Path("fixture.png"), output)

            marker = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertFalse(marker["paddle_predict_executed"])
        self.assertIn("missing model", marker["traceback"])
        reader._read_with_paddle.assert_not_called()

    def test_environment_trigger_ignores_incomplete_request(self) -> None:
        with patch.dict("os.environ", {SMOKE_IMAGE_ENV: "fixture.png", SMOKE_OUTPUT_ENV: ""}, clear=True):
            self.assertIsNone(run_release_ocr_smoke_if_requested())

    def test_model_cache_preflight_requires_complete_det_and_rec_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(RuntimeError, "禁止下載模型"):
                _validate_paddlex_model_cache({"PADDLE_PDX_CACHE_HOME": temporary_directory})

    def test_model_cache_preflight_accepts_nonempty_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_root = Path(temporary_directory)
            for model_name in ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"):
                model_root = cache_root / "official_models" / model_name
                model_root.mkdir(parents=True)
                for filename in ("config.json", "inference.json", "inference.pdiparams", "inference.yml"):
                    (model_root / filename).write_bytes(b"ready")
            self.assertEqual(
                _validate_paddlex_model_cache({"PADDLE_PDX_CACHE_HOME": temporary_directory}),
                cache_root.resolve(),
            )


if __name__ == "__main__":
    unittest.main()
