from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QHeaderView, QLineEdit, QSpinBox, QTableView, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..components import SettingsCard, SwitchControl, create_page_shell
from ..delegates import SwitchDelegate
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

BASIC_FIELDS = (
    "minimap_cruise_toggle_hotkey", "minimap_cruise_attack_key", "minimap_cruise_left_x",
    "minimap_cruise_right_x", "minimap_cruise_detect_y", "minimap_cruise_detect_band_height",
    "minimap_cruise_last_direction",
)

RECOVERY_FIELDS = (
    "minimap_cruise_pre_boundary_skill_enabled", "minimap_cruise_pre_boundary_skill_key",
    "minimap_cruise_pre_boundary_distance", "minimap_cruise_stationary_skill_key",
    "minimap_cruise_stationary_min_forward_pixels", "minimap_cruise_lie_detector_alert_volume_percent",
)


def _cruise_widget(field: str, value: object):
    if field == "minimap_cruise_last_direction":
        widget = QComboBox()
        widget.addItem("左", "left")
        widget.addItem("右", "right")
        return widget
    if isinstance(value, bool):
        return SwitchControl()
    if isinstance(value, int):
        widget = QSpinBox()
        widget.setRange(-1, 100000)
        return widget
    if isinstance(value, float):
        widget = QDoubleSpinBox()
        widget.setRange(0.0, 3600.0)
        return widget
    return HotkeyEdit() if field.endswith(("_key", "_hotkey")) else QLineEdit()


class CruisePage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        self.settings_grid = create_page_shell(self, "小地圖巡航")
        cards = {
            "basic": self.settings_grid.add_card(SettingsCard("巡航與邊界")),
            "recovery": self.settings_grid.add_card(SettingsCard("技能與警示")),
        }
        for field in BASIC_FIELDS + RECOVERY_FIELDS:
            value = getattr(settings, field, "")
            widget = _cruise_widget(field, value)
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value if value is not None else (-1 if isinstance(widget, QSpinBox) else ""))
            self.bindings[field] = binding
            cards["basic" if field in BASIC_FIELDS else "recovery"].add_field(field, widget)

        periodic_card = self.settings_grid.add_card(SettingsCard("週期按鍵", wide=True), full_width=True)
        self.periodic_model = PeriodicKeyTableModel(settings, on_change=on_change)
        self.periodic_table = QTableView()
        self.periodic_table.setModel(self.periodic_model)
        self.periodic_table.setItemDelegateForColumn(0, SwitchDelegate(self.periodic_table))
        self.periodic_table.setAlternatingRowColors(True)
        header = self.periodic_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.periodic_table.setMinimumHeight(210)
        periodic_card.add_widget(self.periodic_table)


__all__ = ["CRUISE_FIELDS", "CruisePage"]
