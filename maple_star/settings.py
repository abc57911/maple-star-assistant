from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


SETTINGS_PATH = app_base_dir() / "settings.json"
DEFAULT_PROFILE_NAME = "Default"
DEFAULT_TOGGLE_HOTKEY = "F11"
DEFAULT_EMERGENCY_STOP_HOTKEY = "Pause"
DEFAULT_EXPERIENCE_TOGGLE_HOTKEY = "F10"
CONTROLLER_BUTTON_CHOICES = (
    "A",
    "B",
    "X",
    "Y",
    "LB",
    "RB",
    "BACK",
    "START",
    "HOME",
    "L3",
    "R3",
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
)
CONTROLLER_BUTTON_ALIASES = {
    "LEFT_SHOULDER": "LB",
    "RIGHT_SHOULDER": "RB",
    "GUIDE": "HOME",
    "SELECT": "BACK",
}


def normalize_controller_button_name(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().upper().replace(" ", "_").replace("-", "_")
    normalized = CONTROLLER_BUTTON_ALIASES.get(normalized, normalized)
    if normalized in CONTROLLER_BUTTON_CHOICES:
        return normalized
    return fallback


def normalize_profile_name(value: object, fallback: str = DEFAULT_PROFILE_NAME) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized or fallback


@dataclass
class AutoPotionSettings:
    hp_enabled: bool = True
    mp_enabled: bool = True
    rb_enabled: bool = False
    hp_threshold_percent: float = 50.0
    mp_threshold_percent: float = 30.0
    hp_key: str = "Delete"
    mp_key: str = "End"
    hp_cooldown_seconds: float = 0.2
    mp_cooldown_seconds: float = 0.2
    rb_jump_key: str = "X"
    rb_skill_key: str = "C"
    rb_controller_button: str = "RB"
    rb_skill_delay_seconds: float = 0.2
    rb_jump_interval_seconds: float = 0.66
    lb_enabled: bool = False
    lb_jump_key: str = "X"
    lb_skill_key: str = "C"
    lb_controller_button: str = "LB"
    lb_skill_delay_seconds: float = 0.2
    exp_efficiency_enabled: bool = False
    toggle_hotkey: str = DEFAULT_TOGGLE_HOTKEY
    emergency_stop_hotkey: str = DEFAULT_EMERGENCY_STOP_HOTKEY
    experience_toggle_hotkey: str = DEFAULT_EXPERIENCE_TOGGLE_HOTKEY
    console_collapsed: bool = False
    compact_experience_mode: bool = False
    window_topmost: bool = False
    active_profile: str = DEFAULT_PROFILE_NAME
    profiles: dict[str, dict[str, object]] = field(default_factory=dict)

    def snapshot(self) -> tuple[object, ...]:
        return (
            self.hp_enabled,
            self.mp_enabled,
            self.rb_enabled,
            self.hp_threshold_percent,
            self.mp_threshold_percent,
            self.hp_key,
            self.mp_key,
            self.hp_cooldown_seconds,
            self.mp_cooldown_seconds,
            self.rb_jump_key,
            self.rb_skill_key,
            self.rb_controller_button,
            self.rb_skill_delay_seconds,
            self.rb_jump_interval_seconds,
            self.lb_enabled,
            self.lb_jump_key,
            self.lb_skill_key,
            self.lb_controller_button,
            self.lb_skill_delay_seconds,
            self.exp_efficiency_enabled,
            self.toggle_hotkey,
            self.emergency_stop_hotkey,
            self.experience_toggle_hotkey,
            self.console_collapsed,
            self.compact_experience_mode,
            self.window_topmost,
            self.active_profile,
            json.dumps(self.profiles, ensure_ascii=False, sort_keys=True),
        )

    def to_json_dict(self) -> dict[str, object]:
        current_values = profile_payload_from_settings(self)
        profiles = {
            name: dict(payload)
            for name, payload in self.profiles.items()
            if isinstance(name, str) and isinstance(payload, dict)
        }
        profiles[normalize_profile_name(self.active_profile)] = current_values
        return {
            "hp_enabled": self.hp_enabled,
            "mp_enabled": self.mp_enabled,
            "rb_enabled": self.rb_enabled,
            "hp_threshold_percent": self.hp_threshold_percent,
            "mp_threshold_percent": self.mp_threshold_percent,
            "hp_key": self.hp_key,
            "mp_key": self.mp_key,
            "hp_cooldown_seconds": self.hp_cooldown_seconds,
            "mp_cooldown_seconds": self.mp_cooldown_seconds,
            "rb_jump_key": self.rb_jump_key,
            "rb_skill_key": self.rb_skill_key,
            "rb_controller_button": self.rb_controller_button,
            "rb_skill_delay_seconds": self.rb_skill_delay_seconds,
            "rb_jump_interval_seconds": self.rb_jump_interval_seconds,
            "lb_enabled": self.lb_enabled,
            "lb_jump_key": self.lb_jump_key,
            "lb_skill_key": self.lb_skill_key,
            "lb_controller_button": self.lb_controller_button,
            "lb_skill_delay_seconds": self.lb_skill_delay_seconds,
            "exp_efficiency_enabled": self.exp_efficiency_enabled,
            "toggle_hotkey": self.toggle_hotkey,
            "emergency_stop_hotkey": self.emergency_stop_hotkey,
            "experience_toggle_hotkey": self.experience_toggle_hotkey,
            "console_collapsed": self.console_collapsed,
            "compact_experience_mode": self.compact_experience_mode,
            "window_topmost": self.window_topmost,
            "active_profile": normalize_profile_name(self.active_profile),
            "profiles": profiles,
        }

    def save_current_profile(self) -> None:
        self.active_profile = normalize_profile_name(self.active_profile)
        self.profiles[self.active_profile] = profile_payload_from_settings(self)

    def profile_names(self) -> list[str]:
        names = {
            normalize_profile_name(name)
            for name in self.profiles
            if isinstance(name, str) and normalize_profile_name(name)
        }
        names.add(normalize_profile_name(self.active_profile))
        return sorted(names, key=lambda name: (name != DEFAULT_PROFILE_NAME, name.lower()))

    def apply_profile(self, name: str) -> bool:
        target_name = normalize_profile_name(name)
        payload = self.profiles.get(target_name)
        if not isinstance(payload, dict):
            return False
        self.save_current_profile()
        loaded = settings_from_profile_payload(payload, self, target_name, self.profiles)
        copy_setting_values(loaded, self)
        self.active_profile = target_name
        return True

    def create_profile(self, name: str) -> bool:
        target_name = normalize_profile_name(name)
        if target_name in self.profiles:
            return False
        self.save_current_profile()
        self.profiles[target_name] = profile_payload_from_settings(self)
        self.active_profile = target_name
        return True

    def delete_profile(self, name: str) -> bool:
        target_name = normalize_profile_name(name)
        if target_name not in self.profiles or len(self.profile_names()) <= 1:
            return False
        del self.profiles[target_name]
        if self.active_profile == target_name:
            next_name = sorted(self.profiles, key=lambda name: (name != DEFAULT_PROFILE_NAME, name.lower()))[0]
            payload = self.profiles[next_name]
            loaded = settings_from_profile_payload(payload, self, next_name, self.profiles)
            copy_setting_values(loaded, self)
            self.active_profile = next_name
        return True


PROFILE_SETTING_KEYS = (
    "hp_enabled",
    "mp_enabled",
    "rb_enabled",
    "hp_threshold_percent",
    "mp_threshold_percent",
    "hp_key",
    "mp_key",
    "hp_cooldown_seconds",
    "mp_cooldown_seconds",
    "rb_jump_key",
    "rb_skill_key",
    "rb_controller_button",
    "rb_skill_delay_seconds",
    "rb_jump_interval_seconds",
    "lb_enabled",
    "lb_jump_key",
    "lb_skill_key",
    "lb_controller_button",
    "lb_skill_delay_seconds",
    "exp_efficiency_enabled",
)
GLOBAL_SETTING_KEYS = (
    "toggle_hotkey",
    "emergency_stop_hotkey",
    "experience_toggle_hotkey",
    "console_collapsed",
    "compact_experience_mode",
    "window_topmost",
)


def profile_payload_from_settings(settings: AutoPotionSettings) -> dict[str, object]:
    return {key: getattr(settings, key) for key in PROFILE_SETTING_KEYS}


def copy_setting_values(source: AutoPotionSettings, target: AutoPotionSettings) -> None:
    for key in PROFILE_SETTING_KEYS + GLOBAL_SETTING_KEYS:
        setattr(target, key, getattr(source, key))


def _read_bool(data: dict[str, object], key: str, fallback: bool) -> bool:
    value = data.get(key, fallback)
    return value if isinstance(value, bool) else fallback


def _read_float(data: dict[str, object], key: str, fallback: float, minimum: float, maximum: float) -> float:
    value = data.get(key, fallback)
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _read_string(data: dict[str, object], key: str, fallback: str) -> str:
    value = data.get(key, fallback)
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    return value or fallback


def _read_profile_payload(raw: object, fallback: AutoPotionSettings) -> dict[str, object]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "hp_enabled": _read_bool(data, "hp_enabled", fallback.hp_enabled),
        "mp_enabled": _read_bool(data, "mp_enabled", fallback.mp_enabled),
        "rb_enabled": _read_bool(data, "rb_enabled", fallback.rb_enabled),
        "hp_threshold_percent": _read_float(data, "hp_threshold_percent", fallback.hp_threshold_percent, 1.0, 100.0),
        "mp_threshold_percent": _read_float(data, "mp_threshold_percent", fallback.mp_threshold_percent, 1.0, 100.0),
        "hp_key": _read_string(data, "hp_key", fallback.hp_key),
        "mp_key": _read_string(data, "mp_key", fallback.mp_key),
        "hp_cooldown_seconds": _read_float(data, "hp_cooldown_seconds", fallback.hp_cooldown_seconds, 0.05, 60.0),
        "mp_cooldown_seconds": _read_float(data, "mp_cooldown_seconds", fallback.mp_cooldown_seconds, 0.05, 60.0),
        "rb_jump_key": _read_string(data, "rb_jump_key", fallback.rb_jump_key),
        "rb_skill_key": _read_string(data, "rb_skill_key", fallback.rb_skill_key),
        "rb_controller_button": normalize_controller_button_name(data.get("rb_controller_button"), fallback.rb_controller_button),
        "rb_skill_delay_seconds": _read_float(data, "rb_skill_delay_seconds", fallback.rb_skill_delay_seconds, 0.0, 10.0),
        "rb_jump_interval_seconds": _read_float(data, "rb_jump_interval_seconds", fallback.rb_jump_interval_seconds, 0.05, 10.0),
        "lb_enabled": _read_bool(data, "lb_enabled", fallback.lb_enabled),
        "lb_jump_key": _read_string(data, "lb_jump_key", fallback.lb_jump_key),
        "lb_skill_key": _read_string(data, "lb_skill_key", fallback.lb_skill_key),
        "lb_controller_button": normalize_controller_button_name(data.get("lb_controller_button"), fallback.lb_controller_button),
        "lb_skill_delay_seconds": _read_float(data, "lb_skill_delay_seconds", fallback.lb_skill_delay_seconds, 0.0, 10.0),
        "exp_efficiency_enabled": _read_bool(data, "exp_efficiency_enabled", fallback.exp_efficiency_enabled),
    }


def _read_profiles(raw: object, fallback: AutoPotionSettings) -> dict[str, dict[str, object]]:
    if not isinstance(raw, dict):
        return {}
    profiles: dict[str, dict[str, object]] = {}
    for name, payload in raw.items():
        profile_name = normalize_profile_name(name, "")
        if not profile_name:
            continue
        profiles[profile_name] = _read_profile_payload(payload, fallback)
    return profiles


def settings_from_profile_payload(
    payload: dict[str, object],
    fallback: AutoPotionSettings,
    active_profile: str,
    profiles: dict[str, dict[str, object]],
) -> AutoPotionSettings:
    values = _read_profile_payload(payload, fallback)
    return AutoPotionSettings(
        **values,
        toggle_hotkey=fallback.toggle_hotkey,
        emergency_stop_hotkey=fallback.emergency_stop_hotkey,
        experience_toggle_hotkey=fallback.experience_toggle_hotkey,
        console_collapsed=fallback.console_collapsed,
        compact_experience_mode=fallback.compact_experience_mode,
        window_topmost=fallback.window_topmost,
        active_profile=normalize_profile_name(active_profile),
        profiles=profiles,
    )


def load_settings(path: Path = SETTINGS_PATH, save_migrations: bool = True) -> AutoPotionSettings:
    settings = AutoPotionSettings()
    if not path.exists():
        if save_migrations:
            save_settings(settings, path)
        print(f"已建立預設設定檔：{path}")
        return settings

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"讀取設定失敗，使用預設值：{exc}")
        if save_migrations:
            save_settings(settings, path)
        return settings

    if not isinstance(raw, dict):
        print("設定檔格式錯誤，使用預設值")
        if save_migrations:
            save_settings(settings, path)
        return settings

    base_settings = AutoPotionSettings(
        hp_enabled=_read_bool(raw, "hp_enabled", settings.hp_enabled),
        mp_enabled=_read_bool(raw, "mp_enabled", settings.mp_enabled),
        rb_enabled=_read_bool(raw, "rb_enabled", settings.rb_enabled),
        hp_threshold_percent=_read_float(raw, "hp_threshold_percent", settings.hp_threshold_percent, 1.0, 100.0),
        mp_threshold_percent=_read_float(raw, "mp_threshold_percent", settings.mp_threshold_percent, 1.0, 100.0),
        hp_key=_read_string(raw, "hp_key", settings.hp_key),
        mp_key=_read_string(raw, "mp_key", settings.mp_key),
        hp_cooldown_seconds=_read_float(raw, "hp_cooldown_seconds", settings.hp_cooldown_seconds, 0.05, 60.0),
        mp_cooldown_seconds=_read_float(raw, "mp_cooldown_seconds", settings.mp_cooldown_seconds, 0.05, 60.0),
        rb_jump_key=_read_string(raw, "rb_jump_key", settings.rb_jump_key),
        rb_skill_key=_read_string(raw, "rb_skill_key", settings.rb_skill_key),
        rb_controller_button=normalize_controller_button_name(raw.get("rb_controller_button"), settings.rb_controller_button),
        rb_skill_delay_seconds=_read_float(raw, "rb_skill_delay_seconds", settings.rb_skill_delay_seconds, 0.0, 10.0),
        rb_jump_interval_seconds=_read_float(raw, "rb_jump_interval_seconds", settings.rb_jump_interval_seconds, 0.05, 10.0),
        lb_enabled=_read_bool(raw, "lb_enabled", settings.lb_enabled),
        lb_jump_key=_read_string(raw, "lb_jump_key", settings.lb_jump_key),
        lb_skill_key=_read_string(raw, "lb_skill_key", settings.lb_skill_key),
        lb_controller_button=normalize_controller_button_name(raw.get("lb_controller_button"), settings.lb_controller_button),
        lb_skill_delay_seconds=_read_float(raw, "lb_skill_delay_seconds", settings.lb_skill_delay_seconds, 0.0, 10.0),
        exp_efficiency_enabled=_read_bool(raw, "exp_efficiency_enabled", settings.exp_efficiency_enabled),
        toggle_hotkey=_read_string(raw, "toggle_hotkey", settings.toggle_hotkey),
        emergency_stop_hotkey=_read_string(raw, "emergency_stop_hotkey", settings.emergency_stop_hotkey),
        experience_toggle_hotkey=_read_string(
            raw,
            "experience_toggle_hotkey",
            settings.experience_toggle_hotkey,
        ),
        console_collapsed=_read_bool(raw, "console_collapsed", settings.console_collapsed),
        compact_experience_mode=_read_bool(raw, "compact_experience_mode", settings.compact_experience_mode),
        window_topmost=_read_bool(raw, "window_topmost", settings.window_topmost),
        active_profile=normalize_profile_name(raw.get("active_profile"), DEFAULT_PROFILE_NAME),
    )
    profiles = _read_profiles(raw.get("profiles"), base_settings)
    if base_settings.active_profile not in profiles:
        profiles[base_settings.active_profile] = profile_payload_from_settings(base_settings)

    loaded_settings = settings_from_profile_payload(
        profiles[base_settings.active_profile],
        base_settings,
        base_settings.active_profile,
        profiles,
    )
    expected = loaded_settings.to_json_dict()
    needs_save = any(
        key not in raw
        or type(raw.get(key)) is not type(value)
        or raw.get(key) != value
        for key, value in expected.items()
    )
    if needs_save:
        if save_migrations:
            save_settings(loaded_settings, path)
        print("設定檔已補齊缺少或格式異常的參數")
    return loaded_settings


def save_settings(settings: AutoPotionSettings, path: Path = SETTINGS_PATH) -> None:
    path.write_text(
        json.dumps(settings.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
