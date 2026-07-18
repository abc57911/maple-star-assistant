from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from maple_star.models.settings import AutoPotionSettings, load_settings, save_settings


class SettingsV2ProductionTests(unittest.TestCase):
    def test_save_writes_v2_and_load_preserves_profile_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = AutoPotionSettings()
            settings.hp_threshold_percent = 47.0

            save_settings(settings, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            loaded = load_settings(path, save_migrations=False)

            self.assertEqual(raw["schema_version"], 2)
            self.assertEqual(loaded.hp_threshold_percent, 47.0)

    def test_legacy_load_migrates_atomically_and_keeps_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            raw = AutoPotionSettings().to_json_dict()
            raw["hp_threshold_percent"] = 43.0
            raw["profiles"][raw["active_profile"]]["hp_threshold_percent"] = 43.0
            path.write_text(json.dumps(raw), encoding="utf-8")

            loaded = load_settings(path, save_migrations=True)

            self.assertEqual(loaded.hp_threshold_percent, 43.0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 2)
            self.assertEqual(len(list(Path(directory).glob("settings.json.backup.*"))), 1)

    def test_invalid_v2_does_not_overwrite_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = '{"schema_version": 2, "global": {}, "profiles": "bad"}\n'
            path.write_text(original, encoding="utf-8")

            with self.assertRaises(ValueError):
                load_settings(path)

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_invalid_json_does_not_fall_back_to_runnable_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = '{"schema_version": 2, bad json}\n'
            path.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "原檔未修改"):
                load_settings(path)

            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
