from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from maple_star.models.settings import AutoPotionSettings, load_settings, save_settings
from maple_star.services.settings_restoration import (
    SettingsRestorationError,
    file_sha256,
    restore_settings,
    validate_legacy_settings,
)


class SettingsRestorationTests(unittest.TestCase):
    def _legacy_payload(self) -> dict[str, object]:
        settings = AutoPotionSettings()
        settings.toggle_hotkey = "F3"
        settings.hp_threshold_percent = 77.0
        settings.save_current_profile()
        return settings.to_json_dict()

    def test_restore_migrates_legacy_atomically_and_keeps_verified_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "settings.json"
            source.write_text(json.dumps(self._legacy_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
            target.write_text(json.dumps(AutoPotionSettings().to_json_dict(), ensure_ascii=False), encoding="utf-8")
            source_hash = file_sha256(source)
            target_before = target.read_bytes()

            result = restore_settings(
                source,
                target,
                now=lambda: datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
            )

            raw = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 2)
            self.assertEqual(load_settings(target, save_migrations=False).toggle_hotkey, "F3")
            self.assertEqual(result.source_sha256, source_hash)
            self.assertEqual(file_sha256(source), source_hash)
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(result.backup_path.read_bytes(), target_before)
            self.assertFalse((root / "settings.restore.lock").exists())

    def test_root_profile_conflict_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "settings.json"
            payload = self._legacy_payload()
            payload["hp_key"] = "F1"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            target.write_text("{\"keep\": true}\n", encoding="utf-8")
            original = target.read_bytes()

            with self.assertRaisesRegex(SettingsRestorationError, "root 與 active profile 衝突"):
                restore_settings(source, target)

            self.assertEqual(target.read_bytes(), original)

    def test_unknown_field_is_rejected_by_read_only_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            payload = self._legacy_payload()
            payload["future_key"] = True
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            before = file_sha256(source)

            with self.assertRaisesRegex(SettingsRestorationError, "未知欄位"):
                validate_legacy_settings(source)

            self.assertEqual(file_sha256(source), before)

    def test_same_second_restores_create_distinct_backups_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "settings.json"
            source.write_text(json.dumps(self._legacy_payload(), ensure_ascii=False), encoding="utf-8")
            target.write_text(json.dumps(AutoPotionSettings().to_json_dict(), ensure_ascii=False), encoding="utf-8")
            first_target = target.read_bytes()
            fixed_now = lambda: datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

            first = restore_settings(source, target, now=fixed_now)
            second = restore_settings(source, target, now=fixed_now)

            self.assertNotEqual(first.backup_path, second.backup_path)
            self.assertEqual(first.backup_path.read_bytes(), first_target)
            self.assertTrue(second.backup_path.exists())

    def test_post_write_verification_failure_rolls_back_exact_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "settings.json"
            source.write_text(json.dumps(self._legacy_payload(), ensure_ascii=False), encoding="utf-8")
            target.write_text("{\"keep\": true}\n", encoding="utf-8")
            original = target.read_bytes()

            def write_wrong_settings(_settings, path: Path) -> None:
                save_settings(AutoPotionSettings(), path)

            with self.assertRaisesRegex(SettingsRestorationError, "model 比對失敗"):
                restore_settings(source, target, settings_writer=write_wrong_settings)

            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"keep": True})

    def test_rollback_verification_failure_is_reported_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "settings.json"
            source.write_text(json.dumps(self._legacy_payload(), ensure_ascii=False), encoding="utf-8")
            target.write_text("{\"keep\": true}\n", encoding="utf-8")

            def write_wrong_settings(_settings, path: Path) -> None:
                save_settings(AutoPotionSettings(), path)

            def corrupt_rollback(path: Path, _payload: bytes, _suffix: str) -> None:
                path.write_bytes(b"{}\n")

            with self.assertRaisesRegex(SettingsRestorationError, "rollback 驗證失敗"):
                restore_settings(
                    source,
                    target,
                    settings_writer=write_wrong_settings,
                    rollback_writer=corrupt_rollback,
                )


if __name__ == "__main__":
    unittest.main()
