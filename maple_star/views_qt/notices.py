from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel


class ToggleNotice(QLabel):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("toggleNotice")
        self.setStyleSheet(
            "QLabel { color: white; background: #173255; border: 1px solid #3b82f6; "
            "border-radius: 8px; padding: 10px 16px; font-size: 14px; }"
        )
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, message: str, *, duration_ms: int = 1600) -> None:
        self.setText(message)
        self.adjustSize()
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 48)
        self.show()
        self.raise_()
        self._timer.start(max(100, int(duration_ms)))


__all__ = ["ToggleNotice"]
