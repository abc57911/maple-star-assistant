from __future__ import annotations

from maple_star.models.settings import GLOBAL_SETTING_KEYS, PROFILE_SETTING_KEYS


SETTINGS_V2_PATHS = {
    **{name: f"global.{name}" for name in GLOBAL_SETTING_KEYS},
    **{name: f"profiles.<selected>.{name}" for name in PROFILE_SETTING_KEYS},
}


def assert_complete_settings_v2_mapping() -> None:
    expected = set(GLOBAL_SETTING_KEYS) | set(PROFILE_SETTING_KEYS)
    assert set(SETTINGS_V2_PATHS) == expected
    assert len(SETTINGS_V2_PATHS) == len(expected)


__all__ = ["SETTINGS_V2_PATHS", "assert_complete_settings_v2_mapping"]
