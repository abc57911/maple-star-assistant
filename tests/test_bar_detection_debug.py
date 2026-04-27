import unittest
from unittest.mock import Mock

import numpy as np
import tkinter as tk

from maple_star.controller import AutoPotionController, BarDetectionDebug, bgra_image_to_ppm_data


class BarDetectionDebugTests(unittest.TestCase):
    def make_controller(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.last_bar_debug = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        controller.bar_override_warnings = {"hp": "", "mp": ""}
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
            source="自動定位",
            region=(1, 2, 3, 4),
            percent=55.5,
            success=True,
            reason="OK",
            require_clear_tail=False,
            tail_clear=None,
        )

        text = controller._bar_detection_debug_text("hp")

        self.assertIn("HP: 自動定位", text)
        self.assertIn("56%", text)
        self.assertIn("1,2,3,4", text)
        self.assertIn("OK", text)

    def test_bottom_bar_pair_regions_are_derived_from_candidate_pair(self):
        controller = self.make_controller()

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(120, 70, 90)],
            mp_candidates=[(360, 72, 85)],
            search_left=10,
            search_top=900,
            search_width=700,
            search_height=120,
            client_width=1000,
            client_height=800,
        )

        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(regions["hp"][0], regions["mp"][0])
        self.assertEqual(regions["hp"][2:], regions["mp"][2:])
        self.assertLessEqual(abs(regions["hp"][1] - regions["mp"][1]), 2)
        self.assertGreaterEqual(regions["hp"][2], 70)
        self.assertLessEqual(regions["hp"][2], 200)

    def test_bottom_bar_pair_regions_use_detected_vertical_body_height(self):
        controller = self.make_controller()
        hp_mask = np.zeros((120, 700), dtype=bool)
        mp_mask = np.zeros((120, 700), dtype=bool)
        hp_mask[68:82, 120:210] = True
        mp_mask[69:83, 360:445] = True

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(120, 72, 90)],
            mp_candidates=[(360, 73, 85)],
            hp_mask=hp_mask,
            mp_mask=mp_mask,
            search_left=10,
            search_top=900,
            search_width=700,
            search_height=120,
            client_width=1000,
            client_height=1080,
        )

        self.assertEqual(regions["hp"][1], 967)
        self.assertEqual(regions["hp"][3], 16)
        self.assertEqual(regions["mp"][1], 968)
        self.assertEqual(regions["mp"][3], 16)

    def test_capture_bar_percent_reports_auto_locator_failure(self):
        controller = self.make_controller()
        controller._find_bottom_bar_pair_regions = Mock(return_value={})

        percent = controller._capture_bar_percent("hp")

        self.assertIsNone(percent)
        debug = controller.last_bar_debug["hp"]
        self.assertEqual(debug.source, "自動定位")
        self.assertIsNone(debug.region)
        self.assertEqual(debug.reason, "找不到 HP/MP 成對 HUD 條")

    def test_bgra_image_to_ppm_data_scales_preview(self):
        image = np.array([[[10, 20, 30, 255]]], dtype=np.uint8)

        data = bgra_image_to_ppm_data(image, scale=2)

        self.assertTrue(data.startswith(b"P6\n2 2\n255\n"))
        self.assertEqual(data[-12:], bytes([30, 20, 10]) * 4)

    def test_bgra_image_to_ppm_data_loads_in_tk_photo_image(self):
        image = np.array([[[10, 20, 30, 255]]], dtype=np.uint8)
        data = bgra_image_to_ppm_data(image, scale=2)
        root = tk.Tk()
        root.withdraw()
        try:
            photo = tk.PhotoImage(data=data, format="PPM")
            self.assertEqual(photo.width(), 2)
            self.assertEqual(photo.height(), 2)
        finally:
            root.destroy()
