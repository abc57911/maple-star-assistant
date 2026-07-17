from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ..gui_theme import *  # noqa: F401,F403
from .contracts import ConsolePageContext, ConsolePageRefs, ConsoleTextRefs


def build_console_page(parent: ctk.CTkFrame, context: ConsolePageContext) -> ConsolePageRefs:
    widgets = context.widgets
    section, header, body = widgets.section(
        parent,
        "",
        row=1,
        column=0,
        sticky="nsew",
        padx=0,
        pady=0,
    )
    section.grid_propagate(False)
    title_label = widgets.title_label(header, "Console")
    title_label.grid(row=0, column=0, sticky="w", padx=8, pady=4)
    clear_button = widgets.button(header, "清除", context.clear_console, width=58)
    clear_button.grid(row=0, column=98, sticky="e", padx=(8, 0), pady=4)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    container = ctk.CTkFrame(
        body,
        height=620,
        width=CONSOLE_MIN_WIDTH,
        fg_color=CONSOLE_BG,
        border_width=1,
        border_color=BUTTON_BORDER,
        corner_radius=CONTROL_RADIUS,
    )
    container.grid(row=0, column=0, sticky="nsew")
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)
    return ConsolePageRefs(section, title_label, clear_button, body, container)


def build_console_text(parent: ctk.CTkFrame) -> ConsoleTextRefs:
    text = tk.Text(
        parent,
        height=1,
        width=1,
        state="disabled",
        wrap="word",
        bg=CONSOLE_BG,
        fg=CONSOLE_TEXT,
        insertbackground=CONSOLE_TEXT,
        selectbackground=SECONDARY_BUTTON_BG,
        selectforeground=HEADER_TEXT,
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        padx=10,
        pady=8,
        font=CONSOLE_FONT,
    )
    scrollbar = ctk.CTkScrollbar(
        parent,
        command=text.yview,
        button_color=SECONDARY_BUTTON_BG,
        button_hover_color=SECONDARY_BUTTON_HOVER,
    )
    text.configure(yscrollcommand=scrollbar.set)
    text.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
    scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
    return ConsoleTextRefs(text, scrollbar)
