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
        self.assertIn("Default", saved["profiles"])
        self.assertEqual(saved["profiles"]["Default"]["hp_key"], "9")
        self.assertFalse(saved["profiles"]["Default"]["exp_efficiency_enabled"])
        self.assertEqual(saved["toggle_hotkey"], "F11")
        self.assertEqual(saved["emergency_stop_hotkey"], "Pause")
        self.assertEqual(saved["experience_toggle_hotkey"], "F10")

    def test_load_settings_can_skip_writing_migrations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            original = json.dumps({"hp_key": "9"})
            settings_path.write_text(original, encoding="utf-8")

            with patch("builtins.print"):
                settings = load_settings(settings_path, save_migrations=False)
            saved = settings_path.read_text(encoding="utf-8")

        self.assertEqual(settings.hp_key, "9")
        self.assertEqual(saved, original)

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
        )
        payload = settings.to_json_dict()

        self.assertEqual(payload["toggle_hotkey"], "F9")
        self.assertEqual(payload["emergency_stop_hotkey"], "Pause")
        self.assertEqual(payload["experience_toggle_hotkey"], "F10")
        self.assertNotIn("toggle_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("emergency_stop_hotkey", payload["profiles"]["Default"])
        self.assertNotIn("experience_toggle_hotkey", payload["profiles"]["Default"])
