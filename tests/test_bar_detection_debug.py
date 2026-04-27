import unittest

import base64

import numpy as np

from maple_star.controller import AutoPotionController, BarDetectionDebug, bgra_image_to_ppm_base64


class BarDetectionDebugTests(unittest.TestCase):
    def make_controller(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.last_bar_debug = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        return controller

    def test_percent_result_reports_missing_color_columns(self):
        controller = self.make_controller()
        mask = np.zeros((4, 10), dtype=bool)

        percent, reason, tail_clear = controller._percent_from_bar_mask_result(mask)

        self.assertIsNone(percent)
        self.assertEqual(reason, "找不到符合顏色的填滿欄位")
        self.assertIsNone(tail_clear)

    def test_bar_detection_debug_text_includes_source_region_and_percent(self):
        controller = self.make_controller()
        controller._set_bar_detection_debug(
            "hp",
            source="client 比例縮放",
            region=(1, 2, 3, 4),
            percent=55.5,
            success=True,
            reason="OK",
            require_clear_tail=False,
            tail_clear=None,
        )

        text = controller._bar_detection_debug_text("hp")

        self.assertIn("HP: client 比例縮放", text)
        self.assertIn("56%", text)
        self.assertIn("1,2,3,4", text)
        self.assertIn("OK", text)

    def test_bgra_image_to_ppm_base64_scales_preview(self):
        image = np.array([[[10, 20, 30, 255]]], dtype=np.uint8)

        encoded = bgra_image_to_ppm_base64(image, scale=2)
        decoded = base64.b64decode(encoded)

        self.assertTrue(decoded.startswith(b"P6\n2 2\n255\n"))
        self.assertEqual(decoded[-12:], bytes([30, 20, 10]) * 4)
