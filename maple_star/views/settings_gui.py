from __future__ import annotations

import ctypes
import io
import json
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any, Callable

import customtkinter as ctk

from ..constants import (
    MAX_CONSOLE_CHARS,
    MAX_CONSOLE_LINES,
    POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT,
    POTION_MIN_COOLDOWN_SECONDS,
)
from ..adapters.debug_logging import install_tk_exception_logging, write_debug_text
from ..models.experience import (
    ExperienceSnapshot,
    format_duration,
    format_eta,
    format_exp,
    format_exp_10m_gain,
    format_exp_rate,
    format_ocr_success_rate,
    format_rate_confidence,
)
from ..adapters.key_capture import DETECTABLE_KEY_VKS, event_to_hotkey, pressed_detectable_vks, vk_to_key_name
from ..adapters.window_style import apply_background_toolwindow_style
from ..models.settings import (
    SETTINGS_PATH,
    AutoPotionSettings,
    CONTROLLER_BUTTON_CHOICES,
    COMBO_ATTACK_START_DELAY_MAX_SECONDS,
    COMBO_ATTACK_START_DELAY_MIN_SECONDS,
    COMBO_ATTACK_HOLD_MAX_SECONDS,
    COMBO_ATTACK_HOLD_MIN_SECONDS,
    COMBO_JUMP_INTERVAL_MAX_SECONDS,
    COMBO_JUMP_INTERVAL_MIN_SECONDS,
    COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP,
    COMBO_SCRIPT_LABELS,
    COMBO_SCRIPT_REPEATING_JUMP_SKILL,
    COMBO_SCRIPT_SINGLE_JUMP_SKILL,
    MINIMAP_CRUISE_MAX_PRE_BOUNDARY_SKILL_DISTANCE,
    MINIMAP_CRUISE_MAX_STATIONARY_MIN_FORWARD_PIXELS,
    MINIMAP_CRUISE_MAX_ALERT_VOLUME_PERCENT,
    MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
    MINIMAP_CRUISE_MIN_PRE_BOUNDARY_SKILL_DISTANCE,
    MINIMAP_CRUISE_MIN_STATIONARY_MIN_FORWARD_PIXELS,
    MINIMAP_CRUISE_MIN_ALERT_VOLUME_PERCENT,
    MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
    copy_setting_values,
    normalize_controller_button_name,
    normalize_combo_script_id,
    normalize_profile_name,
)
from ..services.settings_store import load_settings, save_settings
from ..services.minimap_cruise import (
    MINIMAP_CRUISE_MAX_BOUNDARY_Y_DELTA_PIXELS,
    MINIMAP_CRUISE_MIN_BOUNDARY_WIDTH_PIXELS,
    validate_minimap_cruise_settings,
)
from ..adapters.win_input import Point, parse_vk_key, user32
from .gui_theme import *  # noqa: F401,F403
from .gui_presentation import GuiPresentationMixin
from .pages.console_page import build_console_page, build_console_text
from .pages.combo_page import FlowLayout, build_combo_page
from .pages.contracts import (
    ComboPageContext,
    ComboPageRefs,
    ComboSlotContext,
    ConsolePageContext,
    ConsolePageRefs,
    ConsoleTextRefs,
    MinimapPageContext,
    MinimapPageRefs,
    MonitorControlsContext,
    MonitorControlsRefs,
    MonitorPageContext,
    MonitorPageRefs,
    PageWidgets,
    PotionKindContext,
    PotionPageContext,
    PotionPageRefs,
)
from .pages.minimap_page import build_minimap_page
from .pages.monitor_page import build_monitor_controls, build_monitor_page
from .pages.potion_page import build_potion_page

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

class GuiConsoleWriter:
    def __init__(self, gui: AutoPotionSettingsGui, original: object | None = None) -> None:
        self.gui = gui
        self.original = original

    def write(self, text: str) -> int:
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        write_debug_text(text)
        self.gui.append_console(text)
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass


class AutoPotionSettingsGui(GuiPresentationMixin):
    def __init__(self, settings: AutoPotionSettings) -> None:
        self.settings = settings
        self.closed = False
        self.root = ctk.CTk(fg_color=APP_BG)
        install_tk_exception_logging(self.root)
        self.root.title("大雞雞專用")
        self.root.resizable(True, True)
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        initial_position = self._saved_position(settings.full_panel_window_x, settings.full_panel_window_y)
        self.root.geometry(self._geometry_string(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT, initial_position))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.detecting_key_target: tk.StringVar | None = None
        self.detecting_key_label = ""
        self.key_detection_window: ctk.CTkToplevel | None = None
        self.key_detection_just_finished = False
        self.key_detection_release_vks: set[int] = set()
        self.key_detection_focus_bindings: list[tuple[tk.Misc, str]] = []
        self.toggle_notice_window: ctk.CTkToplevel | None = None
        self.toggle_notice_after_id: str | None = None
        self.toggle_notice_message = ""
        self.bar_preview_provider: Callable[[bool], dict[str, dict[str, object]]] | None = None
        self.experience_reset_handler: Callable[[], bool | None] | None = None
        self.auto_drink_toggle_handler: Callable[[bool], bool | None] | None = None
        self.pickup_toggle_handler: Callable[[bool], bool | None] | None = None
        self.bar_preview_labels: dict[str, ctk.CTkLabel] = {}
        self.bar_preview_images: list[ctk.CTkImage] = []
        self.bar_preview_has_snapshot = False
        self.detecting_vk_down: set[int] = set()
        self.last_gui_error_at = -999.0
        self.window_interaction_pause_until = 0.0
        self.content_frame: ctk.CTkFrame | None = None
        self.controls_frame: ctk.CTkFrame | None = None
        self.monitor_frame: ctk.CTkFrame | None = None
        self.monitor_responsive_relayout: Callable[[], None] | None = None
        self.exp_section: ctk.CTkFrame | None = None
        self.detection_section: ctk.CTkFrame | None = None
        self.combo_group_section: ctk.CTkFrame | None = None
        self.combo_group_body: ctk.CTkFrame | None = None
        self.combo_group_title_label: ctk.CTkLabel | None = None
        self.minimap_cruise_section: ctk.CTkFrame | None = None
        self.minimap_cruise_body: ctk.CTkFrame | None = None
        self.minimap_cruise_title_label: ctk.CTkLabel | None = None
        self.minimap_cruise_extra_settings_window: ctk.CTkToplevel | None = None
        self.combo_group_collapsed = False
        self.minimap_cruise_group_collapsed = False
        self.full_panel_widgets: list[tk.Misc] = []
        self.panel_mode_button: ctk.CTkButton | None = None
        self.topmost_button: ctk.CTkButton | None = None
        self.console_section: ctk.CTkFrame | None = None
        self.console_title_label: ctk.CTkLabel | None = None
        self.console_clear_button: ctk.CTkButton | None = None
        self.console_toggle_button: ctk.CTkButton | None = None
        self.console_restore_button: ctk.CTkButton | None = None
        self.console_frame: ctk.CTkFrame | None = None
        self.console_container: ctk.CTkFrame | None = None
        self.console_scrollbar: ctk.CTkScrollbar | None = None
        self.console: tk.Text | None = None
        self.console_placeholder: ctk.CTkLabel | None = None
        self.console_page_refs: ConsolePageRefs | None = None
        self.console_text_refs: ConsoleTextRefs | None = None
        self.potion_page_refs: PotionPageRefs | None = None
        self.minimap_page_refs: MinimapPageRefs | None = None
        self.combo_page_refs: ComboPageRefs | None = None
        self.monitor_page_refs: MonitorPageRefs | None = None
        self.monitor_controls_refs: MonitorControlsRefs | None = None
        self.console_collapsed = False
        self.console_resize_after_id: str | None = None
        self.console_height_after_id: str | None = None
        self.console_flush_after_id: str | None = None
        self.console_pending_text: list[str] = []
        self.console_pending_char_count = 0
        self.active_page = "監控"
        self.page_frames: dict[str, ctk.CTkFrame] = {}
        self.page_built: set[str] = {"監控"}
        self.page_placeholders: dict[str, ctk.CTkLabel] = {}
        self.page_build_after_id: str | None = None
        self.profile_select: ctk.CTkComboBox | None = None
        self.monitor_controls_after_id: str | None = None
        self.console_resize_frozen = False
        self.resize_layout_suspended = False
        self.suppress_resize_suspend_until = 0.0
        self.expanded_window_width = WINDOW_DEFAULT_WIDTH
        self.default_window_size = (WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
        self.compact_experience_mode = False
        self.window_topmost = False
        self.last_root_size: tuple[int, int] | None = None
        self.root_was_minimized = False
        self.restore_repaint_until = 0.0
        self.restore_repaint_after_id: str | None = None
        self.tooltip_window: ctk.CTkToplevel | None = None
        self.tooltip_windows: list[ctk.CTkToplevel] = []
        self.tooltip_anchor_widget: ctk.CTkBaseClass | None = None
        self.tooltip_after_id: str | None = None
        self.tooltip_hide_after_id: str | None = None
        self.active_profile = tk.StringVar(value=settings.active_profile)
        self.auto_drink_enabled = tk.BooleanVar(value=True)
        self.pickup_enabled = tk.BooleanVar(value=False)
        self.hp_enabled = tk.BooleanVar(value=settings.hp_enabled)
        self.mp_enabled = tk.BooleanVar(value=settings.mp_enabled)
        self.potion_enabled_ui_only_snapshot: tuple[bool, bool, bool, bool] | None = None
        self.rb_enabled = tk.BooleanVar(value=settings.rb_enabled)
        self.hp_threshold = tk.DoubleVar(value=settings.hp_threshold_percent)
        self.mp_threshold = tk.DoubleVar(value=settings.mp_threshold_percent)
        self.hp_threshold_text = tk.StringVar(value=f"{settings.hp_threshold_percent:.0f}")
        self.mp_threshold_text = tk.StringVar(value=f"{settings.mp_threshold_percent:.0f}")
        self.hp_key = tk.StringVar(value=settings.hp_key)
        self.mp_key = tk.StringVar(value=settings.mp_key)
        self.hp_cooldown = tk.StringVar(value=f"{settings.hp_cooldown_seconds:g}")
        self.mp_cooldown = tk.StringVar(value=f"{settings.mp_cooldown_seconds:g}")
        self.hp_continuous_enabled = tk.BooleanVar(value=settings.hp_continuous_enabled)
        self.mp_continuous_enabled = tk.BooleanVar(value=settings.mp_continuous_enabled)
        self.hp_continuous_stop_margin = tk.StringVar(value=f"{settings.hp_continuous_stop_margin_percent:g}")
        self.mp_continuous_stop_margin = tk.StringVar(value=f"{settings.mp_continuous_stop_margin_percent:g}")
        self.rb_jump_key = tk.StringVar(value=settings.rb_jump_key)
        self.rb_skill_key = tk.StringVar(value=settings.rb_skill_key)
        self.rb_attack_key = tk.StringVar(value=str(settings.combo_slot("A")["attack_key"]))
        self.rb_attack_start_delay = tk.StringVar(value=f"{float(settings.combo_slot('A')['attack_start_delay_seconds']):g}")
        self.rb_attack_hold = tk.StringVar(value=f"{float(settings.combo_slot('A')['attack_hold_seconds']):g}")
        self.rb_controller_button = tk.StringVar(value=settings.rb_controller_button)
        self.rb_skill_delay = tk.StringVar(value=f"{settings.rb_skill_delay_seconds:g}")
        self.rb_jump_interval = tk.StringVar(value=f"{settings.rb_jump_interval_seconds:g}")
        self.lb_enabled = tk.BooleanVar(value=settings.lb_enabled)
        self.lb_jump_key = tk.StringVar(value=settings.lb_jump_key)
        self.lb_skill_key = tk.StringVar(value=settings.lb_skill_key)
        self.lb_attack_key = tk.StringVar(value=str(settings.combo_slot("B")["attack_key"]))
        self.lb_attack_start_delay = tk.StringVar(value=f"{float(settings.combo_slot('B')['attack_start_delay_seconds']):g}")
        self.lb_attack_hold = tk.StringVar(value=f"{float(settings.combo_slot('B')['attack_hold_seconds']):g}")
        self.lb_controller_button = tk.StringVar(value=settings.lb_controller_button)
        self.lb_skill_delay = tk.StringVar(value=f"{settings.lb_skill_delay_seconds:g}")
        self.lb_jump_interval = tk.StringVar(value=f"{float(settings.combo_slot('B')['jump_interval_seconds']):g}")
        self.combo_a_script = tk.StringVar(value=self._combo_script_label(str(settings.combo_slot("A")["script_id"])))
        self.combo_b_script = tk.StringVar(value=self._combo_script_label(str(settings.combo_slot("B")["script_id"])))
        self.combo_skill_key_fields: dict[str, tuple[tk.Misc, ...]] = {}
        self.combo_attack_key_fields: dict[str, tuple[tk.Misc, ...]] = {}
        self.combo_skill_delay_fields: dict[str, tuple[tk.Misc, ...]] = {}
        self.combo_attack_start_delay_fields: dict[str, tuple[tk.Misc, ...]] = {}
        self.combo_attack_hold_fields: dict[str, tuple[tk.Misc, ...]] = {}
        self.combo_jump_interval_fields: dict[str, tuple[tk.Misc, ...]] = {}
        self.combo_field_flows: dict[str, FlowLayout] = {}
        self.exp_efficiency_enabled = tk.BooleanVar(value=settings.exp_efficiency_enabled)
        self.toggle_hotkey = tk.StringVar(value=settings.toggle_hotkey)
        self.emergency_stop_hotkey = tk.StringVar(value=settings.emergency_stop_hotkey)
        self.experience_toggle_hotkey = tk.StringVar(value=settings.experience_toggle_hotkey)
        self.experience_reset_hotkey = tk.StringVar(value=settings.experience_reset_hotkey)
        self.character_stat_hotkey = tk.StringVar(value=settings.character_stat_hotkey)
        self.pickup_toggle_hotkey = tk.StringVar(value=settings.pickup_toggle_hotkey or "")
        self.pickup_key = tk.StringVar(value=settings.pickup_key or "")
        self.minimap_cruise_toggle_hotkey = tk.StringVar(value=settings.minimap_cruise_toggle_hotkey or "")
        self.minimap_cruise_attack_key = tk.StringVar(value=settings.minimap_cruise_attack_key)
        self.minimap_cruise_pre_boundary_skill_enabled = tk.BooleanVar(
            value=settings.minimap_cruise_pre_boundary_skill_enabled
        )
        self.minimap_cruise_pre_boundary_skill_key = tk.StringVar(
            value=settings.minimap_cruise_pre_boundary_skill_key
        )
        self.minimap_cruise_pre_boundary_distance = tk.StringVar(
            value=f"{settings.minimap_cruise_pre_boundary_distance:g}"
        )
        self.minimap_cruise_stationary_skill_key = tk.StringVar(value=settings.minimap_cruise_stationary_skill_key)
        self.minimap_cruise_stationary_min_forward_pixels = tk.StringVar(
            value=f"{settings.minimap_cruise_stationary_min_forward_pixels:g}"
        )
        self.minimap_cruise_lie_detector_alert_volume = tk.StringVar(
            value=f"{settings.minimap_cruise_lie_detector_alert_volume_percent:g}"
        )
        self.minimap_cruise_periodic_key_enabled_vars = [
            tk.BooleanVar(value=settings.minimap_cruise_periodic_key_1_enabled),
            tk.BooleanVar(value=settings.minimap_cruise_periodic_key_2_enabled),
            tk.BooleanVar(value=settings.minimap_cruise_periodic_key_3_enabled),
            tk.BooleanVar(value=settings.minimap_cruise_periodic_key_4_enabled),
            tk.BooleanVar(value=settings.minimap_cruise_periodic_key_5_enabled),
        ]
        self.minimap_cruise_periodic_key_vars = [
            tk.StringVar(value=settings.minimap_cruise_periodic_key_1),
            tk.StringVar(value=settings.minimap_cruise_periodic_key_2),
            tk.StringVar(value=settings.minimap_cruise_periodic_key_3),
            tk.StringVar(value=settings.minimap_cruise_periodic_key_4),
            tk.StringVar(value=settings.minimap_cruise_periodic_key_5),
        ]
        self.minimap_cruise_periodic_key_interval_vars = [
            tk.StringVar(value=f"{settings.minimap_cruise_periodic_key_1_interval_seconds:g}"),
            tk.StringVar(value=f"{settings.minimap_cruise_periodic_key_2_interval_seconds:g}"),
            tk.StringVar(value=f"{settings.minimap_cruise_periodic_key_3_interval_seconds:g}"),
            tk.StringVar(value=f"{settings.minimap_cruise_periodic_key_4_interval_seconds:g}"),
            tk.StringVar(value=f"{settings.minimap_cruise_periodic_key_5_interval_seconds:g}"),
        ]
        self.minimap_cruise_boundary_status = tk.StringVar(value=self._minimap_cruise_boundary_status_text())
        self.minimap_cruise_boundary_step = ""
        self.minimap_cruise_first_point: tuple[int, int] | None = None
        self.minimap_cruise_boundary_after_id: str | None = None
        self.minimap_cruise_mouse_was_down = False
        self.hp_current = tk.StringVar(value="HP: --%")
        self.mp_current = tk.StringVar(value="MP: --%")
        self.status = tk.StringVar(value="控制熱鍵可在楓星或本程式前景觸發")
        self.runtime_script_status = tk.StringVar(value="自動喝水：啟用")
        self.runtime_foreground_status = tk.StringVar(value="前景：--")
        self.runtime_status_message = tk.StringVar(value=f"狀態：{self.status.get()}")
        self.hp_detection_status = tk.StringVar(value="HP: --")
        self.mp_detection_status = tk.StringVar(value="MP: --")
        self.exp_current_status = tk.StringVar(value="EXP：--")
        self.exp_rate_10m_status = tk.StringVar(value="10m：--")
        self.exp_rate_1h_status = tk.StringVar(value="1h：--")
        self.exp_10m_gain_status = tk.StringVar(value="EXP-10：--")
        self.exp_eta_status = tk.StringVar(value="升級預估：--    時間：--")
        self.exp_quality_status = tk.StringVar(value="樣本：--    信賴度：--")
        self.exp_reader_status = tk.StringVar(value="狀態：尚未開始")

        frame = ctk.CTkFrame(self.root, fg_color=APP_BG, corner_radius=0)
        frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.content_frame = frame
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.bind("<Alt-F4>", lambda _event: self.close(), add="+")
        frame.columnconfigure(0, weight=1, minsize=LEFT_PANEL_MAX_WIDTH)
        frame.columnconfigure(1, weight=0, minsize=0)
        frame.rowconfigure(1, weight=1)

        self.page_navigation = ctk.CTkSegmentedButton(
            frame,
            values=("監控", "自動喝水", "小地圖巡航", "手把組合", "Console"),
            command=self.show_page,
            fg_color=PANEL_BG_ALT,
            selected_color=ACCENT_GREEN,
            selected_hover_color=ACCENT_GREEN,
            unselected_color=SECONDARY_BUTTON_BG,
            unselected_hover_color=SECONDARY_BUTTON_HOVER,
            font=TAB_FONT,
            height=28,
            dynamic_resizing=True,
        )
        self.page_navigation.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.page_navigation.set("監控")

        controls_frame = ctk.CTkFrame(frame, fg_color="transparent", width=LEFT_PANEL_MAX_WIDTH)
        self.controls_frame = controls_frame
        controls_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        controls_frame.grid_propagate(False)
        controls_frame.columnconfigure(0, weight=1)

        for page_name in ("監控", "自動喝水", "小地圖巡航", "手把組合"):
            page = ctk.CTkFrame(controls_frame, fg_color="transparent")
            page.columnconfigure(0, weight=1)
            self.page_frames[page_name] = page
        monitor_page = self.page_frames["監控"]
        monitor_page.grid(row=0, column=0, sticky="nsew")

        refs = build_monitor_page(
            monitor_page,
            MonitorPageContext(
                widgets=self._page_widgets(),
                exp_enabled=self.exp_efficiency_enabled,
                exp_current_status=self.exp_current_status,
                exp_eta_status=self.exp_eta_status,
                exp_rate_10m_status=self.exp_rate_10m_status,
                exp_rate_1h_status=self.exp_rate_1h_status,
                exp_10m_gain_status=self.exp_10m_gain_status,
                exp_quality_status=self.exp_quality_status,
                exp_reader_status=self.exp_reader_status,
                hp_detection_status=self.hp_detection_status,
                mp_detection_status=self.mp_detection_status,
                runtime_script_status=self.runtime_script_status,
                runtime_foreground_status=self.runtime_foreground_status,
                runtime_status_message=self.runtime_status_message,
                reset_experience=self.reset_experience_statistics,
                toggle_compact_mode=self.toggle_compact_experience_mode,
                toggle_topmost=self.toggle_window_topmost,
                refresh_bar_preview=self.refresh_bar_preview,
                toggle_console=self.toggle_console_collapsed,
                bind_checkbox_label=self._bind_checkbox_label,
                monitor_is_active=lambda: not self.compact_experience_mode,
            ),
        )
        self.monitor_page_refs = refs
        self.monitor_frame = refs.monitor_frame
        self.exp_section = refs.exp_section
        self.detection_section = refs.detection_section
        self.bar_preview_labels.update(refs.bar_preview_labels)
        self.monitor_responsive_relayout = refs.monitor_responsive_relayout
        self.panel_mode_button = refs.panel_mode_button
        self.topmost_button = refs.topmost_button
        self.console_restore_button = refs.console_restore_button
        self.full_panel_widgets = list(refs.full_panel_widgets)

        self.root.bind("<Configure>", self._on_root_configure, add="+")
        self.set_window_topmost(settings.window_topmost)
        self.set_minimap_cruise_group_collapsed(settings.minimap_cruise_group_collapsed)
        self.set_combo_group_collapsed(settings.combo_group_collapsed)
        self.set_console_collapsed(settings.console_collapsed)
        self.set_compact_experience_mode(settings.compact_experience_mode, restore_saved_position=True)
        self.show_page("監控")
        self.monitor_controls_after_id = self.root.after(250, self._build_monitor_controls)

    def _build_monitor_controls(self) -> None:
        self.monitor_controls_after_id = None
        page = self.page_frames.get("監控")
        if page is None or self.profile_select is not None or self.closed:
            return
        existing_children = set(page.winfo_children())
        previous_full_panel_widgets = list(self.full_panel_widgets)
        try:
            refs = build_monitor_controls(
                page,
                MonitorControlsContext(
                widgets=self._page_widgets(),
                active_profile=self.active_profile,
                toggle_hotkey=self.toggle_hotkey,
                emergency_stop_hotkey=self.emergency_stop_hotkey,
                experience_toggle_hotkey=self.experience_toggle_hotkey,
                experience_reset_hotkey=self.experience_reset_hotkey,
                character_stat_hotkey=self.character_stat_hotkey,
                pickup_toggle_hotkey=self.pickup_toggle_hotkey,
                pickup_key=self.pickup_key,
                pickup_enabled=self.pickup_enabled,
                detect_key=self._start_key_detection_from_entry,
                toggle_pickup=self._toggle_pickup_enabled_from_checkbox,
                profile_names=self.settings.profile_names,
                switch_profile=self._switch_profile,
                create_profile=self.create_profile,
                delete_profile=self.delete_profile,
                import_settings=self.import_settings,
                export_settings=self.export_settings,
                ),
            )
            self.monitor_controls_refs = refs
            self.profile_select = refs.profile_select
            self.full_panel_widgets[:0] = list(refs.full_panel_widgets)
            if self.compact_experience_mode:
                refs.hotkey_section.grid_remove()
                refs.profile_section.grid_remove()
            else:
                self.root.after_idle(self._sync_full_window_height_to_left_panel)
        except Exception:
            for child in page.winfo_children():
                if child not in existing_children:
                    child.destroy()
            self.monitor_controls_refs = None
            self.profile_select = None
            self.full_panel_widgets[:] = previous_full_panel_widgets
            if not self.closed:
                self.monitor_controls_after_id = self.root.after(250, self._build_monitor_controls)
            raise

    def show_page(self, page_name: str) -> None:
        if page_name not in {"監控", "自動喝水", "小地圖巡航", "手把組合", "Console"}:
            return
        self.active_page = page_name
        try:
            self.page_navigation.set(page_name)
            for page in self.page_frames.values():
                page.grid_remove()
            if page_name == "Console":
                self._ensure_console_page_built()
                if self.controls_frame is not None:
                    self.controls_frame.grid_remove()
                if self.console_section is not None:
                    self.console_section.grid(
                        row=1,
                        column=0,
                        columnspan=2,
                        sticky="nsew",
                        padx=0,
                        pady=0,
                    )
                self._ensure_console_built()
                self.page_built.add("Console")
                current_width = max(WINDOW_EXPANDED_MIN_WIDTH, int(self.root.winfo_width()))
                current_height = int(self.root.winfo_height())
                self.root.minsize(WINDOW_EXPANDED_MIN_WIDTH, CONSOLE_PAGE_MIN_HEIGHT)
                if current_height < CONSOLE_PAGE_MIN_HEIGHT:
                    self._set_window_size(current_width, CONSOLE_PAGE_MIN_HEIGHT)
            else:
                if self.console_section is not None:
                    self.console_section.grid_remove()
                if self.controls_frame is not None:
                    self.controls_frame.grid(
                        row=1,
                        column=0,
                        columnspan=2,
                        sticky="nsew",
                        padx=0,
                    )
                self.page_frames[page_name].grid(row=0, column=0, sticky="nsew")
                if page_name not in self.page_built:
                    placeholder = self.page_placeholders.get(page_name)
                    if placeholder is None:
                        placeholder = self._label(
                            self.page_frames[page_name],
                            "載入設定頁…",
                            color=MUTED_TEXT,
                        )
                        placeholder.grid(row=0, column=0, sticky="w", padx=12, pady=12)
                        self.page_placeholders[page_name] = placeholder
                    self.root.update_idletasks()
                    if self.page_build_after_id is not None:
                        self.root.after_cancel(self.page_build_after_id)
                    self.page_build_after_id = self.root.after(
                        1,
                        lambda name=page_name: self._finish_page_build(name),
                    )
        except tk.TclError:
            return
        self._schedule_console_height_sync()
        if page_name != "Console" and page_name in self.page_built:
            self.root.after_idle(self._sync_full_window_height_to_left_panel)

    def _finish_page_build(self, page_name: str) -> None:
        self.page_build_after_id = None
        if self.closed or self.active_page != page_name:
            return
        self._ensure_page_built(page_name)
        placeholder = self.page_placeholders.pop(page_name, None)
        if placeholder is not None:
            placeholder.destroy()
        self.root.after_idle(self._sync_full_window_height_to_left_panel)

    def _ensure_page_built(self, page_name: str) -> None:
        if page_name in self.page_built:
            return
        builders = {
            "自動喝水": self._build_potion_page,
            "小地圖巡航": self._build_minimap_page,
            "手把組合": self._build_combo_page,
        }
        builder = builders.get(page_name)
        if builder is not None:
            builder(self.page_frames[page_name])
        self.page_built.add(page_name)

    def _page_widgets(self) -> PageWidgets:
        return PageWidgets(
            section=self._build_section,
            title_label=self._title_label,
            label=self._label,
            entry=self._entry,
            checkbox=self._checkbox,
            button=self._button,
            responsive_columns=self._bind_responsive_two_columns,
            combo=self._combo,
        )

    def _build_potion_page(self, page: ctk.CTkFrame) -> None:
        existing_children = set(page.winfo_children())
        context = PotionPageContext(
            widgets=self._page_widgets(),
            auto_drink_enabled=self.auto_drink_enabled,
            hp=PotionKindContext(
                "HP／紅水",
                "紅水",
                self.hp_enabled,
                self.hp_threshold,
                self.hp_threshold_text,
                self.hp_key,
                self.hp_cooldown,
                self.hp_continuous_enabled,
                self.hp_continuous_stop_margin,
                self.hp_current,
            ),
            mp=PotionKindContext(
                "MP／藍水",
                "藍水",
                self.mp_enabled,
                self.mp_threshold,
                self.mp_threshold_text,
                self.mp_key,
                self.mp_cooldown,
                self.mp_continuous_enabled,
                self.mp_continuous_stop_margin,
                self.mp_current,
            ),
            toggle_auto_drink=self._toggle_auto_drink_enabled_from_checkbox,
            detect_key=self._start_key_detection_from_entry,
            apply_percent=self._apply_percent_text,
        )
        try:
            refs = build_potion_page(page, context)
        except Exception:
            for child in page.winfo_children():
                if child not in existing_children:
                    child.destroy()
            raise
        self.potion_page_refs = refs


    def _build_minimap_page(self, page: ctk.CTkFrame) -> None:
        existing_children = set(page.winfo_children())
        context = MinimapPageContext(
            widgets=self._page_widgets(),
            toggle_hotkey=self.minimap_cruise_toggle_hotkey,
            attack_key=self.minimap_cruise_attack_key,
            boundary_status=self.minimap_cruise_boundary_status,
            detect_key=self._start_key_detection_from_entry,
            setup_boundary=self.start_minimap_cruise_boundary_setup,
            open_extra_settings=self.open_minimap_cruise_extra_settings,
            toggle_collapsed=self.toggle_minimap_cruise_group_collapsed,
        )
        try:
            refs = build_minimap_page(page, context)
            self.minimap_page_refs = refs
            self.minimap_cruise_section = refs.section
            self.minimap_cruise_body = refs.body
            self.minimap_cruise_title_label = refs.title_label
            self.set_minimap_cruise_group_collapsed(self.minimap_cruise_group_collapsed)
        except Exception:
            for child in page.winfo_children():
                if child not in existing_children:
                    child.destroy()
            self.minimap_page_refs = None
            self.minimap_cruise_section = None
            self.minimap_cruise_body = None
            self.minimap_cruise_title_label = None
            raise

    def _build_combo_page(self, page: ctk.CTkFrame) -> None:
        existing_children = set(page.winfo_children())

        context = ComboPageContext(
            widgets=self._page_widgets(),
            slot_a=ComboSlotContext(
                "A",
                self.rb_enabled,
                self.rb_controller_button,
                self.combo_a_script,
                self.rb_jump_key,
                self.rb_skill_key,
                self.rb_attack_key,
                self.rb_attack_start_delay,
                self.rb_attack_hold,
                self.rb_skill_delay,
                self.rb_jump_interval,
                self._combo_a_description,
            ),
            slot_b=ComboSlotContext(
                "B",
                self.lb_enabled,
                self.lb_controller_button,
                self.combo_b_script,
                self.lb_jump_key,
                self.lb_skill_key,
                self.lb_attack_key,
                self.lb_attack_start_delay,
                self.lb_attack_hold,
                self.lb_skill_delay,
                self.lb_jump_interval,
                self._combo_b_description,
            ),
            toggle_collapsed=self.toggle_combo_group_collapsed,
            bind_checkbox_label=self._bind_checkbox_label,
            info_icon=self._info_icon,
            detect_key=self._start_key_detection_from_entry,
            script_changed=self._on_combo_script_changed,
            step_seconds=self._step_seconds,
        )
        try:
            refs = build_combo_page(page, context)
            self.combo_page_refs = refs
            self.combo_group_section = refs.section
            self.combo_group_body = refs.body
            self.combo_group_title_label = refs.title_label
            for slot_id, slot_refs in refs.slots.items():
                self.combo_field_flows[slot_id] = slot_refs.field_flow
                self.combo_skill_key_fields[slot_id] = slot_refs.skill_key_fields
                self.combo_attack_key_fields[slot_id] = slot_refs.attack_key_fields
                self.combo_skill_delay_fields[slot_id] = slot_refs.skill_delay_fields
                self.combo_attack_start_delay_fields[slot_id] = slot_refs.attack_start_delay_fields
                self.combo_attack_hold_fields[slot_id] = slot_refs.attack_hold_fields
                self.combo_jump_interval_fields[slot_id] = slot_refs.jump_interval_fields
            self._refresh_combo_script_visibility()
            self.set_combo_group_collapsed(self.combo_group_collapsed)
        except Exception:
            for child in page.winfo_children():
                if child not in existing_children:
                    child.destroy()
            self.combo_page_refs = None
            self.combo_group_section = None
            self.combo_group_body = None
            self.combo_group_title_label = None
            for registry in (
                self.combo_field_flows,
                self.combo_skill_key_fields,
                self.combo_attack_key_fields,
                self.combo_skill_delay_fields,
                self.combo_attack_start_delay_fields,
                self.combo_attack_hold_fields,
                self.combo_jump_interval_fields,
            ):
                registry.pop("A", None)
                registry.pop("B", None)
            raise

    def _ensure_console_page_built(self) -> None:
        if self.console_section is not None or self.content_frame is None:
            return
        parent = self.content_frame
        existing_children = set(parent.winfo_children())
        try:
            refs = build_console_page(
                parent,
                ConsolePageContext(
                    widgets=self._page_widgets(),
                    clear_console=self.clear_console,
                ),
            )
        except Exception:
            for child in parent.winfo_children():
                if child not in existing_children:
                    child.destroy()
            raise
        self.console_page_refs = refs
        self.console_section = refs.section
        self.console_title_label = refs.title_label
        self.console_clear_button = refs.clear_button
        self.console_frame = refs.frame
        self.console_container = refs.container

    def _ensure_console_built(self) -> None:
        if self.console is not None or self.console_container is None:
            return
        if self.console_placeholder is not None:
            self.console_placeholder.destroy()
            self.console_placeholder = None
        existing_children = set(self.console_container.winfo_children())
        try:
            refs = build_console_text(self.console_container)
        except Exception:
            for child in self.console_container.winfo_children():
                if child not in existing_children:
                    child.destroy()
            raise
        self.console_text_refs = refs
        self.console = refs.text
        self.console_scrollbar = refs.scrollbar
        if self.console_pending_text:
            try:
                self.console_flush_after_id = self.root.after_idle(self._flush_console_buffer)
            except tk.TclError:
                self.console_flush_after_id = None


    def _on_root_configure(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        if self._root_is_minimized():
            self.window_interaction_pause_until = 0.0
            self.root_was_minimized = True
            return
        current_size = (int(event.width), int(event.height))
        size_changed = self.last_root_size is not None and current_size != self.last_root_size
        self.last_root_size = current_size
        now = time.monotonic()
        restored_from_minimized = bool(getattr(self, "root_was_minimized", False))
        self.root_was_minimized = False
        if restored_from_minimized:
            self._begin_restore_repaint(now)
            return
        if now < getattr(self, "restore_repaint_until", 0.0):
            return
        self.window_interaction_pause_until = now + WINDOW_INTERACTION_GRACE_SECONDS
        if size_changed and now >= self.suppress_resize_suspend_until:
            self._suspend_layout_for_resize()
        self._schedule_window_interaction_finish()

    def is_window_interaction_active(self) -> bool:
        if getattr(self, "minimap_cruise_boundary_step", ""):
            return True
        if self._root_is_minimized():
            return False
        now = time.monotonic()
        return now < self.window_interaction_pause_until or now < getattr(self, "restore_repaint_until", 0.0)

    def _root_is_minimized(self) -> bool:
        try:
            return self.root.state() == "iconic"
        except tk.TclError:
            return False

    def toggle_console_collapsed(self) -> None:
        self.set_console_collapsed(not self.console_collapsed)

    def toggle_combo_group_collapsed(self) -> None:
        self.set_combo_group_collapsed(not self.combo_group_collapsed)

    def toggle_minimap_cruise_group_collapsed(self) -> None:
        self.set_minimap_cruise_group_collapsed(not self.minimap_cruise_group_collapsed)

    def set_minimap_cruise_group_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        self.minimap_cruise_group_collapsed = collapsed
        if hasattr(self, "settings"):
            self.settings.minimap_cruise_group_collapsed = collapsed
        try:
            if self.minimap_cruise_body is not None:
                if collapsed:
                    self.minimap_cruise_body.grid_remove()
                else:
                    self.minimap_cruise_body.grid()
            if self.minimap_cruise_title_label is not None:
                self.minimap_cruise_title_label.configure(
                    text="小地圖巡航（已收合）" if collapsed else "小地圖巡航"
                )
        except tk.TclError:
            return
        if getattr(self, "console_collapsed", False):
            self._sync_full_window_height_to_left_panel()
        else:
            self._sync_console_height_to_left_panel()

    def set_combo_group_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        self.combo_group_collapsed = collapsed
        if hasattr(self, "settings"):
            self.settings.combo_group_collapsed = collapsed
        try:
            if self.combo_group_body is not None:
                if collapsed:
                    self.combo_group_body.grid_remove()
                else:
                    self.combo_group_body.grid()
            if self.combo_group_title_label is not None:
                self.combo_group_title_label.configure(text="組合設定（已收合）" if collapsed else "組合設定")
        except tk.TclError:
            return
        if getattr(self, "console_collapsed", False):
            self._sync_full_window_height_to_left_panel()
        else:
            self._sync_console_height_to_left_panel()

    def set_console_collapsed(self, collapsed: bool) -> None:
        if self.console_collapsed == collapsed:
            self.settings.console_collapsed = collapsed
            return
        if collapsed:
            self._unfreeze_console_resize()
            self._remember_expanded_window_width()
            self.console_collapsed = True
            self.settings.console_collapsed = True
            if not self.compact_experience_mode:
                self._collapse_console_panel()
                self._sync_full_window_height_to_left_panel(width=WINDOW_COLLAPSED_WIDTH)
            return
        self.console_collapsed = False
        self.settings.console_collapsed = False
        if not self.compact_experience_mode:
            self._restore_console_panel()
            self._set_window_width(max(WINDOW_EXPANDED_MIN_WIDTH, self.expanded_window_width))
            self._sync_console_height_to_left_panel()

    def toggle_compact_experience_mode(self) -> None:
        self.set_compact_experience_mode(not self.compact_experience_mode)

    def set_compact_experience_mode(self, compact: bool, *, restore_saved_position: bool = False) -> None:
        if self.compact_experience_mode == compact:
            self.settings.compact_experience_mode = compact
            self._update_panel_mode_buttons()
            return
        if compact:
            experience_anchor = None if restore_saved_position else self._experience_section_screen_position()
            self._remember_default_window_size()
            self._remember_full_panel_window_position()
            self.compact_experience_mode = True
            self.settings.compact_experience_mode = True
            self._enter_compact_experience_mode()
            target_position = None
            if restore_saved_position:
                target_position = self._saved_position(
                    self.settings.compact_experience_window_x,
                    self.settings.compact_experience_window_y,
                )
            if target_position is None:
                target_position = self._compact_window_position_for_experience_anchor(experience_anchor)
            self._set_window_size(COMPACT_WINDOW_WIDTH, COMPACT_WINDOW_HEIGHT, target_position)
            if target_position is not None:
                self._store_compact_experience_window_position(target_position)
            self._update_panel_mode_buttons()
            return
        self._remember_compact_experience_window_position()
        self.compact_experience_mode = False
        self.settings.compact_experience_mode = False
        self._leave_compact_experience_mode()
        width, height = self.default_window_size
        if self.console_collapsed:
            width = WINDOW_COLLAPSED_WIDTH
        else:
            width = max(WINDOW_EXPANDED_MIN_WIDTH, width)
        target_position = self._saved_position(self.settings.full_panel_window_x, self.settings.full_panel_window_y)
        target_height = max(WINDOW_MIN_HEIGHT, height)
        if self.console_collapsed:
            target_height = self._full_window_target_height()
        self._set_window_size(width, target_height, target_position)
        if target_position is not None:
            self._store_full_panel_window_position(target_position)
        self._update_panel_mode_buttons()

    def toggle_window_topmost(self) -> None:
        self.set_window_topmost(not self.window_topmost)

    def set_window_topmost(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self.window_topmost = enabled
        self.settings.window_topmost = enabled
        try:
            self.root.attributes("-topmost", enabled)
        except tk.TclError:
            pass
        self._update_panel_mode_buttons()

    def _update_panel_mode_buttons(self) -> None:
        try:
            if self.panel_mode_button is not None:
                self.panel_mode_button.configure(text="完整面板" if self.compact_experience_mode else "經驗模式")
            if self.topmost_button is not None:
                self.topmost_button.configure(text="取消置頂" if self.window_topmost else "置頂")
        except tk.TclError:
            return

    def _remember_expanded_window_width(self) -> None:
        try:
            current_width = int(self.root.winfo_width())
        except tk.TclError:
            return
        if current_width > WINDOW_COLLAPSED_MIN_WIDTH:
            self.expanded_window_width = max(WINDOW_EXPANDED_MIN_WIDTH, current_width)

    def _remember_default_window_size(self) -> None:
        try:
            width = int(self.root.winfo_width())
            height = int(self.root.winfo_height())
        except tk.TclError:
            return
        if width >= WINDOW_COLLAPSED_MIN_WIDTH and height >= COMPACT_WINDOW_MIN_HEIGHT:
            self.default_window_size = (
                max(WINDOW_COLLAPSED_MIN_WIDTH, width),
                max(WINDOW_MIN_HEIGHT, height),
            )

    def _saved_position(self, x: int | None, y: int | None) -> tuple[int, int] | None:
        if x is None or y is None:
            return None
        position = int(x), int(y)
        if not self._is_window_position_visible(position):
            return None
        return position

    def _is_window_position_visible(self, position: tuple[int, int]) -> bool:
        x, y = position
        if x <= MINIMIZED_WINDOW_POSITION_SENTINEL or y <= MINIMIZED_WINDOW_POSITION_SENTINEL:
            return False
        bounds = self._virtual_screen_bounds()
        if bounds is None:
            return True
        left, top, right, bottom = bounds
        return (
            x >= left - WINDOW_POSITION_VISIBILITY_MARGIN
            and y >= top - WINDOW_POSITION_VISIBILITY_MARGIN
            and x <= right - WINDOW_POSITION_VISIBILITY_MARGIN
            and y <= bottom - WINDOW_POSITION_VISIBILITY_MARGIN
        )

    def _virtual_screen_bounds(self) -> tuple[int, int, int, int] | None:
        try:
            metrics = ctypes.windll.user32.GetSystemMetrics
            left = int(metrics(SM_XVIRTUALSCREEN))
            top = int(metrics(SM_YVIRTUALSCREEN))
            width = int(metrics(SM_CXVIRTUALSCREEN))
            height = int(metrics(SM_CYVIRTUALSCREEN))
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return left, top, left + width, top + height

    def _current_window_position(self) -> tuple[int, int] | None:
        try:
            return int(self.root.winfo_x()), int(self.root.winfo_y())
        except tk.TclError:
            return None

    def _remember_current_mode_window_position(self) -> None:
        if self.compact_experience_mode:
            self._remember_compact_experience_window_position()
            return
        self._remember_full_panel_window_position()

    def _remember_full_panel_window_position(self) -> None:
        position = self._current_window_position()
        if position is not None:
            self._store_full_panel_window_position(position)

    def _remember_compact_experience_window_position(self) -> None:
        position = self._current_window_position()
        if position is not None:
            self._store_compact_experience_window_position(position)

    def _store_full_panel_window_position(self, position: tuple[int, int]) -> None:
        if not self._is_window_position_visible(position):
            self.settings.full_panel_window_x = None
            self.settings.full_panel_window_y = None
            return
        self.settings.full_panel_window_x = int(position[0])
        self.settings.full_panel_window_y = int(position[1])

    def _store_compact_experience_window_position(self, position: tuple[int, int]) -> None:
        if not self._is_window_position_visible(position):
            self.settings.compact_experience_window_x = None
            self.settings.compact_experience_window_y = None
            return
        self.settings.compact_experience_window_x = int(position[0])
        self.settings.compact_experience_window_y = int(position[1])

    def _experience_section_screen_position(self) -> tuple[int, int] | None:
        if self.exp_section is None:
            return None
        try:
            self.root.update_idletasks()
            return int(self.exp_section.winfo_rootx()), int(self.exp_section.winfo_rooty())
        except tk.TclError:
            return None

    def _compact_window_position_for_experience_anchor(
        self,
        experience_anchor: tuple[int, int] | None,
    ) -> tuple[int, int] | None:
        if experience_anchor is None or self.exp_section is None:
            return None
        current_position = self._current_window_position()
        if current_position is None:
            return None
        try:
            self.root.update_idletasks()
            exp_x = int(self.exp_section.winfo_rootx())
            exp_y = int(self.exp_section.winfo_rooty())
        except tk.TclError:
            return None
        return (
            current_position[0] + experience_anchor[0] - exp_x,
            current_position[1] + experience_anchor[1] - exp_y,
        )

    def _geometry_string(
        self,
        width: int,
        height: int,
        position: tuple[int, int] | None = None,
    ) -> str:
        geometry = f"{int(width)}x{int(height)}"
        if position is None:
            return geometry
        return f"{geometry}{int(position[0]):+d}{int(position[1]):+d}"

    def _set_window_width(self, width: int) -> None:
        try:
            height = max(WINDOW_MIN_HEIGHT, int(self.root.winfo_height()))
        except tk.TclError:
            return
        self._set_window_size(width, height)

    def _set_window_size(
        self,
        width: int,
        height: int,
        position: tuple[int, int] | None = None,
    ) -> None:
        try:
            self.suppress_resize_suspend_until = time.monotonic() + 0.25
            self.root.geometry(self._geometry_string(width, height, position))
        except tk.TclError:
            return

    def _enter_compact_experience_mode(self) -> None:
        try:
            self._unfreeze_console_resize()
            self.root.minsize(COMPACT_WINDOW_MIN_WIDTH, COMPACT_WINDOW_MIN_HEIGHT)
            if self.controls_frame is not None:
                self.controls_frame.configure(width=COMPACT_PANEL_WIDTH)
                self.controls_frame.grid_configure(padx=0)
            if self.content_frame is not None:
                self.content_frame.columnconfigure(0, weight=1, minsize=COMPACT_PANEL_WIDTH)
                self.content_frame.columnconfigure(1, weight=0, minsize=0)
            for widget in self.full_panel_widgets:
                widget.grid_remove()
            if self.console_section is not None:
                self.console_section.grid_remove()
            if self.console_restore_button is not None:
                self.console_restore_button.grid_remove()
            if self.monitor_frame is not None:
                self.monitor_frame.grid_configure(row=0, column=0, sticky="nsew", pady=0)
                self.monitor_frame.configure(height=MONITOR_PANEL_HEIGHT)
                self.monitor_frame.grid_propagate(False)
                self.monitor_frame.columnconfigure(0, weight=0, minsize=COMPACT_PANEL_WIDTH)
                self.monitor_frame.columnconfigure(1, weight=0, minsize=0)
            if self.exp_section is not None:
                self.exp_section.configure(width=COMPACT_PANEL_WIDTH, height=MONITOR_PANEL_HEIGHT)
                self.exp_section.grid_propagate(False)
                self.exp_section.grid_configure(row=0, column=0, sticky="nsew", padx=0, pady=0)
        except tk.TclError:
            return

    def _leave_compact_experience_mode(self) -> None:
        try:
            if self.controls_frame is not None:
                self.controls_frame.configure(width=LEFT_PANEL_MAX_WIDTH)
                self.controls_frame.grid_configure(padx=(0, 8))
            if self.content_frame is not None:
                self.content_frame.columnconfigure(0, weight=1, minsize=LEFT_PANEL_MAX_WIDTH)
            if self.monitor_frame is not None:
                self.monitor_frame.grid_configure(row=2, column=0, sticky="ew", pady=(8, 0))
                self.monitor_frame.grid_propagate(True)
                self.monitor_frame.columnconfigure(0, weight=3, minsize=0, uniform="monitor")
                self.monitor_frame.columnconfigure(1, weight=2, minsize=0, uniform="monitor")
            if self.exp_section is not None:
                self.exp_section.grid_propagate(True)
                self.exp_section.grid_configure(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
            if self.detection_section is not None:
                self.detection_section.grid_propagate(True)
            for widget in self.full_panel_widgets:
                widget.grid()
            if self.console_collapsed:
                self._collapse_console_panel()
            else:
                self._restore_console_panel()
            if self.monitor_responsive_relayout is not None:
                self.root.after_idle(self.monitor_responsive_relayout)
        except tk.TclError:
            return

    def _collapse_console_panel(self) -> None:
        try:
            self.root.minsize(WINDOW_COLLAPSED_MIN_WIDTH, COMPACT_WINDOW_MIN_HEIGHT)
            if self.content_frame is not None:
                self.content_frame.columnconfigure(1, weight=0, minsize=0)
            if self.console_section is not None:
                self.console_section.grid_remove()
            if self.console_restore_button is not None:
                self.console_restore_button.grid()
        except tk.TclError:
            return

    def _restore_console_panel(self) -> None:
        try:
            self.root.minsize(WINDOW_EXPANDED_MIN_WIDTH, WINDOW_MIN_HEIGHT)
            if self.content_frame is not None:
                self.content_frame.columnconfigure(1, weight=0, minsize=0)
            if self.console_restore_button is not None:
                self.console_restore_button.grid_remove()
        except tk.TclError:
            return
        self._schedule_console_height_sync()

    def _suspend_layout_for_resize(self) -> None:
        if self.resize_layout_suspended or self.content_frame is None:
            return
        try:
            self._hide_tooltip()
            self._unfreeze_console_resize()
            self.content_frame.grid_remove()
        except tk.TclError:
            return
        self.resize_layout_suspended = True

    def _restore_layout_after_resize(self) -> None:
        if not self.resize_layout_suspended or self.content_frame is None:
            return
        try:
            self.content_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
            self.suppress_resize_suspend_until = time.monotonic() + 0.08
        except tk.TclError:
            return
        self.resize_layout_suspended = False

    def _begin_restore_repaint(self, now: float) -> None:
        self.restore_repaint_until = max(
            getattr(self, "restore_repaint_until", 0.0),
            now + RESTORE_REPAINT_GRACE_SECONDS,
        )
        self.window_interaction_pause_until = self.restore_repaint_until
        self.suppress_resize_suspend_until = max(
            getattr(self, "suppress_resize_suspend_until", 0.0),
            self.restore_repaint_until,
        )
        self._restore_layout_after_resize()
        if self.restore_repaint_after_id is not None:
            try:
                self.root.after_cancel(self.restore_repaint_after_id)
            except tk.TclError:
                pass
        try:
            self.restore_repaint_after_id = self.root.after_idle(self._finish_restore_repaint)
        except tk.TclError:
            self.restore_repaint_after_id = None
            self._finish_restore_repaint()

    def _finish_restore_repaint(self) -> None:
        self.restore_repaint_after_id = None
        try:
            self.root.update_idletasks()
        except tk.TclError:
            return
        self._unfreeze_console_resize()
        self._schedule_console_height_sync()

    def _schedule_window_interaction_finish(self) -> None:
        if self.console_resize_after_id is not None:
            try:
                self.root.after_cancel(self.console_resize_after_id)
            except tk.TclError:
                pass
        self.console_resize_after_id = self.root.after(RESIZE_SETTLE_DELAY_MS, self._finish_window_interaction)

    def _finish_window_interaction(self) -> None:
        self.console_resize_after_id = None
        self.window_interaction_pause_until = 0.0
        self._restore_layout_after_resize()
        self._unfreeze_console_resize()
        self._schedule_console_height_sync()
        self._remember_current_mode_window_position()

    def _unfreeze_console_resize(self) -> None:
        if self.console_collapsed or not self.console_resize_frozen or self.console_container is None:
            return
        try:
            if self.console_frame is not None:
                self.console_frame.columnconfigure(0, weight=1)
                self.console_frame.rowconfigure(0, weight=1)
            self.console_container.configure(width=CONSOLE_MIN_WIDTH)
            self.console_container.grid_configure(sticky="nsew")
        except tk.TclError:
            return
        self.console_resize_frozen = False
        self._schedule_console_height_sync()

    def _schedule_console_height_sync(self) -> None:
        if (
            getattr(self, "closed", False)
            or getattr(self, "compact_experience_mode", False)
            or getattr(self, "console_collapsed", False)
            or getattr(self, "active_page", "監控") == "Console"
            or getattr(self, "controls_frame", None) is None
            or getattr(self, "console_container", None) is None
        ):
            return
        if getattr(self, "console_height_after_id", None) is not None:
            try:
                self.root.after_cancel(self.console_height_after_id)
            except tk.TclError:
                pass
        try:
            self.console_height_after_id = self.root.after(20, self._sync_console_height_to_left_panel)
        except tk.TclError:
            self.console_height_after_id = None

    def _sync_console_height_to_left_panel(self) -> None:
        self.console_height_after_id = None
        if (
            self.closed
            or self.compact_experience_mode
            or self.console_collapsed
            or getattr(self, "active_page", "監控") == "Console"
        ):
            return
        if self.controls_frame is None or self.console_container is None:
            return
        try:
            self.root.update_idletasks()
            left_height = self._left_panel_content_height()
            if left_height <= 0:
                return
            console_height = max(CONSOLE_MIN_BODY_HEIGHT, left_height - CONSOLE_HEADER_BODY_RESERVED_HEIGHT)
            if self.console_collapsed:
                self.controls_frame.configure(height=left_height)
            if self.console_section is not None:
                self.console_section.configure(height=left_height)
            self.console_container.configure(width=CONSOLE_MIN_WIDTH, height=console_height)
            self.console_container.grid_configure(sticky="nsew")
            self._sync_full_window_height_to_left_panel(left_height)
        except tk.TclError:
            return

    def _left_panel_content_height(self) -> int:
        if self.controls_frame is None:
            return 0
        try:
            _left, top, _width, height = self.controls_frame.grid_bbox()
            if height > 0:
                return int(top + height)
        except tk.TclError:
            pass
        return int(self.controls_frame.winfo_reqheight())

    def _full_window_target_height(self, left_height: int | None = None) -> int:
        if left_height is None:
            left_height = self._left_panel_content_height()
        if left_height <= 0:
            return WINDOW_MIN_HEIGHT
        return max(COMPACT_WINDOW_MIN_HEIGHT, left_height + WINDOW_CONTENT_VERTICAL_PADDING)

    def _sync_full_window_height_to_left_panel(
        self,
        left_height: int | None = None,
        *,
        width: int | None = None,
    ) -> None:
        if self.compact_experience_mode:
            return
        if self.controls_frame is None:
            return
        try:
            if left_height is None:
                self.root.update_idletasks()
                left_height = self._left_panel_content_height()
            if left_height <= 0:
                return
            min_width = WINDOW_COLLAPSED_MIN_WIDTH if self.console_collapsed else WINDOW_EXPANDED_MIN_WIDTH
            target_height = self._full_window_target_height(left_height)
            self.controls_frame.configure(height=left_height)
            self.root.minsize(min_width, target_height)
            current_width = int(self.root.winfo_width())
            target_width = max(min_width, int(width) if width is not None else current_width)
            current_height = int(self.root.winfo_height())
            if current_width != target_width or current_height != target_height:
                self._set_window_size(target_width, target_height)
        except tk.TclError:
            return

    def _combo_script_label(self, script_id: str) -> str:
        return COMBO_SCRIPT_LABELS.get(script_id, COMBO_SCRIPT_LABELS[COMBO_SCRIPT_SINGLE_JUMP_SKILL])

    def _combo_script_id(self, script_label: str, fallback: str) -> str:
        return normalize_combo_script_id(COMBO_SCRIPT_LABEL_TO_ID.get(script_label), fallback)

    def _combo_a_description(self) -> str:
        return self._combo_slot_description(
            "A",
            self.rb_controller_button,
            self.combo_a_script,
            self.rb_jump_key,
            self.rb_skill_key,
            self.rb_attack_key,
            self.rb_attack_start_delay,
            self.rb_attack_hold,
            self.rb_skill_delay,
            self.rb_jump_interval,
        )

    def _combo_b_description(self) -> str:
        return self._combo_slot_description(
            "B",
            self.lb_controller_button,
            self.combo_b_script,
            self.lb_jump_key,
            self.lb_skill_key,
            self.lb_attack_key,
            self.lb_attack_start_delay,
            self.lb_attack_hold,
            self.lb_skill_delay,
            self.lb_jump_interval,
        )

    def _combo_slot_description(
        self,
        slot_id: str,
        trigger_var: tk.StringVar,
        script_var: tk.StringVar,
        jump_key_var: tk.StringVar,
        skill_key_var: tk.StringVar,
        attack_key_var: tk.StringVar,
        attack_start_delay_var: tk.StringVar,
        attack_hold_var: tk.StringVar,
        skill_delay_var: tk.StringVar,
        jump_interval_var: tk.StringVar,
    ) -> str:
        script_id = self._combo_script_id(script_var.get(), COMBO_SCRIPT_SINGLE_JUMP_SKILL)
        if script_id == COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP:
            return (
                f"組合{slot_id} 按住 {trigger_var.get()} 時按住 {jump_key_var.get()} 跳躍，"
                f"{attack_start_delay_var.get()} 秒後開始攻擊，"
                f"每 {jump_interval_var.get()} 秒按住 {attack_key_var.get()} 攻擊 {attack_hold_var.get()} 秒。"
            )
        if script_id == COMBO_SCRIPT_REPEATING_JUMP_SKILL:
            return (
                f"組合{slot_id} 按下 {trigger_var.get()} 時，每 {jump_interval_var.get()} 秒短按 "
                f"{jump_key_var.get()} 跳躍，並在每次跳躍 {skill_delay_var.get()} 秒後按 "
                f"{skill_key_var.get()}。"
            )
        return (
            f"組合{slot_id} 按下 {trigger_var.get()} 時短按 {jump_key_var.get()} 跳躍一次，"
            f"並在 {skill_delay_var.get()} 秒後按 {skill_key_var.get()}。"
        )

    def _on_combo_script_changed(self) -> None:
        self._refresh_combo_script_visibility()
        self.apply_to_settings()

    def _refresh_combo_script_visibility(self) -> None:
        script_vars = {
            "A": self.combo_a_script,
            "B": self.combo_b_script,
        }
        for slot_id in ("A", "B"):
            widgets_by_kind = {
                "skill_key": self.combo_skill_key_fields.get(slot_id, ()),
                "attack_key": self.combo_attack_key_fields.get(slot_id, ()),
                "skill_delay": self.combo_skill_delay_fields.get(slot_id, ()),
                "attack_start_delay": self.combo_attack_start_delay_fields.get(slot_id, ()),
                "attack_hold": self.combo_attack_hold_fields.get(slot_id, ()),
                "jump_interval": self.combo_jump_interval_fields.get(slot_id, ()),
            }
            script_var = script_vars.get(slot_id)
            if script_var is None:
                continue
            script_id = self._combo_script_id(script_var.get(), COMBO_SCRIPT_SINGLE_JUMP_SKILL)
            show_skill_fields = script_id != COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP
            show_attack_fields = script_id == COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP
            show_interval = script_id in (COMBO_SCRIPT_REPEATING_JUMP_SKILL, COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP)
            visibility = {
                "skill_key": show_skill_fields,
                "attack_key": show_attack_fields,
                "skill_delay": show_skill_fields,
                "attack_start_delay": show_attack_fields,
                "attack_hold": show_attack_fields,
                "jump_interval": show_interval,
            }
            field_flow = self.combo_field_flows.get(slot_id)
            for kind, widgets in widgets_by_kind.items():
                for widget in widgets:
                    if field_flow is not None:
                        field_flow.set_visible(widget, visibility[kind])
                    elif visibility[kind]:
                        widget.grid()
                    else:
                        widget.grid_remove()
            if field_flow is not None:
                field_flow.layout()

    def _step_seconds(self, value_var: tk.StringVar, delta: float, minimum: float, maximum: float) -> None:
        try:
            current = float(value_var.get())
        except ValueError:
            current = minimum
        value = max(minimum, min(maximum, round(current + delta, 2)))
        value_var.set(f"{value:.2f}")

    def _apply_percent_text(self, value_var: tk.DoubleVar, text_var: tk.StringVar) -> None:
        try:
            value = max(1.0, min(100.0, float(text_var.get())))
        except ValueError:
            value = value_var.get()

        value_var.set(value)
        text_var.set(f"{value:.0f}")

    def close(self) -> None:
        self.cancel_minimap_cruise_boundary_setup()
        self.cancel_key_detection()
        self.close_minimap_cruise_extra_settings()
        self._remember_current_mode_window_position()
        self.apply_to_settings()
        save_settings(self.settings, SETTINGS_PATH)
        self._destroy_toggle_notice()
        self._hide_tooltip()
        if self.page_build_after_id is not None:
            try:
                self.root.after_cancel(self.page_build_after_id)
            except tk.TclError:
                pass
            self.page_build_after_id = None
        for placeholder in self.page_placeholders.values():
            try:
                placeholder.destroy()
            except tk.TclError:
                pass
        self.page_placeholders.clear()
        if self.console_resize_after_id is not None:
            try:
                self.root.after_cancel(self.console_resize_after_id)
            except tk.TclError:
                pass
            self.console_resize_after_id = None
        if self.console_height_after_id is not None:
            try:
                self.root.after_cancel(self.console_height_after_id)
            except tk.TclError:
                pass
            self.console_height_after_id = None
        if self.restore_repaint_after_id is not None:
            try:
                self.root.after_cancel(self.restore_repaint_after_id)
            except tk.TclError:
                pass
            self.restore_repaint_after_id = None
        if self.console_flush_after_id is not None:
            try:
                self.root.after_cancel(self.console_flush_after_id)
            except tk.TclError:
                pass
            self.console_flush_after_id = None
        if self.monitor_controls_after_id is not None:
            try:
                self.root.after_cancel(self.monitor_controls_after_id)
            except tk.TclError:
                pass
            self.monitor_controls_after_id = None
        self.closed = True
        self.root.destroy()

    def set_bar_preview_provider(self, provider: Callable[[bool], dict[str, dict[str, object]]]) -> None:
        self.bar_preview_provider = provider

    def set_experience_reset_handler(self, handler: Callable[[], bool | None]) -> None:
        self.experience_reset_handler = handler

    def set_auto_drink_toggle_handler(self, handler: Callable[[bool], bool | None]) -> None:
        self.auto_drink_toggle_handler = handler

    def set_pickup_toggle_handler(self, handler: Callable[[bool], bool | None]) -> None:
        self.pickup_toggle_handler = handler

    def reset_experience_statistics(self) -> None:
        if self.experience_reset_handler is not None:
            if self.experience_reset_handler() is False:
                return
        self.set_experience_snapshot(ExperienceSnapshot(status="已重置"))

    def is_detecting_key(self) -> bool:
        return self.detecting_key_target is not None

    def consume_key_detection_finished(self) -> bool:
        if not self.key_detection_just_finished:
            return False
        self.key_detection_just_finished = False
        return True

    def is_key_detection_release_pending(self) -> bool:
        if not self.key_detection_release_vks:
            return False
        if self.key_detection_release_vks & pressed_detectable_vks():
            return True
        self.key_detection_release_vks = set()
        return False

    def is_app_window_foreground(self) -> bool:
        if self.closed:
            return False
        foreground_hwnd = int(user32.GetForegroundWindow() or 0)
        if not foreground_hwnd:
            return False
        for window in self._app_top_level_windows():
            try:
                if bool(window.winfo_exists()) and int(window.winfo_id()) == foreground_hwnd:
                    return True
            except tk.TclError:
                continue
        return False

    def _app_top_level_windows(self) -> tuple[tk.Misc, ...]:
        windows: list[tk.Misc] = [self.root]
        for candidate in (
            self.key_detection_window,
            self.minimap_cruise_extra_settings_window,
            self.toggle_notice_window,
            self.tooltip_window,
        ):
            if candidate is not None and not any(candidate is existing for existing in windows):
                windows.append(candidate)
        for candidate in self.tooltip_windows:
            if not any(candidate is existing for existing in windows):
                windows.append(candidate)
        return tuple(windows)

    def refresh_bar_preview_once(self) -> None:
        if self.bar_preview_has_snapshot:
            return
        self._refresh_bar_preview(make_target_topmost=False)

    def refresh_bar_preview(self) -> None:
        self._refresh_bar_preview(make_target_topmost=True)

    def _refresh_bar_preview(self, make_target_topmost: bool) -> None:
        if self.bar_preview_provider is None:
            self.set_status("尚未連接偵測預覽來源")
            return
        try:
            previews = self.bar_preview_provider(make_target_topmost)
        except Exception as exc:
            self.set_status(f"偵測預覽失敗：{exc}")
            return

        image_payloads: dict[str, bytes] = {}
        for bar_type in ("hp", "mp"):
            preview = previews.get(bar_type, {})
            image_data = preview.get("image")
            if not isinstance(image_data, bytes):
                self.set_status("HP/MP 預覽未更新：尚未同時抓到 HP/MP 條")
                return
            image_payloads[bar_type] = image_data

        next_images = {
            bar_type: self._ctk_preview_image_from_ppm(image_payloads[bar_type])
            for bar_type in ("hp", "mp")
        }
        self.bar_preview_images = []
        for bar_type in ("hp", "mp"):
            image = next_images[bar_type]
            self.bar_preview_images.append(image)
            self.bar_preview_labels[bar_type].configure(image=image, text="")
        self.bar_preview_has_snapshot = True

    def _ctk_preview_image_from_ppm(self, image_data: bytes) -> ctk.CTkImage:
        from PIL import Image

        with Image.open(io.BytesIO(image_data)) as pil_image:
            preview_image = pil_image.copy()
        return ctk.CTkImage(
            light_image=preview_image,
            dark_image=preview_image,
            size=preview_image.size,
        )

    def _ctk_image_from_path(self, path: Path, *, max_size: tuple[int, int]) -> ctk.CTkImage:
        from PIL import Image

        with Image.open(path) as pil_image:
            preview_image = pil_image.convert("RGB")
        preview_image.thumbnail(max_size)
        return ctk.CTkImage(
            light_image=preview_image,
            dark_image=preview_image,
            size=preview_image.size,
        )

    def _refresh_profile_select(self) -> None:
        if self.profile_select is None:
            return
        self.profile_select.configure(values=self.settings.profile_names())
        self.active_profile.set(self.settings.active_profile)

    def _sync_vars_from_settings(self) -> None:
        self.active_profile.set(self.settings.active_profile)
        self.hp_enabled.set(self.settings.hp_enabled)
        self.mp_enabled.set(self.settings.mp_enabled)
        self.potion_enabled_ui_only_snapshot = None
        self.rb_enabled.set(self.settings.rb_enabled)
        self.lb_enabled.set(self.settings.lb_enabled)
        self.hp_threshold.set(self.settings.hp_threshold_percent)
        self.mp_threshold.set(self.settings.mp_threshold_percent)
        self.hp_threshold_text.set(f"{self.settings.hp_threshold_percent:.0f}")
        self.mp_threshold_text.set(f"{self.settings.mp_threshold_percent:.0f}")
        self.hp_key.set(self.settings.hp_key)
        self.mp_key.set(self.settings.mp_key)
        self.hp_cooldown.set(f"{self.settings.hp_cooldown_seconds:g}")
        self.mp_cooldown.set(f"{self.settings.mp_cooldown_seconds:g}")
        self.hp_continuous_enabled.set(self.settings.hp_continuous_enabled)
        self.mp_continuous_enabled.set(self.settings.mp_continuous_enabled)
        self.hp_continuous_stop_margin.set(f"{self.settings.hp_continuous_stop_margin_percent:g}")
        self.mp_continuous_stop_margin.set(f"{self.settings.mp_continuous_stop_margin_percent:g}")
        self.rb_jump_key.set(self.settings.rb_jump_key)
        self.rb_skill_key.set(self.settings.rb_skill_key)
        self.rb_attack_key.set(str(self.settings.combo_slot("A")["attack_key"]))
        self.rb_attack_start_delay.set(f"{float(self.settings.combo_slot('A')['attack_start_delay_seconds']):g}")
        self.rb_attack_hold.set(f"{float(self.settings.combo_slot('A')['attack_hold_seconds']):g}")
        self.rb_controller_button.set(self.settings.rb_controller_button)
        self.rb_skill_delay.set(f"{self.settings.rb_skill_delay_seconds:g}")
        self.rb_jump_interval.set(f"{self.settings.rb_jump_interval_seconds:g}")
        self.lb_jump_key.set(self.settings.lb_jump_key)
        self.lb_skill_key.set(self.settings.lb_skill_key)
        self.lb_attack_key.set(str(self.settings.combo_slot("B")["attack_key"]))
        self.lb_attack_start_delay.set(f"{float(self.settings.combo_slot('B')['attack_start_delay_seconds']):g}")
        self.lb_attack_hold.set(f"{float(self.settings.combo_slot('B')['attack_hold_seconds']):g}")
        self.lb_controller_button.set(self.settings.lb_controller_button)
        self.lb_skill_delay.set(f"{self.settings.lb_skill_delay_seconds:g}")
        self.lb_jump_interval.set(f"{float(self.settings.combo_slot('B')['jump_interval_seconds']):g}")
        self.combo_a_script.set(self._combo_script_label(str(self.settings.combo_slot("A")["script_id"])))
        self.combo_b_script.set(self._combo_script_label(str(self.settings.combo_slot("B")["script_id"])))
        self._refresh_combo_script_visibility()
        self.exp_efficiency_enabled.set(self.settings.exp_efficiency_enabled)
        self.toggle_hotkey.set(self.settings.toggle_hotkey)
        self.emergency_stop_hotkey.set(self.settings.emergency_stop_hotkey)
        self.experience_toggle_hotkey.set(self.settings.experience_toggle_hotkey)
        self.experience_reset_hotkey.set(self.settings.experience_reset_hotkey)
        self.character_stat_hotkey.set(self.settings.character_stat_hotkey)
        self.pickup_toggle_hotkey.set(self.settings.pickup_toggle_hotkey or "")
        self.pickup_key.set(self.settings.pickup_key or "")
        self.minimap_cruise_toggle_hotkey.set(self.settings.minimap_cruise_toggle_hotkey or "")
        self.minimap_cruise_attack_key.set(self.settings.minimap_cruise_attack_key)
        self.minimap_cruise_pre_boundary_skill_enabled.set(
            self.settings.minimap_cruise_pre_boundary_skill_enabled
        )
        self.minimap_cruise_pre_boundary_skill_key.set(self.settings.minimap_cruise_pre_boundary_skill_key)
        self.minimap_cruise_pre_boundary_distance.set(f"{self.settings.minimap_cruise_pre_boundary_distance:g}")
        self.minimap_cruise_stationary_skill_key.set(self.settings.minimap_cruise_stationary_skill_key)
        self.minimap_cruise_stationary_min_forward_pixels.set(
            f"{self.settings.minimap_cruise_stationary_min_forward_pixels:g}"
        )
        periodic_enabled = (
            self.settings.minimap_cruise_periodic_key_1_enabled,
            self.settings.minimap_cruise_periodic_key_2_enabled,
            self.settings.minimap_cruise_periodic_key_3_enabled,
            self.settings.minimap_cruise_periodic_key_4_enabled,
            self.settings.minimap_cruise_periodic_key_5_enabled,
        )
        periodic_keys = (
            self.settings.minimap_cruise_periodic_key_1,
            self.settings.minimap_cruise_periodic_key_2,
            self.settings.minimap_cruise_periodic_key_3,
            self.settings.minimap_cruise_periodic_key_4,
            self.settings.minimap_cruise_periodic_key_5,
        )
        periodic_intervals = (
            self.settings.minimap_cruise_periodic_key_1_interval_seconds,
            self.settings.minimap_cruise_periodic_key_2_interval_seconds,
            self.settings.minimap_cruise_periodic_key_3_interval_seconds,
            self.settings.minimap_cruise_periodic_key_4_interval_seconds,
            self.settings.minimap_cruise_periodic_key_5_interval_seconds,
        )
        for index in range(len(self.minimap_cruise_periodic_key_enabled_vars)):
            self.minimap_cruise_periodic_key_enabled_vars[index].set(periodic_enabled[index])
            self.minimap_cruise_periodic_key_vars[index].set(periodic_keys[index])
            self.minimap_cruise_periodic_key_interval_vars[index].set(f"{periodic_intervals[index]:g}")
        self.minimap_cruise_boundary_status.set(self._minimap_cruise_boundary_status_text())
        self.set_window_topmost(self.settings.window_topmost)
        self.set_minimap_cruise_group_collapsed(self.settings.minimap_cruise_group_collapsed)
        self.set_combo_group_collapsed(self.settings.combo_group_collapsed)
        self.set_console_collapsed(self.settings.console_collapsed)
        self.set_compact_experience_mode(self.settings.compact_experience_mode)
        self._refresh_profile_select()

    def _switch_profile(self, _event: tk.Event | None = None) -> str:
        target_profile = normalize_profile_name(self.active_profile.get(), self.settings.active_profile)
        if target_profile == self.settings.active_profile:
            return "break"
        self.apply_to_settings()
        if self.settings.apply_profile(target_profile):
            self._sync_vars_from_settings()
            self.set_status(f"已切換設定檔：{target_profile}")
        else:
            self._refresh_profile_select()
            self.set_status("設定檔切換失敗")
        return "break"

    def create_profile(self) -> None:
        self.apply_to_settings()
        name = simpledialog.askstring("新增設定檔", "設定檔名稱", parent=self.root)
        profile_name = normalize_profile_name(name, "")
        if not profile_name:
            return
        if not self.settings.create_profile(profile_name):
            self.set_status(f"設定檔已存在：{profile_name}")
            return
        self._sync_vars_from_settings()
        self.set_status(f"已新增設定檔：{profile_name}")

    def delete_profile(self) -> None:
        profile_name = normalize_profile_name(self.active_profile.get(), self.settings.active_profile)
        if len(self.settings.profile_names()) <= 1:
            self.set_status("至少需保留一個設定檔")
            return
        if not messagebox.askyesno("刪除設定檔", f"刪除設定檔「{profile_name}」？", parent=self.root):
            return
        if not self.settings.delete_profile(profile_name):
            self.set_status("設定檔刪除失敗")
            return
        self._sync_vars_from_settings()
        self.set_status(f"已刪除設定檔：{profile_name}")

    def export_settings(self) -> None:
        self.apply_to_settings()
        self.settings.save_current_profile()
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="匯出設定",
            defaultextension=".json",
            filetypes=(("JSON 設定檔", "*.json"), ("所有檔案", "*.*")),
            initialfile="maple-star-settings.json",
        )
        if not path:
            return
        try:
            save_settings(self.settings, Path(path))
        except OSError as exc:
            self.set_status(f"匯出設定失敗：{exc}")
            return
        self.set_status(f"已匯出設定：{path}")

    def import_settings(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="匯入設定",
            filetypes=(("JSON 設定檔", "*.json"), ("所有檔案", "*.*")),
        )
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
            if not isinstance(json.loads(raw), dict):
                raise ValueError("設定檔根節點必須是 JSON object")
            imported = load_settings(Path(path), save_migrations=False)
            copy_setting_values(imported, self.settings)
            self.settings.active_profile = imported.active_profile
            self.settings.profiles = imported.profiles
            save_settings(self.settings, SETTINGS_PATH)
        except Exception as exc:
            self.set_status(f"匯入設定失敗：{exc}")
            return

        self._sync_vars_from_settings()
        self.set_status(f"已匯入設定：{path}")

    def _minimap_cruise_boundary_status_text(self) -> str:
        left_x = self.settings.minimap_cruise_left_x
        right_x = self.settings.minimap_cruise_right_x
        detect_y = self.settings.minimap_cruise_detect_y
        if left_x is None or right_x is None or detect_y is None:
            return "邊界：未設定"
        left_x, right_x = sorted((int(left_x), int(right_x)))
        return f"邊界：X {left_x}-{right_x} / Y {int(detect_y)}"

    def start_minimap_cruise_boundary_setup(self) -> None:
        self.cancel_key_detection()
        self.cancel_minimap_cruise_boundary_setup(keep_status=True)
        self.minimap_cruise_boundary_step = "left"
        self.minimap_cruise_first_point = None
        self.minimap_cruise_mouse_was_down = self._left_mouse_button_is_down()
        self.minimap_cruise_boundary_status.set("邊界：請點左界")
        self.set_status("請點擊小地圖左邊界")
        self._schedule_minimap_cruise_boundary_poll()

    def cancel_minimap_cruise_boundary_setup(self, keep_status: bool = False) -> None:
        after_id = getattr(self, "minimap_cruise_boundary_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
            self.minimap_cruise_boundary_after_id = None
        self.minimap_cruise_boundary_step = ""
        self.minimap_cruise_first_point = None
        self.minimap_cruise_mouse_was_down = False
        if not keep_status and not self.closed:
            self.minimap_cruise_boundary_status.set(self._minimap_cruise_boundary_status_text())

    def _schedule_minimap_cruise_boundary_poll(self) -> None:
        if not getattr(self, "minimap_cruise_boundary_step", "") or self.closed:
            return
        self.minimap_cruise_boundary_after_id = self.root.after(
            MINIMAP_BOUNDARY_POLL_MS,
            self._poll_minimap_cruise_boundary_click,
        )

    def _poll_minimap_cruise_boundary_click(self) -> None:
        if not getattr(self, "minimap_cruise_boundary_step", ""):
            return
        is_down = self._left_mouse_button_is_down()
        if is_down and not self.minimap_cruise_mouse_was_down:
            point = self._current_foreground_client_point()
            if point is None:
                self.set_status("請在小地圖所在的遊戲視窗內點擊")
            elif self.minimap_cruise_boundary_step == "left":
                self.minimap_cruise_first_point = point
                self.minimap_cruise_boundary_step = "right"
                self.minimap_cruise_boundary_status.set(f"左界：X {point[0]} / 請點右界")
                self.set_status("請點擊小地圖右邊界")
            else:
                first = self.minimap_cruise_first_point
                if first is not None:
                    left_x, right_x = sorted((first[0], point[0]))
                    if right_x - left_x < MINIMAP_CRUISE_MIN_BOUNDARY_WIDTH_PIXELS:
                        self.minimap_cruise_first_point = None
                        self.minimap_cruise_boundary_step = "left"
                        self.minimap_cruise_boundary_status.set("邊界：請重新點左界")
                        self.set_status("小地圖巡航邊界寬度至少需 20 px")
                        self.minimap_cruise_mouse_was_down = is_down
                        self._schedule_minimap_cruise_boundary_poll()
                        return
                    if abs(first[1] - point[1]) > MINIMAP_CRUISE_MAX_BOUNDARY_Y_DELTA_PIXELS:
                        self.minimap_cruise_first_point = None
                        self.minimap_cruise_boundary_step = "left"
                        self.minimap_cruise_boundary_status.set("邊界：請重新點左界")
                        self.set_status("小地圖巡航左右邊界高度差不得超過 30 px")
                        self.minimap_cruise_mouse_was_down = is_down
                        self._schedule_minimap_cruise_boundary_poll()
                        return
                    detect_y = round((first[1] + point[1]) / 2)
                    self.settings.minimap_cruise_left_x = left_x
                    self.settings.minimap_cruise_right_x = right_x
                    self.settings.minimap_cruise_detect_y = detect_y
                    self.minimap_cruise_boundary_status.set(self._minimap_cruise_boundary_status_text())
                    self.set_status("小地圖巡航邊界已設定")
                    self.cancel_minimap_cruise_boundary_setup(keep_status=True)
                    self.apply_to_settings()
                    return
        self.minimap_cruise_mouse_was_down = is_down
        self._schedule_minimap_cruise_boundary_poll()

    def _left_mouse_button_is_down(self) -> bool:
        return bool(user32.GetAsyncKeyState(VK_LBUTTON) & ASYNC_KEY_DOWN_MASK)

    def _current_foreground_client_point(self) -> tuple[int, int] | None:
        cursor = Point()
        if not user32.GetCursorPos(ctypes.byref(cursor)):
            return None
        rect = self._foreground_client_rect()
        if rect is None:
            return None
        left, top, right, bottom = rect
        if not (left <= cursor.x < right and top <= cursor.y < bottom):
            return None
        return cursor.x - left, cursor.y - top

    def _start_key_detection_from_entry(self, event: tk.Event, target: tk.StringVar, label: str) -> str:
        source_widget = getattr(event, "widget", None)
        return self.start_key_detection(target, label, source_widget=source_widget)

    def start_key_detection(
        self,
        target: tk.StringVar,
        label: str,
        *,
        source_widget: tk.Misc | None = None,
    ) -> str:
        self.cancel_key_detection()
        self._install_key_detection_focus_guards(source_widget)
        self.detecting_key_target = target
        self.detecting_key_label = label
        self.detecting_vk_down = pressed_detectable_vks()
        self.set_status(f"請按下要設定為 {label} 的按鍵")
        self.key_detection_window = self._create_auxiliary_window(fg_color=PANEL_BG)
        self.key_detection_window.title("快捷鍵偵測")
        self.key_detection_window.resizable(False, False)
        self.key_detection_window.protocol("WM_DELETE_WINDOW", self.cancel_key_detection)
        self._label(
            self.key_detection_window,
            text=f"請按下要設定為 {label} 的按鍵",
            color=HEADER_TEXT,
            font=TITLE_FONT,
        ).grid(row=0, column=0, sticky="nsew", padx=18, pady=16)
        self.key_detection_window.update_idletasks()
        self._prepare_auxiliary_window_for_show(self.key_detection_window)
        x = self.root.winfo_rootx() + 80
        y = self.root.winfo_rooty() + 80
        self.key_detection_window.geometry(f"+{x}+{y}")
        self.key_detection_window.deiconify()
        self.key_detection_window.bind("<KeyPress>", self._capture_keypress)
        try:
            self.key_detection_window.grab_set()
        except tk.TclError:
            pass
        self.key_detection_window.focus_set()
        self.key_detection_window.focus_force()
        self.root.bind_all("<KeyPress>", self._capture_keypress)
        return "break"

    def _install_key_detection_focus_guards(self, source_widget: tk.Misc | None = None) -> None:
        self._clear_key_detection_focus_guards()
        widgets: list[tk.Misc] = []
        try:
            focused_widget = self.root.focus_get()
        except tk.TclError:
            focused_widget = None
        for widget in (focused_widget, source_widget):
            if widget is None or any(widget is existing for existing in widgets):
                continue
            widgets.append(widget)
        for widget in widgets:
            try:
                binding_id = widget.bind("<KeyPress>", self._capture_keypress, add="+")
            except tk.TclError:
                continue
            if binding_id:
                self.key_detection_focus_bindings.append((widget, binding_id))

    def _clear_key_detection_focus_guards(self) -> None:
        bindings = getattr(self, "key_detection_focus_bindings", [])
        for widget, binding_id in bindings:
            try:
                widget.unbind("<KeyPress>", binding_id)
            except tk.TclError:
                pass
        self.key_detection_focus_bindings = []

    def _capture_keypress(self, event: tk.Event) -> str:
        if self.detecting_key_target is None:
            return "break"

        hotkey = event_to_hotkey(event)
        if hotkey is None:
            self.set_status("不支援只設定修飾鍵，請按一般按鍵")
            return "break"
        try:
            parse_vk_key(hotkey)
        except ValueError:
            self.set_status("等待可辨識的鍵盤按鍵")
            return "break"

        self._finish_key_detection(hotkey)
        return "break"

    def _poll_key_detection(self) -> None:
        if self.detecting_key_target is None:
            return

        current_down = pressed_detectable_vks()
        new_down = current_down - self.detecting_vk_down
        if new_down:
            for vk_code in DETECTABLE_KEY_VKS:
                if vk_code in new_down:
                    hotkey = vk_to_key_name(vk_code)
                    if hotkey is not None:
                        self._finish_key_detection(hotkey)
                    return
        self.detecting_vk_down = current_down

    def _finish_key_detection(self, hotkey: str) -> None:
        if self.detecting_key_target is None:
            return
        try:
            release_vk = parse_vk_key(hotkey)
        except ValueError:
            release_vk = 0
        self.detecting_key_target.set(hotkey)
        self.set_status(f"{self.detecting_key_label} 快捷鍵已設定為 {hotkey}")
        self.key_detection_just_finished = True
        self.key_detection_release_vks = {release_vk} if release_vk else set()
        self.cancel_key_detection(keep_status=True)

    def cancel_key_detection(self, keep_status: bool = False) -> None:
        self.root.unbind_all("<KeyPress>")
        self._clear_key_detection_focus_guards()
        self.detecting_key_target = None
        self.detecting_key_label = ""
        self.detecting_vk_down = set()
        if self.key_detection_window is not None:
            try:
                self.key_detection_window.grab_release()
            except tk.TclError:
                pass
            try:
                self.key_detection_window.destroy()
            except tk.TclError:
                pass
            self.key_detection_window = None
        if not keep_status and not self.closed:
            self.set_status("控制熱鍵可在楓星或本程式前景觸發")

    def pump(self) -> bool:
        if self.closed:
            return False
        try:
            self.root.update_idletasks()
            self.root.update()
        except (tk.TclError, RuntimeError) as exc:
            if self.closed:
                return False
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"GUI 更新暫時失敗，已略過：{exc}")
                self.last_gui_error_at = now
            return True

        return self.sync_after_event_processing()

    def sync_after_event_processing(self) -> bool:
        if self.closed:
            return False
        if self.is_window_interaction_active():
            return False
        self._poll_key_detection()
        self.apply_to_settings()
        return True

    def exists(self) -> bool:
        if self.closed:
            return False
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            self.closed = True
            return False

    def apply_to_settings(self) -> None:
        previous_minimap_settings = {
            name: getattr(self.settings, name)
            for name in self.settings.__dataclass_fields__
            if name.startswith("minimap_cruise_")
        }
        self._read_percent(self.hp_threshold, self.hp_threshold_text)
        self._read_percent(self.mp_threshold, self.mp_threshold_text)
        self.settings.normalize_combo_slots()
        lb_jump_interval_fallback = float(self.settings.combo_slots["B"]["jump_interval_seconds"])

        rb_enabled = self.rb_enabled.get()
        lb_enabled = self.lb_enabled.get()
        rb_jump_key = self.rb_jump_key.get().strip()
        rb_skill_key = self.rb_skill_key.get().strip()
        rb_attack_key = self.rb_attack_key.get().strip()
        rb_attack_start_delay_seconds = self._read_seconds(
            self.rb_attack_start_delay,
            float(self.settings.combo_slots["A"]["attack_start_delay_seconds"]),
            COMBO_ATTACK_START_DELAY_MIN_SECONDS,
            COMBO_ATTACK_START_DELAY_MAX_SECONDS,
        )
        rb_attack_hold_seconds = self._read_seconds(
            self.rb_attack_hold,
            float(self.settings.combo_slots["A"]["attack_hold_seconds"]),
            COMBO_ATTACK_HOLD_MIN_SECONDS,
            COMBO_ATTACK_HOLD_MAX_SECONDS,
        )
        rb_controller_button = normalize_controller_button_name(
            self.rb_controller_button.get(),
            self.settings.rb_controller_button,
        )
        rb_skill_delay_seconds = self._read_seconds(
            self.rb_skill_delay,
            self.settings.rb_skill_delay_seconds,
            0.0,
            10.0,
        )
        rb_jump_interval_seconds = self._read_seconds(
            self.rb_jump_interval,
            self.settings.rb_jump_interval_seconds,
            COMBO_JUMP_INTERVAL_MIN_SECONDS,
            COMBO_JUMP_INTERVAL_MAX_SECONDS,
        )
        lb_jump_key = self.lb_jump_key.get().strip()
        lb_skill_key = self.lb_skill_key.get().strip()
        lb_attack_key = self.lb_attack_key.get().strip()
        lb_attack_start_delay_seconds = self._read_seconds(
            self.lb_attack_start_delay,
            float(self.settings.combo_slots["B"]["attack_start_delay_seconds"]),
            COMBO_ATTACK_START_DELAY_MIN_SECONDS,
            COMBO_ATTACK_START_DELAY_MAX_SECONDS,
        )
        lb_attack_hold_seconds = self._read_seconds(
            self.lb_attack_hold,
            float(self.settings.combo_slots["B"]["attack_hold_seconds"]),
            COMBO_ATTACK_HOLD_MIN_SECONDS,
            COMBO_ATTACK_HOLD_MAX_SECONDS,
        )
        lb_controller_button = normalize_controller_button_name(
            self.lb_controller_button.get(),
            self.settings.lb_controller_button,
        )
        lb_skill_delay_seconds = self._read_seconds(
            self.lb_skill_delay,
            self.settings.lb_skill_delay_seconds,
            0.0,
            10.0,
        )
        lb_jump_interval_seconds = self._read_seconds(
            self.lb_jump_interval,
            lb_jump_interval_fallback,
            COMBO_JUMP_INTERVAL_MIN_SECONDS,
            COMBO_JUMP_INTERVAL_MAX_SECONDS,
        )

        hp_enabled = self.hp_enabled.get()
        mp_enabled = self.mp_enabled.get()
        ui_only_snapshot = getattr(self, "potion_enabled_ui_only_snapshot", None)
        if isinstance(ui_only_snapshot, tuple) and len(ui_only_snapshot) == 4:
            saved_hp_enabled, saved_mp_enabled, ui_hp_enabled, ui_mp_enabled = ui_only_snapshot
            if bool(hp_enabled) == ui_hp_enabled and bool(mp_enabled) == ui_mp_enabled:
                hp_enabled, mp_enabled = saved_hp_enabled, saved_mp_enabled
            else:
                self.potion_enabled_ui_only_snapshot = None
        self.settings.hp_enabled = hp_enabled
        self.settings.mp_enabled = mp_enabled
        self.settings.rb_enabled = rb_enabled
        self.settings.lb_enabled = lb_enabled
        self.settings.hp_threshold_percent = self.hp_threshold.get()
        self.settings.mp_threshold_percent = self.mp_threshold.get()
        self.settings.hp_key = self.hp_key.get().strip()
        self.settings.mp_key = self.mp_key.get().strip()
        self.settings.hp_cooldown_seconds = self._read_cooldown(self.hp_cooldown, self.settings.hp_cooldown_seconds)
        self.settings.mp_cooldown_seconds = self._read_cooldown(self.mp_cooldown, self.settings.mp_cooldown_seconds)
        self.settings.hp_continuous_enabled = self.hp_continuous_enabled.get()
        self.settings.mp_continuous_enabled = self.mp_continuous_enabled.get()
        self.settings.hp_continuous_stop_margin_percent = self._read_continuous_stop_margin(
            self.hp_continuous_stop_margin,
            self.settings.hp_continuous_stop_margin_percent,
        )
        self.settings.mp_continuous_stop_margin_percent = self._read_continuous_stop_margin(
            self.mp_continuous_stop_margin,
            self.settings.mp_continuous_stop_margin_percent,
        )
        self.settings.rb_jump_key = rb_jump_key
        self.settings.rb_skill_key = rb_skill_key
        self.settings.rb_controller_button = rb_controller_button
        self.rb_controller_button.set(self.settings.rb_controller_button)
        self.settings.rb_skill_delay_seconds = rb_skill_delay_seconds
        self.settings.rb_jump_interval_seconds = rb_jump_interval_seconds
        self.settings.lb_jump_key = lb_jump_key
        self.settings.lb_skill_key = lb_skill_key
        self.settings.lb_controller_button = lb_controller_button
        self.lb_controller_button.set(self.settings.lb_controller_button)
        self.settings.lb_skill_delay_seconds = lb_skill_delay_seconds
        self.settings.set_combo_slots(
            {
                "A": {
                    "enabled": rb_enabled,
                    "script_id": self._combo_script_id(self.combo_a_script.get(), COMBO_SCRIPT_REPEATING_JUMP_SKILL),
                    "trigger_button": rb_controller_button,
                    "jump_key": rb_jump_key,
                    "skill_key": rb_skill_key,
                    "attack_key": rb_attack_key,
                    "attack_start_delay_seconds": rb_attack_start_delay_seconds,
                    "attack_hold_seconds": rb_attack_hold_seconds,
                    "skill_delay_seconds": rb_skill_delay_seconds,
                    "jump_interval_seconds": rb_jump_interval_seconds,
                },
                "B": {
                    "enabled": lb_enabled,
                    "script_id": self._combo_script_id(self.combo_b_script.get(), COMBO_SCRIPT_SINGLE_JUMP_SKILL),
                    "trigger_button": lb_controller_button,
                    "jump_key": lb_jump_key,
                    "skill_key": lb_skill_key,
                    "attack_key": lb_attack_key,
                    "attack_start_delay_seconds": lb_attack_start_delay_seconds,
                    "attack_hold_seconds": lb_attack_hold_seconds,
                    "skill_delay_seconds": lb_skill_delay_seconds,
                    "jump_interval_seconds": lb_jump_interval_seconds,
                },
            }
        )
        self.rb_enabled.set(self.settings.rb_enabled)
        self.lb_enabled.set(self.settings.lb_enabled)
        self.rb_controller_button.set(self.settings.rb_controller_button)
        self.lb_controller_button.set(self.settings.lb_controller_button)
        self.rb_attack_key.set(str(self.settings.combo_slot("A")["attack_key"]))
        self.lb_attack_key.set(str(self.settings.combo_slot("B")["attack_key"]))
        self.rb_attack_start_delay.set(f"{float(self.settings.combo_slot('A')['attack_start_delay_seconds']):g}")
        self.lb_attack_start_delay.set(f"{float(self.settings.combo_slot('B')['attack_start_delay_seconds']):g}")
        self.rb_attack_hold.set(f"{float(self.settings.combo_slot('A')['attack_hold_seconds']):g}")
        self.lb_attack_hold.set(f"{float(self.settings.combo_slot('B')['attack_hold_seconds']):g}")
        self.rb_jump_interval.set(f"{self.settings.rb_jump_interval_seconds:g}")
        self.lb_jump_interval.set(f"{float(self.settings.combo_slot('B')['jump_interval_seconds']):g}")
        self.settings.exp_efficiency_enabled = self.exp_efficiency_enabled.get()
        self.settings.toggle_hotkey = self.toggle_hotkey.get().strip() or self.settings.toggle_hotkey
        self.settings.emergency_stop_hotkey = (
            self.emergency_stop_hotkey.get().strip() or self.settings.emergency_stop_hotkey
        )
        self.settings.experience_toggle_hotkey = (
            self.experience_toggle_hotkey.get().strip() or self.settings.experience_toggle_hotkey
        )
        self.settings.experience_reset_hotkey = (
            self.experience_reset_hotkey.get().strip() or self.settings.experience_reset_hotkey
        )
        self.settings.character_stat_hotkey = self.character_stat_hotkey.get().strip()
        self.settings.pickup_toggle_hotkey = self.pickup_toggle_hotkey.get().strip() or None
        self.settings.pickup_key = self.pickup_key.get().strip() or None
        minimap_toggle_var = getattr(self, "minimap_cruise_toggle_hotkey", None)
        if minimap_toggle_var is not None:
            self.settings.minimap_cruise_toggle_hotkey = minimap_toggle_var.get().strip() or None
        minimap_attack_var = getattr(self, "minimap_cruise_attack_key", None)
        if minimap_attack_var is not None:
            self.settings.minimap_cruise_attack_key = minimap_attack_var.get().strip() or "C"
        minimap_pre_skill_enabled = getattr(self, "minimap_cruise_pre_boundary_skill_enabled", None)
        if minimap_pre_skill_enabled is not None:
            self.settings.minimap_cruise_pre_boundary_skill_enabled = minimap_pre_skill_enabled.get()
        minimap_pre_skill_key = getattr(self, "minimap_cruise_pre_boundary_skill_key", None)
        if minimap_pre_skill_key is not None:
            self.settings.minimap_cruise_pre_boundary_skill_key = minimap_pre_skill_key.get().strip()
        minimap_pre_skill_distance = getattr(self, "minimap_cruise_pre_boundary_distance", None)
        if minimap_pre_skill_distance is not None:
            distance = self._read_int_text(
                minimap_pre_skill_distance,
                self.settings.minimap_cruise_pre_boundary_distance,
                MINIMAP_CRUISE_MIN_PRE_BOUNDARY_SKILL_DISTANCE,
                MINIMAP_CRUISE_MAX_PRE_BOUNDARY_SKILL_DISTANCE,
            )
            self.settings.minimap_cruise_pre_boundary_distance = distance
            minimap_pre_skill_distance.set(str(distance))
        minimap_stationary_skill_key = getattr(self, "minimap_cruise_stationary_skill_key", None)
        if minimap_stationary_skill_key is not None:
            self.settings.minimap_cruise_stationary_skill_key = minimap_stationary_skill_key.get().strip()
        minimap_stationary_min_forward_pixels = getattr(
            self,
            "minimap_cruise_stationary_min_forward_pixels",
            None,
        )
        if minimap_stationary_min_forward_pixels is not None:
            min_forward_pixels = self._read_int_text(
                minimap_stationary_min_forward_pixels,
                self.settings.minimap_cruise_stationary_min_forward_pixels,
                MINIMAP_CRUISE_MIN_STATIONARY_MIN_FORWARD_PIXELS,
                MINIMAP_CRUISE_MAX_STATIONARY_MIN_FORWARD_PIXELS,
            )
            self.settings.minimap_cruise_stationary_min_forward_pixels = min_forward_pixels
            minimap_stationary_min_forward_pixels.set(str(min_forward_pixels))
        minimap_lie_detector_alert_volume = getattr(self, "minimap_cruise_lie_detector_alert_volume", None)
        if minimap_lie_detector_alert_volume is not None:
            volume = self._read_int_text(
                minimap_lie_detector_alert_volume,
                self.settings.minimap_cruise_lie_detector_alert_volume_percent,
                MINIMAP_CRUISE_MIN_ALERT_VOLUME_PERCENT,
                MINIMAP_CRUISE_MAX_ALERT_VOLUME_PERCENT,
            )
            self.settings.minimap_cruise_lie_detector_alert_volume_percent = volume
            minimap_lie_detector_alert_volume.set(str(volume))
        periodic_enabled_vars = getattr(self, "minimap_cruise_periodic_key_enabled_vars", ())
        periodic_key_vars = getattr(self, "minimap_cruise_periodic_key_vars", ())
        periodic_interval_vars = getattr(self, "minimap_cruise_periodic_key_interval_vars", ())
        for index in range(min(len(periodic_enabled_vars), len(periodic_key_vars), len(periodic_interval_vars), 5)):
            slot = index + 1
            enabled = periodic_enabled_vars[index].get()
            key = periodic_key_vars[index].get().strip()
            interval_attr = f"minimap_cruise_periodic_key_{slot}_interval_seconds"
            interval = self._read_seconds(
                periodic_interval_vars[index],
                getattr(self.settings, interval_attr),
                MINIMAP_CRUISE_MIN_PERIODIC_KEY_INTERVAL_SECONDS,
                MINIMAP_CRUISE_MAX_PERIODIC_KEY_INTERVAL_SECONDS,
            )
            setattr(self.settings, f"minimap_cruise_periodic_key_{slot}_enabled", enabled)
            setattr(self.settings, f"minimap_cruise_periodic_key_{slot}", key)
            setattr(self.settings, interval_attr, interval)
            periodic_interval_vars[index].set(f"{interval:g}")
        minimap_error = validate_minimap_cruise_settings(self.settings, parse_vk_key)
        if minimap_error is not None:
            for name, value in previous_minimap_settings.items():
                setattr(self.settings, name, value)
            self.set_status(minimap_error)
        self.settings.console_collapsed = self.console_collapsed
        self.settings.combo_group_collapsed = self.combo_group_collapsed
        self.settings.minimap_cruise_group_collapsed = getattr(
            self,
            "minimap_cruise_group_collapsed",
            self.settings.minimap_cruise_group_collapsed,
        )
        self.settings.compact_experience_mode = self.compact_experience_mode
        self.settings.window_topmost = self.window_topmost

    def set_exp_efficiency_enabled(self, enabled: bool) -> None:
        self.exp_efficiency_enabled.set(enabled)
        self.settings.exp_efficiency_enabled = enabled

    def set_auto_drink_enabled(self, enabled: bool) -> None:
        self.auto_drink_enabled.set(enabled)

    def set_pickup_enabled(self, enabled: bool) -> None:
        self.pickup_enabled.set(enabled)

    def _toggle_auto_drink_enabled_from_checkbox(self) -> None:
        desired = bool(self.auto_drink_enabled.get())
        if self.auto_drink_toggle_handler is not None:
            result = self.auto_drink_toggle_handler(desired)
            if result is False:
                self.auto_drink_enabled.set(not desired)

    def _toggle_pickup_enabled_from_checkbox(self) -> None:
        desired = bool(self.pickup_enabled.get())
        if self.pickup_toggle_handler is not None:
            result = self.pickup_toggle_handler(desired)
            if result is False:
                self.pickup_enabled.set(not desired)

    def set_potion_enabled(self, hp_enabled: bool, mp_enabled: bool, *, update_settings: bool = True) -> None:
        if update_settings:
            self.potion_enabled_ui_only_snapshot = None
        else:
            self.potion_enabled_ui_only_snapshot = (
                bool(self.settings.hp_enabled),
                bool(self.settings.mp_enabled),
                bool(hp_enabled),
                bool(mp_enabled),
            )
        self.hp_enabled.set(hp_enabled)
        self.mp_enabled.set(mp_enabled)
        if not update_settings:
            return
        self.settings.hp_enabled = hp_enabled
        self.settings.mp_enabled = mp_enabled

    def _read_cooldown(self, var: tk.StringVar, fallback: float) -> float:
        return self._read_seconds(var, fallback, POTION_MIN_COOLDOWN_SECONDS, 60.0)

    def _read_continuous_stop_margin(self, var: tk.StringVar, fallback: float) -> float:
        return self._read_seconds(var, fallback, 0.0, POTION_CONTINUOUS_STOP_MARGIN_MAX_PERCENT)

    def _read_seconds(self, var: tk.StringVar, fallback: float, minimum: float, maximum: float) -> float:
        try:
            value = max(minimum, min(maximum, float(var.get())))
        except ValueError:
            value = fallback
        return value

    def _read_int_text(self, var: tk.StringVar, fallback: int, minimum: int, maximum: int) -> int:
        try:
            value = int(var.get())
        except ValueError:
            value = fallback
        return max(minimum, min(maximum, value))

    def _read_percent(self, value_var: tk.DoubleVar, text_var: tk.StringVar) -> None:
        text = text_var.get().strip()
        if not text:
            return
        try:
            value = max(1.0, min(100.0, float(text)))
        except ValueError:
            return
        value_var.set(value)

    def _set_text_if_changed(self, var: tk.StringVar, value: str) -> None:
        if var.get() != value:
            var.set(value)

    def set_current_percentages(self, hp_percent: float | None, mp_percent: float | None) -> None:
        self._set_text_if_changed(self.hp_current, "HP: --%" if hp_percent is None else f"HP: {hp_percent:.0f}%")
        self._set_text_if_changed(self.mp_current, "MP: --%" if mp_percent is None else f"MP: {mp_percent:.0f}%")

    def set_bar_detection_debug(self, hp_debug: str, mp_debug: str) -> None:
        self._set_text_if_changed(self.hp_detection_status, hp_debug)
        self._set_text_if_changed(self.mp_detection_status, mp_debug)

    def set_experience_snapshot(self, snapshot: ExperienceSnapshot) -> None:
        percent = "" if snapshot.current_percent is None else f" ({snapshot.current_percent:.2f}%)"
        ocr_success = format_ocr_success_rate(snapshot.ocr_success_count, snapshot.ocr_attempt_count)
        self._set_text_if_changed(
            self.exp_current_status,
            f"EXP：{format_exp(snapshot.current_exp)}{percent}    OCR：{ocr_success}",
        )
        self._set_text_if_changed(self.exp_rate_10m_status, f"10m：{format_exp_rate(snapshot.xp_per_10m)}")
        self._set_text_if_changed(self.exp_rate_1h_status, f"1h：{format_exp_rate(snapshot.xp_per_hour)}")
        self._set_text_if_changed(self.exp_10m_gain_status, f"EXP-10：{format_exp_10m_gain(snapshot.exp_10m_gain)}")
        self._set_text_if_changed(
            self.exp_eta_status,
            f"升級預估：{format_eta(snapshot.eta_seconds)}    時間：{format_duration(snapshot.elapsed_seconds)}",
        )
        sample_accept = format_ocr_success_rate(snapshot.sample_accept_count, snapshot.sample_attempt_count)
        confidence = format_rate_confidence(snapshot.rate_confidence)
        self._set_text_if_changed(self.exp_quality_status, f"樣本：{sample_accept}    信賴度：{confidence}")
        self._set_text_if_changed(self.exp_reader_status, f"狀態：{snapshot.status}")

    def set_status(self, message: str) -> None:
        self._set_text_if_changed(self.status, message)
        self._set_text_if_changed(self.runtime_status_message, f"狀態：{message or '--'}")

    def set_runtime_info(
        self,
        *,
        scripts_enabled: bool,
        target_active: bool,
        foreground_title: str,
        macro_status: str,
        held_keys: str,
        last_action: str,
    ) -> None:
        foreground_label = "楓星" if target_active else (foreground_title or "--")
        if len(foreground_label) > 24:
            foreground_label = foreground_label[:23] + "..."
        self._set_text_if_changed(self.runtime_script_status, f"自動喝水：{'啟用' if scripts_enabled else '暫停'}")
        self._set_text_if_changed(self.runtime_foreground_status, f"前景：{foreground_label}")

    def _create_auxiliary_window(
        self,
        *,
        fg_color: str,
        overrideredirect: bool = False,
    ) -> ctk.CTkToplevel:
        window = ctk.CTkToplevel(self.root, fg_color=fg_color)
        window.withdraw()
        try:
            window.transient(self.root)
        except tk.TclError:
            pass
        try:
            window.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        if overrideredirect:
            window.overrideredirect(True)
        window.attributes("-topmost", True)
        return window

    def _prepare_auxiliary_window_for_show(self, window: ctk.CTkToplevel) -> None:
        try:
            window.update_idletasks()
        except tk.TclError:
            return
        apply_background_toolwindow_style(window)

    def show_toggle_notice(self, message: str) -> None:
        if self.closed:
            return

        if self.toggle_notice_window is not None and self.toggle_notice_message == message:
            try:
                if self.toggle_notice_after_id is not None:
                    self.root.after_cancel(self.toggle_notice_after_id)
                self.toggle_notice_after_id = self.root.after(1300, self._destroy_toggle_notice)
                self.toggle_notice_window.lift()
                return
            except tk.TclError:
                self.toggle_notice_after_id = None
                self.toggle_notice_window = None
                self.toggle_notice_message = ""

        self._destroy_toggle_notice()
        target_rect = self._foreground_client_rect()
        try:
            notice = self._create_auxiliary_window(fg_color=NOTICE_BG, overrideredirect=True)
            self.toggle_notice_window = notice
            self.toggle_notice_message = message
            try:
                notice.attributes("-alpha", 0.92)
            except tk.TclError:
                pass
            notice.configure(fg_color=NOTICE_BG)

            ctk.CTkLabel(
                notice,
                text=message,
                fg_color=NOTICE_BG,
                text_color=NOTICE_TEXT,
                font=(FONT_FAMILY, 18, "bold"),
            ).grid(row=0, column=0, sticky="nsew", padx=24, pady=10)

            notice.update_idletasks()
            self._prepare_auxiliary_window_for_show(notice)
            x, y = self._toggle_notice_position(notice.winfo_width(), notice.winfo_height(), target_rect)
            notice.geometry(f"+{x}+{y}")
            notice.deiconify()
            notice.lift()
            self.toggle_notice_after_id = self.root.after(1300, self._destroy_toggle_notice)
        except tk.TclError as exc:
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"熱鍵提示顯示失敗，已略過：{exc}", file=sys.__stdout__)
                self.last_gui_error_at = now

    def _toggle_notice_position(
        self,
        width: int,
        height: int,
        rect: tuple[int, int, int, int] | None,
    ) -> tuple[int, int]:
        if rect is None:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            return self._clamp_notice_position(
                (screen_width - width) // 2,
                int(screen_height * TOGGLE_NOTICE_VERTICAL_RATIO) - height // 2,
                width,
                height,
                (0, 0, screen_width, screen_height),
            )

        left, top, right, bottom = rect
        target_width = max(1, right - left)
        target_height = max(1, bottom - top)
        return self._clamp_notice_position(
            left + (target_width - width) // 2,
            top + int(target_height * TOGGLE_NOTICE_VERTICAL_RATIO) - height // 2,
            width,
            height,
            rect,
        )

    def _clamp_notice_position(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        bounds: tuple[int, int, int, int],
    ) -> tuple[int, int]:
        left, top, right, bottom = bounds
        min_x = left + TOGGLE_NOTICE_EDGE_PADDING
        min_y = top + TOGGLE_NOTICE_EDGE_PADDING
        max_x = max(min_x, right - width - TOGGLE_NOTICE_EDGE_PADDING)
        max_y = max(min_y, bottom - height - TOGGLE_NOTICE_EDGE_PADDING)
        return (
            max(min_x, min(max_x, x)),
            max(min_y, min(max_y, y)),
        )

    def _foreground_client_rect(self) -> tuple[int, int, int, int] | None:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None

        top_left = Point(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
            return None

        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None

        return (
            top_left.x,
            top_left.y,
            top_left.x + width,
            top_left.y + height,
        )

    def _destroy_toggle_notice(self) -> None:
        if self.toggle_notice_after_id is not None:
            try:
                self.root.after_cancel(self.toggle_notice_after_id)
            except tk.TclError:
                pass
            self.toggle_notice_after_id = None

        if self.toggle_notice_window is None:
            self.toggle_notice_message = ""
            return

        try:
            self.toggle_notice_window.destroy()
        except tk.TclError:
            pass
        self.toggle_notice_window = None
        self.toggle_notice_message = ""

    def append_console(self, text: str) -> None:
        if self.closed or not text:
            return
        self.console_pending_text.append(text)
        self.console_pending_char_count = int(getattr(self, "console_pending_char_count", 0)) + len(text)
        if self.console_pending_char_count > MAX_CONSOLE_CHARS:
            buffered = "".join(self.console_pending_text)[-MAX_CONSOLE_CHARS:]
            self.console_pending_text[:] = [buffered]
            self.console_pending_char_count = len(buffered)
        if getattr(self, "console", None) is None or getattr(self, "active_page", "Console") != "Console":
            return
        if self.console_flush_after_id is not None:
            return
        try:
            self.console_flush_after_id = self.root.after(CONSOLE_FLUSH_DELAY_MS, self._flush_console_buffer)
        except tk.TclError:
            self.console_flush_after_id = None
            self._flush_console_buffer()

    def _flush_console_buffer(self) -> None:
        self.console_flush_after_id = None
        if self.closed or getattr(self, "console", None) is None or not self.console_pending_text:
            return
        text = "".join(self.console_pending_text)
        self.console_pending_text.clear()
        self.console_pending_char_count = 0
        try:
            self.console.configure(state="normal")
            self.console.insert("end", text)
            self._trim_console()
            self.console.see("end")
            self.console.configure(state="disabled")
        except tk.TclError as exc:
            if self.closed:
                return
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"GUI console 更新暫時失敗，已略過：{exc}", file=self.original if hasattr(self, "original") else sys.__stdout__)
                self.last_gui_error_at = now

    def clear_console(self) -> None:
        if self.closed:
            return
        self.console_pending_text.clear()
        self.console_pending_char_count = 0
        if self.console_flush_after_id is not None:
            try:
                self.root.after_cancel(self.console_flush_after_id)
            except tk.TclError:
                pass
            self.console_flush_after_id = None
        if getattr(self, "console", None) is None:
            return
        try:
            self.console.configure(state="normal")
            self.console.delete("1.0", "end")
            self.console.configure(state="disabled")
        except tk.TclError as exc:
            if self.closed:
                return
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"GUI console 清除暫時失敗，已略過：{exc}", file=sys.__stdout__)
                self.last_gui_error_at = now

    def _trim_console(self) -> None:
        line_count = int(self.console.index("end-1c").split(".")[0])
        if line_count > MAX_CONSOLE_LINES:
            self.console.delete("1.0", f"{line_count - MAX_CONSOLE_LINES + 1}.0")
        overflow_start = self.console.index(f"end-{MAX_CONSOLE_CHARS + 1}c")
        if overflow_start != "1.0":
            self.console.delete("1.0", overflow_start)
