from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from .gui_theme import *  # noqa: F401,F403


class GuiPresentationMixin:
    def _bind_responsive_two_columns(
        self,
        container: ctk.CTkFrame,
        first: ctk.CTkFrame,
        second: ctk.CTkFrame,
        *,
        breakpoint: int = 900,
        active: Callable[[], bool] | None = None,
        wide_weights: tuple[int, int] = (1, 1),
        wide_uniform: str = "",
    ) -> Callable[[], None]:
        layout_state = {"narrow": None}

        def layout(_event: tk.Event | None = None) -> None:
            try:
                if active is not None and not active():
                    layout_state["narrow"] = None
                    return
                narrow = int(container.winfo_width()) < breakpoint
                if layout_state["narrow"] == narrow:
                    return
                layout_state["narrow"] = narrow
                if narrow:
                    container.columnconfigure(0, weight=1, uniform="")
                    container.columnconfigure(1, weight=0, uniform="")
                    first.grid_configure(row=0, column=0, sticky="ew", padx=0, pady=(0, 4))
                    second.grid_configure(row=1, column=0, sticky="ew", padx=0, pady=(4, 0))
                else:
                    container.columnconfigure(0, weight=wide_weights[0], uniform=wide_uniform)
                    container.columnconfigure(1, weight=wide_weights[1], uniform=wide_uniform)
                    first.grid_configure(row=0, column=0, sticky="nsew", padx=(0, 4), pady=0)
                    second.grid_configure(row=0, column=1, sticky="nsew", padx=(4, 0), pady=0)
            except tk.TclError:
                return

        def relayout() -> None:
            layout_state["narrow"] = None
            layout()

        container.bind("<Configure>", layout, add="+")
        self.root.after_idle(relayout)
        return relayout

    def _build_section(
        self,
        parent: ctk.CTkFrame,
        title: str,
        *,
        row: int,
        column: int = 0,
        sticky: str = "ew",
        padx: int | tuple[int, int] = 0,
        pady: int | tuple[int, int] = (8, 0),
    ) -> tuple[ctk.CTkFrame, ctk.CTkFrame, ctk.CTkFrame]:
        section = ctk.CTkFrame(
            parent,
            fg_color=PANEL_BG,
            corner_radius=SECTION_RADIUS,
            border_width=1,
            border_color=PANEL_BORDER,
        )
        section.grid(row=row, column=column, sticky=sticky, padx=padx, pady=pady)
        section.columnconfigure(0, weight=1)
        section.rowconfigure(1, weight=1)
        header = ctk.CTkFrame(
            section,
            fg_color=SECTION_HEADER_BG,
            corner_radius=CONTROL_RADIUS,
            border_width=1,
            border_color=SECTION_HEADER_BORDER,
        )
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        header.columnconfigure(99, weight=1)
        body = ctk.CTkFrame(section, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=SECTION_PAD_X, pady=(0, SECTION_PAD_Y))
        body.columnconfigure(0, weight=1)
        if title:
            self._title_label(header, title).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        return section, header, body

    def _title_label(self, parent: ctk.CTkFrame, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent, text=text, text_color=HEADER_TEXT, font=TITLE_FONT, height=24, anchor="w"
        )

    def _label(
        self,
        parent: ctk.CTkFrame | ctk.CTkToplevel,
        text: str = "",
        *,
        textvariable: tk.StringVar | None = None,
        color: str = BODY_TEXT,
        font: tuple[str, int] | tuple[str, int, str] = UI_FONT,
        width: int = 0,
        anchor: str = "w",
    ) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            textvariable=textvariable,
            text_color=color,
            font=font,
            width=width,
            height=24,
            anchor=anchor,
        )

    def _button(
        self,
        parent: ctk.CTkFrame,
        text: str,
        command: Callable[[], object],
        *,
        width: int = 74,
        primary: bool = False,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=32,
            corner_radius=CONTROL_RADIUS,
            fg_color=BUTTON_BG if primary else SECONDARY_BUTTON_BG,
            hover_color=BUTTON_HOVER if primary else SECONDARY_BUTTON_HOVER,
            text_color=BUTTON_TEXT,
            border_width=1,
            border_color=BUTTON_BORDER,
            font=BUTTON_FONT,
        )

    def _entry(
        self,
        parent: ctk.CTkFrame,
        textvariable: tk.StringVar,
        *,
        width: int = 82,
        justify: str = "left",
        placeholder_text: str = "",
    ) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            textvariable=textvariable,
            width=width,
            height=30,
            corner_radius=CONTROL_RADIUS,
            fg_color=ENTRY_BG,
            border_color=PANEL_BORDER,
            text_color=BODY_TEXT,
            placeholder_text=placeholder_text,
            placeholder_text_color=MUTED_TEXT,
            font=UI_FONT,
            justify=justify,
        )

    def _combo(
        self,
        parent: ctk.CTkFrame,
        *,
        textvariable: tk.StringVar,
        values: list[str] | tuple[str, ...],
        width: int = 110,
        command: Callable[[str], object] | None = None,
    ) -> ctk.CTkComboBox:
        return ctk.CTkComboBox(
            parent,
            variable=textvariable,
            values=list(values),
            command=command,
            width=width,
            height=30,
            state="readonly",
            corner_radius=CONTROL_RADIUS,
            fg_color=ENTRY_BG,
            border_color=PANEL_BORDER,
            button_color=SECONDARY_BUTTON_BG,
            button_hover_color=SECONDARY_BUTTON_HOVER,
            dropdown_fg_color=PANEL_BG_ALT,
            dropdown_hover_color=SECONDARY_BUTTON_HOVER,
            dropdown_text_color=BODY_TEXT,
            text_color=BODY_TEXT,
            font=UI_FONT,
            dropdown_font=UI_FONT,
        )

    def _checkbox(
        self,
        parent: ctk.CTkFrame,
        text: str,
        variable: tk.BooleanVar,
        *,
        width: int = 92,
        command: Callable[[], None] | None = None,
    ) -> ctk.CTkCheckBox:
        return ctk.CTkCheckBox(
            parent,
            text=text,
            variable=variable,
            command=command or self.apply_to_settings,
            width=width,
            height=26,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=5,
            border_width=2,
            border_color=PANEL_BORDER,
            fg_color=ACCENT_GREEN,
            hover_color=SECONDARY_BUTTON_HOVER,
            text_color=BODY_TEXT,
            font=UI_FONT,
        )

    def _bind_checkbox_label(
        self,
        label: ctk.CTkLabel,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
    ) -> ctk.CTkLabel:
        label.configure(cursor="hand2")
        label.bind("<Button-1>", lambda _event: self._toggle_checkbox_label(variable, command))
        return label

    def _toggle_checkbox_label(
        self, variable: tk.BooleanVar, command: Callable[[], None] | None = None
    ) -> str:
        variable.set(not bool(variable.get()))
        (command or self.apply_to_settings)()
        return "break"

    def _info_icon(self, parent: ctk.CTkFrame, text_provider: Callable[[], str]) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent,
            text="🛈",
            width=22,
            height=22,
            corner_radius=12,
            fg_color=INFO_ICON_BG,
            hover_color=INFO_ICON_HOVER,
            border_width=1,
            border_color=SECTION_HEADER_BORDER,
            text_color=HEADER_TEXT,
            font=(FONT_FAMILY, 15, "bold"),
        )
        button.bind("<Enter>", lambda _event: self._handle_tooltip_enter(button, text_provider))
        button.bind("<Leave>", lambda _event: self._schedule_tooltip_hide(button))
        return button

    def _handle_tooltip_enter(self, widget: ctk.CTkBaseClass, text_provider: Callable[[], str]) -> None:
        if self.tooltip_hide_after_id is not None:
            try:
                self.root.after_cancel(self.tooltip_hide_after_id)
            except tk.TclError:
                pass
            self.tooltip_hide_after_id = None
        if self.tooltip_anchor_widget is widget and self.tooltip_window is not None:
            self._ensure_tooltip_pointer_check()
            return
        self._show_tooltip(widget, text_provider())

    def _schedule_tooltip_hide(self, widget: ctk.CTkBaseClass) -> None:
        if self.tooltip_anchor_widget is not widget:
            return
        if self.tooltip_hide_after_id is not None:
            try:
                self.root.after_cancel(self.tooltip_hide_after_id)
            except tk.TclError:
                pass
        self.tooltip_hide_after_id = self.root.after(120, self._hide_tooltip_if_pointer_left)

    def _show_tooltip(self, widget: ctk.CTkBaseClass, text: str) -> None:
        self._hide_tooltip()
        if self.closed:
            return
        tooltip = self._create_auxiliary_window(fg_color=TOOLTIP_BG, overrideredirect=True)
        self.tooltip_window = tooltip
        self.tooltip_windows.append(tooltip)
        self.tooltip_anchor_widget = widget
        bubble = ctk.CTkFrame(
            tooltip,
            fg_color=TOOLTIP_BG,
            corner_radius=8,
            border_width=1,
            border_color=TOOLTIP_BORDER,
        )
        bubble.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(
            bubble,
            text=text,
            text_color=HEADER_TEXT,
            fg_color="transparent",
            font=UI_FONT,
            justify="left",
            wraplength=320,
            anchor="w",
        ).grid(row=0, column=0, sticky="nsew", padx=12, pady=8)
        tooltip.update_idletasks()
        self._prepare_auxiliary_window_for_show(tooltip)
        tooltip.geometry(f"+{widget.winfo_rootx() + widget.winfo_width() + 8}+{widget.winfo_rooty() - 2}")
        tooltip.deiconify()
        self._ensure_tooltip_pointer_check()

    def _hide_tooltip(self) -> None:
        for attribute in ("tooltip_after_id", "tooltip_hide_after_id"):
            after_id = getattr(self, attribute)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        windows = list(self.tooltip_windows)
        if self.tooltip_window is not None and self.tooltip_window not in windows:
            windows.append(self.tooltip_window)
        for window in windows:
            try:
                window.destroy()
            except tk.TclError:
                pass
        self.tooltip_windows.clear()
        self.tooltip_window = None
        self.tooltip_anchor_widget = None

    def _hide_tooltip_if_pointer_left(self) -> None:
        self.tooltip_hide_after_id = None
        if self.tooltip_anchor_widget is None:
            self._hide_tooltip()
            return
        x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        if self._point_inside_widget(self.tooltip_anchor_widget, x, y):
            self._ensure_tooltip_pointer_check()
        else:
            self._hide_tooltip()

    def _ensure_tooltip_pointer_check(self) -> None:
        if self.tooltip_after_id is None and self.tooltip_window is not None:
            self.tooltip_after_id = self.root.after(80, self._check_tooltip_pointer)

    def _check_tooltip_pointer(self) -> None:
        self.tooltip_after_id = None
        if self.tooltip_window is None or self.tooltip_anchor_widget is None:
            return
        x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        if not self._point_inside_widget(self.tooltip_anchor_widget, x, y):
            self._hide_tooltip()
            return
        self.tooltip_after_id = self.root.after(80, self._check_tooltip_pointer)

    @staticmethod
    def _point_inside_widget(widget: tk.Misc, x: int, y: int) -> bool:
        try:
            left = widget.winfo_rootx()
            top = widget.winfo_rooty()
            return left <= x <= left + widget.winfo_width() and top <= y <= top + widget.winfo_height()
        except tk.TclError:
            return False
    def open_minimap_cruise_extra_settings(self) -> None:
        existing = self.minimap_cruise_extra_settings_window
        if existing is not None:
            try:
                if bool(existing.winfo_exists()):
                    existing.lift()
                    existing.focus_set()
                    return
            except tk.TclError:
                self.minimap_cruise_extra_settings_window = None

        window = self._create_auxiliary_window(fg_color=APP_BG)
        self.minimap_cruise_extra_settings_window = window
        window.title("巡航進階設定")
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close_minimap_cruise_extra_settings)
        window.columnconfigure(0, weight=1)

        container = ctk.CTkFrame(window, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        container.columnconfigure(0, weight=1)
        self._build_minimap_cruise_extra_settings(container)

        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="e", pady=(8, 0))
        self._button(actions, "關閉", self.close_minimap_cruise_extra_settings, width=74).grid(
            row=0,
            column=0,
            sticky="e",
        )

        window.update_idletasks()
        self._prepare_auxiliary_window_for_show(window)
        x = self.root.winfo_rootx() + 72
        y = self.root.winfo_rooty() + 72
        window.geometry(f"+{x}+{y}")
        window.deiconify()
        window.lift()
        window.focus_set()

    def close_minimap_cruise_extra_settings(self) -> None:
        window = self.minimap_cruise_extra_settings_window
        self.minimap_cruise_extra_settings_window = None
        if window is None:
            return
        if not self.closed:
            try:
                self.apply_to_settings()
            except tk.TclError:
                pass
        try:
            window.destroy()
        except tk.TclError:
            pass

    def _build_minimap_cruise_extra_settings(self, parent: ctk.CTkFrame) -> None:
        skill_section, _skill_header, skill_frame = self._build_section(
            parent,
            "邊界技能",
            row=0,
            pady=(0, 0),
        )
        skill_section.grid_propagate(False)
        skill_section.configure(width=610, height=126)
        for column in range(9):
            skill_frame.columnconfigure(column, weight=0)
        skill_frame.columnconfigure(9, weight=1)
        self._checkbox(
            skill_frame,
            "邊界前技能",
            self.minimap_cruise_pre_boundary_skill_enabled,
            width=104,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=(0, 8), pady=6)
        self._label(skill_frame, "技能鍵").grid(row=0, column=2, sticky="w", padx=(8, 4), pady=6)
        skill_entry = self._entry(
            skill_frame,
            self.minimap_cruise_pre_boundary_skill_key,
            width=HOTKEY_ENTRY_WIDTH,
            justify="center",
            placeholder_text="自訂",
        )
        skill_entry.grid(row=0, column=3, sticky="w", padx=(0, 8), pady=6)
        skill_entry.bind(
            "<Button-1>",
            lambda event: self._start_key_detection_from_entry(
                event,
                self.minimap_cruise_pre_boundary_skill_key,
                "巡航邊界前技能鍵",
            ),
        )
        self._label(skill_frame, "距離").grid(row=0, column=4, sticky="w", padx=(8, 4), pady=6)
        self._entry(
            skill_frame,
            self.minimap_cruise_pre_boundary_distance,
            width=56,
            justify="center",
        ).grid(row=0, column=5, sticky="w", padx=(0, 4), pady=6)
        self._label(skill_frame, "px").grid(row=0, column=6, sticky="w", padx=(0, 8), pady=6)
        self._label(skill_frame, "測謊音量").grid(row=0, column=7, sticky="w", padx=(8, 4), pady=6)
        self._entry(
            skill_frame,
            self.minimap_cruise_lie_detector_alert_volume,
            width=48,
            justify="center",
        ).grid(row=0, column=8, sticky="w", padx=(0, 4), pady=6)
        self._label(skill_frame, "%").grid(row=0, column=9, sticky="w", padx=(0, 8), pady=6)
        self._label(skill_frame, "原地位移技").grid(row=1, column=0, columnspan=2, sticky="w", padx=(0, 8), pady=6)
        stationary_skill_entry = self._entry(
            skill_frame,
            self.minimap_cruise_stationary_skill_key,
            width=HOTKEY_ENTRY_WIDTH,
            justify="center",
            placeholder_text="空白=轉向",
        )
        stationary_skill_entry.grid(row=1, column=2, sticky="w", padx=(8, 8), pady=6)
        stationary_skill_entry.bind(
            "<Button-1>",
            lambda event: self._start_key_detection_from_entry(
                event,
                self.minimap_cruise_stationary_skill_key,
                "巡航原地位移技",
            ),
        )
        self._label(skill_frame, "1秒前進門檻").grid(row=1, column=3, sticky="w", padx=(8, 4), pady=6)
        self._entry(
            skill_frame,
            self.minimap_cruise_stationary_min_forward_pixels,
            width=56,
            justify="center",
        ).grid(row=1, column=4, sticky="w", padx=(0, 4), pady=6)
        self._label(skill_frame, "px").grid(row=1, column=5, sticky="w", padx=(0, 8), pady=6)

        periodic_section, _periodic_header, periodic_frame = self._build_section(
            parent,
            "定期熱鍵",
            row=1,
            pady=(8, 0),
        )
        periodic_section.configure(width=610)
        for column in range(7):
            periodic_frame.columnconfigure(column, weight=0)
        periodic_frame.columnconfigure(7, weight=1)
        for index, (enabled_var, key_var, interval_var) in enumerate(
            zip(
                self.minimap_cruise_periodic_key_enabled_vars,
                self.minimap_cruise_periodic_key_vars,
                self.minimap_cruise_periodic_key_interval_vars,
            ),
            start=1,
        ):
            row = index - 1
            self._checkbox(
                periodic_frame,
                f"定期按鍵{index}",
                enabled_var,
                width=104,
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=(0, 8), pady=(0, 6))
            self._label(periodic_frame, "熱鍵").grid(row=row, column=2, sticky="w", padx=(8, 4), pady=(0, 6))
            periodic_key_entry = self._entry(
                periodic_frame,
                key_var,
                width=HOTKEY_ENTRY_WIDTH,
                justify="center",
                placeholder_text="自訂",
            )
            periodic_key_entry.grid(row=row, column=3, sticky="w", padx=(0, 8), pady=(0, 6))
            periodic_key_entry.bind(
                "<Button-1>",
                lambda event, var=key_var, slot=index: self._start_key_detection_from_entry(
                    event,
                    var,
                    f"巡航定期按鍵{slot}",
                ),
            )
            self._label(periodic_frame, "間隔").grid(row=row, column=4, sticky="w", padx=(8, 4), pady=(0, 6))
            self._entry(
                periodic_frame,
                interval_var,
                width=56,
                justify="center",
            ).grid(row=row, column=5, sticky="w", padx=(0, 4), pady=(0, 6))
            self._label(periodic_frame, "秒").grid(row=row, column=6, sticky="w", padx=(0, 8), pady=(0, 6))
