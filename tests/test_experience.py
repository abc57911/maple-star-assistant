import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from maple_star.experience import (
    ExperienceEfficiencyTracker,
    ExperienceOcrImage,
    ExperiencePixelFontAttempt,
    ExperienceTextReading,
    PADDLEOCR_DETECTION_MODEL_NAME,
    PADDLEOCR_LANGUAGE,
    PADDLEOCR_RECOGNITION_MODEL_NAME,
    PaddleExperienceTextReader,
    _binarize_experience_text,
    _clean_experience_text_mask,
    _experience_text_structure_score,
    _pixel_font_text_reading,
    _select_pixel_font_success,
    _suppress_experience_green_bar_background,
    estimate_experience_bar_percent,
    experience_ocr_learning_pending_dir,
    extract_paddle_text_items,
    format_duration,
    format_eta,
    format_exp_rate,
    format_ocr_success_rate,
    format_rate_confidence,
    parse_exp_percent_text,
    parse_current_exp_text,
    prepare_experience_ocr_image,
    prepare_experience_ocr_images,
    reading_from_paddle_result,
    save_experience_ocr_learning_case,
    suppress_subprocess_windows,
)


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self._localappdata_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._localappdata_dir.cleanup)
        self._localappdata_patch = patch.dict(os.environ, {"LOCALAPPDATA": self._localappdata_dir.name}, clear=False)
        self._localappdata_patch.start()
        self.addCleanup(self._localappdata_patch.stop)

    def test_paddle_reader_burst_uses_consensus_result(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(current_exp=4266438, percent=94.86, text="4266438[94.86%]", confidence=0.87, success=True),
                ExperienceTextReading(current_exp=4266438, percent=94.86, text="4266438[94.86%]", confidence=0.92, success=True),
                ExperienceTextReading(current_exp=42664381, percent=94.86, text="4266438194.86", confidence=0.96, success=True),
            ]
        )

        reading = reader.read_burst([np.zeros((1, 1, 3), dtype=np.uint8) for _ in range(3)])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 4266438)
        self.assertEqual(reading.percent, 94.86)
        self.assertEqual(reading.confidence, 0.92)

    def test_reader_prefers_structured_same_value_over_merged_roi(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(
                    current_exp=14757042,
                    percent=96.19,
                    text="14757042[96.19%]",
                    confidence=0.951,
                    success=True,
                ),
                ExperienceTextReading(
                    current_exp=14757042,
                    percent=96.19,
                    text="14757042196.19",
                    confidence=0.955,
                    success=True,
                    needs_bar_percent_guard=True,
                ),
            ]
        )

        reading = reader._read_burst_frame([np.zeros((1, 1, 3), dtype=np.uint8) for _ in range(2)])

        self.assertTrue(reading.success)
        self.assertEqual(reading.text, "14757042[96.19%]")
        self.assertFalse(reading.needs_bar_percent_guard)
        self.assertEqual(reader.read.call_count, 1)

    def test_burst_frame_uses_wide_roi_only_when_primary_fails(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(text="--", confidence=0.20, reason="EXP 數字解析失敗"),
                ExperienceTextReading(
                    current_exp=14757042,
                    percent=96.19,
                    text="14757042[96.19%]",
                    confidence=0.951,
                    success=True,
                ),
            ]
        )

        reading = reader._read_burst_frame([np.zeros((1, 1, 3), dtype=np.uint8) for _ in range(2)])

        self.assertTrue(reading.success)
        self.assertEqual(reading.text, "14757042[96.19%]")
        self.assertEqual(reader.read.call_count, 2)

    def test_paddle_reader_burst_rejects_conflicting_successes_without_consensus(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(current_exp=4266438, percent=94.86, text="4266438[94.86%]", confidence=0.87, success=True),
                ExperienceTextReading(current_exp=4266439, percent=94.86, text="4266439[94.86%]", confidence=0.92, success=True),
                ExperienceTextReading(current_exp=4266437, percent=94.86, text="4266437[94.86%]", confidence=0.89, success=True),
            ]
        )

        reading = reader.read_burst([np.zeros((1, 1, 3), dtype=np.uint8) for _ in range(3)])

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP burst 結果不一致")
        self.assertEqual(reading.confidence, 0.92)

    def test_paddle_reader_burst_rejects_tied_conflicting_consensus(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(current_exp=4266438, percent=94.86, text="4266438[94.86%]", confidence=0.87, success=True),
                ExperienceTextReading(current_exp=4266438, percent=94.86, text="4266438[94.86%]", confidence=0.91, success=True),
                ExperienceTextReading(current_exp=42664381, percent=94.86, text="42664381[94.86%]", confidence=0.92, success=True),
                ExperienceTextReading(current_exp=42664381, percent=94.86, text="42664381[94.86%]", confidence=0.96, success=True),
            ]
        )

        reading = reader.read_burst([np.zeros((1, 1, 3), dtype=np.uint8) for _ in range(4)])

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP burst 結果不一致")
        self.assertEqual(reading.confidence, 0.96)

    def test_paddle_reader_burst_frames_accepts_temporal_progression(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(current_exp=3796880, percent=99.08, text="3796880[99.08%]", confidence=0.91, success=True),
                ExperienceTextReading(current_exp=3804488, percent=99.27, text="3804488[99.27%]", confidence=0.88, success=True),
                ExperienceTextReading(current_exp=3805756, percent=99.31, text="3805756[99.31%]", confidence=0.89, success=True),
            ]
        )

        reading = reader.read_burst_frames([[np.zeros((1, 1, 3), dtype=np.uint8)] for _ in range(3)])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3805756)
        self.assertEqual(reading.percent, 99.31)

    def test_paddle_reader_burst_frames_prefers_latest_progression_over_old_consensus(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(current_exp=3696708, percent=96.46, text="3696708[96.46%]", confidence=0.96, success=True),
                ExperienceTextReading(current_exp=3696708, percent=96.46, text="3696708[96.46%]", confidence=0.95, success=True),
                ExperienceTextReading(current_exp=3704316, percent=96.66, text="3704316[96.66%]", confidence=0.89, success=True),
            ]
        )

        reading = reader.read_burst_frames([[np.zeros((1, 1, 3), dtype=np.uint8)] for _ in range(3)])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3704316)
        self.assertEqual(reading.percent, 96.66)

    def test_paddle_reader_burst_frames_prefers_primary_roi_when_wide_conflicts(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(current_exp=3796880, percent=99.08, text="3796880[99.08%]", confidence=0.88, success=True),
                ExperienceTextReading(current_exp=3804488, percent=99.27, text="3804488[99.27%]", confidence=0.89, success=True),
                ExperienceTextReading(current_exp=3805756, percent=99.31, text="3805756[99.31%]", confidence=0.90, success=True),
            ]
        )
        frames = [[np.zeros((1, 1, 3), dtype=np.uint8), np.zeros((1, 1, 3), dtype=np.uint8)] for _ in range(3)]

        reading = reader.read_burst_frames(frames)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3805756)
        self.assertEqual(reading.percent, 99.31)
        self.assertEqual(reader.read.call_count, 3)

    def test_paddle_reader_burst_paddle_success_does_not_create_learning_case(self):
        reader = PaddleExperienceTextReader()
        reader._read_burst_frame = Mock(
            return_value=ExperienceTextReading(
                current_exp=4731714,
                percent=24.91,
                text="4731714[24.91%]",
                confidence=0.95,
                success=True,
                reason="OK",
            )
        )
        primary = ExperienceOcrImage(np.full((10, 40, 3), 255, dtype=np.uint8), source_id="primary")
        wide = ExperienceOcrImage(np.full((10, 48, 3), 220, dtype=np.uint8), source_id="wide")

        with patch("maple_star.models.experience.save_experience_ocr_learning_case") as save_case:
            reading = reader.read_burst_frames([[primary, wide]])

        self.assertEqual(reading.learning_case_id, "")
        save_case.assert_not_called()
        reader._read_burst_frame.assert_called_once()
        self.assertFalse(reader._read_burst_frame.call_args.kwargs["record_learning"])

    def test_paddle_reader_burst_pixel_success_does_not_create_learning_case(self):
        reader = PaddleExperienceTextReader()
        reader._read_burst_frame = Mock(
            return_value=ExperienceTextReading(
                current_exp=4731714,
                percent=24.91,
                text="4731714[24.91%]",
                confidence=0.98,
                success=True,
                reason="OK:Pixel",
            )
        )
        primary = ExperienceOcrImage(np.full((10, 40, 3), 255, dtype=np.uint8), source_id="primary")
        wide = ExperienceOcrImage(np.full((10, 48, 3), 220, dtype=np.uint8), source_id="wide")

        with patch("maple_star.models.experience.save_experience_ocr_learning_case") as save_case:
            reading = reader.read_burst_frames([[primary, wide]])

        self.assertEqual(reading.learning_case_id, "")
        save_case.assert_not_called()

    def test_paddle_reader_burst_keeps_single_success_when_other_frames_fail(self):
        reader = PaddleExperienceTextReader()
        reader.read = Mock(
            side_effect=[
                ExperienceTextReading(text="--", confidence=0.30, reason="EXP 數字解析失敗"),
                ExperienceTextReading(current_exp=4266438, percent=94.86, text="4266438[94.86%]", confidence=0.91, success=True),
                ExperienceTextReading(text="4266438", confidence=0.66, reason="EXP 百分比解析失敗"),
            ]
        )

        reading = reader.read_burst([np.zeros((1, 1, 3), dtype=np.uint8) for _ in range(3)])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 4266438)
        self.assertEqual(reading.percent, 94.86)

    def test_parse_current_exp_before_percent_text(self):
        self.assertEqual(parse_current_exp_text("132553[18.36%]"), 132553)
        self.assertEqual(parse_current_exp_text("132,553 [18.36%]"), 132553)
        self.assertEqual(parse_current_exp_text("2,374,841[88.72%]"), 2374841)
        self.assertEqual(parse_current_exp_text("2.374.841[88.72%]"), 2374841)
        self.assertEqual(parse_current_exp_text("EXP: 132,553 [18.36%]"), 132553)

    def test_parse_current_exp_rejects_untrusted_exp_number_shape(self):
        self.assertIsNone(parse_current_exp_text("4E145[1.84%]"))
        self.assertIsNone(parse_current_exp_text("4Ｅ145[1.84%]"))
        self.assertIsNone(parse_current_exp_text("41,45[1.84%]"))
        self.assertIsNone(parse_current_exp_text("4,14,5[1.84%]"))

    def test_parse_exp_percent_from_ui_text(self):
        self.assertEqual(parse_exp_percent_text("132553[18.36%]"), 18.36)
        self.assertEqual(parse_exp_percent_text("132,553 [18.36％]"), 18.36)
        self.assertEqual(parse_exp_percent_text("13255318.36%"), 18.36)
        self.assertEqual(parse_exp_percent_text("18%"), 18.0)
        self.assertEqual(parse_exp_percent_text("283744[2 7 :0671"), 27.06)
        self.assertEqual(parse_exp_percent_text("283744[27.06X]"), 27.06)
        self.assertEqual(parse_exp_percent_text("1448234[6108%]"), 61.08)

    def test_parse_current_exp_uses_percent_hint_when_ocr_merges_digits(self):
        self.assertEqual(parse_current_exp_text("1325531836", percent_hint=18.36), 132553)
        self.assertEqual(
            parse_current_exp_text("13255318.36%", parse_exp_percent_text("13255318.36%")),
            132553,
        )
        self.assertEqual(
            parse_current_exp_text("283744127:06X", parse_exp_percent_text("283744127:06X")),
            283744,
        )

    def test_extract_paddle_text_items_supports_v3_json_result(self):
        result = [{"res": {"rec_texts": ["132553[18.36%]"], "rec_scores": [0.97]}}]

        items = extract_paddle_text_items(result)

        self.assertEqual(items, [("132553[18.36%]", 0.97)])

    def test_paddle_reader_parses_current_exp_from_predict_result(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["132553[18.36%]"], "rec_scores": [0.98]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()

        reading = reader.read(np.zeros((8, 60, 4), dtype=np.uint8))

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 132553)
        self.assertEqual(reading.percent, 18.36)
        self.assertEqual(reading.text, "132553[18.36%]")

    def test_paddle_reader_requires_ui_percent(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["1325531836"], "rec_scores": [0.98]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()

        reading = reader.read(np.zeros((8, 60, 4), dtype=np.uint8))

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比解析失敗")

    def test_prepare_experience_ocr_image_crops_and_resizes_ui_text(self):
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        image[:, :, 0] = 40
        image[:, :, 1] = 210
        image[:, :, 2] = 100
        image[:, :, 3] = 255
        image[5:12, 62:112, :3] = 245

        prepared = prepare_experience_ocr_image(image)

        self.assertGreaterEqual(prepared.shape[0], 54)
        self.assertLess(prepared.shape[1], image.shape[1] * 5)

    def test_prepare_experience_ocr_images_includes_original_and_prepared(self):
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        image[:, :, 0] = 40
        image[:, :, 1] = 210
        image[:, :, 2] = 100
        image[:, :, 3] = 255
        image[5:12, 62:112, :3] = 245

        variants = prepare_experience_ocr_images(image)

        self.assertGreaterEqual(len(variants), 2)
        self.assertEqual(variants[0].shape[0], 18)
        self.assertGreater(variants[1].shape[0], variants[0].shape[0])
        self.assertGreater(variants[1].shape[1], variants[0].shape[1])

    def test_binary_fallback_removes_dense_horizontal_borders(self):
        image = np.zeros((30, 180, 4), dtype=np.uint8)
        image[:, :, 0] = 45
        image[:, :, 1] = 215
        image[:, :, 2] = 95
        image[:, :, 3] = 255
        image[2:4, :, :3] = 180
        image[26:28, :, :3] = 180
        for left in range(58, 130, 12):
            image[10:19, left : left + 5, :3] = 245

        binary = prepare_experience_ocr_images(image)[-1]
        black_density_by_row = (binary[:, :, 0] == 0).mean(axis=1)

        self.assertLess(float(black_density_by_row.max()), 0.72)

    def test_binary_fallback_keeps_text_touching_top_border(self):
        mask = np.zeros((12, 24), dtype=bool)
        mask[2:4, :] = True
        mask[4, 10:16] = True

        cleaned = _clean_experience_text_mask(mask)

        self.assertFalse(cleaned[2:4, :].any())
        self.assertTrue(cleaned[4, 10:16].all())

    def test_binary_fallback_removes_top_horizontal_border_residue(self):
        mask = np.zeros((72, 180), dtype=bool)
        mask[5:10, 0:100] = True
        mask[16:24, 40:48] = True
        mask[16:24, 56:64] = True

        cleaned = _clean_experience_text_mask(mask)

        self.assertFalse(cleaned[5:10, 0:100].any())
        self.assertTrue(cleaned[16:24, 40:48].all())
        self.assertTrue(cleaned[16:24, 56:64].all())

    def test_binary_fallback_ignores_dim_vertical_background_noise(self):
        image = np.zeros((30, 80, 4), dtype=np.uint8)
        image[:, :, :3] = 45
        image[:, :, 3] = 255
        image[8:22, 18:24, :3] = 245
        image[8:11, 24:32, :3] = 245
        image[12:24, 42:44, :3] = 170

        binary = _binarize_experience_text(image)

        self.assertIsNotNone(binary)
        assert binary is not None
        self.assertEqual(int(binary[12, 20, 0]), 0)
        self.assertEqual(int(binary[18, 43, 0]), 255)

    def test_green_bar_suppression_removes_background_without_erasing_white_text(self):
        image = np.zeros((20, 120, 4), dtype=np.uint8)
        image[:, :, :3] = 28
        image[:, :70, :3] = (40, 215, 95)
        image[:, :, 3] = 255
        image[7:14, 46:50, :3] = 245

        suppressed = _suppress_experience_green_bar_background(image)

        self.assertLess(int(suppressed[5, 20, 1]), 60)
        self.assertGreater(int(suppressed[9, 48, 1]), 220)

    def test_green_bar_suppression_handles_high_exp_fill(self):
        image = np.zeros((20, 120, 4), dtype=np.uint8)
        image[:, :, :3] = 28
        image[:, :110, :3] = (40, 215, 95)
        image[:, :, 3] = 255
        image[7:14, 96:100, :3] = 245

        suppressed = _suppress_experience_green_bar_background(image)

        self.assertLess(int(suppressed[5, 20, 1]), 60)
        self.assertLess(int(suppressed[5, 108, 1]), 60)
        self.assertGreater(int(suppressed[9, 98, 1]), 220)

    def test_binary_fallback_includes_bolder_text_variant(self):
        image = np.zeros((30, 180, 4), dtype=np.uint8)
        image[:, :, :3] = (45, 215, 95)
        image[:, :, 3] = 255
        for left in range(58, 130, 12):
            image[10:19, left : left + 5, :3] = 245

        variants = prepare_experience_ocr_images(image)

        self.assertGreaterEqual(len(variants), 4)
        normal_black = int((variants[-2][:, :, 0] == 0).sum())
        bold_black = int((variants[-1][:, :, 0] == 0).sum())
        self.assertGreater(bold_black, normal_black)

    def test_estimate_experience_bar_percent_uses_green_fill_as_guard_hint(self):
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = (30, 30, 30)
        image[:, :, 3] = 255
        image[:, :288, :3] = (40, 215, 95)

        percent = estimate_experience_bar_percent(image)

        self.assertIsNotNone(percent)
        assert percent is not None
        self.assertGreater(percent, 90.0)
        self.assertLess(percent, 100.0)

    def test_estimate_experience_bar_percent_handles_partial_low_fill_roi(self):
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = (30, 30, 30)
        image[:, :, 3] = 255
        image[:, :25, :3] = (40, 215, 95)

        percent = estimate_experience_bar_percent(image, bar_crop_left_ratio=0.34)

        self.assertIsNotNone(percent)
        assert percent is not None
        self.assertGreater(percent, 38.0)
        self.assertLess(percent, 40.0)

    def test_paddle_reader_prefers_high_confidence_raw_roi(self):
        class FakeOcr:
            def predict(self, input):
                if input.shape[0] == 30:
                    return [{"res": {"rec_texts": ["283744[27.06%]"], "rec_scores": [0.94]}}]
                return [{"res": {"rec_texts": ["288744[27.06%]"], "rec_scores": [0.89]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()

        reading = reader.read(np.zeros((30, 325, 4), dtype=np.uint8))

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 283744)
        self.assertEqual(reading.percent, 27.06)

    def test_paddle_reader_prefers_structured_binary_text_over_merged_percent(self):
        class FakeOcr:
            def __init__(self):
                self.calls = 0

            def predict(self, input):
                self.calls += 1
                if self.calls == 1:
                    return [{"res": {"rec_texts": ["1960868197.028"], "rec_scores": [0.96]}}]
                if self.calls == 2:
                    return [{"res": {"rec_texts": ["1960262197.088 1"], "rec_scores": [0.62]}}]
                return [{"res": {"rec_texts": ["1960363[97.03%]"], "rec_scores": [0.91]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, 0] = 45
        image[:, :, 1] = 120
        image[:, :, 2] = 45
        image[:, :, 3] = 255
        for left in range(70, 220, 16):
            image[10:19, left : left + 6, :3] = 245

        reading = reader.read(image)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 1960363)
        self.assertEqual(reading.percent, 97.03)
        self.assertGreaterEqual(reader.ocr.calls, 3)

    def test_paddle_reader_prefers_exact_percent_marker_over_repaired_noise(self):
        class FakeOcr:
            def __init__(self):
                self.calls = 0

            def predict(self, input):
                self.calls += 1
                if self.calls == 1:
                    return [{"res": {"rec_texts": ["14757042[96.19%]"], "rec_scores": [0.958]}}]
                return [{"res": {"rec_texts": ["14757042[96.13*]"], "rec_scores": [0.961]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = (30, 30, 30)
        image[:, :, 3] = 255
        image[:, :288, :3] = (40, 215, 95)

        reading = reader.read(image)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 14757042)
        self.assertEqual(reading.percent, 96.19)
        self.assertEqual(reading.text, "14757042[96.19%]")

    def test_paddle_reader_prefers_binary_candidate_over_conflicting_raw_candidate(self):
        class FakeOcr:
            def __init__(self):
                self.calls = 0

            def predict(self, input):
                self.calls += 1
                if self.calls == 1:
                    return [{"res": {"rec_texts": ["2828712[99.91]"], "rec_scores": [0.92]}}]
                if self.calls == 2:
                    return [{"res": {"rec_texts": ["3828712199.91X"], "rec_scores": [0.88]}}]
                return [{"res": {"rec_texts": ["3828712[99.9141]"], "rec_scores": [0.91]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = 30
        image[:, :, 3] = 255
        for left in range(70, 220, 16):
            image[10:19, left : left + 6, :3] = 245

        reading = reader.read(image)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3828712)
        self.assertEqual(reading.percent, 99.91)

    def test_paddle_reader_prefers_missing_open_bracket_candidate_over_binary_percent_noise(self):
        class FakeOcr:
            def __init__(self):
                self.calls = 0

            def predict(self, input):
                self.calls += 1
                if self.calls == 1:
                    return [{"res": {"rec_texts": ["159557139.47%]"], "rec_scores": [0.86]}}]
                if self.calls == 2:
                    return [{"res": {"rec_texts": ["159557139.47%]"], "rec_scores": [0.96]}}]
                if self.calls == 3:
                    return [{"res": {"rec_texts": ["1595571[33.47]"], "rec_scores": [0.95]}}]
                return [{"res": {"rec_texts": ["1595571[33.473]"], "rec_scores": [0.92]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = 30
        image[:, :, 3] = 255
        for left in range(70, 220, 16):
            image[10:19, left : left + 6, :3] = 245

        reading = reader.read(image)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 1595571)
        self.assertEqual(reading.percent, 39.47)

    def test_paddle_reader_prefers_original_nonbinary_when_binary_percent_disagrees(self):
        class FakeOcr:
            def __init__(self):
                self.calls = 0

            def predict(self, input):
                self.calls += 1
                if self.calls == 1:
                    return [{"res": {"rec_texts": ["1577819[39.03X]"], "rec_scores": [0.864]}}]
                if self.calls == 2:
                    return [{"res": {"rec_texts": ["1577819[89.03X]"], "rec_scores": [0.886]}}]
                if self.calls == 3:
                    return [{"res": {"rec_texts": ["1577819[38.03*]"], "rec_scores": [0.899]}}]
                return [{"res": {"rec_texts": ["1577819[38.037]"], "rec_scores": [0.882]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = 30
        image[:, :, 3] = 255
        for left in range(70, 220, 16):
            image[10:19, left : left + 6, :3] = 245

        reading = reader.read(image)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 1577819)
        self.assertEqual(reading.percent, 39.03)

    def test_paddle_reader_uses_bar_hint_to_resolve_percent_disagreement(self):
        class FakeOcr:
            def __init__(self):
                self.calls = 0

            def predict(self, input):
                self.calls += 1
                if self.calls == 1:
                    return [{"res": {"rec_texts": ["1577819[39.03X]"], "rec_scores": [0.864]}}]
                if self.calls == 2:
                    return [{"res": {"rec_texts": ["1577819[89.03X]"], "rec_scores": [0.886]}}]
                if self.calls == 3:
                    return [{"res": {"rec_texts": ["1577819[38.03*]"], "rec_scores": [0.899]}}]
                return [{"res": {"rec_texts": ["1577819[38.037]"], "rec_scores": [0.882]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = 30
        image[:, :, 3] = 255
        image[:, :25, :3] = (40, 215, 95)
        for left in range(70, 220, 16):
            image[10:19, left : left + 6, :3] = 245

        reading = reader.read(ExperienceOcrImage(image, bar_crop_left_ratio=0.34))

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 1577819)
        self.assertEqual(reading.percent, 39.03)

    def test_paddle_reader_rejects_weak_merged_percent_structure(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["237484188.72%"], "rec_scores": [0.98]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()

        reading = reader.read(np.zeros((30, 325, 4), dtype=np.uint8))

        self.assertFalse(reading.success)
        self.assertIsNone(reading.current_exp)
        self.assertIsNone(reading.percent)
        self.assertEqual(reading.reason, "EXP 百分比解析失敗")

    def test_paddle_reader_rejects_missing_decimal_in_bracketed_percent(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["1448234[6108%]"], "rec_scores": [0.98]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()

        reading = reader.read(np.zeros((30, 325, 4), dtype=np.uint8))

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比解析失敗")

    def test_paddle_reader_rejects_percent_that_conflicts_with_green_bar(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["3147582[12.13%]"], "rec_scores": [0.98]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = (30, 30, 30)
        image[:, :, 3] = 255
        image[:, :288, :3] = (40, 215, 95)

        reading = reader.read(image)

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比與綠條不一致")

    def test_paddle_reader_accepts_merged_exp_percent_when_green_bar_confirms(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["4266438194.86"], "rec_scores": [0.91]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = (30, 30, 30)
        image[:, :, 3] = 255
        image[:, :293, :3] = (40, 215, 95)

        reading = reader.read(image)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 4266438)
        self.assertEqual(reading.percent, 94.86)

    def test_paddle_reader_accepts_high_fill_exp_text_with_bar_hint(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["13846565[76.90%]"], "rec_scores": [0.98]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)
        image[:, :, :3] = (30, 30, 30)
        image[:, :, 3] = 255
        image[:, :191, :3] = (40, 215, 95)

        reading = reader.read(ExperienceOcrImage(image, bar_crop_left_ratio=0.44))

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 13846565)
        self.assertEqual(reading.percent, 76.90)

    def test_paddle_reader_rejects_merged_exp_percent_without_green_bar(self):
        class FakeOcr:
            def predict(self, input):
                return [{"res": {"rec_texts": ["4266438194.86"], "rec_scores": [0.91]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()
        image = np.zeros((30, 325, 4), dtype=np.uint8)

        reading = reader.read(image)

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比需要綠條確認")

    def test_experience_text_structure_prefers_bracketed_percent(self):
        self.assertGreater(
            _experience_text_structure_score("1960363[97.03%]"),
            _experience_text_structure_score("1960868197.028"),
        )

    def test_reading_from_paddle_result_repairs_percent_symbol_read_as_x(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744[27.06X]"], "rec_scores": [0.94]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 283744)
        self.assertEqual(reading.percent, 27.06)

    def test_reading_from_paddle_result_repairs_missing_percent_marker(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["3704316[96.66]"], "rec_scores": [0.91]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3704316)
        self.assertEqual(reading.percent, 96.66)

    def test_reading_from_paddle_result_accepts_missing_open_bracket_with_closing_bracket(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["158289139.16%]"], "rec_scores": [0.92]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 1582891)
        self.assertEqual(reading.percent, 39.16)

    def test_reading_from_paddle_result_accepts_safe_trailing_punctuation(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["4005069[93.93x]:"], "rec_scores": [0.90]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 4005069)
        self.assertEqual(reading.percent, 93.93)

    def test_reading_from_paddle_result_accepts_comma_decimal_inside_percent(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["739393[16,44%]"], "rec_scores": [0.86]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 739393)
        self.assertEqual(reading.percent, 16.44)

    def test_reading_from_paddle_result_normalizes_multiply_sign_as_percent_marker(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["3972101[93.16×]"], "rec_scores": [0.90]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3972101)
        self.assertEqual(reading.percent, 93.16)

    def test_reading_from_paddle_result_repairs_percent_marker_read_as_three(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["3696708[96.463]"], "rec_scores": [0.91]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3696708)
        self.assertEqual(reading.percent, 96.46)

    def test_reading_from_paddle_result_rejects_open_bracket_as_one(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744127:06X"], "rec_scores": [0.91]}}])

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比解析失敗")

    def test_reading_from_paddle_result_rejects_stray_closing_bracket_inside_exp(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["37943]6[96.66%]"], "rec_scores": [0.96]}}])

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 數字解析失敗")

    def test_reading_from_paddle_result_accepts_structured_candidate_at_089_confidence(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744[27.06%]"], "rec_scores": [0.89]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 283744)
        self.assertEqual(reading.percent, 27.06)

    def test_reading_from_paddle_result_rejects_candidate_below_accept_confidence(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744[27.06%]"], "rec_scores": [0.84]}}])

        self.assertFalse(reading.success)
        self.assertIsNone(reading.current_exp)
        self.assertEqual(reading.reason, "PaddleOCR 信心未達可信門檻")

    def test_reading_from_paddle_result_rejects_extremely_low_confidence_before_parsing(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744[27.06%]"], "rec_scores": [0.69]}}])

        self.assertFalse(reading.success)
        self.assertIsNone(reading.current_exp)
        self.assertEqual(reading.reason, "PaddleOCR 信心過低")

    def test_reading_from_paddle_result_rejects_missing_decimal_in_bracketed_percent(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["1448234[6108%]"], "rec_scores": [0.98]}}])

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比解析失敗")

    def test_reading_from_paddle_result_rejects_another_missing_decimal_in_bracketed_percent(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["942948[4195%]"], "rec_scores": [0.98]}}])

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP 百分比解析失敗")

    def test_reading_from_paddle_result_rejects_letters_inside_exp_digits(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["4E145[1.84%]"], "rec_scores": [0.89]}}])

        self.assertFalse(reading.success)
        self.assertIsNone(reading.current_exp)
        self.assertEqual(reading.percent, None)
        self.assertEqual(reading.reason, "EXP 數字解析失敗")

    def test_reading_from_paddle_result_rejects_fullwidth_letters_inside_exp_digits(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["4Ｅ145[1.84%]"], "rec_scores": [0.89]}}])

        self.assertFalse(reading.success)
        self.assertIsNone(reading.current_exp)
        self.assertEqual(reading.reason, "EXP 數字解析失敗")

    def test_reading_from_paddle_result_rejects_bad_exp_grouping(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["41,45[1.84%]"], "rec_scores": [0.92]}}])

        self.assertFalse(reading.success)
        self.assertIsNone(reading.current_exp)
        self.assertEqual(reading.reason, "EXP 數字解析失敗")

    def test_reading_from_paddle_result_accepts_exp_label_and_grouping(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["EXP: 2,374,841 [88.72%]"], "rec_scores": [0.96]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 2374841)
        self.assertEqual(reading.percent, 88.72)

    def test_experience_tracker_records_ocr_success_rate_and_reset_clears_it(self):
        tracker = ExperienceEfficiencyTracker()

        tracker.record_ocr_result(False)
        tracker.record_ocr_result(True)

        snapshot = tracker.snapshot(1.0)
        self.assertEqual(snapshot.ocr_attempt_count, 2)
        self.assertEqual(snapshot.ocr_success_count, 1)
        self.assertEqual(snapshot.ocr_success_rate, 0.5)

        tracker.reset()
        snapshot = tracker.snapshot(2.0)
        self.assertEqual(snapshot.ocr_attempt_count, 0)
        self.assertEqual(snapshot.ocr_success_count, 0)
        self.assertIsNone(snapshot.ocr_success_rate)
        self.assertEqual(snapshot.sample_attempt_count, 0)
        self.assertEqual(snapshot.sample_accept_count, 0)
        self.assertIsNone(snapshot.sample_accept_rate)

    def test_experience_tracker_records_sample_accept_rate_separately_from_ocr(self):
        tracker = ExperienceEfficiencyTracker()

        self.assertTrue(tracker.add_reading(0.0, 100000, 10.0))
        self.assertFalse(tracker.add_reading(5.0, 18886119, 10.01))
        tracker.record_ocr_result(True)
        tracker.record_ocr_result(True)

        snapshot = tracker.snapshot(5.0)
        self.assertEqual(snapshot.sample_attempt_count, 2)
        self.assertEqual(snapshot.sample_accept_count, 1)
        self.assertEqual(snapshot.sample_accept_rate, 0.5)
        self.assertEqual(snapshot.ocr_attempt_count, 2)
        self.assertEqual(snapshot.ocr_success_count, 2)
        self.assertEqual(snapshot.ocr_success_rate, 1.0)

    def test_experience_tracker_rejects_lost_exp_prefix_instead_of_correcting(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 3901093, 91.49))
        self.assertTrue(tracker.add_reading(10.0, 3913773, 91.79))

        self.assertFalse(tracker.add_reading(20.0, 3320113, 91.94))

        snapshot = tracker.snapshot(20.0)
        self.assertEqual(snapshot.current_exp, 3913773)
        self.assertIn("樣本拒絕", snapshot.status)

    def test_experience_tracker_rejects_percent_regression_instead_of_correcting(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 3873137, 90.84))
        self.assertTrue(tracker.add_reading(10.0, 3877001, 90.93))

        self.assertFalse(tracker.add_reading(20.0, 3878269, 90.36))

        snapshot = tracker.snapshot(20.0)
        self.assertEqual(snapshot.current_exp, 3877001)
        self.assertEqual(snapshot.current_percent, 90.93)
        self.assertIn("樣本拒絕", snapshot.status)

    def test_experience_tracker_repairs_green_bar_three_read_as_eight(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 5294931, 76.83))

        self.assertTrue(tracker.add_reading(5.0, 5805653, 76.98))
        snapshot = tracker.snapshot(5.0)

        self.assertEqual(snapshot.current_exp, 5305653)
        self.assertEqual(tracker.total_gained_exp, 10722)
        self.assertEqual(snapshot.current_percent, 76.98)

    def test_experience_tracker_rebases_repeated_trusted_conflicting_reading(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 13186620, 78.24, confidence=0.98))

        self.assertFalse(tracker.add_reading(5.0, 13846565, 76.90, confidence=0.98))
        pending = tracker.snapshot(5.0)
        self.assertEqual(pending.current_exp, 13186620)
        self.assertTrue(pending.status.startswith("樣本拒絕：基準修正候選"))

        self.assertTrue(tracker.add_reading(10.0, 13856565, 76.95, confidence=0.98))
        snapshot = tracker.snapshot(10.0)

        self.assertEqual(snapshot.current_exp, 13856565)
        self.assertEqual(snapshot.sample_count, 2)
        self.assertEqual(tracker.sample_attempt_count, 3)
        self.assertEqual(tracker.sample_accept_count, 2)

    def test_experience_tracker_requires_confirmed_initial_baseline_when_requested(self):
        tracker = ExperienceEfficiencyTracker()

        self.assertFalse(
            tracker.add_reading(
                0.0,
                12846656,
                76.90,
                confidence=0.98,
                require_initial_confirmation=True,
            )
        )
        first = tracker.snapshot(0.0)
        self.assertIsNone(first.current_exp)
        self.assertEqual(first.status, "等待基準二次確認")

        self.assertFalse(
            tracker.add_reading(
                5.0,
                13846565,
                76.90,
                confidence=0.98,
                require_initial_confirmation=True,
            )
        )
        self.assertIsNone(tracker.snapshot(5.0).current_exp)

        self.assertTrue(
            tracker.add_reading(
                10.0,
                13856565,
                76.95,
                confidence=0.98,
                require_initial_confirmation=True,
            )
        )
        confirmed = tracker.snapshot(10.0)

        self.assertEqual(confirmed.current_exp, 13856565)
        self.assertEqual(confirmed.current_percent, 76.95)
        self.assertEqual(confirmed.sample_count, 1)

    def test_pixel_reader_handles_live7_to_live12_without_paddle(self):
        fixture_dir = Path(__file__).with_name("fixtures") / "experience_ocr"
        manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
        sample_ids = {
            "live7_20260507_ocr_13846565_7690",
            "live8_20260507_ocr_14211700_7893",
            "live9_20260507_ocr_16260166_9031",
            "live10_20260507_ocr_16514298_9172",
            "live11_20260507_ocr_16537454_9185",
            "live12_20260507_ocr_16579564_9283",
        }
        samples = [sample for sample in manifest.get("samples", []) if sample.get("id") in sample_ids]
        self.assertEqual(len(samples), len(sample_ids))

        reader = PaddleExperienceTextReader()
        reader._read_with_paddle = Mock(side_effect=AssertionError("Pixel OCR should not need Paddle fallback"))

        false_accepts: list[str] = []
        for sample in samples:
            image = cv2.imread(str(fixture_dir / sample["file"]), cv2.IMREAD_UNCHANGED)
            self.assertIsNotNone(image, sample["file"])
            reading = reader.read(ExperienceOcrImage(image=image, source_id=sample["id"]))
            expected_exp = int(sample["current_exp"])
            expected_percent = float(sample["percent"])
            if (
                not reading.success
                or reading.current_exp != expected_exp
                or reading.percent is None
                or round(reading.percent, 2) != round(expected_percent, 2)
            ):
                false_accepts.append(
                    f"{sample['id']}: expected={expected_exp}[{expected_percent:.2f}%] "
                    f"got={reading.current_exp}[{reading.percent}] text={reading.text!r} reason={reading.reason}"
                )

        self.assertEqual(false_accepts, [], "\n".join(false_accepts))
        reader._read_with_paddle.assert_not_called()

    def test_pixel_reader_has_no_false_accepts_on_labeled_fixtures(self):
        fixture_dir = Path(__file__).with_name("fixtures") / "experience_ocr"
        manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
        samples = manifest.get("samples", [])
        self.assertTrue(samples)

        reader = PaddleExperienceTextReader()
        reader._read_with_paddle = Mock(return_value=ExperienceTextReading(reason="fallback disabled"))
        false_accepts: list[str] = []
        with patch("maple_star.models.experience.save_experience_ocr_learning_case", return_value=""):
            for sample in samples:
                image = cv2.imread(str(fixture_dir / sample["file"]), cv2.IMREAD_UNCHANGED)
                self.assertIsNotNone(image, sample["file"])
                reading = reader.read(ExperienceOcrImage(image=image, source_id=sample["id"]))
                expected_exp = int(sample["current_exp"])
                expected_percent = float(sample["percent"])
                if (
                    reading.success
                    and (
                        reading.current_exp != expected_exp
                        or reading.percent is None
                        or round(reading.percent, 2) != round(expected_percent, 2)
                    )
                ):
                    false_accepts.append(
                        f"{sample['id']}: expected={expected_exp}[{expected_percent:.2f}%] "
                        f"got={reading.current_exp}[{reading.percent}] text={reading.text!r} reason={reading.reason}"
                    )

        self.assertEqual(false_accepts, [], "\n".join(false_accepts))

    def test_experience_ocr_fixture_images_are_not_duplicated(self):
        fixture_dir = Path(__file__).with_name("fixtures") / "experience_ocr"
        manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for sample in manifest.get("samples", []):
            path = fixture_dir / sample["file"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = seen.setdefault(digest, sample["file"])
            if previous != sample["file"]:
                duplicates.append(f"{sample['file']} duplicates {previous}")

        self.assertEqual(duplicates, [], "\n".join(duplicates))

    def test_pixel_reader_falls_back_to_paddle_without_learning_case_when_final_success(self):
        reader = PaddleExperienceTextReader()
        image = np.zeros((24, 160, 3), dtype=np.uint8)
        pixel_conflict = ExperienceTextReading(
            current_exp=None,
            percent=None,
            text="16593283[92.16%]",
            confidence=0.96,
            reason="EXP OCR 模糊數字候選不一致",
        )
        paddle_success = ExperienceTextReading(
            current_exp=16593280,
            percent=92.16,
            text="16593280[92.16%]",
            confidence=0.91,
            success=True,
            reason="OK",
        )
        reader._read_with_paddle = Mock(return_value=paddle_success)

        with (
            patch("maple_star.models.experience._read_experience_pixel_font_adaptive", return_value=pixel_conflict),
            patch("maple_star.models.experience.save_experience_ocr_learning_case", return_value="exp-unit") as save_case,
        ):
            reading = reader.read(ExperienceOcrImage(image=image, source_id="unit"))

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 16593280)
        self.assertEqual(reading.learning_case_id, "")
        reader._read_with_paddle.assert_called_once()
        save_case.assert_not_called()

    def test_pixel_reader_rejects_same_percent_low_margin_exp_conflict(self):
        conflict_candidates = [
            (
                (0.962, 1.0, 1.0, 0),
                ExperienceTextReading(
                    current_exp=16593283,
                    percent=92.16,
                    text="16593283[92.16%]",
                    confidence=0.962,
                    success=True,
                    reason="OK:Pixel",
                ),
            ),
            (
                (0.960, 1.0, 1.0, -1),
                ExperienceTextReading(
                    current_exp=16593280,
                    percent=92.16,
                    text="16593280[92.16%]",
                    confidence=0.960,
                    success=True,
                    reason="OK:Pixel",
                ),
            ),
        ]

        reading = _select_pixel_font_success(conflict_candidates, bar_percent=92.16)

        self.assertIsNotNone(reading)
        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP OCR 模糊數字候選不一致")

    def test_pixel_text_acceptance_does_not_depend_on_exp_digit_count(self):
        attempt = ExperiencePixelFontAttempt(
            image=np.zeros((16, 80, 3), dtype=np.uint8),
            bar_crop_left_ratio=0.44,
            source_id="unit",
            roi_offset=(0, 0, 0, 0),
            preprocess_variant="raw",
            attempt_id="unit:raw",
        )

        short_reading = _pixel_font_text_reading(
            "144313[0.75%]",
            0.95,
            bar_percent=0.75,
            attempt=attempt,
        )
        long_reading = _pixel_font_text_reading(
            "16579564[92.83%]",
            0.95,
            bar_percent=92.83,
            attempt=attempt,
        )

        self.assertTrue(short_reading.success)
        self.assertEqual(short_reading.current_exp, 144313)
        self.assertTrue(long_reading.success)
        self.assertEqual(long_reading.current_exp, 16579564)

    def test_experience_ocr_learning_case_writes_pending_bundle_under_localappdata(self):
        image = np.full((24, 120, 3), 255, dtype=np.uint8)
        pixel_reading = ExperienceTextReading(text="--", confidence=0.0, reason="EXP 像素字型解析失敗")
        paddle_reading = ExperienceTextReading(text="--", confidence=0.0, reason="PaddleOCR 失敗")
        final_reading = ExperienceTextReading(text="--", confidence=0.0, reason="OCR 失敗")

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
                pending_dir = experience_ocr_learning_pending_dir()
                self.assertEqual(pending_dir, Path(temp_dir) / "MapleStar" / "experience_ocr_pending")
                case_id = save_experience_ocr_learning_case(
                    [[ExperienceOcrImage(image=image, source_id="primary")]],
                    trigger="unit_failure",
                    pixel_reading=pixel_reading,
                    paddle_reading=paddle_reading,
                    final_reading=final_reading,
                    bar_percent=12.34,
                )

                case_dir = pending_dir / case_id
                metadata = json.loads((case_dir / "metadata.json").read_text(encoding="utf-8"))
                roi_exists = (case_dir / metadata["frames"][0][0]["file"]).exists()

        self.assertTrue(case_id.startswith("exp-"))
        self.assertEqual(metadata["trigger"], "unit_failure")
        self.assertEqual(metadata["bar_percent"], 12.34)
        self.assertEqual(metadata["frames"][0][0]["source_id"], "primary")
        self.assertTrue(roi_exists)
        self.assertIn("attempts", metadata["frames"][0][0])
        self.assertIn("mask_file", metadata["frames"][0][0]["attempts"][0])
        self.assertIn("segments", metadata["frames"][0][0]["attempts"][0])

    def test_experience_ocr_learning_case_deduplicates_same_reading(self):
        image = np.full((24, 120, 3), 255, dtype=np.uint8)
        pixel_reading = ExperienceTextReading(text="4652609[24.4933]", confidence=0.91, reason="EXP 像素字型結構不可信")
        paddle_reading = ExperienceTextReading(
            current_exp=4652609,
            percent=24.49,
            text="4652609[24.49%]",
            confidence=0.96,
            success=True,
            reason="OK",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
                first_id = save_experience_ocr_learning_case(
                    [[ExperienceOcrImage(image=image, source_id="primary")]],
                    trigger="pixel_to_paddle_fallback",
                    pixel_reading=pixel_reading,
                    paddle_reading=paddle_reading,
                    final_reading=paddle_reading,
                )
                second_id = save_experience_ocr_learning_case(
                    [[ExperienceOcrImage(image=image.copy(), source_id="primary")]],
                    trigger="pixel_to_paddle_fallback",
                    pixel_reading=ExperienceTextReading(
                        text="4652609[24.49%][.",
                        confidence=0.88,
                        reason="EXP 像素字型結構不可信",
                    ),
                    paddle_reading=paddle_reading,
                    final_reading=paddle_reading,
                )
                cases = list((experience_ocr_learning_pending_dir()).glob("*/metadata.json"))

        self.assertEqual(second_id, first_id)
        self.assertEqual(len(cases), 1)

    def test_experience_ocr_learning_case_skips_blank_roi(self):
        image = np.zeros((24, 120, 3), dtype=np.uint8)
        final_reading = ExperienceTextReading(text="--", confidence=0.0, reason="OCR 失敗")

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}, clear=False):
                case_id = save_experience_ocr_learning_case(
                    [[ExperienceOcrImage(image=image, source_id="primary")]],
                    trigger="ocr_failure",
                    pixel_reading=None,
                    paddle_reading=None,
                    final_reading=final_reading,
                )
                pending_dir = experience_ocr_learning_pending_dir()

        self.assertEqual(case_id, "")
        self.assertFalse(pending_dir.exists())

    def test_learning_service_promotes_pending_case_to_fixture_manifest(self):
        from maple_star.services import experience_ocr_learning as learning_service

        image = np.full((12, 80, 3), 255, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pending_root = root / "pending"
            case_dir = pending_root / "exp-unit"
            case_dir.mkdir(parents=True)
            cv2.imwrite(str(case_dir / "roi.png"), image)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            [
                                {
                                    "file": "roi.png",
                                    "attempts": [
                                        {
                                            "file": "attempt.png",
                                            "candidates": [{"text": "2043879[10.75%]"}],
                                        }
                                    ],
                                }
                            ]
                        ]
                    }
                ),
                encoding="utf-8",
            )
            attempt_image = np.full((12, 80, 3), 128, dtype=np.uint8)
            cv2.imwrite(str(case_dir / "attempt.png"), attempt_image)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            manifest_path = fixture_dir / "manifest.json"
            old_fixture = fixture_dir / "exp-unit_ocr_2043000_1074.png"
            cv2.imwrite(str(old_fixture), np.full((12, 80, 3), 64, dtype=np.uint8))
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "id": "exp-unit_ocr_2043000_1074",
                                "file": old_fixture.name,
                                "current_exp": 2043000,
                                "percent": 10.74,
                                "text": "2043000[10.74%]",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(learning_service, "FIXTURE_DIR", fixture_dir),
                patch.object(learning_service, "MANIFEST_PATH", manifest_path),
                patch.object(learning_service, "experience_ocr_learning_pending_dir", return_value=pending_root),
            ):
                result = learning_service.promote_experience_ocr_learning_case(
                    "exp-unit",
                    "2043879[10.75%]",
                )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            promoted_image = cv2.imread(str(fixture_dir / manifest["samples"][0]["file"]), cv2.IMREAD_UNCHANGED)

        self.assertEqual(result["sample_id"], "exp-unit_ocr_2043879_1075")
        self.assertEqual(len(manifest["samples"]), 1)
        self.assertEqual(manifest["samples"][0]["current_exp"], 2043879)
        self.assertEqual(manifest["samples"][0]["percent"], 10.75)
        self.assertIsNotNone(promoted_image)
        self.assertEqual(int(promoted_image[0, 0, 0]), 128)
        self.assertFalse(old_fixture.exists())

    def test_learning_service_dedupes_and_deletes_pending_cases(self):
        from maple_star.services import experience_ocr_learning as learning_service

        with tempfile.TemporaryDirectory() as temp_dir:
            pending_root = Path(temp_dir) / "pending"
            for case_id in ("exp-a", "exp-b"):
                case_dir = pending_root / case_id
                case_dir.mkdir(parents=True)
                pixel_reason = "EXP 像素字型信心過低" if case_id == "exp-a" else "EXP 像素字型結構不可信"
                (case_dir / "metadata.json").write_text(
                    json.dumps(
                        {
                            "id": case_id,
                            "created_at": case_id,
                            "trigger": "pixel_to_paddle_fallback",
                            "reading_key": "4652609[24.49%]",
                            "pixel_reason": pixel_reason,
                        }
                    ),
                    encoding="utf-8",
                )

            with patch.object(learning_service, "experience_ocr_learning_pending_dir", return_value=pending_root):
                duplicates = learning_service.dedupe_experience_ocr_learning_cases()
                kept_exists = (pending_root / "exp-a").exists()
                removed_exists = (pending_root / "exp-b").exists()

        self.assertEqual(duplicates, [{"id": "exp-b", "duplicate_of": "exp-a"}])
        self.assertFalse(removed_exists)
        self.assertTrue(kept_exists)

    def test_learning_service_hides_resolved_fallback_and_tracker_cases(self):
        from maple_star.services import experience_ocr_learning as learning_service

        with tempfile.TemporaryDirectory() as temp_dir:
            pending_root = Path(temp_dir) / "pending"
            for case_id, trigger, success in (
                ("exp-fallback", "pixel_to_paddle_fallback", True),
                ("exp-tracker", "tracker_rejection", True),
                ("exp-failure", "ocr_failure", False),
            ):
                case_dir = pending_root / case_id
                case_dir.mkdir(parents=True)
                (case_dir / "metadata.json").write_text(
                    json.dumps(
                        {
                            "id": case_id,
                            "created_at": case_id,
                            "trigger": trigger,
                            "final_reading": {
                                "success": success,
                                "text": "4732309[24.91%]",
                                "reason": "OK" if success else "OCR 失敗",
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            with patch.object(learning_service, "experience_ocr_learning_pending_dir", return_value=pending_root):
                cases = learning_service.list_experience_ocr_learning_cases()

        self.assertEqual([case["id"] for case in cases], ["exp-failure"])

    def test_learning_service_dedupes_fixture_promotions_from_same_case(self):
        from maple_star.services import experience_ocr_learning as learning_service

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            old_file = fixture_dir / "exp-unit_ocr_4731672_2491.png"
            new_file = fixture_dir / "exp-unit_ocr_4731707_2491.png"
            cv2.imwrite(str(old_file), np.full((8, 20, 3), 64, dtype=np.uint8))
            cv2.imwrite(str(new_file), np.full((8, 20, 3), 128, dtype=np.uint8))
            manifest_path = fixture_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "id": "exp-unit_ocr_4731672_2491",
                                "file": old_file.name,
                                "current_exp": 4731672,
                                "percent": 24.91,
                                "text": "4731672[24.91%]",
                            },
                            {
                                "id": "exp-unit_ocr_4731707_2491",
                                "file": new_file.name,
                                "current_exp": 4731707,
                                "percent": 24.91,
                                "text": "4731707[24.91%]",
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(learning_service, "FIXTURE_DIR", fixture_dir),
                patch.object(learning_service, "MANIFEST_PATH", manifest_path),
            ):
                removed = learning_service.dedupe_experience_ocr_fixtures_by_case_prefix()

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_exists = old_file.exists()
            new_exists = new_file.exists()

        self.assertEqual(
            removed,
            [
                {
                    "id": "exp-unit_ocr_4731672_2491",
                    "duplicate_of": "exp-unit_ocr_4731707_2491",
                    "text": "4731672[24.91%]",
                }
            ],
        )
        self.assertFalse(old_exists)
        self.assertTrue(new_exists)
        self.assertEqual([sample["id"] for sample in manifest["samples"]], ["exp-unit_ocr_4731707_2491"])

    def test_learning_service_removes_failed_promoted_fixture_sample(self):
        from maple_star.services import experience_ocr_learning as learning_service

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            fixture_file = fixture_dir / "exp-unit_ocr_4731819_2491.png"
            cv2.imwrite(str(fixture_file), np.full((8, 20, 3), 64, dtype=np.uint8))
            manifest_path = fixture_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "id": "exp-unit_ocr_4731819_2491",
                                "file": fixture_file.name,
                                "current_exp": 4731819,
                                "percent": 24.91,
                                "text": "4731819[24.91%]",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(learning_service, "FIXTURE_DIR", fixture_dir),
                patch.object(learning_service, "MANIFEST_PATH", manifest_path),
            ):
                removed = learning_service.remove_experience_ocr_fixture_sample("exp-unit_ocr_4731819_2491")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            fixture_exists = fixture_file.exists()

        self.assertTrue(removed)
        self.assertFalse(fixture_exists)
        self.assertEqual(manifest["samples"], [])

    def test_learning_service_fixture_pixel_validation_has_no_pending_side_effect(self):
        from maple_star.models import experience as experience_model
        from maple_star.services import experience_ocr_learning as learning_service

        image = np.full((12, 80, 3), 255, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            cv2.imwrite(str(fixture_dir / "unit.png"), image)
            sample = {
                "id": "unit",
                "file": "unit.png",
                "current_exp": 2043879,
                "percent": 10.75,
                "text": "2043879[10.75%]",
            }

            with (
                patch.object(learning_service, "FIXTURE_DIR", fixture_dir),
                patch.object(
                    experience_model,
                    "save_experience_ocr_learning_case",
                    side_effect=AssertionError("fixture validation must not create pending cases"),
                ),
            ):
                success = learning_service._fixture_sample_pixel_succeeds(sample)

        self.assertFalse(success)

    def test_paddle_reader_uses_traditional_chinese_ppocrv5_models(self):
        captured_kwargs = {}

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

        reader = PaddleExperienceTextReader()
        self.assertTrue(reader._build_ocr(FakePaddleOCR))

        self.assertNotIn("lang", captured_kwargs)
        self.assertEqual(captured_kwargs["text_detection_model_name"], PADDLEOCR_DETECTION_MODEL_NAME)
        self.assertEqual(captured_kwargs["text_recognition_model_name"], PADDLEOCR_RECOGNITION_MODEL_NAME)
        self.assertFalse(captured_kwargs["use_doc_orientation_classify"])
        self.assertFalse(captured_kwargs["use_doc_unwarping"])
        self.assertFalse(captured_kwargs["use_textline_orientation"])

    def test_paddle_reader_legacy_fallback_uses_traditional_chinese_lang(self):
        calls = []

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                if "text_recognition_model_name" in kwargs:
                    raise TypeError("unsupported keyword")

        reader = PaddleExperienceTextReader()
        self.assertTrue(reader._build_ocr(FakePaddleOCR))

        self.assertEqual(calls[-1]["lang"], PADDLEOCR_LANGUAGE)
        self.assertFalse(calls[-1]["use_angle_cls"])

    def test_paddle_fallback_reaches_90_percent_accuracy_on_labeled_fixtures(self):
        fixture_dir = Path(__file__).with_name("fixtures") / "experience_ocr"
        manifest_path = fixture_dir / "manifest.json"
        if not manifest_path.exists():
            self.skipTest("缺少 EXP OCR fixture manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pixel_primary_ids = {
            "live7_20260507_ocr_13846565_7690",
            "live8_20260507_ocr_14211700_7893",
            "live9_20260507_ocr_16260166_9031",
            "live10_20260507_ocr_16514298_9172",
            "live11_20260507_ocr_16537454_9185",
            "live12_20260507_ocr_16579564_9283",
        }
        samples = [
            sample
            for sample in manifest.get("samples", [])
            if sample.get("id") not in pixel_primary_ids
        ]
        if not samples:
            self.skipTest("缺少 EXP OCR fixture samples")

        reader = PaddleExperienceTextReader()
        if not reader._ensure_ocr():
            self.skipTest(reader.unavailable_reason or "PaddleOCR 不可用")

        correct = 0
        false_accepts: list[str] = []
        misses: list[str] = []
        for sample in samples:
            image = cv2.imread(str(fixture_dir / sample["file"]), cv2.IMREAD_UNCHANGED)
            self.assertIsNotNone(image, sample["file"])
            ocr_image = ExperienceOcrImage(image=image, source_id=sample["id"])
            reading = reader._read_with_paddle(
                ocr_image,
                bar_percent=estimate_experience_bar_percent(
                    image,
                    bar_crop_left_ratio=ocr_image.bar_crop_left_ratio,
                ),
            )
            expected_exp = int(sample["current_exp"])
            expected_percent = float(sample["percent"])
            if (
                reading.success
                and reading.current_exp == expected_exp
                and reading.percent is not None
                and round(reading.percent, 2) == round(expected_percent, 2)
            ):
                correct += 1
                continue
            detail = (
                f"{sample['id']}: expected={expected_exp}[{expected_percent:.2f}%] "
                f"got={reading.current_exp}[{reading.percent}] text={reading.text!r} reason={reading.reason}"
            )
            if reading.success:
                false_accepts.append(detail)
            else:
                misses.append(detail)

        self.assertEqual(false_accepts, [], "\n".join(false_accepts))
        minimum_correct = (len(samples) * 90 + 99) // 100
        self.assertGreaterEqual(correct, minimum_correct, "\n".join(misses))

    def test_paddle_reader_suppresses_noisy_initialization_output(self):
        fake_module = types.ModuleType("paddleocr")

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                print("Creating model")
                print("Using cached files", file=sys.stderr)
                warnings.warn("No ccache found. Please be aware that recompiling all source files may be required.")

        fake_module.PaddleOCR = FakePaddleOCR
        original_module = sys.modules.get("paddleocr")
        sys.modules["paddleocr"] = fake_module
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            reader = PaddleExperienceTextReader()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertTrue(reader._ensure_ocr())
        finally:
            if original_module is None:
                sys.modules.pop("paddleocr", None)
            else:
                sys.modules["paddleocr"] = original_module

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_paddle_reader_initialization_uses_hidden_subprocess_context(self):
        fake_module = types.ModuleType("paddleocr")
        events = []

        class FakeHiddenContext:
            def __enter__(self):
                events.append("hidden-enter")

            def __exit__(self, exc_type, exc, traceback):
                events.append("hidden-exit")

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                events.append("ocr-init")

        fake_module.PaddleOCR = FakePaddleOCR
        original_module = sys.modules.get("paddleocr")
        sys.modules["paddleocr"] = fake_module
        try:
            reader = PaddleExperienceTextReader()
            with patch("maple_star.models.experience.suppress_subprocess_windows", return_value=FakeHiddenContext()):
                self.assertTrue(reader._ensure_ocr())
        finally:
            if original_module is None:
                sys.modules.pop("paddleocr", None)
            else:
                sys.modules["paddleocr"] = original_module

        self.assertEqual(events, ["hidden-enter", "ocr-init", "hidden-exit"])

    def test_suppress_subprocess_windows_hides_windows_subprocesses(self):
        calls = []
        original_popen = subprocess.Popen

        class FakePopen:
            def __init__(self, *args, **kwargs):
                calls.append(kwargs)

        subprocess.Popen = FakePopen
        try:
            with suppress_subprocess_windows():
                subprocess.Popen(["dummy"])
        finally:
            subprocess.Popen = original_popen

        self.assertEqual(len(calls), 1)
        if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
            self.assertNotIn("creationflags", calls[0])
            self.assertNotIn("startupinfo", calls[0])
            return

        self.assertTrue(calls[0]["creationflags"] & subprocess.CREATE_NO_WINDOW)
        startupinfo = calls[0]["startupinfo"]
        self.assertTrue(startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startupinfo.wShowWindow, 0)

    def test_tracker_reports_exp_rates_and_eta(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 10.0)
        tracker.add_reading(60.0, 7000, 70.0)

        snapshot = tracker.snapshot(60.0)

        self.assertEqual(snapshot.xp_per_5m, 30000.0)
        self.assertEqual(snapshot.xp_per_10m, 60000.0)
        self.assertEqual(snapshot.xp_per_hour, 360000.0)
        self.assertIsNotNone(snapshot.eta_seconds)

    def test_tracker_rejects_outlier_exp_and_keeps_last_statistics(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 100000, 10.0))
        self.assertTrue(tracker.add_reading(60.0, 110000, 11.0))
        before = tracker.snapshot(60.0)

        self.assertFalse(tracker.add_reading(68.0, 18886119, 21.03))
        after = tracker.snapshot(68.0)

        self.assertEqual(after.current_exp, 110000)
        self.assertEqual(after.xp_per_5m, before.xp_per_5m)
        self.assertEqual(after.xp_per_10m, before.xp_per_10m)
        self.assertEqual(after.xp_per_hour, before.xp_per_hour)
        self.assertEqual(after.sample_count, 2)
        self.assertTrue(after.status.startswith("樣本拒絕"))

    def test_tracker_rebases_bad_initial_sample_before_statistics_start(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 18886119, 21.03))

        self.assertFalse(tracker.add_reading(8.0, 132553, 18.36))
        baseline = tracker.snapshot(8.0)

        self.assertEqual(baseline.current_exp, 18886119)
        self.assertEqual(baseline.sample_count, 1)
        self.assertIsNone(baseline.xp_per_5m)
        self.assertTrue(baseline.status.startswith("樣本拒絕：基準修正候選"))

        self.assertTrue(tracker.add_reading(13.0, 133553, 18.42))
        snapshot = tracker.snapshot(13.0)

        self.assertEqual(snapshot.current_exp, 133553)
        self.assertEqual(snapshot.sample_count, 2)

    def test_tracker_clears_transient_rejection_when_resuming(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 18886119, 21.03))
        self.assertFalse(tracker.add_reading(8.0, 132553, 18.36))
        rejected = tracker.snapshot(8.0)
        self.assertTrue(rejected.status.startswith("樣本拒絕：基準修正候選"))
        self.assertIsNotNone(tracker.pending_rebase)

        tracker.clear_transient_rejection()
        snapshot = tracker.snapshot(9.0)

        self.assertIsNone(tracker.pending_rebase)
        self.assertEqual(snapshot.status, "等待下一次 EXP 樣本")
        self.assertFalse(snapshot.status.startswith("樣本拒絕"))
        self.assertEqual(snapshot.sample_count, 1)

    def test_tracker_rejects_cold_session_when_initial_exp_missed_a_digit(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 11614, 7.50))
        self.assertTrue(tracker.add_reading(30.0, 11614, 7.50))

        self.assertFalse(tracker.add_reading(60.0, 118071, 7.54))
        baseline = tracker.snapshot(60.0)

        self.assertEqual(baseline.current_exp, 11614)
        self.assertTrue(baseline.status.startswith("樣本拒絕：EXP 跳動與百分比不一致"))

    def test_tracker_does_not_rebase_to_single_huge_initial_outlier(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 2374841, 88.72))
        before = tracker.snapshot(0.0)

        self.assertFalse(tracker.add_reading(5.0, 200728289, 88.73))
        rejected = tracker.snapshot(5.0)

        self.assertEqual(tracker.last_current_exp, 2374841)
        self.assertAlmostEqual(tracker.estimated_level_total_exp, 2374841 / 0.8872)
        self.assertEqual(rejected.current_exp, before.current_exp)
        self.assertIsNone(tracker.pending_rebase)
        self.assertTrue(rejected.status.startswith("樣本拒絕：EXP 跳動與百分比不一致"))

        self.assertTrue(tracker.add_reading(10.0, 2375000, 88.73))
        snapshot = tracker.snapshot(10.0)

        self.assertEqual(snapshot.current_exp, 2375000)
        self.assertEqual(snapshot.current_percent, 88.73)
        self.assertEqual(snapshot.sample_count, 2)

    def test_tracker_displays_baseline_sample_before_rate_is_available(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 2425901, 23.13))

        snapshot = tracker.snapshot(30.0)

        self.assertEqual(snapshot.current_exp, 2425901)
        self.assertEqual(snapshot.current_percent, 23.13)
        self.assertIsNone(snapshot.xp_per_5m)
        self.assertIsNone(snapshot.xp_per_10m)
        self.assertIsNone(snapshot.xp_per_hour)
        self.assertIsNone(snapshot.eta_seconds)
        self.assertEqual(snapshot.elapsed_seconds, 30.0)
        self.assertEqual(snapshot.sample_count, 1)
        self.assertEqual(snapshot.status, "校準 EXP 基準")

    def test_tracker_rejects_non_level_exp_drop_without_resetting(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 100000, 10.0))
        self.assertTrue(tracker.add_reading(60.0, 110000, 11.0))

        self.assertFalse(tracker.add_reading(68.0, 5000, 5.0))
        snapshot = tracker.snapshot(68.0)

        self.assertEqual(snapshot.current_exp, 110000)
        self.assertEqual(snapshot.sample_count, 2)
        self.assertTrue(snapshot.status.startswith("樣本拒絕"))

    def test_tracker_rejects_regressed_exp_even_when_percent_increases(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 100000, 10.0))
        self.assertTrue(tracker.add_reading(60.0, 110000, 11.0))

        self.assertFalse(tracker.add_reading(120.0, 11500, 11.5))
        snapshot = tracker.snapshot(120.0)

        self.assertEqual(snapshot.current_exp, 110000)
        self.assertEqual(snapshot.current_percent, 11.0)
        self.assertEqual(snapshot.sample_count, 2)
        self.assertTrue(snapshot.status.startswith("樣本拒絕"))

    def test_tracker_rejects_exp_jump_inconsistent_with_percent_delta(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 1900000, 95.0))
        self.assertTrue(tracker.add_reading(60.0, 1940000, 97.0))

        self.assertFalse(tracker.add_reading(65.0, 2080000, 98.0))
        snapshot = tracker.snapshot(65.0)

        self.assertEqual(snapshot.current_exp, 1940000)
        self.assertEqual(snapshot.current_percent, 97.0)
        self.assertTrue(snapshot.status.startswith("樣本拒絕"))

    def test_tracker_rejects_exp_gain_when_percent_drops(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 2374841, 88.72))
        self.assertTrue(tracker.add_reading(5.0, 2375000, 88.73))

        self.assertFalse(tracker.add_reading(10.0, 2380000, 61.08))
        snapshot = tracker.snapshot(10.0)

        self.assertEqual(snapshot.current_exp, 2375000)
        self.assertEqual(snapshot.current_percent, 88.73)
        self.assertTrue(snapshot.status.startswith("樣本拒絕：EXP 百分比回落"))

    def test_tracker_rejects_small_digit_error_when_percent_does_not_move(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 283744, 27.06))
        self.assertTrue(tracker.add_reading(5.0, 283900, 27.08))

        self.assertFalse(tracker.add_reading(10.0, 288900, 27.08))
        snapshot = tracker.snapshot(10.0)

        self.assertEqual(snapshot.current_exp, 283900)
        self.assertEqual(snapshot.current_percent, 27.08)
        self.assertTrue(snapshot.status.startswith("樣本拒絕：EXP 跳動與百分比不一致"))

    def test_tracker_repairs_recent_accepted_outliers_after_confirmation(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 100000, 10.0))
        self.assertTrue(tracker.add_reading(60.0, 110000, 11.0))
        self.assertTrue(tracker.add_reading(70.0, 130000, 13.0))
        self.assertTrue(tracker.add_reading(80.0, 131000, 13.1))

        self.assertFalse(tracker.add_reading(90.0, 112000, 11.2))
        self.assertTrue(tracker.add_reading(100.0, 113000, 11.3))
        snapshot = tracker.snapshot(100.0)

        self.assertEqual([sample.current_exp for sample in tracker.samples], [100000, 110000, 113000])
        self.assertEqual(tracker.total_gained_exp, 13000)
        self.assertEqual(snapshot.current_exp, 113000)
        self.assertLess(snapshot.xp_per_5m or 0, 50000)

    def test_tracker_keeps_true_sample_when_lower_outlier_is_not_confirmed(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 100000, 10.0))
        self.assertTrue(tracker.add_reading(60.0, 110000, 11.0))
        self.assertTrue(tracker.add_reading(70.0, 130000, 13.0))

        self.assertFalse(tracker.add_reading(80.0, 112000, 11.2))
        self.assertTrue(tracker.add_reading(90.0, 131000, 13.1))
        snapshot = tracker.snapshot(90.0)

        self.assertEqual([sample.current_exp for sample in tracker.samples], [100000, 110000, 130000, 131000])
        self.assertEqual(snapshot.current_exp, 131000)

    def test_tracker_keeps_last_rate_when_short_window_is_temporarily_insufficient(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 10.0)
        tracker.add_reading(300.0, 7000, 70.0)
        before = tracker.snapshot(300.0)

        tracker.add_reading(301.0, 7000, 70.0)
        after = tracker.snapshot(301.0)

        self.assertEqual(after.xp_per_5m, before.xp_per_5m)
        self.assertEqual(after.current_exp, 7000)

    def test_tracker_rates_and_eta_decay_without_new_reading(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 10.0)
        tracker.add_reading(60.0, 7000, 70.0)
        before = tracker.snapshot(60.0)

        after = tracker.snapshot(660.0)

        self.assertLess(after.xp_per_5m or 0, 1000.0)
        self.assertLess(after.xp_per_10m or 0, before.xp_per_10m or 0)
        self.assertLess(after.xp_per_hour or 0, before.xp_per_hour or 0)
        self.assertGreater(after.eta_seconds or 0, before.eta_seconds or 0)
        self.assertEqual(after.current_exp, 7000)
        self.assertEqual(after.elapsed_seconds, 660.0)

    def test_tracker_hides_eta_after_rate_decays_below_displayable_speed(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 3000000, 18.50, confidence=0.95)
        tracker.add_reading(60.0, 3044878, 18.81, confidence=0.95)
        tracker.snapshot(60.0)

        snapshot = None
        for now in (600.0, 3600.0, 7200.0):
            snapshot = tracker.snapshot(now)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertIsNone(snapshot.eta_seconds)
        self.assertEqual(format_eta(snapshot.eta_seconds), "--")

    def test_tracker_handles_level_wrap_when_percent_restarts(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 9000, 90.0)
        tracker.add_reading(60.0, 500, 5.0)

        snapshot = tracker.snapshot(60.0)

        self.assertEqual(snapshot.xp_per_5m, 7500.0)

    def test_tracker_long_rate_weights_recent_trend(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 0.10)
        tracker.add_reading(1800.0, 2000, 0.20)
        tracker.add_reading(3600.0, 92000, 9.20)

        snapshot = tracker.snapshot(3600.0)

        self.assertGreater(snapshot.xp_per_hour, 91000.0)
        self.assertLess(snapshot.xp_per_hour, 180000.0)

    def test_tracker_does_not_resmooth_without_time_advancing(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 0.10)
        tracker.add_reading(60.0, 7000, 0.70)
        tracker.snapshot(60.0)
        tracker.add_reading(120.0, 25000, 2.50)
        first = tracker.snapshot(120.0)

        second = tracker.snapshot(120.0)

        self.assertEqual(second.xp_per_5m, first.xp_per_5m)
        self.assertEqual(second.xp_per_10m, first.xp_per_10m)
        self.assertEqual(second.xp_per_hour, first.xp_per_hour)

    def test_tracker_rates_converge_quickly_after_rate_change(self):
        tracker = ExperienceEfficiencyTracker()
        for index in range(5):
            captured_at = index * 60.0
            current_exp = 1000 + round(100 * captured_at)
            tracker.add_reading(captured_at, current_exp, current_exp / 10000)
            tracker.snapshot(captured_at)

        snapshot = None
        for index in range(1, 5):
            captured_at = 240.0 + index * 60.0
            current_exp = 1000 + round(100 * 240 + 300 * (captured_at - 240))
            tracker.add_reading(captured_at, current_exp, current_exp / 10000)
            snapshot = tracker.snapshot(captured_at)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertGreater(snapshot.xp_per_5m, 85000.0)
        self.assertGreater(snapshot.xp_per_10m, 130000.0)
        self.assertGreater(snapshot.xp_per_hour, 700000.0)
        self.assertLess(snapshot.xp_per_hour, 900000.0)
        self.assertEqual(format_rate_confidence(snapshot.rate_confidence), "高")

    def test_tracker_rate_confidence_reflects_ocr_reading_confidence(self):
        high_confidence = ExperienceEfficiencyTracker()
        high_confidence.add_reading(0.0, 1000, 10.0, confidence=0.95)
        high_confidence.add_reading(60.0, 7000, 70.0, confidence=0.95)
        high_snapshot = high_confidence.snapshot(60.0)

        low_confidence = ExperienceEfficiencyTracker()
        low_confidence.add_reading(0.0, 1000, 10.0, confidence=0.25)
        low_confidence.add_reading(60.0, 7000, 70.0, confidence=0.25)
        low_snapshot = low_confidence.snapshot(60.0)

        self.assertIsNotNone(high_snapshot.rate_confidence)
        self.assertIsNotNone(low_snapshot.rate_confidence)
        assert high_snapshot.rate_confidence is not None
        assert low_snapshot.rate_confidence is not None
        self.assertGreater(high_snapshot.rate_confidence, low_snapshot.rate_confidence)

    def test_format_eta(self):
        self.assertEqual(format_eta(65), "00:01:05")
        self.assertEqual(format_eta(3599), "00:59:59")
        self.assertEqual(format_eta(3661), "1:01:01")
        self.assertEqual(format_eta(10000 * 3600), "--")
        self.assertEqual(format_duration(3723), "1:02:03")

    def test_format_exp_rate(self):
        self.assertEqual(format_exp_rate(None), "--")
        self.assertEqual(format_exp_rate(9999), "9,999")
        self.assertEqual(format_exp_rate(10000), "1萬")
        self.assertEqual(format_exp_rate(84965), "8萬4")
        self.assertEqual(format_exp_rate(2001195), "200萬1")
        self.assertEqual(format_exp_rate(10759664), "1,075萬9")

    def test_format_ocr_success_rate(self):
        self.assertEqual(format_ocr_success_rate(0, 0), "--")
        self.assertEqual(format_ocr_success_rate(9, 10), "90% (9/10)")
        self.assertEqual(format_ocr_success_rate(28, 29), "96.6% (28/29)")

    def test_format_rate_confidence(self):
        self.assertEqual(format_rate_confidence(None), "--")
        self.assertEqual(format_rate_confidence(0.20), "低")
        self.assertEqual(format_rate_confidence(0.55), "中")
        self.assertEqual(format_rate_confidence(0.90), "高")


if __name__ == "__main__":
    unittest.main()
