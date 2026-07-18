from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QThreadPool, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from maple_star.adapters.debug_logging import write_debug_text
from maple_star.app.application import ensure_application
from maple_star.models.settings import (
    SETTINGS_PATH,
    copy_setting_values,
    load_settings,
    normalize_profile_name,
    save_settings,
)

from .main_window import MainWindow
from .bindings import HotkeyEdit
from .labels import runtime_value
from .jobs import CallableJob
from .notices import ToggleNotice
from .models.console_model import BoundedConsoleBuffer
from .pages.dashboard import DashboardPage
from .pages.diagnostics import DiagnosticsPage
from .pages.experience import ExperiencePage


class GuiConsoleWriter:
    def __init__(self, gui: "AutoPotionSettingsGui", original: object | None = None) -> None:
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


class AutoPotionSettingsGui(MainWindow):
    def __init__(self, settings) -> None:
        self.application = ensure_application([])
        self.settings = settings
        self._bar_preview_provider: Callable[[bool], dict[str, dict[str, object]]] | None = None
        self.bar_preview_provider = None
        self.bar_preview_images: list[object] = []
        self.bar_preview_has_snapshot = False
        self._experience_reset_handler: Callable[[], bool | None] | None = None
        self._auto_drink_toggle_handler: Callable[[bool], bool | None] | None = None
        self._pickup_toggle_handler: Callable[[bool], bool | None] | None = None
        self._key_detection_finished = False
        self._key_detection_until = 0.0
        self._key_detection_release_vks: set[int] = set()
        self._preview_job_active = False
        self._preview_job: CallableJob | None = None
        self._toggle_notice: ToggleNotice | None = None
        self._latest_bar_detection_debug: tuple[str, str] = ("", "")
        self._console_buffer = BoundedConsoleBuffer(capacity=1000)
        super().__init__(settings, settings_changed=self._setting_changed)
        self.dashboard.auto_drink_toggle.toggled.connect(self._request_auto_drink_toggle)
        self.dashboard.pickup_toggle.toggled.connect(self._request_pickup_toggle)
        self.experience.reset_experience.clicked.connect(self.reset_experience_statistics)
        self.pages["自動喝水"].refresh_preview.clicked.connect(
            lambda: self._refresh_bar_preview(make_target_topmost=True)
        )
        self._build_settings_menu()
        self._console_flush_timer = QTimer(self)
        self._console_flush_timer.timeout.connect(self._flush_console)
        self._console_flush_timer.start(50)
        for page in self.pages.values():
            for binding in getattr(page, "bindings", {}).values():
                if isinstance(binding.widget, HotkeyEdit):
                    binding.widget.captured.connect(self._hotkey_captured)

    @property
    def dashboard(self) -> DashboardPage:
        return self.pages["監控"]

    @property
    def diagnostics(self) -> DiagnosticsPage:
        return self.pages["診斷"]

    @property
    def experience(self) -> ExperiencePage:
        return self.pages["經驗計算"]

    def _setting_changed(self, name: str, value: object) -> None:
        if name in {
            "minimap_cruise_left_x", "minimap_cruise_right_x", "minimap_cruise_detect_y",
            "full_panel_window_x", "full_panel_window_y",
            "compact_experience_window_x", "compact_experience_window_y",
        }:
            text = str(value).strip()
            value = int(text) if text else None
        else:
            current = getattr(self.settings, name, None)
            try:
                if isinstance(current, bool):
                    value = bool(value)
                elif isinstance(current, int):
                    value = int(value)
                elif isinstance(current, float):
                    value = float(value)
                elif isinstance(current, str):
                    value = str(value).strip()
            except (TypeError, ValueError):
                self.set_status(f"設定值格式錯誤：{name}")
                return
        setattr(self.settings, name, value)

    def _build_settings_menu(self) -> None:
        profile_menu = self.menuBar().addMenu("設定檔")
        for label, callback in (
            ("新增", self.create_profile),
            ("刪除目前設定檔", self.delete_profile),
            ("匯入", self.import_settings),
            ("匯出", self.export_settings),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            profile_menu.addAction(action)

    def set_auto_drink_toggle_handler(self, handler: Callable[[bool], bool | None]) -> None:
        self._auto_drink_toggle_handler = handler

    def set_pickup_toggle_handler(self, handler: Callable[[bool], bool | None]) -> None:
        self._pickup_toggle_handler = handler

    def _request_auto_drink_toggle(self, enabled: bool) -> None:
        if self._auto_drink_toggle_handler is not None and self._auto_drink_toggle_handler(enabled) is False:
            self.set_auto_drink_enabled(not enabled)

    def _request_pickup_toggle(self, enabled: bool) -> None:
        if self._pickup_toggle_handler is not None and self._pickup_toggle_handler(enabled) is False:
            self.set_pickup_enabled(not enabled)

    def set_auto_drink_enabled(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self.dashboard.auto_drink_toggle)
        self.dashboard.auto_drink_toggle.setChecked(bool(enabled))
        del blocker

    def set_pickup_enabled(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self.dashboard.pickup_toggle)
        self.dashboard.pickup_toggle.setChecked(bool(enabled))
        del blocker

    def reset_experience_statistics(self) -> None:
        if self._experience_reset_handler is None or self._experience_reset_handler() is not False:
            self.experience.apply_snapshot({"experience": "已重置"})

    def set_bar_preview_provider(self, provider: Callable[[bool], dict[str, dict[str, object]]]) -> None:
        self._bar_preview_provider = provider
        self.bar_preview_provider = provider

    def set_experience_reset_handler(self, handler: Callable[[], bool | None]) -> None:
        self._experience_reset_handler = handler

    def set_current_percentages(self, hp_percent: float | None, mp_percent: float | None) -> None:
        hp = "--" if hp_percent is None else f"{hp_percent:.1f}%"
        mp = "--" if mp_percent is None else f"{mp_percent:.1f}%"
        self.dashboard.apply_snapshot({"hp_mp": f"{hp} / {mp}"})

    def set_bar_detection_debug(self, hp_debug: str, mp_debug: str) -> None:
        self._latest_bar_detection_debug = (str(hp_debug), str(mp_debug))

    def set_experience_snapshot(self, snapshot) -> None:
        status = getattr(snapshot, "status", "--")
        self.experience.apply_snapshot({"experience": status})

    def set_exp_efficiency_enabled(self, enabled: bool) -> None:
        self.settings.exp_efficiency_enabled = bool(enabled)
        self.experience.bindings["exp_efficiency_enabled"].sync(bool(enabled))

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
        translated_macro_status = runtime_value(macro_status)
        translated_held_keys = runtime_value(held_keys)
        self.dashboard.apply_snapshot(
            {
                "target": f"{'作用中' if target_active else '未作用'}｜{foreground_title}",
                "workers": f"自動化={'啟用' if scripts_enabled else '停用'}｜組合={translated_macro_status}｜按住={translated_held_keys}",
                "last_action": last_action,
            }
        )
        self.diagnostics.metrics.setText(
            f"目標={'作用中' if target_active else '未作用'}｜自動化={'啟用' if scripts_enabled else '停用'}｜"
            f"組合={translated_macro_status}｜按住={translated_held_keys}"
        )

    def set_backend_diagnostics(self, text: str) -> None:
        if text:
            self.diagnostics.metrics.setText(text)

    def show_toggle_notice(self, message: str) -> None:
        self.set_status(message)
        if self._toggle_notice is None:
            self._toggle_notice = ToggleNotice()
        self._toggle_notice.show_message(message)

    def append_console(self, text: str) -> None:
        self._console_buffer.append(text)

    def _flush_console(self) -> None:
        self.diagnostics.append_console_batch(self._console_buffer.drain())

    def refresh_bar_preview_once(self) -> bool:
        return self._refresh_bar_preview(make_target_topmost=False)

    def _refresh_bar_preview(self, *, make_target_topmost: bool) -> bool:
        provider = getattr(self, "_bar_preview_provider", None) or getattr(self, "bar_preview_provider", None)
        if provider is None:
            return False
        if not hasattr(self, "_preview_job_active"):
            self._apply_bar_preview_result(provider(make_target_topmost))
            return True
        if self._preview_job_active:
            return False
        self._preview_job_active = True
        job = CallableJob(lambda: provider(make_target_topmost))
        self._preview_job = job
        job.signals.succeeded.connect(self._apply_bar_preview_result)
        job.signals.failed.connect(self._bar_preview_failed)
        QThreadPool.globalInstance().start(job)
        return True

    def _bar_preview_failed(self, message: str) -> None:
        self._preview_job_active = False
        self._preview_job = None
        self.set_status(f"偵測預覽失敗：{message}")

    def _apply_bar_preview_result(self, snapshots: object) -> None:
        self._preview_job_active = False
        if hasattr(self, "_preview_job"):
            self._preview_job = None
        if not isinstance(snapshots, dict):
            self.set_status("偵測預覽失敗：回傳格式錯誤")
            return
        missing = [
            str(payload.get("error") or "尚無可預覽的偵測區域")
            for payload in snapshots.values()
            if not isinstance(payload, dict) or payload.get("image") is None
        ]
        if missing:
            self.set_status("HP/MP 預覽未更新：尚未同時抓到 HP/MP 條")
            return
        page = self.pages["自動喝水"]
        next_images: list[QPixmap] = []
        for name in ("hp", "mp"):
            payload = snapshots[name]
            raw = payload.get("image")
            pixmap = QPixmap()
            if not isinstance(raw, bytes) or not pixmap.loadFromData(raw):
                self.set_status(f"{name.upper()} 預覽影像格式無效")
                return
            page.preview_labels[name].setPixmap(pixmap)
            next_images.append(pixmap)
        self.bar_preview_images = next_images
        self.bar_preview_has_snapshot = True
        self.pages["自動喝水"].preview_status.setText(
            "｜".join(f"{name.upper()}：{'正常' if payload else '--'}" for name, payload in snapshots.items())
            or "尚無 HP／MP 預覽"
        )

    def is_detecting_key(self) -> bool:
        return time.monotonic() < self._key_detection_until

    def _hotkey_captured(self, hotkey: str) -> None:
        from maple_star.adapters.win_input import parse_vk_key

        self._key_detection_until = time.monotonic() + 0.25
        self._key_detection_finished = True
        try:
            self._key_detection_release_vks = {parse_vk_key(hotkey)}
        except ValueError:
            self._key_detection_release_vks = set()
        self.set_status(f"快捷鍵已設定為 {hotkey}")

    def consume_key_detection_finished(self) -> bool:
        value = self._key_detection_finished
        self._key_detection_finished = False
        return value

    def is_key_detection_release_pending(self) -> bool:
        if not self._key_detection_release_vks:
            return False
        from maple_star.adapters.key_capture import pressed_detectable_vks

        if self._key_detection_release_vks & pressed_detectable_vks():
            return True
        self._key_detection_release_vks.clear()
        return False

    def pump(self) -> bool:
        self.application.processEvents()
        return not self.closed

    def sync_after_event_processing(self) -> bool:
        return not self.closed

    def exists(self) -> bool:
        return not self.closed

    def apply_to_settings(self) -> None:
        return None

    def set_shutdown_handler(self, handler: Callable[[], None]) -> None:
        self._shutdown = handler

    def _sync_bindings_from_settings(self) -> None:
        for page in self.pages.values():
            for name, binding in getattr(page, "bindings", {}).items():
                value = getattr(self.settings, name)
                binding.sync(value if value is not None else "")
        self.pages["小地圖巡航"].periodic_model.replace_from_settings(self.settings)
        self.pages["手把組合"].model.replace_slots(self.settings.combo_slots)

    def create_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "新增設定檔", "設定檔名稱")
        profile_name = normalize_profile_name(name, "")
        if not accepted or not profile_name:
            return
        if not self.settings.create_profile(profile_name):
            self.set_status(f"設定檔已存在：{profile_name}")
            return
        self._sync_bindings_from_settings()
        self.set_status(f"已新增設定檔：{profile_name}")

    def delete_profile(self) -> None:
        profile_name = self.settings.active_profile
        if len(self.settings.profile_names()) <= 1:
            self.set_status("至少需保留一個設定檔")
            return
        if QMessageBox.question(self, "刪除設定檔", f"刪除設定檔「{profile_name}」？") != QMessageBox.StandardButton.Yes:
            return
        if self.settings.delete_profile(profile_name):
            self._sync_bindings_from_settings()
            self.set_status(f"已刪除設定檔：{profile_name}")

    def export_settings(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "匯出設定", "maple-star-settings.json", "JSON (*.json)")
        if not path:
            return
        try:
            self.settings.save_current_profile()
            save_settings(self.settings, Path(path))
        except Exception as exc:
            self.set_status(f"匯出設定失敗：{exc}")
            return
        self.set_status(f"已匯出設定：{path}")

    def import_settings(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "匯入設定", "", "JSON (*.json)")
        if not path:
            return
        try:
            imported = load_settings(Path(path), save_migrations=False)
            copy_setting_values(imported, self.settings)
            self.settings.active_profile = imported.active_profile
            self.settings.profiles = imported.profiles
            save_settings(self.settings, SETTINGS_PATH)
        except Exception as exc:
            self.set_status(f"匯入設定失敗：{exc}")
            return
        self._sync_bindings_from_settings()
        self.set_status(f"已匯入設定：{path}")


__all__ = ["AutoPotionSettingsGui", "GuiConsoleWriter"]
