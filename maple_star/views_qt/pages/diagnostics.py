from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from ..bindings import SettingsBinding, bind_widget


DIAGNOSTIC_FIELDS = (
    "console_collapsed", "combo_group_collapsed", "minimap_cruise_group_collapsed",
    "compact_experience_mode", "window_topmost", "full_panel_window_x",
    "full_panel_window_y", "compact_experience_window_x", "compact_experience_window_y",
)


class DiagnosticsPage(QWidget):
    def __init__(self, settings: object | None = None, *, on_change: Callable[[str, object], None] | None = None) -> None:
        super().__init__()
        self.bindings: dict[str, SettingsBinding] = {}
        layout = QVBoxLayout(self)
        title = QLabel("診斷")
        title.setObjectName("title")
        layout.addWidget(title)
        self.metrics = QLabel("PID / incarnation / heartbeat / progress / queue：--")
        layout.addWidget(self.metrics)
        form = QFormLayout()
        for field in DIAGNOSTIC_FIELDS:
            value = getattr(settings, field, False if field.endswith(("collapsed", "mode", "topmost")) else "")
            widget = QCheckBox() if isinstance(value, bool) else QLineEdit()
            binding = bind_widget(widget, lambda changed, name=field: on_change and on_change(name, changed))
            binding.sync(value)
            self.bindings[field] = binding
            form.addRow(field, widget)
        layout.addLayout(form)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1000)
        layout.addWidget(self.console, 1)

    def append_console_batch(self, lines: list[str]) -> None:
        if lines:
            self.console.appendPlainText("\n".join(lines))


__all__ = ["DIAGNOSTIC_FIELDS", "DiagnosticsPage"]
