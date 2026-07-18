from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..components import SettingsCard, SwitchControl, create_page_shell


DASHBOARD_FIELDS = (
    "toggle_hotkey", "emergency_stop_hotkey", "pickup_toggle_hotkey", "pickup_key",
)


class DashboardPage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        self.settings_grid = create_page_shell(self, "監控")

        status_card = self.settings_grid.add_card(SettingsCard("執行狀態"))
        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(8)
        self.values: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(
            (
                ("target", "目標視窗"),
                ("workers", "背景程序"),
                ("hp_mp", "HP／MP"),
                ("last_action", "最近動作"),
            )
        ):
            status_grid.addWidget(QLabel(label), row, 0)
            value = QLabel("--")
            value.setObjectName(key)
            value.setWordWrap(True)
            status_grid.addWidget(value, row, 1)
            self.values[key] = value
        status_card.add_layout(status_grid)

        control_card = self.settings_grid.add_card(SettingsCard("快速控制", "切換自動撿取執行狀態。"))
        self.pickup_toggle = SwitchControl()
        control_card.add_control("自動撿取", self.pickup_toggle)

        self.hotkey_card = self.settings_grid.add_card(SettingsCard("快捷鍵與統計"))
        for field in DASHBOARD_FIELDS:
            value = getattr(settings, field, "")
            widget = SwitchControl() if isinstance(value, bool) else HotkeyEdit()
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            self.hotkey_card.add_field(field, widget)
            if field == "toggle_hotkey":
                self.auto_drink_toggle = SwitchControl()
                self.hotkey_card.add_control("自動喝水", self.auto_drink_toggle)

    def apply_snapshot(self, snapshot: dict[str, object]) -> None:
        for key, label in self.values.items():
            if key in snapshot:
                label.setText(str(snapshot[key]))


__all__ = ["DASHBOARD_FIELDS", "DashboardPage"]
