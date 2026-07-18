from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldText:
    label: str
    description: str = ""


FIELD_TEXT: dict[str, FieldText] = {
    "toggle_hotkey": FieldText("自動喝水快捷鍵"),
    "emergency_stop_hotkey": FieldText("緊急停止快捷鍵"),
    "experience_toggle_hotkey": FieldText("EXP 統計開關快捷鍵"),
    "experience_reset_hotkey": FieldText("重置 EXP 統計快捷鍵"),
    "character_stat_hotkey": FieldText("角色能力值快捷鍵"),
    "pickup_toggle_hotkey": FieldText("自動撿取開關快捷鍵"),
    "pickup_key": FieldText("撿取按鍵"),
    "exp_efficiency_enabled": FieldText("啟用 EXP 效率統計"),
    "hp_enabled": FieldText("啟用 HP 自動補充"),
    "mp_enabled": FieldText("啟用 MP 自動補充"),
    "hp_threshold_percent": FieldText("HP 觸發門檻（%）"),
    "mp_threshold_percent": FieldText("MP 觸發門檻（%）"),
    "hp_key": FieldText("HP 補充按鍵"),
    "mp_key": FieldText("MP 補充按鍵"),
    "hp_cooldown_seconds": FieldText("HP 冷卻時間（秒）"),
    "mp_cooldown_seconds": FieldText("MP 冷卻時間（秒）"),
    "hp_continuous_enabled": FieldText("啟用 HP 連續補充"),
    "mp_continuous_enabled": FieldText("啟用 MP 連續補充"),
    "hp_continuous_stop_margin_percent": FieldText("HP 連續補充停止餘量（%）"),
    "mp_continuous_stop_margin_percent": FieldText("MP 連續補充停止餘量（%）"),
    "minimap_cruise_toggle_hotkey": FieldText("巡航開關快捷鍵"),
    "minimap_cruise_attack_key": FieldText("巡航攻擊按鍵"),
    "minimap_cruise_left_x": FieldText("左側邊界 X"),
    "minimap_cruise_right_x": FieldText("右側邊界 X"),
    "minimap_cruise_detect_y": FieldText("偵測線 Y"),
    "minimap_cruise_detect_band_height": FieldText("偵測帶高度"),
    "minimap_cruise_last_direction": FieldText("上次移動方向"),
    "minimap_cruise_pre_boundary_skill_enabled": FieldText("啟用接近邊界技能"),
    "minimap_cruise_pre_boundary_skill_key": FieldText("接近邊界技能按鍵"),
    "minimap_cruise_pre_boundary_distance": FieldText("接近邊界距離"),
    "minimap_cruise_stationary_skill_key": FieldText("停滯恢復技能按鍵"),
    "minimap_cruise_stationary_min_forward_pixels": FieldText("最小前進像素"),
    "minimap_cruise_lie_detector_alert_volume_percent": FieldText("測謊警示音量（%）"),
    "rb_enabled": FieldText("啟用 RB 組合"),
    "rb_jump_key": FieldText("RB 跳躍按鍵"),
    "rb_skill_key": FieldText("RB 技能按鍵"),
    "rb_controller_button": FieldText("RB 手把按鈕"),
    "rb_skill_delay_seconds": FieldText("RB 技能延遲（秒）"),
    "rb_jump_interval_seconds": FieldText("RB 跳躍間隔（秒）"),
    "lb_enabled": FieldText("啟用 LB 組合"),
    "lb_jump_key": FieldText("LB 跳躍按鍵"),
    "lb_skill_key": FieldText("LB 技能按鍵"),
    "lb_controller_button": FieldText("LB 手把按鈕"),
    "lb_skill_delay_seconds": FieldText("LB 技能延遲（秒）"),
    "console_collapsed": FieldText("啟動時收合診斷紀錄"),
    "combo_group_collapsed": FieldText("啟動時收合手把組合"),
    "minimap_cruise_group_collapsed": FieldText("啟動時收合巡航設定"),
    "compact_experience_mode": FieldText("使用精簡 EXP 視窗"),
    "window_topmost": FieldText("視窗保持最上層"),
    "full_panel_window_x": FieldText("完整面板 X 座標"),
    "full_panel_window_y": FieldText("完整面板 Y 座標"),
    "compact_experience_window_x": FieldText("精簡 EXP 視窗 X 座標"),
    "compact_experience_window_y": FieldText("精簡 EXP 視窗 Y 座標"),
}

for _index in range(1, 6):
    FIELD_TEXT[f"minimap_cruise_periodic_key_{_index}_enabled"] = FieldText(f"啟用週期按鍵 {_index}")
    FIELD_TEXT[f"minimap_cruise_periodic_key_{_index}"] = FieldText(f"週期按鍵 {_index}")
    FIELD_TEXT[f"minimap_cruise_periodic_key_{_index}_interval_seconds"] = FieldText(
        f"週期按鍵 {_index} 間隔（秒）"
    )


COMBO_COLUMN_LABELS = {
    "slot": "組合",
    "enabled": "啟用",
    "script_id": "執行腳本",
    "trigger_button": "觸發按鈕",
    "jump_key": "跳躍按鍵",
    "skill_key": "技能按鍵",
    "attack_key": "攻擊按鍵",
    "attack_start_delay_seconds": "攻擊啟動延遲（秒）",
    "attack_hold_seconds": "攻擊按住時間（秒）",
    "skill_delay_seconds": "技能延遲（秒）",
    "jump_interval_seconds": "跳躍間隔（秒）",
}

SCRIPT_LABELS = {
    "repeating_jump_skill": "重複跳躍技能",
    "hold_jump_attack_loop": "按住跳躍攻擊循環",
}

DIRECTION_LABELS = {"left": "左", "right": "右"}

RUNTIME_VALUE_LABELS = {
    "active": "作用中",
    "inactive": "未作用",
    "running": "執行中",
    "stopped": "已停止",
    "idle": "閒置",
    "enabled": "啟用",
    "disabled": "停用",
    "true": "啟用",
    "false": "停用",
    "none": "無",
    "clear": "無",
}


def field_text(name: str) -> FieldText:
    try:
        return FIELD_TEXT[name]
    except KeyError as exc:
        raise KeyError(f"缺少介面繁中欄位定義：{name}") from exc


def display_value(field: str, value: object) -> object:
    if field == "minimap_cruise_last_direction":
        return DIRECTION_LABELS.get(str(value), value)
    if field == "script_id":
        return SCRIPT_LABELS.get(str(value), value)
    return value


def runtime_value(value: object) -> str:
    text = str(value)
    return RUNTIME_VALUE_LABELS.get(text.strip().lower(), text)


__all__ = [
    "COMBO_COLUMN_LABELS",
    "DIRECTION_LABELS",
    "FIELD_TEXT",
    "SCRIPT_LABELS",
    "RUNTIME_VALUE_LABELS",
    "FieldText",
    "display_value",
    "field_text",
    "runtime_value",
]
