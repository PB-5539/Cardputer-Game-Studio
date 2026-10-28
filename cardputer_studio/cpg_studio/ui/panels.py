"""Right-hand tools (docs, problems, runtime stats) and the bottom console."""
from __future__ import annotations

import re
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QFormLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget)

from ..runtime import api_docs
from . import theme

_LOCATION = re.compile(r'File "([^"]+)", line (\d+)')


class DocsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the engine docs…")
        self.search.setClearButtonEnabled(True)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.document().setDefaultStyleSheet(
            f"h2 {{ color: {theme.ACCENT}; }} h3 {{ color: {theme.SYNTAX['api']}; }} "
            f"pre {{ background-color: #1c1c1c; color: {theme.FG}; }} code {{ color: {theme.SYNTAX['string']}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.search)
        layout.addWidget(self.view, 1)
        self.search.textChanged.connect(self._render)
        self._render("")

    def _render(self, query: str) -> None:
        self.view.setHtml(api_docs.to_html(query))


class ProblemsPanel(QListWidget):
    jump_requested = Signal(str, int, int)        # path, line, col
    counts_changed = Signal(int, int)             # errors, warnings

    def __init__(self, parent=None):
        super().__init__(parent)
        self._by_path: dict[str, list] = {}
        self.itemActivated.connect(self._activated)

    def set_diagnostics(self, path: str, diagnostics) -> None:
        if diagnostics:
            self._by_path[path] = list(diagnostics)
        else:
            self._by_path.pop(path, None)
        self._rebuild()

    def forget_path(self, prefix: str) -> None:
        for p in [p for p in self._by_path if p == prefix or p.startswith(prefix + "/")]:
            del self._by_path[p]
        self._rebuild()

    def rename_path(self, old: str, new: str) -> None:
        moved = {}
        for p, diags in self._by_path.items():
            if p == old or p.startswith(old + "/"):
                moved[new + p[len(old):]] = [replace(d, path=new + p[len(old):]) for d in diags]
            else:
                moved[p] = diags
        self._by_path = moved
        self._rebuild()

    def clear_all(self) -> None:
        self._by_path.clear()
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear()
        errors = warnings = 0
        for path in sorted(self._by_path):
            for d in self._by_path[path]:
                mark = "●" if d.severity == "error" else "▲"
                item = QListWidgetItem(f"{mark} {path}:{d.line}:{d.col + 1}   {d.message}")
                item.setForeground(QColor(theme.ERROR if d.severity == "error" else theme.WARNING))
                item.setData(Qt.ItemDataRole.UserRole, (path, d.line, d.col))
                self.addItem(item)
                if d.severity == "error":
                    errors += 1
                else:
                    warnings += 1
        self.counts_changed.emit(errors, warnings)

    def _activated(self, item):
        path, line, col = item.data(Qt.ItemDataRole.UserRole)
        self.jump_requested.emit(path, line, col)


class RuntimePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(10, 10, 10, 10)
        self._labels = {}
        for key, title in (("status", "Status"), ("entry", "Entry file"), ("target", "Target FPS"),
                           ("fps", "Measured FPS"), ("frame", "Game time per frame"), ("frames", "Frames")):
            label = QLabel("–")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._labels[key] = label
            form.addRow(title, label)
        note = QLabel("Frame time measures only your update() and draw(); "
                      "the Cardputer itself will be slower than this PC.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        form.addRow(note)

    def set_status(self, status: str, entry: str | None = None) -> None:
        self._labels["status"].setText(status)
        if entry is not None:
            self._labels["entry"].setText(entry)

    def reset_stats(self) -> None:
        for key in ("target", "fps", "frame", "frames"):
            self._labels[key].setText("–")

    def update_stats(self, info: dict) -> None:
        self._labels["target"].setText(str(info.get("target_fps", "–")))
        self._labels["fps"].setText(str(info.get("fps", "–")))
        self._labels["frame"].setText("%s ms" % info.get("frame_ms", "–"))
        self._labels["frames"].setText(str(info.get("frames", "–")))


class ConsolePanel(QPlainTextEdit):
    """Program output, engine messages and errors. Double-click a traceback line to jump to it."""

    jump_requested = Signal(str, int)

    COLORS = {"out": theme.FG, "error": theme.ERROR, "info": theme.ACCENT, "warn": theme.WARNING}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(theme.monospace_font(10))
        self.setMaximumBlockCount(5000)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def append_text(self, text: str, kind: str = "out") -> None:
        if not text:
            return
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.COLORS.get(kind, theme.FG)))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Copy", self.copy)
        menu.addAction("Select All", self.selectAll)
        menu.addSeparator()
        menu.addAction("Clear", self.clear)
        menu.exec(self.viewport().mapToGlobal(pos))

    def mouseDoubleClickEvent(self, event):
        line = self.cursorForPosition(event.pos()).block().text()
        m = _LOCATION.search(line)
        if m:
            self.jump_requested.emit(m.group(1).replace("\\", "/"), int(m.group(2)))
            return
        super().mouseDoubleClickEvent(event)
