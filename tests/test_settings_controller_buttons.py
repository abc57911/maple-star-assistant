import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maple_star.settings import AutoPotionSettings, load_settings, normalize_controller_button_name


class ControllerButtonSettingsTests(unittest.TestCase):
    def test_normalize_controller_button_name_accepts_aliases(self):
        self.assertEqual(normalize_controller_button_name("right shoulder", "LB"), "RB")
        self.assertEqual(normalize_controller_button_name("dpad-left", "RB"), "DPAD_LEFT")
        self.assertEqual(normalize_controller_button_name("unknown", "RB"), "RB")

    def test_load_settings_migrates_controller_button_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps({"rb_enabled": True, "lb_enabled": True}),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertTrue(settings.rb_enabled)
        self.assertTrue(settings.lb_enabled)
        self.assertEqual(settings.rb_controller_button, "RB")
        self.assertEqual(settings.lb_controller_button, "LB")
        self.assertEqual(saved["rb_controller_button"], "RB")
        self.assertEqual(saved["lb_controller_button"], "LB")

    def test_settings_snapshot_includes_controller_buttons(self):
        settings = AutoPotionSettings(rb_controller_button="A", lb_controller_button="B")

        self.assertIn("A", settings.snapshot())
        self.assertIn("B", settings.snapshot())
