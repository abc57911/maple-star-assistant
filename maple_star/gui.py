from __future__ import annotations

import ctypes
import json
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from .constants import MAX_CONSOLE_LINES
from .key_capture import DETECTABLE_KEY_VKS, event_to_hotkey, pressed_detectable_vks, vk_to_key_name
from .settings import (
    SETTINGS_PATH,
    AutoPotionSettings,
    CONTROLLER_BUTTON_CHOICES,
    copy_setting_values,
    load_settings,
    normalize_controller_button_name,
    normalize_profile_name,
    save_settings,
)
from .win_input import Point, parse_vk_key, user32

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
        self.gui.append_console(text)
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass


class AutoPotionSettingsGui:
    def __init__(self, settings: AutoPotionSettings) -> None:
        self.settings = settings
        self.closed = False
        self.root = tk.Tk()
        self.root.title("自動喝水設定")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.detecting_key_target: tk.StringVar | None = None
        self.detecting_key_label = ""
        self.key_detection_window: tk.Toplevel | None = None
        self.toggle_notice_window: tk.Toplevel | None = None
        self.toggle_notice_after_id: str | None = None
        self.bar_preview_provider: Callable[[], dict[str, dict[str, object]]] | None = None
        self.bar_preview_labels: dict[str, ttk.Label] = {}
        self.bar_preview_images: list[tk.PhotoImage] = []
        self.bar_preview_has_snapshot = False
        self.detecting_vk_down: set[int] = set()
        self.last_gui_error_at = -999.0

        self.active_profile = tk.StringVar(value=settings.active_profile)
        self.hp_enabled = tk.BooleanVar(value=settings.hp_enabled)
        self.mp_enabled = tk.BooleanVar(value=settings.mp_enabled)
        self.rb_enabled = tk.BooleanVar(value=settings.rb_enabled)
        self.hp_threshold = tk.DoubleVar(value=settings.hp_threshold_percent)
        self.mp_threshold = tk.DoubleVar(value=settings.mp_threshold_percent)
        self.hp_threshold_text = tk.StringVar(value=f"{settings.hp_threshold_percent:.0f}")
        self.mp_threshold_text = tk.StringVar(value=f"{settings.mp_threshold_percent:.0f}")
        self.hp_key = tk.StringVar(value=settings.hp_key)
        self.mp_key = tk.StringVar(value=settings.mp_key)
        self.hp_cooldown = tk.StringVar(value=f"{settings.hp_cooldown_seconds:g}")
        self.mp_cooldown = tk.StringVar(value=f"{settings.mp_cooldown_seconds:g}")
        self.rb_jump_key = tk.StringVar(value=settings.rb_jump_key)
        self.rb_skill_key = tk.StringVar(value=settings.rb_skill_key)
        self.rb_controller_button = tk.StringVar(value=settings.rb_controller_button)
        self.rb_skill_delay = tk.StringVar(value=f"{settings.rb_skill_delay_seconds:g}")
        self.rb_jump_interval = tk.StringVar(value=f"{settings.rb_jump_interval_seconds:g}")
        self.lb_enabled = tk.BooleanVar(value=settings.lb_enabled)
        self.lb_jump_key = tk.StringVar(value=settings.lb_jump_key)
        self.lb_skill_key = tk.StringVar(value=settings.lb_skill_key)
        self.lb_controller_button = tk.StringVar(value=settings.lb_controller_button)
        self.lb_skill_delay = tk.StringVar(value=f"{settings.lb_skill_delay_seconds:g}")
        self.hp_current = tk.StringVar(value="HP: --%")
        self.mp_current = tk.StringVar(value="MP: --%")
        self.status = tk.StringVar(value="只在楓星為前景視窗時生效")
        self.runtime_script_status = tk.StringVar(value="腳本：啟用")
        self.runtime_foreground_status = tk.StringVar(value="前景：--")
        self.runtime_macro_status = tk.StringVar(value="巨集：--")
        self.runtime_held_keys_status = tk.StringVar(value="按住：--")
        self.runtime_last_action_status = tk.StringVar(value="最近動作：啟動")
        self.hp_detection_status = tk.StringVar(value="HP: --")
        self.mp_detection_status = tk.StringVar(value="MP: --")

        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(8, weight=1)

        profile_frame = ttk.Frame(frame)
        profile_frame.grid(row=0, column=0, sticky="ew")
        profile_frame.columnconfigure(1, weight=1)
        ttk.Label(profile_frame, text="設定檔").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        self.profile_select = ttk.Combobox(
            profile_frame,
            textvariable=self.active_profile,
            values=self.settings.profile_names(),
            state="readonly",
            width=18,
        )
        self.profile_select.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
        self.profile_select.bind("<<ComboboxSelected>>", self._switch_profile)
        ttk.Button(profile_frame, text="新增", command=self.create_profile).grid(row=0, column=2, sticky="w", padx=(0, 4), pady=(0, 4))
        ttk.Button(profile_frame, text="刪除", command=self.delete_profile).grid(row=0, column=3, sticky="w", padx=(0, 4), pady=(0, 4))
        ttk.Button(profile_frame, text="匯入", command=self.import_settings).grid(row=0, column=4, sticky="w", padx=(0, 4), pady=(0, 4))
        ttk.Button(profile_frame, text="匯出", command=self.export_settings).grid(row=0, column=5, sticky="w", pady=(0, 4))

        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        self._build_row(controls, 0, "紅水", self.hp_enabled, self.hp_threshold, self.hp_threshold_text, self.hp_key, self.hp_cooldown, self.hp_current)
        self._build_row(controls, 1, "藍水", self.mp_enabled, self.mp_threshold, self.mp_threshold_text, self.mp_key, self.mp_cooldown, self.mp_current)

        detection_frame = ttk.LabelFrame(frame, text="偵測診斷")
        detection_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        detection_frame.columnconfigure(0, weight=1)
        ttk.Label(detection_frame, textvariable=self.hp_detection_status).grid(row=0, column=0, sticky="w", padx=8, pady=(4, 2))
        self.bar_preview_labels["hp"] = ttk.Label(detection_frame, text="尚未刷新預覽")
        self.bar_preview_labels["hp"].grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Label(detection_frame, textvariable=self.mp_detection_status).grid(row=2, column=0, sticky="w", padx=8, pady=(2, 2))
        self.bar_preview_labels["mp"] = ttk.Label(detection_frame, text="尚未刷新預覽")
        self.bar_preview_labels["mp"].grid(row=3, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Button(detection_frame, text="刷新預覽", command=self.refresh_bar_preview).grid(row=0, column=1, rowspan=4, sticky="ne", padx=8, pady=4)

        rb_frame = ttk.LabelFrame(frame, text="RB function")
        rb_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for column in range(13):
            rb_frame.columnconfigure(column, weight=0)
        rb_frame.columnconfigure(12, weight=1)
        ttk.Checkbutton(rb_frame, text="啟用", variable=self.rb_enabled).grid(row=0, column=0, sticky="w", padx=(8, 12), pady=6)
        self._build_controller_button_select(rb_frame, 0, 1, "觸發", self.rb_controller_button)
        self._build_key_entry(rb_frame, 0, 3, "跳躍鍵", self.rb_jump_key)
        self._build_key_entry(rb_frame, 0, 5, "技能鍵", self.rb_skill_key)
        ttk.Label(rb_frame, text="技能延遲").grid(row=0, column=7, sticky="w", padx=(12, 4), pady=6)
        self._build_seconds_stepper(rb_frame, 0, 8, self.rb_skill_delay, 0.0, 10.0)
        ttk.Label(rb_frame, text="跳躍間隔").grid(row=1, column=7, sticky="w", padx=(12, 4), pady=(0, 8))
        self._build_seconds_stepper(rb_frame, 1, 8, self.rb_jump_interval, 0.05, 10.0, pady=(0, 8))

        lb_frame = ttk.LabelFrame(frame, text="LB function")
        lb_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        for column in range(13):
            lb_frame.columnconfigure(column, weight=0)
        lb_frame.columnconfigure(12, weight=1)
        ttk.Checkbutton(lb_frame, text="啟用", variable=self.lb_enabled).grid(row=0, column=0, sticky="w", padx=(8, 12), pady=6)
        self._build_controller_button_select(lb_frame, 0, 1, "觸發", self.lb_controller_button)
        self._build_key_entry(lb_frame, 0, 3, "跳躍鍵", self.lb_jump_key)
        self._build_key_entry(lb_frame, 0, 5, "技能鍵", self.lb_skill_key)
        ttk.Label(lb_frame, text="技能延遲").grid(row=0, column=7, sticky="w", padx=(12, 4), pady=6)
        self._build_seconds_stepper(lb_frame, 0, 8, self.lb_skill_delay, 0.0, 10.0)

        ttk.Label(frame, text="F11：暫停/恢復所有腳本功能；F12：硬停止並釋放按鍵").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Label(frame, textvariable=self.status).grid(row=6, column=0, sticky="w", pady=(2, 4))

        runtime_frame = ttk.Frame(frame)
        runtime_frame.grid(row=7, column=0, sticky="ew", pady=(0, 6))
        for column in range(5):
            runtime_frame.columnconfigure(column, weight=1)
        ttk.Label(runtime_frame, textvariable=self.runtime_script_status).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(runtime_frame, textvariable=self.runtime_foreground_status).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Label(runtime_frame, textvariable=self.runtime_macro_status).grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Label(runtime_frame, textvariable=self.runtime_held_keys_status).grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Label(runtime_frame, textvariable=self.runtime_last_action_status).grid(row=0, column=4, sticky="w")

        console_frame = ttk.LabelFrame(frame, text="Console")
        console_frame.grid(row=8, column=0, sticky="nsew")
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)
        self.console = tk.Text(console_frame, height=10, width=92, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _build_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        enabled_var: tk.BooleanVar,
        threshold_var: tk.DoubleVar,
        threshold_text: tk.StringVar,
        key_var: tk.StringVar,
        cooldown_var: tk.StringVar,
        current_var: tk.StringVar,
    ) -> None:
        ttk.Checkbutton(parent, text=label, variable=enabled_var).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        scale = ttk.Scale(
            parent,
            from_=1,
            to=100,
            orient="horizontal",
            variable=threshold_var,
            command=lambda value, text=threshold_text: text.set(f"{float(value):.0f}"),
            length=160,
        )
        scale.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, width=5, textvariable=threshold_text)
        entry.grid(row=row, column=2, sticky="w", padx=(0, 4), pady=4)
        ttk.Label(parent, text="%").grid(row=row, column=3, sticky="w", padx=(0, 10), pady=4)
        key_entry = ttk.Entry(parent, width=10, textvariable=key_var)
        key_entry.grid(row=row, column=4, sticky="w", padx=(0, 8), pady=4)
        key_entry.bind("<Button-1>", lambda _event, var=key_var, name=label: self.start_key_detection(var, name))
        ttk.Entry(parent, width=6, textvariable=cooldown_var).grid(row=row, column=5, sticky="w", padx=(0, 4), pady=4)
        ttk.Label(parent, text="秒").grid(row=row, column=6, sticky="w", pady=4)
        ttk.Label(parent, textvariable=current_var, width=9).grid(row=row, column=7, sticky="e", padx=(12, 0), pady=4)

        entry.bind("<Return>", lambda _event, var=threshold_var, text=threshold_text: self._apply_percent_text(var, text))
        entry.bind("<FocusOut>", lambda _event, var=threshold_var, text=threshold_text: self._apply_percent_text(var, text))

    def _build_key_entry(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        key_var: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 4), pady=6)
        key_entry = ttk.Entry(parent, width=9, textvariable=key_var)
        key_entry.grid(row=row, column=column + 1, sticky="w", padx=(0, 8), pady=6)
        key_entry.bind("<Button-1>", lambda _event, var=key_var, name=label: self.start_key_detection(var, name))

    def _build_controller_button_select(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        button_var: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 4), pady=6)
        button_select = ttk.Combobox(
            parent,
            width=9,
            textvariable=button_var,
            values=CONTROLLER_BUTTON_CHOICES,
            state="readonly",
        )
        button_select.grid(row=row, column=column + 1, sticky="w", padx=(0, 8), pady=6)

    def _build_seconds_stepper(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        value_var: tk.StringVar,
        minimum: float,
        maximum: float,
        pady: int | tuple[int, int] = 6,
    ) -> None:
        ttk.Entry(parent, width=6, textvariable=value_var).grid(row=row, column=column, sticky="w", padx=(0, 2), pady=pady)
        ttk.Label(parent, text="秒").grid(row=row, column=column + 1, sticky="w", padx=(0, 4), pady=pady)
        ttk.Button(
            parent,
            text="-",
            width=2,
            command=lambda: self._step_seconds(value_var, -0.01, minimum, maximum),
        ).grid(row=row, column=column + 2, sticky="w", padx=(0, 2), pady=pady)
        ttk.Button(
            parent,
            text="+",
            width=2,
            command=lambda: self._step_seconds(value_var, 0.01, minimum, maximum),
        ).grid(row=row, column=column + 3, sticky="w", padx=(0, 4), pady=pady)

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
        self.cancel_key_detection()
        self._destroy_toggle_notice()
        self.closed = True
        self.root.destroy()

    def set_bar_preview_provider(self, provider: Callable[[], dict[str, dict[str, object]]]) -> None:
        self.bar_preview_provider = provider

    def refresh_bar_preview_once(self) -> None:
        if self.bar_preview_has_snapshot:
            return
        self.refresh_bar_preview()

    def refresh_bar_preview(self) -> None:
        if self.bar_preview_provider is None:
            self.set_status("尚未連接偵測預覽來源")
            return
        try:
            previews = self.bar_preview_provider()
        except Exception as exc:
            self.set_status(f"偵測預覽失敗：{exc}")
            return

        self.bar_preview_images = []
        has_image = False
        for bar_type in ("hp", "mp"):
            preview = previews.get(bar_type, {})
            image_data = preview.get("image")
            if isinstance(image_data, bytes):
                image = tk.PhotoImage(data=image_data, format="PPM")
                self.bar_preview_images.append(image)
                self.bar_preview_labels[bar_type].configure(image=image, text="")
                has_image = True
            else:
                error = str(preview.get("error") or "尚無預覽圖片")
                self.bar_preview_labels[bar_type].configure(image="", text=error)

        if has_image:
            self.bar_preview_has_snapshot = True

    def _refresh_profile_select(self) -> None:
        self.profile_select.configure(values=self.settings.profile_names())
        self.active_profile.set(self.settings.active_profile)

    def _sync_vars_from_settings(self) -> None:
        self.active_profile.set(self.settings.active_profile)
        self.hp_enabled.set(self.settings.hp_enabled)
        self.mp_enabled.set(self.settings.mp_enabled)
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
        self.rb_jump_key.set(self.settings.rb_jump_key)
        self.rb_skill_key.set(self.settings.rb_skill_key)
        self.rb_controller_button.set(self.settings.rb_controller_button)
        self.rb_skill_delay.set(f"{self.settings.rb_skill_delay_seconds:g}")
        self.rb_jump_interval.set(f"{self.settings.rb_jump_interval_seconds:g}")
        self.lb_jump_key.set(self.settings.lb_jump_key)
        self.lb_skill_key.set(self.settings.lb_skill_key)
        self.lb_controller_button.set(self.settings.lb_controller_button)
        self.lb_skill_delay.set(f"{self.settings.lb_skill_delay_seconds:g}")
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

    def start_key_detection(self, target: tk.StringVar, label: str) -> str:
        self.cancel_key_detection()
        self.detecting_key_target = target
        self.detecting_key_label = label
        self.detecting_vk_down = pressed_detectable_vks()
        self.set_status(f"請按下要設定為 {label} 的按鍵")
        self.key_detection_window = tk.Toplevel(self.root)
        self.key_detection_window.title("快捷鍵偵測")
        self.key_detection_window.resizable(False, False)
        self.key_detection_window.transient(self.root)
        self.key_detection_window.attributes("-topmost", True)
        self.key_detection_window.protocol("WM_DELETE_WINDOW", self.cancel_key_detection)
        ttk.Label(
            self.key_detection_window,
            text=f"請按下要設定為 {label} 的按鍵",
            padding=16,
        ).grid(row=0, column=0, sticky="nsew")
        self.key_detection_window.update_idletasks()
        x = self.root.winfo_rootx() + 80
        y = self.root.winfo_rooty() + 80
        self.key_detection_window.geometry(f"+{x}+{y}")
        self.key_detection_window.focus_force()
        self.root.bind_all("<KeyPress>", self._capture_keypress)
        return "break"

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
        self.detecting_key_target.set(hotkey)
        self.set_status(f"{self.detecting_key_label} 快捷鍵已設定為 {hotkey}")
        self.cancel_key_detection(keep_status=True)

    def cancel_key_detection(self, keep_status: bool = False) -> None:
        self.root.unbind_all("<KeyPress>")
        self.detecting_key_target = None
        self.detecting_key_label = ""
        self.detecting_vk_down = set()
        if self.key_detection_window is not None:
            try:
                self.key_detection_window.destroy()
            except tk.TclError:
                pass
            self.key_detection_window = None
        if not keep_status and not self.closed:
            self.set_status("只在楓星為前景視窗時生效")

    def pump(self) -> bool:
        if self.closed:
            return False
        try:
            self.root.update_idletasks()
            self.root.update()
        except tk.TclError as exc:
            if self.closed:
                return False
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"GUI 更新暫時失敗，已略過：{exc}")
                self.last_gui_error_at = now
            return True

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
        self._read_percent(self.hp_threshold, self.hp_threshold_text)
        self._read_percent(self.mp_threshold, self.mp_threshold_text)
        self.settings.hp_enabled = self.hp_enabled.get()
        self.settings.mp_enabled = self.mp_enabled.get()
        self.settings.rb_enabled = self.rb_enabled.get()
        self.settings.lb_enabled = self.lb_enabled.get()
        self.settings.hp_threshold_percent = self.hp_threshold.get()
        self.settings.mp_threshold_percent = self.mp_threshold.get()
        self.settings.hp_key = self.hp_key.get().strip()
        self.settings.mp_key = self.mp_key.get().strip()
        self.settings.hp_cooldown_seconds = self._read_cooldown(self.hp_cooldown, self.settings.hp_cooldown_seconds)
        self.settings.mp_cooldown_seconds = self._read_cooldown(self.mp_cooldown, self.settings.mp_cooldown_seconds)
        self.settings.rb_jump_key = self.rb_jump_key.get().strip()
        self.settings.rb_skill_key = self.rb_skill_key.get().strip()
        self.settings.rb_controller_button = normalize_controller_button_name(
            self.rb_controller_button.get(),
            self.settings.rb_controller_button,
        )
        self.rb_controller_button.set(self.settings.rb_controller_button)
        self.settings.rb_skill_delay_seconds = self._read_seconds(
            self.rb_skill_delay,
            self.settings.rb_skill_delay_seconds,
            0.0,
            10.0,
        )
        self.settings.rb_jump_interval_seconds = self._read_seconds(
            self.rb_jump_interval,
            self.settings.rb_jump_interval_seconds,
            0.05,
            10.0,
        )
        self.settings.lb_jump_key = self.lb_jump_key.get().strip()
        self.settings.lb_skill_key = self.lb_skill_key.get().strip()
        self.settings.lb_controller_button = normalize_controller_button_name(
            self.lb_controller_button.get(),
            self.settings.lb_controller_button,
        )
        self.lb_controller_button.set(self.settings.lb_controller_button)
        self.settings.lb_skill_delay_seconds = self._read_seconds(
            self.lb_skill_delay,
            self.settings.lb_skill_delay_seconds,
            0.0,
            10.0,
        )

    def _read_cooldown(self, var: tk.StringVar, fallback: float) -> float:
        return self._read_seconds(var, fallback, 0.05, 60.0)

    def _read_seconds(self, var: tk.StringVar, fallback: float, minimum: float, maximum: float) -> float:
        try:
            value = max(minimum, min(maximum, float(var.get())))
        except ValueError:
            value = fallback
        return value

    def _read_percent(self, value_var: tk.DoubleVar, text_var: tk.StringVar) -> None:
        text = text_var.get().strip()
        if not text:
            return
        try:
            value = max(1.0, min(100.0, float(text)))
        except ValueError:
            return
        value_var.set(value)

    def set_current_percentages(self, hp_percent: float | None, mp_percent: float | None) -> None:
        self.hp_current.set("HP: --%" if hp_percent is None else f"HP: {hp_percent:.0f}%")
        self.mp_current.set("MP: --%" if mp_percent is None else f"MP: {mp_percent:.0f}%")

    def set_bar_detection_debug(self, hp_debug: str, mp_debug: str) -> None:
        self.hp_detection_status.set(hp_debug)
        self.mp_detection_status.set(mp_debug)

    def set_status(self, message: str) -> None:
        self.status.set(message)

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
        self.runtime_script_status.set(f"腳本：{'啟用' if scripts_enabled else '暫停'}")
        foreground_label = "楓星" if target_active else (foreground_title or "--")
        if len(foreground_label) > 24:
            foreground_label = foreground_label[:23] + "..."
        self.runtime_foreground_status.set(f"前景：{foreground_label}")
        self.runtime_macro_status.set(f"巨集：{macro_status or '--'}")
        self.runtime_held_keys_status.set(f"按住：{held_keys or '--'}")
        self.runtime_last_action_status.set(f"最近動作：{last_action or '--'}")

    def show_toggle_notice(self, message: str) -> None:
        if self.closed:
            return

        self._destroy_toggle_notice()
        target_rect = self._foreground_client_rect()
        try:
            notice = tk.Toplevel(self.root)
            self.toggle_notice_window = notice
            notice.withdraw()
            notice.overrideredirect(True)
            notice.attributes("-topmost", True)
            try:
                notice.attributes("-alpha", 0.92)
            except tk.TclError:
                pass
            notice.configure(bg="#111111")

            tk.Label(
                notice,
                text=message,
                bg="#111111",
                fg="#ffffff",
                padx=24,
                pady=10,
                font=("Microsoft JhengHei UI", 18, "bold"),
            ).grid(row=0, column=0, sticky="nsew")

            notice.update_idletasks()
            x, y = self._toggle_notice_position(notice.winfo_width(), notice.winfo_height(), target_rect)
            notice.geometry(f"+{x}+{y}")
            notice.deiconify()
            notice.lift()
            self.toggle_notice_after_id = self.root.after(1300, self._destroy_toggle_notice)
        except tk.TclError as exc:
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"F11 提示顯示失敗，已略過：{exc}", file=sys.__stdout__)
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
            return (
                max(0, (screen_width - width) // 2),
                max(0, int(screen_height * 0.12) - height // 2),
            )

        left, top, right, bottom = rect
        target_width = max(1, right - left)
        target_height = max(1, bottom - top)
        return (
            left + max(0, (target_width - width) // 2),
            top + max(0, int(target_height * 0.10) - height // 2),
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
            return

        try:
            self.toggle_notice_window.destroy()
        except tk.TclError:
            pass
        self.toggle_notice_window = None

    def append_console(self, text: str) -> None:
        if self.closed or not text:
            return
        try:
            self.console.configure(state="normal")
            self.console.insert("end", text)
            line_count = int(self.console.index("end-1c").split(".")[0])
            if line_count > MAX_CONSOLE_LINES:
                self.console.delete("1.0", f"{line_count - MAX_CONSOLE_LINES}.0")
            self.console.see("end")
            self.console.configure(state="disabled")
        except tk.TclError as exc:
            if self.closed:
                return
            now = time.monotonic()
            if now - self.last_gui_error_at >= 2.0:
                print(f"GUI console 更新暫時失敗，已略過：{exc}", file=self.original if hasattr(self, "original") else sys.__stdout__)
                self.last_gui_error_at = now
