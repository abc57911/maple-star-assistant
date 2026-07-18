from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDoubleSpinBox, QHeaderView, QLineEdit, QTableView, QWidget

from ..bindings import HotkeyEdit, SettingsBinding, bind_widget
from ..components import SettingsCard, SwitchControl, create_page_shell
from ..delegates import SwitchDelegate
from ..models.combo_model import ComboTableModel


COMBO_FIELDS = (
    "rb_enabled", "rb_jump_key", "rb_skill_key", "rb_controller_button",
    "rb_skill_delay_seconds", "rb_jump_interval_seconds", "lb_enabled",
    "lb_jump_key", "lb_skill_key", "lb_controller_button", "lb_skill_delay_seconds",
)


def _combo_widget(field: str, value: object):
    if isinstance(value, bool):
        return SwitchControl()
    if isinstance(value, float):
        widget = QDoubleSpinBox()
        widget.setRange(0.0, 60.0)
        widget.setDecimals(3)
        return widget
    return HotkeyEdit() if field.endswith("_key") else QLineEdit()


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
        self.settings_grid = create_page_shell(self, "手把組合")
        cards = {
            "rb": self.settings_grid.add_card(SettingsCard("RB 組合")),
            "lb": self.settings_grid.add_card(SettingsCard("LB 組合")),
        }
        for field in COMBO_FIELDS:
            value = getattr(settings, field, False if field.endswith("enabled") else "")
            widget = _combo_widget(field, value)
            binding = bind_widget(widget, lambda changed, name=field: on_field_change and on_field_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            cards["rb" if field.startswith("rb_") else "lb"].add_field(field, widget)

        table_card = self.settings_grid.add_card(SettingsCard("自訂組合", wide=True), full_width=True)
        self.model = ComboTableModel(slots or {}, on_change=on_change)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(1, SwitchDelegate(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(250)
        table_card.add_widget(self.table)


__all__ = ["COMBO_FIELDS", "ComboPage"]
