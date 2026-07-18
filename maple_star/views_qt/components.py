from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .labels import field_text


PAGE_BREAKPOINT = 820
CARD_MIN_WIDTH = 340
CARD_MAX_WIDTH = 480
WIDE_CARD_MAX_WIDTH = 976


def draw_switch(
    painter: QPainter,
    rect,
    *,
    checked: bool,
    enabled: bool,
    focused: bool = False,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    track = QRectF(rect)
    track.setWidth(min(track.width(), 44.0))
    track.setHeight(min(track.height(), 24.0))
    track.moveCenter(QRectF(rect).center())
    active = QColor("#2f7df4") if enabled else QColor("#40506a")
    inactive = QColor("#3a4558") if enabled else QColor("#2a303b")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(active if checked else inactive)
    painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
    knob_size = track.height() - 6.0
    knob_x = track.right() - knob_size - 3.0 if checked else track.left() + 3.0
    knob = QRectF(knob_x, track.top() + 3.0, knob_size, knob_size)
    painter.setBrush(QColor("#ffffff") if enabled else QColor("#9aa3b2"))
    painter.drawEllipse(knob)
    if focused:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor("#79a8ff"))
        focus = track.adjusted(-3.0, -3.0, 3.0, 3.0)
        painter.drawRoundedRect(focus, focus.height() / 2, focus.height() / 2)
    painter.restore()


class SwitchControl(QAbstractButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleDescription("切換開關")

    def sizeHint(self) -> QSize:
        return QSize(50, 30)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        draw_switch(
            painter,
            self.rect().adjusted(3, 3, -3, -3),
            checked=self.isChecked(),
            enabled=self.isEnabled(),
            focused=self.hasFocus(),
        )


def constrain_input(widget: QWidget) -> None:
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        widget.setMaximumWidth(140)
    elif isinstance(widget, QLineEdit):
        maximum = 180 if widget.__class__.__name__ == "HotkeyEdit" else 280
        widget.setMaximumWidth(maximum)
    elif widget.__class__.__name__ == "QComboBox":
        widget.setMaximumWidth(180)
    if not isinstance(widget, SwitchControl):
        widget.setMinimumWidth(min(widget.maximumWidth(), 120))


class SettingsCard(QFrame):
    def __init__(self, title: str, description: str = "", *, wide: bool = False) -> None:
        super().__init__()
        self.setObjectName("settingsCard")
        self.setProperty("wideCard", wide)
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setMaximumWidth(WIDE_CARD_MAX_WIDTH if wide else CARD_MAX_WIDTH)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding if wide else QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        root.addWidget(heading)
        if description:
            details = QLabel(description)
            details.setObjectName("cardDescription")
            details.setWordWrap(True)
            root.addWidget(details)
        self.fields = QGridLayout()
        self.fields.setHorizontalSpacing(18)
        self.fields.setVerticalSpacing(10)
        self.fields.setColumnStretch(0, 1)
        root.addLayout(self.fields)
        self._row = 0

    def add_field(self, name: str, widget: QWidget) -> QWidget:
        text = field_text(name)
        return self.add_control(text.label, widget, text.description)

    def add_control(self, label: str, widget: QWidget, description: str = "") -> QWidget:
        label_box = QWidget(self)
        label_layout = QVBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(2)
        name_label = QLabel(label, label_box)
        name_label.setObjectName("fieldLabel")
        name_label.setWordWrap(True)
        label_layout.addWidget(name_label)
        if description:
            detail_label = QLabel(description, label_box)
            detail_label.setObjectName("fieldDescription")
            detail_label.setWordWrap(True)
            label_layout.addWidget(detail_label)
        constrain_input(widget)
        widget.setAccessibleName(label)
        self.fields.addWidget(label_box, self._row, 0)
        self.fields.addWidget(widget, self._row, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._row += 1
        return widget

    def add_layout(self, layout: QLayout) -> None:
        self.fields.addLayout(layout, self._row, 0, 1, 2)
        self._row += 1

    def add_widget(self, widget: QWidget, *, stretch: int = 0) -> None:
        self.fields.addWidget(widget, self._row, 0, 1, 2)
        if stretch:
            self.fields.setRowStretch(self._row, stretch)
        self._row += 1


class SettingsGrid(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[tuple[SettingsCard, bool]] = []
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    @property
    def column_count(self) -> int:
        return self._columns

    def add_card(self, card: SettingsCard, *, full_width: bool = False) -> SettingsCard:
        self._cards.append((card, full_width))
        self._relayout(self._columns or (2 if self.width() >= PAGE_BREAKPOINT else 1), force=True)
        return card

    def layout_for_width(self, width: int) -> None:
        self._relayout(2 if width >= PAGE_BREAKPOINT else 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.layout_for_width(event.size().width())

    def _relayout(self, columns: int, *, force: bool = False) -> None:
        if not force and columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        cursor = 0
        for card, full_width in self._cards:
            if columns == 2 and full_width:
                if cursor % 2:
                    cursor += 1
                row, column, span = cursor // 2, 0, 2
                cursor += 2
            else:
                row, column, span = cursor // columns, cursor % columns, 1
                cursor += 1
            alignment = Qt.AlignmentFlag.AlignTop if full_width else (
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
            )
            self.grid.addWidget(card, row, column, 1, span, alignment)
        for column in range(2):
            self.grid.setColumnStretch(column, 0)
        self.grid.setColumnStretch(columns, 1)


def create_page_shell(page: QWidget, title: str) -> SettingsGrid:
    root = QVBoxLayout(page)
    root.setContentsMargins(22, 18, 22, 18)
    root.setSpacing(14)
    heading = QLabel(title, page)
    heading.setObjectName("pageTitle")
    root.addWidget(heading)
    scroll = QScrollArea(page)
    scroll.setObjectName("pageScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    grid = SettingsGrid(scroll)
    scroll.setWidget(grid)
    root.addWidget(scroll, 1)
    return grid


def horizontal_controls(*widgets: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return layout


__all__ = [
    "CARD_MAX_WIDTH",
    "CARD_MIN_WIDTH",
    "PAGE_BREAKPOINT",
    "SettingsCard",
    "SettingsGrid",
    "SwitchControl",
    "constrain_input",
    "create_page_shell",
    "draw_switch",
    "horizontal_controls",
]
