"""Dark, high-contrast look for the whole app."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# editor / syntax colours
BG = "#0a0a0a"
FG = "#ffffff"
GUTTER_BG = "#101010"
GUTTER_FG = "#8a8a8a"
CURRENT_LINE = "#1a1a1a"
SELECTION = "#264f78"
FIND_MATCH = "#5a4a12"
FIND_CURRENT = "#9a6a00"
PANEL_BG = "#141414"
BORDER = "#3a3a3a"
ACCENT = "#3794ff"
ERROR = "#f14c4c"
WARNING = "#e5c07b"
MUTED = "#9a9a9a"

SYNTAX = {
    "keyword": "#569cd6",
    "constant": "#569cd6",
    "variable": "#7eecff",
    "builtin": "#4ec9b0",
    "api": "#c586c0",          # engine functions stand out from ordinary builtins
    "string": "#ce9178",
    "comment": "#7ca668",
    "number": "#b5cea8",
    "decorator": "#dcdcaa",
    "definition": "#dcdcaa",
    "self": "#9cdcfe",
}

STYLE = f"""
QMainWindow, QDialog {{ background: {PANEL_BG}; }}
QToolTip {{ background: #202020; color: {FG}; border: 1px solid {BORDER}; }}
QDockWidget {{ color: {FG}; }}
QDockWidget::title {{
    background: #1c1c1c; padding: 5px 8px; border-bottom: 1px solid {BORDER};
}}
QMenuBar, QMenu {{ background: #1c1c1c; color: {FG}; }}
QMenu::item:selected, QMenuBar::item:selected {{ background: {SELECTION}; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{
    background: #1c1c1c; color: {MUTED}; padding: 6px 12px; border-right: 1px solid {BORDER};
}}
QTabBar::tab:selected {{ background: {BG}; color: {FG}; border-top: 2px solid {ACCENT}; }}
QPlainTextEdit, QTextBrowser, QTreeWidget, QListWidget, QLineEdit {{
    background: {BG}; color: {FG}; border: 0; selection-background-color: {SELECTION};
}}
QLineEdit {{ border: 1px solid {BORDER}; padding: 3px 6px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {SELECTION}; }}
QToolBar {{ background: #1c1c1c; border: 0; spacing: 4px; padding: 2px; }}
QToolButton {{ color: {FG}; padding: 3px 8px; border: 1px solid transparent; border-radius: 3px; }}
QToolButton:hover {{ border-color: {BORDER}; background: #262626; }}
QToolButton:disabled {{ color: #666; }}
QStatusBar {{ background: #007acc; color: white; }}
QLabel {{ color: {FG}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, PANEL_BG), (QPalette.ColorRole.WindowText, FG),
        (QPalette.ColorRole.Base, BG), (QPalette.ColorRole.AlternateBase, "#1a1a1a"),
        (QPalette.ColorRole.Text, FG), (QPalette.ColorRole.Button, "#1c1c1c"),
        (QPalette.ColorRole.ButtonText, FG), (QPalette.ColorRole.Highlight, SELECTION),
        (QPalette.ColorRole.HighlightedText, FG), (QPalette.ColorRole.ToolTipBase, "#202020"),
        (QPalette.ColorRole.ToolTipText, FG), (QPalette.ColorRole.PlaceholderText, MUTED),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


def monospace_font(size: int = 11) -> QFont:
    font = QFont()
    font.setFamilies(["Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New", "monospace"])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(size)
    return font
