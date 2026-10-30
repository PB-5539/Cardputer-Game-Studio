"""Code editor widget (line numbers, highlighting, diagnostics, autocomplete, hover, multiple
cursors) and the tabbed editor area."""
from __future__ import annotations

import html
import posixpath

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFontMetricsF, QGuiApplication, QKeySequence, QPainter, QStandardItem,
                           QStandardItemModel, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import (QCompleter, QFrame, QPlainTextEdit, QTabWidget, QTextEdit, QToolTip, QWidget)

from ..core import multicursor as mc
from ..core import textpos
from ..core.diagnostics import Diagnostic
from . import theme
from .highlighter import PythonHighlighter

INDENT = "    "
MAX_SEARCH_HIGHLIGHTS = 2000
_KIND_COLOR = {"local": "variable", "project": "definition", "engine": "api", "member": "self",
               "builtin": "builtin", "keyword": "keyword"}


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event):
        self._editor.paint_line_numbers(event)


class _BlockLines:
    """Read-only list-of-lines view of a QTextDocument (so we never copy the whole text)."""

    def __init__(self, doc):
        self.doc = doc

    def __len__(self):
        return self.doc.blockCount()

    def __getitem__(self, n):
        return self.doc.findBlockByNumber(n).text()


class CodeEditor(QPlainTextEdit):
    def __init__(self, path: str, api_names=(), parent=None):
        super().__init__(parent)
        self.path = path
        self.completion_provider = None     # (path, text, offset) -> (replace_len, [Completion])
        self.hover_provider = None          # (path, text, line, col) -> html | None
        self._diagnostics: list[Diagnostic] = []
        self._extra: list[QTextCursor] = []         # additional cursors (the primary is textCursor())
        self._col_anchor = None                     # (line, visual column) while column-dragging
        self._search: list = []                     # [(qt_start, qt_end)]
        self._search_current = None
        self._completion_len = 0
        self.setFont(theme.monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(4 * QFontMetricsF(self.font()).horizontalAdvance(" "))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._numbers = _LineNumberArea(self)
        self.highlighter = PythonHighlighter(self.document(), api_names) if path.endswith(".py") else None
        self._make_completer()
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

    # ---- highlighting: current line, search matches, diagnostics, extra cursors ----------------
    def set_diagnostics(self, diagnostics) -> None:
        self._diagnostics = list(diagnostics)
        self._refresh_selections()
        self._numbers.update()

    def set_search_highlights(self, ranges, current=None) -> None:
        """Highlight matches. `ranges` are (start, end) Python string indexes; `current` indexes into it."""
        text = self.toPlainText()
        self._search = [(textpos.qt_pos(text, s), textpos.qt_pos(text, e)) for s, e in ranges]
        self._search_current = current
        self._refresh_selections()

    def _range_selection(self, start, end, color):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(color))
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cursor
        return sel

    def _refresh_selections(self):
        selections = []
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(theme.CURRENT_LINE))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)
        for i, (s, e) in enumerate(self._search[:MAX_SEARCH_HIGHLIGHTS]):
            selections.append(self._range_selection(
                s, e, theme.FIND_CURRENT if i == self._search_current else theme.FIND_MATCH))
        if self._search_current is not None and self._search_current >= MAX_SEARCH_HIGHLIGHTS:
            s, e = self._search[self._search_current]
            selections.append(self._range_selection(s, e, theme.FIND_CURRENT))
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
        for c in self._extra:
            if c.hasSelection():
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor(theme.SELECTION))
                sel.cursor = c
                selections.append(sel)
        self.setExtraSelections(selections)
        self._numbers.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._extra:
            return
        painter = QPainter(self.viewport())
        for c in self._extra:                                   # carets of the additional cursors
            r = self.cursorRect(c)
            if r.intersects(event.rect()):
                painter.fillRect(r.x(), r.y(), 2, r.height(), QColor(theme.FG))

    # ---- hover: diagnostics plus symbol info with its call tree ----------------------------------
    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            self._show_hover(e)
            return True
        return super().event(e)

    def _show_hover(self, e):
        cursor = self.cursorForPosition(e.pos())
        char_width = QFontMetricsF(self.font()).horizontalAdvance(" ")
        if abs(e.pos().x() - self.cursorRect(cursor).x()) > char_width * 1.5:
            QToolTip.hideText()                                 # pointer is past the end of the line
            return
        line = cursor.blockNumber()
        parts = []
        messages = [d.message for d in self._diagnostics if d.line == line + 1]
        if messages:
            parts.append("<div style='color:%s'>%s</div>" % (
                theme.ERROR, "<br>".join(html.escape(m, quote=False) for m in messages)))
        if self.hover_provider is not None and self.path.endswith(".py"):
            col = textpos.py_index(cursor.block().text(), cursor.positionInBlock())
            try:
                info = self.hover_provider(self.path, self.toPlainText(), line, col)
            except Exception:                                   # never let hover break the editor
                info = None
            if info:
                parts.append(info)
        if parts:
            QToolTip.showText(e.globalPos(), "<div>%s</div>" % "".join(parts), self)
        else:
            QToolTip.hideText()

    # ---- autocomplete ----------------------------------------------------------------------------
    def _make_completer(self):
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setModel(self._model)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionRole(Qt.ItemDataRole.UserRole)
        self._completer.setMaxVisibleItems(12)
        self._completer.popup().setFont(theme.monospace_font(10))
        self._completer.popup().setStyleSheet(
            "QListView { background: #1c1c1c; color: %s; border: 1px solid %s; "
            "selection-background-color: %s; }" % (theme.FG, theme.BORDER, theme.SELECTION))
        self._completer.activated[str].connect(self._insert_completion)

    def completion_visible(self) -> bool:
        return self._completer.popup().isVisible()

    def hide_completion(self) -> None:
        self._completer.popup().hide()

    def trigger_completion(self) -> None:
        """Ctrl+Space."""
        self._update_completion()

    def _update_completion(self) -> None:
        cursor = self.textCursor()
        if (self.completion_provider is None or self._extra or cursor.hasSelection()
                or not self.path.endswith(".py")):
            self.hide_completion()
            return
        text = self.toPlainText()
        offset = textpos.py_index(text, cursor.position())
        try:
            replace_len, items = self.completion_provider(self.path, text, offset)
        except Exception:
            replace_len, items = 0, []
        if not items:
            self.hide_completion()
            return
        prefix = text[offset - replace_len:offset]
        self._completion_len = textpos.qt_len(prefix)
        self._model.clear()
        for it in items:
            item = QStandardItem("%s    %s" % (it.name, it.detail[:70]) if it.detail else it.name)
            item.setData(it.name, Qt.ItemDataRole.UserRole)
            item.setForeground(QColor(theme.SYNTAX[_KIND_COLOR.get(it.kind, "variable")]))
            self._model.appendRow(item)
        self._completer.setCompletionPrefix(prefix)
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.moveLeft(rect.left() - round(QFontMetricsF(self.font()).horizontalAdvance(prefix)))
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 8)
        self._completer.complete(rect)

    def _insert_completion(self, name: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, self._completion_len)
        cursor.insertText(name)
        self.setTextCursor(cursor)

    # ---- multiple cursors ------------------------------------------------------------------------
    def cursor_count(self) -> int:
        return 1 + len(self._extra)

    def _cursors(self):
        return [self.textCursor()] + list(self._extra)

    def _commit(self, cursors) -> None:
        """Make cursors[0] the primary cursor and the rest the extras, dropping duplicates/overlaps."""
        keep = mc.keep_indices([(c.selectionStart(), c.selectionEnd()) for c in cursors])
        cursors = [cursors[i] for i in keep]
        self._extra = cursors[1:]
        self.setTextCursor(cursors[0])
        self._refresh_selections()
        self.viewport().update()

    def clear_extra_cursors(self) -> None:
        if self._extra:
            self._extra = []
            self._refresh_selections()
            self.viewport().update()

    def _edit_all(self, fn) -> None:
        """Run fn(cursor, index) on every cursor as one undo step, last position first."""
        cursors = self._cursors()
        order = sorted(range(len(cursors)), key=lambda i: cursors[i].selectionStart(), reverse=True)
        cursors[0].beginEditBlock()
        for i in order:
            fn(cursors[i], i)
        cursors[0].endEditBlock()
        self._commit(cursors)

    def _move_all(self, key, mods) -> None:
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        mode = QTextCursor.MoveMode.KeepAnchor if shift else QTextCursor.MoveMode.MoveAnchor
        Move = QTextCursor.MoveOperation
        cursors = self._cursors()
        for c in cursors:
            if key == Qt.Key.Key_Left:
                if c.hasSelection() and not shift:
                    c.setPosition(c.selectionStart())
                else:
                    c.movePosition(Move.WordLeft if ctrl else Move.Left, mode)
            elif key == Qt.Key.Key_Right:
                if c.hasSelection() and not shift:
                    c.setPosition(c.selectionEnd())
                else:
                    c.movePosition(Move.NextWord if ctrl else Move.Right, mode)
            elif key == Qt.Key.Key_Up:
                c.movePosition(Move.Up, mode)
            elif key == Qt.Key.Key_Down:
                c.movePosition(Move.Down, mode)
            elif key == Qt.Key.Key_Home:
                if ctrl:
                    c.movePosition(Move.StartOfBlock, mode)
                else:
                    text = c.block().text()
                    first = len(text) - len(text.lstrip())
                    target = first if c.positionInBlock() != first else 0     # smart Home
                    c.setPosition(c.block().position() + target, mode)
            elif key == Qt.Key.Key_End:
                c.movePosition(Move.EndOfBlock, mode)
        self._commit(cursors)

    def _newline(self, cursor, _i=0) -> None:
        before = cursor.block().text()[:cursor.positionInBlock()]
        indent = before[:len(before) - len(before.lstrip(" "))]
        if before.rstrip().endswith(":"):
            indent += INDENT
        cursor.insertText("\n" + indent)

    def _multi_key(self, event) -> bool:
        """Key handling while there are several cursors. Returns True if the key was used."""
        key, mods = event.key(), event.modifiers()
        Key = Qt.Key
        if key == Key.Key_Escape:
            self.clear_extra_cursors()
            return True
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
            return True
        if event.matches(QKeySequence.StandardKey.Cut):
            self.cut()
            return True
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
            return True
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.clear_extra_cursors()
            return False
        if key == Key.Key_Backspace:
            self._edit_all(lambda c, i: c.removeSelectedText() if c.hasSelection() else c.deletePreviousChar())
            return True
        if key == Key.Key_Delete:
            self._edit_all(lambda c, i: c.removeSelectedText() if c.hasSelection() else c.deleteChar())
            return True
        if key in (Key.Key_Return, Key.Key_Enter):
            self._edit_all(self._newline)
            return True
        if key == Key.Key_Tab and not (mods & Qt.KeyboardModifier.ControlModifier):
            def tab(c, i):
                if c.hasSelection():
                    self._shift_lines(True, c)
                else:
                    c.insertText(" " * (len(INDENT) - c.positionInBlock() % len(INDENT)))
            self._edit_all(tab)
            return True
        if key == Key.Key_Backtab:
            self._edit_all(lambda c, i: self._shift_lines(False, c))
            return True
        if (key in (Key.Key_Left, Key.Key_Right, Key.Key_Up, Key.Key_Down, Key.Key_Home, Key.Key_End)
                and not (mods & Qt.KeyboardModifier.AltModifier)):
            self._move_all(key, mods)
            return True
        text = event.text()
        if text and text.isprintable() and not (mods & (Qt.KeyboardModifier.ControlModifier
                                                        | Qt.KeyboardModifier.MetaModifier)):
            self._edit_all(lambda c, i: c.insertText(text))
            return True
        return False

    def copy(self):
        if not self._extra:
            super().copy()
            return
        cursors = sorted(self._cursors(), key=lambda c: c.selectionStart())
        parts = [c.selectedText().replace(" ", "\n") for c in cursors]
        if not any(parts):                                       # only carets: copy their lines
            parts = [c.block().text() for c in cursors]
        QGuiApplication.clipboard().setText("\n".join(parts))

    def cut(self):
        if not self._extra:
            super().cut()
            return
        self.copy()
        self._edit_all(lambda c, i: c.removeSelectedText())

    def paste(self):
        if not self._extra:
            super().paste()
            return
        clip = QGuiApplication.clipboard().text().replace("\r\n", "\n")
        cursors = self._cursors()
        pieces = mc.distribute_paste(clip, len(cursors))
        rank = {i: r for r, i in enumerate(sorted(range(len(cursors)), key=lambda i: cursors[i].selectionStart()))}
        self._edit_all(lambda c, i: c.insertText(pieces[rank[i]]))

    def add_cursor_vertically(self, delta: int) -> None:
        """Ctrl+Alt+Up / Down: add a cursor on the line above the top / below the bottom cursor."""
        cursors = self._cursors()
        edge = min(cursors, key=lambda c: c.position()) if delta < 0 else max(cursors, key=lambda c: c.position())
        lines = _BlockLines(self.document())
        target = mc.vertical_target(lines, edge.blockNumber(), edge.positionInBlock(), delta)
        if target is None:
            return
        line, index = target
        block = self.document().findBlockByNumber(line)
        new = QTextCursor(block)
        new.setPosition(block.position() + textpos.qt_pos(block.text(), index))
        self._commit(cursors + [new])

    def add_cursor_above(self) -> None:
        self.add_cursor_vertically(-1)

    def add_cursor_below(self) -> None:
        self.add_cursor_vertically(1)

    def select_next_occurrence(self) -> None:
        """Ctrl+D: select the word under the cursor, then add the next occurrence each time."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            self.setTextCursor(cursor)
            return
        needle = cursor.selectedText()
        if not needle or " " in needle:
            return
        cursors = self._cursors()
        start_from = max(c.selectionEnd() for c in cursors)
        flags = QTextDocument.FindFlag.FindCaseSensitively
        found = self.document().find(needle, start_from, flags)
        if found.isNull():
            found = self.document().find(needle, 0, flags)
        if found.isNull():
            return
        if (found.selectionStart(), found.selectionEnd()) in {(c.selectionStart(), c.selectionEnd()) for c in cursors}:
            return
        self._commit([found] + cursors)

    def _add_cursor_at(self, point) -> None:
        self._commit([self.cursorForPosition(point)] + self._cursors())

    def _pos_to_line_vcol(self, point):
        cursor = self.cursorForPosition(point)
        width = QFontMetricsF(self.font()).horizontalAdvance(" ")
        x = point.x() - self.contentOffset().x() - self.document().documentMargin()
        return cursor.blockNumber(), max(0, round(x / width))

    def _column_update(self, point) -> None:
        line, vcol = self._pos_to_line_vcol(point)
        doc = self.document()
        spans = mc.column_spans(_BlockLines(doc), self._col_anchor, (line, vcol))
        cursors = []
        for n, s, e in spans:
            block = doc.findBlockByNumber(n)
            text = block.text()
            c = QTextCursor(block)
            c.setPosition(block.position() + textpos.qt_pos(text, s))
            c.setPosition(block.position() + textpos.qt_pos(text, e), QTextCursor.MoveMode.KeepAnchor)
            cursors.append((n, c))
        if not cursors:
            return
        cursors.sort(key=lambda t: t[0] != line)                # the line under the mouse is the primary
        self._commit([c for _n, c in cursors])

    # ---- mouse ------------------------------------------------------------------------------------
    def mousePressEvent(self, event):
        button, mods = event.button(), event.modifiers()
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        point = event.position().toPoint()
        if button == Qt.MouseButton.MiddleButton or (button == Qt.MouseButton.LeftButton and alt and shift):
            self.hide_completion()
            self._col_anchor = self._pos_to_line_vcol(point)    # middle-drag: column / multi-line selection
            self._column_update(point)
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton and alt:
            self._add_cursor_at(point)                          # Alt+click adds a cursor
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton:
            self.clear_extra_cursors()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._col_anchor is not None:
            self._column_update(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._col_anchor is not None:
            self._col_anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---- editing conveniences -----------------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()
        if self.completion_visible() and key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape,
                                                 Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            event.ignore()                                      # the popup takes these
            return
        if self._extra and self._multi_key(event):
            return
        if key == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.trigger_completion()
            return
        if key == Qt.Key.Key_Escape and not self.completion_visible():
            self.clear_extra_cursors()
        self._handle_key(event)
        text = event.text()
        typed_word = bool(text) and (text.isalnum() or text in "_.")
        if self.completion_visible() or typed_word or key == Qt.Key.Key_Backspace:
            if typed_word or (self.completion_visible() and key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)):
                self._update_completion()
            else:
                self.hide_completion()

    def _handle_key(self, event):
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

    def _shift_lines(self, indent: bool, cursor=None):
        cursor = cursor or self.textCursor()
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

    # ---- helpers for the find bar and the main window ----------------------------------------------
    def goto(self, line: int, col: int = 0) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + min(col, max(len(block.text()), 0)))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def select_range(self, start: int, end: int) -> None:
        """Select the Python-string-index range [start, end) and scroll it into view."""
        self.clear_extra_cursors()
        text = self.toPlainText()
        cursor = self.textCursor()
        cursor.setPosition(textpos.qt_pos(text, start))
        cursor.setPosition(textpos.qt_pos(text, end), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def selection_range(self):
        """Current selection as Python string indexes (start, end), both equal when there is none."""
        text = self.toPlainText()
        c = self.textCursor()
        return textpos.py_index(text, c.selectionStart()), textpos.py_index(text, c.selectionEnd())

    def apply_edits(self, edits) -> None:
        """Apply [(start, end, new_text)] (Python indexes into the current text) as one undo step."""
        if not edits:
            return
        self.clear_extra_cursors()
        text = self.toPlainText()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for start, end, new in sorted(edits, reverse=True):
            cursor.setPosition(textpos.qt_pos(text, start))
            cursor.setPosition(textpos.qt_pos(text, end), QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(new)
        cursor.endEditBlock()

    def search_seed(self) -> str:
        """Text to pre-fill the find box with: the selection, or else the word under the cursor."""
        c = self.textCursor()
        if c.hasSelection():
            s = c.selectedText()
            return "" if " " in s else s
        c.select(QTextCursor.SelectionType.WordUnderCursor)
        return c.selectedText()


class EditorTabs(QTabWidget):
    """Open files as tabs. The Project is the source of truth: edits are pushed out via text_edited."""

    text_edited = Signal(str, str)        # path, full text
    count_changed = Signal(int)

    def __init__(self, api_names=(), parent=None):
        super().__init__(parent)
        self._api_names = tuple(api_names)
        self._editors: dict[str, CodeEditor] = {}
        self._completion_provider = None
        self._hover_provider = None
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._close_index)

    def set_providers(self, completion=None, hover=None) -> None:
        """Callbacks that feed autocomplete and hover (see CodeEditor); applied to every editor."""
        self._completion_provider = completion
        self._hover_provider = hover
        for ed in self._editors.values():
            ed.completion_provider = completion
            ed.hover_provider = hover

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
            ed.completion_provider = self._completion_provider
            ed.hover_provider = self._hover_provider
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

    def open_asset(self, path: str, make_widget) -> QWidget:
        """Open a non-text editor (sprite, tilemap, sound) as a tab; make_widget() builds it once."""
        ed = self._editors.get(path)
        if ed is None:
            ed = make_widget()
            self._editors[path] = ed
            index = self.addTab(ed, posixpath.basename(path))
            self.setTabToolTip(index, path)
        self.setCurrentWidget(ed)
        return ed

    def _close_index(self, index):
        ed = self.widget(index)
        if getattr(ed, "path", None) in self._editors:
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
        if isinstance(ed, CodeEditor):
            ed.set_diagnostics(diagnostics)
