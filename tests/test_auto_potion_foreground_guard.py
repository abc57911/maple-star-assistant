import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from maple_star.controller import (
    AUTO_DRINK_START_SOUND_PATH,
    AUTO_DRINK_STOP_SOUND_PATH,
    AUTO_PICKUP_START_SOUND_PATH,
    AUTO_PICKUP_STOP_SOUND_PATH,
    AutoPotionController,
    ExperienceOcrJob,
)
from maple_star.constants import (
    ASYNC_KEY_DOWN_MASK,
    BAR_CONFIRM_CAPTURE_ATTEMPTS,
    BAR_TRANSIENT_CAPTURE_ATTEMPTS,
    EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
    EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
    POTION_EFFECT_NO_EFFECT_LIMIT,
    POTION_EFFECT_OBSERVATION_SECONDS,
)
from maple_star.experience import ExperienceEfficiencyTracker, ExperienceOcrImage, ExperienceSnapshot, ExperienceTextReading
from maple_star.models.controller_state import BarDetectionDebug, OutOfPotionHold, PotionEffectAttempt
from maple_star.services.control_hotkey_worker import CONTROL_HOTKEY_EXPERIENCE_TOGGLE, CONTROL_HOTKEY_PICKUP_TOGGLE
from maple_star.services.potion_action_worker import PotionAction, PotionActionWorker, _apply_potion_action
from maple_star.settings import AutoPotionSettings


class AutoPotionForegroundGuardTests(unittest.TestCase):
    def make_controller(self, active_sequence):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.settings = AutoPotionSettings(
            hp_enabled=True,
            mp_enabled=True,
            hp_threshold_percent=50.0,
            mp_threshold_percent=50.0,
            hp_key="Delete",
            mp_key="End",
            hp_cooldown_seconds=0.0,
            mp_cooldown_seconds=0.0,
        )
        controller.is_target_window_active = Mock(side_effect=active_sequence)
        controller.gui = Mock()
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = False
        controller.gui.is_key_detection_release_pending.return_value = False
        controller.last_hp_drink_at = -999.0
        controller.last_mp_drink_at = -999.0
        controller.hp_potion_effect_attempts = []
        controller.mp_potion_effect_attempts = []
        controller.hp_potion_no_effect_count = 0
        controller.mp_potion_no_effect_count = 0
        controller.hp_potion_last_no_effect_counted_at = -999.0
        controller.mp_potion_last_no_effect_counted_at = -999.0
        controller.hp_potion_last_observed_percent = None
        controller.mp_potion_last_observed_percent = None
        controller.hp_potion_recent_samples = []
        controller.mp_potion_recent_samples = []
        controller.hp_potion_recent_damage_at = -999.0
        controller.mp_potion_recent_damage_at = -999.0
        controller.hp_potion_damage_pressure_active = False
        controller.mp_potion_damage_pressure_active = False
        controller.hp_out_of_potion_hold = None
        controller.mp_out_of_potion_hold = None
        controller.last_error_at = -999.0
        controller.last_unstable_bar_at = -999.0
        controller.last_bar_debug = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        controller.last_experience_ocr_error_at = -999.0
        controller.last_experience_ocr_error_reason = ""
        controller.last_completed_experience_ocr_signature = None
        controller.last_failed_experience_ocr_signature = None
        controller.emergency_stop_requested = False
        controller.auto_drink_enabled = True
        controller.scripts_enabled = True
        controller.registered_toggle_hotkey_vk = 0
        controller.registered_emergency_stop_hotkey_vk = 0
        controller.registered_experience_toggle_hotkey_vk = 0
        controller.registered_experience_reset_hotkey_vk = 0
        controller.registered_pickup_toggle_hotkey_vk = 0
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller.experience_toggle_hotkey_was_down = False
        controller.experience_reset_hotkey_was_down = False
        controller.pickup_toggle_hotkey_was_down = False
        controller.last_experience_reset_hotkey_at = -999.0
        controller.last_pickup_toggle_hotkey_at = -999.0
        controller.pickup_enabled = False
        controller.pickup_held_vk = 0
        controller.hp_potion_held_vk = 0
        controller.mp_potion_held_vk = 0
        controller.gameplay_hud_active = False
        controller.pending_settings_snapshot = controller.settings.snapshot()
        controller.next_settings_save_at = None
        controller.control_hotkeys_suppressed_until_release = False
        controller.last_action = "啟動"
        controller.experience_ocr_job = None
        controller.experience_ocr_burst = None
        controller.experience_pause_started_at = None
        controller.experience_total_paused_seconds = 0.0
        controller._log_unstable_bar = Mock()
        controller._play_toggle_beep = Mock()
        controller._capture_bar_percent = Mock(return_value=25.0)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        return controller

    def seed_stable_potion_samples(self, controller, bar_type, now, percent):
        if bar_type == "hp":
            samples = [
                (now - 7.6, percent),
                (now - 6.4, percent),
                (now - 5.2, percent),
                (now - 4.0, percent),
                (now - 2.8, percent),
                (now - 1.6, percent),
                (now - 0.5, percent),
                (now - 0.2, percent),
                (now - 0.1, percent),
            ]
        else:
            samples = [
                (now - 7.6, percent),
                (now - 6.4, percent),
                (now - 5.2, percent),
                (now - 4.0, percent),
                (now - 2.8, percent),
                (now - 1.6, percent),
                (now - 0.5, percent),
                (now - 0.2, percent),
                (now - 0.1, percent),
            ]
        if bar_type == "hp":
            controller.hp_potion_recent_samples = samples
        else:
            controller.mp_potion_recent_samples = samples

    def test_experience_capture_submits_burst_reader_without_runtime_templates(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = []
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot()
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._experience_text_region = Mock(return_value=(10, 20, 140, 18))
        controller.sct = Mock()
        controller.sct.grab.return_value = image

        controller._update_experience_efficiency(5.0)

        self.assertFalse(hasattr(controller.experience_ocr_executor, "call"))
        for index in range(1, EXPERIENCE_BURST_CAPTURE_ATTEMPTS):
            controller._update_experience_efficiency(5.0 + EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS * index)

        self.assertEqual(controller.experience_ocr_executor.call[2], {})
        submitted_fn, submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, controller.experience_reader.read_burst_frames)
        self.assertEqual(len(submitted_args[0]), EXPERIENCE_BURST_CAPTURE_ATTEMPTS)
        self.assertTrue(all(len(frame) == 1 for frame in submitted_args[0]))

    def test_experience_capture_submits_all_roi_candidates_for_each_burst_frame(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((32, 420, 4), dtype=np.uint8)
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = []
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot()
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.bottom_bar_regions = {
            "hp": (100, 700, 250, 24),
            "mp": (400, 700, 250, 24),
        }
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 800))
        controller.sct = Mock()
        controller.sct.grab.return_value = image

        for index in range(EXPERIENCE_BURST_CAPTURE_ATTEMPTS):
            controller._update_experience_efficiency(5.0 + EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS * index)

        submitted_fn, submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, controller.experience_reader.read_burst_frames)
        self.assertEqual(len(submitted_args[0]), EXPERIENCE_BURST_CAPTURE_ATTEMPTS)
        self.assertTrue(all(len(frame) == 2 for frame in submitted_args[0]))
        first_frame = submitted_args[0][0]
        self.assertTrue(all(isinstance(image, ExperienceOcrImage) for image in first_frame))
        self.assertAlmostEqual(first_frame[0].bar_crop_left_ratio, 0.44)
        self.assertAlmostEqual(first_frame[1].bar_crop_left_ratio, 0.34)
        self.assertEqual(controller.sct.grab.call_count, EXPERIENCE_BURST_CAPTURE_ATTEMPTS * 2)

    def test_experience_capture_uses_single_frame_after_trusted_baseline(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._experience_text_region = Mock(return_value=(10, 20, 140, 18))
        controller.sct = Mock()
        controller.sct.grab.return_value = image

        controller._update_experience_efficiency(5.0)

        submitted_fn, submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, controller.experience_reader.read_burst_frames)
        self.assertEqual(len(submitted_args[0]), 1)
        self.assertTrue(all(len(frame) == 1 for frame in submitted_args[0]))
        self.assertIsNone(controller.experience_ocr_burst)

    def test_failed_experience_signature_keeps_next_capture_on_burst_path(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.last_failed_experience_ocr_signature = controller._experience_ocr_image_signature([[image]])
        controller._experience_text_region = Mock(return_value=(10, 20, 140, 18))
        controller.sct = Mock()
        controller.sct.grab.return_value = image.copy()

        controller._update_experience_efficiency(5.0)

        self.assertFalse(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNotNone(controller.experience_ocr_burst)
        self.assertEqual(controller.experience_ocr_burst.capture_count, 1)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, f"擷取經驗樣本中 1/{EXPERIENCE_BURST_CAPTURE_ATTEMPTS}")

    def test_experience_ocr_signature_treats_identical_roi_as_similar(self):
        controller = self.make_controller([])
        image = np.zeros((24, 180, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[7:15, 90:120, :3] = 255

        first = controller._experience_ocr_image_signature([[image]])
        second = controller._experience_ocr_image_signature([[image.copy()]])
        changed = image.copy()
        changed[7:15, 110:150, :3] = 0
        changed[7:15, 130:160, :3] = 255
        third = controller._experience_ocr_image_signature([[changed]])

        self.assertTrue(controller._experience_ocr_signatures_are_similar(first, second))
        self.assertFalse(controller._experience_ocr_signatures_are_similar(first, third))

    def test_repeated_failed_experience_ocr_roi_skips_submit_without_counting_failure(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((24, 180, 4), dtype=np.uint8)
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.last_failed_experience_ocr_signature = controller._experience_ocr_image_signature([[image]])

        controller._submit_experience_ocr_burst(9.0, [[image.copy()]])

        self.assertFalse(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNone(controller.experience_ocr_job)
        controller.experience_tracker.record_ocr_result.assert_not_called()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "OCR ROI 未變化，保留統計")
        self.assertGreater(controller.next_experience_capture_at, 9.0)

    def test_repeated_completed_experience_ocr_roi_skips_submit_without_counting_attempt(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((24, 180, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[7:15, 90:120, :3] = 255
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.last_completed_experience_ocr_signature = controller._experience_ocr_image_signature([[image]])

        controller._submit_experience_ocr_burst(9.0, [[image.copy()]])

        self.assertFalse(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNone(controller.experience_ocr_job)
        controller.experience_tracker.record_ocr_result.assert_not_called()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "EXP ROI 未變化，保留統計")
        self.assertGreater(controller.next_experience_capture_at, 9.0)

    def test_visually_unchanged_completed_experience_ocr_roi_skips_submit(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((24, 180, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[7:15, 90:120, :3] = 255
        changed = image.copy()
        changed[3, 2, 0] = 1
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.last_completed_experience_ocr_signature = controller._experience_ocr_image_signature([[image]])

        controller._submit_experience_ocr_burst(9.0, [[changed]])

        self.assertFalse(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNone(controller.experience_ocr_job)
        controller.experience_tracker.record_ocr_result.assert_not_called()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "EXP ROI 未變化，保留統計")
        self.assertGreater(controller.next_experience_capture_at, 9.0)

    def test_static_experience_roi_burst_submits_when_not_completed_duplicate(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((24, 180, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[7:15, 90:120, :3] = 255
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()

        controller._submit_experience_ocr_burst(9.0, [[image], [image.copy()]])

        submitted_fn, submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, controller.experience_reader.read_burst_frames)
        self.assertEqual(len(submitted_args[0]), 2)
        self.assertIsNotNone(controller.experience_ocr_job)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "讀取經驗樣本中")
        self.assertGreater(controller.next_experience_capture_at, 9.0)

    def test_changed_completed_experience_fixture_submits_even_when_current_burst_is_static(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        fixture_dir = Path(__file__).with_name("fixtures") / "experience_ocr"
        previous = cv2.imread(str(fixture_dir / "live2_20260502_011523_029.png"), cv2.IMREAD_UNCHANGED)
        current = cv2.imread(str(fixture_dir / "live2_20260502_011525_030.png"), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(previous)
        self.assertIsNotNone(current)
        assert previous is not None
        assert current is not None

        controller = self.make_controller([])
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.last_completed_experience_ocr_signature = controller._experience_ocr_image_signature([[previous]])

        controller._submit_experience_ocr_burst(9.0, [[current], [current.copy()], [current.copy()]])

        submitted_fn, submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, controller.experience_reader.read_burst_frames)
        self.assertEqual(len(submitted_args[0]), 3)
        self.assertIsNotNone(controller.experience_ocr_job)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "讀取經驗樣本中")

    def test_changed_failed_experience_ocr_roi_submits_again(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        image = np.zeros((24, 180, 4), dtype=np.uint8)
        changed = image.copy()
        changed[7:15, 120:160, :3] = 255
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller.last_failed_experience_ocr_signature = controller._experience_ocr_image_signature([[image]])

        controller._submit_experience_ocr_burst(9.0, [[changed]])

        submitted_fn, _submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, controller.experience_reader.read_burst_frames)
        self.assertIsNotNone(controller.experience_ocr_job)
        self.assertIsNotNone(controller.experience_ocr_job.image_signature)

    def test_actions_require_scripts_enabled_and_gameplay_hud(self):
        controller = self.make_controller([])

        self.assertFalse(controller.can_run_actions())

        controller.gameplay_hud_active = True
        self.assertTrue(controller.can_run_actions())

        controller.scripts_enabled = False
        self.assertFalse(controller.can_run_actions())

    def test_potion_action_worker_queues_commands_without_running_key_actions_on_caller(self):
        worker = PotionActionWorker()

        worker.tap("hp", "Delete")
        worker.hold("mp", 0x23)
        worker.release("mp", 0x23)
        worker.release_all()

        self.assertEqual(
            worker.drain_actions(),
            [
                PotionAction("tap", "hp", key_name="Delete"),
                PotionAction("hold", "mp", vk_code=0x23),
                PotionAction("release", "mp", vk_code=0x23),
                PotionAction("release_all", "all"),
            ],
        )

    def test_potion_action_worker_applies_hold_release_order(self):
        held: dict[str, int] = {}

        with (
            patch("maple_star.services.potion_action_worker.key_down") as key_down,
            patch("maple_star.services.potion_action_worker.key_up") as key_up,
            patch("maple_star.services.potion_action_worker.tap_hotkey") as tap_hotkey,
        ):
            _apply_potion_action(PotionAction("tap", "hp", key_name="Delete"), held)
            _apply_potion_action(PotionAction("hold", "hp", vk_code=0x2E), held)
            _apply_potion_action(PotionAction("hold", "hp", vk_code=0x2E), held)
            _apply_potion_action(PotionAction("release", "hp", vk_code=0x2E), held)

        tap_hotkey.assert_called_once_with("Delete")
        key_down.assert_called_once_with(0x2E)
        key_up.assert_called_once_with(0x2E)
        self.assertEqual(held, {})

    def test_gameplay_hud_gate_clears_stale_bar_regions_on_fresh_failure(self):
        controller = self.make_controller([])
        del controller._refresh_gameplay_hud_state
        controller.bottom_bar_regions = {
            "hp": (100, 900, 200, 16),
            "mp": (360, 900, 200, 16),
        }
        controller.bottom_bar_track_regions = dict(controller.bottom_bar_regions)
        controller.bottom_bar_client_bounds = (0, 0, 1000, 800)
        controller.bottom_bar_regions_at = 0.0
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((128, 700, 4), dtype=np.uint8)
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 800))
        controller._bar_color_mask = Mock(return_value=np.zeros((128, 700), dtype=bool))
        controller._bar_run_candidates = Mock(return_value=[])
        controller._set_bar_detection_debug = Mock()

        self.assertFalse(controller._refresh_gameplay_hud_state(10.0))

        self.assertFalse(controller.gameplay_hud_active)
        self.assertEqual(controller.bottom_bar_regions, {})
        self.assertEqual(controller.bottom_bar_track_regions, {})
        self.assertEqual(controller.last_hp_drink_at, 10.0)
        self.assertEqual(controller.last_mp_drink_at, 10.0)
        self.assertEqual(controller._set_bar_detection_debug.call_count, 2)

    def test_gameplay_hud_gate_reuses_stale_regions_when_old_bar_is_still_visible(self):
        controller = self.make_controller([])
        del controller._refresh_gameplay_hud_state
        old_regions = {
            "hp": (100, 900, 200, 16),
            "mp": (360, 900, 200, 16),
        }
        old_track_regions = {
            "hp": (102, 902, 190, 12),
            "mp": (362, 902, 190, 12),
        }
        controller.bottom_bar_regions = dict(old_regions)
        controller.bottom_bar_track_regions = dict(old_track_regions)
        controller.bottom_bar_client_bounds = (0, 0, 1000, 800)
        controller.bottom_bar_regions_at = 0.0
        controller._find_bottom_bar_pair_regions = Mock(return_value={})
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 800))
        controller._bar_percent_from_region_snapshot = Mock(return_value=(72.0, "OK", None))
        controller._set_bar_detection_debug = Mock()

        self.assertTrue(controller._refresh_gameplay_hud_state(10.0))

        self.assertTrue(controller.gameplay_hud_active)
        self.assertEqual(controller.bottom_bar_regions, old_regions)
        self.assertEqual(controller.bottom_bar_track_regions, old_track_regions)
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        self.assertEqual(controller.last_mp_drink_at, -999.0)
        controller._bar_percent_from_region_snapshot.assert_called_once_with(
            old_regions["mp"],
            "mp",
            require_clear_tail=False,
            track_region=old_track_regions["mp"],
        )
        controller._set_bar_detection_debug.assert_not_called()

    def test_hp_threshold_100_does_not_tap_when_bar_is_full(self):
        controller = self.make_controller([])
        controller.settings.hp_threshold_percent = 100.0

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 100.0)

        tap_hotkey.assert_not_called()
        controller._refresh_gameplay_hud_state.assert_not_called()

    def test_hp_does_not_tap_if_target_loses_focus_before_send(self):
        controller = self.make_controller([True, False])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        controller.gui.set_status.assert_called_with("等待楓星成為前景視窗")

    def test_hp_retries_initial_transient_failure_before_logging(self):
        controller = self.make_controller([])
        controller._capture_bar_percent = Mock(return_value=80.0)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, None)

        tap_hotkey.assert_not_called()
        controller._log_unstable_bar.assert_not_called()
        controller._capture_bar_percent.assert_called_once_with("hp")
        sleep.assert_not_called()

    def test_hp_logs_unstable_only_after_initial_transient_retries_fail(self):
        controller = self.make_controller([])
        controller._capture_bar_percent = Mock(return_value=None)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, None)

        tap_hotkey.assert_not_called()
        controller._log_unstable_bar.assert_called_once_with(100.0, "HP")
        self.assertEqual(controller._capture_bar_percent.call_count, BAR_TRANSIENT_CAPTURE_ATTEMPTS)
        self.assertEqual(sleep.call_count, BAR_TRANSIENT_CAPTURE_ATTEMPTS - 1)

    def test_hp_does_not_tap_if_gameplay_hud_disappears_before_send(self):
        controller = self.make_controller([True])
        controller._refresh_gameplay_hud_state.return_value = False

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        controller.gui.set_status.assert_called_with("未偵測到遊戲 HUD，暫停自動喝水")

    def test_hp_confirm_capture_retries_transient_failure_before_tapping(self):
        controller = self.make_controller([True, True])
        controller._capture_bar_percent = Mock(side_effect=[None, 25.0])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        self.assertEqual(controller._capture_bar_percent.call_count, 2)
        sleep.assert_called_once()
        controller._log_unstable_bar.assert_not_called()

    def test_hp_successful_auto_drink_does_not_print_console_action(self):
        controller = self.make_controller([True, True])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print") as print_mock,
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        print_mock.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, 100.0)
        self.assertEqual(controller.last_action, "HP 喝水：Delete")

    def test_hp_auto_drink_uses_potion_action_worker_when_available(self):
        controller = self.make_controller([True, True])
        controller.potion_action_worker = Mock()

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        controller.potion_action_worker.tap.assert_called_once_with("hp", "Delete")
        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, 100.0)

    def test_mp_successful_auto_drink_does_not_print_console_action(self):
        controller = self.make_controller([True, True])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print") as print_mock,
        ):
            controller._maybe_drink_mp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("End")
        print_mock.assert_not_called()
        self.assertEqual(controller.last_mp_drink_at, 100.0)
        self.assertEqual(controller.last_action, "MP 喝水：End")

    def test_hp_confirm_capture_logs_unstable_after_retries_fail(self):
        controller = self.make_controller([True])
        controller._capture_bar_percent = Mock(return_value=None)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller._capture_bar_percent.call_count, BAR_CONFIRM_CAPTURE_ATTEMPTS + 1)
        self.assertEqual(sleep.call_count, BAR_CONFIRM_CAPTURE_ATTEMPTS - 1)
        controller._log_unstable_bar.assert_called_once_with(100.0, "HP")

    def test_hp_confirm_capture_uses_matching_unchecked_fallback(self):
        controller = self.make_controller([True, True])
        controller._capture_bar_percent = Mock(
            side_effect=[None] * BAR_CONFIRM_CAPTURE_ATTEMPTS + [26.0]
        )

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep"),
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        controller._log_unstable_bar.assert_not_called()

    def test_potion_effect_attempt_starts_only_after_hp_key_is_sent(self):
        controller = self.make_controller([True, True])

        self.assertTrue(controller._update_potion_effect_watch_cycles(100.0, 25.0, 80.0))
        self.assertEqual(controller.hp_potion_effect_attempts, [])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        self.assertEqual(controller.hp_potion_effect_attempts, [PotionEffectAttempt(100.0, 25.0)])
        self.assertEqual(controller.mp_potion_effect_attempts, [])

    def test_potion_effect_attempt_records_stable_pre_window(self):
        controller = self.make_controller([])

        controller._update_potion_effect_watch_cycles(99.6, 49.0, 80.0)
        controller._update_potion_effect_watch_cycles(99.8, 49.0, 80.0)
        controller._update_potion_effect_watch_cycles(100.0, 49.0, 80.0)
        controller._record_potion_effect_attempt("hp", 100.0, 49.0)

        self.assertTrue(controller.hp_potion_effect_attempts[0].pre_window_is_stable)

    def test_potion_effect_attempt_rejects_unstable_pre_window(self):
        controller = self.make_controller([])

        controller._update_potion_effect_watch_cycles(99.6, 49.0, 80.0)
        controller._update_potion_effect_watch_cycles(99.8, 43.0, 80.0)
        controller._update_potion_effect_watch_cycles(100.0, 49.0, 80.0)
        controller._record_potion_effect_attempt("hp", 100.0, 49.0)

        self.assertFalse(controller.hp_potion_effect_attempts[0].pre_window_is_stable)

    def test_hp_flat_repeat_can_drink_every_0_1_seconds(self):
        controller = self.make_controller([True] * 6)
        controller.settings.hp_cooldown_seconds = 0.1

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.1, 25.0)
            controller._maybe_drink_hp(100.2, 25.0)

        self.assertEqual(tap_hotkey.call_count, 3)
        tap_hotkey.assert_called_with("Delete")
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.1, 25.0),
                PotionEffectAttempt(100.2, 25.0),
            ],
        )

    def test_mp_flat_repeat_can_drink_every_0_1_seconds(self):
        controller = self.make_controller([True] * 6)
        controller.settings.mp_cooldown_seconds = 0.1

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_mp(100.0, 25.0)
            controller._maybe_drink_mp(100.1, 25.0)
            controller._maybe_drink_mp(100.2, 25.0)

        self.assertEqual(tap_hotkey.call_count, 3)
        tap_hotkey.assert_called_with("End")
        self.assertEqual(
            controller.mp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.1, 25.0),
                PotionEffectAttempt(100.2, 25.0),
            ],
        )

    def test_hp_cooldown_blocks_before_0_1_seconds(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_cooldown_seconds = 0.1

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.05, 25.0)
            controller._maybe_drink_hp(100.1, 25.0)

        self.assertEqual(tap_hotkey.call_count, 2)
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.1, 25.0),
            ],
        )

    def test_hp_continuous_holds_once_until_above_threshold(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_continuous_enabled = True

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.2, 25.0)
            controller._maybe_drink_hp(100.3, 51.0)

        key_down.assert_called_once_with(0x2E)
        key_up.assert_called_once_with(0x2E)
        tap_hotkey.assert_not_called()
        self.assertEqual(controller.hp_potion_held_vk, 0)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_hp_continuous_hold_uses_potion_action_worker_when_available(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_continuous_enabled = True
        controller.potion_action_worker = Mock()

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.2, 51.0)

        controller.potion_action_worker.hold.assert_called_once_with("hp", 0x2E)
        controller.potion_action_worker.release.assert_called_once_with("hp", 0x2E)
        key_down.assert_not_called()
        key_up.assert_not_called()
        tap_hotkey.assert_not_called()

    def test_mp_continuous_holds_and_releases_configured_key(self):
        controller = self.make_controller([True] * 4)
        controller.settings.mp_continuous_enabled = True

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_mp(100.0, 25.0)
            controller._maybe_drink_mp(100.2, 51.0)

        key_down.assert_called_once_with(0x23)
        key_up.assert_called_once_with(0x23)
        tap_hotkey.assert_not_called()
        self.assertEqual(controller.mp_potion_held_vk, 0)

    def test_continuous_potion_invalid_key_releases_existing_hold(self):
        controller = self.make_controller([True] * 2)
        controller.settings.hp_continuous_enabled = True
        controller.settings.hp_key = "InvalidKey"
        controller.hp_potion_held_vk = 0x2E

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        key_up.assert_called_once_with(0x2E)
        key_down.assert_not_called()
        tap_hotkey.assert_not_called()
        self.assertEqual(controller.hp_potion_held_vk, 0)
        controller.gui.set_status.assert_called_with("HP 喝水鍵設定無效")

    def test_continuous_potion_releases_when_out_of_potion_hold_is_active(self):
        controller = self.make_controller([])
        controller.settings.hp_continuous_enabled = True
        controller.hp_potion_held_vk = 0x2E
        controller.hp_out_of_potion_hold = OutOfPotionHold(100.0, 25.0)

        with patch("maple_star.controller.key_up") as key_up:
            controller._maybe_drink_hp(100.0, 25.0)

        key_up.assert_called_once_with(0x2E)
        self.assertEqual(controller.hp_potion_held_vk, 0)

    def test_continuous_potion_releases_when_scripts_disabled(self):
        controller = self.make_controller([])
        controller.scripts_enabled = False
        controller.hp_potion_held_vk = 0x2E
        controller.mp_potion_held_vk = 0x23
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._pause_experience_for_inactive_state = Mock()

        with patch("maple_star.controller.key_up") as key_up:
            controller.update(100.0)

        self.assertEqual(key_up.call_args_list[0].args, (0x2E,))
        self.assertEqual(key_up.call_args_list[1].args, (0x23,))
        self.assertEqual(controller.hp_potion_held_vk, 0)
        self.assertEqual(controller.mp_potion_held_vk, 0)

    def test_continuous_potion_releases_on_key_capture(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = True
        controller.hp_potion_held_vk = 0x2E
        controller.mp_potion_held_vk = 0x23

        with patch("maple_star.controller.key_up") as key_up:
            controller.poll_control_hotkeys()

        self.assertEqual(key_up.call_args_list[0].args, (0x2E,))
        self.assertEqual(key_up.call_args_list[1].args, (0x23,))

    def test_continuous_potion_releases_when_foreground_lost(self):
        controller = self.make_controller([False])
        controller.next_capture_at = 999.0
        controller.pending_settings_snapshot = controller.settings.snapshot()
        controller.next_settings_save_at = None
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller.hp_potion_held_vk = 0x2E

        with patch("maple_star.controller.key_up") as key_up:
            controller.update(100.0)

        key_up.assert_called_once_with(0x2E)
        self.assertEqual(controller.hp_potion_held_vk, 0)

    def test_update_prioritizes_potion_send_before_effect_watch_and_experience(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.next_experience_capture_at = 0.0
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.settings.exp_efficiency_enabled = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._capture_bar_percent = Mock(side_effect=[25.0, 25.0])
        order = []
        controller._maybe_drink_hp = Mock(side_effect=lambda now, percent: order.append("hp"))
        controller._maybe_drink_mp = Mock(side_effect=lambda now, percent: order.append("mp"))
        controller._update_potion_effect_watch_cycles = Mock(
            side_effect=lambda now, hp, mp: order.append("watch")
        )
        controller._update_experience_efficiency = Mock(side_effect=lambda now: order.append("exp"))

        controller.update(100.0)

        self.assertEqual(order, ["hp", "mp", "watch", "exp"])

    def test_continuous_potion_observation_windows_are_throttled(self):
        controller = self.make_controller([True] * 6)
        controller.settings.hp_continuous_enabled = True

        with (
            patch("maple_star.controller.key_down"),
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.2, 25.0)
            controller._maybe_drink_hp(101.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(101.0, 25.0),
            ],
        )

    def test_continuous_potion_no_effect_hold_releases_held_key(self):
        controller = self.make_controller([])
        controller.hp_potion_held_vk = 0x2E

        with (
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file"),
            patch("builtins.print"),
        ):
            controller._enter_out_of_potion_hold("hp", "HP", 25.0, 100.0)

        key_up.assert_called_once_with(0x2E)
        self.assertIsNotNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_held_vk, 0)

    def test_continuous_potion_enters_hold_after_three_stable_no_effect_windows(self):
        controller = self.make_controller([True] * 6)
        controller.settings.hp_continuous_enabled = True
        controller._capture_bar_percent = Mock(return_value=49.0)

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file"),
            patch("builtins.print"),
        ):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                self.seed_stable_potion_samples(controller, "hp", now, 49.0)
                controller._maybe_drink_hp(now, 49.0)
                mature_at = now + POTION_EFFECT_OBSERVATION_SECONDS
                self.seed_stable_potion_samples(controller, "hp", mature_at, 49.0)
                self.assertTrue(controller._update_potion_effect_watch_cycles(mature_at, 49.0, 80.0))

        key_down.assert_called_once_with(0x2E)
        key_up.assert_called_once_with(0x2E)
        self.assertEqual(controller.hp_potion_no_effect_count, POTION_EFFECT_NO_EFFECT_LIMIT)
        self.assertIsNotNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_held_vk, 0)

    def test_hp_pending_observation_allows_repeat_when_percent_keeps_dropping(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_cooldown_seconds = 0.2
        controller._capture_bar_percent = Mock(side_effect=[25.0, 23.5])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.2, 23.5)

        self.assertEqual(tap_hotkey.call_count, 2)
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.2, 23.5),
            ],
        )

    def test_potion_watch_clears_when_bar_recovers_past_threshold(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [PotionEffectAttempt(100.0, 25.0)]
        controller.hp_potion_no_effect_count = 2

        self.assertTrue(
            controller._update_potion_effect_watch_cycles(
                100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                60.0,
                80.0,
            )
        )

        self.assertEqual(controller.hp_potion_effect_attempts, [])
        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertTrue(controller.auto_drink_enabled)

    def test_potion_watch_enters_mp_hold_after_repeated_no_effect_attempts_mature(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                mature_at = now + POTION_EFFECT_OBSERVATION_SECONDS
                controller.mp_potion_effect_attempts = [
                    PotionEffectAttempt(now, 49.0, pre_window_is_stable=True)
                ]
                self.seed_stable_potion_samples(controller, "mp", mature_at, 49.0)
                self.assertTrue(
                    controller._update_potion_effect_watch_cycles(
                        mature_at,
                        80.0,
                        49.0,
                    )
                )

        self.assertTrue(controller.auto_drink_enabled)
        self.assertIsNotNone(controller.mp_out_of_potion_hold)
        self.assertEqual(controller.mp_potion_effect_attempts, [])
        controller.gui.set_status.assert_called_with(
            "MP 疑似無藥水，已停止 MP 喝水；按 F11 恢復"
        )
        controller.gui.show_toggle_notice.assert_called_with("MP 疑似無藥水")
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_potion_watch_counts_rapid_taps_once_per_observation_window(self):
        controller = self.make_controller([])
        controller.mp_potion_effect_attempts = [
            PotionEffectAttempt(100.0 + index * 0.1, 49.0, pre_window_is_stable=True)
            for index in range(10)
        ]

        with patch("builtins.print"):
            self.seed_stable_potion_samples(controller, "mp", 101.0, 49.0)
            self.assertTrue(controller._update_potion_effect_watch_cycles(101.0, 80.0, 49.0))
            self.seed_stable_potion_samples(controller, "mp", 101.1, 49.0)
            self.assertTrue(controller._update_potion_effect_watch_cycles(101.1, 80.0, 49.0))

        self.assertEqual(controller.mp_potion_no_effect_count, 1)
        self.assertIsNone(controller.mp_out_of_potion_hold)

    def test_potion_watch_does_not_hold_mp_after_short_stable_confirmation(self):
        controller = self.make_controller([])
        mature_at = 100.0 + POTION_EFFECT_OBSERVATION_SECONDS
        controller.mp_potion_no_effect_count = 2
        controller.mp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 49.0, pre_window_is_stable=True)
        ]
        controller.mp_potion_recent_samples = [
            (mature_at - 1.6, 48.6),
            (mature_at - 1.2, 48.8),
            (mature_at - 0.8, 49.0),
            (mature_at - 0.4, 48.8),
            (mature_at - 0.1, 49.0),
        ]

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    mature_at,
                    80.0,
                    49.0,
                )
            )

        self.assertEqual(controller.mp_potion_no_effect_count, 2)
        self.assertIsNone(controller.mp_out_of_potion_hold)
        self.assertEqual(controller.mp_potion_effect_attempts, [])
        play_media.assert_not_called()

    def test_potion_watch_does_not_count_damage_as_no_effect(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 25.0, pre_window_is_stable=True)
        ]

        with patch("builtins.print"):
            keep_running = controller._update_potion_effect_watch_cycles(
                100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                20.0,
                80.0,
            )

        self.assertTrue(keep_running)
        self.assertTrue(controller.auto_drink_enabled)
        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_potion_watch_large_damage_window_does_not_count_flat_final_as_no_effect(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 25.0, pre_window_is_stable=True)
        ]
        controller.hp_potion_no_effect_count = 2

        with patch("builtins.print"):
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    100.0 + POTION_EFFECT_OBSERVATION_SECONDS / 2,
                    15.0,
                    80.0,
                )
            )
            keep_running = controller._update_potion_effect_watch_cycles(
                100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                25.0,
                80.0,
            )

        self.assertTrue(keep_running)
        self.assertTrue(controller.auto_drink_enabled)
        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_potion_watch_recent_damage_blocks_following_flat_no_effect_count(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 35.0, pre_window_is_stable=True)
        ]
        controller.hp_potion_no_effect_count = 2

        with patch("builtins.print"):
            self.assertTrue(controller._update_potion_effect_watch_cycles(100.5, 25.0, 80.0))
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                    35.0,
                    80.0,
                )
            )
            controller.hp_potion_effect_attempts = [
                PotionEffectAttempt(101.2, 35.0, pre_window_is_stable=True)
            ]
            keep_running = controller._update_potion_effect_watch_cycles(
                101.2 + POTION_EFFECT_OBSERVATION_SECONDS,
                35.0,
                80.0,
            )

        self.assertTrue(keep_running)
        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_potion_watch_sustained_damage_pressure_blocks_flat_no_effect_after_grace(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 35.0, pre_window_is_stable=True)
        ]

        with patch("builtins.print"):
            self.assertTrue(controller._update_potion_effect_watch_cycles(100.5, 25.0, 80.0))
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                    35.0,
                    80.0,
                )
            )

            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 105.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                controller.hp_potion_effect_attempts = [PotionEffectAttempt(now, 35.0)]
                self.assertTrue(
                    controller._update_potion_effect_watch_cycles(
                        now + POTION_EFFECT_OBSERVATION_SECONDS,
                        35.0,
                        80.0,
                    )
                )

        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_potion_watch_low_hp_pressure_blocks_no_effect_even_without_observed_drop(self):
        controller = self.make_controller([])

        with patch("builtins.print"):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                controller.hp_potion_effect_attempts = [
                    PotionEffectAttempt(now, 35.0, pre_window_is_stable=True)
                ]
                self.assertTrue(
                    controller._update_potion_effect_watch_cycles(
                        now + POTION_EFFECT_OBSERVATION_SECONDS,
                        35.0,
                        80.0,
                    )
                )

        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_potion_watch_enters_hp_hold_after_stable_pre_and_post_no_effect_confirmations(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                mature_at = now + POTION_EFFECT_OBSERVATION_SECONDS
                controller.hp_potion_effect_attempts = [
                    PotionEffectAttempt(now, 49.0, pre_window_is_stable=True)
                ]
                self.seed_stable_potion_samples(controller, "hp", mature_at, 49.0)
                self.assertTrue(
                    controller._update_potion_effect_watch_cycles(
                        mature_at,
                        49.0,
                        80.0,
                    )
                )

        self.assertEqual(controller.hp_potion_no_effect_count, POTION_EFFECT_NO_EFFECT_LIMIT)
        self.assertIsNotNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        controller.gui.set_status.assert_called_with(
            "HP 疑似無藥水，已停止 HP 喝水；按 F11 恢復"
        )
        controller.gui.show_toggle_notice.assert_called_with("HP 疑似無藥水")
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_potion_watch_does_not_hold_hp_when_pre_window_is_not_stable(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT + 1):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                controller.hp_potion_effect_attempts = [PotionEffectAttempt(now, 49.0)]
                self.assertTrue(
                    controller._update_potion_effect_watch_cycles(
                        now + POTION_EFFECT_OBSERVATION_SECONDS,
                        49.0,
                        80.0,
                    )
                )

        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_not_called()

    def test_potion_watch_resets_no_effect_count_when_bar_is_unstable_without_attempts(self):
        controller = self.make_controller([])
        controller.hp_potion_no_effect_count = 2
        controller.hp_potion_recent_samples = [
            (100.0, 49.0),
            (100.4, 47.5),
            (100.8, 49.0),
        ]

        with patch("builtins.print"):
            self.assertTrue(controller._update_potion_effect_watch_cycles(101.0, 49.0, 80.0))

        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)

    def test_potion_watch_unstable_recent_bar_delays_quiet_hp_confirmation(self):
        controller = self.make_controller([])
        controller.hp_potion_no_effect_count = 2
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 49.0, pre_window_is_stable=True)
        ]
        controller.hp_potion_recent_samples = [
            (100.0, 49.0),
            (100.4, 47.5),
            (100.8, 49.0),
        ]

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                    49.0,
                    80.0,
                )
            )

        self.assertEqual(controller.hp_potion_no_effect_count, 2)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_not_called()

        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(102.0, 49.0, pre_window_is_stable=True)
        ]
        self.seed_stable_potion_samples(controller, "hp", 102.0 + POTION_EFFECT_OBSERVATION_SECONDS, 49.0)

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    102.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                    49.0,
                    80.0,
                )
            )

        self.assertEqual(controller.hp_potion_no_effect_count, POTION_EFFECT_NO_EFFECT_LIMIT)
        self.assertIsNotNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_potion_watch_recent_hp_damage_blocks_confirmation_after_short_stable_window(self):
        controller = self.make_controller([])
        mature_at = 100.0 + POTION_EFFECT_OBSERVATION_SECONDS
        controller.hp_potion_no_effect_count = 2
        controller.hp_potion_recent_damage_at = mature_at - 4.0
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 49.0, pre_window_is_stable=True)
        ]
        self.seed_stable_potion_samples(controller, "hp", mature_at, 49.0)

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    mature_at,
                    49.0,
                    80.0,
                )
            )

        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_not_called()

    def test_potion_watch_can_hold_hp_below_threshold_when_stable_no_effect(self):
        controller = self.make_controller([])
        mature_at = 100.0 + POTION_EFFECT_OBSERVATION_SECONDS
        controller.hp_potion_no_effect_count = 2
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 30.0, pre_window_is_stable=True)
        ]
        self.seed_stable_potion_samples(controller, "hp", mature_at, 30.0)

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            self.assertTrue(
                controller._update_potion_effect_watch_cycles(
                    mature_at,
                    30.0,
                    80.0,
                )
            )

        self.assertEqual(controller.hp_potion_no_effect_count, POTION_EFFECT_NO_EFFECT_LIMIT)
        self.assertIsNotNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_potion_watch_can_hold_hp_at_high_percent_threshold(self):
        controller = self.make_controller([])
        controller.settings.hp_threshold_percent = 85.0

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                mature_at = now + POTION_EFFECT_OBSERVATION_SECONDS
                controller.hp_potion_effect_attempts = [
                    PotionEffectAttempt(now, 85.0, pre_window_is_stable=True)
                ]
                self.seed_stable_potion_samples(controller, "hp", mature_at, 85.0)
                self.assertTrue(
                    controller._update_potion_effect_watch_cycles(
                        mature_at,
                        85.0,
                        80.0,
                    )
                )

        self.assertEqual(controller.hp_potion_no_effect_count, POTION_EFFECT_NO_EFFECT_LIMIT)
        self.assertIsNotNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        controller.gui.set_status.assert_called_with(
            "HP 疑似無藥水，已停止 HP 喝水；按 F11 恢復"
        )
        controller.gui.show_toggle_notice.assert_called_with("HP 疑似無藥水")
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_potion_watch_counts_at_most_one_no_effect_when_attempts_mature_together(self):
        controller = self.make_controller([])
        controller.mp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 49.0, pre_window_is_stable=True),
            PotionEffectAttempt(100.2, 49.0, pre_window_is_stable=True),
            PotionEffectAttempt(100.4, 49.0, pre_window_is_stable=True),
        ]

        with patch("builtins.print"):
            self.seed_stable_potion_samples(
                controller,
                "mp",
                100.4 + POTION_EFFECT_OBSERVATION_SECONDS,
                49.0,
            )
            keep_running = controller._update_potion_effect_watch_cycles(
                100.4 + POTION_EFFECT_OBSERVATION_SECONDS,
                80.0,
                49.0,
            )

        self.assertTrue(keep_running)
        self.assertEqual(controller.mp_potion_no_effect_count, 1)
        self.assertIsNone(controller.mp_out_of_potion_hold)
        self.assertEqual(controller.mp_potion_effect_attempts, [])

    def test_out_of_potion_hold_plays_auto_drink_stop_sound(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._enter_out_of_potion_hold("hp", "HP", 25.0, 100.0)

        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
        controller.gui.set_status.assert_called_with(
            "HP 疑似無藥水，已停止 HP 喝水；按 F11 恢復"
        )
        controller.gui.show_toggle_notice.assert_called_with("HP 疑似無藥水")

    def test_potion_watch_uncertain_capture_drops_observation_without_counting(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [PotionEffectAttempt(100.0, 25.0)]
        controller.hp_potion_no_effect_count = 2

        controller._clear_uncertain_potion_observations(None, 80.0)

        self.assertEqual(controller.hp_potion_effect_attempts, [])
        self.assertEqual(controller.hp_potion_no_effect_count, 2)
        self.assertIsNone(controller.hp_out_of_potion_hold)

    def test_potion_watch_effective_recovery_below_threshold_resets_no_effect_count(self):
        controller = self.make_controller([])
        controller.hp_potion_effect_attempts = [
            PotionEffectAttempt(100.0, 25.0, pre_window_is_stable=True)
        ]
        controller.hp_potion_no_effect_count = 2

        with patch("builtins.print"):
            keep_running = controller._update_potion_effect_watch_cycles(
                100.0 + POTION_EFFECT_OBSERVATION_SECONDS,
                35.0,
                80.0,
            )

        self.assertTrue(keep_running)
        self.assertTrue(controller.auto_drink_enabled)
        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_hp_hold_does_not_block_mp_auto_drink(self):
        controller = self.make_controller([True, True])
        controller.hp_out_of_potion_hold = OutOfPotionHold(100.0, 25.0)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(101.0, 25.0)
            controller._maybe_drink_mp(101.0, 25.0)

        tap_hotkey.assert_called_once_with("End")
        self.assertEqual(controller.last_mp_drink_at, 101.0)

    def test_mp_hold_does_not_block_hp_auto_drink(self):
        controller = self.make_controller([True, True])
        controller.mp_out_of_potion_hold = OutOfPotionHold(100.0, 25.0)

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_mp(101.0, 25.0)
            controller._maybe_drink_hp(101.0, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        self.assertEqual(controller.last_hp_drink_at, 101.0)

    def test_hp_confirm_capture_rejects_mismatched_unchecked_fallback(self):
        controller = self.make_controller([True])
        controller._capture_bar_percent = Mock(
            side_effect=[None] * BAR_CONFIRM_CAPTURE_ATTEMPTS + [80.0]
        )

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("maple_star.controller.time.sleep"),
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        controller._log_unstable_bar.assert_called_once_with(100.0, "HP")

    def test_unstable_bar_log_is_throttled(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller.last_unstable_bar_at = -999.0

        with patch("builtins.print") as print_mock:
            controller._log_unstable_bar(100.0, "HP")
            controller._log_unstable_bar(107.0, "HP")
            controller._log_unstable_bar(108.1, "HP")

        self.assertEqual(print_mock.call_count, 2)

    def test_mp_does_not_tap_if_target_loses_focus_after_confirm_capture(self):
        controller = self.make_controller([True, False])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_mp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(controller.last_mp_drink_at, -999.0)
        controller.gui.set_current_percentages.assert_called_with(None, None)

    def test_emergency_stop_toggles_total_switch_off_and_requests_macro_stop(self):
        controller = self.make_controller([])

        with patch("builtins.print"):
            controller.emergency_stop()

        self.assertFalse(controller.scripts_enabled)
        self.assertFalse(controller.auto_drink_enabled)
        self.assertTrue(controller.consume_emergency_stop_requested())
        self.assertFalse(controller.consume_emergency_stop_requested())
        self.assertEqual(controller.last_action, "Pause 總開關")
        controller.gui.set_status.assert_called_with("Pause 總開關：所有功能已暫停")

    def test_emergency_stop_toggles_total_switch_back_on(self):
        controller = self.make_controller([])
        controller.scripts_enabled = False
        controller.auto_drink_enabled = False

        with patch("builtins.print"):
            controller.emergency_stop()

        self.assertTrue(controller.scripts_enabled)
        self.assertTrue(controller.auto_drink_enabled)
        self.assertFalse(controller.consume_emergency_stop_requested())
        self.assertEqual(controller.last_action, "Pause 總開關啟用")
        controller.gui.set_status.assert_called_with("總開關已啟用")

    def test_toggle_auto_drink_clears_out_of_potion_hold_without_disabling(self):
        controller = self.make_controller([])
        controller.hp_out_of_potion_hold = OutOfPotionHold(100.0, 25.0)
        controller.hp_potion_no_effect_count = POTION_EFFECT_NO_EFFECT_LIMIT
        controller.mp_potion_no_effect_count = 1

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller.toggle_auto_drink_enabled()

        self.assertTrue(controller.auto_drink_enabled)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertIsNone(controller.mp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_no_effect_count, 0)
        self.assertEqual(controller.mp_potion_no_effect_count, 0)
        play_media.assert_called_once_with(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")
        controller.gui.set_status.assert_called_with("自動喝水已恢復")
        controller.gui.show_toggle_notice.assert_called_with("自動喝水已恢復")

    def test_toggle_auto_drink_uses_stop_and_start_sounds(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller.toggle_auto_drink_enabled()
            controller.toggle_auto_drink_enabled()

        self.assertEqual(play_media.call_args_list[0].args, (AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop"))
        self.assertEqual(play_media.call_args_list[1].args, (AUTO_DRINK_START_SOUND_PATH, "auto_drink_start"))

    def test_play_media_file_sets_volume_to_20_percent_before_playing(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller._play_toggle_beep = Mock()
        winmm = SimpleNamespace(mciSendStringW=Mock(return_value=0))
        sound_path = AUTO_DRINK_STOP_SOUND_PATH

        with patch("maple_star.controller.ctypes.windll", SimpleNamespace(winmm=winmm), create=True):
            controller._play_media_file(sound_path, "test_sound")

        commands = [call.args[0] for call in winmm.mciSendStringW.call_args_list]
        self.assertIn("setaudio test_sound volume to 200", commands)
        self.assertLess(commands.index("setaudio test_sound volume to 200"), commands.index("play test_sound from 0"))
        controller._play_toggle_beep.assert_not_called()

    def test_play_toggle_beep_uses_tone_sequence(self):
        controller = AutoPotionController.__new__(AutoPotionController)

        with (
            patch("maple_star.controller.winsound.Beep") as beep,
            patch("maple_star.controller.winsound.MessageBeep") as message_beep,
        ):
            controller._play_toggle_beep(((659, 45), (880, 55)))

        self.assertEqual(beep.call_args_list[0].args, (659, 45))
        self.assertEqual(beep.call_args_list[1].args, (880, 55))
        message_beep.assert_not_called()

    def test_play_toggle_beep_falls_back_to_message_beep(self):
        controller = AutoPotionController.__new__(AutoPotionController)

        with (
            patch("maple_star.controller.winsound.Beep", side_effect=RuntimeError),
            patch("maple_star.controller.winsound.MessageBeep") as message_beep,
        ):
            controller._play_toggle_beep(((659, 45), (880, 55)))

        message_beep.assert_called_once()

    def test_control_hotkeys_are_ignored_while_key_capture_is_active(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = True
        controller.control_hotkey_worker = Mock()
        controller.toggle_hotkey_was_down = True
        controller.emergency_stop_hotkey_was_down = True
        controller.experience_toggle_hotkey_was_down = True
        controller.experience_reset_hotkey_was_down = True
        controller.pickup_toggle_hotkey_was_down = True
        controller._discard_control_hotkey_messages = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()
        controller._try_reset_experience_statistics = Mock()
        controller._try_toggle_pickup = Mock()

        controller.poll_control_hotkeys()

        controller._discard_control_hotkey_messages.assert_called_once()
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()
        controller._try_reset_experience_statistics.assert_not_called()
        controller._try_toggle_pickup.assert_not_called()
        self.assertFalse(controller.toggle_hotkey_was_down)
        self.assertFalse(controller.emergency_stop_hotkey_was_down)
        self.assertFalse(controller.experience_toggle_hotkey_was_down)
        self.assertFalse(controller.experience_reset_hotkey_was_down)
        self.assertFalse(controller.pickup_toggle_hotkey_was_down)

    def test_control_hotkeys_are_ignored_once_after_key_capture_finishes(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = True
        controller.control_hotkey_worker = Mock()
        controller._discard_control_hotkey_messages = Mock()
        controller._sync_control_hotkey_down_states = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()

        controller.poll_control_hotkeys()

        controller._discard_control_hotkey_messages.assert_called_once()
        controller._sync_control_hotkey_down_states.assert_called_once()
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()

    def test_control_hotkeys_stay_ignored_until_captured_key_is_released(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.side_effect = [True, False, False]
        controller.control_hotkey_worker = None
        controller.registered_toggle_hotkey_vk = 0x7A
        controller.registered_emergency_stop_hotkey_vk = 0x13
        controller.registered_experience_toggle_hotkey_vk = 0x79
        controller.registered_experience_reset_hotkey_vk = 0x78
        controller.registered_pickup_toggle_hotkey_vk = 0x77
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller.experience_toggle_hotkey_was_down = False
        controller.experience_reset_hotkey_was_down = False
        controller.pickup_toggle_hotkey_was_down = False
        controller._discard_control_hotkey_messages = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()
        controller._try_reset_experience_statistics = Mock()
        controller._try_toggle_pickup = Mock()

        with patch("maple_star.controller.user32.GetAsyncKeyState", return_value=ASYNC_KEY_DOWN_MASK):
            controller.poll_control_hotkeys()
            controller.poll_control_hotkeys()

        self.assertTrue(controller.control_hotkeys_suppressed_until_release)
        self.assertTrue(controller.toggle_hotkey_was_down)
        self.assertTrue(controller.experience_toggle_hotkey_was_down)
        self.assertTrue(controller.experience_reset_hotkey_was_down)
        self.assertTrue(controller.pickup_toggle_hotkey_was_down)
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()
        controller._try_toggle_pickup.assert_not_called()
        controller._try_reset_experience_statistics.assert_not_called()

        with patch("maple_star.controller.user32.GetAsyncKeyState", return_value=0):
            controller.poll_control_hotkeys()

        self.assertFalse(controller.control_hotkeys_suppressed_until_release)
        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()
        controller._try_reset_experience_statistics.assert_not_called()
        controller._try_toggle_pickup.assert_not_called()

    def test_control_hotkey_worker_events_are_dispatched_without_main_thread_key_polling(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = False
        controller.control_hotkey_worker = Mock()
        controller.control_hotkey_worker.drain_events.return_value = [
            "toggle",
            "experience_toggle",
            "experience_reset",
            CONTROL_HOTKEY_PICKUP_TOGGLE,
            "emergency_stop",
        ]
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()
        controller._try_reset_experience_statistics = Mock()
        controller._try_toggle_pickup = Mock()
        controller.emergency_stop = Mock()

        with patch("maple_star.controller.user32.GetAsyncKeyState") as key_state:
            controller.poll_control_hotkeys()

        key_state.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_called_once()
        controller._try_toggle_experience_efficiency.assert_called_once()
        controller._try_reset_experience_statistics.assert_called_once()
        controller._try_toggle_pickup.assert_called_once()
        controller.emergency_stop.assert_called_once()

    def test_control_hotkey_worker_event_does_not_fall_back_to_second_key_edge(self):
        class FakeWorker:
            def __init__(self):
                self.events = [CONTROL_HOTKEY_EXPERIENCE_TOGGLE]

            def drain_events(self):
                events = self.events
                self.events = []
                return events

            def cached_down_states(self):
                return {CONTROL_HOTKEY_EXPERIENCE_TOGGLE: True}

        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = False
        controller.control_hotkey_worker = FakeWorker()
        controller.registered_experience_toggle_hotkey_vk = 0x79
        controller.experience_toggle_hotkey_was_down = False
        controller._try_toggle_experience_efficiency = Mock()

        with (
            patch("maple_star.controller.time.monotonic", return_value=100.0),
            patch("maple_star.controller.user32.GetAsyncKeyState", return_value=ASYNC_KEY_DOWN_MASK) as key_state,
        ):
            controller.poll_control_hotkeys()
            controller.poll_control_hotkeys()

        key_state.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_called_once_with(100.0)
        self.assertTrue(controller.experience_toggle_hotkey_was_down)

    def test_register_control_hotkeys_updates_worker_hotkeys(self):
        controller = self.make_controller([])
        controller.control_hotkey_worker = Mock()

        controller._register_toggle_hotkey(0x7A, 0x13, 0x79, 0x78)

        controller.control_hotkey_worker.update_hotkeys.assert_called_once_with(
            {
                "toggle": 0x7A,
                "emergency_stop": 0x13,
                "experience_toggle": 0x79,
                "experience_reset": 0x78,
                "pickup_toggle": 0,
            }
        )

    def test_experience_hotkey_toggles_exp_efficiency(self):
        controller = self.make_controller([])
        controller.control_hotkey_worker = None
        controller.registered_toggle_hotkey_vk = 0x7A
        controller.registered_emergency_stop_hotkey_vk = 0x13
        controller.registered_experience_toggle_hotkey_vk = 0x79
        controller.registered_experience_reset_hotkey_vk = 0x78
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller.experience_toggle_hotkey_was_down = False
        controller.experience_reset_hotkey_was_down = False
        controller.last_experience_toggle_hotkey_at = -999.0
        controller._try_toggle_scripts_enabled = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_experience_efficiency = Mock()
        controller._try_reset_experience_statistics = Mock()

        def key_state(vk_code):
            return ASYNC_KEY_DOWN_MASK if vk_code == 0x79 else 0

        with patch("maple_star.controller.user32.GetAsyncKeyState", side_effect=key_state):
            controller.poll_control_hotkeys()

        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_called_once()
        controller._try_reset_experience_statistics.assert_not_called()

    def test_experience_reset_hotkey_resets_statistics(self):
        controller = self.make_controller([])
        controller.control_hotkey_worker = None
        controller.registered_toggle_hotkey_vk = 0x7A
        controller.registered_emergency_stop_hotkey_vk = 0x13
        controller.registered_experience_toggle_hotkey_vk = 0x79
        controller.registered_experience_reset_hotkey_vk = 0x78
        controller.toggle_hotkey_was_down = False
        controller.emergency_stop_hotkey_was_down = False
        controller.experience_toggle_hotkey_was_down = False
        controller.experience_reset_hotkey_was_down = False
        controller._try_toggle_scripts_enabled = Mock()
        controller.emergency_stop = Mock()
        controller._try_toggle_experience_efficiency = Mock()
        controller._try_reset_experience_statistics = Mock()

        def key_state(vk_code):
            return ASYNC_KEY_DOWN_MASK if vk_code == 0x78 else 0

        with patch("maple_star.controller.user32.GetAsyncKeyState", side_effect=key_state):
            controller.poll_control_hotkeys()

        controller.emergency_stop.assert_not_called()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()
        controller._try_reset_experience_statistics.assert_called_once()

    def test_try_reset_experience_statistics_updates_gui(self):
        controller = self.make_controller([])
        controller.settings.experience_reset_hotkey = "F9"
        controller.reset_experience_statistics = Mock()

        with patch("builtins.print") as print_mock:
            controller._try_reset_experience_statistics(100.0)

        controller.reset_experience_statistics.assert_called_once()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "已重置")
        controller.gui.set_status.assert_called_once_with("經驗統計已重置")
        controller.gui.show_toggle_notice.assert_called_once_with("經驗統計已重置")
        self.assertEqual(controller.last_action, "F9 經驗統計重置")
        print_mock.assert_called_once_with("F9：經驗統計已重置")

    def test_pickup_toggle_holds_and_releases_configured_key_with_sounds(self):
        controller = self.make_controller([])
        controller.settings.pickup_key = "Z"

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller.toggle_pickup_enabled()
            controller.toggle_pickup_enabled()

        key_down.assert_called_once_with(0x5A)
        key_up.assert_called_once_with(0x5A)
        self.assertEqual(play_media.call_args_list[0].args, (AUTO_PICKUP_START_SOUND_PATH, "pickup_start"))
        self.assertEqual(play_media.call_args_list[1].args, (AUTO_PICKUP_STOP_SOUND_PATH, "pickup_stop"))
        self.assertFalse(controller.pickup_enabled)
        self.assertEqual(controller.pickup_held_vk, 0)

    def test_pickup_toggle_without_key_stays_disabled(self):
        controller = self.make_controller([])
        controller.settings.pickup_key = None

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller.toggle_pickup_enabled()

        key_down.assert_not_called()
        play_media.assert_not_called()
        self.assertFalse(controller.pickup_enabled)
        controller.gui.set_status.assert_called_with("拾取鍵未設定")
        controller.gui.show_toggle_notice.assert_called_with("拾取鍵未設定")

    def test_pickup_toggle_with_invalid_key_stays_disabled(self):
        controller = self.make_controller([])
        controller.settings.pickup_key = "InvalidKey"

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller.toggle_pickup_enabled()

        key_down.assert_not_called()
        play_media.assert_not_called()
        self.assertFalse(controller.pickup_enabled)
        controller.gui.set_status.assert_called_with("拾取鍵設定無效")
        controller.gui.show_toggle_notice.assert_called_with("拾取鍵設定無效")

    def test_emergency_stop_releases_pickup_key(self):
        controller = self.make_controller([])
        controller.pickup_enabled = True
        controller.pickup_held_vk = 0x5A

        with (
            patch("maple_star.controller.key_up") as key_up,
            patch("builtins.print"),
        ):
            controller.emergency_stop()

        key_up.assert_called_once_with(0x5A)
        self.assertEqual(controller.pickup_held_vk, 0)

    def test_key_capture_releases_pickup_key(self):
        controller = self.make_controller([])
        controller.gui.is_detecting_key.return_value = True
        controller.pickup_enabled = True
        controller.pickup_held_vk = 0x5A

        with patch("maple_star.controller.key_up") as key_up:
            controller.poll_control_hotkeys()

        key_up.assert_called_once_with(0x5A)
        self.assertEqual(controller.pickup_held_vk, 0)

    def test_pickup_releases_when_target_loses_foreground_and_reholds_on_return(self):
        controller = self.make_controller([True, False, True])
        controller.settings.pickup_key = "Z"
        controller.pickup_enabled = True
        controller.control_hotkey_worker = None
        controller.next_capture_at = 999.0
        controller.pending_settings_snapshot = controller.settings.snapshot()
        controller.next_settings_save_at = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
        ):
            controller.update(10.0)
            controller.update(11.0)
            controller.update(12.0)

        self.assertEqual(key_down.call_args_list[0].args, (0x5A,))
        self.assertEqual(key_down.call_args_list[1].args, (0x5A,))
        key_up.assert_called_once_with(0x5A)
        self.assertEqual(controller.pickup_held_vk, 0x5A)

    def test_cleanup_releases_pickup_key(self):
        controller = self.make_controller([])
        controller.pickup_held_vk = 0x5A
        controller._unregister_toggle_hotkey = Mock()
        controller.control_hotkey_worker = None
        controller.experience_ocr_executor = Mock()
        controller.sct = Mock()
        controller.gui.closed = True
        controller.original_stdout = None
        controller.original_stderr = None

        with (
            patch("maple_star.controller.key_up") as key_up,
            patch("maple_star.controller.save_settings"),
        ):
            controller.cleanup()

        key_up.assert_called_once_with(0x5A)
        controller._unregister_toggle_hotkey.assert_called_once()

    def test_toggle_experience_efficiency_preserves_statistics_when_disabling(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.next_experience_capture_at = 999.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2)
        controller._stop_experience_ocr_job = Mock()

        with patch("builtins.print"):
            controller.toggle_experience_efficiency()

        controller.gui.set_exp_efficiency_enabled.assert_called_once_with(False)
        controller._stop_experience_ocr_job.assert_called_once()
        controller.gui.set_experience_snapshot.assert_called_once()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "已停用，保留統計")
        self.assertEqual(controller.last_action, "F10 經驗統計停用")

    def test_toggle_experience_efficiency_freezes_elapsed_while_disabled(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gui.set_exp_efficiency_enabled.side_effect = (
            lambda enabled: setattr(controller.settings, "exp_efficiency_enabled", enabled)
        )
        controller._stop_experience_ocr_job = Mock()
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.experience_tracker.add_reading(0.0, 1000, 10.0)
        controller.experience_tracker.add_reading(60.0, 7000, 70.0)
        before = controller.experience_tracker.snapshot(60.0)

        with (
            patch("maple_star.controller.time.monotonic", return_value=60.0),
            patch("builtins.print"),
        ):
            controller.toggle_experience_efficiency()
        frozen = controller.experience_tracker.snapshot(controller._experience_effective_time(660.0))

        self.assertEqual(frozen.elapsed_seconds, before.elapsed_seconds)
        self.assertEqual(frozen.xp_per_5m, before.xp_per_5m)
        self.assertEqual(frozen.xp_per_10m, before.xp_per_10m)
        self.assertEqual(frozen.xp_per_hour, before.xp_per_hour)
        self.assertEqual(frozen.eta_seconds, before.eta_seconds)

    def test_toggle_experience_efficiency_clears_stale_rejection_when_enabling(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = False
        controller.next_experience_capture_at = 999.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(
            current_exp=110000,
            current_percent=11.0,
            xp_per_5m=30000.0,
            sample_count=2,
            status="樣本拒絕：基準修正候選：EXP 回落但需二次確認",
        )
        controller._stop_experience_ocr_job = Mock()

        with patch("builtins.print"):
            controller.toggle_experience_efficiency()

        controller.gui.set_exp_efficiency_enabled.assert_called_once_with(True)
        controller._stop_experience_ocr_job.assert_called_once()
        controller.experience_tracker.clear_transient_rejection.assert_called_once()
        self.assertEqual(controller.next_experience_capture_at, 0.0)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.current_exp, 110000)
        self.assertEqual(snapshot.xp_per_5m, 30000.0)
        self.assertEqual(snapshot.status, "等待下一次 EXP 樣本")
        self.assertEqual(controller.last_action, "F10 經驗統計啟用")

    def test_experience_snapshot_waits_for_next_ocr_interval_before_refreshing(self):
        controller = self.make_controller([])
        controller.experience_ocr_job = None
        controller.experience_ocr_burst = None
        controller.next_experience_capture_at = 10.0
        controller.experience_tracker = Mock()

        controller._update_experience_efficiency(5.0)

        controller.experience_tracker.snapshot.assert_not_called()
        controller.gui.set_experience_snapshot.assert_not_called()

    def test_missing_hud_experience_snapshot_refreshes_only_on_ocr_interval(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.next_experience_capture_at = 10.0
        controller._stop_experience_ocr_job = Mock()
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        controller._pause_experience_for_missing_hud(5.0)

        controller._stop_experience_ocr_job.assert_called_once()
        controller.experience_tracker.snapshot.assert_not_called()
        controller.gui.set_experience_snapshot.assert_not_called()
        self.assertEqual(controller.next_experience_capture_at, 10.0)

        controller._pause_experience_for_missing_hud(10.0)

        self.assertEqual(controller._stop_experience_ocr_job.call_count, 2)
        controller.experience_tracker.snapshot.assert_called_once_with(5.0)
        controller.gui.set_experience_snapshot.assert_called_once()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "HUD 未出現，保留統計")
        self.assertEqual(
            controller.next_experience_capture_at,
            10.0 + EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
        )

    def test_target_inactive_pauses_experience_clock_before_update_returns(self):
        controller = self.make_controller([False, False])
        controller.settings.exp_efficiency_enabled = True
        controller.control_hotkey_worker = None
        controller.next_capture_at = 0.0
        controller.next_experience_capture_at = 0.0
        controller.pending_settings_snapshot = controller.settings.snapshot()
        controller.next_settings_save_at = None
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1)
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()

        controller.update(100.0)
        controller.update(160.0)

        controller.experience_tracker.snapshot.assert_called_with(100.0)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "等待楓星前景，保留統計")

    def test_missing_hud_stops_pending_experience_ocr_without_recording_result(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=132553,
                    percent=18.36,
                    text="132553[18.36%]",
                    confidence=0.98,
                    success=True,
                )

            def cancel(self):
                return True

        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.next_experience_capture_at = 0.0
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=55.0, future=DoneFuture())
        controller.experience_ocr_burst = SimpleNamespace(
            started_at=55.0,
            next_capture_at=56.0,
            regions=[],
            image_frames=[],
            capture_count=1,
        )
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=1)

        controller._pause_experience_for_missing_hud(60.0)

        self.assertIsNone(controller.experience_ocr_job)
        self.assertIsNone(controller.experience_ocr_burst)
        controller.experience_tracker.add_reading.assert_not_called()
        controller.experience_tracker.record_ocr_result.assert_not_called()

    def test_resumed_experience_ocr_sample_excludes_paused_duration(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=132553,
                    percent=18.36,
                    text="132553[18.36%]",
                    confidence=0.98,
                    success=True,
                )

            def cancel(self):
                return True

        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.add_reading.return_value = True
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2)

        controller._pause_experience_for_missing_hud(60.0)
        controller._resume_experience_clock(660.0)
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=670.0, future=DoneFuture())

        with patch("builtins.print"):
            self.assertTrue(controller._process_experience_ocr_job(670.0))

        controller.experience_tracker.add_reading.assert_called_once_with(
            70.0,
            132553,
            18.36,
            confidence=0.98,
        )

    def test_pending_experience_ocr_job_does_not_refresh_snapshot_every_loop(self):
        class PendingFuture:
            def done(self):
                return False

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=PendingFuture())
        controller.experience_tracker = Mock()

        self.assertTrue(controller._process_experience_ocr_job(1.0))

        controller.experience_tracker.snapshot.assert_not_called()
        controller.gui.set_experience_snapshot.assert_not_called()

    def test_delayed_experience_ocr_job_refreshes_status(self):
        class PendingFuture:
            def done(self):
                return False

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=PendingFuture())
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        self.assertTrue(controller._process_experience_ocr_job(6.0))

        controller.experience_tracker.snapshot.assert_called_once()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "OCR 延遲：6.0s")

    def test_waiting_experience_burst_does_not_refresh_snapshot_every_loop(self):
        controller = self.make_controller([])
        controller.experience_ocr_job = None
        controller.experience_ocr_burst = SimpleNamespace(
            started_at=0.0,
            next_capture_at=10.0,
            regions=[],
            image_frames=[],
            capture_count=1,
        )
        controller.experience_tracker = Mock()

        self.assertTrue(controller._continue_experience_ocr_burst(5.0))

        controller.experience_tracker.snapshot.assert_not_called()
        controller.gui.set_experience_snapshot.assert_not_called()

    def test_experience_ocr_uses_ui_percent_from_reading(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=132553,
                    percent=18.36,
                    text="132553[18.36%]",
                    confidence=0.98,
                    success=True,
                )

        controller = self.make_controller([])
        controller.last_failed_experience_ocr_signature = controller._experience_ocr_image_signature(
            [[np.zeros((18, 140, 4), dtype=np.uint8)]]
        )
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=DoneFuture())
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.add_reading.return_value = True
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(
            sample_count=1,
            sample_attempt_count=1,
            sample_accept_count=1,
            ocr_attempt_count=1,
            ocr_success_count=1,
            xp_per_5m=1000.0,
            xp_per_10m=2000.0,
            xp_per_hour=12000.0,
            eta_seconds=300.0,
            rate_confidence=0.75,
        )

        with (
            patch("builtins.print") as print_mock,
            patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log,
        ):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        controller.experience_tracker.add_reading.assert_called_once_with(8.0, 132553, 18.36, confidence=0.98)
        controller.experience_tracker.record_ocr_result.assert_called_once_with(True)
        controller.gui.set_experience_snapshot.assert_called_once()
        self.assertEqual(controller.next_experience_capture_at, EXPERIENCE_CAPTURE_INTERVAL_SECONDS)
        self.assertIsNone(controller.last_failed_experience_ocr_signature)
        print_mock.assert_not_called()
        payload = exp_debug_log.call_args.args[0]
        self.assertEqual(payload["decision"], "accepted")
        self.assertEqual(payload["current_exp"], 132553)
        self.assertEqual(payload["percent"], 18.36)
        self.assertEqual(payload["xp_per_10m"], 2000.0)

    def test_experience_ocr_does_not_use_merged_text_as_initial_baseline(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=4266438,
                    percent=94.86,
                    text="4266438194.86",
                    confidence=0.91,
                    success=True,
                    needs_bar_percent_guard=True,
                )

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=0.0, future=DoneFuture())
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = []
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=0)

        with patch("builtins.print"):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        controller.experience_tracker.add_reading.assert_not_called()
        controller.experience_tracker.record_ocr_result.assert_called_once_with(True)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "等待明確 EXP 樣本")

    def test_experience_ocr_accepted_guarded_merge_uses_burst_next_time(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=4266438,
                    percent=94.86,
                    text="4266438194.86",
                    confidence=0.91,
                    success=True,
                    needs_bar_percent_guard=True,
                )

        controller = self.make_controller([])
        image_signature = controller._experience_ocr_image_signature([[np.zeros((18, 140, 4), dtype=np.uint8)]])
        controller.experience_ocr_job = ExperienceOcrJob(
            submitted_at=0.0,
            future=DoneFuture(),
            image_signature=image_signature,
            image_frames=[[np.full((18, 140, 3), 255, dtype=np.uint8)]],
        )
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.samples = [object()]
        controller.experience_tracker.add_reading.return_value = True
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        with patch("builtins.print"):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        controller.experience_tracker.add_reading.assert_called_once_with(
            8.0,
            4266438,
            94.86,
            confidence=0.91,
        )
        self.assertEqual(controller.last_failed_experience_ocr_signature, image_signature)

    def test_experience_ocr_waits_for_second_clear_initial_baseline(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=12846656,
                    percent=76.90,
                    text="12846656[76.90%]",
                    confidence=0.98,
                    success=True,
                )

        controller = self.make_controller([])
        image_signature = controller._experience_ocr_image_signature([[np.zeros((18, 140, 4), dtype=np.uint8)]])
        controller.experience_ocr_job = ExperienceOcrJob(
            submitted_at=0.0,
            future=DoneFuture(),
            image_signature=image_signature,
            image_frames=[[np.full((18, 140, 3), 255, dtype=np.uint8)]],
        )
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = ExperienceEfficiencyTracker()

        with (
            patch("builtins.print") as print_mock,
            patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log,
        ):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertIsNone(snapshot.current_exp)
        self.assertEqual(snapshot.status, "等待下一次 EXP 基準確認")
        self.assertEqual(controller.experience_tracker.ocr_success_count, 1)
        self.assertIsNone(controller.last_failed_experience_ocr_signature)
        print_mock.assert_not_called()

    def test_experience_ocr_failure_keeps_business_status_and_logs_raw_text(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    text="1325531836",
                    confidence=0.91,
                    reason="EXP 百分比解析失敗",
                )

        controller = self.make_controller([])
        image_signature = controller._experience_ocr_image_signature([[np.zeros((18, 140, 4), dtype=np.uint8)]])
        controller.experience_ocr_job = ExperienceOcrJob(
            submitted_at=0.0,
            future=DoneFuture(),
            image_signature=image_signature,
        )
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        with (
            patch("builtins.print") as print_mock,
            patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log,
        ):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "統計中")
        controller.experience_tracker.record_ocr_result.assert_called_once_with(False)
        self.assertEqual(controller.last_failed_experience_ocr_signature, image_signature)
        printed = "\n".join(call.args[0] for call in print_mock.call_args_list)
        self.assertIn("1325531836", printed)
        self.assertIn("經驗效率 OCR 錯誤", printed)
        payload = exp_debug_log.call_args.args[0]
        self.assertEqual(payload["decision"], "ocr_failure")
        self.assertEqual(payload["text"], "1325531836")
        self.assertEqual(payload["reason"], "EXP 百分比解析失敗")

    def test_experience_rejected_ocr_reading_logs_raw_text_and_values(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=288900,
                    percent=27.08,
                    text="288900[27.08%]",
                    confidence=0.98,
                    success=True,
                    reason="OK",
                )

        controller = self.make_controller([])
        image_signature = controller._experience_ocr_image_signature([[np.zeros((18, 140, 4), dtype=np.uint8)]])
        controller.experience_ocr_job = ExperienceOcrJob(
            submitted_at=0.0,
            future=DoneFuture(),
            image_signature=image_signature,
            image_frames=[[np.full((18, 140, 3), 255, dtype=np.uint8)]],
        )
        controller.next_experience_capture_at = 0.0
        controller.experience_tracker = Mock()
        controller.experience_tracker.add_reading.return_value = False
        controller.experience_tracker.last_status = "樣本拒絕：EXP 跳動與百分比不一致"
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=2, status="統計中")

        with (
            patch("builtins.print") as print_mock,
            patch("maple_star.controllers.auto_potion_controller.save_experience_ocr_learning_case", return_value="exp-unit") as save_case,
            patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log,
        ):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        controller.experience_tracker.record_ocr_result.assert_called_once_with(True)
        self.assertEqual(controller.last_failed_experience_ocr_signature, image_signature)
        save_case.assert_called_once()
        self.assertEqual(save_case.call_args.kwargs["trigger"], "tracker_rejected")
        self.assertEqual(save_case.call_args.kwargs["final_reading"].text, "288900[27.08%]")
        printed = "\n".join(call.args[0] for call in print_mock.call_args_list)
        self.assertIn("經驗效率 異常樣本拒絕", printed)
        self.assertIn("EXP OCR learning case: exp-unit", printed)
        self.assertIn("288900[27.08%]", printed)
        self.assertIn("exp=288,900", printed)
        self.assertIn("percent=27.08%", printed)
        payload = exp_debug_log.call_args.args[0]
        self.assertEqual(payload["decision"], "rejected")
        self.assertEqual(payload["text"], "288900[27.08%]")
        self.assertEqual(payload["current_exp"], 288900)
        self.assertEqual(payload["percent"], 27.08)
        self.assertEqual(payload["tracker_status"], "樣本拒絕：EXP 跳動與百分比不一致")
        self.assertEqual(payload["learning_case_id"], "exp-unit")

    def test_missing_experience_region_preserves_last_statistics(self):
        controller = self.make_controller([])
        controller.experience_ocr_job = None
        controller.next_experience_capture_at = 0.0
        controller._experience_text_region = Mock(return_value=None)
        preserved = ExperienceSnapshot(
            current_exp=718035,
            current_percent=58.37,
            xp_per_5m=84965,
            xp_per_10m=169929,
            xp_per_hour=1019576,
            eta_seconds=1808,
            sample_count=3,
            status="統計中",
        )
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = preserved

        controller._update_experience_efficiency(12.0)

        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.current_exp, 718035)
        self.assertEqual(snapshot.xp_per_5m, 84965)
        self.assertEqual(snapshot.xp_per_10m, 169929)
        self.assertEqual(snapshot.xp_per_hour, 1019576)
        self.assertEqual(snapshot.status, "找不到 EXP 區域，保留統計")
        self.assertGreater(controller.next_experience_capture_at, 12.0)

    def test_experience_text_region_crops_to_right_side_text_band(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (486, 1025, 253, 28),
            "mp": (795, 1025, 253, 28),
        }
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1920, 1080))

        region = controller._experience_text_region()

        self.assertIsNotNone(region)
        assert region is not None
        left, top, width, height = region
        self.assertGreater(left, 486)
        self.assertGreaterEqual(top, 1053)
        self.assertLess(width, 1048 - 486)
        self.assertGreaterEqual(height, 14)

    def test_experience_text_regions_include_wider_fallback_roi(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (100, 700, 250, 24),
            "mp": (400, 700, 250, 24),
        }
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 800))

        regions = controller._experience_text_regions()

        self.assertEqual(len(regions), 2)
        primary, wide = regions
        self.assertLess(wide[0], primary[0])
        self.assertGreaterEqual(wide[0] + wide[2], primary[0] + primary[2])
        self.assertGreaterEqual(wide[3], primary[3])

    def test_bottom_bar_search_areas_try_full_client_before_16_9_crop(self):
        controller = self.make_controller([])

        areas = controller._bottom_bar_search_areas((0, 0, 1440, 1080))

        self.assertGreaterEqual(len(areas), 2)
        self.assertEqual(areas[0].reference_width, 1440)
        self.assertEqual(areas[0].reference_height, 1080)
        self.assertGreaterEqual(areas[0].top + areas[0].height, 1080)
        self.assertEqual(areas[1].reference_width, 1440)
        self.assertLess(areas[1].reference_height, 1080)

    def test_bottom_bar_pair_accepts_tall_non_16_9_hud_geometry(self):
        controller = self.make_controller([])

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(260, 116, 178)],
            mp_candidates=[(494, 116, 178)],
            hp_mask=None,
            mp_mask=None,
            search_left=230,
            search_top=907,
            search_width=1008,
            search_height=173,
            client_width=1440,
            client_height=1080,
        )

        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(regions["hp"][0], regions["mp"][0])
        self.assertGreaterEqual(regions["hp"][1], 907)
        self.assertGreaterEqual(regions["mp"][1], 907)

    def test_find_bottom_bar_pair_regions_detects_full_height_non_16_9_bottom_hud(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {}
        controller.bottom_bar_track_regions = {}
        controller.bottom_bar_regions_at = -999.0
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1440, 1080))
        image = np.zeros((173, 1008, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[112:125, 260:438, :3] = (30, 60, 220)
        image[112:125, 494:672, :3] = (220, 110, 40)
        controller.sct = Mock()
        controller.sct.grab.return_value = image

        regions = controller._find_bottom_bar_pair_regions(use_cache=False)

        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(regions["hp"][0], regions["mp"][0])
        self.assertGreaterEqual(regions["hp"][1], 1015)
        self.assertGreaterEqual(regions["mp"][1], 1015)
        controller.sct.grab.assert_called_once()

    def test_bottom_bar_pair_rejects_right_side_shortcut_colors(self):
        controller = self.make_controller([])

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(761, 100, 134), (179, 118, 220)],
            mp_candidates=[(906, 100, 134), (488, 118, 220)],
            hp_mask=None,
            mp_mask=None,
            search_left=307,
            search_top=900,
            search_width=1344,
            search_height=180,
            client_width=1920,
            client_height=1080,
        )

        self.assertLess(regions["hp"][0], 700)
        self.assertLess(regions["mp"][0], 1000)


if __name__ == "__main__":
    unittest.main()
