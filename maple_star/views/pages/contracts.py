from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


Callback = Callable[..., Any]


@dataclass(frozen=True)
class PageWidgets:
    section: Callback
    title_label: Callback
    label: Callback
    entry: Callback
    checkbox: Callback
    button: Callback
    responsive_columns: Callback
    combo: Callback | None = None


class MonitorWidgets(Protocol):
    section: Callback
    title_label: Callback
    label: Callback
    checkbox: Callback
    button: Callback
    responsive_columns: Callback


class MonitorControlsWidgets(Protocol):
    section: Callback
    label: Callback
    entry: Callback
    checkbox: Callback
    button: Callback
    combo: Callback | None


class PotionWidgets(Protocol):
    section: Callback
    title_label: Callback
    label: Callback
    entry: Callback
    checkbox: Callback
    button: Callback
    responsive_columns: Callback


class MinimapWidgets(Protocol):
    section: Callback
    title_label: Callback
    label: Callback
    entry: Callback
    button: Callback
    responsive_columns: Callback


class ComboWidgets(Protocol):
    section: Callback
    title_label: Callback
    label: Callback
    entry: Callback
    checkbox: Callback
    button: Callback
    combo: Callback | None
    responsive_columns: Callback


class ConsoleWidgets(Protocol):
    section: Callback
    title_label: Callback
    label: Callback
    button: Callback


@dataclass(frozen=True)
class MonitorPageContext:
    widgets: MonitorWidgets
    exp_enabled: Any
    exp_current_status: Any
    exp_eta_status: Any
    exp_rate_10m_status: Any
    exp_rate_1h_status: Any
    exp_10m_gain_status: Any
    exp_quality_status: Any
    exp_reader_status: Any
    hp_detection_status: Any
    mp_detection_status: Any
    runtime_script_status: Any
    runtime_foreground_status: Any
    runtime_status_message: Any
    reset_experience: Callback
    toggle_compact_mode: Callback
    toggle_topmost: Callback
    refresh_bar_preview: Callback
    bind_checkbox_label: Callback
    monitor_is_active: Callback


@dataclass(frozen=True)
class MonitorPageRefs:
    monitor_frame: Any
    exp_section: Any
    detection_section: Any
    bar_preview_labels: dict[str, Any]
    monitor_responsive_relayout: Callback
    panel_mode_button: Any
    topmost_button: Any
    full_panel_widgets: tuple[Any, ...]


@dataclass(frozen=True)
class MonitorControlsContext:
    widgets: MonitorControlsWidgets
    active_profile: Any
    toggle_hotkey: Any
    emergency_stop_hotkey: Any
    experience_toggle_hotkey: Any
    experience_reset_hotkey: Any
    character_stat_hotkey: Any
    pickup_toggle_hotkey: Any
    pickup_key: Any
    pickup_enabled: Any
    detect_key: Callback
    toggle_pickup: Callback
    profile_names: Callable[[], list[str]]
    switch_profile: Callback
    create_profile: Callback
    delete_profile: Callback
    import_settings: Callback
    export_settings: Callback


@dataclass(frozen=True)
class MonitorControlsRefs:
    hotkey_section: Any
    profile_section: Any
    profile_select: Any
    full_panel_widgets: tuple[Any, ...]


@dataclass(frozen=True)
class PotionKindContext:
    title: str
    capture_label: str
    enabled: Any
    threshold: Any
    threshold_text: Any
    key: Any
    cooldown: Any
    continuous: Any
    stop_margin: Any
    current: Any


@dataclass(frozen=True)
class PotionPageContext:
    widgets: PotionWidgets
    auto_drink_enabled: Any
    hp: PotionKindContext
    mp: PotionKindContext
    toggle_auto_drink: Callback
    detect_key: Callback
    apply_percent: Callback


@dataclass(frozen=True)
class PotionPageRefs:
    header: Any
    cards: Any
    hp_section: Any
    mp_section: Any
    hp_threshold_entry: Any
    mp_threshold_entry: Any


@dataclass(frozen=True)
class MinimapPageContext:
    widgets: MinimapWidgets
    toggle_hotkey: Any
    attack_key: Any
    boundary_status: Any
    detect_key: Callback
    setup_boundary: Callback
    open_extra_settings: Callback
    toggle_collapsed: Callback


@dataclass(frozen=True)
class MinimapPageRefs:
    section: Any
    body: Any
    title_label: Any
    toggle_entry: Any
    attack_entry: Any
    primary_frame: Any
    actions_frame: Any


@dataclass(frozen=True)
class ComboSlotContext:
    slot_id: str
    enabled: Any
    controller_button: Any
    script: Any
    jump_key: Any
    skill_key: Any
    attack_key: Any
    attack_start_delay: Any
    attack_hold: Any
    skill_delay: Any
    jump_interval: Any
    description: Callback


@dataclass(frozen=True)
class ComboPageContext:
    widgets: ComboWidgets
    slot_a: ComboSlotContext
    slot_b: ComboSlotContext
    toggle_collapsed: Callback
    bind_checkbox_label: Callback
    info_icon: Callback
    detect_key: Callback
    script_changed: Callback
    step_seconds: Callback


@dataclass(frozen=True)
class ComboSlotRefs:
    field_flow: Any
    skill_key_fields: tuple[Any, ...]
    attack_key_fields: tuple[Any, ...]
    skill_delay_fields: tuple[Any, ...]
    attack_start_delay_fields: tuple[Any, ...]
    attack_hold_fields: tuple[Any, ...]
    jump_interval_fields: tuple[Any, ...]


@dataclass(frozen=True)
class ComboPageRefs:
    section: Any
    body: Any
    title_label: Any
    slot_a_card: Any
    slot_b_card: Any
    slots: dict[str, ComboSlotRefs]


@dataclass(frozen=True)
class ConsolePageContext:
    widgets: ConsoleWidgets
    clear_console: Callback


@dataclass(frozen=True)
class ConsolePageRefs:
    section: Any
    title_label: Any
    clear_button: Any
    frame: Any
    container: Any


@dataclass(frozen=True)
class ConsoleTextRefs:
    text: Any
    scrollbar: Any
