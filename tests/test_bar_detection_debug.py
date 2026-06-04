import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

import numpy as np
import tkinter as tk

from maple_star.controller import AutoPotionController, BarDetectionDebug, bgra_image_to_ppm_data
from maple_star.gui import AutoPotionSettingsGui
from maple_star.key_capture import DETECTABLE_KEY_VKS, vk_to_key_name
from maple_star.window_target import is_target_process_name, is_target_window, normalize_process_name


class BarDetectionDebugTests(unittest.TestCase):
    def make_controller(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.last_bar_debug = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        controller.stable_bar_samples = {}
        controller.bar_override_warnings = {"hp": "", "mp": ""}
        return controller

    def solid_bar_image(self, width: int, height: int, bar_type: str) -> np.ndarray:
        image = np.zeros((height, width, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        if bar_type == "hp":
            image[:, :, 2] = 220
        else:
            image[:, :, 0] = 220
            image[:, :, 1] = 120
        return image

    def test_percent_result_reports_missing_color_columns(self):
        controller = self.make_controller()
        mask = np.zeros((4, 10), dtype=bool)

        percent, reason, tail_clear = controller._percent_from_bar_mask_result(mask)

        self.assertIsNone(percent)
        self.assertEqual(reason, "找不到符合顏色的填滿欄位")
        self.assertIsNone(tail_clear)

    def test_empty_known_track_region_reports_zero_percent(self):
        controller = self.make_controller()
        image = np.full((12, 100, 4), 45, dtype=np.uint8)
        image[:, :, 3] = 255
        controller.sct = Mock()
        controller.sct.grab.return_value = image

        percent, reason, tail_clear = controller._bar_percent_from_region_snapshot(
            (10, 20, 100, 12),
            "mp",
            track_region=(10, 20, 100, 12),
        )

        self.assertEqual(percent, 0.0)
        self.assertEqual(reason, "OK:EmptyTrack")
        self.assertIsNone(tail_clear)

    def test_percent_result_treats_full_width_bar_with_large_internal_gap_as_full(self):
        controller = self.make_controller()
        mask = np.ones((8, 100), dtype=bool)
        mask[:, 42:64] = False

        percent, reason, tail_clear = controller._percent_from_bar_mask_result(mask)

        self.assertEqual(percent, 100.0)
        self.assertEqual(reason, "OK:FullWidth")
        self.assertIsNone(tail_clear)

    def test_percent_result_does_not_treat_partial_bar_as_full_without_right_edge_fill(self):
        controller = self.make_controller()
        mask = np.zeros((8, 100), dtype=bool)
        mask[:, :82] = True

        percent, reason, tail_clear = controller._percent_from_bar_mask_result(mask)

        self.assertEqual(percent, 82.0)
        self.assertEqual(reason, "OK")
        self.assertIsNone(tail_clear)

    def test_bar_detection_debug_text_includes_source_percent_and_reason(self):
        controller = self.make_controller()
        controller._set_bar_detection_debug(
            "hp",
            source="自動定位",
            region=(1, 2, 3, 4),
            track_region=(5, 6, 7, 8),
            percent=55.5,
            success=True,
            reason="OK",
            require_clear_tail=False,
            tail_clear=None,
        )

        text = controller._bar_detection_debug_text("hp")

        self.assertIn("HP: 定位", text)
        self.assertIn("56%", text)
        self.assertIn("OK", text)
        self.assertNotIn("f=", text)
        self.assertNotIn("t=", text)
        self.assertNotIn("full=", text)
        self.assertNotIn("track=", text)

    def test_bar_detection_debug_text_omits_coordinate_regions_for_direct_track(self):
        controller = self.make_controller()
        controller._set_bar_detection_debug(
            "mp",
            source="直接取色",
            region=(488, 1019, 255, 28),
            track_region=(488, 1019, 255, 28),
            percent=91.0,
            success=True,
            reason="OK:Direct",
            require_clear_tail=False,
            tail_clear=None,
        )

        text = controller._bar_detection_debug_text("mp")

        self.assertIn("MP: 直取", text)
        self.assertIn("91%", text)
        self.assertIn("OK:Direct", text)
        self.assertNotIn("488,1019", text)
        self.assertNotIn("t=", text)
        self.assertNotIn("f=", text)

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

        hp_track = controller.bottom_bar_track_regions["hp"]
        mp_track = controller.bottom_bar_track_regions["mp"]
        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(hp_track[0], mp_track[0])
        self.assertLessEqual(regions["hp"][0], hp_track[0])
        self.assertGreaterEqual(regions["hp"][0] + regions["hp"][2], hp_track[0] + hp_track[2])
        self.assertLessEqual(regions["hp"][1], hp_track[1])
        self.assertGreaterEqual(regions["hp"][1] + regions["hp"][3], hp_track[1] + hp_track[3])
        self.assertLessEqual(abs(regions["hp"][1] - regions["mp"][1]), 2)
        self.assertGreater(regions["hp"][2], hp_track[2])
        self.assertGreaterEqual(hp_track[2], 70)
        self.assertLessEqual(hp_track[2], 200)

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

        hp_track = controller.bottom_bar_track_regions["hp"]
        mp_track = controller.bottom_bar_track_regions["mp"]
        self.assertEqual(hp_track[1], 967)
        self.assertEqual(hp_track[3], 16)
        self.assertEqual(mp_track[1], 968)
        self.assertEqual(mp_track[3], 16)
        self.assertLess(regions["hp"][1], hp_track[1])
        self.assertGreater(regions["hp"][3], hp_track[3])

    def test_bottom_bar_pair_ignores_upper_map_objects_in_search_area(self):
        controller = self.make_controller()

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(600, 12, 320), (490, 118, 250)],
            mp_candidates=[(970, 14, 320), (795, 119, 44)],
            search_left=0,
            search_top=900,
            search_width=1920,
            search_height=173,
            client_width=1920,
            client_height=1080,
        )

        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(regions["hp"][0], 600)
        self.assertGreater(regions["hp"][1], 1000)
        self.assertGreater(regions["mp"][1], 1000)

    def test_bottom_bar_search_areas_include_centered_gameplay_content_for_wide_window(self):
        controller = self.make_controller()

        areas = controller._bottom_bar_search_areas((0, 0, 3840, 1080))

        self.assertGreaterEqual(len(areas), 2)
        full_client = areas[0]
        self.assertEqual(full_client.reference_left, 0)
        self.assertEqual(full_client.reference_width, 3840)
        self.assertEqual(full_client.reference_height, 1080)
        centered = areas[1]
        self.assertEqual(centered.reference_left, 960)
        self.assertEqual(centered.reference_width, 1920)
        self.assertEqual(centered.reference_height, 1080)
        self.assertEqual(centered.left, 960 + round(1920 * 0.16))
        self.assertEqual(centered.width, round(1920 * 0.70))

    def test_bottom_bar_search_areas_include_centered_gameplay_content_for_tall_window(self):
        controller = self.make_controller()

        areas = controller._bottom_bar_search_areas((0, 0, 900, 900))

        self.assertGreaterEqual(len(areas), 2)
        full_client = areas[0]
        self.assertEqual(full_client.reference_left, 0)
        self.assertEqual(full_client.reference_width, 900)
        self.assertEqual(full_client.reference_height, 900)
        centered = areas[1]
        self.assertEqual(centered.reference_left, 0)
        self.assertEqual(centered.reference_width, 900)
        self.assertEqual(centered.reference_height, 506)
        self.assertEqual(centered.top, 197 + round(506 * 0.84))

    def test_bottom_bar_pair_accepts_centered_wide_window_coordinates(self):
        controller = self.make_controller()

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(179, 118, 220)],
            mp_candidates=[(488, 118, 220)],
            hp_mask=None,
            mp_mask=None,
            search_left=1267,
            search_top=900,
            search_width=1344,
            search_height=180,
            client_width=1920,
            client_height=1080,
            reference_left=960,
        )

        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(regions["hp"][0], regions["mp"][0])
        self.assertGreaterEqual(regions["hp"][0], 1267)

    def test_exp_track_right_of_label_does_not_extend_into_red_button(self):
        controller = self.make_controller()
        image = np.zeros((80, 420, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[38:50, 100:260, :3] = (50, 190, 60)
        image[38:50, 260:300, :3] = (80, 80, 80)
        image[38:50, 300:360, :3] = (40, 45, 190)
        exp_mask = np.zeros((80, 420), dtype=bool)
        exp_mask[38:50, 100:260] = True

        track = controller._bar_track_right_of_label(
            image,
            exp_mask,
            label_rect=(48, 34, 42, 18),
            client_width=1000,
            client_height=800,
            bar_type="exp",
        )

        self.assertIsNotNone(track)
        self.assertLessEqual(track[0] + track[2], 300)

    def test_hp_track_right_of_label_stays_inside_track_before_adjacent_mp_label(self):
        controller = self.make_controller()
        image = np.zeros((80, 380, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[28:48, 12:46, :3] = (235, 235, 235)
        image[34:46, 56:160, :3] = (35, 35, 220)
        image[34:46, 160:210, :3] = (75, 75, 75)
        image[28:48, 215:248, :3] = (235, 235, 235)
        image[34:46, 252:330, :3] = (220, 120, 20)
        hp_mask = np.zeros((80, 380), dtype=bool)
        hp_mask[34:46, 56:160] = True

        track = controller._bar_track_right_of_label(
            image,
            hp_mask,
            label_rect=(12, 28, 34, 20),
            client_width=1000,
            client_height=800,
            bar_type="hp",
        )

        self.assertIsNotNone(track)
        self.assertGreaterEqual(track[0], 54)
        self.assertLessEqual(track[0] + track[2], 212)

    def test_transition_fade_guard_samples_centered_gameplay_content(self):
        controller = self.make_controller()
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 3840, 1080))
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((12, 24, 4), dtype=np.uint8)

        controller._is_transition_fade_active()

        region = controller.sct.grab.call_args.args[0]
        self.assertEqual(region["left"], 960)
        self.assertEqual(region["width"], 1920)
        self.assertEqual(region["top"], round(1080 * 0.88))

    def test_loading_guard_samples_centered_gameplay_content(self):
        controller = self.make_controller()
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 3840, 1080))
        controller.sct = Mock()
        image = np.full((12, 24, 4), 255, dtype=np.uint8)
        controller.sct.grab.return_value = image

        controller._is_channel_loading_screen_active()

        region = controller.sct.grab.call_args.args[0]
        self.assertEqual(region["left"], 960 + round(1920 * 0.14))
        self.assertEqual(region["width"], round(1920 * 0.72))
        self.assertEqual(region["top"], round(1080 * 0.12))

    def test_capture_bar_percent_reports_auto_locator_failure(self):
        controller = self.make_controller()
        controller._find_bottom_bar_pair_regions = Mock(return_value={})

        percent = controller._capture_bar_percent("hp")

        self.assertIsNone(percent)
        debug = controller.last_bar_debug["hp"]
        self.assertEqual(debug.source, "自動定位")
        self.assertIsNone(debug.region)
        self.assertEqual(debug.reason, "找不到 HP/MP 定位座標，無法直接取色")

    def test_capture_bar_percent_holds_recent_stable_sample_for_transient_failure(self):
        controller = self.make_controller()
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((4, 10, 4), dtype=np.uint8)
        controller._bar_color_mask = Mock(return_value=np.zeros((4, 10), dtype=bool))
        controller._percent_from_bar_mask_result = Mock(
            side_effect=[
                (55.0, "OK", None),
                (None, "找不到符合顏色的填滿欄位", None),
            ]
        )
        region = (10, 20, 100, 12)

        first_percent = controller._capture_bar_percent_from_region(region, "hp")
        second_percent = controller._capture_bar_percent_from_region(region, "hp")

        self.assertEqual(first_percent, 55.0)
        self.assertEqual(second_percent, 55.0)
        debug = controller.last_bar_debug["hp"]
        self.assertTrue(debug.success)
        self.assertEqual(debug.reason, "短暫失敗，沿用最近穩定取樣")

    def test_capture_bar_percent_uses_inner_track_inside_full_status_region(self):
        controller = self.make_controller()
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((4, 16, 4), dtype=np.uint8)
        mask = np.zeros((4, 16), dtype=bool)
        mask[:, 4:8] = True
        controller._bar_color_mask = Mock(return_value=mask)
        full_region = (10, 20, 16, 4)
        track_region = (14, 20, 8, 4)

        percent = controller._capture_bar_percent_from_region(
            full_region,
            "hp",
            track_region=track_region,
        )

        self.assertEqual(percent, 50.0)
        debug = controller.last_bar_debug["hp"]
        self.assertEqual(debug.region, full_region)
        self.assertEqual(debug.reason, "OK")

    def test_clear_tail_recheck_does_not_hold_recent_stable_sample(self):
        controller = self.make_controller()
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((4, 10, 4), dtype=np.uint8)
        controller._bar_color_mask = Mock(return_value=np.zeros((4, 10), dtype=bool))
        controller._percent_from_bar_mask_result = Mock(
            side_effect=[
                (25.0, "OK", True),
                (None, "尾段疑似被遮擋", False),
            ]
        )
        region = (10, 20, 100, 12)

        first_percent = controller._capture_bar_percent_from_region(region, "hp", require_clear_tail=True)
        second_percent = controller._capture_bar_percent_from_region(region, "hp", require_clear_tail=True)

        self.assertEqual(first_percent, 25.0)
        self.assertIsNone(second_percent)
        debug = controller.last_bar_debug["hp"]
        self.assertFalse(debug.success)
        self.assertEqual(debug.reason, "尾段疑似被遮擋")

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

    def test_bgra_image_to_ppm_data_can_render_fixed_preview_size(self):
        image = np.array([[[10, 20, 30, 255], [40, 50, 60, 255]]], dtype=np.uint8)

        data = bgra_image_to_ppm_data(image, target_size=(6, 4))

        self.assertTrue(data.startswith(b"P6\n6 4\n255\n"))
        self.assertEqual(len(data.split(b"\n", 3)[3]), 6 * 4 * 3)

    def test_refresh_bar_preview_keeps_previous_image_when_preview_is_incomplete(self):
        gui = AutoPotionSettingsGui.__new__(AutoPotionSettingsGui)
        gui.bar_preview_provider = Mock(
            return_value={
                "hp": {"image": b"P6\n1 1\n255\n\x00\x00\x00"},
                "mp": {"image": None, "error": "尚無可預覽的偵測區域"},
            }
        )
        gui.bar_preview_labels = {"hp": Mock(), "mp": Mock()}
        previous_images = [object()]
        gui.bar_preview_images = previous_images
        gui.bar_preview_has_snapshot = True
        gui.set_status = Mock()

        gui._refresh_bar_preview(make_target_topmost=True)

        self.assertIs(gui.bar_preview_images, previous_images)
        gui.bar_preview_labels["hp"].configure.assert_not_called()
        gui.bar_preview_labels["mp"].configure.assert_not_called()
        gui.set_status.assert_called_once_with("HP/MP 預覽未更新：尚未同時抓到 HP/MP 條")

    def test_target_process_name_uses_msw_executable_not_window_title(self):
        self.assertEqual(normalize_process_name("msw"), "msw.exe")
        self.assertTrue(is_target_process_name("msw.exe"))
        self.assertFalse(is_target_process_name("chrome.exe"))
        self.assertFalse(is_target_process_name("Discord.exe"))

    def test_target_window_accepts_foreground_child_when_root_is_msw_process(self):
        def process_name(process_id):
            return "msw.exe" if process_id == 200 else "dwm.exe"

        with (
            patch("maple_star.adapters.window_target.window_ancestor_handles", return_value=(111, 222)),
            patch("maple_star.adapters.window_target.is_valid_window", return_value=True),
            patch("maple_star.adapters.window_target.window_process_id", side_effect=[100, 200]),
            patch("maple_star.adapters.window_target.process_executable_name", side_effect=process_name),
        ):
            self.assertTrue(is_target_window(111))

    def test_pause_and_function_keys_are_detectable_for_control_hotkeys(self):
        self.assertEqual(vk_to_key_name(0x13), "Pause")
        self.assertIn(0x13, DETECTABLE_KEY_VKS)
        self.assertIn(0x7A, DETECTABLE_KEY_VKS)
        self.assertIn(0x7B, DETECTABLE_KEY_VKS)

    def test_capture_bar_preview_rejects_screenshot_without_bar_colors(self):
        controller = self.make_controller()
        controller.last_bar_debug["hp"].region = (1, 2, 3, 4)
        controller.last_bar_debug["mp"].region = (5, 6, 7, 8)
        controller.last_target_hwnd = 123
        controller.target_window_provider = Mock(return_value=123)
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((4, 10, 4), dtype=np.uint8)
        controller._wait_for_preview_target_ready = Mock(return_value=True)

        @contextmanager
        def ready_topmost(_hwnd):
            yield True

        import maple_star.controller as controller_module

        original_topmost = controller_module.temporarily_make_window_topmost
        controller_module.temporarily_make_window_topmost = ready_topmost
        try:
            previews = controller.capture_bar_preview_images(make_target_topmost=True)
        finally:
            controller_module.temporarily_make_window_topmost = original_topmost

        self.assertIsNone(previews["hp"]["image"])
        self.assertIsNone(previews["mp"]["image"])
        self.assertEqual(previews["hp"]["error"], "預覽截圖未通過 HP/MP 色條驗證")

    def test_capture_bar_preview_uses_track_region_when_available(self):
        controller = self.make_controller()
        controller.last_bar_debug["hp"] = BarDetectionDebug(
            "hp",
            region=(1, 2, 20, 8),
            track_region=(4, 3, 10, 4),
            percent=100.0,
        )
        controller.last_bar_debug["mp"] = BarDetectionDebug(
            "mp",
            region=(30, 2, 20, 8),
            track_region=(34, 3, 10, 4),
            percent=100.0,
        )
        controller.sct = Mock()
        controller.sct.grab.side_effect = [
            self.solid_bar_image(10, 4, "hp"),
            self.solid_bar_image(10, 4, "mp"),
        ]

        previews = controller.capture_bar_preview_images(make_target_topmost=False)

        self.assertIsInstance(previews["hp"]["image"], bytes)
        self.assertIsInstance(previews["mp"]["image"], bytes)
        self.assertEqual(controller.sct.grab.call_args_list[0].args[0]["left"], 4)
        self.assertEqual(controller.sct.grab.call_args_list[0].args[0]["width"], 10)
        self.assertEqual(controller.sct.grab.call_args_list[1].args[0]["left"], 34)
        self.assertEqual(controller.sct.grab.call_args_list[1].args[0]["width"], 10)

    def test_capture_bar_preview_falls_back_to_full_region_without_track_region(self):
        controller = self.make_controller()
        controller.last_bar_debug["hp"] = BarDetectionDebug("hp", region=(1, 2, 20, 8), percent=100.0)
        controller.last_bar_debug["mp"] = BarDetectionDebug("mp", region=(30, 2, 20, 8), percent=100.0)
        controller.sct = Mock()
        controller.sct.grab.side_effect = [
            self.solid_bar_image(20, 8, "hp"),
            self.solid_bar_image(20, 8, "mp"),
        ]

        previews = controller.capture_bar_preview_images(make_target_topmost=False)

        self.assertIsInstance(previews["hp"]["image"], bytes)
        self.assertIsInstance(previews["mp"]["image"], bytes)
        self.assertEqual(controller.sct.grab.call_args_list[0].args[0]["left"], 1)
        self.assertEqual(controller.sct.grab.call_args_list[0].args[0]["width"], 20)
        self.assertEqual(controller.sct.grab.call_args_list[1].args[0]["left"], 30)
        self.assertEqual(controller.sct.grab.call_args_list[1].args[0]["width"], 20)

    def test_capture_bar_preview_fails_when_target_window_cannot_be_displayed(self):
        controller = self.make_controller()
        controller.last_bar_debug["hp"].region = (1, 2, 3, 4)
        controller.last_bar_debug["mp"].region = (5, 6, 7, 8)
        controller.last_target_hwnd = 123
        controller.target_window_provider = Mock(return_value=123)
        controller.sct = Mock()

        @contextmanager
        def failed_topmost(_hwnd):
            yield False

        import maple_star.controller as controller_module

        original_topmost = controller_module.temporarily_make_window_topmost
        controller_module.temporarily_make_window_topmost = failed_topmost
        try:
            previews = controller.capture_bar_preview_images(make_target_topmost=True)
        finally:
            controller_module.temporarily_make_window_topmost = original_topmost

        self.assertIsNone(previews["hp"]["image"])
        self.assertIsNone(previews["mp"]["image"])
        self.assertEqual(previews["hp"]["error"], "無法顯示目標遊戲視窗，預覽未更新")
        controller.sct.grab.assert_not_called()
