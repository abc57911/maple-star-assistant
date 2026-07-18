from __future__ import annotations

import unittest

from maple_star.models.settings import AutoPotionSettings, DEFAULT_PROFILE_NAME
from maple_star.models.settings_migrations import migrate_settings_payload
from maple_star.models.settings_v2 import CURRENT_SETTINGS_SCHEMA_VERSION, SettingsV2Document


class SettingsV2MigrationTests(unittest.TestCase):
    def test_current_payload_is_partitioned_into_global_and_profiles(self) -> None:
        settings = AutoPotionSettings()
        settings.toggle_hotkey = "F8"
        settings.hp_threshold_percent = 44.0

        document = migrate_settings_payload(settings.to_json_dict())

        self.assertEqual(document.schema_version, CURRENT_SETTINGS_SCHEMA_VERSION)
        self.assertEqual(document.global_settings["toggle_hotkey"], "F8")
        self.assertEqual(document.profiles[DEFAULT_PROFILE_NAME]["hp_threshold_percent"], 44.0)
        self.assertEqual(document.selected_profile, DEFAULT_PROFILE_NAME)

    def test_unknown_root_and_profile_fields_survive_legacy_round_trip(self) -> None:
        raw = AutoPotionSettings().to_json_dict()
        raw["future_root"] = {"enabled": True}
        profiles = dict(raw["profiles"])
        default_profile = dict(profiles[DEFAULT_PROFILE_NAME])
        default_profile["future_profile"] = "kept"
        profiles[DEFAULT_PROFILE_NAME] = default_profile
        raw["profiles"] = profiles

        document = migrate_settings_payload(raw)
        restored = document.to_legacy_payload()

        self.assertEqual(document.extensions["future_root"], {"enabled": True})
        self.assertEqual(document.profile_extensions[DEFAULT_PROFILE_NAME]["future_profile"], "kept")
        self.assertEqual(restored["future_root"], {"enabled": True})
        self.assertEqual(restored["profiles"][DEFAULT_PROFILE_NAME]["future_profile"], "kept")

    def test_v2_payload_migration_is_idempotent(self) -> None:
        first = migrate_settings_payload(AutoPotionSettings().to_json_dict())

        second = migrate_settings_payload(first.to_json_dict())

        self.assertEqual(second, first)

    def test_invalid_profile_aborts_whole_migration(self) -> None:
        raw = AutoPotionSettings().to_json_dict()
        raw["profiles"] = {DEFAULT_PROFILE_NAME: "invalid"}

        with self.assertRaises(ValueError):
            migrate_settings_payload(raw)

    def test_document_rejects_missing_selected_profile(self) -> None:
        with self.assertRaises(ValueError):
            SettingsV2Document(
                schema_version=CURRENT_SETTINGS_SCHEMA_VERSION,
                global_settings={},
                profiles={DEFAULT_PROFILE_NAME: {}},
                selected_profile="Missing",
            )


if __name__ == "__main__":
    unittest.main()
