from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QStyledItemDelegate

from .components import draw_switch


class SwitchDelegate(QStyledItemDelegate):
    @staticmethod
    def switch_rect(cell_rect: QRect) -> QRect:
        rect = QRect(0, 0, 50, 30)
        rect.moveCenter(cell_rect.center())
        return rect

    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:
        value = bool(index.data(Qt.ItemDataRole.EditRole))
        rect = self.switch_rect(option.rect)
        draw_switch(
            painter,
            rect.adjusted(3, 3, -3, -3),
            checked=value,
            enabled=bool(option.state & QStyle.StateFlag.State_Enabled),
            focused=bool(option.state & QStyle.StateFlag.State_HasFocus),
        )

    def editorEvent(self, event, model, option, index) -> bool:
        if not (index.flags() & Qt.ItemFlag.ItemIsEnabled):
            return False
        toggled = (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.switch_rect(option.rect).contains(event.position().toPoint())
        )
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            toggled = event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select)
        if not toggled:
            return False
        return model.setData(index, not bool(index.data(Qt.ItemDataRole.EditRole)), Qt.ItemDataRole.EditRole)

    def createEditor(self, *_args):
        return None


__all__ = ["SwitchDelegate"]
