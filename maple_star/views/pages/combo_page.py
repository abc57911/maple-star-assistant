from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ...models.settings import (
    COMBO_ATTACK_HOLD_MAX_SECONDS,
    COMBO_ATTACK_HOLD_MIN_SECONDS,
    COMBO_ATTACK_START_DELAY_MAX_SECONDS,
    COMBO_ATTACK_START_DELAY_MIN_SECONDS,
    COMBO_JUMP_INTERVAL_MAX_SECONDS,
    COMBO_JUMP_INTERVAL_MIN_SECONDS,
    CONTROLLER_BUTTON_CHOICES,
)
from ..gui_theme import (
    COMBO_COMPACT_CONTROLLER_WIDTH,
    COMBO_COMPACT_KEY_ENTRY_WIDTH,
    COMBO_COMPACT_SECONDS_ENTRY_WIDTH,
    COMBO_SCRIPT_COMBO_WIDTH,
    COMBO_SCRIPT_LABEL_VALUES,
    CONTROL_RADIUS,
    FLOW_GAP_X,
    FLOW_GAP_Y,
    PANEL_BG_ALT,
    PANEL_BORDER,
)
from .contracts import ComboPageContext, ComboPageRefs, ComboSlotContext, ComboSlotRefs


class FlowLayout:
    def __init__(self, parent: tk.Misc, *, gap_x: int = FLOW_GAP_X, gap_y: int = FLOW_GAP_Y) -> None:
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.gap_x = gap_x
        self.gap_y = gap_y
        self.items: list[dict[str, object]] = []
        self.frame.bind("<Configure>", lambda _event: self.layout(), add="+")

    def add(self, widget: tk.Misc, min_width: int) -> None:
        self.items.append({"widget": widget, "min_width": min_width, "visible": True, "last_layout": None})
        self.layout()

    def set_visible(self, widget: tk.Misc, visible: bool) -> None:
        changed = False
        for item in self.items:
            if item["widget"] is widget and item["visible"] != visible:
                item["visible"] = visible
                changed = True
        if changed:
            self.layout()

    def layout(self) -> None:
        width = max(1, self.frame.winfo_width())
        row = 0
        column = 0
        row_width = 0
        for item in self.items:
            widget = item["widget"]
            min_width = int(item["min_width"])
            if not isinstance(widget, tk.Misc):
                continue
            if not item["visible"]:
                if item.get("last_layout") is not None:
                    widget.grid_remove()
                    item["last_layout"] = None
                continue
            next_width = min_width if column == 0 else row_width + self.gap_x + min_width
            if column > 0 and next_width > width:
                row += 1
                column = 0
                row_width = 0
            desired_layout = (row, column)
            if item.get("last_layout") != desired_layout:
                widget.grid(row=row, column=column, sticky="w", padx=(0, self.gap_x), pady=(0, self.gap_y))
                item["last_layout"] = desired_layout
            row_width = min_width if column == 0 else row_width + self.gap_x + min_width
            column += 1


def _combo_title_field(parent: tk.Misc, context: ComboPageContext, slot: ComboSlotContext) -> ctk.CTkFrame:
    field = ctk.CTkFrame(parent, fg_color="transparent")
    context.widgets.checkbox(field, "", slot.enabled, width=20).grid(
        row=0, column=0, sticky="w", padx=0, pady=0
    )
    label = context.widgets.title_label(field, f"組合{slot.slot_id}")
    label.grid(row=0, column=1, sticky="w", padx=(2, 0), pady=0)
    context.bind_checkbox_label(label, slot.enabled)
    return field


def _combo_key_field(parent: tk.Misc, context: ComboPageContext, label: str, key_var: object) -> ctk.CTkFrame:
    field = ctk.CTkFrame(parent, fg_color="transparent")
    context.widgets.label(field, label).grid(row=0, column=0, sticky="w", padx=(0, 2), pady=0)
    entry = context.widgets.entry(field, key_var, width=COMBO_COMPACT_KEY_ENTRY_WIDTH, justify="center")
    entry.grid(row=0, column=1, sticky="w", padx=0, pady=0)
    entry.bind("<Button-1>", lambda event: context.detect_key(event, key_var, label))
    return field


def _combo_controller_field(
    parent: tk.Misc, context: ComboPageContext, label: str, button_var: object
) -> ctk.CTkFrame:
    field = ctk.CTkFrame(parent, fg_color="transparent")
    context.widgets.label(field, label).grid(row=0, column=0, sticky="w", padx=(0, 2), pady=0)
    context.widgets.combo(
        field,
        textvariable=button_var,
        values=CONTROLLER_BUTTON_CHOICES,
        width=COMBO_COMPACT_CONTROLLER_WIDTH,
    ).grid(row=0, column=1, sticky="w", padx=0, pady=0)
    return field


def _combo_script_field(
    parent: tk.Misc, context: ComboPageContext, label: str, script_var: object
) -> ctk.CTkFrame:
    field = ctk.CTkFrame(parent, fg_color="transparent")
    context.widgets.label(field, label).grid(row=0, column=0, sticky="w", padx=(0, 2), pady=0)
    context.widgets.combo(
        field,
        textvariable=script_var,
        values=COMBO_SCRIPT_LABEL_VALUES,
        width=COMBO_SCRIPT_COMBO_WIDTH,
        command=lambda _value: context.script_changed(),
    ).grid(row=0, column=1, sticky="w", padx=0, pady=0)
    return field


def _combo_seconds_field(
    parent: tk.Misc,
    context: ComboPageContext,
    label: str,
    value_var: object,
    minimum: float,
    maximum: float,
) -> ctk.CTkFrame:
    field = ctk.CTkFrame(parent, fg_color="transparent")
    context.widgets.label(field, label).grid(row=0, column=0, sticky="w", padx=(0, 2), pady=0)
    group = ctk.CTkFrame(field, fg_color="transparent")
    group.grid(row=0, column=1, sticky="w", padx=0, pady=0)
    context.widgets.entry(group, value_var, width=COMBO_COMPACT_SECONDS_ENTRY_WIDTH).grid(
        row=0, column=0, sticky="w", padx=(0, 2), pady=0
    )
    context.widgets.label(group, "秒").grid(row=0, column=1, sticky="w", padx=(0, 1), pady=0)
    buttons = ctk.CTkFrame(group, fg_color="transparent")
    buttons.grid(row=0, column=2, sticky="w", padx=(0, 1), pady=0)
    context.widgets.button(
        buttons, "-", lambda: context.step_seconds(value_var, -0.01, minimum, maximum), width=22
    ).grid(row=0, column=0, sticky="w", padx=(0, 2), pady=0)
    context.widgets.button(
        buttons, "+", lambda: context.step_seconds(value_var, 0.01, minimum, maximum), width=22
    ).grid(row=0, column=1, sticky="w", padx=0, pady=0)
    return field


def _build_combo_slot(
    parent: ctk.CTkFrame, row: int, context: ComboPageContext, slot: ComboSlotContext
) -> ComboSlotRefs:
    row_frame = ctk.CTkFrame(parent, fg_color="transparent")
    row_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    row_frame.columnconfigure(0, weight=1)
    header_flow = FlowLayout(row_frame)
    header_flow.frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
    header_flow.add(_combo_title_field(header_flow.frame, context, slot), 82)
    header_flow.add(_combo_controller_field(header_flow.frame, context, "觸發", slot.controller_button), 124)
    header_flow.add(_combo_script_field(header_flow.frame, context, "腳本", slot.script), 176)
    info_field = ctk.CTkFrame(header_flow.frame, fg_color="transparent")
    context.info_icon(info_field, slot.description).grid(row=0, column=0, sticky="w", padx=0, pady=0)
    header_flow.add(info_field, 28)

    field_flow = FlowLayout(row_frame)
    field_flow.frame.grid(row=1, column=0, sticky="ew", pady=(2, 0))
    jump = _combo_key_field(field_flow.frame, context, "跳躍", slot.jump_key)
    skill = _combo_key_field(field_flow.frame, context, "技能", slot.skill_key)
    attack = _combo_key_field(field_flow.frame, context, "攻擊", slot.attack_key)
    skill_delay = _combo_seconds_field(field_flow.frame, context, "延遲", slot.skill_delay, 0.0, 10.0)
    attack_start = _combo_seconds_field(
        field_flow.frame,
        context,
        "起攻",
        slot.attack_start_delay,
        COMBO_ATTACK_START_DELAY_MIN_SECONDS,
        COMBO_ATTACK_START_DELAY_MAX_SECONDS,
    )
    attack_hold = _combo_seconds_field(
        field_flow.frame,
        context,
        "按住",
        slot.attack_hold,
        COMBO_ATTACK_HOLD_MIN_SECONDS,
        COMBO_ATTACK_HOLD_MAX_SECONDS,
    )
    interval = _combo_seconds_field(
        field_flow.frame,
        context,
        "間隔",
        slot.jump_interval,
        COMBO_JUMP_INTERVAL_MIN_SECONDS,
        COMBO_JUMP_INTERVAL_MAX_SECONDS,
    )
    for field, width in (
        (jump, 88),
        (skill, 88),
        (attack, 88),
        (skill_delay, 142),
        (attack_start, 142),
        (attack_hold, 142),
        (interval, 142),
    ):
        field_flow.add(field, width)
    return ComboSlotRefs(
        field_flow,
        (skill,),
        (attack,),
        (skill_delay,),
        (attack_start,),
        (attack_hold,),
        (interval,),
    )


def build_combo_page(parent: ctk.CTkFrame, context: ComboPageContext) -> ComboPageRefs:
    widgets = context.widgets
    section, header, body = widgets.section(parent, "", row=0, sticky="ew", pady=(0, 0))
    title_label = widgets.title_label(header, "組合設定")
    title_label.grid(row=0, column=0, sticky="w", padx=8, pady=4)
    header.bind("<Button-1>", lambda _event: context.toggle_collapsed())
    title_label.bind("<Button-1>", lambda _event: context.toggle_collapsed())
    body.columnconfigure(0, weight=1)
    combos = ctk.CTkFrame(body, fg_color="transparent")
    combos.grid(row=0, column=0, sticky="ew")
    combos.columnconfigure(0, weight=1, uniform="combo")
    combos.columnconfigure(1, weight=1, uniform="combo")
    slot_a_card = ctk.CTkFrame(
        combos,
        fg_color=PANEL_BG_ALT,
        corner_radius=CONTROL_RADIUS,
        border_width=1,
        border_color=PANEL_BORDER,
    )
    slot_b_card = ctk.CTkFrame(
        combos,
        fg_color=PANEL_BG_ALT,
        corner_radius=CONTROL_RADIUS,
        border_width=1,
        border_color=PANEL_BORDER,
    )
    slot_a_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    slot_b_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
    slot_a_card.columnconfigure(0, weight=1)
    slot_b_card.columnconfigure(0, weight=1)
    slots = {
        "A": _build_combo_slot(slot_a_card, 0, context, context.slot_a),
        "B": _build_combo_slot(slot_b_card, 0, context, context.slot_b),
    }
    widgets.responsive_columns(combos, slot_a_card, slot_b_card, wide_uniform="combo")
    return ComboPageRefs(section, body, title_label, slot_a_card, slot_b_card, slots)
