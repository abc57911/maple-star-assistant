from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..labels import COMBO_COLUMN_LABELS, display_value


class ComboTableModel(QAbstractTableModel):
    columns = (
        "slot",
        "enabled",
        "script_id",
        "trigger_button",
        "jump_key",
        "skill_key",
        "attack_key",
        "attack_start_delay_seconds",
        "attack_hold_seconds",
        "skill_delay_seconds",
        "jump_interval_seconds",
    )

    def __init__(self, slots: dict[str, dict[str, object]], *, on_change: Callable[[dict[str, dict[str, object]]], None] | None = None) -> None:
        super().__init__()
        self._names = sorted(slots)
        self._slots = {name: dict(slots[name]) for name in self._names}
        self._on_change = on_change

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self._names)

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        name = self._names[index.row()]
        column = self.columns[index.column()]
        value = name if column == "slot" else self._slots[name].get(column, "")
        return display_value(column, value) if role == Qt.ItemDataRole.DisplayRole else value

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole or index.column() == 0:
            return False
        name = self._names[index.row()]
        self._slots[name][self.columns[index.column()]] = value
        self.dataChanged.emit(index, index, [role])
        if self._on_change is not None:
            self._on_change(self.to_dict())
        return True

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        return flags if index.column() == 0 else flags | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return COMBO_COLUMN_LABELS[self.columns[section]] if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {name: dict(payload) for name, payload in self._slots.items()}

    def replace_slots(self, slots: dict[str, dict[str, object]]) -> None:
        self.beginResetModel()
        self._names = sorted(slots)
        self._slots = {name: dict(slots[name]) for name in self._names}
        self.endResetModel()


__all__ = ["ComboTableModel"]
