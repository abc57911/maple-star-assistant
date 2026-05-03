import contextlib
import io
import json
import os
import subprocess
import sys
import types
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from maple_star.experience import (
    ExperienceEfficiencyTracker,
    ExperienceTextReading,
    PADDLEOCR_DETECTION_MODEL_NAME,
    PADDLEOCR_LANGUAGE,
    PADDLEOCR_RECOGNITION_MODEL_NAME,
    PaddleExperienceTextReader,
    _binarize_experience_text,
    _clean_experience_text_mask,
    _experience_text_structure_score,
    _suppress_experience_green_bar_background,
    estimate_experience_bar_percent,
    extract_paddle_text_items,
    format_duration,
    format_eta,
    format_exp_rate,
    format_ocr_success_rate,
    parse_exp_percent_text,
    parse_current_exp_text,
    prepare_experience_ocr_image,
    prepare_experience_ocr_images,
    reading_from_paddle_result,
    suppress_subprocess_windows,
)


class ExperienceTests(unittest.TestCase):
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
                ExperienceTextReading(current_exp=37968801, percent=99.08, text="37968801[99.08%]", confidence=0.98, success=True),
                ExperienceTextReading(current_exp=3804488, percent=99.27, text="3804488[99.27%]", confidence=0.89, success=True),
                ExperienceTextReading(current_exp=38044881, percent=99.27, text="38044881[99.27%]", confidence=0.98, success=True),
                ExperienceTextReading(current_exp=3805756, percent=99.31, text="3805756[99.31%]", confidence=0.90, success=True),
                ExperienceTextReading(current_exp=38057561, percent=99.31, text="38057561[99.31%]", confidence=0.98, success=True),
            ]
        )
        frames = [[np.zeros((1, 1, 3), dtype=np.uint8), np.zeros((1, 1, 3), dtype=np.uint8)] for _ in range(3)]

        reading = reader.read_burst_frames(frames)

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 3805756)
        self.assertEqual(reading.percent, 99.31)

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

    def test_paddle_reader_rejects_ambiguous_binary_percent_disagreement(self):
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

        self.assertFalse(reading.success)
        self.assertEqual(reading.reason, "EXP OCR 候選不一致")

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

    def test_paddle_reader_reaches_90_percent_accuracy_on_labeled_fixtures(self):
        fixture_dir = Path(__file__).with_name("fixtures") / "experience_ocr"
        manifest_path = fixture_dir / "manifest.json"
        if not manifest_path.exists():
            self.skipTest("缺少 EXP OCR fixture manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        samples = manifest.get("samples", [])
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
            reading = reader.read(image)
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
        accuracy = correct / len(samples)
        self.assertGreaterEqual(accuracy, 0.90, "\n".join(misses))

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
        self.assertGreater(snapshot.xp_per_10m, 160000.0)
        self.assertGreater(snapshot.xp_per_hour, 900000.0)

    def test_format_eta(self):
        self.assertEqual(format_eta(65), "00:01:05")
        self.assertEqual(format_eta(3599), "00:59:59")
        self.assertEqual(format_eta(3661), "1:01:01")
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


if __name__ == "__main__":
    unittest.main()
