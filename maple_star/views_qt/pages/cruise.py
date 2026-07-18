from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QScrollArea, QSpinBox, QTableView, QVBoxLayout, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..models.periodic_key_model import PeriodicKeyTableModel


CRUISE_FIELDS = (
    "minimap_cruise_toggle_hotkey", "minimap_cruise_attack_key", "minimap_cruise_left_x",
    "minimap_cruise_right_x", "minimap_cruise_detect_y", "minimap_cruise_detect_band_height",
    "minimap_cruise_pre_boundary_skill_enabled", "minimap_cruise_pre_boundary_skill_key",
    "minimap_cruise_pre_boundary_distance", "minimap_cruise_stationary_skill_key",
    "minimap_cruise_stationary_min_forward_pixels", "minimap_cruise_lie_detector_alert_volume_percent",
    "minimap_cruise_last_direction",
    *(field for index in range(1, 6) for field in (
        f"minimap_cruise_periodic_key_{index}_enabled",
        f"minimap_cruise_periodic_key_{index}",
        f"minimap_cruise_periodic_key_{index}_interval_seconds",
    )),
)


class CruisePage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        layout = QVBoxLayout(self)
        title = QLabel("小地圖巡航")
        title.setObjectName("title")
        layout.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        form = QFormLayout()
        for field in CRUISE_FIELDS:
            if field.startswith("minimap_cruise_periodic_key_"):
                continue
            value = getattr(settings, field, "")
            if isinstance(value, bool):
                widget = QCheckBox()
            elif isinstance(value, int):
                widget = QSpinBox()
                widget.setRange(-1, 100000)
            elif isinstance(value, float):
                widget = QDoubleSpinBox()
                widget.setRange(0.0, 3600.0)
            else:
                widget = HotkeyEdit() if field.endswith(("_key", "_hotkey")) else QLineEdit()
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value if value is not None else (-1 if isinstance(widget, QSpinBox) else ""))
            self.bindings[field] = binding
            form.addRow(field, widget)
        body_layout.addLayout(form)
        body_layout.addWidget(QLabel("週期按鍵"))
        self.periodic_model = PeriodicKeyTableModel(settings, on_change=on_change)
        self.periodic_table = QTableView()
        self.periodic_table.setModel(self.periodic_model)
        self.periodic_table.setAlternatingRowColors(True)
        self.periodic_table.horizontalHeader().setStretchLastSection(True)
        self.periodic_table.setMinimumHeight(190)
        body_layout.addWidget(self.periodic_table)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)


__all__ = ["CRUISE_FIELDS", "CruisePage"]
