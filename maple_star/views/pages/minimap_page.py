from __future__ import annotations

import customtkinter as ctk

from ..gui_theme import HOTKEY_ENTRY_WIDTH, MUTED_TEXT
from .contracts import MinimapPageContext, MinimapPageRefs


def build_minimap_page(parent: ctk.CTkFrame, context: MinimapPageContext) -> MinimapPageRefs:
    widgets = context.widgets
    section, header, body = widgets.section(parent, "", row=0, sticky="ew", pady=(0, 0))
    title_label = widgets.title_label(header, "小地圖巡航")
    title_label.grid(row=0, column=0, sticky="w", padx=8, pady=4)
    header.bind("<Button-1>", lambda _event: context.toggle_collapsed())
    title_label.bind("<Button-1>", lambda _event: context.toggle_collapsed())
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    primary = ctk.CTkFrame(body, fg_color="transparent")
    actions = ctk.CTkFrame(body, fg_color="transparent")
    primary.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    actions.grid(row=0, column=1, sticky="ew", padx=(8, 0))
    widgets.label(primary, "啟停").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=6)
    toggle_entry = widgets.entry(
        primary,
        context.toggle_hotkey,
        width=HOTKEY_ENTRY_WIDTH,
        justify="center",
        placeholder_text="自訂",
    )
    toggle_entry.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=6)
    toggle_entry.bind(
        "<Button-1>",
        lambda event: context.detect_key(event, context.toggle_hotkey, "巡航啟停熱鍵"),
    )
    widgets.label(primary, "攻擊鍵").grid(row=0, column=2, sticky="w", padx=(8, 4), pady=6)
    attack_entry = widgets.entry(primary, context.attack_key, width=HOTKEY_ENTRY_WIDTH, justify="center")
    attack_entry.grid(row=0, column=3, sticky="w", padx=(0, 8), pady=6)
    attack_entry.bind(
        "<Button-1>",
        lambda event: context.detect_key(event, context.attack_key, "巡航攻擊鍵"),
    )
    widgets.button(actions, "設定邊界", context.setup_boundary, width=88).grid(
        row=0, column=0, sticky="w", padx=(8, 8), pady=6
    )
    widgets.button(actions, "進階設定", context.open_extra_settings, width=88).grid(
        row=0, column=1, sticky="w", padx=(0, 8), pady=6
    )
    widgets.label(actions, textvariable=context.boundary_status, color=MUTED_TEXT).grid(
        row=1, column=0, columnspan=2, sticky="w", padx=(0, 8), pady=6
    )
    widgets.responsive_columns(body, primary, actions)
    return MinimapPageRefs(section, body, title_label, toggle_entry, attack_entry, primary, actions)
