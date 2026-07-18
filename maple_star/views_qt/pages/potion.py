from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget


POTION_FIELDS = (
    "hp_enabled", "mp_enabled", "hp_threshold_percent", "mp_threshold_percent",
    "hp_key", "mp_key", "hp_cooldown_seconds", "mp_cooldown_seconds",
    "hp_continuous_enabled", "mp_continuous_enabled",
    "hp_continuous_stop_margin_percent", "mp_continuous_stop_margin_percent",
)


class PotionPage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        layout = QVBoxLayout(self)
        title = QLabel("自動喝水")
        title.setObjectName("title")
        layout.addWidget(title)
        form = QFormLayout()
        for field in POTION_FIELDS:
            value = getattr(settings, field, False if field.endswith("enabled") else "")
            if isinstance(value, bool):
                widget = QCheckBox()
            elif isinstance(value, int):
                widget = QSpinBox()
                widget.setRange(0, 100)
            elif isinstance(value, float):
                widget = QDoubleSpinBox()
                widget.setRange(0.0, 100.0)
                widget.setDecimals(2)
            else:
                widget = HotkeyEdit() if field.endswith("_key") else QLineEdit()
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            form.addRow(field, widget)
        layout.addLayout(form)
        self.preview_status = QLabel("尚無 HUD preview")
        layout.addWidget(self.preview_status)
        preview_layout = QHBoxLayout()
        self.preview_labels: dict[str, QLabel] = {}
        for name in ("hp", "mp"):
            label = QLabel(name.upper())
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(42)
            preview_layout.addWidget(label, 1)
            self.preview_labels[name] = label
        layout.addLayout(preview_layout)
        self.refresh_preview = QPushButton("重新擷取 HP / MP 預覽")
        layout.addWidget(self.refresh_preview)
        layout.addStretch(1)


__all__ = ["POTION_FIELDS", "PotionPage"]
