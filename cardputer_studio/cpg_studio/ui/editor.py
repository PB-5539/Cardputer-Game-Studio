"""Code editor widget (line numbers, highlighting, diagnostics) and the tabbed editor area."""
from __future__ import annotations

import posixpath

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFontMetricsF, QPainter, QTextCharFormat, QTextCursor,
                           QTextFormat)
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QTabWidget, QTextEdit, QToolTip, QWidget

from ..core.diagnostics import Diagnostic
from . import theme
from .highlighter import PythonHighlighter

INDENT = "    "


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event):
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, path: str, api_names=(), parent=None):
        super().__init__(parent)
        self.path = path
        self._diagnostics: list[Diagnostic] = []
        self.setFont(theme.monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(4 * QFontMetricsF(self.font()).horizontalAdvance(" "))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._numbers = _LineNumberArea(self)
        self.highlighter = PythonHighlighter(self.document(), api_names) if path.endswith(".py") else None
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_numbers)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self._update_margin()
        self._refresh_selections()

    # ---- line numbers ----------------------------------------------------------------------
    def line_number_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_numbers(self, rect, dy):
        if dy:
            self._numbers.scroll(0, dy)
        else:
            self._numbers.update(0, rect.y(), self._numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._numbers.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self._numbers)
        painter.fillRect(event.rect(), QColor(theme.GUTTER_BG))
        severity_by_line = {}
        for d in self._diagnostics:
            if severity_by_line.get(d.line) != "error":
                severity_by_line[d.line] = d.severity
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        height = self.fontMetrics().height()
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor(theme.FG if number == current else theme.GUTTER_FG))
                painter.drawText(0, top, self._numbers.width() - 8, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
                sev = severity_by_line.get(number + 1)
                if sev:
                    painter.setBrush(QColor(theme.ERROR if sev == "error" else theme.WARNING))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QPoint(6, top + height // 2), 3, 3)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # ---- highlighting current line and diagnostics -------------------------------------------
    def set_diagnostics(self, diagnostics) -> None:
        self._diagnostics = list(diagnostics)
        self._refresh_selections()
        self._numbers.update()

    def _refresh_selections(self):
        selections = []
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(theme.CURRENT_LINE))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)
        doc = self.document()
        for d in self._diagnostics:
            block = doc.findBlockByNumber(d.line - 1)
            if not block.isValid():
                continue
            length = len(block.text())
            start = min(d.col, max(length - 1, 0))
            end = d.end_col if d.end_col > start else length
            end = min(max(end, start + 1), max(length, start + 1))
            sel = QTextEdit.ExtraSelection()
            sel.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            sel.format.setUnderlineColor(QColor(theme.ERROR if d.severity == "error" else theme.WARNING))
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + start)
            cursor.setPosition(min(block.position() + end, block.position() + length), QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            selections.append(sel)
        self.setExtraSelections(selections)
        self._numbers.update()

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip and self._diagnostics:
            line = self.cursorForPosition(e.pos()).blockNumber() + 1
            messages = [d.message for d in self._diagnostics if d.line == line]
            if messages:
                QToolTip.showText(e.globalPos(), "\n".join(messages), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    # ---- editing conveniences -----------------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        cursor = self.textCursor()
        if key == Qt.Key.Key_Tab and not (mods & Qt.KeyboardModifier.ControlModifier):
            if cursor.hasSelection():
                self._shift_lines(indent=True)
            else:
                col = cursor.positionInBlock()
                cursor.insertText(" " * (len(INDENT) - col % len(INDENT)))
            return
        if key == Qt.Key.Key_Backtab:
            self._shift_lines(indent=False)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not cursor.hasSelection():
            before = cursor.block().text()[:cursor.positionInBlock()]
            indent = before[:len(before) - len(before.lstrip(" "))]
            if before.rstrip().endswith(":"):
                indent += INDENT
            super().keyPressEvent(event)
            self.textCursor().insertText(indent)
            return
        super().keyPressEvent(event)

    def _shift_lines(self, indent: bool):
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        if cursor.hasSelection() and doc.findBlock(cursor.selectionEnd()).position() == cursor.selectionEnd() and last > first:
            last -= 1                                  # selection ends at the start of a line: don't touch it
        cursor.beginEditBlock()
        for n in range(first, last + 1):
            block = doc.findBlockByNumber(n)
            c = QTextCursor(block)
            if indent:
                c.insertText(INDENT)
            else:
                text = block.text()
                remove = min(len(INDENT), len(text) - len(text.lstrip(" ")))
                if remove:
                    c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove)
                    c.removeSelectedText()
        cursor.endEditBlock()

    def goto(self, line: int, col: int = 0) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + min(col, max(len(block.text()), 0)))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()


class EditorTabs(QTabWidget):
    """Open files as tabs. The Project is the source of truth: edits are pushed out via text_edited."""

    text_edited = Signal(str, str)        # path, full text
    count_changed = Signal(int)

    def __init__(self, api_names=(), parent=None):
        super().__init__(parent)
        self._api_names = tuple(api_names)
        self._editors: dict[str, CodeEditor] = {}
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._close_index)

    def tabInserted(self, index):
        super().tabInserted(index)
        self.count_changed.emit(self.count())

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self.count_changed.emit(self.count())

    def paths(self) -> list[str]:
        return list(self._editors)

    def current_path(self) -> str | None:
        ed = self.currentWidget()
        return ed.path if isinstance(ed, CodeEditor) else None

    def current_editor(self) -> CodeEditor | None:
        ed = self.currentWidget()
        return ed if isinstance(ed, CodeEditor) else None

    def editor_for(self, path: str) -> CodeEditor | None:
        return self._editors.get(path)

    def open_path(self, path: str, text: str, line: int | None = None, col: int = 0) -> CodeEditor:
        ed = self._editors.get(path)
        if ed is None:
            ed = CodeEditor(path, self._api_names)
            ed.setPlainText(text)
            ed.document().setModified(False)
            ed.textChanged.connect(lambda ed=ed: self.text_edited.emit(ed.path, ed.toPlainText()))
            self._editors[path] = ed
            index = self.addTab(ed, posixpath.basename(path))
            self.setTabToolTip(index, path)
        self.setCurrentWidget(ed)
        if line:
            ed.goto(line, col)
        else:
            ed.setFocus()
        return ed

    def _close_index(self, index):
        ed = self.widget(index)
        if isinstance(ed, CodeEditor):
            self.close_path(ed.path)

    def close_path(self, path: str) -> None:
        ed = self._editors.pop(path, None)
        if ed is not None:
            self.removeTab(self.indexOf(ed))
            ed.deleteLater()

    def close_under(self, prefix: str) -> None:
        for p in [p for p in self._editors if p == prefix or p.startswith(prefix + "/")]:
            self.close_path(p)

    def close_all(self) -> None:
        for p in list(self._editors):
            self.close_path(p)

    def rename_path(self, old: str, new: str) -> None:
        """Follow a file or folder rename in the project."""
        for p in list(self._editors):
            if p == old or p.startswith(old + "/"):
                ed = self._editors.pop(p)
                ed.path = new + p[len(old):]
                self._editors[ed.path] = ed
                index = self.indexOf(ed)
                self.setTabText(index, posixpath.basename(ed.path))
                self.setTabToolTip(index, ed.path)

    def set_diagnostics(self, path: str, diagnostics) -> None:
        ed = self._editors.get(path)
        if ed is not None:
            ed.set_diagnostics(diagnostics)
