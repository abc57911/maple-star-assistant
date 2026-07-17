from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from maple_star.models.controller_state import BarDetectionDebug
from maple_star.services.hud_bar_detector import (
    DirectBarCaptureContext,
    HudBarDetector,
    HudDetectionRequest,
    HudDetectionResult,
)


class HudBarDetectorTests(unittest.TestCase):
    def test_module_does_not_import_controller_or_gui(self) -> None:
        services = Path(__file__).resolve().parents[1] / "maple_star" / "services"
        for filename in ("hud_bar_detector.py", "hud_bar_detection_algorithms.py"):
            with self.subTest(filename=filename):
                tree = ast.parse((services / filename).read_text(encoding="utf-8"))
                imports = "\n".join(
                    ast.unparse(node)
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                )
                self.assertNotIn("controllers", imports)
                self.assertNotIn("gui", imports)

    def test_request_and_result_contracts_are_immutable(self) -> None:
        self.assertTrue(HudDetectionRequest.__dataclass_params__.frozen)
        self.assertTrue(HudDetectionResult.__dataclass_params__.frozen)

    def test_controller_reexports_canonical_direct_capture_context(self) -> None:
        from maple_star.controller import DirectBarCaptureContext as facade_context

        self.assertIs(facade_context, DirectBarCaptureContext)

    def test_lazy_controller_state_does_not_create_mss_backend(self) -> None:
        from maple_star.controller import AutoPotionController

        controller = AutoPotionController.__new__(AutoPotionController)
        controller.last_bar_debug = {"hp": BarDetectionDebug("hp")}

        self.assertFalse(hasattr(controller, "screen_capture_service"))
        self.assertIs(controller.last_bar_debug, controller.hud_bar_detector.last_bar_debug)

    def test_controller_backend_assignment_updates_borrowed_capture_port(self) -> None:
        from maple_star.controller import AutoPotionController

        controller = AutoPotionController.__new__(AutoPotionController)
        controller.bottom_bar_regions = {}
        backend = Mock()

        controller.sct = backend

        self.assertIs(
            controller.hud_bar_detector.screen_capture,
            controller.screen_capture_service,
        )
        self.assertIs(controller.sct, backend)

    def test_detector_close_does_not_close_borrowed_screen_capture(self) -> None:
        screen_capture = Mock()
        detector = HudBarDetector(screen_capture)
        detector.direct_capture_context = Mock()

        detector.close()
        detector.close()

        detector.direct_capture_context.close.assert_called_once_with()
        screen_capture.close.assert_not_called()

    def test_detector_close_retries_direct_capture_failure(self) -> None:
        detector = HudBarDetector(Mock())
        detector.direct_capture_context = Mock()
        detector.direct_capture_context.close.side_effect = [RuntimeError("close failed"), None]

        with self.assertRaises(RuntimeError):
            detector.close()
        detector.close()
        detector.close()

        self.assertEqual(detector.direct_capture_context.close.call_count, 2)

    def test_direct_capture_uses_injected_dynamic_win32_providers(self) -> None:
        user = SimpleNamespace(
            GetDC=Mock(return_value=1),
            ReleaseDC=Mock(return_value=1),
        )
        gdi = SimpleNamespace(
            CreateCompatibleDC=Mock(return_value=2),
            CreateCompatibleBitmap=Mock(return_value=3),
            SelectObject=Mock(return_value=4),
            DeleteObject=Mock(return_value=1),
            DeleteDC=Mock(return_value=1),
            BitBlt=Mock(return_value=1),
            GetDIBits=Mock(return_value=2),
        )
        context = DirectBarCaptureContext(
            user32_provider=lambda: user,
            gdi32_provider=lambda: gdi,
        )

        image = context.capture(10, 20, 3, 2)
        context.close()

        self.assertEqual(image.shape, (2, 3, 4))
        gdi.BitBlt.assert_called_once()
        gdi.DeleteObject.assert_called_once_with(3)
        gdi.DeleteDC.assert_called_once_with(2)
        user.ReleaseDC.assert_called_once_with(None, 1)

    def test_detector_owns_all_mutable_hud_state(self) -> None:
        detector = HudBarDetector(None)

        field_names = {
            field
            for field in vars(detector)
            if field
            in {
                "direct_capture_context",
                "template_cache",
                "stable_bar_samples",
                "bottom_bar_regions",
                "bottom_bar_track_regions",
                "last_bar_debug",
                "direct_bar_failure_count",
                "fade_guard_hits",
            }
        }

        self.assertEqual(
            field_names,
            {
                "direct_capture_context",
                "template_cache",
                "stable_bar_samples",
                "bottom_bar_regions",
                "bottom_bar_track_regions",
                "last_bar_debug",
                "direct_bar_failure_count",
                "fade_guard_hits",
            },
        )

    def test_stable_sample_uses_injected_clock_and_expires(self) -> None:
        now = [10.0]
        detector = HudBarDetector(None, monotonic=lambda: now[0])
        region = (1, 2, 30, 4)

        detector.remember_stable_bar_sample("hp", 42.0, region)
        now[0] = 10.5
        self.assertEqual(detector.recent_stable_bar_percent("hp", region), 42.0)
        now[0] = 11.0
        self.assertIsNone(detector.recent_stable_bar_percent("hp", region))

    def test_bar_percent_algorithm_is_owned_by_detector(self) -> None:
        normalizer = Mock(return_value=40.0)
        detector = HudBarDetector(None, normalize_percent=normalizer)
        mask = np.zeros((4, 10), dtype=bool)
        mask[:, :4] = True

        percent, reason, tail_clear = detector.percent_from_bar_mask_result(mask)

        self.assertEqual((percent, reason, tail_clear), (40.0, "OK", None))
        normalizer.assert_called_once_with(40.0)

    def test_controller_bar_algorithm_methods_are_detector_shims(self) -> None:
        from maple_star.controller import AutoPotionController

        controller = AutoPotionController.__new__(AutoPotionController)
        detector = Mock()
        detector.bar_color_mask.return_value = np.ones((2, 3), dtype=bool)
        controller.hud_bar_detector = detector
        image = np.zeros((2, 3, 4), dtype=np.uint8)

        result = controller._bar_color_mask(image, "hp")

        self.assertIs(result, detector.bar_color_mask.return_value)
        detector.bar_color_mask.assert_called_once_with(image, "hp")

    def test_detector_request_result_is_the_production_hud_refresh_entry(self) -> None:
        detector = HudBarDetector(None)
        detector._find_bottom_bar_pair_regions = Mock(return_value={})
        request = HudDetectionRequest(
            now=10.0,
            target_hwnd=123,
            target_client_rect=(0, 0, 800, 600),
            detect_hp=True,
            detect_mp=True,
            require_clear_tail_hp=False,
            require_clear_tail_mp=False,
        )

        result = detector.detect(request)

        self.assertIsInstance(result, HudDetectionResult)
        self.assertFalse(result.gameplay_hud_active)
        self.assertEqual(result.debug["hp"].source, "HUD gate")
        controller_source = (
            Path(__file__).resolve().parents[1]
            / "maple_star"
            / "controllers"
            / "auto_potion_controller.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._hud_detector().detect(", controller_source)
        self.assertIn("HudDetectionRequest(", controller_source)


if __name__ == "__main__":
    unittest.main()
