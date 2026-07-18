from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..components import SettingsCard, SwitchControl, create_page_shell


EXPERIENCE_FIELDS = (
    "exp_efficiency_enabled",
    "experience_toggle_hotkey",
    "experience_reset_hotkey",
    "character_stat_hotkey",
    "compact_experience_mode",
    "window_topmost",
    "full_panel_window_x",
    "full_panel_window_y",
    "compact_experience_window_x",
    "compact_experience_window_y",
)


class ExperiencePage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        self.settings_grid = create_page_shell(self, "經驗計算")

        statistics_card = self.settings_grid.add_card(SettingsCard("EXP 統計"))
        self.status_value = QLabel("--")
        self.status_value.setWordWrap(True)
        statistics_card.add_control("目前狀態", self.status_value)
        self._add_field(statistics_card, "exp_efficiency_enabled", settings, on_change)
        self.reset_experience = QPushButton("重置 EXP 統計")
        self.reset_experience.setObjectName("actionButton")
        statistics_card.add_widget(self.reset_experience)

        hotkey_card = self.settings_grid.add_card(SettingsCard("EXP 快捷鍵"))
        for field in ("experience_toggle_hotkey", "experience_reset_hotkey", "character_stat_hotkey"):
            self._add_field(hotkey_card, field, settings, on_change)

        window_card = self.settings_grid.add_card(SettingsCard("EXP 視窗"))
        for field in (
            "compact_experience_mode",
            "window_topmost",
            "full_panel_window_x",
            "full_panel_window_y",
            "compact_experience_window_x",
            "compact_experience_window_y",
        ):
            self._add_field(window_card, field, settings, on_change)

    def _add_field(
        self,
        card: SettingsCard,
        field: str,
        settings: object | None,
        on_change: Callable[[str, object], None] | None,
    ) -> None:
        value = getattr(settings, field, False if field in {
            "exp_efficiency_enabled", "compact_experience_mode", "window_topmost"
        } else "")
        if isinstance(value, bool):
            widget = SwitchControl()
        elif "hotkey" in field:
            widget = HotkeyEdit()
        else:
            widget = QLineEdit()
        binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
        binding.sync(value if value is not None else "")
        self.bindings[field] = binding
        card.add_field(field, widget)

    def apply_snapshot(self, snapshot: dict[str, object]) -> None:
        if "experience" in snapshot:
            self.status_value.setText(str(snapshot["experience"]))


__all__ = ["EXPERIENCE_FIELDS", "ExperiencePage"]
