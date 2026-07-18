from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import APP_STYLESHEET
from .pages import ComboPage, CruisePage, DashboardPage, DiagnosticsPage, ExperiencePage, PotionPage


WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232


class MainWindow(QMainWindow):
    page_names = ("監控", "自動喝水", "小地圖巡航", "手把組合", "經驗計算", "診斷")

    def __init__(
        self,
        settings: object | None = None,
        *,
        shutdown: Callable[[], None] | None = None,
        settings_changed: Callable[[str, object], None] | None = None,
    ) -> None:
        super().__init__()
        self.closed = False
        self._shutdown = shutdown
        self._shutdown_started = False
        self._window_interaction_active = False
        self._navigation: list[QPushButton] = []
        self.setWindowTitle("楓星助手")
        self.resize(1080, 720)
        self.setMinimumSize(860, 560)
        self.setStyleSheet(APP_STYLESHEET)

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        sidebar = QFrame(body)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        nav_layout = QVBoxLayout(sidebar)
        nav_layout.setContentsMargins(14, 18, 14, 18)
        title = QLabel("MAPLE STAR", sidebar)
        title.setObjectName("title")
        nav_layout.addWidget(title)
        nav_layout.addSpacing(16)

        self.stack = QStackedWidget(body)
        page_widgets = (
            DashboardPage(settings, on_change=settings_changed),
            PotionPage(settings, on_change=settings_changed),
            CruisePage(settings, on_change=settings_changed),
            ComboPage(
                getattr(settings, "combo_slots", {}) if settings is not None else {},
                settings=settings,
                on_change=(
                    (lambda value: settings_changed("combo_slots", value))
                    if settings_changed is not None
                    else None
                ),
                on_field_change=settings_changed,
            ),
            ExperiencePage(settings, on_change=settings_changed),
            DiagnosticsPage(settings, on_change=settings_changed),
        )
        self.pages = dict(zip(self.page_names, page_widgets, strict=True))
        for index, page_name in enumerate(self.page_names):
            button = QPushButton(page_name, sidebar)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=index: self.show_page(value))
            nav_layout.addWidget(button)
            self._navigation.append(button)

            page = page_widgets[index]
            self.stack.addWidget(page)
        nav_layout.addStretch(1)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(self.stack, 1)

        self.status_label = QLabel("後端尚未連線", central)
        self.status_label.setObjectName("status")
        self.status_label.setMinimumHeight(38)
        root_layout.addWidget(body, 1)
        root_layout.addWidget(self.status_label)
        self.setCentralWidget(central)
        self.show_page(0)

    def show_page(self, page: int | str) -> None:
        index = self.page_names.index(page) if isinstance(page, str) else int(page)
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self._navigation):
            button.setChecked(button_index == index)

    def set_status(self, message: str) -> None:
        if self.status_label.text() != message:
            self.status_label.setText(message)

    def _set_window_interaction_active(self, active: bool) -> None:
        self._window_interaction_active = bool(active)

    def is_window_interaction_active(self) -> bool:
        return bool(self._window_interaction_active)

    def _handle_native_message(self, message_id: int) -> None:
        if message_id == WM_ENTERSIZEMOVE:
            self._set_window_interaction_active(True)
        elif message_id == WM_EXITSIZEMOVE:
            self._set_window_interaction_active(False)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            try:
                message_id = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents.message
                self._handle_native_message(message_id)
            except (TypeError, ValueError, OSError):
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:
        self._set_window_interaction_active(False)
        if not self._shutdown_started:
            self._shutdown_started = True
            if self._shutdown is not None:
                self._shutdown()
        self.closed = True
        event.accept()


__all__ = ["MainWindow"]
