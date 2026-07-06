import unittest

import cv2
import numpy as np

from maple_star.services.minimap_cruise import (
    LEFT_DIRECTION_VK,
    MINIMAP_CRUISE_CONFIRM_TURN_INTERVAL_SECONDS,
    MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS,
    MINIMAP_CRUISE_STATIONARY_TURN_SECONDS,
    MINIMAP_CRUISE_TURN_AFTER_ATTACK_RELEASE_DELAY_SECONDS,
    MINIMAP_CRUISE_TURN_KEY_HOLD_SECONDS,
    MINIMAP_CRUISE_TURN_RESUME_ATTACK_DELAY_SECONDS,
    MINIMAP_CRUISE_STATUS_ATTACKING,
    MINIMAP_CRUISE_STATUS_TURNING,
    MinimapCruiseRuntime,
    detect_yellow_character_center_x,
)
from maple_star.models.settings import MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT
from maple_star.settings import AutoPotionSettings


class MinimapCruiseTests(unittest.TestCase):
    def make_runtime(self, character_positions: list[int | None]) -> tuple[MinimapCruiseRuntime, list[tuple[str, int]], list[str]]:
        settings = AutoPotionSettings(
            minimap_cruise_attack_key="C",
            minimap_cruise_left_x=100,
            minimap_cruise_right_x=200,
            minimap_cruise_detect_y=150,
            minimap_cruise_detect_band_height=12,
        )
        events: list[tuple[str, int]] = []
        statuses: list[str] = []
        remaining_positions = list(character_positions)

        def capture(monitor: dict[str, int]) -> np.ndarray:
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
            key_down_func=lambda vk: events.append(("down", vk)),
            key_up_func=lambda vk: events.append(("up", vk)),
            tap_key_func=lambda vk: events.append(("tap", vk)),
            parse_vk_key_func=lambda key: {"C": 0x43}[key],
        )
        return runtime, events, statuses

    def test_detect_yellow_character_center_x(self):
        image = np.zeros((15, 30, 4), dtype=np.uint8)
        image[6:9, 10:13] = (0, 204, 255, 255)

        self.assertEqual(detect_yellow_character_center_x(image), 11)

    def test_detect_yellow_character_center_x_accepts_minimap_marker_shape(self):
        image = np.zeros((40, 40, 4), dtype=np.uint8)
        cv2.circle(image, (20, 20), 6, (68, 221, 255, 255), thickness=-1)
        cv2.circle(image, (20, 20), 7, (40, 40, 40, 255), thickness=1)

        self.assertEqual(detect_yellow_character_center_x(image), 20)

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
        runtime, events, statuses = self.make_runtime([120])
        runtime.settings.minimap_cruise_left_x = None

        self.assertFalse(runtime.toggle(100.0))

        self.assertFalse(runtime.enabled)
        self.assertEqual(events, [])
        self.assertEqual(statuses[-1], "請先設定小地圖邊界")

    def test_initial_direction_uses_character_side_and_holds_attack(self):
        runtime, events, _statuses = self.make_runtime([120])

        self.assertTrue(runtime.toggle(100.0))
        runtime.update(100.0)

        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(events, [("down", 0x43)])

    def test_detection_runs_about_once_per_second(self):
        runtime, events, _statuses = self.make_runtime([120, 130])

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(100.5)
        runtime.update(101.0)

        self.assertEqual(runtime.last_detected_x, 130)
        self.assertAlmostEqual(runtime.next_detect_at, 101.0 + MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS)
        self.assertEqual(events, [("down", 0x43)])

    def test_stationary_character_turns_after_two_seconds_without_boundary_hit(self):
        runtime, events, _statuses = self.make_runtime([150, 150])

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

    def test_stationary_tracking_allows_small_x_jitter(self):
        runtime, events, _statuses = self.make_runtime([150, 151, 151])

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(101.0)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(events, [("down", 0x43)])

        runtime.update(102.0)

        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

    def test_stationary_tracking_resets_when_character_x_changes_beyond_tolerance(self):
        runtime, events, _statuses = self.make_runtime([150, 153, 153, 153])

        runtime.toggle(100.0)
        runtime.update(100.0)
        runtime.update(101.0)
        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(events, [("down", 0x43)])

        runtime.update(102.0)

        self.assertEqual(runtime.status, MINIMAP_CRUISE_STATUS_ATTACKING)
        self.assertEqual(runtime.turn_direction_vk, 0)
        self.assertEqual(runtime.stationary_x, 153)
        self.assertEqual(events, [("down", 0x43)])

        runtime.update(103.0)

        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(
            events,
            [
                ("down", 0x43),
                ("up", 0x43),
                ("down", LEFT_DIRECTION_VK),
            ],
        )

    def test_reaching_right_boundary_releases_attack_holds_left_before_resuming_attack(self):
        runtime, events, _statuses = self.make_runtime([199])
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

    def test_turn_retries_same_direction_when_character_remains_at_original_boundary(self):
        runtime, events, _statuses = self.make_runtime([199, 199])
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
        runtime, events, _statuses = self.make_runtime([280])
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
        runtime, events, _statuses = self.make_runtime([380])
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
        runtime, events, _statuses = self.make_runtime([20])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.last_detected_x, 20)
        self.assertEqual(runtime.current_direction, "right")
        self.assertEqual(runtime.turn_direction_vk, 0x27)
        self.assertEqual(events, [("up", 0x43), ("down", 0x27)])

    def test_character_beyond_right_boundary_retries_turn_even_when_already_facing_left(self):
        runtime, events, _statuses = self.make_runtime([280])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.current_direction = "left"
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.last_detected_x, 280)
        self.assertEqual(runtime.current_direction, "left")
        self.assertEqual(runtime.turn_direction_vk, LEFT_DIRECTION_VK)
        self.assertEqual(events, [("up", 0x43), ("down", LEFT_DIRECTION_VK)])

    def test_stop_during_turn_wait_clears_pending_direction_key(self):
        runtime, events, _statuses = self.make_runtime([199])
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
        runtime, events, _statuses = self.make_runtime([199])
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
        runtime, events, statuses = self.make_runtime([None])
        runtime.enabled = True
        runtime.status = MINIMAP_CRUISE_STATUS_ATTACKING
        runtime.attack_held_vk = 0x43

        runtime.update(100.0)

        self.assertEqual(runtime.attack_held_vk, 0)
        self.assertEqual(events, [("up", 0x43)])
        self.assertEqual(statuses[-1], "小地圖巡航：找不到角色點")


if __name__ == "__main__":
    unittest.main()
