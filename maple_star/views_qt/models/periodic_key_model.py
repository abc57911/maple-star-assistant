from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass(slots=True)
class PeriodicKeyRow:
    enabled: bool
    key: str
    interval_seconds: float


def periodic_rows_from_settings(settings: object) -> list[PeriodicKeyRow]:
    return [
        PeriodicKeyRow(
            bool(getattr(settings, f"minimap_cruise_periodic_key_{index}_enabled", False)),
            str(getattr(settings, f"minimap_cruise_periodic_key_{index}", "")),
            float(getattr(settings, f"minimap_cruise_periodic_key_{index}_interval_seconds", 60.0)),
        )
        for index in range(1, 6)
    ]


class PeriodicKeyTableModel(QAbstractTableModel):
    columns = ("啟用", "按鍵", "間隔秒數")

    def __init__(self, settings: object, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.rows = periodic_rows_from_settings(settings)
        self._on_change = on_change

    def replace_from_settings(self, settings: object) -> None:
        self.beginResetModel()
        self.rows = periodic_rows_from_settings(settings)
        self.endResetModel()

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        value = (row.enabled, row.key, row.interval_seconds)[index.column()]
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole) and index.column() != 0:
            return value
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        row = self.rows[index.row()]
        prefix = f"minimap_cruise_periodic_key_{index.row() + 1}"
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            row.enabled = value == Qt.CheckState.Checked.value
            name, changed = f"{prefix}_enabled", row.enabled
        elif index.column() == 1 and role == Qt.ItemDataRole.EditRole:
            row.key = str(value).strip()
            name, changed = prefix, row.key
        elif index.column() == 2 and role == Qt.ItemDataRole.EditRole:
            try:
                row.interval_seconds = max(0.1, min(3600.0, float(value)))
            except (TypeError, ValueError):
                return False
            name, changed = f"{prefix}_interval_seconds", row.interval_seconds
        else:
            return False
        self.dataChanged.emit(index, index, [role])
        if self._on_change is not None:
            self._on_change(name, changed)
        return True

    def flags(self, index: QModelIndex):
        flags = super().flags(index) | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags | (Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else Qt.ItemFlag.ItemIsEditable)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.columns[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)


__all__ = ["PeriodicKeyRow", "PeriodicKeyTableModel", "periodic_rows_from_settings"]
