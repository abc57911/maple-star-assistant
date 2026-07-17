from __future__ import annotations

import ast
import importlib
import inspect
import pickle
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

from maple_star.models import experience
from maple_star.models import experience_constants, experience_types
from maple_star.models import experience_tracker
from maple_star.services import experience_text_parsing
from maple_star.services import experience_image_processing
from maple_star.services import experience_pixel_ocr
from maple_star.services import experience_paddle_reader


ROOT = Path(__file__).resolve().parents[1]


class ExperienceModuleBoundaryTests(unittest.TestCase):
    def test_aggregator_reexports_leaf_types_by_identity(self) -> None:
        for name in experience_types.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_types, name))

    def test_aggregator_reexports_leaf_constants_by_identity(self) -> None:
        for name in experience_constants.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_constants, name))

    def test_aggregator_reexports_tracker_symbols_by_identity(self) -> None:
        for name in experience_tracker.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_tracker, name))

    def test_aggregator_reexports_text_parsing_symbols_by_identity(self) -> None:
        for name in experience_text_parsing.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_text_parsing, name))

    def test_aggregator_reexports_image_processing_symbols_by_identity(self) -> None:
        for name in experience_image_processing.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_image_processing, name))

    def test_aggregator_reexports_pixel_ocr_symbols_by_identity(self) -> None:
        for name in experience_pixel_ocr.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_pixel_ocr, name))

    def test_aggregator_reexports_paddle_reader_symbols_by_identity(self) -> None:
        for name in experience_paddle_reader.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(experience, name), getattr(experience_paddle_reader, name))

    def test_tracker_public_signatures_are_unchanged(self) -> None:
        tracker = experience_tracker.ExperienceEfficiencyTracker
        expected = {
            "__init__": "(self) -> 'None'",
            "reset": "(self) -> 'None'",
            "clear_transient_rejection": "(self) -> 'None'",
            "record_ocr_result": "(self, success: 'bool') -> 'None'",
            "record_exp_10m_checkpoint": "(self, current_exp: 'int') -> 'None'",
            "add_reading": "(self, now: 'float', current_exp: 'int', percent: 'float | None', *, confidence: 'float | None' = None, require_initial_confirmation: 'bool' = False) -> 'bool'",
            "snapshot": "(self, now: 'float') -> 'ExperienceSnapshot'",
            "level_total_deviation_ratio": "(self, current_exp: 'int | None', percent: 'float | None') -> 'float | None'",
        }
        for name, signature in expected.items():
            with self.subTest(name=name):
                self.assertEqual(str(inspect.signature(getattr(tracker, name))), signature)

    def test_experience_ocr_image_default_is_owned_by_constants_leaf(self) -> None:
        image = experience_types.ExperienceOcrImage(np.zeros((1, 1, 4), dtype=np.uint8))
        self.assertEqual(image.bar_crop_left_ratio, experience_constants.EXP_OCR_BAR_CROP_LEFT_RATIO)

    def test_leaf_dataclasses_round_trip_through_pickle(self) -> None:
        reading = experience_types.ExperienceTextReading(
            current_exp=123456,
            percent=78.9,
            success=True,
            source="test",
        )
        restored = pickle.loads(pickle.dumps(reading))
        self.assertEqual(restored, reading)
        self.assertIs(type(restored), experience_types.ExperienceTextReading)

    def test_pixel_runtime_state_is_owned_by_pixel_service(self) -> None:
        self.assertFalse(hasattr(experience_constants, "EXP_PIXEL_FONT_DIGIT_PROTOTYPES"))
        self.assertFalse(hasattr(experience_constants, "EXP_PIXEL_FONT_FEATURE_WEIGHTS"))
        self.assertFalse(hasattr(experience_constants, "_EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE"))
        self.assertTrue(hasattr(experience_pixel_ocr, "EXP_PIXEL_FONT_DIGIT_PROTOTYPES"))
        self.assertTrue(hasattr(experience_pixel_ocr, "EXP_PIXEL_FONT_FEATURE_WEIGHTS"))
        self.assertTrue(hasattr(experience_pixel_ocr, "_EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE"))

    def test_leaf_modules_do_not_import_experience_aggregator(self) -> None:
        for module in (
            experience_constants,
            experience_types,
            experience_tracker,
            experience_text_parsing,
            experience_image_processing,
            experience_pixel_ocr,
            experience_paddle_reader,
        ):
            with self.subTest(module=module.__name__):
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                imported = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported.update(
                    node.module or ""
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                )
                self.assertNotIn("maple_star.models.experience", imported)
                self.assertNotIn("experience", imported)

    def test_leaf_modules_import_in_clean_process(self) -> None:
        for module_name in (
            "maple_star.models.experience_constants",
            "maple_star.models.experience_types",
            "maple_star.models.experience_tracker",
            "maple_star.services.experience_text_parsing",
            "maple_star.services.experience_image_processing",
            "maple_star.services.experience_pixel_ocr",
            "maple_star.services.experience_paddle_reader",
        ):
            with self.subTest(module=module_name):
                script = (
                    "import importlib, sys; "
                    f"sys.path.insert(0, {str(ROOT)!r}); "
                    f"module = importlib.import_module({module_name!r}); "
                    f"assert module.__name__ == {module_name!r}"
                )
                result = subprocess.run(
                    [sys.executable, "-I", "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
