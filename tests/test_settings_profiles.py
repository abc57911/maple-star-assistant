import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertFalse(settings.console_collapsed)
        self.assertFalse(settings.combo_group_collapsed)
        self.assertFalse(settings.compact_experience_mode)
        self.assertFalse(settings.window_topmost)
        self.assertIsNone(settings.full_panel_window_x)
        self.assertIsNone(settings.full_panel_window_y)
        self.assertIsNone(settings.compact_experience_window_x)
        self.assertIsNone(settings.compact_experience_window_y)
        self.assertIn("Default", saved["profiles"])
        self.assertEqual(saved["profiles"]["Default"]["hp_key"], "9")
        self.assertFalse(saved["profiles"]["Default"]["exp_efficiency_enabled"])
        self.assertEqual(saved["toggle_hotkey"], "F11")
        self.assertEqual(saved["emergency_stop_hotkey"], "Pause")
        self.assertEqual(saved["experience_toggle_hotkey"], "F10")
        self.assertFalse(saved["console_collapsed"])
        self.assertFalse(saved["combo_group_collapsed"])
        self.assertFalse(saved["compact_experience_mode"])
        self.assertFalse(saved["window_topmost"])
        self.assertIsNone(saved["full_panel_window_x"])
        self.assertIsNone(saved["full_panel_window_y"])
        self.assertIsNone(saved["compact_experience_window_x"])
        self.assertIsNone(saved["compact_experience_window_y"])

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

    def test_apply_profile_saves_current_profile_before_switching(self):
        settings = AutoPotionSettings(hp_key="9", active_profile="Main")
        settings.save_current_profile()
        settings.profiles["Boss"] = {
            **settings.profiles["Main"],
            "hp_key": "8",
            "mp_threshold_percent": 20.0,
        }

        settings.hp_key = "7"
        switched = settings.apply_profile("Boss")

        self.assertTrue(switched)
        self.assertEqual(settings.active_profile, "Boss")
        self.assertEqual(settings.hp_key, "8")
        self.assertEqual(settings.mp_threshold_percent, 20.0)
        self.assertEqual(settings.profiles["Main"]["hp_key"], "7")

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
            toggle_hotkey="F9",
            emergency_stop_hotkey="Pause",
            experience_toggle_hotkey="F10",
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
        self.assertTrue(payload["console_collapsed"])
        self.assertTrue(payload["combo_group_collapsed"])
        self.assertTrue(payload["compact_experience_mode"])
        self.assertTrue(payload["window_topmost"])
        self.assertEqual(payload["full_panel_window_x"], 100)
        self.assertEqual(payload["full_panel_window_y"], 200)
        self.assertEqual(payload["compact_experience_window_x"], 300)
        self.assertEqual(payload["compact_experience_window_y"], 400)
        self.assertNotIn("toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("emergency_stop_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("experience_toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("console_collapsed", payload["profiles"]["Default"])
        self.assertNotIn("combo_group_collapsed", payload["profiles"]["Default"])
        self.assertNotIn("compact_experience_mode", payload["profiles"]["Default"])
        self.assertNotIn("window_topmost", payload["profiles"]["Default"])
        self.assertNotIn("full_panel_window_x", payload["profiles"]["Default"])
        self.assertNotIn("full_panel_window_y", payload["profiles"]["Default"])
        self.assertNotIn("compact_experience_window_x", payload["profiles"]["Default"])
        self.assertNotIn("compact_experience_window_y", payload["profiles"]["Default"])
