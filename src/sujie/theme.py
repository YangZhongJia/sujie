"""Shared light desktop theme for the PySide6 interface."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

COLORS = {
    "canvas": "#F5F5F7",
    "surface": "#FFFFFF",
    "text": "#1D1D1F",
    "secondary": "#6E6E73",
    "line": "#D2D2D7",
    "accent": "#0066CC",
}

_STYLESHEET = r"""
QDialog, QMessageBox, QInputDialog {
    background: #F5F5F7;
    color: #1D1D1F;
}
QLabel { color: #1D1D1F; }
QLabel[role="title"] { font-size: 21pt; font-weight: 600; }
QLabel[role="sectionTitle"] { font-size: 16pt; font-weight: 600; }
QLabel[role="subtitle"], QLabel[role="hint"], QLabel[role="status"] {
    color: #6E6E73;
}
QLabel[role="subtitle"] { font-size: 10pt; }
QLabel[role="hint"] { font-size: 9pt; }
QLabel[role="status"] { padding: 5px 0; }

QPushButton {
    min-height: 34px;
    padding: 0 14px;
    color: #1D1D1F;
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
}
QPushButton:hover { background: #F0F0F2; }
QPushButton:pressed { background: #E5E5EA; }
QPushButton:disabled { color: #A1A1A6; background: #F5F5F7; }
QPushButton:focus { border: 2px solid #0066CC; }
QPushButton[primary="true"] {
    color: #FFFFFF;
    background: #0066CC;
    border-color: #0066CC;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: #0056B3; }
QPushButton[primary="true"]:pressed { background: #004A99; }
QPushButton[tool="true"] { min-width: 52px; padding: 0 11px; }
QPushButton[tool="true"]:checked {
    color: #0066CC;
    background: #E8F2FF;
    border-color: #A8CCF7;
}
QPushButton[destructive="true"] { color: #D70015; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 34px;
    padding: 3px 10px;
    color: #1D1D1F;
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    selection-background-color: #0066CC;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid #0066CC;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: #8E8E93;
    background: #F0F0F2;
}
QComboBox::drop-down { width: 28px; border: none; }
QComboBox QAbstractItemView {
    color: #1D1D1F;
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    selection-background-color: #E8F2FF;
    selection-color: #1D1D1F;
    outline: 0;
}

QListWidget {
    color: #1D1D1F;
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 10px;
    outline: 0;
    padding: 4px;
}
QListWidget::item { min-height: 34px; padding: 6px 9px; border-radius: 7px; }
QListWidget::item:hover { background: #F5F5F7; }
QListWidget::item:selected { color: #1D1D1F; background: #E8F2FF; }
QListWidget#settingsNavigation {
    background: transparent;
    border: none;
    padding: 0;
}
QListWidget#settingsNavigation::item { min-height: 36px; padding-left: 12px; }

QCheckBox { spacing: 8px; color: #1D1D1F; }
QTabWidget#settingsPages::pane { border: none; background: transparent; }
QScrollArea { border: none; background: transparent; }
QRadioButton { spacing: 9px; color: #1D1D1F; }
QFrame#modeOption {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 11px;
}
QFrame#modeOption[selected="true"] {
    background: #F7FAFF;
    border: 2px solid #0066CC;
}

QMenu {
    color: #1D1D1F;
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    padding: 5px;
}
QMenu::item { min-height: 28px; padding: 5px 28px 5px 10px; border-radius: 6px; }
QMenu::item:selected { color: #1D1D1F; background: #E8F2FF; }
QMenu::separator { height: 1px; background: #E5E5EA; margin: 5px 8px; }
QToolTip {
    color: #FFFFFF;
    background: #2C2C2E;
    border: none;
    padding: 6px 8px;
}
QScrollBar:vertical { width: 9px; margin: 3px 1px; background: transparent; }
QScrollBar::handle:vertical { min-height: 28px; background: #C7C7CC; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def apply_theme(app) -> None:
    """Apply a consistent Windows-native light palette and control style."""
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Segoe UI"])
    font.setPointSize(10)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(COLORS["canvas"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["canvas"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(COLORS["surface"]))
    palette.setColor(QPalette.PlaceholderText, QColor(COLORS["secondary"]))
    app.setPalette(palette)
    app.setStyleSheet(_STYLESHEET)
