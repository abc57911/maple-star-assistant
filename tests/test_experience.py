import contextlib
import io
import sys
import types
import unittest
import warnings

import numpy as np

from maple_star.experience import (
    ExperienceEfficiencyTracker,
    PADDLEOCR_DETECTION_MODEL_NAME,
    PADDLEOCR_LANGUAGE,
    PADDLEOCR_RECOGNITION_MODEL_NAME,
    PaddleExperienceTextReader,
    extract_paddle_text_items,
    format_eta,
    parse_exp_percent_text,
    parse_current_exp_text,
    prepare_experience_ocr_image,
    prepare_experience_ocr_images,
    reading_from_paddle_result,
)


class ExperienceTests(unittest.TestCase):
    def test_parse_current_exp_before_percent_text(self):
        self.assertEqual(parse_current_exp_text("132553[18.36%]"), 132553)
        self.assertEqual(parse_current_exp_text("132,553 [18.36%]"), 132553)

    def test_parse_exp_percent_from_ui_text(self):
        self.assertEqual(parse_exp_percent_text("132553[18.36%]"), 18.36)
        self.assertEqual(parse_exp_percent_text("132,553 [18.36％]"), 18.36)
        self.assertEqual(parse_exp_percent_text("13255318.36%"), 18.36)
        self.assertEqual(parse_exp_percent_text("18%"), 18.0)
        self.assertEqual(parse_exp_percent_text("283744[2 7 :0671"), 27.06)
        self.assertEqual(parse_exp_percent_text("283744[27.06X]"), 27.06)

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

    def test_paddle_reader_prefers_high_confidence_raw_roi(self):
        class FakeOcr:
            def predict(self, input):
                if input.shape[0] == 30:
                    return [{"res": {"rec_texts": ["283744[27.06X]"], "rec_scores": [0.94]}}]
                return [{"res": {"rec_texts": ["288744[27.062]"], "rec_scores": [0.89]}}]

        reader = PaddleExperienceTextReader()
        reader.ocr = FakeOcr()

        reading = reader.read(np.zeros((30, 325, 4), dtype=np.uint8))

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 283744)
        self.assertEqual(reading.percent, 27.06)

    def test_reading_from_paddle_result_accepts_percent_symbol_noise(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744[27.06X]"], "rec_scores": [0.94]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 283744)
        self.assertEqual(reading.percent, 27.06)

    def test_reading_from_paddle_result_handles_open_bracket_as_one(self):
        reading = reading_from_paddle_result([{"res": {"rec_texts": ["283744127:06X"], "rec_scores": [0.87]}}])

        self.assertTrue(reading.success)
        self.assertEqual(reading.current_exp, 283744)
        self.assertEqual(reading.percent, 27.06)

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

    def test_tracker_reports_exp_rates_and_eta(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 10.0)
        tracker.add_reading(60.0, 7000, 70.0)

        snapshot = tracker.snapshot(60.0)

        self.assertEqual(snapshot.xp_per_minute, 6000.0)
        self.assertEqual(snapshot.xp_per_5m, 30000.0)
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
        self.assertEqual(after.xp_per_minute, before.xp_per_minute)
        self.assertEqual(after.xp_per_hour, before.xp_per_hour)
        self.assertEqual(after.sample_count, 2)
        self.assertTrue(after.status.startswith("OCR 樣本拒絕"))

    def test_tracker_rebases_bad_initial_sample_before_statistics_start(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 18886119, 21.03))

        self.assertTrue(tracker.add_reading(8.0, 132553, 18.36))
        baseline = tracker.snapshot(8.0)

        self.assertIsNone(baseline.current_exp)
        self.assertEqual(baseline.sample_count, 1)
        self.assertIsNone(baseline.xp_per_minute)
        self.assertTrue(baseline.status.startswith("基準修正"))

        self.assertTrue(tracker.add_reading(68.0, 136553, 18.91))
        snapshot = tracker.snapshot(68.0)

        self.assertEqual(snapshot.current_exp, 136553)
        self.assertAlmostEqual(snapshot.xp_per_minute, 4000.0)
        self.assertEqual(snapshot.sample_count, 2)

    def test_tracker_does_not_display_unconfirmed_first_sample(self):
        tracker = ExperienceEfficiencyTracker()
        self.assertTrue(tracker.add_reading(0.0, 2425901, 23.13))

        snapshot = tracker.snapshot(0.0)

        self.assertIsNone(snapshot.current_exp)
        self.assertIsNone(snapshot.current_percent)
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
        self.assertTrue(snapshot.status.startswith("OCR 樣本拒絕"))

    def test_tracker_keeps_last_rate_when_short_window_is_temporarily_insufficient(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 1000, 10.0)
        tracker.add_reading(60.0, 7000, 70.0)
        before = tracker.snapshot(60.0)

        tracker.add_reading(61.0, 7000, 70.0)
        after = tracker.snapshot(61.0)

        self.assertEqual(after.xp_per_minute, before.xp_per_minute)
        self.assertEqual(after.current_exp, 7000)

    def test_tracker_handles_level_wrap_when_percent_restarts(self):
        tracker = ExperienceEfficiencyTracker()
        tracker.add_reading(0.0, 9000, 90.0)
        tracker.add_reading(60.0, 500, 5.0)

        snapshot = tracker.snapshot(60.0)

        self.assertEqual(snapshot.xp_per_minute, 1500.0)

    def test_format_eta(self):
        self.assertEqual(format_eta(65), "1:05")
        self.assertEqual(format_eta(3661), "1:01:01")


if __name__ == "__main__":
    unittest.main()
