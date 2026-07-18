import unittest
from unittest.mock import patch

import cv2
import numpy as np
from maple_star.services import minimap_cruise as minimap_cruise_module

from maple_star.services.minimap_cruise import (
    LEFT_DIRECTION_VK,
    MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS,
    MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS,
    MINIMAP_CRUISE_FOREGROUND_RESUME_DELAY_SECONDS,
    MINIMAP_CRUISE_LIE_DETECTOR_ALERT_INTERVAL_SECONDS,
    MINIMAP_CRUISE_PERIODIC_KEY_HOLD_SECONDS,
    MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS,
    MINIMAP_CRUISE_RED_PLAYER_ALERT_AFTER_SECONDS,
    MINIMAP_CRUISE_RED_PLAYER_ALERT_INTERVAL_SECONDS,
    MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS,
    MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS,
    MINIMAP_CRUISE_STATIONARY_TRACKING_DELAY_SECONDS,
    MINIMAP_CRUISE_STATIONARY_TURN_SECONDS,
    MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS,
    MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS,
    MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS,
    MINIMAP_CRUISE_STATUS_ATTACKING,
    MINIMAP_CRUISE_STATUS_LIE_DETECTOR,
    MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL,
    MINIMAP_CRUISE_STATUS_RECOVERING,
    MINIMAP_CRUISE_STATUS_STARTING,
    MINIMAP_CRUISE_STATUS_STATIONARY_SKILL,
    MINIMAP_CRUISE_STATUS_STOPPED,
    MINIMAP_CRUISE_STATUS_SUSPENDED,
    MINIMAP_CRUISE_STATUS_TURNING,
    RIGHT_DIRECTION_VK,
    MinimapCruiseRuntime,
    detect_lie_detector_bomb,
    detect_minimap_red_player_dot,
    detect_yellow_character_center_x,
    load_lie_detector_bomb_template,
)
from maple_star.models.settings import MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT
from maple_star.settings import AutoPotionSettings


class MinimapCruiseTests(unittest.TestCase):
    def make_runtime(
        self,
        character_positions: list[int | None],
        lie_detector_images: list[np.ndarray] | None = None,
        red_player_images: list[np.ndarray] | None = None,
    ) -> tuple[MinimapCruiseRuntime, list[tuple[str, int]], list[str], list[float]]:
        settings = AutoPotionSettings(
            minimap_cruise_attack_key="C",
            minimap_cruise_left_x=100,
            minimap_cruise_right_x=200,
            minimap_cruise_detect_y=150,
            minimap_cruise_detect_band_height=12,
        )
        events: list[tuple[str, int]] = []
        statuses: list[str] = []
        alerts: list[float] = []
        remaining_positions = list(character_positions)
        remaining_lie_detector_images = list(lie_detector_images or [])
        remaining_red_player_images = list(red_player_images or [])

        def capture(monitor: dict[str, int]) -> np.ndarray:
            if monitor["left"] == 10 and monitor["top"] == 20:
                if remaining_red_player_images:
                    return remaining_red_player_images.pop(0)
                return np.zeros((monitor["height"], monitor["width"], 4), dtype=np.uint8)
            if monitor["top"] < 100:
                if remaining_lie_detector_images:
                    return remaining_lie_detector_images.pop(0)
                return np.zeros((monitor["height"], monitor["width"], 4), dtype=np.uint8)
            image = np.zeros((monitor["height"], monitor["width"], 4), dtype=np.uint8)
            if not remaining_positions:
                return image
            character_x = remaining_positions.pop(0)
            if character_x is None:
                return image
            client_left = monitor["left"] - 10
            local_x = character_x - client_left
            if 1 <= local_x < monitor["width"] - 1:
                image[monitor["height"] // 2 - 1 : monitor["height"] // 2 + 2, local_x - 1 : local_x + 2] = (
                    0,
                    204,
                    255,
                    255,
                )
            return image

        runtime = MinimapCruiseRuntime(
            settings=settings,
            is_target_window_active=lambda: True,
            can_run_actions=lambda: True,
            is_action_blocked=lambda: False,
            target_client_bounds_provider=lambda: (10, 20, 400, 300),
            capture_provider=capture,
            set_status=statuses.append,
            lie_detector_alert_func=alerts.append,
            red_player_alert_func=alerts.append,
            key_down_func=lambda vk: events.append(("down", vk)),
            key_up_func=lambda vk: events.append(("up", vk)),
            tap_key_func=lambda vk: events.append(("tap", vk)),
            parse_vk_key_func=lambda key: {
                "A": 0x41,
                "B": 0x42,
                "C": 0x43,
                "D": 0x44,
                "E": 0x45,
                "V": 0x56,
            }[key],
        )
        return runtime, events, statuses, alerts

    def test_detect_yellow_character_center_x(self):
        image = np.zeros((15, 30, 4), dtype=np.uint8)
        image[6:9, 10:13] = (0, 204, 255, 255)

        self.assertEqual(detect_yellow_character_center_x(image), 11)

    def test_detect_yellow_character_center_x_accepts_minimap_marker_shape(self):
        image = np.zeros((40, 40, 4), dtype=np.uint8)
        cv2.circle(image, (20, 20), 6, (68, 221, 255, 255), thickness=-1)
        cv2.circle(image, (20, 20), 7, (40, 40, 40, 255), thickness=1)

        self.assertEqual(detect_yellow_character_center_x(image), 20)

    def test_detect_lie_detector_bomb_matches_template_patch(self):
        loaded = load_lie_detector_bomb_template()
        self.assertIsNotNone(loaded)
        template, mask = loaded
        image = np.zeros((180, 240, 4), dtype=np.uint8)
        top = 50
        left = 60
        height, width = template.shape[:2]
        image[top : top + height, left : left + width, :3] = template
        image[top : top + height, left : left + width, 3] = 255

        self.assertTrue(detect_lie_detector_bomb(image, template, mask))
        self.assertFalse(detect_lie_detector_bomb(np.zeros_like(image), template, mask))

    def test_default_lie_detector_scaled_templates_are_cached(self):
        loaded = load_lie_detector_bomb_template()
        self.assertIsNotNone(loaded)
        image = np.zeros((320, 512, 4), dtype=np.uint8)
        minimap_cruise_module._LIE_DETECTOR_BOMB_SCALED_TEMPLATES = None

        with patch.object(cv2, "resize", wraps=cv2.resize) as resize:
            detect_lie_detector_bomb(image)
            first_call_count = resize.call_count
            detect_lie_detector_bomb(image)

        self.assertGreater(first_call_count, 0)
        self.assertEqual(resize.call_count, first_call_count)

    def test_detect_minimap_red_player_dot(self):
        image = np.zeros((80, 120, 4), dtype=np.uint8)
        cv2.circle(image, (50, 35), 4, (0, 0, 230, 255), thickness=-1)

        self.assertTrue(detect_minimap_red_player_dot(image))
        self.assertFalse(detect_minimap_red_player_dot(np.zeros_like(image)))

        wide_red_ui = np.zeros_like(image)
        wide_red_ui[20:25, 10:70] = (0, 0, 230, 255)
        self.assertFalse(detect_minimap_red_player_dot(wide_red_ui))

    def test_runtime_uses_default_minimum_detect_band_height_for_saved_narrow_value(self):
        settings = AutoPotionSettings(
            minimap_cruise_attack_key="C",
            minimap_cruise_left_x=100,
            minimap_cruise_right_x=200,
            minimap_cruise_detect_y=150,
            minimap_cruise_detect_band_height=12,
        )
        captured_heights: list[int] = []

        def capture(monitor: dict[str, int]) -> np.ndarray:
            captured_heights.append(monitor["height"])
            image = np.zeros((monitor["height"], monitor["width"], 4), dtype=np.uint8)
            image[monitor["height"] // 2 - 1 : monitor["height"] // 2 + 2, 19:22] = (0, 204, 255, 255)
            return image

        runtime = MinimapCruiseRuntime(
            settings=settings,
            is_target_window_active=lambda: True,
            can_run_actions=lambda: True,
            is_action_blocked=lambda: False,
            target_client_bounds_provider=lambda: (10, 20, 400, 300),
            capture_provider=capture,
            key_down_func=lambda _vk: None,
            key_up_func=lambda _vk: None,
            tap_key_func=lambda _vk: None,
            parse_vk_key_func=lambda key: {"C": 0x43}[key],
        )

        runtime.toggle(100.0)
        runtime.update(100.0)

        self.assertGreaterEqual(captured_heights[-1], MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT)

    def test_toggle_requires_boundaries(self):
        runtime, events, statuses, _alerts = self.make_runtime([120])
        runtime.settings.minimap_cruise_left_x = None

        self.assertFalse(runtime.toggle(100.0))

        self.assertFalse(runtime.enabled)
        self.assertEqual(events, [])
        self.assertEqual(statuses[-1], "請先設定小地圖邊界")

    def test_toggle_rejects_periodic_key_that_conflicts_with_attack(self):
        runtime, events, statuses, _alerts = self.make_runtime([])
        runtime.settings.minimap_cruise_periodic_key_1_enabled = True
        runtime.settings.minimap_cruise_periodic_key_1 = "C"

        self.assertFalse(runtime.toggle(100.0))

        self.assertEqual(events, [])
        self.assertIn("衝突", statuses[-1])

    def test_toggle_rejects_boundary_narrower_than_twenty_pixels(self):
        runtime, events, statuses, _alerts = self.make_runtime([])
        runtime.settings.minimap_cruise_right_x = 119

        self.assertFalse(runtime.toggle(100.0))

        self.assertEqual(events, [])
        self.assertIn("20 px", statuses[-1])

    def test_apply_settings_restarts_enabled_runtime_without_old_pending_key(self):
        runtime, events, _statuses, _alerts = self.make_runtime([])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43
        runtime.periodic_key_pending_taps[1] = (0x56, 101.0, 10.0)
        candidate = AutoPotionSettings(
            minimap_cruise_attack_key="A",
            minimap_cruise_left_x=100,
            minimap_cruise_right_x=200,
            minimap_cruise_detect_y=150,
        )

        self.assertTrue(runtime.apply_settings(candidate, 100.0))

        self.assertIs(runtime.settings, candidate)
        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.periodic_key_pending_taps, {})
        self.assertEqual(events, [("up", 0x43)])

    def test_target_update_resumes_only_after_old_key_release_succeeds(self):
        runtime, events, _statuses, _alerts = self.make_runtime([])
        attempts = 0

        def release(vk: int) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("send failed")
            events.append(("up", vk))

        runtime.key_up_func = release
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43

        runtime.prepare_target_window_update(100.0)

        self.assertFalse(runtime.enabled)
        self.assertTrue(runtime.resume_after_target_update)
        runtime.update(100.049)
        self.assertFalse(runtime.enabled)
        runtime.update(100.05)

        self.assertTrue(runtime.enabled)
        self.assertFalse(runtime.resume_after_target_update)
        self.assertEqual(events, [("up", 0x43)])

    def test_initial_direction_uses_character_side_and_holds_attack(self):
        runtime, events, _statuses, _alerts = self.make_runtime([120])

        self.assertTrue(runtime.toggle(100.0))
        runtime.update(100.0)

        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(events, [("down", 0x43)])

    def test_detection_runs_at_configured_interval(self):
        runtime, events, _statuses, _alerts = self.make_runtime([120, 130])

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.1)
        runtime.update(100.2)

        self.assertEqual(runtime.last_detected_x, 130)
        self.assertAlmostEqual(runtime.next_detect_at, 100.2 + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS)
        self.assertEqual(events, [("down", 0x43)])

    def test_periodic_keys_are_spaced_when_due_at_the_same_time(self):
        runtime, events, _statuses, _alerts = self.make_runtime([120, 124, 128, 132, 136, 140])
        runtime.settings.minimap_cruise_periodic_key_1_enabled = True
        runtime.settings.minimap_cruise_periodic_key_1 = "V"
        runtime.settings.minimap_cruise_periodic_key_1_interval_seconds = 10.0
        runtime.settings.minimap_cruise_periodic_key_2_enabled = True
        runtime.settings.minimap_cruise_periodic_key_2 = "A"
        runtime.settings.minimap_cruise_periodic_key_2_interval_seconds = 10.0
        runtime.settings.minimap_cruise_periodic_key_3_enabled = True
        runtime.settings.minimap_cruise_periodic_key_3 = "B"
        runtime.settings.minimap_cruise_periodic_key_3_interval_seconds = 10.0
        runtime.settings.minimap_cruise_periodic_key_4_enabled = True
        runtime.settings.minimap_cruise_periodic_key_4 = "D"
        runtime.settings.minimap_cruise_periodic_key_4_interval_seconds = 10.0
        runtime.settings.minimap_cruise_periodic_key_5_enabled = True
        runtime.settings.minimap_cruise_periodic_key_5 = "E"
        runtime.settings.minimap_cruise_periodic_key_5_interval_seconds = 10.0

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(110.0)
        runtime.update(111.0)
        runtime.update(112.0)
        runtime.update(113.0)
        runtime.update(114.0)
        runtime.update(114.0 + MINIMAP_CRUISE_PERIODIC_KEY_HOLD_SECONDS)

        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("down", 0x56), ("up", 0x56),
                ("down", 0x41), ("up", 0x41),
                ("down", 0x42), ("up", 0x42),
                ("down", 0x44), ("up", 0x44),
                ("down", 0x45), ("up", 0x45),
            ],
        )

    def test_periodic_keys_resume_without_backlog_after_suspend(self):
        runtime, events, _statuses, _alerts = self.make_runtime([120, 124, 128])
        runtime.settings.minimap_cruise_periodic_key_1_enabled = True
        runtime.settings.minimap_cruise_periodic_key_1 = "V"
        runtime.settings.minimap_cruise_periodic_key_1_interval_seconds = 1.0

        runtime.toggle(100.0)
        runtime.can_run_actions = lambda: False
        runtime.update(101.0)

        runtime.can_run_actions = lambda: True
        runtime.update(102.0)
        runtime.update(103.0)
        runtime.update(103.0 + MINIMAP_CRUISE_PERIODIC_KEY_HOLD_SECONDS)

        self.assertEqual(events, [("down", 0x56), ("down", 0x43), ("up", 0x56)])
        self.assertEqual(runtime.periodic_key_next_at[1], 104.0)

    def test_periodic_key_countdown_continues_while_target_is_not_foreground(self):
        target_active = True
        runtime, events, _statuses, _alerts = self.make_runtime([120, 124])
        runtime.is_target_window_active = lambda: target_active
        runtime.settings.minimap_cruise_periodic_key_1_enabled = True
        runtime.settings.minimap_cruise_periodic_key_1 = "V"
        runtime.settings.minimap_cruise_periodic_key_1_interval_seconds = 1.0

        runtime.toggle(100.0)
        runtime.update(100.0)
        target_active = False
        runtime.update(101.0)

        self.assertEqual(events, [("down", 0x43), ("up", 0x43)])
        self.assertEqual(runtime.periodic_key_next_at[1], 101.0)

        target_active = True
        runtime.update(102.0)

        self.assertEqual(events, [("down", 0x43), ("up", 0x43)])
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)

        resume_at = 102.0 + MINIMAP_CRUISE_FOREGROUND_RESUME_DELAY_SECONDS
        runtime.update(resume_at - 0.001)

        self.assertEqual(events, [("down", 0x43), ("up", 0x43)])

        runtime.update(resume_at)
        runtime.update(resume_at + MINIMAP_CRUISE_PERIODIC_KEY_HOLD_SECONDS)

        self.assertEqual(events, [("down", 0x43), ("up", 0x43), ("down", 0x56), ("down", 0x43), ("up", 0x56)])

    def test_target_must_remain_foreground_for_full_resume_delay(self):
        target_active = True
        runtime, events, _statuses, _alerts = self.make_runtime([120, 124])
        runtime.toggle(100.0)
        runtime.update(100.0)

        target_active = False
        runtime.is_target_window_active = lambda: target_active
        runtime.update(101.0)

        target_active = True
        runtime.update(102.0)
        target_active = False
        runtime.update(102.1)
        target_active = True
        runtime.update(102.2)
        resume_at = 102.2 + MINIMAP_CRUISE_FOREGROUND_RESUME_DELAY_SECONDS
        runtime.update(resume_at - 0.001)

        self.assertEqual(events, [("down", 0x43), ("up", 0x43)])
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)

        runtime.update(resume_at)

        self.assertEqual(events, [("down", 0x43), ("up", 0x43), ("down", 0x43)])
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.stationary_started_at, resume_at)

    def test_periodic_keys_wait_while_potion_action_has_priority(self):
        defer_potion = True
        runtime, events, _statuses, _alerts = self.make_runtime([120, 124, 128])
        runtime.should_defer_periodic_keys = lambda _now: defer_potion
        runtime.settings.minimap_cruise_periodic_key_1_enabled = True
        runtime.settings.minimap_cruise_periodic_key_1 = "V"
        runtime.settings.minimap_cruise_periodic_key_1_interval_seconds = 1.0

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(101.0)

        self.assertEqual(events, [("down", 0x43)])
        self.assertIn(1, runtime.periodic_key_pending_taps)

        defer_potion = False
        runtime.update(102.0)
        runtime.update(102.0 + MINIMAP_CRUISE_PERIODIC_KEY_HOLD_SECONDS)

        self.assertEqual(events, [("down", 0x43), ("down", 0x56), ("up", 0x56)])

    def test_release_failure_retries_while_stopped_and_blocks_enable(self):
        runtime, events, _statuses, _alerts = self.make_runtime([])
        attempts = 0

        def release(vk: int) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("send failed")
            events.append(("up", vk))

        runtime.key_up_func = release
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43

        runtime.stop(now=100.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STOPPED)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(runtime.pending_release_vks, {0x43})
        self.assertFalse(runtime.toggle(100.01))

        runtime.update(100.049)
        self.assertEqual(attempts, 1)
        runtime.update(100.05)

        self.assertEqual(events, [("up", 0x43)])
        self.assertEqual(runtime.pending_release_vks, set())
        self.assertEqual(runtime.attack_held_vk, 0)

    def test_key_down_rechecks_foreground_at_send_boundary(self):
        runtime, events, _statuses, _alerts = self.make_runtime([])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_STARTING
        runtime.is_target_window_active = lambda: False

        self.assertFalse(runtime._hold_attack_key())

        self.assertEqual(events, [])
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)

    def test_stationary_character_turns_after_configured_delay_without_boundary_hit(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150])

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS)

        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(runtime.stationary_x, None)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

    def test_stationary_skill_resumes_attack_before_tracking_delay_ends(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150, 150, 150, 150, 150, 150])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"
        self.assertEqual(MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS, 0.2)
        self.assertEqual(MINIMAP_CRUISE_STATIONARY_TRACKING_DELAY_SECONDS, 0.5)

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        post_delay_ended_at = skill_ended_at + MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS
        tracking_delay_ended_at = skill_ended_at + MINIMAP_CRUISE_STATIONARY_TRACKING_DELAY_SECONDS
        runtime.update(skill_started_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(runtime.stationary_skill_held_vk, 0x56)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertIsNone(runtime.stationary_x)
        self.assertIsNone(runtime.stationary_started_at)
        self.assertEqual(events, [("down", 0x43), ("up", 0x43), ("down", 0x56)])

        runtime.update(skill_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(runtime.stationary_skill_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.stationary_skill_post_delay_until, post_delay_ended_at)
        self.assertEqual(runtime.stationary_tracking_delay_until, tracking_delay_ended_at)
        self.assertIsNone(runtime.stationary_x)
        self.assertIsNone(runtime.stationary_started_at)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", 0x56),
                ("up", 0x56),
            ],
        )

        runtime.update(post_delay_ended_at - 0.001)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertIsNone(runtime.stationary_x)
        self.assertIsNone(runtime.stationary_started_at)

        runtime.update(post_delay_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertIsNone(runtime.stationary_skill_post_delay_until)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertIsNone(runtime.stationary_x)
        self.assertIsNone(runtime.stationary_started_at)
        self.assertEqual(events[-1], ("down", 0x43))

        runtime.update(tracking_delay_ended_at - 0.001)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertIsNone(runtime.stationary_started_at)

        runtime.update(tracking_delay_ended_at)

        self.assertIsNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(runtime.stationary_x, 150)
        self.assertEqual(runtime.stationary_started_at, tracking_delay_ended_at)

        runtime.update(tracking_delay_ended_at + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS - 0.001)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.turn_direction_vk, 0)

    def test_stationary_skill_completes_hold_and_delays_right_boundary_turn(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150, 205, 205])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        post_delay_ended_at = skill_ended_at + MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_started_at + 0.1)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(runtime.stationary_skill_held_vk, 0x56)
        self.assertEqual(events, [("down", 0x43), ("up", 0x43), ("down", 0x56)])

        runtime.update(skill_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(runtime.stationary_skill_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertEqual(events[-1], ("up", 0x56))

        runtime.update(post_delay_ended_at - 0.001)

        self.assertEqual(runtime.turn_direction_vk, 0)

        runtime.update(post_delay_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", 0x56),
                ("up", 0x56),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

    def test_stationary_skill_delays_left_boundary_turn(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150, 95, 95])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        post_delay_ended_at = skill_ended_at + MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(runtime.turn_direction_vk, 0)

        runtime.update(post_delay_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_direction_vk, RIGHT_DIRECTION_VK)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", 0x56),
                ("up", 0x56),
                ("down", RIGHT_DIRECTION_VK),
            ],
        )

    def test_stationary_skill_uses_post_delay_position_when_moving_out_of_bounds(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150, 150, 205])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_ended_at)

        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events[-1], ("up", 0x56))

        runtime.update(skill_ended_at + MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertIsNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(events[-2:], [("up", 0x56), ("down", LEFT_DIRECTION_VK)])

    def test_stationary_skill_uses_post_delay_position_when_returning_in_bounds(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150, 205, 190, 190])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        post_delay_ended_at = skill_ended_at + MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS
        tracking_delay_ended_at = skill_ended_at + MINIMAP_CRUISE_STATIONARY_TRACKING_DELAY_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_ended_at)

        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_direction_vk, 0)

        runtime.update(post_delay_ended_at)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertIsNone(runtime.stationary_x)
        self.assertIsNone(runtime.stationary_started_at)
        self.assertEqual(events[-1], ("down", 0x43))

        runtime.update(tracking_delay_ended_at)

        self.assertEqual(runtime.stationary_x, 190)
        self.assertEqual(runtime.stationary_started_at, tracking_delay_ended_at)

    def test_stationary_skill_suspends_when_release_position_is_missing(self):
        runtime, events, statuses, _alerts = self.make_runtime([150, 150, None])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.stationary_skill_held_vk, 0)
        self.assertIsNone(runtime.stationary_skill_post_delay_until)
        self.assertEqual(statuses[-1], "小地圖巡航：找不到角色點")
        self.assertEqual(events[-1], ("up", 0x56))

    def test_stationary_skill_suspends_when_post_delay_position_is_missing(self):
        runtime, events, statuses, _alerts = self.make_runtime([150, 150, 150, None])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_ended_at)
        runtime.update(skill_ended_at + MINIMAP_CRUISE_STATIONARY_SKILL_POST_DELAY_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertIsNone(runtime.stationary_skill_post_delay_until)
        self.assertIsNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(statuses[-1], "小地圖巡航：找不到角色點")
        self.assertEqual(events[-2:], [("down", 0x56), ("up", 0x56)])

    def test_stop_during_stationary_skill_post_delay_clears_deadline(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 150, 150])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS)

        self.assertIsNotNone(runtime.stationary_skill_post_delay_until)
        self.assertIsNotNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(runtime.attack_held_vk, 0)

        runtime.stop()

        self.assertIsNone(runtime.stationary_skill_post_delay_until)
        self.assertIsNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events[-1], ("up", 0x56))

    def test_lie_detector_during_stationary_skill_post_delay_clears_deadline(self):
        loaded = load_lie_detector_bomb_template()
        self.assertIsNotNone(loaded)
        template, _mask = loaded
        blank_lie_image = np.zeros((160, 200, 4), dtype=np.uint8)
        lie_image = blank_lie_image.copy()
        height, width = template.shape[:2]
        lie_image[35 : 35 + height, 40 : 40 + width, :3] = template
        lie_image[35 : 35 + height, 40 : 40 + width, 3] = 255
        runtime, events, _statuses, alerts = self.make_runtime(
            [150, 150, 150],
            [blank_lie_image.copy(), blank_lie_image.copy(), blank_lie_image.copy(), lie_image],
        )
        runtime.settings.minimap_cruise_stationary_skill_key = "V"

        runtime.toggle(100.0)
        runtime.update(100.0)
        skill_started_at = 100.0 + MINIMAP_CRUISE_STATIONARY_TURN_SECONDS
        skill_ended_at = skill_started_at + MINIMAP_CRUISE_STATIONARY_SKILL_HOLD_SECONDS
        runtime.update(skill_started_at)
        runtime.update(skill_ended_at)

        self.assertIsNotNone(runtime.stationary_skill_post_delay_until)
        self.assertIsNotNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(runtime.attack_held_vk, 0)

        alert_at = skill_ended_at + 0.1
        runtime.next_lie_detector_check_at = alert_at
        runtime.update(alert_at)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_LIE_DETECTOR)
        self.assertIsNone(runtime.stationary_skill_post_delay_until)
        self.assertIsNone(runtime.stationary_tracking_delay_until)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events[-1], ("up", 0x56))
        self.assertEqual(alerts, [alert_at])

    def test_stationary_tracking_uses_skill_when_forward_progress_does_not_exceed_threshold(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 151, 153])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"
        runtime.settings.minimap_cruise_stationary_min_forward_pixels = 3

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.2)
        runtime.update(101.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", 0x56),
            ],
        )

    def test_stationary_tracking_restarts_after_forward_progress_exceeds_threshold(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 151, 154, 154, 154])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"
        runtime.settings.minimap_cruise_stationary_min_forward_pixels = 3

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.2)
        runtime.update(101.0)
        runtime.update(101.999)

        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.stationary_started_at, 101.0)
        self.assertEqual(events, [("down", 0x43)])

        runtime.update(102.2)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(events[-2:], [("up", 0x43), ("down", 0x56)])

    def test_stationary_tracking_rightward_knockback_resets_timer(self):
        runtime, events, _statuses, _alerts = self.make_runtime([150, 152, 150, 150, 150])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"
        runtime.settings.minimap_cruise_stationary_min_forward_pixels = 3

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.2)
        runtime.update(100.4)
        runtime.update(101.0)

        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.stationary_started_at, 100.4)
        self.assertEqual(events, [("down", 0x43)])

        runtime.update(101.4)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(events[-2:], [("up", 0x43), ("down", 0x56)])

    def test_stationary_tracking_leftward_knockback_resets_timer(self):
        runtime, events, _statuses, _alerts = self.make_runtime([160, 158, 160, 160, 160])
        runtime.settings.minimap_cruise_stationary_skill_key = "V"
        runtime.settings.minimap_cruise_stationary_min_forward_pixels = 3

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.2)
        runtime.update(100.4)
        runtime.update(101.0)

        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.stationary_started_at, 100.4)
        self.assertEqual(events, [("down", 0x43)])

        runtime.update(101.4)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STATIONARY_SKILL)
        self.assertEqual(events[-2:], [("up", 0x43), ("down", 0x56)])

    def test_reaching_right_boundary_releases_attack_holds_left_before_resuming_attack(self):
        runtime, events, _statuses, _alerts = self.make_runtime([199])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(runtime.turn_held_vk, LEFT_DIRECTION_VK)
        self.assertEqual(
            events,
            [
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

        runtime.update(100.0 + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS - 0.001)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])
        self.assertEqual(runtime.turn_held_vk, LEFT_DIRECTION_VK)

        turn_down_at = 100.0

        runtime.update(turn_down_at + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS)
        self.assertEqual(events[-2], ("up", LEFT_DIRECTION_VK))
        self.assertEqual(events[-1], ("down", 0x43))
        self.assertEqual(runtime.turn_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(
            events,
            [
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
                ("up", LEFT_DIRECTION_VK),
                ("down", 0x43),
            ],
        )
        self.assertAlmostEqual(
            runtime.next_detect_at,
            turn_down_at
            + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS
            + MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS
            + MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS,
        )

    def test_pre_boundary_skill_keeps_attack_held_holds_skill_then_continues_attack(self):
        runtime, events, _statuses, _alerts = self.make_runtime([186, 186, 186])
        runtime.settings.minimap_cruise_pre_boundary_skill_enabled = True
        runtime.settings.minimap_cruise_pre_boundary_skill_key = "V"
        runtime.settings.minimap_cruise_pre_boundary_distance = 15
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(runtime.pre_boundary_skill_held_vk, 0x56)
        self.assertEqual(events, [("down", 0x56)])

        runtime.update(100.0 + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS - 0.001)
        self.assertEqual(events, [("down", 0x56)])

        runtime.update(100.0 + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.pre_boundary_skill_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [("down", 0x56), ("up", 0x56)])

    def test_pre_boundary_skill_turns_immediately_if_dash_ends_outside_boundary(self):
        runtime, events, _statuses, _alerts = self.make_runtime([186, 230])
        runtime.settings.minimap_cruise_pre_boundary_skill_enabled = True
        runtime.settings.minimap_cruise_pre_boundary_skill_key = "V"
        runtime.settings.minimap_cruise_pre_boundary_distance = 15
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.update(100.0 + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_held_vk, LEFT_DIRECTION_VK)
        self.assertEqual(
            events,
            [
                ("down", 0x56),
                ("up", 0x56),
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

    def test_pre_boundary_skill_holds_full_duration_before_turning_after_left_dash(self):
        runtime, events, _statuses, _alerts = self.make_runtime([114, 80, 80])
        runtime.settings.minimap_cruise_pre_boundary_skill_enabled = True
        runtime.settings.minimap_cruise_pre_boundary_skill_key = "V"
        runtime.settings.minimap_cruise_pre_boundary_distance = 15
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.update(101.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(runtime.pre_boundary_skill_held_vk, 0x56)
        self.assertEqual(events, [("down", 0x56)])

        runtime.update(100.0 + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(runtime.turn_held_vk, 0x27)
        self.assertEqual(
            events,
            [
                ("down", 0x56),
                ("up", 0x56),
                ("up", 0x43),
                ("down", 0x27),
            ],
        )

    def test_pre_boundary_skill_suspends_when_marker_disappears_at_release(self):
        runtime, events, _statuses, _alerts = self.make_runtime([114, 114, None])
        runtime.settings.minimap_cruise_pre_boundary_skill_enabled = True
        runtime.settings.minimap_cruise_pre_boundary_skill_key = "V"
        runtime.settings.minimap_cruise_pre_boundary_distance = 15
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.update(101.0)
        runtime.update(100.0 + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)
        self.assertEqual(runtime.turn_held_vk, 0)
        self.assertEqual(
            events,
            [
                ("down", 0x56),
                ("up", 0x56),
                ("up", 0x43),
            ],
        )

    def test_pre_boundary_skill_triggers_anywhere_between_configured_distance_and_boundary(self):
        runtime, events, _statuses, _alerts = self.make_runtime([199])
        runtime.settings.minimap_cruise_pre_boundary_skill_enabled = True
        runtime.settings.minimap_cruise_pre_boundary_skill_key = "V"
        runtime.settings.minimap_cruise_pre_boundary_distance = 15
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(runtime.pre_boundary_skill_held_vk, 0x56)
        self.assertEqual(runtime.turn_held_vk, 0)
        self.assertEqual(events, [("down", 0x56)])

    def test_pre_boundary_skill_triggers_once_until_character_leaves_trigger_zone(self):
        runtime, events, _statuses, _alerts = self.make_runtime([186, 189, 160, 186])
        runtime.settings.minimap_cruise_pre_boundary_skill_enabled = True
        runtime.settings.minimap_cruise_pre_boundary_skill_key = "V"
        runtime.settings.minimap_cruise_pre_boundary_distance = 15
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        first_skill_done_at = 100.0 + MINIMAP_CRUISE_PRE_BOUNDARY_SKILL_HOLD_SECONDS
        runtime.update(first_skill_done_at)
        runtime.update(first_skill_done_at + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS)
        runtime.update(first_skill_done_at + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS * 2)
        runtime.update(first_skill_done_at + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS * 3)

        self.assertEqual(
            events,
            [
                ("down", 0x56),
                ("up", 0x56),
                ("down", 0x56),
            ],
        )
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_PRE_BOUNDARY_SKILL)
        self.assertEqual(runtime.pre_boundary_skill_held_vk, 0x56)

    def test_turn_retries_same_direction_when_character_remains_at_original_boundary(self):
        runtime, events, _statuses, _alerts = self.make_runtime([199, 199])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        first_turn_down_at = 100.0
        runtime.update(first_turn_down_at + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS)
        first_resume_at = (
            first_turn_down_at
            + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS
            + MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS
        )
        runtime.update(first_resume_at)

        runtime.update(first_resume_at + MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS)

        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_confirmation_boundary, "right")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(
            events,
            [
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
                ("up", LEFT_DIRECTION_VK),
                ("down", 0x43),
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

        self.assertEqual(events[-1], ("down", LEFT_DIRECTION_VK))

    def test_character_far_beyond_right_boundary_is_detected_and_turns_left(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.last_detected_x, 280)
        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

    def test_character_farther_beyond_right_boundary_stays_in_capture_region(self):
        runtime, events, _statuses, _alerts = self.make_runtime([380])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.last_detected_x, 380)
        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

    def test_character_far_beyond_left_boundary_is_detected_and_turns_right(self):
        runtime, events, _statuses, _alerts = self.make_runtime([20])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.last_detected_x, 20)
        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.turn_direction_vk, 0x27)
        self.assertEqual(events, [("up", 0x43), ("down", 0x27)])

    def test_character_beyond_right_boundary_turns_even_when_already_facing_left(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.last_detected_x, 280)
        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_TURNING)
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

    def test_character_beyond_right_boundary_recovers_after_turn_if_still_outside(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280, 280])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.update(100.0 + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS)
        runtime.update(100.0 + MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS + MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_boundary, "right")
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(
            events,
            [
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
                ("up", LEFT_DIRECTION_VK),
                ("down", 0x43),
            ],
        )

    def test_out_of_bounds_recovery_keeps_attack_while_moving_inward(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280, 260])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "right"

        runtime.update(100.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_boundary, "right")
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [])

        runtime.update(101.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [])

    def test_out_of_bounds_recovery_releases_attack_and_holds_direction_when_not_moving_inward(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280, 280])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "right"
        runtime.recovery_last_x = 280

        runtime.update(100.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [])

        runtime.update(101.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_held_vk, LEFT_DIRECTION_VK)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

    def test_out_of_bounds_recovery_oscillation_does_not_reset_best_progress(self):
        runtime, events, _statuses, _alerts = self.make_runtime([279, 280, 279])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "right"
        runtime.recovery_last_x = 280

        runtime.update(100.0)
        runtime.update(101.0)
        runtime.update(102.0)

        self.assertEqual(runtime.recovery_last_x, 279)
        self.assertEqual(runtime.recovery_held_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

    def test_left_out_of_bounds_recovery_releases_attack_and_holds_inward_direction_when_stuck(self):
        runtime, events, _statuses, _alerts = self.make_runtime([80, 80])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "left"
        runtime.recovery_last_x = 80

        runtime.update(100.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_boundary, "left")
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [])

        runtime.update(101.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_boundary, "left")
        self.assertEqual(runtime.recovery_held_vk, RIGHT_DIRECTION_VK)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events, [("up", 0x43), ("down", RIGHT_DIRECTION_VK)])

    def test_out_of_bounds_recovery_keeps_direction_until_back_inside_range(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280, 280, 280, 199])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "right"

        runtime.update(100.0)
        runtime.update(101.0)
        runtime.update(102.0)
        runtime.update(103.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK), ("up", LEFT_DIRECTION_VK), ("down", 0x43)])

    def test_out_of_bounds_recovery_does_not_finish_until_inside_strict_boundary(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280, 280, 280, 202, 200])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "right"

        runtime.update(100.0)
        runtime.update(101.0)
        runtime.update(102.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_held_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

        runtime.update(103.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_RECOVERING)
        self.assertEqual(runtime.recovery_held_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

        runtime.update(104.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK), ("up", LEFT_DIRECTION_VK), ("down", 0x43)])

    def test_out_of_bounds_recovery_keeps_attack_when_character_moves_inward(self):
        runtime, events, _statuses, _alerts = self.make_runtime([280, 260, 240, 199])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_RECOVERING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43
        runtime.recovery_boundary = "right"

        runtime.update(100.0)
        runtime.update(101.0)
        runtime.update(102.0)
        runtime.update(103.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.recovery_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0x43)
        self.assertEqual(events, [])

    def test_stop_during_turn_wait_clears_pending_direction_key(self):
        runtime, events, _statuses, _alerts = self.make_runtime([199])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.stop("小地圖巡航已停用")

        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertEqual(runtime.turn_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertIsNone(runtime.turn_key_down_at)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK), ("up", LEFT_DIRECTION_VK)])

    def test_stop_during_turn_hold_releases_direction_key(self):
        runtime, events, _statuses, _alerts = self.make_runtime([199])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "right"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.update(100.0 + MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS)
        runtime.stop("小地圖巡航已停用")

        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertEqual(runtime.turn_held_vk, 0)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(
            events,
            [
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
                ("up", LEFT_DIRECTION_VK),
            ],
        )

    def test_detection_failure_releases_attack_and_suspends(self):
        runtime, events, statuses, _alerts = self.make_runtime([None])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events, [("up", 0x43)])
        self.assertEqual(statuses[-1], "小地圖巡航：找不到角色點")

    def test_lie_detector_detection_pauses_and_auto_resumes_after_challenge_disappears(self):
        loaded = load_lie_detector_bomb_template()
        self.assertIsNotNone(loaded)
        template, _mask = loaded
        blank_image = np.zeros((160, 200, 4), dtype=np.uint8)
        lie_image = np.zeros((160, 200, 4), dtype=np.uint8)
        height, width = template.shape[:2]
        lie_image[35 : 35 + height, 40 : 40 + width, :3] = template
        lie_image[35 : 35 + height, 40 : 40 + width, 3] = 255
        runtime, events, statuses, alerts = self.make_runtime(
            [120],
            [lie_image, lie_image.copy(), lie_image.copy(), blank_image],
        )
        challenge_pause_states: list[bool] = []
        runtime.lie_detector_state_func = challenge_pause_states.append
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_LIE_DETECTOR)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events, [("up", 0x43)])
        self.assertEqual(statuses[-1], "小地圖巡航：偵測到測謊視窗")
        self.assertEqual(alerts, [100.0])
        self.assertEqual(runtime.status_text(), "巡航(測謊暫停)")
        self.assertEqual(challenge_pause_states, [True])

        runtime.update(100.5)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_LIE_DETECTOR)
        self.assertEqual(alerts, [100.0])

        runtime.update(100.0 + MINIMAP_CRUISE_LIE_DETECTOR_ALERT_INTERVAL_SECONDS)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_LIE_DETECTOR)
        self.assertEqual(alerts, [100.0, 101.0])

        runtime.update(101.5)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STARTING)
        self.assertEqual(statuses[-1], "小地圖巡航：測謊已完成，自動恢復")
        self.assertEqual(alerts, [100.0, 101.0])
        self.assertEqual(challenge_pause_states, [True, False])

        runtime.update(101.5)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(events, [("up", 0x43), ("down", 0x43)])
        self.assertEqual(alerts, [100.0, 101.0])

    def test_manual_stop_during_lie_detector_pause_prevents_auto_resume(self):
        loaded = load_lie_detector_bomb_template()
        self.assertIsNotNone(loaded)
        template, _mask = loaded
        blank_image = np.zeros((160, 200, 4), dtype=np.uint8)
        lie_image = np.zeros((160, 200, 4), dtype=np.uint8)
        height, width = template.shape[:2]
        lie_image[35 : 35 + height, 40 : 40 + width, :3] = template
        lie_image[35 : 35 + height, 40 : 40 + width, 3] = 255
        runtime, events, statuses, _alerts = self.make_runtime([120], [lie_image, blank_image])
        challenge_pause_states: list[bool] = []
        runtime.lie_detector_state_func = challenge_pause_states.append
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)
        runtime.stop("小地圖巡航已停用")
        runtime.update(101.0)

        self.assertFalse(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STOPPED)
        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events, [("up", 0x43)])
        self.assertEqual(statuses[-1], "小地圖巡航已停用")
        self.assertEqual(challenge_pause_states, [True, False])

    def test_lie_detector_pause_does_not_resume_when_challenge_state_is_unknown(self):
        runtime, events, statuses, alerts = self.make_runtime([120])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_LIE_DETECTOR
        runtime.lie_detector_challenge_active = True
        runtime.next_lie_detector_check_at = 100.0
        runtime.next_lie_detector_alert_at = 100.0
        runtime.target_client_bounds_provider = lambda: None

        runtime.update(100.0)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_LIE_DETECTOR)
        self.assertEqual(events, [])
        self.assertEqual(statuses, [])
        self.assertEqual(alerts, [100.0])

    def test_lie_detector_pause_can_finish_while_gameplay_hud_is_inactive(self):
        blank_image = np.zeros((160, 200, 4), dtype=np.uint8)
        runtime, _events, statuses, _alerts = self.make_runtime([120], [blank_image])
        challenge_pause_states: list[bool] = []
        runtime.lie_detector_state_func = challenge_pause_states.append
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_LIE_DETECTOR
        runtime.lie_detector_challenge_active = True
        runtime.can_run_actions = lambda: False
        runtime.next_lie_detector_check_at = 100.0

        runtime.update(100.0)

        self.assertFalse(runtime.lie_detector_challenge_active)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_STARTING)
        self.assertEqual(challenge_pause_states, [False])
        self.assertEqual(statuses[-1], "小地圖巡航：測謊已完成，自動恢復")

    def test_lie_detector_detection_releases_turn_key(self):
        loaded = load_lie_detector_bomb_template()
        self.assertIsNotNone(loaded)
        template, _mask = loaded
        lie_image = np.zeros((160, 200, 4), dtype=np.uint8)
        height, width = template.shape[:2]
        lie_image[35 : 35 + height, 40 : 40 + width, :3] = template
        lie_image[35 : 35 + height, 40 : 40 + width, 3] = 255
        runtime, events, _statuses, alerts = self.make_runtime([120], [lie_image])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_TURNING
        runtime.turn_direction_vk = LEFT_DIRECTION_VK
        runtime.turn_held_vk = LEFT_DIRECTION_VK

        runtime.update(100.0)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_LIE_DETECTOR)
        self.assertEqual(runtime.turn_held_vk, 0)
        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertEqual(events, [("up", LEFT_DIRECTION_VK)])
        self.assertEqual(alerts, [100.0])

    def test_red_player_dot_alerts_after_twenty_seconds_without_stopping_cruise(self):
        red_image = np.zeros((84, 96, 4), dtype=np.uint8)
        cv2.circle(red_image, (45, 45), 4, (0, 0, 230, 255), thickness=-1)
        runtime, events, statuses, alerts = self.make_runtime(
            [],
            red_player_images=[red_image.copy(), red_image.copy(), red_image.copy(), red_image.copy()],
        )
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.next_detect_at = 9999.0
        runtime.next_red_player_check_at = 100.0
        red_player_notices: list[float] = []
        runtime.red_player_detected_func = red_player_notices.append

        runtime.update(100.0)
        runtime.update(100.0 + MINIMAP_CRUISE_RED_PLAYER_ALERT_AFTER_SECONDS - 0.001)

        self.assertTrue(runtime.enabled)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(events, [])
        self.assertEqual(alerts, [])

        runtime.update(100.0 + MINIMAP_CRUISE_RED_PLAYER_ALERT_AFTER_SECONDS + 1.0)

        self.assertTrue(runtime.red_player_alert_active)
        self.assertEqual(statuses[-1], "小地圖巡航：其他玩家紅點超過 20 秒")
        self.assertEqual(alerts, [121.0])
        self.assertEqual(red_player_notices, [121.0])

        runtime.update(121.0 + MINIMAP_CRUISE_RED_PLAYER_ALERT_INTERVAL_SECONDS - 0.001)
        self.assertEqual(alerts, [121.0])

        runtime.update(121.0 + MINIMAP_CRUISE_RED_PLAYER_ALERT_INTERVAL_SECONDS)
        self.assertEqual(alerts, [121.0, 122.0])
        self.assertEqual(red_player_notices, [121.0])

    def test_red_player_dot_timer_resets_when_dot_disappears(self):
        red_image = np.zeros((84, 96, 4), dtype=np.uint8)
        cv2.circle(red_image, (45, 45), 4, (0, 0, 230, 255), thickness=-1)
        blank = np.zeros_like(red_image)
        runtime, _events, _statuses, alerts = self.make_runtime(
            [],
            red_player_images=[red_image.copy(), blank, red_image.copy()],
        )
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.next_detect_at = 9999.0
        runtime.next_red_player_check_at = 100.0

        runtime.update(100.0)
        runtime.update(110.0)
        runtime.update(130.0)

        self.assertFalse(runtime.red_player_alert_active)
        self.assertEqual(runtime.red_player_present_since, 130.0)

    def test_red_player_timer_resets_when_cruise_is_suspended(self):
        runtime, _events, _statuses, alerts = self.make_runtime([])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.red_player_present_since = 100.0
        runtime.can_run_actions = lambda: False

        runtime.update(110.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_SUSPENDED)
        self.assertIsNone(runtime.red_player_present_since)
        self.assertEqual(alerts, [])

    def test_red_player_notice_rearms_after_dot_disappears(self):
        red_image = np.zeros((84, 96, 4), dtype=np.uint8)
        cv2.circle(red_image, (45, 45), 4, (0, 0, 230, 255), thickness=-1)
        blank = np.zeros_like(red_image)
        runtime, _events, _statuses, alerts = self.make_runtime(
            [],
            red_player_images=[
                red_image.copy(),
                red_image.copy(),
                blank,
                red_image.copy(),
                red_image.copy(),
            ],
        )
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.next_detect_at = 9999.0
        runtime.next_red_player_check_at = 100.0
        red_player_notices: list[float] = []
        runtime.red_player_detected_func = red_player_notices.append

        runtime.update(100.0)
        runtime.update(121.0)
        runtime.update(122.0)
        runtime.update(130.0)
        runtime.update(151.0)

        self.assertTrue(runtime.red_player_alert_active)
        self.assertEqual(red_player_notices, [121.0, 151.0])
        self.assertEqual(alerts, [121.0, 151.0])


if __name__ == "__main__":
    unittest.main()
