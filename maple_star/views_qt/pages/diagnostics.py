from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QWidget

from ..bindings import SettingsBinding
from ..components import SettingsCard, create_page_shell


DIAGNOSTIC_FIELDS: tuple[str, ...] = ()


class DiagnosticsPage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        self.settings_grid = create_page_shell(self, "診斷")

        health_card = self.settings_grid.add_card(SettingsCard("背景程序健康狀態"))
        self.metrics = QLabel("PID／執行代次／心跳／進度／佇列：--")
        self.metrics.setWordWrap(True)
        health_card.add_widget(self.metrics)

        console_card = self.settings_grid.add_card(SettingsCard("診斷紀錄", "顯示後端原始診斷資訊。", wide=True), full_width=True)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1000)
        self.console.setMinimumHeight(260)
        console_card.add_widget(self.console, stretch=1)

    def append_console_batch(self, lines: list[str]) -> None:
        if lines:
            self.console.appendPlainText("\n".join(lines))


__all__ = ["DIAGNOSTIC_FIELDS", "DiagnosticsPage"]
