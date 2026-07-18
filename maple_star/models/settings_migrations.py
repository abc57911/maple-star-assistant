from __future__ import annotations

import json

from .settings import (
    DEFAULT_PROFILE_NAME,
    GLOBAL_SETTING_KEYS,
    PROFILE_SETTING_KEYS,
    AutoPotionSettings,
    normalize_profile_name,
)
from .settings_v2 import (
    CURRENT_SETTINGS_SCHEMA_VERSION,
    SettingsV2Document,
    settings_v2_from_json_dict,
)


def _copy_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def migrate_settings_payload(raw: dict[str, object]) -> SettingsV2Document:
    if not isinstance(raw, dict):
        raise ValueError("settings payload must be a mapping")
    if raw.get("schema_version") == CURRENT_SETTINGS_SCHEMA_VERSION:
        return settings_v2_from_json_dict(raw)
    if "schema_version" in raw:
        raise ValueError(f"unsupported settings schema: {raw.get('schema_version')}")

    defaults = AutoPotionSettings().to_json_dict()
    selected_profile = normalize_profile_name(raw.get("active_profile"), DEFAULT_PROFILE_NAME)
    global_settings = {
        key: _copy_json(raw.get(key, defaults[key]))
        for key in GLOBAL_SETTING_KEYS
    }

    raw_profiles = raw.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ValueError("profiles must be a mapping")
    profiles: dict[str, dict[str, object]] = {}
    profile_extensions: dict[str, dict[str, object]] = {}
    for raw_name, raw_payload in raw_profiles.items():
        if not isinstance(raw_name, str) or not isinstance(raw_payload, dict):
            raise ValueError("every profile must be a mapping")
        name = normalize_profile_name(raw_name)
        profiles[name] = {
            key: _copy_json(raw_payload.get(key, defaults[key]))
            for key in PROFILE_SETTING_KEYS
        }
        profile_extensions[name] = {
            key: _copy_json(value)
            for key, value in raw_payload.items()
            if key not in PROFILE_SETTING_KEYS
        }

    if selected_profile not in profiles:
        profiles[selected_profile] = {
            key: _copy_json(raw.get(key, defaults[key]))
            for key in PROFILE_SETTING_KEYS
        }
        profile_extensions[selected_profile] = {}

    known_root_keys = set(PROFILE_SETTING_KEYS) | set(GLOBAL_SETTING_KEYS) | {"active_profile", "profiles"}
    extensions = {
        key: _copy_json(value)
        for key, value in raw.items()
        if key not in known_root_keys
    }
    return SettingsV2Document(
        schema_version=CURRENT_SETTINGS_SCHEMA_VERSION,
        global_settings=global_settings,
        profiles=profiles,
        selected_profile=selected_profile,
        extensions=extensions,
        profile_extensions=profile_extensions,
        migration={"from_version": 1, "to_version": CURRENT_SETTINGS_SCHEMA_VERSION},
    )


__all__ = ["migrate_settings_payload"]
