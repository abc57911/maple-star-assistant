from __future__ import annotations

import json
from dataclasses import dataclass, field

from .settings import DEFAULT_PROFILE_NAME, GLOBAL_SETTING_KEYS, PROFILE_SETTING_KEYS, normalize_profile_name


CURRENT_SETTINGS_SCHEMA_VERSION = 2


def _copy_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


@dataclass(frozen=True, slots=True)
class SettingsV2Document:
    schema_version: int
    global_settings: dict[str, object]
    profiles: dict[str, dict[str, object]]
    selected_profile: str
    extensions: dict[str, object] = field(default_factory=dict)
    profile_extensions: dict[str, dict[str, object]] = field(default_factory=dict)
    migration: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != CURRENT_SETTINGS_SCHEMA_VERSION:
            raise ValueError(f"unsupported settings schema: {self.schema_version}")
        normalized = normalize_profile_name(self.selected_profile)
        if normalized != self.selected_profile or normalized not in self.profiles:
            raise ValueError("selected_profile must name an existing normalized profile")
        if any(not isinstance(payload, dict) for payload in self.profiles.values()):
            raise ValueError("every profile must be a mapping")

    def to_json_dict(self) -> dict[str, object]:
        rendered_profiles: dict[str, dict[str, object]] = {}
        for name, payload in self.profiles.items():
            rendered = _copy_json(payload)
            extensions = self.profile_extensions.get(name, {})
            if extensions:
                rendered["extensions"] = _copy_json(extensions)
            rendered_profiles[name] = rendered
        return {
            "schema_version": self.schema_version,
            "global": _copy_json(self.global_settings),
            "profiles": rendered_profiles,
            "selected_profile": self.selected_profile,
            "extensions": _copy_json(self.extensions),
            "migration": _copy_json(self.migration),
        }

    def to_legacy_payload(self) -> dict[str, object]:
        result = _copy_json(self.extensions)
        result.update(_copy_json(self.global_settings))
        profiles: dict[str, dict[str, object]] = {}
        for name, payload in self.profiles.items():
            restored = _copy_json(payload)
            restored.update(_copy_json(self.profile_extensions.get(name, {})))
            profiles[name] = restored
        result.update(_copy_json(profiles[self.selected_profile]))
        result["active_profile"] = self.selected_profile
        result["profiles"] = profiles
        return result


def settings_v2_from_json_dict(raw: dict[str, object]) -> SettingsV2Document:
    if int(raw.get("schema_version", 0) or 0) != CURRENT_SETTINGS_SCHEMA_VERSION:
        raise ValueError("payload is not settings v2")
    global_settings = raw.get("global")
    raw_profiles = raw.get("profiles")
    if not isinstance(global_settings, dict) or not isinstance(raw_profiles, dict):
        raise ValueError("settings v2 global and profiles must be mappings")
    profiles: dict[str, dict[str, object]] = {}
    profile_extensions: dict[str, dict[str, object]] = {}
    for raw_name, raw_payload in raw_profiles.items():
        if not isinstance(raw_name, str) or not isinstance(raw_payload, dict):
            raise ValueError("settings v2 contains an invalid profile")
        name = normalize_profile_name(raw_name)
        payload = dict(raw_payload)
        extensions = payload.pop("extensions", {})
        if not isinstance(extensions, dict):
            raise ValueError(f"profile extensions must be a mapping: {name}")
        profiles[name] = {key: _copy_json(value) for key, value in payload.items() if key in PROFILE_SETTING_KEYS}
        profile_extensions[name] = _copy_json(extensions)
    extensions = raw.get("extensions", {})
    migration = raw.get("migration", {})
    if not isinstance(extensions, dict) or not isinstance(migration, dict):
        raise ValueError("settings v2 metadata must be mappings")
    return SettingsV2Document(
        schema_version=CURRENT_SETTINGS_SCHEMA_VERSION,
        global_settings={
            key: _copy_json(value)
            for key, value in global_settings.items()
            if key in GLOBAL_SETTING_KEYS
        },
        profiles=profiles,
        selected_profile=normalize_profile_name(raw.get("selected_profile"), DEFAULT_PROFILE_NAME),
        extensions=_copy_json(extensions),
        profile_extensions=profile_extensions,
        migration=_copy_json(migration),
    )


__all__ = [
    "CURRENT_SETTINGS_SCHEMA_VERSION",
    "SettingsV2Document",
    "settings_v2_from_json_dict",
]
