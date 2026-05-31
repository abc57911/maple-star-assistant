import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maple_star.settings import (
    AutoPotionSettings,
    COMBO_SCRIPT_REPEATING_JUMP_SKILL,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL,
    load_settings,
    normalize_controller_button_name,
)


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
        self.assertEqual(settings.combo_slots["A"]["script_id"], COMBO_SCRIPT_REPEATING_JUMP_SKILL)
        self.assertEqual(settings.combo_slots["B"]["script_id"], COMBO_SCRIPT_SINGLE_JUMP_SKILL)
        self.assertTrue(settings.combo_slots["A"]["enabled"])
        self.assertTrue(settings.combo_slots["B"]["enabled"])
        self.assertEqual(saved["rb_controller_button"], "RB")
        self.assertEqual(saved["lb_controller_button"], "LB")
        self.assertEqual(saved["combo_slots"]["A"]["trigger_button"], "RB")
        self.assertEqual(saved["combo_slots"]["B"]["trigger_button"], "LB")

    def test_settings_snapshot_includes_controller_buttons(self):
        settings = AutoPotionSettings(rb_controller_button="A", lb_controller_button="B")

        self.assertIn("A", settings.snapshot())
        self.assertIn("B", settings.snapshot())

    def test_load_settings_accepts_combo_slots_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "combo_slots": {
                            "A": {
                                "enabled": True,
                                "script_id": COMBO_SCRIPT_SINGLE_JUMP_SKILL,
                                "trigger_button": "Y",
                                "jump_key": "A",
                                "skill_key": "S",
                                "skill_delay_seconds": 0.35,
                                "jump_interval_seconds": 0.8,
                            },
                            "B": {
                                "enabled": False,
                                "script_id": COMBO_SCRIPT_REPEATING_JUMP_SKILL,
                                "trigger_button": "DPAD_LEFT",
                                "jump_key": "X",
                                "skill_key": "D",
                                "skill_delay_seconds": 0.1,
                                "jump_interval_seconds": 0.7,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                settings = load_settings(settings_path)

        self.assertTrue(settings.rb_enabled)
        self.assertEqual(settings.rb_controller_button, "Y")
        self.assertEqual(settings.rb_jump_key, "A")
        self.assertEqual(settings.rb_skill_key, "S")
        self.assertEqual(settings.combo_slots["A"]["script_id"], COMBO_SCRIPT_SINGLE_JUMP_SKILL)
        self.assertEqual(settings.combo_slots["B"]["script_id"], COMBO_SCRIPT_REPEATING_JUMP_SKILL)
        self.assertEqual(settings.combo_slots["B"]["jump_interval_seconds"], 0.7)

    def test_unknown_combo_script_falls_back_to_safe_default(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {
                    "enabled": True,
                    "script_id": "missing",
                    "trigger_button": "RB",
                }
            }
        )

        self.assertEqual(settings.combo_slots["A"]["script_id"], COMBO_SCRIPT_REPEATING_JUMP_SKILL)

    def test_combo_jump_interval_accepts_one_centisecond(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {
                    "enabled": True,
                    "script_id": COMBO_SCRIPT_REPEATING_JUMP_SKILL,
                    "trigger_button": "RB",
                    "jump_interval_seconds": 0.01,
                }
            }
        )

        self.assertEqual(settings.rb_jump_interval_seconds, 0.01)
        self.assertEqual(settings.combo_slots["A"]["jump_interval_seconds"], 0.01)
