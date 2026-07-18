from __future__ import annotations

import customtkinter as ctk

from ..gui_theme import (
    ACCENT_GREEN,
    EXP_FONT,
    EXP_MONO_FONT,
    HOTKEY_ENTRY_WIDTH,
    HP_RED,
    MP_BLUE,
    MUTED_TEXT,
    PANEL_BG_ALT,
    PANEL_BORDER,
    PROFILE_COMBO_WIDTH,
    SECTION_RADIUS,
    SMALL_FONT,
    WARNING_YELLOW,
)
from .contracts import (
    MonitorControlsContext,
    MonitorControlsRefs,
    MonitorPageContext,
    MonitorPageRefs,
)


def build_monitor_page(parent: ctk.CTkFrame, context: MonitorPageContext) -> MonitorPageRefs:
    widgets = context.widgets
    monitor_frame = ctk.CTkFrame(parent, fg_color="transparent")
    monitor_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    monitor_frame.columnconfigure(0, weight=3, uniform="monitor")
    monitor_frame.columnconfigure(1, weight=2, uniform="monitor")

    exp_section, exp_title, exp_frame = widgets.section(
        monitor_frame, "", row=0, column=0, sticky="nsew", padx=(0, 8), pady=0
    )
    widgets.checkbox(exp_title, "", context.exp_enabled, width=20).grid(
        row=0, column=0, sticky="w", padx=(8, 0), pady=4
    )
    exp_title_label = widgets.title_label(exp_title, "經驗計算")
    exp_title_label.grid(row=0, column=1, sticky="w", padx=(2, 0), pady=4)
    context.bind_checkbox_label(exp_title_label, context.exp_enabled)
    actions = ctk.CTkFrame(exp_title, fg_color="transparent")
    actions.grid(row=0, column=99, sticky="e", padx=8, pady=4)
    widgets.button(actions, "重置", context.reset_experience, width=64).grid(
        row=0, column=0, sticky="w", padx=(0, 6)
    )
    panel_mode_button = widgets.button(actions, "經驗模式", context.toggle_compact_mode, width=82)
    panel_mode_button.grid(row=0, column=1, sticky="w", padx=(0, 6))
    topmost_button = widgets.button(actions, "置頂", context.toggle_topmost, width=76)
    topmost_button.grid(row=0, column=2, sticky="w")
    exp_frame.columnconfigure(0, weight=1)
    widgets.label(exp_frame, textvariable=context.exp_current_status, font=EXP_MONO_FONT, color=ACCENT_GREEN).grid(
        row=0, column=0, sticky="w", padx=(0, 8), pady=(4, 0)
    )
    widgets.label(exp_frame, textvariable=context.exp_eta_status, color=WARNING_YELLOW, font=EXP_FONT).grid(
        row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 2)
    )
    rate_frame = ctk.CTkFrame(exp_frame, fg_color="transparent")
    rate_frame.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=(0, 2))
    for column in range(3):
        rate_frame.columnconfigure(column, weight=1, uniform="exp_rate")
    for column, variable in enumerate(
        (context.exp_rate_10m_status, context.exp_rate_1h_status, context.exp_10m_gain_status)
    ):
        widgets.label(rate_frame, textvariable=variable, font=EXP_MONO_FONT).grid(
            row=0, column=column, sticky="w"
        )
    widgets.label(exp_frame, textvariable=context.exp_quality_status, color=MUTED_TEXT, font=EXP_FONT).grid(
        row=3, column=0, sticky="w", padx=(0, 8)
    )
    widgets.label(exp_frame, textvariable=context.exp_reader_status, color=MUTED_TEXT, font=EXP_FONT).grid(
        row=4, column=0, sticky="w", padx=(0, 8), pady=(2, 0)
    )

    detection_section, detection_title, detection_frame = widgets.section(
        monitor_frame, "", row=0, column=1, sticky="nsew", pady=0
    )
    relayout = widgets.responsive_columns(
        monitor_frame,
        exp_section,
        detection_section,
        active=context.monitor_is_active,
        wide_weights=(3, 2),
        wide_uniform="monitor",
    )
    widgets.title_label(detection_title, "偵測診斷").grid(
        row=0, column=0, sticky="w", padx=(8, 0), pady=4
    )
    widgets.button(detection_title, "刷新預覽", context.refresh_bar_preview, width=82).grid(
        row=0, column=1, sticky="w", padx=(8, 0), pady=4
    )
    detection_frame.columnconfigure(0, weight=1)
    widgets.label(detection_frame, textvariable=context.hp_detection_status, color=HP_RED, font=SMALL_FONT).grid(
        row=0, column=0, sticky="w", pady=(4, 2)
    )
    hp_preview = widgets.label(detection_frame, "尚未刷新預覽", color=MUTED_TEXT)
    hp_preview.grid(row=1, column=0, sticky="w", pady=(0, 6))
    widgets.label(detection_frame, textvariable=context.mp_detection_status, color=MP_BLUE, font=SMALL_FONT).grid(
        row=2, column=0, sticky="w", pady=(2, 2)
    )
    mp_preview = widgets.label(detection_frame, "尚未刷新預覽", color=MUTED_TEXT)
    mp_preview.grid(row=3, column=0, sticky="w", pady=(0, 6))

    runtime_frame = ctk.CTkFrame(
        parent,
        fg_color=PANEL_BG_ALT,
        corner_radius=SECTION_RADIUS,
        border_width=1,
        border_color=PANEL_BORDER,
    )
    runtime_frame.grid(row=3, column=0, sticky="ew", pady=(8, 6))
    for column in range(3):
        runtime_frame.columnconfigure(column, weight=1)
    widgets.label(runtime_frame, textvariable=context.runtime_script_status, color=ACCENT_GREEN).grid(
        row=0, column=0, sticky="w", padx=(10, 12), pady=8
    )
    widgets.label(runtime_frame, textvariable=context.runtime_foreground_status).grid(
        row=0, column=1, sticky="w", padx=(0, 12), pady=8
    )
    widgets.label(runtime_frame, textvariable=context.runtime_status_message, color=WARNING_YELLOW).grid(
        row=0, column=2, sticky="w", padx=(0, 12), pady=8
    )
    return MonitorPageRefs(
        monitor_frame,
        exp_section,
        detection_section,
        {"hp": hp_preview, "mp": mp_preview},
        relayout,
        panel_mode_button,
        topmost_button,
        (detection_section, runtime_frame),
    )


def build_monitor_controls(parent: ctk.CTkFrame, context: MonitorControlsContext) -> MonitorControlsRefs:
    widgets = context.widgets
    hotkey_section, _header, hotkeys = widgets.section(parent, "全域熱鍵", row=0, pady=(0, 0))
    for column in range(10):
        hotkeys.columnconfigure(column, weight=0)
    hotkeys.columnconfigure(10, weight=1)

    def key_entry(row: int, column: int, label: str, variable: object, capture_label: str) -> None:
        widgets.label(hotkeys, label).grid(row=row, column=column, sticky="w", padx=(0, 4), pady=6)
        entry = widgets.entry(hotkeys, variable, width=HOTKEY_ENTRY_WIDTH, justify="center")
        entry.grid(row=row, column=column + 1, sticky="w", padx=(0, 8), pady=6)
        entry.bind("<Button-1>", lambda event: context.detect_key(event, variable, capture_label))

    key_entry(0, 0, "自動喝水", context.toggle_hotkey, "自動喝水熱鍵")
    key_entry(0, 4, "總開關", context.emergency_stop_hotkey, "總開關熱鍵")
    key_entry(0, 7, "經驗統計", context.experience_toggle_hotkey, "經驗統計熱鍵")
    key_entry(1, 7, "重置統計", context.experience_reset_hotkey, "重置統計熱鍵")
    key_entry(1, 9, "能力值", context.character_stat_hotkey, "能力值快捷鍵")
    key_entry(1, 0, "拾取", context.pickup_toggle_hotkey, "拾取熱鍵")
    widgets.checkbox(
        hotkeys, "自動拾取", context.pickup_enabled, width=86, command=context.toggle_pickup
    ).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=(0, 6))
    key_entry(1, 4, "拾取鍵", context.pickup_key, "拾取鍵")

    profile_section, _header, profile = widgets.section(parent, "設定檔", row=1)
    for column in range(7):
        profile.columnconfigure(column, weight=0)
    profile.columnconfigure(2, weight=1)
    widgets.label(profile, "目前").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
    if widgets.combo is None:
        raise RuntimeError("Monitor controls require combo widget factory")
    profile_select = widgets.combo(
        profile,
        textvariable=context.active_profile,
        values=context.profile_names(),
        width=PROFILE_COMBO_WIDTH,
        command=lambda _value: context.switch_profile(),
    )
    profile_select.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
    profile_select.bind("<<ComboboxSelected>>", context.switch_profile)
    for column, (text, command) in enumerate(
        (("新增", context.create_profile), ("刪除", context.delete_profile), ("匯入", context.import_settings), ("匯出", context.export_settings)),
        start=3,
    ):
        padx = (0, 4) if column < 6 else 0
        widgets.button(profile, text, command, width=64).grid(
            row=0, column=column, sticky="w", padx=padx, pady=(0, 4)
        )
    return MonitorControlsRefs(hotkey_section, profile_section, profile_select, (hotkey_section, profile_section))
