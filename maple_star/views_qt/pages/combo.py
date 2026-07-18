from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QTableView, QVBoxLayout, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..models.combo_model import ComboTableModel


COMBO_FIELDS = (
    "rb_enabled", "rb_jump_key", "rb_skill_key", "rb_controller_button",
    "rb_skill_delay_seconds", "rb_jump_interval_seconds", "lb_enabled",
    "lb_jump_key", "lb_skill_key", "lb_controller_button", "lb_skill_delay_seconds",
)


class ComboPage(QWidget):
    def __init__(
        self,
        slots: dict[str, dict[str, object]] | None = None,
        *,
        settings: object | None = None,
        on_change: Callable[[dict[str, dict[str, object]]], None] | None = None,
        on_field_change: Callable[[str, object], None] | None = None,
    ) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        layout = QVBoxLayout(self)
        title = QLabel("手把組合")
        title.setObjectName("title")
        layout.addWidget(title)
        form = QFormLayout()
        for field in COMBO_FIELDS:
            value = getattr(settings, field, False if field.endswith("enabled") else "")
            if isinstance(value, bool):
                widget = QCheckBox()
            elif isinstance(value, float):
                widget = QDoubleSpinBox()
                widget.setRange(0.0, 60.0)
            else:
                widget = HotkeyEdit() if field.endswith("_key") else QLineEdit()
            binding = bind_widget(widget, lambda changed, name=field: on_field_change and on_field_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            form.addRow(field, widget)
        layout.addLayout(form)
        self.model = ComboTableModel(slots or {}, on_change=on_change)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)


__all__ = ["COMBO_FIELDS", "ComboPage"]
