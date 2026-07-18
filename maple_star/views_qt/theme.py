APP_STYLESHEET = """
QWidget {
    background: #0f131b;
    color: #e8ecf4;
    font-family: "Microsoft JhengHei UI";
    font-size: 13px;
}
QMainWindow { background: #0b0e14; }
QMenuBar { background: #0b0e14; padding: 4px 8px; }
QMenuBar::item:selected, QMenu::item:selected { background: #263247; }
QMenu { background: #171d29; border: 1px solid #303b50; }
QFrame#sidebar { background: #151a24; border-right: 1px solid #262d3b; }
QLabel#title { font-size: 20px; font-weight: 700; letter-spacing: 1px; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; }
QLabel#cardTitle { font-size: 15px; font-weight: 700; }
QLabel#cardDescription, QLabel#fieldDescription, QLabel#secondaryText { color: #96a1b5; }
QLabel#fieldLabel { color: #dce2ed; }
QFrame#settingsCard {
    background: #171d29;
    border: 1px solid #293348;
    border-radius: 10px;
}
QFrame#settingsCard QWidget, QFrame#settingsCard QLabel { background: transparent; }
QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget > QWidget { background: transparent; }
QPushButton {
    background: #202838;
    border: 1px solid #303b50;
    border-radius: 7px;
    padding: 8px 12px;
    text-align: left;
}
QPushButton:hover { background: #29344a; border-color: #41506c; }
QPushButton:pressed { background: #1c2534; }
QPushButton:checked { background: #2563eb; border-color: #3b82f6; color: white; }
QPushButton#actionButton { text-align: center; background: #263247; }
QPushButton#actionButton:hover { background: #30405b; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0d1118;
    border: 1px solid #38445b;
    border-radius: 6px;
    padding: 6px 8px;
    min-height: 20px;
    selection-background-color: #2f7df4;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #5790ee; }
QComboBox::drop-down { border: 0; width: 24px; }
QTableView {
    background: #0d1118;
    alternate-background-color: #131a25;
    border: 1px solid #303b50;
    border-radius: 7px;
    gridline-color: #273044;
    selection-background-color: #234f91;
}
QHeaderView::section {
    background: #202838;
    color: #dfe5ef;
    border: 0;
    border-right: 1px solid #303b50;
    padding: 7px;
}
QLabel#previewPanel {
    background: #0d1118;
    border: 1px solid #303b50;
    border-radius: 7px;
}
QLabel#status {
    background: #171d29;
    border: 1px solid #2a3446;
    border-radius: 7px;
    padding: 8px 12px;
}
QPlainTextEdit {
    background: #090c12;
    border: 1px solid #293246;
    border-radius: 7px;
    padding: 8px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3b465a; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

__all__ = ["APP_STYLESHEET"]
