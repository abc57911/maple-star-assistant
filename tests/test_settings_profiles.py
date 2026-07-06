import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maple_star.constants import (
    POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT,
    POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
    POTION_MIN_COOLDOWN_SECONDS,
)
from maple_star.settings import AutoPotionSettings, load_settings


class SettingsProfileTests(unittest.TestCase):
    def test_load_settings_migrates_flat_settings_to_default_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps({"hp_key": "9", "mp_key": "0", "rb_enabled": True}),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(settings.active_profile, "Default")
        self.assertEqual(settings.hp_key, "9")
        self.assertEqual(settings.mp_key, "0")
        self.assertTrue(settings.rb_enabled)
        self.assertEqual(settings.toggle_hotkey, "F11")
        self.assertEqual(settings.emergency_stop_hotkey, "Pause")
        self.assertEqual(settings.experience_toggle_hotkey, "F10")
        self.assertEqual(settings.experience_reset_hotkey, "F9")
        self.assertEqual(settings.character_stat_hotkey, "")
        self.assertIsNone(settings.pickup_toggle_hotkey)
        self.assertIsNone(settings.pickup_key)
        self.assertIsNone(settings.minimap_cruise_toggle_hotkey)
        self.assertEqual(settings.minimap_cruise_attack_key, "C")
        self.assertIsNone(settings.minimap_cruise_left_x)
        self.assertIsNone(settings.minimap_cruise_right_x)
        self.assertIsNone(settings.minimap_cruise_detect_y)
        self.assertEqual(settings.minimap_cruise_detect_band_height, 120)
        self.assertEqual(settings.minimap_cruise_last_direction, "right")
        self.assertFalse(settings.console_collapsed)
        self.assertFalse(settings.combo_group_collapsed)
        self.assertFalse(settings.compact_experience_mode)
        self.assertFalse(settings.window_topmost)
        self.assertFalse(settings.hp_continuous_enabled)
        self.assertFalse(settings.mp_continuous_enabled)
        self.assertEqual(settings.hp_continuous_stop_margin_percent, POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT)
        self.assertEqual(settings.mp_continuous_stop_margin_percent, POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT)
        self.assertIsNone(settings.full_panel_window_x)
        self.assertIsNone(settings.full_panel_window_y)
        self.assertIsNone(settings.compact_experience_window_x)
        self.assertIsNone(settings.compact_experience_window_y)
        self.assertIn("Default", saved["profiles"])
        self.assertEqual(saved["profiles"]["Default"]["hp_key"], "9")
        self.assertFalse(saved["profiles"]["Default"]["exp_efficiency_enabled"])
        self.assertFalse(saved["profiles"]["Default"]["hp_continuous_enabled"])
        self.assertFalse(saved["profiles"]["Default"]["mp_continuous_enabled"])
        self.assertEqual(
            saved["profiles"]["Default"]["hp_continuous_stop_margin_percent"],
            POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT,
        )
        self.assertEqual(
            saved["profiles"]["Default"]["mp_continuous_stop_margin_percent"],
            POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT,
        )
        self.assertEqual(saved["toggle_hotkey"], "F11")
        self.assertEqual(saved["emergency_stop_hotkey"], "Pause")
        self.assertEqual(saved["experience_toggle_hotkey"], "F10")
        self.assertEqual(saved["experience_reset_hotkey"], "F9")
        self.assertEqual(saved["character_stat_hotkey"], "")
        self.assertIsNone(saved["pickup_toggle_hotkey"])
        self.assertIsNone(saved["pickup_key"])
        self.assertIsNone(saved["minimap_cruise_toggle_hotkey"])
        self.assertEqual(saved["minimap_cruise_attack_key"], "C")
        self.assertIsNone(saved["minimap_cruise_left_x"])
        self.assertIsNone(saved["minimap_cruise_right_x"])
        self.assertIsNone(saved["minimap_cruise_detect_y"])
        self.assertEqual(saved["minimap_cruise_detect_band_height"], 120)
        self.assertEqual(saved["minimap_cruise_last_direction"], "right")
        self.assertFalse(saved["console_collapsed"])
        self.assertFalse(saved["combo_group_collapsed"])
        self.assertFalse(saved["compact_experience_mode"])
        self.assertFalse(saved["window_topmost"])
        self.assertIsNone(saved["full_panel_window_x"])
        self.assertIsNone(saved["full_panel_window_y"])
        self.assertIsNone(saved["compact_experience_window_x"])
        self.assertIsNone(saved["compact_experience_window_y"])
        json.dumps(settings.snapshot(), ensure_ascii=False)

    def test_load_settings_can_skip_writing_migrations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            original = json.dumps(
                {
                    "hp_key": "9",
                    "console_collapsed": True,
                    "combo_group_collapsed": True,
                    "compact_experience_mode": True,
                    "window_topmost": True,
                }
            )
            settings_path.write_text(original, encoding="utf-8")

            with patch("builtins.print"):
                settings = load_settings(settings_path, save_migrations=False)
            saved = settings_path.read_text(encoding="utf-8")

        self.assertEqual(settings.hp_key, "9")
        self.assertTrue(settings.console_collapsed)
        self.assertTrue(settings.combo_group_collapsed)
        self.assertTrue(settings.compact_experience_mode)
        self.assertTrue(settings.window_topmost)
        self.assertIsNone(settings.full_panel_window_x)
        self.assertIsNone(settings.full_panel_window_y)
        self.assertIsNone(settings.compact_experience_window_x)
        self.assertIsNone(settings.compact_experience_window_y)
        self.assertEqual(saved, original)

    def test_load_settings_clamps_potion_cooldowns_to_stable_minimum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps({"hp_cooldown_seconds": 0.05, "mp_cooldown_seconds": 0.01}),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(settings.hp_cooldown_seconds, POTION_MIN_COOLDOWN_SECONDS)
        self.assertEqual(settings.mp_cooldown_seconds, POTION_MIN_COOLDOWN_SECONDS)
        self.assertEqual(saved["profiles"]["Default"]["hp_cooldown_seconds"], POTION_MIN_COOLDOWN_SECONDS)
        self.assertEqual(saved["profiles"]["Default"]["mp_cooldown_seconds"], POTION_MIN_COOLDOWN_SECONDS)

    def test_load_settings_clamps_continuous_stop_margin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "hp_continuous_stop_margin_percent": -3.0,
                        "mp_continuous_stop_margin_percent": 75.0,
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(settings.hp_continuous_stop_margin_percent, 0.0)
        self.assertEqual(settings.mp_continuous_stop_margin_percent, POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT)
        self.assertEqual(saved["profiles"]["Default"]["hp_continuous_stop_margin_percent"], 0.0)
        self.assertEqual(
            saved["profiles"]["Default"]["mp_continuous_stop_margin_percent"],
            POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
        )

    def test_window_positions_are_global_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "full_panel_window_x": 120,
                        "full_panel_window_y": 240,
                        "compact_experience_window_x": 360,
                        "compact_experience_window_y": 480,
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(settings.full_panel_window_x, 120)
        self.assertEqual(settings.full_panel_window_y, 240)
        self.assertEqual(settings.compact_experience_window_x, 360)
        self.assertEqual(settings.compact_experience_window_y, 480)
        self.assertEqual(saved["full_panel_window_x"], 120)
        self.assertEqual(saved["full_panel_window_y"], 240)
        self.assertEqual(saved["compact_experience_window_x"], 360)
        self.assertEqual(saved["compact_experience_window_y"], 480)
        self.assertNotIn("full_panel_window_x", saved["profiles"]["Default"])
        self.assertNotIn("full_panel_window_y", saved["profiles"]["Default"])
        self.assertNotIn("compact_experience_window_x", saved["profiles"]["Default"])
        self.assertNotIn("compact_experience_window_y", saved["profiles"]["Default"])

    def test_minimap_cruise_settings_are_global_and_normalized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "minimap_cruise_toggle_hotkey": "F6",
                        "minimap_cruise_attack_key": "A",
                        "minimap_cruise_left_x": "276",
                        "minimap_cruise_right_x": "104",
                        "minimap_cruise_detect_y": "205",
                        "minimap_cruise_detect_band_height": 999,
                        "minimap_cruise_last_direction": "bad",
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(settings.minimap_cruise_toggle_hotkey, "F6")
        self.assertEqual(settings.minimap_cruise_attack_key, "A")
        self.assertEqual(settings.minimap_cruise_left_x, 276)
        self.assertEqual(settings.minimap_cruise_right_x, 104)
        self.assertEqual(settings.minimap_cruise_detect_y, 205)
        self.assertEqual(settings.minimap_cruise_detect_band_height, 180)
        self.assertEqual(settings.minimap_cruise_last_direction, "right")
        self.assertEqual(saved["minimap_cruise_toggle_hotkey"], "F6")
        self.assertEqual(saved["minimap_cruise_attack_key"], "A")
        self.assertEqual(saved["minimap_cruise_left_x"], 276)
        self.assertEqual(saved["minimap_cruise_right_x"], 104)
        self.assertEqual(saved["minimap_cruise_detect_y"], 205)
        self.assertEqual(saved["minimap_cruise_detect_band_height"], 180)
        self.assertEqual(saved["minimap_cruise_last_direction"], "right")
        self.assertNotIn("minimap_cruise_toggle_hotkey", saved["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_attack_key", saved["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_left_x", saved["profiles"]["Default"])

    def test_apply_profile_saves_current_profile_before_switching(self):
        settings = AutoPotionSettings(hp_key="9", hp_continuous_enabled=True, active_profile="Main")
        settings.hp_continuous_stop_margin_percent = 3.0
        settings.save_current_profile()
        settings.profiles["Boss"] = {
            **settings.profiles["Main"],
            "hp_key": "8",
            "mp_threshold_percent": 20.0,
            "hp_continuous_enabled": False,
            "mp_continuous_enabled": True,
            "hp_continuous_stop_margin_percent": 7.0,
            "mp_continuous_stop_margin_percent": 9.0,
        }

        settings.hp_key = "7"
        settings.hp_continuous_enabled = True
        settings.hp_continuous_stop_margin_percent = 4.0
        switched = settings.apply_profile("Boss")

        self.assertTrue(switched)
        self.assertEqual(settings.active_profile, "Boss")
        self.assertEqual(settings.hp_key, "8")
        self.assertEqual(settings.mp_threshold_percent, 20.0)
        self.assertFalse(settings.hp_continuous_enabled)
        self.assertTrue(settings.mp_continuous_enabled)
        self.assertEqual(settings.hp_continuous_stop_margin_percent, 7.0)
        self.assertEqual(settings.mp_continuous_stop_margin_percent, 9.0)
        self.assertEqual(settings.profiles["Main"]["hp_key"], "7")
        self.assertTrue(settings.profiles["Main"]["hp_continuous_enabled"])
        self.assertEqual(settings.profiles["Main"]["hp_continuous_stop_margin_percent"], 4.0)

    def test_delete_active_profile_switches_to_remaining_profile(self):
        settings = AutoPotionSettings(active_profile="Main", hp_key="9")
        settings.save_current_profile()
        settings.create_profile("Boss")
        settings.hp_key = "8"
        settings.save_current_profile()

        deleted = settings.delete_profile("Boss")

        self.assertTrue(deleted)
        self.assertEqual(settings.active_profile, "Main")
        self.assertEqual(settings.hp_key, "9")
        self.assertNotIn("Boss", settings.profiles)

    def test_control_hotkeys_are_global_not_profile_payload(self):
        settings = AutoPotionSettings(
            hp_continuous_enabled=True,
            mp_continuous_enabled=True,
            hp_continuous_stop_margin_percent=6.0,
            mp_continuous_stop_margin_percent=8.0,
            toggle_hotkey="F9",
            emergency_stop_hotkey="Pause",
            experience_toggle_hotkey="F10",
            experience_reset_hotkey="F8",
            character_stat_hotkey="V",
            pickup_toggle_hotkey="F7",
            pickup_key="Z",
            minimap_cruise_toggle_hotkey="F6",
            minimap_cruise_attack_key="A",
            minimap_cruise_left_x=104,
            minimap_cruise_right_x=276,
            minimap_cruise_detect_y=205,
            minimap_cruise_detect_band_height=16,
            minimap_cruise_last_direction="left",
            console_collapsed=True,
            combo_group_collapsed=True,
            compact_experience_mode=True,
            window_topmost=True,
            full_panel_window_x=100,
            full_panel_window_y=200,
            compact_experience_window_x=300,
            compact_experience_window_y=400,
        )
        payload = settings.to_json_dict()

        self.assertEqual(payload["toggle_hotkey"], "F9")
        self.assertEqual(payload["emergency_stop_hotkey"], "Pause")
        self.assertEqual(payload["experience_toggle_hotkey"], "F10")
        self.assertEqual(payload["experience_reset_hotkey"], "F8")
        self.assertEqual(payload["character_stat_hotkey"], "V")
        self.assertEqual(payload["pickup_toggle_hotkey"], "F7")
        self.assertEqual(payload["pickup_key"], "Z")
        self.assertEqual(payload["minimap_cruise_toggle_hotkey"], "F6")
        self.assertEqual(payload["minimap_cruise_attack_key"], "A")
        self.assertEqual(payload["minimap_cruise_left_x"], 104)
        self.assertEqual(payload["minimap_cruise_right_x"], 276)
        self.assertEqual(payload["minimap_cruise_detect_y"], 205)
        self.assertEqual(payload["minimap_cruise_detect_band_height"], 16)
        self.assertEqual(payload["minimap_cruise_last_direction"], "left")
        self.assertTrue(payload["console_collapsed"])
        self.assertTrue(payload["combo_group_collapsed"])
        self.assertTrue(payload["compact_experience_mode"])
        self.assertTrue(payload["window_topmost"])
        self.assertEqual(payload["full_panel_window_x"], 100)
        self.assertEqual(payload["full_panel_window_y"], 200)
        self.assertEqual(payload["compact_experience_window_x"], 300)
        self.assertEqual(payload["compact_experience_window_y"], 400)
        self.assertTrue(payload["profiles"]["Default"]["hp_continuous_enabled"])
        self.assertTrue(payload["profiles"]["Default"]["mp_continuous_enabled"])
        self.assertEqual(payload["profiles"]["Default"]["hp_continuous_stop_margin_percent"], 6.0)
        self.assertEqual(payload["profiles"]["Default"]["mp_continuous_stop_margin_percent"], 8.0)
        self.assertNotIn("toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("emergency_stop_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("experience_toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("experience_reset_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("character_stat_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("pickup_toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("pickup_key", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_attack_key", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_left_x", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_right_x", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_detect_y", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_detect_band_height", payload["profiles"]["Default"])
        self.assertNotIn("minimap_cruise_last_direction", payload["profiles"]["Default"])
        self.assertNotIn("console_collapsed", payload["profiles"]["Default"])
        self.assertNotIn("combo_group_collapsed", payload["profiles"]["Default"])
        self.assertNotIn("compact_experience_mode", payload["profiles"]["Default"])
        self.assertNotIn("window_topmost", payload["profiles"]["Default"])
        self.assertNotIn("full_panel_window_x", payload["profiles"]["Default"])
        self.assertNotIn("full_panel_window_y", payload["profiles"]["Default"])
        self.assertNotIn("compact_experience_window_x", payload["profiles"]["Default"])
        self.assertNotIn("compact_experience_window_y", payload["profiles"]["Default"])
