import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

from maple_star.controller import (
    AUTO_DRINK_POTION_CHECK_SOUND_PATH,
    AUTO_DRINK_START_SOUND_PATH,
    AUTO_DRINK_STOP_SOUND_PATH,
    AUTO_PICKUP_START_SOUND_PATH,
    AUTO_PICKUP_STOP_SOUND_PATH,
    AutoPotionController,
    ExperienceOcrJob,
)
from maple_star.constants import (
    ASYNC_KEY_DOWN_MASK,
    AUTO_DRINK_DISABLE_HOLD_SECONDS,
    AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS,
    BAR_CONFIRM_CAPTURE_ATTEMPTS,
    BAR_TRANSIENT_CAPTURE_ATTEMPTS,
    DEFAULT_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_BURST_CAPTURE_ATTEMPTS,
    EXPERIENCE_BURST_CAPTURE_INTERVAL_SECONDS,
    EXPERIENCE_CAPTURE_INTERVAL_SECONDS,
    PICKUP_DISABLE_HOLD_SECONDS,
    PICKUP_TOGGLE_DEBOUNCE_SECONDS,
    POTION_CONTINUOUS_HOLD_REFRESH_SECONDS,
    POTION_FAST_CAPTURE_INTERVAL_SECONDS,
    POTION_EFFECT_NO_EFFECT_LIMIT,
    POTION_EFFECT_OBSERVATION_SECONDS,
)
from maple_star.controllers.auto_potion_controller import (
    EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS,
    EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS,
    EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS,
    EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS,
    EXPERIENCE_MOUSE_IDLE_STATUS_UPDATE_SECONDS,
    EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES,
    POTION_BLOCKED_SOUND_INTERVAL_SECONDS,
    POTION_CHECK_SOUND_INTERVAL_SECONDS,
    RUNTIME_POTION_STATUS_TIMEOUT_SECONDS,
)
from maple_star.experience import (
    ExperienceEfficiencyTracker,
    ExperienceOcrImage,
    ExperienceSnapshot,
    ExperienceTextReading,
    read_experience_burst_frames_in_worker,
    read_experience_tooltip_in_worker,
)
from maple_star.models.controller_state import BarDetectionDebug, HudSearchArea, OutOfPotionHold, PotionEffectAttempt
from maple_star.services.control_hotkey_worker import CONTROL_HOTKEY_EXPERIENCE_TOGGLE, CONTROL_HOTKEY_PICKUP_TOGGLE
from maple_star.services.potion_action_worker import PotionAction, PotionActionWorker, _apply_potion_action
from maple_star.services.runtime_processes import (
    ExperienceStatus,
    HeadlessRuntimeGui,
    PotionControl,
    PotionStatus,
    WorkerCrashed,
    _experience_status_signature,
    _is_target_hwnd_active,
    _potion_status,
    _potion_status_signature,
)
from maple_star.settings import AutoPotionSettings


class AutoPotionForegroundGuardTests(unittest.TestCase):
    class FakeRuntime:
        def __init__(self):
            self.settings_sent = []
            self.targets_sent = []
            self.potion_controls = []
            self.experience_controls = []
            self.potion_statuses = []
            self.experience_statuses = []
            self.potion_restarts = []
            self.stopped = False
            self._potion_alive = True
            self._experience_alive = True

        def send_settings(self, settings):
            self.settings_sent.append(settings.snapshot())

        def send_target_window(self, hwnd):
            self.targets_sent.append(hwnd)

        def send_potion_control(self, command):
            self.potion_controls.append(command)

        def send_experience_control(self, command):
            self.experience_controls.append(command)

        def drain_potion_statuses(self, limit=None):
            statuses = list(self.potion_statuses)
            self.potion_statuses.clear()
            return statuses

        def drain_experience_statuses(self, limit=None):
            statuses = list(self.experience_statuses)
            self.experience_statuses.clear()
            return statuses

        def potion_alive(self):
            return self._potion_alive

        def experience_alive(self):
            return self._experience_alive

        def restart_potion(self, settings, target_hwnd):
            self.potion_restarts.append((settings.snapshot(), target_hwnd))
            self._potion_alive = True

        def stop(self):
            self.stopped = True

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
            character_stat_hotkey="V",
        )
        if active_sequence:
            controller.is_target_window_active = Mock(side_effect=active_sequence)
        else:
            controller.is_target_window_active = Mock(return_value=True)
        controller.gui = Mock()
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = False
        controller.gui.is_key_detection_release_pending.return_value = False
        controller.gui.is_app_window_foreground.return_value = False
        controller.gui.set_exp_efficiency_enabled.side_effect = (
            lambda enabled: setattr(controller.settings, "exp_efficiency_enabled", enabled)
        )
        controller.gui.set_potion_enabled.side_effect = lambda hp_enabled, mp_enabled: (
            setattr(controller.settings, "hp_enabled", hp_enabled),
            setattr(controller.settings, "mp_enabled", mp_enabled),
        )
        controller.last_hp_drink_at = -999.0
        controller.last_mp_drink_at = -999.0
        controller.potion_send_prevalidated_at = -999.0
        controller.hp_pending_potion_send_at = -999.0
        controller.mp_pending_potion_send_at = -999.0
        controller.hp_pending_potion_send_percent = None
        controller.mp_pending_potion_send_percent = None
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
        controller.last_potion_blocked_sound_at = -999.0
        controller.last_potion_check_sound_at = -999.0
        controller.last_error_at = -999.0
        controller.last_unstable_bar_at = -999.0
        controller.last_bar_debug = {
            "hp": BarDetectionDebug("hp"),
            "mp": BarDetectionDebug("mp"),
        }
        controller.bottom_bar_regions = {}
        controller.bottom_bar_track_regions = {}
        controller.bottom_bar_regions_client = {}
        controller.bottom_bar_track_regions_client = {}
        controller.bottom_bar_client_size = None
        controller.bottom_bar_client_bounds = None
        controller.bottom_bar_regions_at = -999.0
        controller.stable_bar_samples = {}
        controller.last_experience_ocr_error_at = -999.0
        controller.last_experience_ocr_error_reason = ""
        controller.last_completed_experience_ocr_signature = None
        controller.last_failed_experience_ocr_signature = None
        controller.emergency_stop_requested = False
        controller.auto_drink_enabled = True
        controller.scripts_enabled = True
        controller.auto_drink_potion_option_snapshot = None
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
        controller.last_toggle_hotkey_at = -999.0
        controller.last_experience_toggle_hotkey_at = -999.0
        controller.last_experience_reset_hotkey_at = -999.0
        controller.last_pickup_toggle_hotkey_at = -999.0
        controller.auto_drink_disable_hold_started_at = -999.0
        controller.pickup_disable_hold_started_at = -999.0
        controller.pickup_enabled = False
        controller.pickup_held_vk = 0
        controller.hp_potion_held_vk = 0
        controller.mp_potion_held_vk = 0
        controller.hp_potion_hold_refreshed_at = -999.0
        controller.mp_potion_hold_refreshed_at = -999.0
        controller.gameplay_hud_active = False
        controller.pending_settings_snapshot = controller.settings.snapshot()
        controller.next_settings_save_at = None
        controller.control_hotkeys_suppressed_until_release = False
        controller.last_action = "啟動"
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.next_experience_capture_at = 0.0
        controller.experience_ocr_job = None
        controller.experience_ocr_burst = None
        controller.experience_tooltip_ocr_failures = 0
        controller.experience_10m_checkpoint_capture = None
        controller.experience_10m_checkpoint_ocr_job = None
        controller.next_experience_10m_checkpoint_at = 0.0
        controller.experience_10m_checkpoint_stopped = False
        controller.experience_10m_checkpoint_attempts = 0
        controller.experience_baseline_cursor_position = None
        controller.experience_tooltip_baseline_failed = False
        controller.experience_pause_started_at = None
        controller.experience_total_paused_seconds = 0.0
        controller.runtime_processes_enabled = False
        controller.runtime_processes = None
        controller.runtime_settings_snapshot = None
        controller.runtime_target_hwnd = 0
        controller.runtime_control_state = None
        controller.runtime_potion_generation = 0
        controller.runtime_experience_generation = 0
        controller.runtime_potion_crash_reported = False
        controller.runtime_experience_crash_reported = False
        controller.last_runtime_experience_alert_status = ""
        controller.last_applied_potion_status_signature = None
        controller.last_applied_experience_status_signature = None
        controller.experience_only_runtime = False
        controller.direct_bar_capture_context = Mock()
        controller.last_runtime_potion_status_at = -999.0
        controller._log_unstable_bar = Mock()
        controller._play_toggle_beep = Mock()
        controller._capture_bar_percent = Mock(return_value=25.0)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        controller.bottom_hud_layout = None
        controller.experience_10m_checkpoint_tooltip_failed = False
        controller.mouse_activity_observer = SimpleNamespace(last_activity_at=-999.0)
        controller.last_experience_mouse_idle_delay_log_at = -999.0
        controller.last_experience_mouse_idle_status_at = -999.0
        controller.last_experience_mouse_idle_status_key = None
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

    def colorref(self, red, green, blue):
        return int(red) | (int(green) << 8) | (int(blue) << 16)

    def run_capture_interval_update(
        self,
        *,
        hp_percent,
        mp_percent,
        auto_drink_enabled=True,
        hp_enabled=True,
        mp_enabled=True,
        hp_hold=False,
        mp_hold=False,
    ):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.auto_drink_enabled = auto_drink_enabled
        controller.settings.hp_enabled = hp_enabled
        controller.settings.mp_enabled = mp_enabled
        controller.hp_out_of_potion_hold = OutOfPotionHold(99.0, hp_percent) if hp_hold else None
        controller.mp_out_of_potion_hold = OutOfPotionHold(99.0, mp_percent) if mp_hold else None
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._capture_bar_percents = Mock(return_value=(hp_percent, mp_percent))
        controller._maybe_drink_hp = Mock()
        controller._maybe_drink_mp = Mock()
        controller._update_potion_effect_watch_cycles = Mock()
        controller._stop_experience_ocr_job = Mock()
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot()

        controller.update(100.0)

        return controller

    def test_direct_bar_cache_uses_client_relative_coordinates_after_window_move(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (120, 220, 110, 12),
            "mp": (260, 220, 110, 12),
        }
        controller.bottom_bar_track_regions = {
            "hp": (125, 223, 100, 6),
            "mp": (265, 223, 100, 6),
        }
        controller._cache_bottom_bar_client_regions((100, 200, 800, 600))

        with (
            patch.object(controller, "_foreground_client_bounds", return_value=(150, 240, 800, 600)),
            patch.object(controller, "_sample_direct_bar_percent_from_region", return_value=(42.0, "OK:Direct", None)) as sample,
            patch.object(controller, "_find_bottom_bar_pair_regions") as find_regions,
        ):
            percent = AutoPotionController._capture_bar_percent(controller, "hp")

        self.assertEqual(percent, 42.0)
        sample.assert_called_once_with((175, 263, 100, 6), "hp", require_clear_tail=False)
        find_regions.assert_not_called()

    def test_capture_bar_percent_relocates_then_reads_direct_only(self):
        controller = self.make_controller([])
        fallback_region = (120, 220, 110, 12)

        with (
            patch.object(
                controller,
                "_capture_bar_percent_direct",
                side_effect=[None, 42.0],
            ) as direct,
            patch.object(controller, "_find_bottom_bar_pair_regions", return_value={"hp": fallback_region}),
            patch.object(controller, "_capture_bar_percent_from_region", return_value=55.0) as screenshot_percent,
        ):
            percent = AutoPotionController._capture_bar_percent(controller, "hp")

        self.assertEqual(percent, 42.0)
        direct.assert_has_calls([
            call("hp", require_clear_tail=False),
            call("hp", require_clear_tail=False),
        ])
        screenshot_percent.assert_not_called()

    def test_cached_bar_reuse_requires_both_hp_and_mp_to_sample(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (120, 220, 110, 12),
            "mp": (260, 220, 110, 12),
        }
        controller.bottom_bar_track_regions = {
            "hp": (125, 223, 100, 6),
            "mp": (265, 223, 100, 6),
        }
        controller._cache_bottom_bar_client_regions((100, 200, 800, 600))

        with (
            patch.object(controller, "_foreground_client_bounds", return_value=(100, 200, 800, 600)),
            patch.object(
                controller,
                "_sample_direct_bar_percent_from_region",
                side_effect=[
                    (72.0, "OK:Direct", None),
                    (None, "直接取色找不到符合顏色的填滿欄位", None),
                ],
            ) as sample,
        ):
            reused = controller._reuse_cached_bottom_bar_regions_with_direct_sample(10.0)

        self.assertFalse(reused)
        self.assertEqual(sample.call_count, 2)

    def test_cached_bar_reuse_rejects_implausible_pair_geometry(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (120, 220, 110, 12),
            "mp": (260, 320, 110, 12),
        }
        controller.bottom_bar_track_regions = dict(controller.bottom_bar_regions)
        controller._cache_bottom_bar_client_regions((100, 200, 800, 600))

        with (
            patch.object(controller, "_foreground_client_bounds", return_value=(100, 200, 800, 600)),
            patch.object(controller, "_sample_direct_bar_percent_from_region") as sample,
        ):
            reused = controller._reuse_cached_bottom_bar_regions_with_direct_sample(10.0)

        self.assertFalse(reused)
        sample.assert_not_called()

    def test_direct_gdi_buffer_sampling_reads_synthetic_hp_percent(self):
        controller = self.make_controller([])
        region = (10, 20, 100, 9)
        image = np.zeros((region[3], region[2], 4), dtype=np.uint8)
        image[:, :61] = (40, 40, 220, 255)
        image[:, 61:] = (30, 30, 30, 255)

        with patch.object(controller, "_direct_bar_image_from_region", return_value=image):
            percent, reason, tail_clear = controller._sample_direct_bar_percent_from_region(region, "hp")

        self.assertIsNotNone(percent)
        self.assertAlmostEqual(percent, 61.0, delta=2.0)
        self.assertEqual(reason, "OK:Direct")
        self.assertIsNone(tail_clear)

    def test_direct_gdi_empty_track_reads_zero_percent(self):
        controller = self.make_controller([])
        image = np.full((9, 100, 4), (52, 52, 52, 255), dtype=np.uint8)

        percent, reason, tail_clear = controller._sample_direct_bar_percent_from_image(image, "hp")

        self.assertEqual(percent, 0.0)
        self.assertEqual(reason, "OK:EmptyTrack")
        self.assertIsNone(tail_clear)

    def test_direct_gdi_clamps_track_padding_before_sampling(self):
        controller = self.make_controller([])
        image = np.full((14, 130, 4), (245, 245, 245, 255), dtype=np.uint8)
        image[3:11, 22:118] = (46, 46, 46, 255)
        image[3:11, 22:64] = (35, 35, 225, 255)

        percent, reason, tail_clear = controller._sample_direct_bar_percent_from_image(image, "hp")

        self.assertIsNotNone(percent)
        self.assertAlmostEqual(percent, 43.75, delta=3.0)
        self.assertTrue(reason.startswith("OK:DirectClamp"))
        self.assertIsNone(tail_clear)

    def test_direct_gdi_clamps_mp_track_padding_before_sampling(self):
        controller = self.make_controller([])
        image = np.full((14, 130, 4), (245, 245, 245, 255), dtype=np.uint8)
        image[3:11, 20:120] = (46, 46, 46, 255)
        image[3:11, 20:55] = (230, 160, 25, 255)

        percent, reason, tail_clear = controller._sample_direct_bar_percent_from_image(image, "mp")

        self.assertIsNotNone(percent)
        self.assertAlmostEqual(percent, 35.0, delta=3.0)
        self.assertTrue(reason.startswith("OK:DirectClamp"))
        self.assertIsNone(tail_clear)

    def test_direct_gdi_tooltip_obstruction_is_uncertain_not_zero_percent(self):
        controller = self.make_controller([])
        image = np.full((14, 140, 4), (92, 72, 48, 255), dtype=np.uint8)
        cv2.putText(image, "STR:+8", (7, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (235, 235, 235, 255), 1, cv2.LINE_AA)
        cv2.putText(image, "+DEX", (78, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 145, 255, 255), 1, cv2.LINE_AA)

        percent, reason, tail_clear = controller._sample_direct_bar_percent_from_image(image, "hp")

        self.assertIsNone(percent)
        self.assertTrue(reason.startswith("直接取色"))
        self.assertNotEqual(reason, "OK:EmptyTrack")
        self.assertIsNone(tail_clear)

    def test_capture_bar_percent_returns_none_without_screenshot_percent_fallback(self):
        controller = self.make_controller([])
        fallback_region = (10, 20, 100, 12)
        with (
            patch.object(controller, "_capture_bar_percent_direct", side_effect=[None, None]),
            patch.object(controller, "_find_bottom_bar_pair_regions", return_value={"hp": fallback_region}),
            patch.object(controller, "_capture_bar_percent_from_region", return_value=25.0) as screenshot_percent,
        ):
            percent = AutoPotionController._capture_bar_percent(controller, "hp")

        self.assertIsNone(percent)
        screenshot_percent.assert_not_called()
        self.assertEqual(controller.direct_bar_failure_count, 1)

    def test_capture_bar_percent_require_clear_tail_is_still_direct_only(self):
        controller = self.make_controller([])
        fallback_region = (10, 20, 100, 12)
        with (
            patch.object(controller, "_capture_bar_percent_direct", side_effect=[None, None]) as direct,
            patch.object(controller, "_find_bottom_bar_pair_regions", return_value={"hp": fallback_region}),
            patch.object(controller, "_capture_bar_percent_from_region", return_value=25.0) as screenshot_percent,
        ):
            percent = AutoPotionController._capture_bar_percent(controller, "hp", require_clear_tail=True)

        self.assertIsNone(percent)
        direct.assert_has_calls([
            call("hp", require_clear_tail=True),
            call("hp", require_clear_tail=True),
        ])
        screenshot_percent.assert_not_called()

    def test_screenshot_bar_capture_still_reads_preview_percent(self):
        controller = self.make_controller([])
        region = (10, 20, 100, 12)

        with (
            patch.object(controller, "_foreground_client_bounds", return_value=(100, 200, 800, 600)),
            patch.object(controller, "_bar_percent_from_region_snapshot", return_value=(25.0, "OK", None)),
        ):
            percent = controller._capture_bar_percent_from_region(region, "hp")

        self.assertEqual(percent, 25.0)

    def test_combined_direct_bar_sampling_reads_hp_mp_from_one_capture(self):
        controller = self.make_controller([])
        controller.bottom_bar_regions = {
            "hp": (110, 205, 100, 8),
            "mp": (240, 205, 100, 8),
        }
        controller.bottom_bar_track_regions = dict(controller.bottom_bar_regions)
        controller._cache_bottom_bar_client_regions((100, 200, 800, 600))
        controller.direct_bar_failure_count = 2
        union_image = np.zeros((8, 230, 4), dtype=np.uint8)

        with (
            patch.object(controller, "_foreground_client_bounds", return_value=(100, 200, 800, 600)),
            patch.object(controller, "_direct_bar_image_from_region", return_value=union_image) as capture,
            patch.object(
                controller,
                "_sample_direct_bar_percent_from_image",
                side_effect=[(55.0, "OK:Direct", None), (77.0, "OK:Direct", None)],
            ) as sample,
        ):
            hp_percent, mp_percent = controller._capture_bar_percents()

        self.assertEqual((hp_percent, mp_percent), (55.0, 77.0))
        capture.assert_called_once_with((110, 205, 230, 8))
        self.assertEqual(sample.call_count, 2)
        self.assertEqual(controller.direct_bar_failure_count, 0)

    def test_runtime_bar_regions_sync_into_direct_cache(self):
        controller = self.make_controller([])
        controller._target_client_bounds = Mock(return_value=(100, 200, 800, 600))

        controller._apply_runtime_bar_detection_region(
            "hp",
            (110, 205, 100, 8),
            55.0,
            (112, 206, 96, 6),
        )
        controller._apply_runtime_bar_detection_region(
            "mp",
            (240, 205, 100, 8),
            77.0,
            (242, 206, 96, 6),
        )

        cached = controller._cached_bottom_bar_screen_regions_for_current_client()

        self.assertIsNotNone(cached)
        regions, track_regions, client_bounds = cached
        self.assertEqual(client_bounds, (100, 200, 800, 600))
        self.assertEqual(regions["hp"], (110, 205, 100, 8))
        self.assertEqual(regions["mp"], (240, 205, 100, 8))
        self.assertEqual(track_regions["hp"], (112, 206, 96, 6))
        self.assertEqual(track_regions["mp"], (242, 206, 96, 6))

    def test_capture_bar_percents_locates_then_reads_direct_only(self):
        controller = self.make_controller([])

        with (
            patch.object(
                controller,
                "_capture_bar_percents_direct",
                side_effect=[None, (55.0, 77.0)],
            ) as direct,
            patch.object(
                controller,
                "_find_bottom_bar_pair_regions",
                return_value={"hp": (10, 20, 100, 8), "mp": (10, 36, 100, 8)},
            ) as locate,
            patch.object(controller, "_capture_bar_percent_from_region") as screenshot_percent,
        ):
            hp_percent, mp_percent = controller._capture_bar_percents()

        self.assertEqual((hp_percent, mp_percent), (55.0, 77.0))
        self.assertEqual(direct.call_count, 2)
        locate.assert_called_once()
        screenshot_percent.assert_not_called()

    def test_capture_bar_percents_returns_none_when_locator_succeeds_but_direct_fails(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_capture_bar_percents_direct", side_effect=[None, None]),
            patch.object(
                controller,
                "_find_bottom_bar_pair_regions",
                return_value={"hp": (10, 20, 100, 8), "mp": (10, 36, 100, 8)},
            ),
            patch.object(controller, "_capture_bar_percent_from_region") as screenshot_percent,
        ):
            hp_percent, mp_percent = controller._capture_bar_percents()

        self.assertEqual((hp_percent, mp_percent), (None, None))
        screenshot_percent.assert_not_called()
        self.assertEqual(controller.direct_bar_failure_count, 1)

    def test_direct_bar_failure_warning_after_three_failures_and_success_resets(self):
        controller = self.make_controller([])
        controller._record_direct_bar_failure("direct fail 1")
        controller._record_direct_bar_failure("direct fail 2")
        controller._record_direct_bar_failure("direct fail 3")

        with patch("builtins.print") as print_mock:
            emitted = controller._emit_direct_bar_failure_warning_if_needed(100.0)

        self.assertTrue(emitted)
        controller.gui.set_status.assert_called_with("HP/MP 直接取色連續失敗，已暫停自動喝水")
        controller.gui.show_toggle_notice.assert_called_once_with("HP/MP 直接取色失敗")
        print_mock.assert_called_once()

        controller._record_direct_bar_success()

        self.assertEqual(controller.direct_bar_failure_count, 0)
        self.assertEqual(controller.last_direct_bar_failure_reason, "")

    def test_direct_bar_image_reuses_capture_context(self):
        controller = self.make_controller([])
        context = Mock()
        context.capture.side_effect = [
            np.zeros((8, 100, 4), dtype=np.uint8),
            np.ones((8, 100, 4), dtype=np.uint8),
        ]
        controller.direct_bar_capture_context = context

        first = controller._direct_bar_image_from_region((10, 20, 100, 8))
        second = controller._direct_bar_image_from_region((30, 20, 100, 8))

        self.assertEqual(first.shape, (8, 100, 4))
        self.assertEqual(second.shape, (8, 100, 4))
        self.assertEqual(context.capture.call_count, 2)

    def build_synthetic_bottom_hud(
        self,
        controller,
        *,
        scale=1.0,
        hp_fill=1.0,
        mp_fill=1.0,
        exp_fill=0.62,
        wrong_mp_color=False,
        bar_body_vertical_inset=0,
        exp_yellow_green_top=False,
        neutral_hp_mp_gap=False,
        exp_bright_dividers=False,
    ):
        image = np.zeros((180, 980, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[:, :, :3] = (22, 22, 22)
        label_x = 50
        hp_y = 78
        exp_y = round(hp_y + 31 * scale)
        bar_gap = max(8, round(10 * scale))
        hp_bar_width = round(230 * scale)
        bar_height = max(9, round(14 * scale))
        hp_template = controller._hud_label_template("hp", scale)
        mp_template = controller._hud_label_template("mp", scale)
        exp_template = controller._hud_label_template("exp", scale)
        hp_bar_left = label_x + hp_template.shape[1] + bar_gap
        mp_label_x = hp_bar_left + hp_bar_width + round(34 * scale)
        mp_bar_left = mp_label_x + mp_template.shape[1] + bar_gap
        exp_bar_left = label_x + exp_template.shape[1] + bar_gap
        exp_bar_width = mp_bar_left + hp_bar_width - exp_bar_left

        def paste_label(template, left, top):
            mask = template > 0
            patch = image[top : top + template.shape[0], left : left + template.shape[1], :3]
            patch[mask] = (235, 235, 235)

        paste_label(hp_template, label_x, hp_y)
        paste_label(mp_template, mp_label_x, hp_y)
        paste_label(exp_template, label_x, exp_y)

        hp_bar_top = hp_y + max(2, round((hp_template.shape[0] - bar_height) / 2))
        mp_bar_top = hp_bar_top
        exp_bar_top = exp_y + max(2, round((exp_template.shape[0] - bar_height) / 2))
        image[hp_bar_top : hp_bar_top + bar_height, hp_bar_left : hp_bar_left + hp_bar_width, :3] = (72, 72, 72)
        image[mp_bar_top : mp_bar_top + bar_height, mp_bar_left : mp_bar_left + hp_bar_width, :3] = (72, 72, 72)
        image[exp_bar_top : exp_bar_top + bar_height, exp_bar_left : exp_bar_left + exp_bar_width, :3] = (72, 72, 72)
        if neutral_hp_mp_gap:
            image[
                hp_bar_top : hp_bar_top + bar_height,
                hp_bar_left + hp_bar_width : mp_label_x,
                :3,
            ] = (72, 72, 72)
        hp_fill_width = max(4, round(hp_bar_width * hp_fill))
        mp_fill_width = max(4, round(hp_bar_width * mp_fill))
        exp_fill_width = max(4, round(exp_bar_width * exp_fill))
        body_inset = max(0, min(bar_height // 2 - 1, round(bar_body_vertical_inset * scale)))
        body_top = hp_bar_top + body_inset
        body_bottom = hp_bar_top + bar_height - body_inset
        exp_body_top = exp_bar_top + body_inset
        exp_body_bottom = exp_bar_top + bar_height - body_inset
        image[body_top:body_bottom, hp_bar_left : hp_bar_left + hp_fill_width, :3] = (40, 60, 220)
        mp_color = (40, 60, 220) if wrong_mp_color else (220, 110, 40)
        image[body_top:body_bottom, mp_bar_left : mp_bar_left + mp_fill_width, :3] = mp_color
        image[exp_body_top:exp_body_bottom, exp_bar_left : exp_bar_left + exp_fill_width, :3] = (45, 210, 95)
        if exp_yellow_green_top:
            exp_mid = exp_body_top + max(1, (exp_body_bottom - exp_body_top) // 2)
            image[exp_body_top:exp_mid, exp_bar_left : exp_bar_left + exp_fill_width, :3] = (45, 210, 195)
        if exp_bright_dividers:
            for divider_ratio in (0.38, 0.48, 0.58):
                divider_x = exp_bar_left + round(exp_bar_width * divider_ratio)
                image[exp_bar_top : exp_bar_top + bar_height, divider_x : divider_x + 1, :3] = (210, 210, 210)
        text = "16720794[33.11%]"
        text_x = exp_bar_left + round(exp_bar_width * 0.58)
        text_y = exp_bar_top + bar_height - 1
        cv2.putText(image, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.46 * scale, (240, 240, 240, 255), max(1, round(1.2 * scale)), cv2.LINE_AA)
        text_width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.46 * scale, max(1, round(1.2 * scale)))[0][0]
        return image, HudSearchArea(0, 0, image.shape[1], image.shape[0], 0, 1920, 1080), text_x + text_width

    def attach_synthetic_grab(self, controller, image):
        controller.sct = Mock()

        def grab(monitor):
            left = int(monitor["left"])
            top = int(monitor["top"])
            width = int(monitor["width"])
            height = int(monitor["height"])
            return image[top : top + height, left : left + width].copy()

        controller.sct.grab.side_effect = grab

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
        self.assertEqual(submitted_fn, read_experience_burst_frames_in_worker)
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
        self.assertEqual(submitted_fn, read_experience_burst_frames_in_worker)
        self.assertEqual(len(submitted_args[0]), EXPERIENCE_BURST_CAPTURE_ATTEMPTS)
        self.assertTrue(all(len(frame) == 2 for frame in submitted_args[0]))
        first_frame = submitted_args[0][0]
        self.assertTrue(all(isinstance(image, ExperienceOcrImage) for image in first_frame))
        self.assertAlmostEqual(first_frame[0].bar_crop_left_ratio, 0.44)
        self.assertAlmostEqual(first_frame[1].bar_crop_left_ratio, 0.34)
        self.assertEqual(controller.sct.grab.call_count, EXPERIENCE_BURST_CAPTURE_ATTEMPTS * 2)

    def test_experience_tooltip_capture_uses_exp_track_tail_and_restores_mouse_lock(self):
        class FakeMouseLock:
            def __enter__(self):
                events.append("lock")
                return (400, 500)

            def __exit__(self, exc_type, exc, tb):
                events.append("unlock")
                return False

        events = []
        controller = self.make_controller([])
        controller.bottom_hud_layout = SimpleNamespace(exp_track_region=(100, 200, 300, 20))
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 800, 600))
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((90, 370, 4), dtype=np.uint8)

        with (
            patch("maple_star.controllers.auto_potion_controller.temporary_mouse_input_lock", return_value=FakeMouseLock()),
            patch("maple_star.controllers.auto_potion_controller.set_cursor_position") as set_cursor,
            patch("maple_star.controllers.auto_potion_controller.sleep_while_pumping_messages") as sleep,
            patch("maple_star.controllers.auto_potion_controller.get_cursor_position", return_value=(398, 210)),
        ):
            image = controller._capture_experience_tooltip_image()

        self.assertIsNotNone(image)
        assert image is not None
        self.assertEqual(image.source_id, "tooltip")
        self.assertEqual(image.roi_offset, (406, 132, 370, 90))
        set_cursor.assert_called_once_with(398, 210)
        sleep.assert_called_once()
        self.assertEqual(events, ["lock", "unlock"])
        controller.sct.grab.assert_called_once_with({"left": 406, "top": 132, "width": 370, "height": 90})

    def test_experience_tooltip_capture_retries_when_cursor_moves_during_lock(self):
        class FakeMouseLock:
            def __enter__(self):
                return (400, 500)

            def __exit__(self, exc_type, exc, tb):
                return False

        controller = self.make_controller([])
        controller.bottom_hud_layout = SimpleNamespace(exp_track_region=(100, 200, 300, 20))
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 800, 600))
        controller.sct = Mock()
        controller.sct.grab.return_value = np.zeros((46, 340, 4), dtype=np.uint8)

        with (
            patch("maple_star.controllers.auto_potion_controller.temporary_mouse_input_lock", return_value=FakeMouseLock()),
            patch("maple_star.controllers.auto_potion_controller.set_cursor_position") as set_cursor,
            patch("maple_star.controllers.auto_potion_controller.sleep_while_pumping_messages") as sleep,
            patch(
                "maple_star.controllers.auto_potion_controller.get_cursor_position",
                side_effect=[(430, 210), (398, 210), (398, 210)],
            ),
        ):
            image = controller._capture_experience_tooltip_image()

        self.assertIsNotNone(image)
        self.assertEqual(set_cursor.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        controller.sct.grab.assert_called_once()
        debug = controller.last_experience_tooltip_capture_debug
        self.assertEqual(debug["attempts"][0]["decision"], "cursor_moved_before_grab")
        self.assertEqual(debug["attempts"][1]["decision"], "captured")

    def test_experience_tooltip_capture_skips_when_cursor_keeps_moving(self):
        class FakeMouseLock:
            def __enter__(self):
                return (400, 500)

            def __exit__(self, exc_type, exc, tb):
                return False

        controller = self.make_controller([])
        controller.bottom_hud_layout = SimpleNamespace(exp_track_region=(100, 200, 300, 20))
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 800, 600))
        controller.sct = Mock()

        with (
            patch("maple_star.controllers.auto_potion_controller.temporary_mouse_input_lock", return_value=FakeMouseLock()),
            patch("maple_star.controllers.auto_potion_controller.set_cursor_position"),
            patch("maple_star.controllers.auto_potion_controller.sleep_while_pumping_messages"),
            patch("maple_star.controllers.auto_potion_controller.get_cursor_position", return_value=(430, 210)),
        ):
            image = controller._capture_experience_tooltip_image()

        self.assertIsNone(image)
        self.assertEqual(controller.last_experience_tooltip_capture_skip["reason"], "浮動 EXP 擷取期間滑鼠偏移")
        self.assertEqual(len(controller.last_experience_tooltip_capture_skip["capture_debug"]["attempts"]), 3)
        controller.sct.grab.assert_not_called()

    def test_experience_update_submits_tooltip_ocr_before_bottom_burst(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        controller.next_experience_capture_at = 0.0
        controller.gameplay_hud_active = True
        controller.experience_tracker.add_reading(1.0, 1_000_000, 10.0, confidence=0.95)
        controller.experience_ocr_executor = ImmediateExecutor()
        tooltip_image = ExperienceOcrImage(np.zeros((46, 340, 4), dtype=np.uint8), source_id="tooltip")
        controller._capture_experience_tooltip_image = Mock(return_value=tooltip_image)
        controller._start_bottom_experience_ocr_capture = Mock()

        controller._update_experience_efficiency(5.0)

        submitted_fn, submitted_args, _submitted_kwargs = controller.experience_ocr_executor.call
        self.assertEqual(submitted_fn, read_experience_tooltip_in_worker)
        self.assertIs(submitted_args[0], tooltip_image)
        self.assertEqual(controller.experience_ocr_job.source, "tooltip")
        controller._start_bottom_experience_ocr_capture.assert_not_called()

    def test_experience_update_defers_capture_during_mouse_activity(self):
        controller = self.make_controller([])
        controller.next_experience_capture_at = 0.0
        controller.gameplay_hud_active = True
        controller.experience_tracker.add_reading(1.0, 1_000_000, 10.0, confidence=0.95)
        controller.mouse_activity_observer = SimpleNamespace(last_activity_at=8.0)
        controller._start_experience_tooltip_ocr_capture = Mock(return_value=True)
        controller._start_bottom_experience_ocr_capture = Mock(return_value=True)

        with patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log:
            controller._update_experience_efficiency(10.0)

        controller._start_experience_tooltip_ocr_capture.assert_not_called()
        controller._start_bottom_experience_ocr_capture.assert_not_called()
        self.assertAlmostEqual(controller.next_experience_capture_at, 8.0 + EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS)
        controller.gui.set_experience_snapshot.assert_called()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertIn("滑鼠操作中", snapshot.status)
        payload = exp_debug_log.call_args.args[0]
        self.assertEqual(payload["event"], "experience_mouse_idle_delay")
        self.assertEqual(payload["phase"], "ocr_capture")
        self.assertEqual(payload["decision"], "deferred")

    def test_mouse_activity_defer_status_is_throttled(self):
        controller = self.make_controller([])
        controller.next_experience_capture_at = 0.0
        controller.gameplay_hud_active = True
        controller.experience_tracker.add_reading(1.0, 1_000_000, 10.0, confidence=0.95)
        controller.mouse_activity_observer = SimpleNamespace(last_activity_at=10.0)
        controller._start_experience_tooltip_ocr_capture = Mock(return_value=True)
        controller._start_bottom_experience_ocr_capture = Mock(return_value=True)

        with patch("maple_star.controllers.auto_potion_controller.log_experience_debug"):
            controller._update_experience_efficiency(10.0)
            controller.mouse_activity_observer.last_activity_at = 10.2
            controller._update_experience_efficiency(10.2)
            controller.mouse_activity_observer.last_activity_at = 11.0
            controller._update_experience_efficiency(11.0)
            controller.mouse_activity_observer.last_activity_at = 10.0 + EXPERIENCE_MOUSE_IDLE_STATUS_UPDATE_SECONDS
            controller._update_experience_efficiency(10.0 + EXPERIENCE_MOUSE_IDLE_STATUS_UPDATE_SECONDS)

        self.assertEqual(controller.gui.set_experience_snapshot.call_count, 2)
        controller._start_experience_tooltip_ocr_capture.assert_not_called()
        controller._start_bottom_experience_ocr_capture.assert_not_called()
        self.assertAlmostEqual(
            controller.next_experience_capture_at,
            10.0 + EXPERIENCE_MOUSE_IDLE_STATUS_UPDATE_SECONDS + EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS,
        )

    def test_tooltip_mouse_drift_skip_does_not_fall_back_to_bottom_capture(self):
        controller = self.make_controller([])
        controller.next_experience_capture_at = 0.0
        controller.gameplay_hud_active = True
        controller.experience_tracker.add_reading(1.0, 1_000_000, 10.0, confidence=0.95)
        controller._capture_experience_tooltip_image = Mock(return_value=None)
        controller.last_experience_tooltip_capture_skip = {"reason": "浮動 EXP 擷取期間滑鼠偏移"}
        controller._start_bottom_experience_ocr_capture = Mock(return_value=True)

        controller._update_experience_efficiency(10.0)

        controller._start_bottom_experience_ocr_capture.assert_not_called()
        self.assertAlmostEqual(controller.next_experience_capture_at, 10.0 + EXPERIENCE_MOUSE_IDLE_DELAY_SECONDS)

    def test_experience_update_resumes_capture_after_mouse_idle_delay(self):
        controller = self.make_controller([])
        controller.next_experience_capture_at = 0.0
        controller.gameplay_hud_active = True
        controller.experience_tracker.add_reading(1.0, 1_000_000, 10.0, confidence=0.95)
        controller.mouse_activity_observer = SimpleNamespace(last_activity_at=8.0)
        controller._start_experience_tooltip_ocr_capture = Mock(return_value=True)
        controller._start_bottom_experience_ocr_capture = Mock(return_value=True)

        controller._update_experience_efficiency(13.1)

        controller._start_experience_tooltip_ocr_capture.assert_called_once_with(13.1, effective_now=13.1)
        controller._start_bottom_experience_ocr_capture.assert_not_called()

    def test_mouse_activity_defers_baseline_without_opening_stat_window(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.mouse_activity_observer = SimpleNamespace(last_activity_at=8.0)
        controller._capture_experience_tooltip_image = Mock()
        controller._toggle_experience_stat_window = Mock()

        handled = controller._process_experience_baseline_calibration(10.0, effective_now=10.0)

        self.assertTrue(handled)
        controller._capture_experience_tooltip_image.assert_not_called()
        controller._toggle_experience_stat_window.assert_not_called()

    def test_mouse_activity_defers_exp_10m_checkpoint_without_opening_stat_window(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.experience_tracker.record_exp_10m_checkpoint(1_000_000)
        controller.next_experience_10m_checkpoint_at = 10.0
        controller.mouse_activity_observer = SimpleNamespace(last_activity_at=8.0)
        controller._capture_experience_tooltip_image = Mock()
        controller._toggle_experience_stat_window = Mock()

        handled = controller._process_exp_10m_checkpoint(10.0, effective_now=10.0)

        self.assertTrue(handled)
        controller._capture_experience_tooltip_image.assert_not_called()
        controller._toggle_experience_stat_window.assert_not_called()

    def test_experience_tooltip_capture_skip_writes_experience_debug_reason(self):
        controller = self.make_controller([])
        controller.bottom_hud_layout = None
        controller.bottom_bar_track_regions = {}
        controller.experience_tracker = ExperienceEfficiencyTracker()

        with patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log:
            started = controller._start_experience_tooltip_ocr_capture(12.0, effective_now=11.5)

        self.assertFalse(started)
        exp_debug_log.assert_called_once()
        payload = exp_debug_log.call_args.args[0]
        self.assertEqual(payload["event"], "experience_tooltip_capture")
        self.assertEqual(payload["phase"], "ocr_capture")
        self.assertEqual(payload["source"], "tooltip")
        self.assertEqual(payload["decision"], "skipped")
        self.assertEqual(payload["reason"], "找不到 EXP track 游標目標")
        self.assertFalse(payload["has_bottom_hud_layout"])
        self.assertEqual(payload["bottom_bar_track_keys"], [])
        self.assertIsNone(payload["cursor_point"])
        self.assertIsNone(payload["roi"])

    def test_tooltip_ocr_failure_retries_before_bottom_fallback(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(reason="浮動 EXP 解析失敗", source="tooltip")

            def cancel(self):
                return False

        controller = self.make_controller([])
        controller.experience_ocr_job = ExperienceOcrJob(
            submitted_at=10.0,
            future=DoneFuture(),
            source="tooltip",
        )
        controller._start_bottom_experience_ocr_capture = Mock(return_value=True)

        self.assertTrue(controller._process_experience_ocr_job(10.5, effective_now=10.5))

        controller._start_bottom_experience_ocr_capture.assert_not_called()
        self.assertEqual(controller.experience_tooltip_ocr_failures, 1)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertIn(f"1/{EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES}", snapshot.status)
        self.assertIsNone(controller.experience_ocr_job)

    def test_tooltip_ocr_failure_falls_back_to_bottom_after_three_failures(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(reason="浮動 EXP 解析失敗", source="tooltip")

            def cancel(self):
                return False

        controller = self.make_controller([])
        controller.experience_tooltip_ocr_failures = EXPERIENCE_TOOLTIP_OCR_FALLBACK_FAILURES - 1
        controller.experience_ocr_job = ExperienceOcrJob(
            submitted_at=10.0,
            future=DoneFuture(),
            source="tooltip",
        )
        controller._start_bottom_experience_ocr_capture = Mock(return_value=True)

        self.assertTrue(controller._process_experience_ocr_job(10.5, effective_now=10.5))

        controller._start_bottom_experience_ocr_capture.assert_called_once_with(10.5, effective_now=10.5)
        self.assertEqual(controller.experience_tooltip_ocr_failures, 0)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "浮動 EXP OCR 連續失敗，改用底部 EXP OCR")
        self.assertIsNone(controller.experience_ocr_job)

    def test_experience_stat_window_roi_locator_uses_seventh_green_label(self):
        controller = self.make_controller([])
        image = np.zeros((800, 1000, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        for index in range(8):
            y = 140 + index * 32
            image[y : y + 24, 250:320, :3] = (45, 210, 130)
            image[y : y + 24, 324:520, :3] = (235, 235, 235)

        roi = controller._locate_stat_window_exp_roi(image)

        self.assertIsNotNone(roi)
        assert roi is not None
        left, top, width, height = roi
        self.assertGreaterEqual(left, 320)
        self.assertLessEqual(top, 140 + 6 * 32)
        self.assertGreaterEqual(top + height, 140 + 6 * 32 + 20)
        self.assertGreater(width, 120)

    def test_experience_stat_window_roi_locator_handles_shifted_window(self):
        controller = self.make_controller([])
        image = np.zeros((800, 1000, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        for index in range(8):
            y = 120 + index * 32
            image[y : y + 24, 650:720, :3] = (45, 210, 130)
            image[y : y + 24, 724:940, :3] = (235, 235, 235)

        roi = controller._locate_stat_window_exp_roi(image)

        self.assertIsNotNone(roi)
        assert roi is not None
        left, top, width, height = roi
        self.assertGreaterEqual(left, 720)
        self.assertLessEqual(top, 120 + 6 * 32)
        self.assertGreaterEqual(top + height, 120 + 6 * 32 + 20)
        self.assertGreater(width, 120)

    def test_experience_stat_window_roi_locator_prefers_exp_label_template(self):
        controller = self.make_controller([])
        image = np.zeros((800, 1000, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        labels = [("HP", 180), ("MP", 215), ("EXP", 250), ("STR", 285)]
        for text, y in labels:
            image[y : y + 28, 640:710, :3] = (45, 210, 130)
            image[y : y + 28, 714:930, :3] = (235, 235, 235)
            cv2.putText(image, text, (646, y + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (245, 245, 245, 255), 2)

        roi = controller._locate_stat_window_exp_roi(image)

        self.assertIsNotNone(roi)
        assert roi is not None
        left, top, width, height = roi
        self.assertGreaterEqual(left, 710)
        self.assertLessEqual(top, 250)
        self.assertGreaterEqual(top + height, 274)
        self.assertGreater(width, 120)

    def test_experience_stat_window_roi_locator_uses_fixed_exp_label_template(self):
        controller = self.make_controller([])
        template = controller._stat_window_fixed_exp_label_template()
        self.assertIsNotNone(template)
        assert template is not None
        image = np.zeros((800, 1000, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        label_top = 460
        label_left = 620
        label_height, label_width = template.shape[:2]
        image[label_top : label_top + label_height, label_left : label_left + label_width, :3] = template
        image[label_top : label_top + label_height, label_left + label_width + 8 : 930, :3] = (235, 235, 235)

        roi = controller._locate_stat_window_exp_roi(image)

        self.assertIsNotNone(roi)
        assert roi is not None
        left, top, width, height = roi
        self.assertGreaterEqual(left, label_left + label_width)
        self.assertLessEqual(top, label_top)
        self.assertGreaterEqual(top + height, label_top + label_height)
        self.assertGreater(width, 120)

    def test_foreground_client_bounds_falls_back_to_target_window_when_foreground_is_temporarily_missing(self):
        controller = self.make_controller([])
        controller.target_window_provider = Mock(return_value=1234)

        def fake_get_client_rect(hwnd, rect_pointer):
            rect = rect_pointer._obj
            rect.left = 0
            rect.top = 0
            rect.right = 1920
            rect.bottom = 1080
            return True

        def fake_client_to_screen(hwnd, point_pointer):
            point = point_pointer._obj
            point.x = 11
            point.y = 22
            return True

        with (
            patch("maple_star.controllers.auto_potion_controller.user32.GetForegroundWindow", return_value=0),
            patch("maple_star.controllers.auto_potion_controller.user32.GetClientRect", side_effect=fake_get_client_rect),
            patch("maple_star.controllers.auto_potion_controller.user32.ClientToScreen", side_effect=fake_client_to_screen),
        ):
            bounds = controller._foreground_client_bounds()

        self.assertEqual(bounds, (11, 22, 1920, 1080))
        self.assertEqual(controller.last_target_hwnd, 1234)
        controller.target_window_provider.assert_called_once()

    def test_experience_baseline_uses_tooltip_percent_from_current_total(self):
        class DoneFuture:
            def __init__(self, result):
                self._result = result

            def done(self):
                return True

            def result(self):
                return self._result

            def cancel(self):
                return False

        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                return DoneFuture(
                    ExperienceTextReading(
                        current_exp=15_261_854,
                        percent=17.84,
                        text="EXP: 15261854 / 85538273",
                        confidence=0.96,
                        success=True,
                        reason="OK:Tooltip",
                        source="tooltip",
                    )
                )

        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._capture_experience_tooltip_image = Mock(
            return_value=ExperienceOcrImage(np.zeros((46, 340, 4), dtype=np.uint8), source_id="tooltip")
        )
        controller._toggle_experience_stat_window = Mock()

        self.assertTrue(controller._process_experience_baseline_calibration(10.0, effective_now=10.0))
        self.assertTrue(controller._process_experience_baseline_calibration(10.1, effective_now=10.1))

        controller._toggle_experience_stat_window.assert_not_called()
        self.assertEqual(controller.experience_tracker.samples[-1].current_exp, 15_261_854)
        self.assertEqual(controller.experience_tracker.samples[-1].percent, 17.84)
        self.assertFalse(controller.experience_tooltip_baseline_failed)

    def test_tooltip_baseline_failure_does_not_open_stat_window_when_disabled(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(reason="浮動 EXP 解析失敗", source="tooltip")

            def cancel(self):
                return False

        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                return DoneFuture()

        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._capture_experience_tooltip_image = Mock(
            return_value=ExperienceOcrImage(np.zeros((46, 340, 4), dtype=np.uint8), source_id="tooltip")
        )
        controller._toggle_experience_stat_window = Mock()

        self.assertTrue(controller._process_experience_baseline_calibration(10.0, effective_now=10.0))
        self.assertTrue(controller._process_experience_baseline_calibration(10.1, effective_now=10.1))

        controller._toggle_experience_stat_window.assert_not_called()
        self.assertFalse(controller.experience_tooltip_baseline_failed)

    def test_exp_10m_checkpoint_uses_tooltip_before_character_stat_window(self):
        class DoneFuture:
            def __init__(self, result):
                self._result = result

            def done(self):
                return True

            def result(self):
                return self._result

            def cancel(self):
                return False

        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                return DoneFuture(
                    ExperienceTextReading(
                        current_exp=1_123_456,
                        percent=12.34,
                        text="EXP: 1123456 / 9104182",
                        confidence=0.95,
                        success=True,
                        reason="OK:Tooltip",
                        source="tooltip",
                    )
                )

        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.experience_tracker.record_exp_10m_checkpoint(1_000_000)
        controller.next_experience_10m_checkpoint_at = 610.0
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._capture_experience_tooltip_image = Mock(
            return_value=ExperienceOcrImage(np.zeros((46, 340, 4), dtype=np.uint8), source_id="tooltip")
        )
        controller._toggle_experience_stat_window = Mock()

        self.assertTrue(controller._process_exp_10m_checkpoint(610.0, effective_now=600.0))
        self.assertTrue(controller._process_exp_10m_checkpoint(610.1, effective_now=600.1))

        controller._toggle_experience_stat_window.assert_not_called()
        self.assertEqual(controller.experience_tracker.exp_10m_checkpoint_exp, 1_123_456)
        self.assertEqual(controller.experience_tracker.exp_10m_gain, 123_456)
        self.assertFalse(controller.experience_10m_checkpoint_tooltip_failed)

    def test_exp_10m_tooltip_failure_retries_without_stat_window_when_disabled(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(reason="浮動 EXP 解析失敗", source="tooltip")

            def cancel(self):
                return False

        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                return DoneFuture()

        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.experience_tracker.record_exp_10m_checkpoint(1_000_000)
        controller.next_experience_10m_checkpoint_at = 610.0
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._capture_experience_tooltip_image = Mock(
            return_value=ExperienceOcrImage(np.zeros((46, 340, 4), dtype=np.uint8), source_id="tooltip")
        )
        controller._toggle_experience_stat_window = Mock()

        self.assertTrue(controller._process_exp_10m_checkpoint(610.0, effective_now=600.0))
        self.assertTrue(controller._process_exp_10m_checkpoint(610.1, effective_now=600.1))

        controller._toggle_experience_stat_window.assert_not_called()
        self.assertFalse(controller.experience_10m_checkpoint_tooltip_failed)
        self.assertAlmostEqual(
            controller.next_experience_10m_checkpoint_at,
            610.1 + EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS,
        )

    def test_exp_10m_checkpoint_ocr_failure_retries_without_stopping(self):
        class DoneFuture:
            def __init__(self, result):
                self._result = result

            def done(self):
                return True

            def result(self):
                return self._result

            def cancel(self):
                return False

        controller = self.make_controller([])
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.experience_tracker.record_exp_10m_checkpoint(900_000)
        controller.experience_tracker.record_exp_10m_checkpoint(1_000_000)
        failure = ExperienceTextReading(text="--", confidence=0.0, success=False, reason="OCR 失敗")

        controller.experience_10m_checkpoint_attempts = EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS
        controller.experience_10m_checkpoint_ocr_job = ExperienceOcrJob(
            20.0,
            DoneFuture(failure),
            source="tooltip_checkpoint",
        )

        with patch("builtins.print"):
            self.assertTrue(controller._process_exp_10m_checkpoint_ocr_job(20.5, effective_now=20.5))

        self.assertFalse(controller.experience_10m_checkpoint_stopped)
        self.assertAlmostEqual(
            controller.next_experience_10m_checkpoint_at,
            20.5 + EXPERIENCE_10M_CHECKPOINT_OCR_RETRY_DELAY_SECONDS,
        )
        self.assertEqual(controller.experience_10m_checkpoint_attempts, EXPERIENCE_10M_CHECKPOINT_OCR_MAX_ATTEMPTS)
        self.assertEqual(controller.experience_tracker.exp_10m_gain, 100_000)
        controller._play_toggle_beep.assert_not_called()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "浮動 EXP-10 失敗，稍後重試")

    def test_clear_experience_baseline_state_restores_cursor(self):
        controller = self.make_controller([])
        controller.experience_baseline_cursor_position = (400, 500)

        with patch("maple_star.controllers.auto_potion_controller.set_cursor_position") as set_cursor:
            controller._clear_experience_baseline_calibration_state()

        set_cursor.assert_called_once_with(400, 500)
        self.assertIsNone(controller.experience_baseline_cursor_position)

    def test_experience_baseline_calibration_does_not_run_after_baseline_exists(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.gameplay_hud_active = True
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.experience_tracker.add_reading(1.0, 1000, 10.0)
        controller._capture_foreground_client_image = Mock()

        self.assertFalse(controller._process_experience_baseline_calibration(30.0, effective_now=30.0))
        controller._capture_foreground_client_image.assert_not_called()

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
        self.assertEqual(submitted_fn, read_experience_burst_frames_in_worker)
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
        changed = image.copy()
        changed[4:10, 20:50, :3] = 255
        controller._experience_text_region = Mock(return_value=(10, 20, 140, 18))
        controller.sct = Mock()
        controller.sct.grab.return_value = changed

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
        self.assertEqual(submitted_fn, read_experience_burst_frames_in_worker)
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
        self.assertEqual(submitted_fn, read_experience_burst_frames_in_worker)
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
        self.assertEqual(submitted_fn, read_experience_burst_frames_in_worker)
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
        worker.refresh_hold("mp", 0x23)
        worker.release("mp", 0x23)

        self.assertEqual(
            worker.drain_actions(),
            [
                PotionAction("tap", "hp", key_name="Delete"),
                PotionAction("release", "mp", vk_code=0x23),
            ],
        )

    def test_potion_action_worker_release_all_clears_pending_actions(self):
        worker = PotionActionWorker()

        worker.tap("hp", "Delete")
        worker.hold("mp", 0x23)
        worker.release_all()

        self.assertEqual(worker.drain_actions(), [PotionAction("release_all", "all")])

    def test_potion_action_worker_keeps_pending_actions_bounded(self):
        worker = PotionActionWorker(max_pending_actions=3)

        worker.tap("hp", "A")
        worker.tap("mp", "B")
        worker.tap("hp", "C")
        worker.tap("mp", "D")

        self.assertEqual(
            worker.drain_actions(),
            [
                PotionAction("tap", "mp", key_name="B"),
                PotionAction("tap", "hp", key_name="C"),
                PotionAction("tap", "mp", key_name="D"),
            ],
        )

    def test_potion_action_worker_coalesces_control_actions_per_bar(self):
        worker = PotionActionWorker()

        worker.hold("hp", 0x2E)
        worker.refresh_hold("hp", 0x2E)
        worker.hold("mp", 0x23)
        worker.release("hp", 0x2E)

        self.assertEqual(
            worker.drain_actions(),
            [
                PotionAction("hold", "mp", vk_code=0x23),
                PotionAction("release", "hp", vk_code=0x2E),
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
            _apply_potion_action(PotionAction("refresh_hold", "hp", vk_code=0x2E), held)
            _apply_potion_action(PotionAction("release", "hp", vk_code=0x2E), held)

        tap_hotkey.assert_called_once_with("Delete")
        self.assertEqual(key_down.call_args_list, [call(0x2E), call(0x2E)])
        key_up.assert_called_once_with(0x2E)
        self.assertEqual(held, {})

    def test_potion_action_release_failure_keeps_held_state_for_retry(self):
        held = {"hp": 0x2E}

        with patch("maple_star.services.potion_action_worker.key_up", side_effect=[OSError("send failed"), None]):
            with self.assertRaises(OSError):
                _apply_potion_action(PotionAction("release", "hp", vk_code=0x2E), held)
            self.assertEqual(held, {"hp": 0x2E})

            _apply_potion_action(PotionAction("release", "hp", vk_code=0x2E), held)

        self.assertEqual(held, {})

    def test_potion_action_worker_survives_action_exception(self):
        worker = PotionActionWorker()

        with (
            patch(
                "maple_star.services.potion_action_worker.tap_hotkey",
                side_effect=[ValueError("bad key"), None],
            ) as tap_hotkey,
            patch("maple_star.services.potion_action_worker.log_exception") as log_exception,
        ):
            worker.start()
            try:
                worker.tap("hp", "BadKey")
                worker.tap("mp", "End")
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline and tap_hotkey.call_count < 2:
                    time.sleep(0.01)
            finally:
                worker.stop()

        self.assertEqual(tap_hotkey.call_count, 2)
        log_exception.assert_called_once()

    def test_runtime_process_update_does_not_run_local_potion_or_experience_capture(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.target_window_provider = Mock(return_value=4321)
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.gui.sync_after_event_processing.return_value = True
        controller._capture_bar_percent = Mock()
        controller._update_experience_efficiency = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()

        controller.update(100.0)

        controller._capture_bar_percent.assert_not_called()
        controller._update_experience_efficiency.assert_not_called()
        controller._sync_pickup_key_state.assert_called_once()
        self.assertEqual(runtime.targets_sent, [4321])
        self.assertEqual(runtime.settings_sent, [controller.settings.snapshot()])
        self.assertEqual(runtime.potion_controls[-1], PotionControl(enabled=True, scripts_enabled=True, generation=1))

    def test_experience_only_runtime_skips_potion_capture_until_exp_work_needs_hud(self):
        controller = self.make_controller([True])
        controller.experience_only_runtime = True
        controller.settings.exp_efficiency_enabled = True
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.gui.sync_after_event_processing.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._save_settings_when_idle = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._experience_runtime_needs_hud_refresh = Mock(return_value=False)
        controller._experience_runtime_has_cached_hud = Mock(return_value=True)
        controller._update_experience_efficiency = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._process_due_potion_sends = Mock()

        controller.update(100.0)

        controller._capture_bar_percent.assert_not_called()
        controller._sync_pickup_key_state.assert_not_called()
        controller._process_due_potion_sends.assert_not_called()
        controller._update_experience_efficiency.assert_called_once_with(100.0)

    def test_runtime_target_active_accepts_foreground_msw_window_with_different_hwnd(self):
        with (
            patch("maple_star.services.runtime_processes.foreground_window_handle", return_value=2222),
            patch("maple_star.services.runtime_processes.window_ancestor_handles", return_value=(2222,)),
            patch("maple_star.services.runtime_processes.is_valid_window", return_value=True),
            patch("maple_star.services.runtime_processes.is_window_minimized", return_value=False),
            patch("maple_star.services.runtime_processes.is_target_window", return_value=True),
        ):
            self.assertTrue(_is_target_hwnd_active(1111))

    def test_runtime_target_active_accepts_foreground_child_of_target_hwnd(self):
        with (
            patch("maple_star.services.runtime_processes.foreground_window_handle", return_value=2222),
            patch("maple_star.services.runtime_processes.window_ancestor_handles", return_value=(2222, 1111)),
            patch("maple_star.services.runtime_processes.is_valid_window", return_value=True),
            patch("maple_star.services.runtime_processes.is_window_minimized", return_value=False),
            patch("maple_star.services.runtime_processes.is_target_window", return_value=False),
        ):
            self.assertTrue(_is_target_hwnd_active(1111))

    def test_runtime_target_active_rejects_non_target_foreground_window(self):
        with (
            patch("maple_star.services.runtime_processes.foreground_window_handle", return_value=2222),
            patch("maple_star.services.runtime_processes.window_ancestor_handles", return_value=(2222,)),
            patch("maple_star.services.runtime_processes.is_valid_window", return_value=True),
            patch("maple_star.services.runtime_processes.is_window_minimized", return_value=False),
            patch("maple_star.services.runtime_processes.is_target_window", return_value=False),
        ):
            self.assertFalse(_is_target_hwnd_active(1111))

    def test_runtime_statuses_update_gui_from_worker_queues(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.settings.exp_efficiency_enabled = True
        snapshot = ExperienceSnapshot(status="統計中", current_exp=12345)
        runtime.potion_statuses.append(
            PotionStatus(
                hp_percent=25.0,
                mp_percent=80.0,
                hp_debug="hp ok",
                mp_debug="mp ok",
                status="自動喝水監控中",
                action="HP 喝水：Delete",
                notice="",
                trigger_interval_ms=None,
                console_lines=(),
                gameplay_hud_active=True,
                scripts_enabled=True,
                auto_drink_enabled=True,
                hp_region=(10, 20, 30, 12),
                mp_region=(40, 50, 30, 12),
                hp_track_region=(11, 21, 28, 10),
                mp_track_region=(41, 51, 28, 10),
            )
        )
        runtime.experience_statuses.append(ExperienceStatus(snapshot=snapshot, status="統計中"))
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime

        with patch("builtins.print") as print_mock:
            controller._drain_runtime_statuses()

        controller.gui.set_current_percentages.assert_called_once_with(25.0, 80.0)
        controller.gui.set_bar_detection_debug.assert_called_once_with("hp ok", "mp ok")
        controller.gui.set_experience_snapshot.assert_called_once_with(snapshot)
        self.assertTrue(controller.gameplay_hud_active)
        self.assertEqual(controller.last_action, "HP 喝水：Delete")
        self.assertEqual(controller.last_bar_debug["hp"].region, (10, 20, 30, 12))
        self.assertEqual(controller.last_bar_debug["mp"].region, (40, 50, 30, 12))
        self.assertEqual(controller.last_bar_debug["hp"].track_region, (11, 21, 28, 10))
        self.assertEqual(controller.last_bar_debug["mp"].track_region, (41, 51, 28, 10))
        controller.gui.refresh_bar_preview_once.assert_called_once()
        print_mock.assert_not_called()

    def test_runtime_potion_status_replays_worker_media_sounds(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        runtime.potion_statuses.append(
            PotionStatus(
                hp_percent=25.0,
                mp_percent=80.0,
                hp_debug="hp ok",
                mp_debug="mp ok",
                status="HP 檢查藥水",
                action="HP 檢查藥水",
                notice="HP 檢查藥水",
                trigger_interval_ms=None,
                console_lines=(),
                gameplay_hud_active=True,
                scripts_enabled=True,
                auto_drink_enabled=True,
                media_sound_aliases=("auto_drink_potion_check",),
            )
        )
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime

        with patch.object(controller, "_play_media_file") as play_media:
            controller._drain_runtime_statuses()

        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

    def test_runtime_potion_status_signature_ignores_transient_notice_and_console(self):
        base = PotionStatus(
            hp_percent=25.0,
            mp_percent=80.0,
            hp_debug="hp ok",
            mp_debug="mp ok",
            status="自動喝水監控中",
            action="",
            notice="HP 檢查藥水",
            trigger_interval_ms=None,
            console_lines=("line",),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
        )
        same_core = PotionStatus(
            hp_percent=25.0,
            mp_percent=80.0,
            hp_debug="hp ok",
            mp_debug="mp ok",
            status="自動喝水監控中",
            action="",
            notice="",
            trigger_interval_ms=None,
            console_lines=(),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
        )

        self.assertEqual(_potion_status_signature(base), _potion_status_signature(same_core))

    def test_runtime_potion_status_signature_ignores_debug_percent_and_region_churn(self):
        base = PotionStatus(
            hp_percent=25.0,
            mp_percent=80.0,
            hp_debug="HP: 自動定位 | 25.00% | full=10,20,30,12 | track=11,21,28,10 | OK:F",
            mp_debug="MP: 自動定位 | 80.00% | full=40,50,30,12 | track=41,51,28,10 | OK:F",
            status="自動喝水監控中",
            action="",
            notice="",
            trigger_interval_ms=None,
            console_lines=(),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
            hp_region=(10, 20, 30, 12),
            mp_region=(40, 50, 30, 12),
            hp_track_region=(11, 21, 28, 10),
            mp_track_region=(41, 51, 28, 10),
        )
        same_core = PotionStatus(
            hp_percent=25.0,
            mp_percent=80.0,
            hp_debug="HP: 自動定位 | 25.01% | full=10,20,30,12 | track=11,21,28,10 | OK:F",
            mp_debug="MP: 自動定位 | 79.99% | full=40,50,30,12 | track=41,51,28,10 | OK:F",
            status="自動喝水監控中",
            action="",
            notice="",
            trigger_interval_ms=None,
            console_lines=(),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
            hp_region=(10, 20, 30, 12),
            mp_region=(40, 50, 30, 12),
            hp_track_region=(11, 21, 28, 10),
            mp_track_region=(41, 51, 28, 10),
        )
        percent_changed = PotionStatus(
            hp_percent=26.0,
            mp_percent=80.0,
            hp_debug="HP: 自動定位 | 26.00% | full=10,20,30,12 | track=11,21,28,10 | OK:F",
            mp_debug="MP: 自動定位 | 80.00% | full=40,50,30,12 | track=41,51,28,10 | OK:F",
            status="自動喝水監控中",
            action="",
            notice="",
            trigger_interval_ms=None,
            console_lines=(),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
            hp_region=(10, 20, 30, 12),
            mp_region=(40, 50, 30, 12),
            hp_track_region=(11, 21, 28, 10),
            mp_track_region=(41, 51, 28, 10),
        )
        reason_changed = PotionStatus(
            hp_percent=25.0,
            mp_percent=80.0,
            hp_debug="HP: 自動定位 | 25.00% | full=10,20,30,12 | track=11,21,28,10 | ERR:色條驗證失敗",
            mp_debug="MP: 自動定位 | 80.00% | full=40,50,30,12 | track=41,51,28,10 | OK:F",
            status="自動喝水監控中",
            action="",
            notice="",
            trigger_interval_ms=None,
            console_lines=(),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
            hp_region=(10, 20, 30, 12),
            mp_region=(40, 50, 30, 12),
            hp_track_region=(11, 21, 28, 10),
            mp_track_region=(41, 51, 28, 10),
        )

        self.assertEqual(_potion_status_signature(base), _potion_status_signature(same_core))
        self.assertNotEqual(_potion_status_signature(base), _potion_status_signature(percent_changed))
        self.assertNotEqual(_potion_status_signature(base), _potion_status_signature(reason_changed))

    def test_runtime_experience_status_signature_tracks_snapshot_changes(self):
        first = ExperienceStatus(snapshot=ExperienceSnapshot(status="統計中", current_exp=100), status="統計中")
        second = ExperienceStatus(snapshot=ExperienceSnapshot(status="統計中", current_exp=200), status="統計中")

        self.assertNotEqual(_experience_status_signature(first), _experience_status_signature(second))

    def test_runtime_exp_10m_ocr_failure_status_plays_alert_once(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.settings.exp_efficiency_enabled = True
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        snapshot = ExperienceSnapshot(status="EXP-10 OCR 失敗，10 秒後重試（第 2/3 次）")
        runtime.experience_statuses.extend(
            [
                ExperienceStatus(snapshot=snapshot, status=snapshot.status),
                ExperienceStatus(snapshot=snapshot, status=snapshot.status),
            ]
        )

        controller._drain_runtime_statuses()
        controller._drain_runtime_statuses()

        controller.gui.set_experience_snapshot.assert_called_once_with(snapshot)
        controller._play_toggle_beep.assert_called_once()

    def test_runtime_statuses_use_latest_matching_generation(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.runtime_potion_generation = 2
        controller.runtime_experience_generation = 3
        controller.settings.exp_efficiency_enabled = True
        stale_snapshot = ExperienceSnapshot(status="舊統計", current_exp=111)
        latest_snapshot = ExperienceSnapshot(status="新統計", current_exp=222)

        runtime.potion_statuses.extend(
            [
                PotionStatus(
                    hp_percent=99.0,
                    mp_percent=99.0,
                    hp_debug="old hp",
                    mp_debug="old mp",
                    status="舊狀態",
                    action="",
                    notice="",
                    trigger_interval_ms=None,
                    console_lines=(),
                    gameplay_hud_active=True,
                    scripts_enabled=True,
                    auto_drink_enabled=True,
                    generation=1,
                ),
                PotionStatus(
                    hp_percent=25.0,
                    mp_percent=80.0,
                    hp_debug="new hp",
                    mp_debug="new mp",
                    status="新狀態",
                    action="",
                    notice="",
                    trigger_interval_ms=None,
                    console_lines=(),
                    gameplay_hud_active=True,
                    scripts_enabled=True,
                    auto_drink_enabled=True,
                    generation=2,
                ),
            ]
        )
        runtime.experience_statuses.extend(
            [
                ExperienceStatus(snapshot=stale_snapshot, status="舊統計", generation=2),
                ExperienceStatus(snapshot=latest_snapshot, status="新統計", generation=3),
            ]
        )

        controller._drain_runtime_statuses()

        controller.gui.set_current_percentages.assert_called_once_with(25.0, 80.0)
        controller.gui.set_bar_detection_debug.assert_called_once_with("new hp", "new mp")
        controller.gui.set_experience_snapshot.assert_called_once_with(latest_snapshot)

    def test_runtime_experience_status_is_ignored_after_feature_is_disabled(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.runtime_experience_generation = 5
        controller.settings.exp_efficiency_enabled = False
        snapshot = ExperienceSnapshot(status="舊統計", current_exp=999)
        runtime.experience_statuses.append(ExperienceStatus(snapshot=snapshot, status="舊統計", generation=5))

        controller._drain_runtime_statuses()

        controller.gui.set_experience_snapshot.assert_not_called()

    def test_runtime_toggle_experience_efficiency_does_not_clear_snapshot_when_disabling(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.settings.exp_efficiency_enabled = True

        with patch("builtins.print"):
            controller.toggle_experience_efficiency()

        controller.gui.set_exp_efficiency_enabled.assert_called_once_with(False)
        controller.gui.set_experience_snapshot.assert_not_called()
        self.assertFalse(runtime.experience_controls[-1].enabled)
        self.assertTrue(runtime.experience_controls[-1].pause)

    def test_runtime_potion_status_is_ignored_after_toggle_state_changed(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.runtime_potion_generation = 4
        controller.auto_drink_enabled = False
        runtime.potion_statuses.append(
            PotionStatus(
                hp_percent=25.0,
                mp_percent=80.0,
                hp_debug="hp ok",
                mp_debug="mp ok",
                status="舊喝水狀態",
                action="",
                notice="",
                trigger_interval_ms=None,
                console_lines=(),
                gameplay_hud_active=True,
                scripts_enabled=True,
                auto_drink_enabled=True,
                generation=4,
            )
        )

        controller._drain_runtime_statuses()

        controller.gui.set_current_percentages.assert_not_called()
        controller.gui.set_status.assert_not_called()

    def test_headless_runtime_experience_snapshot_does_not_overwrite_global_status(self):
        gui = HeadlessRuntimeGui(AutoPotionSettings())
        gui.set_status("自動喝水監控中")

        gui.set_experience_snapshot(ExperienceSnapshot(status="已停用"))

        self.assertEqual(gui.status, "自動喝水監控中")
        self.assertEqual(gui.experience_snapshot.status, "已停用")

    def test_headless_runtime_notice_is_consumed_once(self):
        gui = HeadlessRuntimeGui(AutoPotionSettings())
        controller = SimpleNamespace(
            last_action="",
            last_bar_debug={},
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
        )

        gui.show_toggle_notice("HP 檢查藥水")
        first_status = _potion_status(controller, gui)
        second_status = _potion_status(controller, gui)

        self.assertEqual(first_status.notice, "HP 檢查藥水")
        self.assertEqual(second_status.notice, "")

    def test_headless_runtime_potion_status_includes_bar_track_regions(self):
        gui = HeadlessRuntimeGui(AutoPotionSettings())
        controller = SimpleNamespace(
            last_action="",
            last_bar_debug={
                "hp": BarDetectionDebug("hp", region=(10, 20, 30, 12), track_region=(11, 21, 28, 10)),
                "mp": BarDetectionDebug("mp", region=(40, 50, 30, 12), track_region=(41, 51, 28, 10)),
            },
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
        )

        status = _potion_status(controller, gui)

        self.assertEqual(status.hp_region, (10, 20, 30, 12))
        self.assertEqual(status.mp_region, (40, 50, 30, 12))
        self.assertEqual(status.hp_track_region, (11, 21, 28, 10))
        self.assertEqual(status.mp_track_region, (41, 51, 28, 10))

    def test_headless_runtime_media_sounds_are_consumed_once(self):
        gui = HeadlessRuntimeGui(AutoPotionSettings())
        controller = SimpleNamespace(
            last_action="",
            last_bar_debug={},
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
        )

        gui.queue_media_sound("auto_drink_potion_check")
        first_status = _potion_status(controller, gui)
        second_status = _potion_status(controller, gui)

        self.assertEqual(first_status.media_sound_aliases, ("auto_drink_potion_check",))
        self.assertEqual(second_status.media_sound_aliases, ())

    def test_runtime_status_without_regions_does_not_refresh_bar_preview(self):
        controller = self.make_controller([True])
        status = PotionStatus(
            hp_percent=25.0,
            mp_percent=80.0,
            hp_debug="hp ok",
            mp_debug="mp ok",
            status="自動喝水監控中",
            action="",
            notice="",
            trigger_interval_ms=None,
            console_lines=(),
            gameplay_hud_active=True,
            scripts_enabled=True,
            auto_drink_enabled=True,
        )

        controller._apply_potion_status(status)

        controller.gui.refresh_bar_preview_once.assert_not_called()

    def test_runtime_emergency_stop_sends_release_to_potion_process(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller._pause_experience_for_inactive_state = Mock()

        with patch("builtins.print"):
            controller.emergency_stop()

        self.assertFalse(controller.scripts_enabled)
        self.assertFalse(controller.auto_drink_enabled)
        self.assertTrue(
            any(command.emergency_stop and command.release_all for command in runtime.potion_controls)
        )

    def test_runtime_worker_crash_disables_auto_drink(self):
        controller = self.make_controller([])

        controller._apply_worker_crash(WorkerCrashed("potion", "boom"))

        self.assertFalse(controller.auto_drink_enabled)
        self.assertFalse(controller.gameplay_hud_active)
        controller.gui.set_status.assert_called_with("喝水 process 已停止：boom")

    def test_stale_runtime_potion_status_restarts_potion_process(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.target_window_provider = Mock(return_value=2468)
        controller.runtime_control_state = (True, True, False)
        controller.runtime_potion_generation = 5
        controller.last_runtime_potion_status_at = 100.0

        controller._recover_stale_runtime_potion_process(100.0 + RUNTIME_POTION_STATUS_TIMEOUT_SECONDS)

        self.assertEqual(runtime.potion_restarts, [(controller.settings.snapshot(), 2468)])
        self.assertEqual(controller.runtime_control_state, (True, True, False))
        self.assertEqual(controller.runtime_potion_generation, 6)
        self.assertEqual(runtime.potion_controls[-1], PotionControl(enabled=True, scripts_enabled=True, generation=6))
        controller.gui.set_status.assert_any_call("喝水 process 無回報，已自動重啟")

    def test_runtime_potion_status_watchdog_waits_for_first_status(self):
        controller = self.make_controller([True])
        runtime = self.FakeRuntime()
        controller.runtime_processes_enabled = True
        controller.runtime_processes = runtime
        controller.last_runtime_potion_status_at = -999.0

        controller._recover_stale_runtime_potion_process(100.0)

        self.assertEqual(runtime.potion_restarts, [])
        self.assertEqual(controller.last_runtime_potion_status_at, 100.0)

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

    def test_gameplay_hud_gate_requires_fresh_hud_locator_before_sampling(self):
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
        controller.bottom_bar_client_bounds = (0, 0, 1000, 1000)
        controller.bottom_bar_regions_at = 0.0
        controller._find_bottom_bar_pair_regions = Mock(return_value=old_regions)
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 1000))
        controller._bar_percent_from_region_snapshot = Mock(return_value=(72.0, "OK", None))
        controller._set_bar_detection_debug = Mock()
        controller._can_keep_current_bottom_bar_geometry = Mock(return_value=False)

        self.assertTrue(controller._refresh_gameplay_hud_state(10.0))

        self.assertTrue(controller.gameplay_hud_active)
        self.assertEqual(controller.bottom_bar_regions, old_regions)
        self.assertEqual(controller.bottom_bar_track_regions, old_track_regions)
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        self.assertEqual(controller.last_mp_drink_at, -999.0)
        controller._find_bottom_bar_pair_regions.assert_called_once_with(
            use_cache=False,
            allow_stale_on_failure=False,
        )
        controller._bar_percent_from_region_snapshot.assert_not_called()
        controller._set_bar_detection_debug.assert_not_called()

    def test_gameplay_hud_gate_keeps_recent_geometry_when_locator_briefly_fails(self):
        controller = self.make_controller([])
        del controller._refresh_gameplay_hud_state
        old_regions = {
            "hp": (120, 220, 110, 12),
            "mp": (260, 220, 110, 12),
        }
        old_track_regions = {
            "hp": (125, 223, 100, 6),
            "mp": (265, 223, 100, 6),
        }
        controller.bottom_bar_regions = dict(old_regions)
        controller.bottom_bar_track_regions = dict(old_track_regions)
        controller.bottom_bar_client_bounds = (100, 200, 800, 600)
        controller.bottom_bar_regions_at = 9.5
        controller._reuse_cached_bottom_bar_regions_with_direct_sample = Mock(return_value=False)
        controller._can_reuse_stale_bottom_bar_regions = Mock(return_value=False)
        controller._find_bottom_bar_pair_regions = Mock(return_value={})
        controller._target_client_bounds = Mock(return_value=(100, 200, 800, 600))

        self.assertFalse(controller._refresh_gameplay_hud_state(10.0))

        self.assertFalse(controller.gameplay_hud_active)
        self.assertEqual(controller.bottom_bar_regions, old_regions)
        self.assertEqual(controller.bottom_bar_track_regions, old_track_regions)
        controller._reuse_cached_bottom_bar_regions_with_direct_sample.assert_not_called()
        controller._can_reuse_stale_bottom_bar_regions.assert_not_called()

    def test_gameplay_hud_gate_keeps_geometry_when_bar_is_temporarily_obstructed(self):
        controller = self.make_controller([])
        del controller._refresh_gameplay_hud_state
        old_regions = {
            "hp": (120, 220, 110, 12),
            "mp": (260, 220, 110, 12),
        }
        old_track_regions = {
            "hp": (125, 223, 100, 6),
            "mp": (265, 223, 100, 6),
        }
        controller.bottom_bar_regions = dict(old_regions)
        controller.bottom_bar_track_regions = dict(old_track_regions)
        controller.bottom_bar_client_bounds = (100, 200, 800, 600)
        controller.bottom_bar_regions_at = 1.0
        controller._reuse_cached_bottom_bar_regions_with_direct_sample = Mock(return_value=False)
        controller._find_bottom_bar_pair_regions = Mock(return_value={})
        controller._can_reuse_stale_bottom_bar_regions = Mock(return_value=False)
        controller._target_client_bounds = Mock(return_value=(100, 200, 800, 600))

        self.assertFalse(controller._refresh_gameplay_hud_state(10.0))

        self.assertFalse(controller.gameplay_hud_active)
        self.assertEqual(controller.bottom_bar_regions, {})
        self.assertEqual(controller.bottom_bar_track_regions, {})
        controller._find_bottom_bar_pair_regions.assert_called_once_with(
            use_cache=False,
            allow_stale_on_failure=False,
        )
        controller._reuse_cached_bottom_bar_regions_with_direct_sample.assert_not_called()
        controller._can_reuse_stale_bottom_bar_regions.assert_not_called()

    def test_gameplay_hud_gate_rejects_stale_regions_when_one_bar_fails(self):
        controller = self.make_controller([])
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
        controller.bottom_bar_client_bounds = (0, 0, 1000, 1000)
        controller.bottom_bar_regions_at = 0.0
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1000, 1000))
        controller._bar_percent_from_region_snapshot = Mock(
            side_effect=[
                (72.0, "OK", None),
                (None, "找不到符合顏色的填滿欄位", None),
            ]
        )

        self.assertFalse(
            controller._can_reuse_stale_bottom_bar_regions(
                old_regions,
                old_track_regions,
                (0, 0, 1000, 1000),
            )
        )
        self.assertEqual(controller._bar_percent_from_region_snapshot.call_count, 2)

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
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
        self.assertEqual(controller.last_hp_drink_at, -999.0)
        controller.gui.set_status.assert_called_with("等待楓星成為前景視窗")

    def test_hp_blocked_sound_is_throttled_when_target_not_foreground(self):
        controller = self.make_controller([False, False, False])

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.0 + POTION_BLOCKED_SOUND_INTERVAL_SECONDS / 2, 25.0)
            controller._maybe_drink_hp(100.0 + POTION_BLOCKED_SOUND_INTERVAL_SECONDS, 25.0)

        tap_hotkey.assert_not_called()
        self.assertEqual(play_media.call_count, 2)
        self.assertEqual(play_media.call_args_list[0].args, (AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop"))
        self.assertEqual(play_media.call_args_list[1].args, (AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop"))

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
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
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

    def test_hp_successful_auto_drink_does_not_log_trigger(self):
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

    def test_hp_repeat_auto_drink_uses_current_sample_without_confirm_recapture_or_log(self):
        controller = self.make_controller([])
        controller.gameplay_hud_active = True
        controller.potion_send_prevalidated_at = 100.2
        controller.last_hp_drink_at = 100.0
        controller._capture_confirmed_bar_percent = Mock()

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print") as print_mock,
        ):
            controller._maybe_drink_hp(100.2, 25.0)

        tap_hotkey.assert_called_once_with("Delete")
        controller._capture_confirmed_bar_percent.assert_not_called()
        print_mock.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, 100.2)

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

    def test_mp_successful_auto_drink_does_not_log_trigger(self):
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
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)

        tap_hotkey.assert_not_called()
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")
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

    def test_hp_flat_repeat_respects_configured_cooldown(self):
        controller = self.make_controller([True] * 6)
        controller.settings.hp_cooldown_seconds = 0.2

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.05, 25.0)
            controller._maybe_drink_hp(100.19, 25.0)
            controller._maybe_drink_hp(100.2, 25.0)

        self.assertEqual(tap_hotkey.call_count, 2)
        tap_hotkey.assert_called_with("Delete")
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.2, 25.0),
            ],
        )

    def test_mp_flat_repeat_respects_configured_cooldown(self):
        controller = self.make_controller([True] * 6)
        controller.settings.mp_cooldown_seconds = 0.2

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_mp(100.0, 25.0)
            controller._maybe_drink_mp(100.05, 25.0)
            controller._maybe_drink_mp(100.19, 25.0)
            controller._maybe_drink_mp(100.2, 25.0)

        self.assertEqual(tap_hotkey.call_count, 2)
        tap_hotkey.assert_called_with("End")
        self.assertEqual(
            controller.mp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.2, 25.0),
            ],
        )

    def test_hp_repeat_skips_until_configured_cooldown_elapsed(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_cooldown_seconds = 0.2

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.05, 25.0)
            controller._maybe_drink_hp(100.2, 25.0)

        self.assertEqual(tap_hotkey.call_count, 2)
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.2, 25.0),
            ],
        )

    def test_hp_repeat_schedules_due_send_for_exact_cooldown(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_cooldown_seconds = 0.2
        controller.gameplay_hud_active = True

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.05, 25.0)

            self.assertEqual(tap_hotkey.call_count, 1)
            self.assertEqual(controller.hp_pending_potion_send_at, 100.2)
            self.assertEqual(controller.hp_pending_potion_send_percent, 25.0)

            controller._process_due_potion_sends(100.199)
            self.assertEqual(tap_hotkey.call_count, 1)

            controller._process_due_potion_sends(100.2)

        self.assertEqual(tap_hotkey.call_count, 2)
        tap_hotkey.assert_called_with("Delete")
        self.assertEqual(controller.last_hp_drink_at, 100.2)
        self.assertEqual(controller.hp_pending_potion_send_at, -999.0)
        self.assertIsNone(controller.hp_pending_potion_send_percent)
        self.assertEqual(
            controller.hp_potion_effect_attempts,
            [
                PotionEffectAttempt(100.0, 25.0),
                PotionEffectAttempt(100.2, 25.0),
            ],
        )

    def test_update_processes_due_potion_send_before_capture_gate(self):
        controller = self.make_controller([True])
        controller.settings.hp_cooldown_seconds = 0.2
        controller.next_capture_at = 999.0
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.gameplay_hud_active = True
        controller.last_hp_drink_at = 100.0
        controller.hp_pending_potion_send_at = 100.2
        controller.hp_pending_potion_send_percent = 25.0
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._capture_bar_percent = Mock()

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller.update(100.2)

        tap_hotkey.assert_called_once_with("Delete")
        controller._capture_bar_percent.assert_not_called()
        self.assertEqual(controller.last_hp_drink_at, 100.2)
        self.assertEqual(controller.hp_pending_potion_send_at, -999.0)

    def test_near_due_potion_send_skips_capture_to_preserve_cooldown_time(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.gameplay_hud_active = True
        controller.last_hp_drink_at = 100.0
        controller.hp_pending_potion_send_at = 100.2
        controller.hp_pending_potion_send_percent = 25.0
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._capture_bar_percent = Mock()

        controller.update(100.1)

        controller._capture_bar_percent.assert_not_called()
        self.assertEqual(controller.hp_pending_potion_send_at, 100.2)

    def test_update_uses_fast_capture_interval_when_hp_nears_threshold(self):
        controller = self.run_capture_interval_update(hp_percent=57.0, mp_percent=80.0)

        self.assertAlmostEqual(controller.next_capture_at, 100.0 + POTION_FAST_CAPTURE_INTERVAL_SECONDS)

    def test_update_uses_fast_capture_interval_when_mp_nears_threshold(self):
        controller = self.run_capture_interval_update(hp_percent=80.0, mp_percent=57.0)

        self.assertAlmostEqual(controller.next_capture_at, 100.0 + POTION_FAST_CAPTURE_INTERVAL_SECONDS)

    def test_update_keeps_default_capture_interval_when_potions_are_far_from_threshold(self):
        controller = self.run_capture_interval_update(hp_percent=70.0, mp_percent=80.0)

        self.assertAlmostEqual(controller.next_capture_at, 100.0 + DEFAULT_CAPTURE_INTERVAL_SECONDS)

    def test_update_keeps_default_capture_interval_when_auto_drink_is_disabled(self):
        controller = self.run_capture_interval_update(
            hp_percent=57.0,
            mp_percent=80.0,
            auto_drink_enabled=False,
        )

        self.assertAlmostEqual(controller.next_capture_at, 100.0 + DEFAULT_CAPTURE_INTERVAL_SECONDS)
        controller._capture_bar_percents.assert_not_called()
        controller._maybe_drink_hp.assert_not_called()
        controller._maybe_drink_mp.assert_not_called()
        controller.gui.set_current_percentages.assert_called_with(None, None)

    def test_update_skips_hp_mp_hud_refresh_when_auto_drink_is_disabled_and_exp_is_disabled(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.auto_drink_enabled = False
        controller.settings.exp_efficiency_enabled = False
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        controller._capture_bar_percents = Mock(return_value=(57.0, 80.0))
        controller._maybe_drink_hp = Mock()
        controller._maybe_drink_mp = Mock()
        controller._stop_experience_ocr_job = Mock()
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot()

        controller.update(100.0)

        controller._transition_pause_reason.assert_not_called()
        controller._refresh_gameplay_hud_state.assert_not_called()
        controller._capture_bar_percents.assert_not_called()
        controller._maybe_drink_hp.assert_not_called()
        controller._maybe_drink_mp.assert_not_called()
        controller.gui.set_current_percentages.assert_called_with(None, None)
        controller.gui.set_status.assert_called_with(f"自動喝水已暫停，按 {controller.settings.toggle_hotkey} 恢復")

    def test_update_skips_hp_mp_hud_refresh_when_auto_drink_is_disabled_and_exp_needs_hud(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.auto_drink_enabled = False
        controller.settings.exp_efficiency_enabled = True
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._experience_runtime_has_cached_hud = Mock(return_value=False)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        controller._capture_bar_percents = Mock(return_value=(57.0, 80.0))
        controller._update_experience_efficiency = Mock()
        controller._pause_experience_for_missing_hud = Mock()

        controller.update(100.0)

        controller._transition_pause_reason.assert_not_called()
        controller._refresh_gameplay_hud_state.assert_not_called()
        controller._capture_bar_percents.assert_not_called()
        controller._update_experience_efficiency.assert_not_called()
        controller._pause_experience_for_missing_hud.assert_called_once_with(100.0)
        controller.gui.set_current_percentages.assert_called_with(None, None)

    def test_update_allows_exp_with_cached_hud_when_auto_drink_is_disabled(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.auto_drink_enabled = False
        controller.settings.exp_efficiency_enabled = True
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._experience_runtime_has_cached_hud = Mock(return_value=True)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        controller._capture_bar_percents = Mock(return_value=(57.0, 80.0))
        controller._update_experience_efficiency = Mock()
        controller._pause_experience_for_missing_hud = Mock()

        controller.update(100.0)

        controller._refresh_gameplay_hud_state.assert_not_called()
        controller._capture_bar_percents.assert_not_called()
        controller._update_experience_efficiency.assert_called_once_with(100.0)
        controller._pause_experience_for_missing_hud.assert_not_called()
        controller.gui.set_current_percentages.assert_called_with(None, None)

    def test_update_skips_hp_mp_hud_refresh_when_no_potion_bar_is_enabled(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.auto_drink_enabled = True
        controller.settings.hp_enabled = False
        controller.settings.mp_enabled = False
        controller.settings.exp_efficiency_enabled = False
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        controller._capture_bar_percents = Mock(return_value=(57.0, 80.0))
        controller._maybe_drink_hp = Mock()
        controller._maybe_drink_mp = Mock()
        controller._stop_experience_ocr_job = Mock()
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot()

        controller.update(100.0)

        controller._transition_pause_reason.assert_not_called()
        controller._refresh_gameplay_hud_state.assert_not_called()
        controller._capture_bar_percents.assert_not_called()
        controller._maybe_drink_hp.assert_not_called()
        controller._maybe_drink_mp.assert_not_called()
        controller.gui.set_current_percentages.assert_called_with(None, None)
        controller.gui.set_status.assert_called_with("未勾選紅水或藍水，暫停 HP/MP 檢查")

    def test_update_skips_hp_mp_hud_refresh_when_no_potion_bar_is_enabled_and_exp_needs_hud(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.auto_drink_enabled = True
        controller.settings.hp_enabled = False
        controller.settings.mp_enabled = False
        controller.settings.exp_efficiency_enabled = True
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._experience_runtime_has_cached_hud = Mock(return_value=False)
        controller._refresh_gameplay_hud_state = Mock(return_value=True)
        controller._capture_bar_percents = Mock(return_value=(57.0, 80.0))
        controller._update_experience_efficiency = Mock()
        controller._pause_experience_for_missing_hud = Mock()

        controller.update(100.0)

        controller._refresh_gameplay_hud_state.assert_not_called()
        controller._capture_bar_percents.assert_not_called()
        controller._update_experience_efficiency.assert_not_called()
        controller._pause_experience_for_missing_hud.assert_called_once_with(100.0)
        controller.gui.set_current_percentages.assert_called_with(None, None)
        controller.gui.set_status.assert_called_with("未勾選紅水或藍水，暫停 HP/MP 檢查")

    def test_update_skips_hp_mp_capture_when_fresh_hud_locator_fails_with_cached_geometry(self):
        controller = self.make_controller([True])
        del controller._refresh_gameplay_hud_state
        controller.next_capture_at = 0.0
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._sync_pickup_key_state = Mock()
        controller._save_settings_when_idle = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._release_all_potion_keys = Mock()
        controller._pause_experience_for_missing_hud = Mock()
        controller._capture_bar_percents = Mock(return_value=(30.0, 80.0))
        controller._maybe_drink_hp = Mock()
        controller._maybe_drink_mp = Mock()
        controller._find_bottom_bar_pair_regions = Mock(return_value={})
        controller._target_client_bounds = Mock(return_value=(100, 200, 800, 600))
        controller.bottom_bar_regions = {
            "hp": (120, 220, 110, 12),
            "mp": (260, 220, 110, 12),
        }
        controller.bottom_bar_track_regions = {
            "hp": (125, 223, 100, 6),
            "mp": (265, 223, 100, 6),
        }
        controller.bottom_bar_client_bounds = (100, 200, 800, 600)
        controller.bottom_bar_regions_at = 100.0

        controller.update(100.0)

        controller._find_bottom_bar_pair_regions.assert_called_once_with(
            use_cache=False,
            allow_stale_on_failure=False,
        )
        controller._capture_bar_percents.assert_not_called()
        controller._maybe_drink_hp.assert_not_called()
        controller._maybe_drink_mp.assert_not_called()
        controller._release_all_potion_keys.assert_called_once()
        controller._pause_experience_for_missing_hud.assert_called_once_with(100.0)
        controller.gui.set_current_percentages.assert_called_with(None, None)
        controller.gui.set_status.assert_called_with("未偵測到遊戲 HUD，暫停取樣")

    def test_update_ignores_disabled_or_held_potion_for_fast_capture_interval(self):
        disabled = self.run_capture_interval_update(
            hp_percent=57.0,
            mp_percent=80.0,
            hp_enabled=False,
        )
        held = self.run_capture_interval_update(
            hp_percent=57.0,
            mp_percent=80.0,
            hp_hold=True,
        )

        self.assertAlmostEqual(disabled.next_capture_at, 100.0 + DEFAULT_CAPTURE_INTERVAL_SECONDS)
        self.assertAlmostEqual(held.next_capture_at, 100.0 + DEFAULT_CAPTURE_INTERVAL_SECONDS)

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
            controller._maybe_drink_hp(100.0 + POTION_CONTINUOUS_HOLD_REFRESH_SECONDS / 2, 25.0)
            controller._maybe_drink_hp(100.3, 51.0)

        key_down.assert_called_once_with(0x2E)
        key_up.assert_called_once_with(0x2E)
        tap_hotkey.assert_not_called()
        self.assertEqual(controller.hp_potion_held_vk, 0)
        self.assertEqual(controller.hp_potion_effect_attempts, [])

    def test_hp_continuous_refreshes_held_key_until_above_threshold(self):
        controller = self.make_controller([True] * 4)
        controller.settings.hp_continuous_enabled = True

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller._maybe_drink_hp(100.0, 25.0)
            controller._maybe_drink_hp(100.0 + POTION_CONTINUOUS_HOLD_REFRESH_SECONDS, 25.0)

        self.assertEqual(key_down.call_args_list, [call(0x2E), call(0x2E)])
        key_up.assert_not_called()
        tap_hotkey.assert_not_called()
        self.assertEqual(controller.hp_potion_held_vk, 0x2E)

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

    def test_hp_continuous_refresh_uses_potion_action_worker_when_available(self):
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
            controller._maybe_drink_hp(100.0 + POTION_CONTINUOUS_HOLD_REFRESH_SECONDS, 25.0)

        controller.potion_action_worker.hold.assert_called_once_with("hp", 0x2E)
        controller.potion_action_worker.refresh_hold.assert_called_once_with("hp", 0x2E)
        controller.potion_action_worker.release.assert_not_called()
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
        controller._capture_bar_percents = Mock(return_value=(80.0, 80.0))
        order = []
        controller._maybe_drink_hp = Mock(side_effect=lambda now, percent: order.append("hp"))
        controller._maybe_drink_mp = Mock(side_effect=lambda now, percent: order.append("mp"))
        controller._update_potion_effect_watch_cycles = Mock(
            side_effect=lambda now, hp, mp: order.append("watch")
        )
        controller._update_experience_efficiency = Mock(side_effect=lambda now: order.append("exp"))

        controller.update(100.0)

        self.assertEqual(order, ["hp", "mp", "watch", "exp"])

    def test_update_defers_experience_when_potion_needs_action(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.next_experience_capture_at = 0.0
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.settings.exp_efficiency_enabled = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._capture_bar_percents = Mock(return_value=(25.0, 80.0))
        controller._maybe_drink_hp = Mock()
        controller._maybe_drink_mp = Mock()
        controller._update_potion_effect_watch_cycles = Mock()
        controller._update_experience_efficiency = Mock()
        controller._defer_experience_for_potion_priority = Mock()

        controller.update(100.0)

        controller._defer_experience_for_potion_priority.assert_called_once_with(100.0)
        controller._update_experience_efficiency.assert_not_called()

    def test_update_reuses_prevalidated_hud_for_potion_send(self):
        controller = self.make_controller([True])
        controller.next_capture_at = 0.0
        controller.control_hotkey_worker = None
        controller.gui.pump.return_value = True
        controller.settings.exp_efficiency_enabled = False
        controller.last_hp_drink_at = 99.9
        controller.gameplay_hud_active = True
        controller._sync_registered_control_hotkeys = Mock()
        controller._transition_pause_reason = Mock(return_value=None)
        controller._capture_bar_percents = Mock(return_value=(25.0, 80.0))
        controller._update_potion_effect_watch_cycles = Mock()

        with (
            patch("maple_star.controller.tap_hotkey") as tap_hotkey,
            patch("builtins.print"),
        ):
            controller.update(100.0)

        tap_hotkey.assert_called_once_with("Delete")
        controller._refresh_gameplay_hud_state.assert_called_once_with(100.0)
        self.assertEqual(controller.potion_send_prevalidated_at, 100.0)

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

    def test_continuous_potion_no_effect_alert_does_not_release_held_key(self):
        controller = self.make_controller([])
        controller.hp_potion_held_vk = 0x2E

        with (
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._alert_suspected_no_potion("hp", "HP", 25.0, 100.0)

        key_up.assert_not_called()
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_held_vk, 0x2E)
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

    def test_continuous_potion_alerts_after_three_stable_no_effect_windows(self):
        controller = self.make_controller([True] * 6)
        controller.settings.hp_continuous_enabled = True
        controller._capture_bar_percent = Mock(return_value=49.0)

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            for index in range(POTION_EFFECT_NO_EFFECT_LIMIT):
                now = 100.0 + index * (POTION_EFFECT_OBSERVATION_SECONDS + 0.2)
                self.seed_stable_potion_samples(controller, "hp", now, 49.0)
                controller._maybe_drink_hp(now, 49.0)
                mature_at = now + POTION_EFFECT_OBSERVATION_SECONDS
                self.seed_stable_potion_samples(controller, "hp", mature_at, 49.0)
                self.assertTrue(controller._update_potion_effect_watch_cycles(mature_at, 49.0, 80.0))

        self.assertEqual(key_down.call_args_list, [call(0x2E), call(0x2E), call(0x2E)])
        key_up.assert_not_called()
        self.assertEqual(controller.hp_potion_no_effect_count, POTION_EFFECT_NO_EFFECT_LIMIT)
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_held_vk, 0x2E)
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

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

    def test_potion_watch_alerts_after_repeated_no_effect_attempts_mature(self):
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
        self.assertIsNone(controller.mp_out_of_potion_hold)
        self.assertEqual(controller.mp_potion_effect_attempts, [])
        controller.gui.set_status.assert_called_with("MP 檢查藥水")
        controller.gui.show_toggle_notice.assert_called_with("MP 檢查藥水")
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

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

    def test_potion_watch_alerts_after_stable_pre_and_post_no_effect_confirmations(self):
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
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        controller.gui.set_status.assert_called_with("HP 檢查藥水")
        controller.gui.show_toggle_notice.assert_called_with("HP 檢查藥水")
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

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
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

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

    def test_potion_watch_alerts_hp_below_threshold_when_stable_no_effect(self):
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
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

    def test_potion_watch_alerts_hp_at_high_percent_threshold(self):
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
        self.assertIsNone(controller.hp_out_of_potion_hold)
        self.assertEqual(controller.hp_potion_effect_attempts, [])
        controller.gui.set_status.assert_called_with("HP 檢查藥水")
        controller.gui.show_toggle_notice.assert_called_with("HP 檢查藥水")
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")

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

    def test_no_potion_alert_plays_check_sound(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._alert_suspected_no_potion("hp", "HP", 25.0, 100.0)
        play_media.assert_called_once_with(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check")
        controller.gui.set_status.assert_called_with("HP 檢查藥水")
        controller.gui.show_toggle_notice.assert_called_with("HP 檢查藥水")

    def test_no_potion_alert_check_sound_is_throttled_for_ten_seconds(self):
        controller = self.make_controller([])

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._alert_suspected_no_potion("hp", "HP", 25.0, 100.0)
            controller._alert_suspected_no_potion("mp", "MP", 25.0, 109.99)
            controller._alert_suspected_no_potion("mp", "MP", 25.0, 110.0)

        self.assertEqual(play_media.call_args_list, [
            call(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check"),
            call(AUTO_DRINK_POTION_CHECK_SOUND_PATH, "auto_drink_potion_check"),
        ])
        self.assertEqual(controller.last_potion_check_sound_at, 110.0)
        self.assertEqual(POTION_CHECK_SOUND_INTERVAL_SECONDS, 10.0)

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

    def test_toggle_auto_drink_syncs_gui_potion_options_and_restores_previous_selection(self):
        controller = self.make_controller([])
        controller.settings.hp_enabled = True
        controller.settings.mp_enabled = False

        with (
            patch.object(controller, "_play_media_file"),
            patch("builtins.print"),
        ):
            controller.toggle_auto_drink_enabled()
            controller.toggle_auto_drink_enabled()

        self.assertTrue(controller.auto_drink_enabled)
        self.assertTrue(controller.settings.hp_enabled)
        self.assertFalse(controller.settings.mp_enabled)
        self.assertEqual(
            controller.gui.set_potion_enabled.call_args_list,
            [call(False, False), call(True, False)],
        )

    def test_runtime_toggle_auto_drink_syncs_gui_potion_options(self):
        controller = self.make_controller([])
        controller.runtime_processes_enabled = True
        controller.runtime_processes = self.FakeRuntime()

        with (
            patch.object(controller, "_play_media_file"),
            patch("builtins.print"),
        ):
            controller.toggle_auto_drink_enabled()

        self.assertFalse(controller.auto_drink_enabled)
        controller.gui.set_potion_enabled.assert_called_once_with(False, False)

    def test_auto_drink_hotkey_short_press_does_not_disable_when_enabled(self):
        controller = self.make_controller([])
        controller.settings.toggle_hotkey = "F11"
        controller.auto_drink_enabled = True
        controller.toggle_hotkey_was_down = True

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller.toggle_hotkey_was_down = False
            controller._process_pending_auto_drink_disable(100.0 + AUTO_DRINK_DISABLE_HOLD_SECONDS / 2)

        self.assertTrue(controller.auto_drink_enabled)
        self.assertEqual(controller.auto_drink_disable_hold_started_at, -999.0)
        play_media.assert_not_called()

    def test_auto_drink_hotkey_pickup_length_hold_disables_when_enabled(self):
        controller = self.make_controller([])
        controller.settings.toggle_hotkey = "F11"
        controller.auto_drink_enabled = True
        controller.toggle_hotkey_was_down = True

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller._process_pending_auto_drink_disable(100.0 + PICKUP_DISABLE_HOLD_SECONDS)

        self.assertFalse(controller.auto_drink_enabled)
        self.assertEqual(controller.auto_drink_disable_hold_started_at, -999.0)
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_auto_drink_hotkey_long_press_disables_when_enabled(self):
        controller = self.make_controller([])
        controller.settings.toggle_hotkey = "F11"
        controller.auto_drink_enabled = True
        controller.toggle_hotkey_was_down = True

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller._process_pending_auto_drink_disable(100.0 + AUTO_DRINK_DISABLE_HOLD_SECONDS)

        self.assertFalse(controller.auto_drink_enabled)
        self.assertEqual(controller.auto_drink_disable_hold_started_at, -999.0)
        play_media.assert_called_once_with(AUTO_DRINK_STOP_SOUND_PATH, "auto_drink_stop")

    def test_auto_drink_hotkey_short_press_enables_when_disabled(self):
        controller = self.make_controller([])
        controller.auto_drink_enabled = False

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)

        self.assertTrue(controller.auto_drink_enabled)
        play_media.assert_called_once_with(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")

    def test_auto_drink_toggle_debounce_accepts_next_toggle_after_shortened_interval(self):
        controller = self.make_controller([])
        controller.auto_drink_enabled = False
        controller.toggle_hotkey_was_down = True

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller._try_toggle_scripts_enabled(100.0 + AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS - 0.01)
            self.assertEqual(controller.auto_drink_disable_hold_started_at, -999.0)

            controller._try_toggle_scripts_enabled(100.0 + AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS + 0.001)

        self.assertTrue(controller.auto_drink_enabled)
        self.assertEqual(controller.auto_drink_disable_hold_started_at, 100.0 + AUTO_DRINK_TOGGLE_DEBOUNCE_SECONDS + 0.001)
        play_media.assert_called_once_with(AUTO_DRINK_START_SOUND_PATH, "auto_drink_start")

    def test_enable_disable_hotkeys_are_silently_ignored_outside_game_and_app_foreground(self):
        controller = self.make_controller([False, False, False, False, False])
        controller.auto_drink_enabled = False
        controller.settings.exp_efficiency_enabled = False
        controller.pickup_enabled = False
        controller.scripts_enabled = True
        controller.reset_experience_statistics = Mock(return_value=True)

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print") as print_mock,
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller._try_toggle_experience_efficiency(101.0)
            controller._try_reset_experience_statistics(102.0)
            controller._try_toggle_pickup(103.0)
            controller._try_emergency_stop(104.0)

        self.assertFalse(controller.auto_drink_enabled)
        self.assertFalse(controller.settings.exp_efficiency_enabled)
        self.assertFalse(controller.pickup_enabled)
        self.assertTrue(controller.scripts_enabled)
        controller.reset_experience_statistics.assert_not_called()
        play_media.assert_not_called()
        controller.gui.set_status.assert_not_called()
        controller.gui.show_toggle_notice.assert_not_called()
        print_mock.assert_not_called()

    def test_enable_disable_hotkeys_are_allowed_when_app_is_foreground(self):
        controller = self.make_controller([False, False, False, False, False])
        controller.gui.is_app_window_foreground.return_value = True
        controller.auto_drink_enabled = False
        controller.settings.exp_efficiency_enabled = False
        controller.pickup_enabled = False
        controller.settings.pickup_key = "Z"
        controller.scripts_enabled = True
        controller.reset_experience_statistics = Mock(return_value=True)
        controller.emergency_stop = Mock()

        with (
            patch.object(controller, "_play_media_file"),
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller._try_toggle_experience_efficiency(101.0)
            controller._try_reset_experience_statistics(102.0)
            controller._try_toggle_pickup(103.0)
            controller._try_emergency_stop(104.0)

        self.assertTrue(controller.auto_drink_enabled)
        self.assertTrue(controller.settings.exp_efficiency_enabled)
        self.assertTrue(controller.pickup_enabled)
        controller.reset_experience_statistics.assert_called_once()
        controller.emergency_stop.assert_called_once()

    def test_hold_disable_is_cancelled_if_game_loses_foreground_before_completion(self):
        controller = self.make_controller([True, False])
        controller.settings.toggle_hotkey = "F11"
        controller.auto_drink_enabled = True
        controller.toggle_hotkey_was_down = True

        with (
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_scripts_enabled(100.0)
            controller._process_pending_auto_drink_disable(100.0 + AUTO_DRINK_DISABLE_HOLD_SECONDS)

        self.assertTrue(controller.auto_drink_enabled)
        self.assertEqual(controller.auto_drink_disable_hold_started_at, -999.0)
        play_media.assert_not_called()
        controller.gui.show_toggle_notice.assert_not_called()

    def test_play_media_file_reuses_open_alias_and_starts_immediately(self):
        controller = AutoPotionController.__new__(AutoPotionController)
        controller._play_toggle_beep = Mock()
        controller._media_alias_paths = {}
        winmm = SimpleNamespace(mciSendStringW=Mock(return_value=0))
        sound_path = AUTO_DRINK_STOP_SOUND_PATH

        with patch("maple_star.controller.ctypes.windll", SimpleNamespace(winmm=winmm), create=True):
            controller._play_media_file(sound_path, "test_sound")

        commands = [call.args[0] for call in winmm.mciSendStringW.call_args_list]
        self.assertIn(f'open "{sound_path}" type mpegvideo alias test_sound', commands)
        self.assertIn("setaudio test_sound volume to 200", commands)
        self.assertIn("set test_sound time format milliseconds", commands)
        self.assertLess(commands.index("setaudio test_sound volume to 200"), commands.index("play test_sound from 0"))
        self.assertLess(
            commands.index("set test_sound time format milliseconds"),
            commands.index("play test_sound from 0"),
        )

        winmm.mciSendStringW.reset_mock()
        with patch("maple_star.controller.ctypes.windll", SimpleNamespace(winmm=winmm), create=True):
            controller._play_media_file(sound_path, "test_sound")

        replay_commands = [call.args[0] for call in winmm.mciSendStringW.call_args_list]
        self.assertEqual(replay_commands, ["stop test_sound", "play test_sound from 0"])
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

    def test_control_hotkeys_do_not_dispatch_or_notice_outside_game_and_app_foreground(self):
        controller = self.make_controller([False])
        controller.gui.is_detecting_key.return_value = False
        controller.gui.consume_key_detection_finished.return_value = False
        controller.control_hotkey_worker = Mock()
        controller.control_hotkey_worker.sync_down_states.return_value = {
            "toggle": True,
            "emergency_stop": True,
            "experience_toggle": True,
            "experience_reset": True,
            CONTROL_HOTKEY_PICKUP_TOGGLE: True,
        }
        controller.control_hotkey_worker.drain_events.return_value = [
            "toggle",
            "experience_toggle",
            "experience_reset",
            CONTROL_HOTKEY_PICKUP_TOGGLE,
            "emergency_stop",
        ]
        controller.auto_drink_disable_hold_started_at = 100.0
        controller.pickup_disable_hold_started_at = 100.0
        controller._try_toggle_scripts_enabled = Mock()
        controller._try_toggle_experience_efficiency = Mock()
        controller._try_reset_experience_statistics = Mock()
        controller._try_toggle_pickup = Mock()
        controller.emergency_stop = Mock()

        with patch("builtins.print") as print_mock:
            controller.poll_control_hotkeys()

        controller.control_hotkey_worker.set_events_enabled.assert_called_once_with(False)
        controller.control_hotkey_worker.clear_events.assert_called_once()
        controller.control_hotkey_worker.sync_down_states.assert_called_once()
        controller.control_hotkey_worker.drain_events.assert_called_once()
        controller._try_toggle_scripts_enabled.assert_not_called()
        controller._try_toggle_experience_efficiency.assert_not_called()
        controller._try_reset_experience_statistics.assert_not_called()
        controller._try_toggle_pickup.assert_not_called()
        controller.emergency_stop.assert_not_called()
        controller.gui.set_status.assert_not_called()
        controller.gui.show_toggle_notice.assert_not_called()
        print_mock.assert_not_called()
        self.assertTrue(controller.toggle_hotkey_was_down)
        self.assertTrue(controller.experience_toggle_hotkey_was_down)
        self.assertTrue(controller.experience_reset_hotkey_was_down)
        self.assertTrue(controller.pickup_toggle_hotkey_was_down)
        self.assertEqual(controller.auto_drink_disable_hold_started_at, -999.0)
        self.assertEqual(controller.pickup_disable_hold_started_at, -999.0)

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
        controller.reset_experience_statistics = Mock(return_value=True)

        with patch("builtins.print") as print_mock:
            controller._try_reset_experience_statistics(100.0)

        controller.reset_experience_statistics.assert_called_once()
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "已重置")
        controller.gui.set_status.assert_called_once_with("經驗統計已重置")
        controller.gui.show_toggle_notice.assert_called_once_with("經驗統計已重置")
        self.assertEqual(controller.last_action, "F9 經驗統計重置")
        print_mock.assert_called_once_with("F9：經驗統計已重置")

    def test_toggle_experience_efficiency_does_not_require_character_stat_hotkey(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = False
        controller.settings.character_stat_hotkey = ""

        with patch("builtins.print") as print_mock:
            controller.toggle_experience_efficiency()

        controller.gui.set_exp_efficiency_enabled.assert_called_once_with(True)
        controller.gui.set_status.assert_called_once_with("經驗統計已啟用")
        print_mock.assert_called_once_with("F10：經驗統計已啟用")

    def test_reset_experience_statistics_does_not_require_character_stat_hotkey(self):
        controller = self.make_controller([])
        controller.settings.character_stat_hotkey = ""
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.experience_tracker.add_reading(0.0, 1000, 10.0)

        with patch("builtins.print") as print_mock:
            result = controller.reset_experience_statistics()

        self.assertTrue(result)
        self.assertEqual(len(controller.experience_tracker.samples), 0)
        controller.gui.set_status.assert_not_called()
        print_mock.assert_not_called()

    def test_direct_experience_checkbox_is_allowed_without_character_stat_hotkey(self):
        controller = self.make_controller([])
        controller.settings.exp_efficiency_enabled = True
        controller.settings.character_stat_hotkey = ""
        controller.experience_tracker = Mock()
        controller.experience_tracker.snapshot.return_value = ExperienceSnapshot(sample_count=0)

        self.assertTrue(controller._enforce_experience_prerequisites(100.0))

        controller.gui.set_exp_efficiency_enabled.assert_not_called()
        controller.gui.set_experience_snapshot.assert_not_called()
        self.assertTrue(controller.settings.exp_efficiency_enabled)

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

    def test_pickup_hotkey_short_press_does_not_disable_when_enabled(self):
        controller = self.make_controller([])
        controller.settings.pickup_toggle_hotkey = "F7"
        controller.pickup_enabled = True
        controller.pickup_held_vk = 0x5A
        controller.pickup_toggle_hotkey_was_down = True

        with (
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_pickup(100.0)
            controller.pickup_toggle_hotkey_was_down = False
            controller._process_pending_pickup_disable(100.0 + PICKUP_DISABLE_HOLD_SECONDS / 2)

        self.assertTrue(controller.pickup_enabled)
        self.assertEqual(controller.pickup_held_vk, 0x5A)
        key_up.assert_not_called()
        play_media.assert_not_called()

    def test_pickup_hotkey_long_press_disables_when_enabled(self):
        controller = self.make_controller([])
        controller.settings.pickup_toggle_hotkey = "F7"
        controller.pickup_enabled = True
        controller.pickup_held_vk = 0x5A
        controller.pickup_toggle_hotkey_was_down = True

        with (
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_pickup(100.0)
            controller._process_pending_pickup_disable(100.0 + PICKUP_DISABLE_HOLD_SECONDS)

        self.assertFalse(controller.pickup_enabled)
        self.assertEqual(controller.pickup_held_vk, 0)
        key_up.assert_called_once_with(0x5A)
        play_media.assert_called_once_with(AUTO_PICKUP_STOP_SOUND_PATH, "pickup_stop")

    def test_pickup_toggle_debounce_accepts_next_toggle_after_shortened_interval(self):
        controller = self.make_controller([])
        controller.settings.pickup_toggle_hotkey = "F7"
        controller.settings.pickup_key = "Z"
        controller.pickup_toggle_hotkey_was_down = True

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch.object(controller, "_play_media_file") as play_media,
            patch("builtins.print"),
        ):
            controller._try_toggle_pickup(200.0)
            controller._try_toggle_pickup(200.0 + PICKUP_TOGGLE_DEBOUNCE_SECONDS - 0.01)
            self.assertEqual(controller.pickup_disable_hold_started_at, -999.0)

            controller._try_toggle_pickup(200.0 + PICKUP_TOGGLE_DEBOUNCE_SECONDS + 0.001)

        self.assertTrue(controller.pickup_enabled)
        self.assertEqual(controller.pickup_disable_hold_started_at, 200.0 + PICKUP_TOGGLE_DEBOUNCE_SECONDS + 0.001)
        key_down.assert_called_once_with(0x5A)
        play_media.assert_called_once_with(AUTO_PICKUP_START_SOUND_PATH, "pickup_start")

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

    def test_pickup_does_not_reassert_held_key(self):
        controller = self.make_controller([])
        controller.settings.pickup_key = "Z"
        controller.pickup_enabled = True
        controller.pickup_held_vk = 0x5A

        with (
            patch("maple_star.controller.key_down") as key_down,
            patch("maple_star.controller.key_up") as key_up,
            patch.object(controller, "_play_media_file") as play_media,
        ):
            controller._sync_pickup_key_state()

        key_down.assert_not_called()
        key_up.assert_not_called()
        play_media.assert_not_called()
        self.assertTrue(controller.pickup_enabled)
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
        controller.settings.character_stat_hotkey = "V"
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
        self.assertEqual(payload["raw_current_exp"], 132553)
        self.assertEqual(payload["raw_percent"], 18.36)
        self.assertEqual(payload["current_exp"], 132553)
        self.assertEqual(payload["percent"], 18.36)
        self.assertEqual(payload["xp_per_10m"], 2000.0)

    def test_accepted_experience_ocr_seeds_exp_10m_checkpoint_when_missing(self):
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
        controller.experience_tracker.add_reading(0.0, 100000, 10.0, confidence=0.98)
        controller.experience_tracker.exp_10m_checkpoint_exp = None
        controller.experience_tracker.exp_10m_gain = None
        controller.experience_ocr_job = ExperienceOcrJob(submitted_at=8.0, future=DoneFuture())

        with patch("maple_star.controllers.auto_potion_controller.log_experience_debug"):
            self.assertTrue(controller._process_experience_ocr_job(8.0, effective_now=8.0))

        self.assertEqual(controller.experience_tracker.exp_10m_checkpoint_exp, 132553)
        self.assertIsNone(controller.experience_tracker.exp_10m_gain)
        self.assertAlmostEqual(
            controller.next_experience_10m_checkpoint_at,
            8.0 + EXPERIENCE_10M_CHECKPOINT_INTERVAL_SECONDS,
        )

    def test_level_up_recovery_does_not_skip_repeated_failed_experience_roi(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.experience_tracker.add_reading(0.0, 49_377_752, 98.0, confidence=0.98)
        controller.experience_ocr_executor = ImmediateExecutor()
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        image_signature = controller._experience_ocr_image_signature([[image]])
        controller.last_failed_experience_ocr_signature = image_signature

        controller._submit_experience_ocr_burst(35.0, [[image]], effective_now=35.0)

        self.assertTrue(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNotNone(controller.experience_ocr_job)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "讀取經驗樣本中")

    def test_level_up_recovery_does_not_skip_repeated_completed_experience_roi(self):
        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        controller = self.make_controller([])
        controller.experience_tracker = ExperienceEfficiencyTracker()
        controller.experience_tracker.add_reading(0.0, 49_377_752, 80.0, confidence=0.98)
        controller.experience_ocr_executor = ImmediateExecutor()
        image = np.zeros((18, 140, 4), dtype=np.uint8)
        image_signature = controller._experience_ocr_image_signature([[image]])
        controller.last_completed_experience_ocr_signature = image_signature

        controller._submit_experience_ocr_burst(35.0, [[image]], effective_now=35.0)

        self.assertTrue(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNotNone(controller.experience_ocr_job)
        snapshot = controller.gui.set_experience_snapshot.call_args.args[0]
        self.assertEqual(snapshot.status, "讀取經驗樣本中")

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

    def test_experience_ocr_does_not_use_missing_percent_marker_as_initial_baseline(self):
        class DoneFuture:
            def done(self):
                return True

            def result(self):
                return ExperienceTextReading(
                    current_exp=31031512,
                    percent=76.71,
                    text="31031512[76.71]",
                    confidence=0.92,
                    success=True,
                    needs_bar_percent_guard=True,
                    source="paddle",
                    reason="OK",
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

        class ImmediateExecutor:
            def submit(self, fn, *args, **kwargs):
                self.call = (fn, args, kwargs)
                return Mock()

        changed = np.zeros((18, 140, 4), dtype=np.uint8)
        changed[:, :, 3] = 255
        changed[5:12, 30:70, :3] = 255
        controller.experience_ocr_job = None
        controller.experience_ocr_burst = None
        controller.next_experience_capture_at = 0.0
        controller.experience_reader = Mock()
        controller.experience_ocr_executor = ImmediateExecutor()
        controller._experience_text_region = Mock(return_value=(10, 20, 140, 18))
        controller.sct = Mock()
        controller.sct.grab.return_value = changed

        controller._update_experience_efficiency(9.0)

        self.assertFalse(hasattr(controller.experience_ocr_executor, "call"))
        self.assertIsNotNone(controller.experience_ocr_burst)
        self.assertEqual(controller.experience_ocr_burst.capture_count, 1)

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
            patch("maple_star.controllers.auto_potion_controller.log_experience_debug") as exp_debug_log,
        ):
            self.assertTrue(controller._process_experience_ocr_job(8.0))

        controller.experience_tracker.record_ocr_result.assert_called_once_with(True)
        self.assertEqual(controller.last_failed_experience_ocr_signature, image_signature)
        printed = "\n".join(call.args[0] for call in print_mock.call_args_list)
        self.assertIn("經驗效率 異常樣本拒絕", printed)
        self.assertNotIn("EXP OCR learning case:", printed)
        self.assertIn("288900[27.08%]", printed)
        self.assertIn("exp=288,900", printed)
        self.assertIn("percent=27.08%", printed)
        payload = exp_debug_log.call_args.args[0]
        self.assertEqual(payload["decision"], "rejected")
        self.assertEqual(payload["text"], "288900[27.08%]")
        self.assertEqual(payload["current_exp"], 288900)
        self.assertEqual(payload["percent"], 27.08)
        self.assertEqual(payload["tracker_status"], "樣本拒絕：EXP 跳動與百分比不一致")
        self.assertEqual(payload["learning_case_id"], "")

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

    def test_bottom_hud_layout_uses_hp_mp_exp_labels_across_scales(self):
        controller = self.make_controller([])
        for scale in (0.80, 1.0, 1.25):
            with self.subTest(scale=scale):
                image, search_area, text_right = self.build_synthetic_bottom_hud(controller, scale=scale)
                layout = controller._bottom_hud_layout_from_labels(
                    image,
                    hp_mask=controller._bar_color_mask(image, "hp"),
                    mp_mask=controller._bar_color_mask(image, "mp"),
                    exp_mask=controller._bar_color_mask(image, "exp"),
                    search_area=search_area,
                )

                self.assertIsNotNone(layout)
                assert layout is not None
                self.assertGreaterEqual(layout.confidence, 0.42)
                self.assertLess(layout.hp_region[0], layout.mp_region[0])
                self.assertLess(layout.exp_label_rect[0], layout.exp_bar_region[0])
                self.assertLess(layout.exp_label_rect[1], layout.exp_bar_region[1] + layout.exp_bar_region[3])
                self.assertGreaterEqual(layout.exp_text_region[0] + layout.exp_text_region[2], text_right)

    def test_bottom_hud_layout_rejects_label_match_when_bar_color_guard_fails(self):
        controller = self.make_controller([])
        image, search_area, _text_right = self.build_synthetic_bottom_hud(controller, wrong_mp_color=True)

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNone(layout)

    def test_bottom_hud_layout_handles_low_hp_mp_fill_using_label_anchor(self):
        controller = self.make_controller([])
        image, search_area, _text_right = self.build_synthetic_bottom_hud(
            controller,
            hp_fill=0.05,
            mp_fill=0.06,
        )

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertGreater(layout.hp_track_region[2], 100)
        self.assertGreater(layout.mp_track_region[2], 100)

    def test_bottom_hud_layout_uses_actual_hp_mp_track_width_for_percent(self):
        controller = self.make_controller([])
        image, search_area, _text_right = self.build_synthetic_bottom_hud(
            controller,
            hp_fill=0.37,
            mp_fill=0.64,
        )

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertAlmostEqual(layout.hp_track_region[2], 230, delta=3)
        self.assertAlmostEqual(layout.mp_track_region[2], 230, delta=3)

        self.attach_synthetic_grab(controller, image)
        hp_percent, hp_reason, _hp_tail = controller._bar_percent_from_region_snapshot(
            layout.hp_region,
            "hp",
            track_region=layout.hp_track_region,
        )
        mp_percent, mp_reason, _mp_tail = controller._bar_percent_from_region_snapshot(
            layout.mp_region,
            "mp",
            track_region=layout.mp_track_region,
        )

        self.assertEqual(hp_reason, "OK")
        self.assertEqual(mp_reason, "OK")
        self.assertAlmostEqual(hp_percent, 37.0, delta=1.0)
        self.assertAlmostEqual(mp_percent, 64.0, delta=1.0)

    def test_bottom_hud_layout_caps_hp_track_before_mp_label(self):
        controller = self.make_controller([])
        image, search_area, _text_right = self.build_synthetic_bottom_hud(
            controller,
            neutral_hp_mp_gap=True,
        )

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertAlmostEqual(layout.hp_track_region[2], 230, delta=3)
        self.assertLess(layout.hp_track_region[0] + layout.hp_track_region[2], layout.mp_label_rect[0])

    def test_bottom_hud_layout_uses_full_track_height_when_color_body_is_inset(self):
        controller = self.make_controller([])
        image, search_area, text_right = self.build_synthetic_bottom_hud(
            controller,
            bar_body_vertical_inset=4,
        )

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertGreaterEqual(layout.hp_track_region[3], 14)
        self.assertGreaterEqual(layout.mp_track_region[3], 14)
        self.assertGreaterEqual(layout.exp_track_region[3], 14)
        self.assertGreaterEqual(layout.hp_region[3], 18)
        self.assertGreaterEqual(layout.mp_region[3], 18)
        self.assertLessEqual(layout.hp_region[1] + layout.hp_region[3], layout.exp_bar_region[1])
        self.assertLessEqual(layout.mp_region[1] + layout.mp_region[3], layout.exp_bar_region[1])
        self.assertGreaterEqual(layout.exp_text_region[0] + layout.exp_text_region[2], text_right)

    def test_bottom_hud_layout_exp_track_keeps_yellow_green_gradient_top(self):
        controller = self.make_controller([])
        image, search_area, text_right = self.build_synthetic_bottom_hud(
            controller,
            exp_yellow_green_top=True,
        )

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertGreaterEqual(layout.exp_track_region[3], 14)
        self.assertGreaterEqual(layout.exp_text_region[1], layout.exp_bar_region[1] - 12)
        self.assertGreaterEqual(
            layout.exp_text_region[0],
            layout.exp_track_region[0] + round(layout.exp_track_region[2] * 0.35),
        )
        self.assertLess(layout.exp_text_region[2], round(layout.exp_bar_region[2] * 0.55))
        self.assertGreaterEqual(layout.exp_text_region[0] + layout.exp_text_region[2], text_right)

    def test_bottom_hud_layout_exp_text_roi_ignores_bright_track_dividers(self):
        controller = self.make_controller([])
        image, search_area, text_right = self.build_synthetic_bottom_hud(
            controller,
            exp_bright_dividers=True,
        )

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertGreaterEqual(layout.exp_text_region[0] + layout.exp_text_region[2], text_right)
        self.assertLess(layout.exp_text_region[2], round(layout.exp_bar_region[2] * 0.55))

    def test_bottom_hud_layout_exp_text_roi_does_not_include_full_green_bar_band(self):
        controller = self.make_controller([])
        image, search_area, text_right = self.build_synthetic_bottom_hud(controller)

        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )

        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertGreaterEqual(layout.exp_text_region[0] + layout.exp_text_region[2], text_right)
        text_bottom = layout.exp_text_region[1] + layout.exp_text_region[3]
        track_bottom = layout.exp_track_region[1] + layout.exp_track_region[3]
        self.assertLessEqual(text_bottom, track_bottom + max(2, round(layout.exp_track_region[3] * 0.25)))
        left, top, width, height = layout.exp_text_region
        text_crop = image[top : top + height, left : left + width, :3]
        bar_left, bar_top, bar_width, bar_height = layout.exp_bar_region
        bar_crop = image[bar_top : bar_top + bar_height, bar_left : bar_left + bar_width, :3]
        self.assertLess(
            float(controller._bar_color_mask(text_crop, "exp").mean()),
            float(controller._bar_color_mask(bar_crop, "exp").mean()),
        )

    def test_experience_text_regions_prefers_label_driven_exp_roi(self):
        controller = self.make_controller([])
        image, search_area, text_right = self.build_synthetic_bottom_hud(controller)
        layout = controller._bottom_hud_layout_from_labels(
            image,
            hp_mask=controller._bar_color_mask(image, "hp"),
            mp_mask=controller._bar_color_mask(image, "mp"),
            exp_mask=controller._bar_color_mask(image, "exp"),
            search_area=search_area,
        )
        self.assertIsNotNone(layout)
        assert layout is not None
        controller.bottom_hud_layout = layout
        controller.bottom_bar_regions = {
            "hp": layout.hp_region,
            "mp": layout.mp_region,
        }
        controller._foreground_client_bounds = Mock(return_value=(0, 0, 1920, 1080))

        regions = controller._experience_text_regions()

        self.assertEqual(regions[0], layout.exp_text_region)
        self.assertGreater(controller._experience_text_region_bar_crop_left_ratio(0), 0.30)
        self.assertGreaterEqual(regions[0][0] + regions[0][2], text_right)
        self.assertEqual(len(regions), 1)

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

    def test_bottom_bar_pair_infers_mp_region_when_low_mp_has_no_color_candidate(self):
        controller = self.make_controller([])

        regions = controller._bottom_bar_pair_regions_from_candidates(
            hp_candidates=[(183, 136, 250), (766, 104, 133)],
            mp_candidates=[],
            hp_mask=None,
            mp_mask=np.zeros((173, 1344), dtype=bool),
            search_left=307,
            search_top=907,
            search_width=1344,
            search_height=173,
            client_width=1920,
            client_height=1080,
        )

        self.assertEqual(set(regions), {"hp", "mp"})
        self.assertLess(regions["hp"][0], regions["mp"][0])
        self.assertGreaterEqual(regions["mp"][0], 760)
        self.assertLessEqual(regions["mp"][0], 820)
        self.assertIn("mp", controller.bottom_bar_track_regions)

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
