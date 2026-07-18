from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLineEdit, QSpinBox, QWidget


class HotkeyEdit(QLineEdit):
    captured = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        sequence = QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
        if not sequence or sequence in {"Ctrl", "Alt", "Shift", "Meta"}:
            event.ignore()
            return
        self.setText(sequence)
        self.captured.emit(sequence)
        self.editingFinished.emit()
        event.accept()


class SettingsBinding:
    def __init__(
        self,
        widget: QWidget,
        *,
        read: Callable[[], object],
        write: Callable[[object], None],
        changed_signal,
        on_user_change: Callable[[object], None],
    ) -> None:
        self.widget = widget
        self._read = read
        self._write = write
        self._on_user_change = on_user_change
        changed_signal.connect(self._changed)

    def _changed(self, *_args) -> None:
        self._on_user_change(self._read())

    def sync(self, value: object) -> None:
        blocker = QSignalBlocker(self.widget)
        self._write(value)
        del blocker


def bind_widget(widget: QWidget, on_user_change: Callable[[object], None]) -> SettingsBinding:
    if isinstance(widget, QCheckBox):
        return SettingsBinding(
            widget,
            read=widget.isChecked,
            write=lambda value: widget.setChecked(bool(value)),
            changed_signal=widget.toggled,
            on_user_change=on_user_change,
        )
    if isinstance(widget, QSpinBox):
        return SettingsBinding(
            widget,
            read=widget.value,
            write=lambda value: widget.setValue(int(value)),
            changed_signal=widget.valueChanged,
            on_user_change=on_user_change,
        )
    if isinstance(widget, QDoubleSpinBox):
        return SettingsBinding(
            widget,
            read=widget.value,
            write=lambda value: widget.setValue(float(value)),
            changed_signal=widget.valueChanged,
            on_user_change=on_user_change,
        )
    if isinstance(widget, QLineEdit):
        return SettingsBinding(
            widget,
            read=widget.text,
            write=lambda value: widget.setText(str(value or "")),
            changed_signal=widget.editingFinished,
            on_user_change=on_user_change,
        )
    raise TypeError(f"unsupported settings widget: {type(widget).__name__}")


__all__ = ["HotkeyEdit", "SettingsBinding", "bind_widget"]
