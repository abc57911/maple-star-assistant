from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..components import SettingsCard, SwitchControl, create_page_shell


POTION_FIELDS = (
    "hp_enabled", "mp_enabled", "hp_threshold_percent", "mp_threshold_percent",
    "hp_key", "mp_key", "hp_cooldown_seconds", "mp_cooldown_seconds",
    "hp_continuous_enabled", "mp_continuous_enabled",
    "hp_continuous_stop_margin_percent", "mp_continuous_stop_margin_percent",
)


def _potion_widget(field: str, value: object):
    if isinstance(value, bool):
        return SwitchControl()
    if isinstance(value, int):
        widget = QSpinBox()
        widget.setRange(0, 100)
        return widget
    if isinstance(value, float):
        widget = QDoubleSpinBox()
        widget.setRange(0.0, 100.0)
        widget.setDecimals(2)
        return widget
    return HotkeyEdit()


class PotionPage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        self.settings_grid = create_page_shell(self, "自動喝水")
        cards = {
            "hp": self.settings_grid.add_card(SettingsCard("HP 自動補充")),
            "mp": self.settings_grid.add_card(SettingsCard("MP 自動補充")),
        }
        for field in POTION_FIELDS:
            value = getattr(settings, field, False if field.endswith("enabled") else "")
            widget = _potion_widget(field, value)
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            cards["hp" if field.startswith("hp_") else "mp"].add_field(field, widget)

        preview_card = self.settings_grid.add_card(SettingsCard("HP／MP 預覽", wide=True), full_width=True)
        self.preview_status = QLabel("尚無 HP／MP 預覽")
        self.preview_status.setObjectName("secondaryText")
        preview_card.add_widget(self.preview_status)
        preview_layout = QHBoxLayout()
        self.preview_labels: dict[str, QLabel] = {}
        for name in ("hp", "mp"):
            label = QLabel(name.upper())
            label.setObjectName("previewPanel")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(56)
            preview_layout.addWidget(label, 1)
            self.preview_labels[name] = label
        preview_card.add_layout(preview_layout)
        self.refresh_preview = QPushButton("重新擷取 HP／MP 預覽")
        self.refresh_preview.setObjectName("actionButton")
        preview_card.add_widget(self.refresh_preview)


__all__ = ["POTION_FIELDS", "PotionPage"]
