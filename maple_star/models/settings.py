from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..constants import (
    POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT,
    POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
    POTION_MIN_COOLDOWN_SECONDS,
)

def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


SETTINGS_PATH = app_base_dir() / "settings.json"
DEFAULT_PROFILE_NAME = "Default"
DEFAULT_TOGGLE_HOTKEY = "F11"
DEFAULT_EMERGENCY_STOP_HOTKEY = "Pause"
DEFAULT_EXPERIENCE_TOGGLE_HOTKEY = "F10"
DEFAULT_EXPERIENCE_RESET_HOTKEY = "F9"
DEFAULT_CHARACTER_STAT_HOTKEY = ""
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
COMBO_SLOT_IDS = ("A", "B")
COMBO_SCRIPT_REPEATING_JUMP_SKILL = "repeating_jump_skill"
COMBO_SCRIPT_SINGLE_JUMP_SKILL = "single_jump_skill"
COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP = "hold_jump_attack_loop"
COMBO_SCRIPT_IDS = (
    COMBO_SCRIPT_REPEATING_JUMP_SKILL,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL,
    COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP,
)
COMBO_SCRIPT_LABELS = {
    COMBO_SCRIPT_REPEATING_JUMP_SKILL: "循環跳躍技能",
    COMBO_SCRIPT_SINGLE_JUMP_SKILL: "單次跳躍技能",
    COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP: "按住跳躍循環攻擊",
}
COMBO_JUMP_INTERVAL_MIN_SECONDS = 0.01
COMBO_JUMP_INTERVAL_MAX_SECONDS = 10.0
COMBO_ATTACK_START_DELAY_MIN_SECONDS = 0.0
COMBO_ATTACK_START_DELAY_MAX_SECONDS = 10.0
COMBO_ATTACK_HOLD_MIN_SECONDS = 0.01
COMBO_ATTACK_HOLD_MAX_SECONDS = 10.0
MINIMAP_CRUISE_DEFAULT_ATTACK_KEY = "C"
MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT = 120
MINIMAP_CRUISE_MIN_DETECT_BAND_HEIGHT = 12
MINIMAP_CRUISE_MAX_DETECT_BAND_HEIGHT = 180
MINIMAP_CRUISE_DEFAULT_PRE_BOUNDARY_SKILL_DISTANCE = 20
MINIMAP_CRUISE_MIN_PRE_BOUNDARY_SKILL_DISTANCE = 0
MINIMAP_CRUISE_MAX_PRE_BOUNDARY_SKILL_DISTANCE = 500
MINIMAP_CRUISE_DEFAULT_LIE_DETECTOR_ALERT_VOLUME_PERCENT = 80
MINIMAP_CRUISE_MIN_ALERT_VOLUME_PERCENT = 0
MINIMAP_CRUISE_MAX_ALERT_VOLUME_PERCENT = 100
MINIMAP_CRUISE_DEFAULT_PERIODIC_KEY_INTERVAL_SECONDS = 60.0
MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS = 0.1
MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS = 3600.0
MINIMAP_CRUISE_DIRECTIONS = ("left", "right")


def normalize_controller_button_name(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().upper().replace(" ", "_").replace("-", "_")
    normalized = CONTROLLER_BUTTON_ALIASES.get(normalized, normalized)
    if normalized in CONTROLLER_BUTTON_CHOICES:
        return normalized
    return fallback


def normalize_combo_script_id(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if normalized in COMBO_SCRIPT_IDS:
        return normalized
    return fallback


def _coerce_float_value(value: object, fallback: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _normalize_non_empty_string(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized or fallback


def _combo_slots_from_legacy_values(values: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        "A": {
            "enabled": bool(values.get("rb_enabled", False)),
            "script_id": COMBO_SCRIPT_REPEATING_JUMP_SKILL,
            "trigger_button": normalize_controller_button_name(values.get("rb_controller_button"), "RB"),
            "jump_key": str(values.get("rb_jump_key") or "X"),
            "skill_key": str(values.get("rb_skill_key") or "C"),
            "attack_key": str(values.get("rb_attack_key") or values.get("rb_skill_key") or "C"),
            "attack_start_delay_seconds": _coerce_float_value(
                values.get("rb_attack_start_delay_seconds"),
                0.0,
                COMBO_ATTACK_START_DELAY_MIN_SECONDS,
                COMBO_ATTACK_START_DELAY_MAX_SECONDS,
            ),
            "attack_hold_seconds": _coerce_float_value(
                values.get("rb_attack_hold_seconds"),
                1.0,
                COMBO_ATTACK_HOLD_MIN_SECONDS,
                COMBO_ATTACK_HOLD_MAX_SECONDS,
            ),
            "skill_delay_seconds": _coerce_float_value(values.get("rb_skill_delay_seconds"), 0.2, 0.0, 10.0),
            "jump_interval_seconds": _coerce_float_value(
                values.get("rb_jump_interval_seconds"),
                0.66,
                COMBO_JUMP_INTERVAL_MIN_SECONDS,
                COMBO_JUMP_INTERVAL_MAX_SECONDS,
            ),
        },
        "B": {
            "enabled": bool(values.get("lb_enabled", False)),
            "script_id": COMBO_SCRIPT_SINGLE_JUMP_SKILL,
            "trigger_button": normalize_controller_button_name(values.get("lb_controller_button"), "LB"),
            "jump_key": str(values.get("lb_jump_key") or "X"),
            "skill_key": str(values.get("lb_skill_key") or "C"),
            "attack_key": str(values.get("lb_attack_key") or values.get("lb_skill_key") or "C"),
            "attack_start_delay_seconds": _coerce_float_value(
                values.get("lb_attack_start_delay_seconds"),
                0.0,
                COMBO_ATTACK_START_DELAY_MIN_SECONDS,
                COMBO_ATTACK_START_DELAY_MAX_SECONDS,
            ),
            "attack_hold_seconds": _coerce_float_value(
                values.get("lb_attack_hold_seconds"),
                1.0,
                COMBO_ATTACK_HOLD_MIN_SECONDS,
                COMBO_ATTACK_HOLD_MAX_SECONDS,
            ),
            "skill_delay_seconds": _coerce_float_value(values.get("lb_skill_delay_seconds"), 0.2, 0.0, 10.0),
            "jump_interval_seconds": 0.66,
        },
    }


def default_combo_slots() -> dict[str, dict[str, object]]:
    return _combo_slots_from_legacy_values({})


def normalize_combo_slots(
    value: object,
    fallback_values: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    fallback_slots = _combo_slots_from_legacy_values(fallback_values or {})
    raw_slots = value if isinstance(value, dict) else {}
    slots: dict[str, dict[str, object]] = {}
    for slot_id in COMBO_SLOT_IDS:
        fallback = fallback_slots[slot_id]
        raw = raw_slots.get(slot_id)
        data = raw if isinstance(raw, dict) else {}
        skill_key = _normalize_non_empty_string(data.get("skill_key"), str(fallback["skill_key"]))
        slots[slot_id] = {
            "enabled": data.get("enabled") if isinstance(data.get("enabled"), bool) else fallback["enabled"],
            "script_id": normalize_combo_script_id(data.get("script_id"), str(fallback["script_id"])),
            "trigger_button": normalize_controller_button_name(data.get("trigger_button"), str(fallback["trigger_button"])),
            "jump_key": _normalize_non_empty_string(data.get("jump_key"), str(fallback["jump_key"])),
            "skill_key": skill_key,
            "attack_key": _normalize_non_empty_string(data.get("attack_key"), skill_key),
            "attack_start_delay_seconds": _coerce_float_value(
                data.get("attack_start_delay_seconds"),
                float(fallback["attack_start_delay_seconds"]),
                COMBO_ATTACK_START_DELAY_MIN_SECONDS,
                COMBO_ATTACK_START_DELAY_MAX_SECONDS,
            ),
            "attack_hold_seconds": _coerce_float_value(
                data.get("attack_hold_seconds"),
                float(fallback["attack_hold_seconds"]),
                COMBO_ATTACK_HOLD_MIN_SECONDS,
                COMBO_ATTACK_HOLD_MAX_SECONDS,
            ),
            "skill_delay_seconds": _coerce_float_value(
                data.get("skill_delay_seconds"),
                float(fallback["skill_delay_seconds"]),
                0.0,
                10.0,
            ),
            "jump_interval_seconds": _coerce_float_value(
                data.get("jump_interval_seconds"),
                float(fallback["jump_interval_seconds"]),
                COMBO_JUMP_INTERVAL_MIN_SECONDS,
                COMBO_JUMP_INTERVAL_MAX_SECONDS,
            ),
        }
    return slots


def legacy_combo_fields_from_slots(combo_slots: dict[str, dict[str, object]]) -> dict[str, object]:
    slot_a = combo_slots["A"]
    slot_b = combo_slots["B"]
    return {
        "rb_enabled": bool(slot_a["enabled"]),
        "rb_jump_key": str(slot_a["jump_key"]),
        "rb_skill_key": str(slot_a["skill_key"]),
        "rb_controller_button": str(slot_a["trigger_button"]),
        "rb_skill_delay_seconds": float(slot_a["skill_delay_seconds"]),
        "rb_jump_interval_seconds": float(slot_a["jump_interval_seconds"]),
        "lb_enabled": bool(slot_b["enabled"]),
        "lb_jump_key": str(slot_b["jump_key"]),
        "lb_skill_key": str(slot_b["skill_key"]),
        "lb_controller_button": str(slot_b["trigger_button"]),
        "lb_skill_delay_seconds": float(slot_b["skill_delay_seconds"]),
    }


def normalize_profile_name(value: object, fallback: str = DEFAULT_PROFILE_NAME) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized or fallback


def normalize_minimap_cruise_direction(value: object, fallback: str = "right") -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().lower()
    if normalized in MINIMAP_CRUISE_DIRECTIONS:
        return normalized
    return fallback

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
    hp_continuous_enabled: bool = False
    mp_continuous_enabled: bool = False
    hp_continuous_stop_margin_percent: float = POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT
    mp_continuous_stop_margin_percent: float = POTION_CONTINUOUS_STOP_MARGIN_DEFAULT_PERCENT
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
    combo_slots: dict[str, dict[str, object]] | None = None
    exp_efficiency_enabled: bool = False
    toggle_hotkey: str = DEFAULT_TOGGLE_HOTKEY
    emergency_stop_hotkey: str = DEFAULT_EMERGENCY_STOP_HOTKEY
    experience_toggle_hotkey: str = DEFAULT_EXPERIENCE_TOGGLE_HOTKEY
    experience_reset_hotkey: str = DEFAULT_EXPERIENCE_RESET_HOTKEY
    character_stat_hotkey: str = DEFAULT_CHARACTER_STAT_HOTKEY
    pickup_toggle_hotkey: str | None = None
    pickup_key: str | None = None
    minimap_cruise_toggle_hotkey: str | None = None
    minimap_cruise_attack_key: str = MINIMAP_CRUISE_DEFAULT_ATTACK_KEY
    minimap_cruise_left_x: int | None = None
    minimap_cruise_right_x: int | None = None
    minimap_cruise_detect_y: int | None = None
    minimap_cruise_detect_band_height: int = MINIMAP_CRUISE_DEFAULT_DETECT_BAND_HEIGHT
    minimap_cruise_last_direction: str = "right"
    minimap_cruise_pre_boundary_skill_enabled: bool = False
    minimap_cruise_pre_boundary_skill_key: str = ""
    minimap_cruise_pre_boundary_distance: int = MINIMAP_CRUISE_DEFAULT_PRE_BOUNDARY_SKILL_DISTANCE
    minimap_cruise_stationary_skill_key: str = ""
    minimap_cruise_lie_detector_alert_volume_percent: int = MINIMAP_CRUISE_DEFAULT_LIE_DETECTOR_ALERT_VOLUME_PERCENT
    minimap_cruise_periodic_key_1_enabled: bool = False
    minimap_cruise_periodic_key_1: str = ""
    minimap_cruise_periodic_key_1_interval_seconds: float = MINIMAP_CRUISE_DEFAULT_PERIODIC_KEY_INTERVAL_SECONDS
    minimap_cruise_periodic_key_2_enabled: bool = False
    minimap_cruise_periodic_key_2: str = ""
    minimap_cruise_periodic_key_2_interval_seconds: float = MINIMAP_CRUISE_DEFAULT_PERIODIC_KEY_INTERVAL_SECONDS
    minimap_cruise_periodic_key_3_enabled: bool = False
    minimap_cruise_periodic_key_3: str = ""
    minimap_cruise_periodic_key_3_interval_seconds: float = MINIMAP_CRUISE_DEFAULT_PERIODIC_KEY_INTERVAL_SECONDS
    minimap_cruise_periodic_key_4_enabled: bool = False
    minimap_cruise_periodic_key_4: str = ""
    minimap_cruise_periodic_key_4_interval_seconds: float = MINIMAP_CRUISE_DEFAULT_PERIODIC_KEY_INTERVAL_SECONDS
    minimap_cruise_periodic_key_5_enabled: bool = False
    minimap_cruise_periodic_key_5: str = ""
    minimap_cruise_periodic_key_5_interval_seconds: float = MINIMAP_CRUISE_DEFAULT_PERIODIC_KEY_INTERVAL_SECONDS
    console_collapsed: bool = False
    combo_group_collapsed: bool = False
    minimap_cruise_group_collapsed: bool = False
    compact_experience_mode: bool = False
    window_topmost: bool = False
    full_panel_window_x: int | None = None
    full_panel_window_y: int | None = None
    compact_experience_window_x: int | None = None
    compact_experience_window_y: int | None = None
    active_profile: str = DEFAULT_PROFILE_NAME
    profiles: dict[str, dict[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.normalize_combo_slots()

    def normalize_combo_slots(self) -> None:
        fallback_values = {
            "rb_enabled": self.rb_enabled,
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
        }
        self.combo_slots = normalize_combo_slots(self.combo_slots, fallback_values)
        for key, value in legacy_combo_fields_from_slots(self.combo_slots).items():
            setattr(self, key, value)

    def combo_slot(self, slot_id: str) -> dict[str, object]:
        self.normalize_combo_slots()
        return self.combo_slots[slot_id]

    def set_combo_slots(self, combo_slots: dict[str, dict[str, object]]) -> None:
        self.combo_slots = combo_slots
        self.normalize_combo_slots()

    def snapshot(self) -> tuple[object, ...]:
        self.normalize_combo_slots()
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
            self.hp_continuous_enabled,
            self.mp_continuous_enabled,
            self.hp_continuous_stop_margin_percent,
            self.mp_continuous_stop_margin_percent,
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
            json.dumps(self.combo_slots, ensure_ascii=False, sort_keys=True),
            self.exp_efficiency_enabled,
            self.toggle_hotkey,
            self.emergency_stop_hotkey,
            self.experience_toggle_hotkey,
            self.experience_reset_hotkey,
            self.character_stat_hotkey,
            self.pickup_toggle_hotkey,
            self.pickup_key,
            self.minimap_cruise_toggle_hotkey,
            self.minimap_cruise_attack_key,
            self.minimap_cruise_left_x,
            self.minimap_cruise_right_x,
            self.minimap_cruise_detect_y,
            self.minimap_cruise_detect_band_height,
            self.minimap_cruise_last_direction,
            self.minimap_cruise_pre_boundary_skill_enabled,
            self.minimap_cruise_pre_boundary_skill_key,
            self.minimap_cruise_pre_boundary_distance,
            self.minimap_cruise_stationary_skill_key,
            self.minimap_cruise_lie_detector_alert_volume_percent,
            self.minimap_cruise_periodic_key_1_enabled,
            self.minimap_cruise_periodic_key_1,
            self.minimap_cruise_periodic_key_1_interval_seconds,
            self.minimap_cruise_periodic_key_2_enabled,
            self.minimap_cruise_periodic_key_2,
            self.minimap_cruise_periodic_key_2_interval_seconds,
            self.minimap_cruise_periodic_key_3_enabled,
            self.minimap_cruise_periodic_key_3,
            self.minimap_cruise_periodic_key_3_interval_seconds,
            self.minimap_cruise_periodic_key_4_enabled,
            self.minimap_cruise_periodic_key_4,
            self.minimap_cruise_periodic_key_4_interval_seconds,
            self.minimap_cruise_periodic_key_5_enabled,
            self.minimap_cruise_periodic_key_5,
            self.minimap_cruise_periodic_key_5_interval_seconds,
            self.console_collapsed,
            self.combo_group_collapsed,
            self.minimap_cruise_group_collapsed,
            self.compact_experience_mode,
            self.window_topmost,
            self.full_panel_window_x,
            self.full_panel_window_y,
            self.compact_experience_window_x,
            self.compact_experience_window_y,
            self.active_profile,
            json.dumps(self.profiles, ensure_ascii=False, sort_keys=True),
        )

    def to_json_dict(self) -> dict[str, object]:
        self.normalize_combo_slots()
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
            "hp_continuous_enabled": self.hp_continuous_enabled,
            "mp_continuous_enabled": self.mp_continuous_enabled,
            "hp_continuous_stop_margin_percent": self.hp_continuous_stop_margin_percent,
            "mp_continuous_stop_margin_percent": self.mp_continuous_stop_margin_percent,
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
            "combo_slots": self.combo_slots,
            "exp_efficiency_enabled": self.exp_efficiency_enabled,
            "toggle_hotkey": self.toggle_hotkey,
            "emergency_stop_hotkey": self.emergency_stop_hotkey,
            "experience_toggle_hotkey": self.experience_toggle_hotkey,
            "experience_reset_hotkey": self.experience_reset_hotkey,
            "character_stat_hotkey": self.character_stat_hotkey,
            "pickup_toggle_hotkey": self.pickup_toggle_hotkey,
            "pickup_key": self.pickup_key,
            "minimap_cruise_toggle_hotkey": self.minimap_cruise_toggle_hotkey,
            "minimap_cruise_attack_key": self.minimap_cruise_attack_key,
            "minimap_cruise_left_x": self.minimap_cruise_left_x,
            "minimap_cruise_right_x": self.minimap_cruise_right_x,
            "minimap_cruise_detect_y": self.minimap_cruise_detect_y,
            "minimap_cruise_detect_band_height": self.minimap_cruise_detect_band_height,
            "minimap_cruise_last_direction": self.minimap_cruise_last_direction,
            "minimap_cruise_pre_boundary_skill_enabled": self.minimap_cruise_pre_boundary_skill_enabled,
            "minimap_cruise_pre_boundary_skill_key": self.minimap_cruise_pre_boundary_skill_key,
            "minimap_cruise_pre_boundary_distance": self.minimap_cruise_pre_boundary_distance,
            "minimap_cruise_stationary_skill_key": self.minimap_cruise_stationary_skill_key,
            "minimap_cruise_lie_detector_alert_volume_percent": self.minimap_cruise_lie_detector_alert_volume_percent,
            "minimap_cruise_periodic_key_1_enabled": self.minimap_cruise_periodic_key_1_enabled,
            "minimap_cruise_periodic_key_1": self.minimap_cruise_periodic_key_1,
            "minimap_cruise_periodic_key_1_interval_seconds": self.minimap_cruise_periodic_key_1_interval_seconds,
            "minimap_cruise_periodic_key_2_enabled": self.minimap_cruise_periodic_key_2_enabled,
            "minimap_cruise_periodic_key_2": self.minimap_cruise_periodic_key_2,
            "minimap_cruise_periodic_key_2_interval_seconds": self.minimap_cruise_periodic_key_2_interval_seconds,
            "minimap_cruise_periodic_key_3_enabled": self.minimap_cruise_periodic_key_3_enabled,
            "minimap_cruise_periodic_key_3": self.minimap_cruise_periodic_key_3,
            "minimap_cruise_periodic_key_3_interval_seconds": self.minimap_cruise_periodic_key_3_interval_seconds,
            "minimap_cruise_periodic_key_4_enabled": self.minimap_cruise_periodic_key_4_enabled,
            "minimap_cruise_periodic_key_4": self.minimap_cruise_periodic_key_4,
            "minimap_cruise_periodic_key_4_interval_seconds": self.minimap_cruise_periodic_key_4_interval_seconds,
            "minimap_cruise_periodic_key_5_enabled": self.minimap_cruise_periodic_key_5_enabled,
            "minimap_cruise_periodic_key_5": self.minimap_cruise_periodic_key_5,
            "minimap_cruise_periodic_key_5_interval_seconds": self.minimap_cruise_periodic_key_5_interval_seconds,
            "console_collapsed": self.console_collapsed,
            "combo_group_collapsed": self.combo_group_collapsed,
            "minimap_cruise_group_collapsed": self.minimap_cruise_group_collapsed,
            "compact_experience_mode": self.compact_experience_mode,
            "window_topmost": self.window_topmost,
            "full_panel_window_x": self.full_panel_window_x,
            "full_panel_window_y": self.full_panel_window_y,
            "compact_experience_window_x": self.compact_experience_window_x,
            "compact_experience_window_y": self.compact_experience_window_y,
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
    "hp_continuous_enabled",
    "mp_continuous_enabled",
    "hp_continuous_stop_margin_percent",
    "mp_continuous_stop_margin_percent",
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
    "combo_slots",
    "exp_efficiency_enabled",
)
GLOBAL_SETTING_KEYS = (
    "toggle_hotkey",
    "emergency_stop_hotkey",
    "experience_toggle_hotkey",
    "experience_reset_hotkey",
    "character_stat_hotkey",
    "pickup_toggle_hotkey",
    "pickup_key",
    "minimap_cruise_toggle_hotkey",
    "minimap_cruise_attack_key",
    "minimap_cruise_left_x",
    "minimap_cruise_right_x",
    "minimap_cruise_detect_y",
    "minimap_cruise_detect_band_height",
    "minimap_cruise_last_direction",
    "minimap_cruise_pre_boundary_skill_enabled",
    "minimap_cruise_pre_boundary_skill_key",
    "minimap_cruise_pre_boundary_distance",
    "minimap_cruise_stationary_skill_key",
    "minimap_cruise_lie_detector_alert_volume_percent",
    "minimap_cruise_periodic_key_1_enabled",
    "minimap_cruise_periodic_key_1",
    "minimap_cruise_periodic_key_1_interval_seconds",
    "minimap_cruise_periodic_key_2_enabled",
    "minimap_cruise_periodic_key_2",
    "minimap_cruise_periodic_key_2_interval_seconds",
    "minimap_cruise_periodic_key_3_enabled",
    "minimap_cruise_periodic_key_3",
    "minimap_cruise_periodic_key_3_interval_seconds",
    "minimap_cruise_periodic_key_4_enabled",
    "minimap_cruise_periodic_key_4",
    "minimap_cruise_periodic_key_4_interval_seconds",
    "minimap_cruise_periodic_key_5_enabled",
    "minimap_cruise_periodic_key_5",
    "minimap_cruise_periodic_key_5_interval_seconds",
    "console_collapsed",
    "combo_group_collapsed",
    "minimap_cruise_group_collapsed",
    "compact_experience_mode",
    "window_topmost",
    "full_panel_window_x",
    "full_panel_window_y",
    "compact_experience_window_x",
    "compact_experience_window_y",
)


def profile_payload_from_settings(settings: AutoPotionSettings) -> dict[str, object]:
    settings.normalize_combo_slots()
    payload = {key: getattr(settings, key) for key in PROFILE_SETTING_KEYS}
    payload["combo_slots"] = json.loads(json.dumps(settings.combo_slots))
    return payload


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


def _read_optional_string(data: dict[str, object], key: str, fallback: str | None) -> str | None:
    value = data.get(key, fallback)
    if value is None:
        return None
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    return value or None


def _read_optional_int(data: dict[str, object], key: str, fallback: int | None) -> int | None:
    value = data.get(key, fallback)
    if value is None:
        return None
    if isinstance(value, bool):
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _read_int(data: dict[str, object], key: str, fallback: int, minimum: int, maximum: int) -> int:
    value = data.get(key, fallback)
    if isinstance(value, bool):
        return fallback
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return fallback


def _read_profile_payload(raw: object, fallback: AutoPotionSettings) -> dict[str, object]:
    data = raw if isinstance(raw, dict) else {}
    values: dict[str, object] = {
        "hp_enabled": _read_bool(data, "hp_enabled", fallback.hp_enabled),
        "mp_enabled": _read_bool(data, "mp_enabled", fallback.mp_enabled),
        "rb_enabled": _read_bool(data, "rb_enabled", fallback.rb_enabled),
        "hp_threshold_percent": _read_float(data, "hp_threshold_percent", fallback.hp_threshold_percent, 1.0, 100.0),
        "mp_threshold_percent": _read_float(data, "mp_threshold_percent", fallback.mp_threshold_percent, 1.0, 100.0),
        "hp_key": _read_string(data, "hp_key", fallback.hp_key),
        "mp_key": _read_string(data, "mp_key", fallback.mp_key),
        "hp_cooldown_seconds": _read_float(
            data,
            "hp_cooldown_seconds",
            fallback.hp_cooldown_seconds,
            POTION_MIN_COOLDOWN_SECONDS,
            60.0,
        ),
        "mp_cooldown_seconds": _read_float(
            data,
            "mp_cooldown_seconds",
            fallback.mp_cooldown_seconds,
            POTION_MIN_COOLDOWN_SECONDS,
            60.0,
        ),
        "hp_continuous_enabled": _read_bool(
            data,
            "hp_continuous_enabled",
            fallback.hp_continuous_enabled,
        ),
        "mp_continuous_enabled": _read_bool(
            data,
            "mp_continuous_enabled",
            fallback.mp_continuous_enabled,
        ),
        "hp_continuous_stop_margin_percent": _read_float(
            data,
            "hp_continuous_stop_margin_percent",
            fallback.hp_continuous_stop_margin_percent,
            0.0,
            POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
        ),
        "mp_continuous_stop_margin_percent": _read_float(
            data,
            "mp_continuous_stop_margin_percent",
            fallback.mp_continuous_stop_margin_percent,
            0.0,
            POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
        ),
        "rb_jump_key": _read_string(data, "rb_jump_key", fallback.rb_jump_key),
        "rb_skill_key": _read_string(data, "rb_skill_key", fallback.rb_skill_key),
        "rb_controller_button": normalize_controller_button_name(data.get("rb_controller_button"), fallback.rb_controller_button),
        "rb_skill_delay_seconds": _read_float(data, "rb_skill_delay_seconds", fallback.rb_skill_delay_seconds, 0.0, 10.0),
        "rb_jump_interval_seconds": _read_float(
            data,
            "rb_jump_interval_seconds",
            fallback.rb_jump_interval_seconds,
            COMBO_JUMP_INTERVAL_MIN_SECONDS,
            COMBO_JUMP_INTERVAL_MAX_SECONDS,
        ),
        "lb_enabled": _read_bool(data, "lb_enabled", fallback.lb_enabled),
        "lb_jump_key": _read_string(data, "lb_jump_key", fallback.lb_jump_key),
        "lb_skill_key": _read_string(data, "lb_skill_key", fallback.lb_skill_key),
        "lb_controller_button": normalize_controller_button_name(data.get("lb_controller_button"), fallback.lb_controller_button),
        "lb_skill_delay_seconds": _read_float(data, "lb_skill_delay_seconds", fallback.lb_skill_delay_seconds, 0.0, 10.0),
        "exp_efficiency_enabled": _read_bool(data, "exp_efficiency_enabled", fallback.exp_efficiency_enabled),
    }
    combo_slots = normalize_combo_slots(data.get("combo_slots"), values)
    values.update(legacy_combo_fields_from_slots(combo_slots))
    values["combo_slots"] = combo_slots
    return values


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
        experience_reset_hotkey=fallback.experience_reset_hotkey,
        character_stat_hotkey=fallback.character_stat_hotkey,
        pickup_toggle_hotkey=fallback.pickup_toggle_hotkey,
        pickup_key=fallback.pickup_key,
        minimap_cruise_toggle_hotkey=fallback.minimap_cruise_toggle_hotkey,
        minimap_cruise_attack_key=fallback.minimap_cruise_attack_key,
        minimap_cruise_left_x=fallback.minimap_cruise_left_x,
        minimap_cruise_right_x=fallback.minimap_cruise_right_x,
        minimap_cruise_detect_y=fallback.minimap_cruise_detect_y,
        minimap_cruise_detect_band_height=fallback.minimap_cruise_detect_band_height,
        minimap_cruise_last_direction=fallback.minimap_cruise_last_direction,
        minimap_cruise_pre_boundary_skill_enabled=fallback.minimap_cruise_pre_boundary_skill_enabled,
        minimap_cruise_pre_boundary_skill_key=fallback.minimap_cruise_pre_boundary_skill_key,
        minimap_cruise_pre_boundary_distance=fallback.minimap_cruise_pre_boundary_distance,
        minimap_cruise_stationary_skill_key=fallback.minimap_cruise_stationary_skill_key,
        minimap_cruise_lie_detector_alert_volume_percent=fallback.minimap_cruise_lie_detector_alert_volume_percent,
        minimap_cruise_periodic_key_1_enabled=fallback.minimap_cruise_periodic_key_1_enabled,
        minimap_cruise_periodic_key_1=fallback.minimap_cruise_periodic_key_1,
        minimap_cruise_periodic_key_1_interval_seconds=fallback.minimap_cruise_periodic_key_1_interval_seconds,
        minimap_cruise_periodic_key_2_enabled=fallback.minimap_cruise_periodic_key_2_enabled,
        minimap_cruise_periodic_key_2=fallback.minimap_cruise_periodic_key_2,
        minimap_cruise_periodic_key_2_interval_seconds=fallback.minimap_cruise_periodic_key_2_interval_seconds,
        minimap_cruise_periodic_key_3_enabled=fallback.minimap_cruise_periodic_key_3_enabled,
        minimap_cruise_periodic_key_3=fallback.minimap_cruise_periodic_key_3,
        minimap_cruise_periodic_key_3_interval_seconds=fallback.minimap_cruise_periodic_key_3_interval_seconds,
        minimap_cruise_periodic_key_4_enabled=fallback.minimap_cruise_periodic_key_4_enabled,
        minimap_cruise_periodic_key_4=fallback.minimap_cruise_periodic_key_4,
        minimap_cruise_periodic_key_4_interval_seconds=fallback.minimap_cruise_periodic_key_4_interval_seconds,
        minimap_cruise_periodic_key_5_enabled=fallback.minimap_cruise_periodic_key_5_enabled,
        minimap_cruise_periodic_key_5=fallback.minimap_cruise_periodic_key_5,
        minimap_cruise_periodic_key_5_interval_seconds=fallback.minimap_cruise_periodic_key_5_interval_seconds,
        console_collapsed=fallback.console_collapsed,
        combo_group_collapsed=fallback.combo_group_collapsed,
        minimap_cruise_group_collapsed=fallback.minimap_cruise_group_collapsed,
        compact_experience_mode=fallback.compact_experience_mode,
        window_topmost=fallback.window_topmost,
        full_panel_window_x=fallback.full_panel_window_x,
        full_panel_window_y=fallback.full_panel_window_y,
        compact_experience_window_x=fallback.compact_experience_window_x,
        compact_experience_window_y=fallback.compact_experience_window_y,
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
        hp_cooldown_seconds=_read_float(
            raw,
            "hp_cooldown_seconds",
            settings.hp_cooldown_seconds,
            POTION_MIN_COOLDOWN_SECONDS,
            60.0,
        ),
        mp_cooldown_seconds=_read_float(
            raw,
            "mp_cooldown_seconds",
            settings.mp_cooldown_seconds,
            POTION_MIN_COOLDOWN_SECONDS,
            60.0,
        ),
        hp_continuous_enabled=_read_bool(raw, "hp_continuous_enabled", settings.hp_continuous_enabled),
        mp_continuous_enabled=_read_bool(raw, "mp_continuous_enabled", settings.mp_continuous_enabled),
        hp_continuous_stop_margin_percent=_read_float(
            raw,
            "hp_continuous_stop_margin_percent",
            settings.hp_continuous_stop_margin_percent,
            0.0,
            POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
        ),
        mp_continuous_stop_margin_percent=_read_float(
            raw,
            "mp_continuous_stop_margin_percent",
            settings.mp_continuous_stop_margin_percent,
            0.0,
            POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
        ),
        rb_jump_key=_read_string(raw, "rb_jump_key", settings.rb_jump_key),
        rb_skill_key=_read_string(raw, "rb_skill_key", settings.rb_skill_key),
        rb_controller_button=normalize_controller_button_name(raw.get("rb_controller_button"), settings.rb_controller_button),
        rb_skill_delay_seconds=_read_float(raw, "rb_skill_delay_seconds", settings.rb_skill_delay_seconds, 0.0, 10.0),
        rb_jump_interval_seconds=_read_float(
            raw,
            "rb_jump_interval_seconds",
            settings.rb_jump_interval_seconds,
            COMBO_JUMP_INTERVAL_MIN_SECONDS,
            COMBO_JUMP_INTERVAL_MAX_SECONDS,
        ),
        lb_enabled=_read_bool(raw, "lb_enabled", settings.lb_enabled),
        lb_jump_key=_read_string(raw, "lb_jump_key", settings.lb_jump_key),
        lb_skill_key=_read_string(raw, "lb_skill_key", settings.lb_skill_key),
        lb_controller_button=normalize_controller_button_name(raw.get("lb_controller_button"), settings.lb_controller_button),
        lb_skill_delay_seconds=_read_float(raw, "lb_skill_delay_seconds", settings.lb_skill_delay_seconds, 0.0, 10.0),
        combo_slots=raw.get("combo_slots") if isinstance(raw.get("combo_slots"), dict) else None,
        exp_efficiency_enabled=_read_bool(raw, "exp_efficiency_enabled", settings.exp_efficiency_enabled),
        toggle_hotkey=_read_string(raw, "toggle_hotkey", settings.toggle_hotkey),
        emergency_stop_hotkey=_read_string(raw, "emergency_stop_hotkey", settings.emergency_stop_hotkey),
        experience_toggle_hotkey=_read_string(
            raw,
            "experience_toggle_hotkey",
            settings.experience_toggle_hotkey,
        ),
        experience_reset_hotkey=_read_string(
            raw,
            "experience_reset_hotkey",
            settings.experience_reset_hotkey,
        ),
        character_stat_hotkey=_read_string(raw, "character_stat_hotkey", settings.character_stat_hotkey),
        pickup_toggle_hotkey=_read_optional_string(raw, "pickup_toggle_hotkey", settings.pickup_toggle_hotkey),
        pickup_key=_read_optional_string(raw, "pickup_key", settings.pickup_key),
        minimap_cruise_toggle_hotkey=_read_optional_string(
            raw,
            "minimap_cruise_toggle_hotkey",
            settings.minimap_cruise_toggle_hotkey,
        ),
        minimap_cruise_attack_key=_read_string(
            raw,
            "minimap_cruise_attack_key",
            settings.minimap_cruise_attack_key,
        ),
        minimap_cruise_left_x=_read_optional_int(raw, "minimap_cruise_left_x", settings.minimap_cruise_left_x),
        minimap_cruise_right_x=_read_optional_int(raw, "minimap_cruise_right_x", settings.minimap_cruise_right_x),
        minimap_cruise_detect_y=_read_optional_int(raw, "minimap_cruise_detect_y", settings.minimap_cruise_detect_y),
        minimap_cruise_detect_band_height=_read_int(
            raw,
            "minimap_cruise_detect_band_height",
            settings.minimap_cruise_detect_band_height,
            MINIMAP_CRUISE_MIN_DETECT_BAND_HEIGHT,
            MINIMAP_CRUISE_MAX_DETECT_BAND_HEIGHT,
        ),
        minimap_cruise_last_direction=normalize_minimap_cruise_direction(
            raw.get("minimap_cruise_last_direction"),
            settings.minimap_cruise_last_direction,
        ),
        minimap_cruise_pre_boundary_skill_enabled=_read_bool(
            raw,
            "minimap_cruise_pre_boundary_skill_enabled",
            settings.minimap_cruise_pre_boundary_skill_enabled,
        ),
        minimap_cruise_pre_boundary_skill_key=_read_string(
            raw,
            "minimap_cruise_pre_boundary_skill_key",
            settings.minimap_cruise_pre_boundary_skill_key,
        ),
        minimap_cruise_pre_boundary_distance=_read_int(
            raw,
            "minimap_cruise_pre_boundary_distance",
            settings.minimap_cruise_pre_boundary_distance,
            MINIMAP_CRUISE_MIN_PRE_BOUNDARY_SKILL_DISTANCE,
            MINIMAP_CRUISE_MAX_PRE_BOUNDARY_SKILL_DISTANCE,
        ),
        minimap_cruise_stationary_skill_key=_read_string(
            raw,
            "minimap_cruise_stationary_skill_key",
            settings.minimap_cruise_stationary_skill_key,
        ),
        minimap_cruise_lie_detector_alert_volume_percent=_read_int(
            raw,
            "minimap_cruise_lie_detector_alert_volume_percent",
            settings.minimap_cruise_lie_detector_alert_volume_percent,
            MINIMAP_CRUISE_MIN_ALERT_VOLUME_PERCENT,
            MINIMAP_CRUISE_MAX_ALERT_VOLUME_PERCENT,
        ),
        minimap_cruise_periodic_key_1_enabled=_read_bool(
            raw,
            "minimap_cruise_periodic_key_1_enabled",
            settings.minimap_cruise_periodic_key_1_enabled,
        ),
        minimap_cruise_periodic_key_1=_read_string(
            raw,
            "minimap_cruise_periodic_key_1",
            settings.minimap_cruise_periodic_key_1,
        ),
        minimap_cruise_periodic_key_1_interval_seconds=_read_float(
            raw,
            "minimap_cruise_periodic_key_1_interval_seconds",
            settings.minimap_cruise_periodic_key_1_interval_seconds,
            MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
            MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
        ),
        minimap_cruise_periodic_key_2_enabled=_read_bool(
            raw,
            "minimap_cruise_periodic_key_2_enabled",
            settings.minimap_cruise_periodic_key_2_enabled,
        ),
        minimap_cruise_periodic_key_2=_read_string(
            raw,
            "minimap_cruise_periodic_key_2",
            settings.minimap_cruise_periodic_key_2,
        ),
        minimap_cruise_periodic_key_2_interval_seconds=_read_float(
            raw,
            "minimap_cruise_periodic_key_2_interval_seconds",
            settings.minimap_cruise_periodic_key_2_interval_seconds,
            MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
            MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
        ),
        minimap_cruise_periodic_key_3_enabled=_read_bool(
            raw,
            "minimap_cruise_periodic_key_3_enabled",
            settings.minimap_cruise_periodic_key_3_enabled,
        ),
        minimap_cruise_periodic_key_3=_read_string(
            raw,
            "minimap_cruise_periodic_key_3",
            settings.minimap_cruise_periodic_key_3,
        ),
        minimap_cruise_periodic_key_3_interval_seconds=_read_float(
            raw,
            "minimap_cruise_periodic_key_3_interval_seconds",
            settings.minimap_cruise_periodic_key_3_interval_seconds,
            MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
            MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
        ),
        minimap_cruise_periodic_key_4_enabled=_read_bool(
            raw,
            "minimap_cruise_periodic_key_4_enabled",
            settings.minimap_cruise_periodic_key_4_enabled,
        ),
        minimap_cruise_periodic_key_4=_read_string(
            raw,
            "minimap_cruise_periodic_key_4",
            settings.minimap_cruise_periodic_key_4,
        ),
        minimap_cruise_periodic_key_4_interval_seconds=_read_float(
            raw,
            "minimap_cruise_periodic_key_4_interval_seconds",
            settings.minimap_cruise_periodic_key_4_interval_seconds,
            MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
            MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
        ),
        minimap_cruise_periodic_key_5_enabled=_read_bool(
            raw,
            "minimap_cruise_periodic_key_5_enabled",
            settings.minimap_cruise_periodic_key_5_enabled,
        ),
        minimap_cruise_periodic_key_5=_read_string(
            raw,
            "minimap_cruise_periodic_key_5",
            settings.minimap_cruise_periodic_key_5,
        ),
        minimap_cruise_periodic_key_5_interval_seconds=_read_float(
            raw,
            "minimap_cruise_periodic_key_5_interval_seconds",
            settings.minimap_cruise_periodic_key_5_interval_seconds,
            MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
            MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
        ),
        console_collapsed=_read_bool(raw, "console_collapsed", settings.console_collapsed),
        combo_group_collapsed=_read_bool(raw, "combo_group_collapsed", settings.combo_group_collapsed),
        minimap_cruise_group_collapsed=_read_bool(
            raw,
            "minimap_cruise_group_collapsed",
            settings.minimap_cruise_group_collapsed,
        ),
        compact_experience_mode=_read_bool(raw, "compact_experience_mode", settings.compact_experience_mode),
        window_topmost=_read_bool(raw, "window_topmost", settings.window_topmost),
        full_panel_window_x=_read_optional_int(raw, "full_panel_window_x", settings.full_panel_window_x),
        full_panel_window_y=_read_optional_int(raw, "full_panel_window_y", settings.full_panel_window_y),
        compact_experience_window_x=_read_optional_int(
            raw,
            "compact_experience_window_x",
            settings.compact_experience_window_x,
        ),
        compact_experience_window_y=_read_optional_int(
            raw,
            "compact_experience_window_y",
            settings.compact_experience_window_y,
        ),
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
