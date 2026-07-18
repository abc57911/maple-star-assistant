from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from maple_star.models.settings import (
    GLOBAL_SETTING_KEYS,
    PROFILE_SETTING_KEYS,
    AutoPotionSettings,
    load_settings,
    normalize_profile_name,
    save_settings,
)


LEGACY_METADATA_KEYS = ("active_profile", "profiles")


class SettingsRestorationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SettingsRestorationResult:
    source_sha256: str
    target_sha256: str
    backup_path: Path | None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_strict_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _mapping_differences(actual: dict[str, object], expected: dict[str, object], prefix: str = "") -> list[str]:
    differences: list[str] = []
    for key in sorted(actual.keys() | expected.keys()):
        path = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            differences.append(f"缺少欄位：{path}")
        elif key not in expected:
            differences.append(f"未知欄位：{path}")
        elif isinstance(actual[key], dict) and isinstance(expected[key], dict):
            differences.extend(_mapping_differences(actual[key], expected[key], path))
        elif not _strict_equal(actual[key], expected[key]):
            differences.append(f"值或型別不符：{path}（來源={actual[key]!r}，預期={expected[key]!r}）")
    return differences


def validate_legacy_settings(path: Path) -> tuple[AutoPotionSettings, dict[str, object]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsRestorationError(f"無法讀取 legacy 設定：{exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsRestorationError("legacy 設定 root 必須是 JSON object")
    if "schema_version" in raw:
        raise SettingsRestorationError("來源不是 legacy v1：不應包含 schema_version")

    expected_root_keys = set(GLOBAL_SETTING_KEYS) | set(PROFILE_SETTING_KEYS) | set(LEGACY_METADATA_KEYS)
    root_key_errors = []
    for key in sorted(set(raw) - expected_root_keys):
        root_key_errors.append(f"未知欄位：{key}")
    for key in sorted(expected_root_keys - set(raw)):
        root_key_errors.append(f"缺少欄位：{key}")
    if root_key_errors:
        raise SettingsRestorationError("legacy 欄位集合不完整：\n" + "\n".join(root_key_errors))

    active_profile = raw.get("active_profile")
    profiles = raw.get("profiles")
    if not isinstance(active_profile, str) or normalize_profile_name(active_profile) != active_profile:
        raise SettingsRestorationError("active_profile 必須是已正規化的字串")
    if not isinstance(profiles, dict) or active_profile not in profiles:
        raise SettingsRestorationError("profiles 必須包含 active_profile")

    profile_keys = set(PROFILE_SETTING_KEYS)
    for name, payload in profiles.items():
        if not isinstance(name, str) or normalize_profile_name(name) != name or not isinstance(payload, dict):
            raise SettingsRestorationError(f"設定檔格式錯誤：{name!r}")
        missing = sorted(profile_keys - set(payload))
        unknown = sorted(set(payload) - profile_keys)
        if missing or unknown:
            details = [*(f"缺少欄位：profiles.{name}.{key}" for key in missing), *(f"未知欄位：profiles.{name}.{key}" for key in unknown)]
            raise SettingsRestorationError("設定檔欄位集合不完整：\n" + "\n".join(details))

    active_payload = profiles[active_profile]
    conflicts = [
        key for key in PROFILE_SETTING_KEYS
        if not _strict_equal(raw[key], active_payload[key])
    ]
    if conflicts:
        raise SettingsRestorationError(
            "legacy root 與 active profile 衝突：\n"
            + "\n".join(f"{key} != profiles.{active_profile}.{key}" for key in conflicts)
        )

    settings = load_settings(path, save_migrations=False)
    canonical = settings.to_json_dict()
    differences = _mapping_differences(raw, canonical)
    if differences:
        raise SettingsRestorationError("legacy 值會被 fallback、clamp 或正規化：\n" + "\n".join(differences))
    return settings, raw


def _write_bytes_atomic(path: Path, payload: bytes, suffix: str) -> None:
    pending = path.with_name(f"{path.name}.{suffix}-{os.getpid()}")
    try:
        with pending.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    except BaseException:
        pending.unlink(missing_ok=True)
        raise


def _create_verified_backup(target: Path, payload: bytes, timestamp: datetime) -> Path:
    stem = f"{target.name}.pre-restore.{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    for collision_index in range(1000):
        suffix = "" if collision_index == 0 else f".{collision_index}"
        backup = target.with_name(f"{stem}{suffix}.bak.json")
        try:
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
        expected_hash = hashlib.sha256(payload).hexdigest()
        if file_sha256(backup) != expected_hash:
            backup.unlink(missing_ok=True)
            raise SettingsRestorationError("恢復前備份 checksum 不符")
        return backup
    raise SettingsRestorationError("無法建立唯一的恢復前備份名稱")


def restore_settings(
    source: Path,
    target: Path,
    *,
    now: Callable[[], datetime] | None = None,
    settings_writer: Callable[[AutoPotionSettings, Path], None] = save_settings,
    rollback_writer: Callable[[Path, bytes, str], None] = _write_bytes_atomic,
) -> SettingsRestorationResult:
    source = source.resolve(strict=True)
    target = target.resolve(strict=False)
    if source == target:
        raise SettingsRestorationError("來源與目標設定檔不可相同")
    source_hash = file_sha256(source)
    settings, _raw = validate_legacy_settings(source)

    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name("settings.restore.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SettingsRestorationError(f"設定恢復鎖已存在：{lock_path}") from exc

    backup_path: Path | None = None
    target_before: bytes | None = None
    target_before_hash: str | None = None
    replaced = False
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as lock_stream:
            lock_stream.write(f"pid={os.getpid()}\n")
            lock_stream.flush()
            os.fsync(lock_stream.fileno())

        if target.exists():
            target_before = target.read_bytes()
            target_before_hash = hashlib.sha256(target_before).hexdigest()
            try:
                json.loads(target_before.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SettingsRestorationError(f"目前 target 無法解析，停止恢復：{exc}") from exc
            timestamp = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
            backup_path = _create_verified_backup(target, target_before, timestamp)

        settings_writer(settings, target)
        replaced = True
        restored = load_settings(target, save_migrations=False)
        if not _strict_equal(settings.to_json_dict(), restored.to_json_dict()):
            raise SettingsRestorationError("target 寫入後的 model 比對失敗")
        settings_writer(restored, target)
        round_trip = load_settings(target, save_migrations=False)
        if not _strict_equal(settings.to_json_dict(), round_trip.to_json_dict()):
            raise SettingsRestorationError("target save/load round trip 比對失敗")
        if file_sha256(source) != source_hash:
            raise SettingsRestorationError("來源設定在恢復期間被修改")
        return SettingsRestorationResult(source_hash, file_sha256(target), backup_path)
    except BaseException as restore_exc:
        if replaced:
            try:
                if target_before is None:
                    target.unlink(missing_ok=True)
                    if target.exists():
                        raise SettingsRestorationError("rollback 後 target 仍存在")
                else:
                    rollback_writer(target, target_before, "restore-rollback")
                    restored_bytes = target.read_bytes()
                    json.loads(restored_bytes.decode("utf-8"))
                    if hashlib.sha256(restored_bytes).hexdigest() != target_before_hash:
                        raise SettingsRestorationError("rollback 後 target checksum 不符")
            except BaseException as rollback_exc:
                raise SettingsRestorationError(f"設定恢復失敗，且 rollback 驗證失敗：{rollback_exc}") from restore_exc
        raise
    finally:
        lock_path.unlink(missing_ok=True)


__all__ = [
    "SettingsRestorationError",
    "SettingsRestorationResult",
    "file_sha256",
    "restore_settings",
    "validate_legacy_settings",
]
