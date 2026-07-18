from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QFormLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget


DASHBOARD_FIELDS = (
    "toggle_hotkey", "emergency_stop_hotkey", "experience_toggle_hotkey",
    "experience_reset_hotkey", "character_stat_hotkey", "pickup_toggle_hotkey",
    "pickup_key", "exp_efficiency_enabled",
)


class DashboardPage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        layout = QVBoxLayout(self)
        title = QLabel("監控")
        title.setObjectName("title")
        layout.addWidget(title)
        grid = QGridLayout()
        self.values: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(
            (("target", "目標視窗"), ("workers", "Workers"), ("hp_mp", "HP / MP"), ("experience", "經驗效率"), ("last_action", "最近動作"))
        ):
            grid.addWidget(QLabel(label), row, 0)
            value = QLabel("--")
            value.setObjectName(key)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        layout.addLayout(grid)
        self.global_toggle = QPushButton("啟用全部自動化")
        self.global_toggle.setCheckable(True)
        layout.addWidget(self.global_toggle)
        self.pickup_toggle = QPushButton("啟用自動撿取")
        self.pickup_toggle.setCheckable(True)
        layout.addWidget(self.pickup_toggle)
        self.reset_experience = QPushButton("重置經驗統計")
        layout.addWidget(self.reset_experience)
        form = QFormLayout()
        for field in DASHBOARD_FIELDS:
            value = getattr(settings, field, False if field == "exp_efficiency_enabled" else "")
            widget = QCheckBox() if isinstance(value, bool) else HotkeyEdit()
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            form.addRow(field, widget)
        layout.addLayout(form)
        layout.addStretch(1)

    def apply_snapshot(self, snapshot: dict[str, object]) -> None:
        for key, label in self.values.items():
            if key in snapshot:
                label.setText(str(snapshot[key]))


__all__ = ["DASHBOARD_FIELDS", "DashboardPage"]
