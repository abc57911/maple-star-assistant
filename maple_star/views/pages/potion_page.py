from __future__ import annotations

import customtkinter as ctk

from ..gui_theme import *  # noqa: F401,F403
from .contracts import PotionKindContext, PotionPageContext, PotionPageRefs


def _build_potion_card(
    parent: ctk.CTkFrame,
    column: int,
    potion: PotionKindContext,
    context: PotionPageContext,
) -> tuple[ctk.CTkFrame, object]:
    widgets = context.widgets
    section, header, body = widgets.section(
        parent,
        "",
        row=0,
        column=column,
        sticky="nsew",
        padx=(0, 4) if column == 0 else (4, 0),
        pady=0,
    )
    widgets.checkbox(header, potion.title, potion.enabled, width=112).grid(
        row=0, column=0, sticky="w", padx=8, pady=4
    )
    widgets.label(header, textvariable=potion.current, font=MONO_FONT).grid(
        row=0, column=99, sticky="e", padx=8, pady=4
    )
    body.columnconfigure(1, weight=1)
    widgets.label(body, "觸發門檻").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
    scale = ctk.CTkSlider(
        body,
        from_=1,
        to=100,
        variable=potion.threshold,
        command=lambda value: potion.threshold_text.set(f"{float(value):.0f}"),
        height=18,
        fg_color=ENTRY_BG,
        progress_color=ACCENT_BLUE,
        button_color=ACCENT_BLUE,
        button_hover_color=BUTTON_HOVER,
    )
    scale.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)
    threshold_entry = widgets.entry(body, potion.threshold_text, width=PERCENT_ENTRY_WIDTH)
    threshold_entry.grid(row=0, column=2, sticky="w", padx=(0, 4), pady=4)
    widgets.label(body, "%").grid(row=0, column=3, sticky="w", pady=4)

    widgets.label(body, "按鍵").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
    key_entry = widgets.entry(body, potion.key, width=POTION_KEY_ENTRY_WIDTH, justify="center")
    key_entry.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)
    key_entry.bind(
        "<Button-1>",
        lambda event: context.detect_key(event, potion.key, potion.capture_label),
    )
    cooldown = ctk.CTkFrame(body, fg_color="transparent")
    cooldown.grid(row=1, column=2, columnspan=2, sticky="e", pady=4)
    widgets.label(cooldown, "冷卻").grid(row=0, column=0, sticky="w", padx=(0, 4))
    widgets.entry(cooldown, potion.cooldown, width=SECONDS_ENTRY_WIDTH).grid(
        row=0, column=1, sticky="w", padx=(0, 4)
    )
    widgets.label(cooldown, "秒").grid(row=0, column=2, sticky="w")

    continuous = ctk.CTkFrame(body, fg_color="transparent")
    continuous.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 0))
    widgets.checkbox(continuous, "連續補充", potion.continuous, width=94).grid(row=0, column=0, sticky="w")
    widgets.label(continuous, "停止誤差").grid(row=0, column=1, sticky="w", padx=(12, 4))
    widgets.entry(continuous, potion.stop_margin, width=PERCENT_ENTRY_WIDTH).grid(
        row=0, column=2, sticky="w", padx=(0, 4)
    )
    widgets.label(continuous, "%").grid(row=0, column=3, sticky="w")

    threshold_entry.bind("<Return>", lambda _event: context.apply_percent(potion.threshold, potion.threshold_text))
    threshold_entry.bind("<FocusOut>", lambda _event: context.apply_percent(potion.threshold, potion.threshold_text))
    return section, threshold_entry


def build_potion_page(parent: ctk.CTkFrame, context: PotionPageContext) -> PotionPageRefs:
    widgets = context.widgets
    header = ctk.CTkFrame(
        parent,
        fg_color=SECTION_HEADER_BG,
        corner_radius=CONTROL_RADIUS,
        border_width=1,
        border_color=SECTION_HEADER_BORDER,
    )
    header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    header.columnconfigure(99, weight=1)
    widgets.title_label(header, "藥水監控").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    widgets.checkbox(
        header,
        "自動喝水",
        context.auto_drink_enabled,
        width=88,
        command=context.toggle_auto_drink,
    ).grid(row=0, column=98, sticky="e", padx=(8, 8), pady=4)
    cards = ctk.CTkFrame(parent, fg_color="transparent")
    cards.grid(row=1, column=0, sticky="ew")
    cards.columnconfigure(0, weight=1, uniform="potion")
    cards.columnconfigure(1, weight=1, uniform="potion")
    hp_section, hp_threshold_entry = _build_potion_card(cards, 0, context.hp, context)
    mp_section, mp_threshold_entry = _build_potion_card(cards, 1, context.mp, context)
    widgets.responsive_columns(cards, hp_section, mp_section)
    return PotionPageRefs(
        header=header,
        cards=cards,
        hp_section=hp_section,
        mp_section=mp_section,
        hp_threshold_entry=hp_threshold_entry,
        mp_threshold_entry=mp_threshold_entry,
    )
