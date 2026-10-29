"""Find / replace bar shown above the editor (Ctrl+F, Ctrl+H)."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget

from ..core import search
from ..core.search import SearchError, SearchOptions
from . import theme


class _Field(QLineEdit):
    next_requested = Signal()
    prev_requested = Signal()
    escape_pressed = Signal()
    replace_all_requested = Signal()

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & Qt.KeyboardModifier.ControlModifier and mods & Qt.KeyboardModifier.AltModifier:
                self.replace_all_requested.emit()
            elif mods & Qt.KeyboardModifier.ShiftModifier:
                self.prev_requested.emit()
            else:
                self.next_requested.emit()
            return
        if key == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


def _toggle(text: str, tip: str) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(True)
    b.setStyleSheet("QToolButton:checked { background: %s; border-color: %s; }" % (theme.SELECTION, theme.ACCENT))
    return b


class FindBar(QWidget):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editor = None
        self._matches: list = []
        self._current = None
        self.setStyleSheet("FindBar { background: #1c1c1c; border-bottom: 1px solid %s; }" % theme.BORDER)

        self.find_field = _Field()
        self.find_field.setPlaceholderText("Find")
        self.replace_field = _Field()
        self.replace_field.setPlaceholderText("Replace")
        self.btn_case = _toggle("Aa", "Match case")
        self.btn_word = _toggle("ab", "Whole word")
        self.btn_regex = _toggle(".*", "Regular expression (replacement can use \\1)")
        self.count_label = QLabel("")
        self.count_label.setMinimumWidth(90)
        self.btn_prev = QToolButton()
        self.btn_prev.setText("↑")
        self.btn_prev.setToolTip("Previous match (Shift+Enter)")
        self.btn_next = QToolButton()
        self.btn_next.setText("↓")
        self.btn_next.setToolTip("Next match (Enter)")
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("Close (Esc)")
        self.btn_replace = QToolButton()
        self.btn_replace.setText("Replace")
        self.btn_replace_all = QToolButton()
        self.btn_replace_all.setText("Replace All")
        self.btn_replace_all.setToolTip("Replace all (Ctrl+Alt+Enter)")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        for w in (self.find_field, self.btn_case, self.btn_word, self.btn_regex, self.count_label,
                  self.btn_prev, self.btn_next, self.btn_close):
            top.addWidget(w)
        self.replace_row = QWidget()
        bottom = QHBoxLayout(self.replace_row)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.replace_field, 1)
        bottom.addWidget(self.btn_replace)
        bottom.addWidget(self.btn_replace_all)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self.replace_row)
        self.replace_row.hide()
        self.hide()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        self.find_field.textChanged.connect(lambda: self.refresh(jump=True))
        for b in (self.btn_case, self.btn_word, self.btn_regex):
            b.toggled.connect(lambda checked=False: self.refresh(jump=True))
        self.find_field.next_requested.connect(self.find_next)
        self.find_field.prev_requested.connect(self.find_prev)
        self.replace_field.next_requested.connect(self.replace_current)
        self.replace_field.prev_requested.connect(self.find_prev)
        self.find_field.escape_pressed.connect(self.close_bar)
        self.replace_field.escape_pressed.connect(self.close_bar)
        self.find_field.replace_all_requested.connect(self.replace_all)
        self.replace_field.replace_all_requested.connect(self.replace_all)
        self.btn_next.clicked.connect(lambda checked=False: self.find_next())
        self.btn_prev.clicked.connect(lambda checked=False: self.find_prev())
        self.btn_close.clicked.connect(lambda checked=False: self.close_bar())
        self.btn_replace.clicked.connect(lambda checked=False: self.replace_current())
        self.btn_replace_all.clicked.connect(lambda checked=False: self.replace_all())

    # ---- state --------------------------------------------------------------------------------
    def options(self) -> SearchOptions:
        return SearchOptions(self.btn_case.isChecked(), self.btn_word.isChecked(), self.btn_regex.isChecked())

    def set_editor(self, editor) -> None:
        """Follow the active editor tab (None when no file is open)."""
        if self._editor is editor:
            return
        if self._editor is not None:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except (RuntimeError, TypeError):
                pass
            self._editor.set_search_highlights([], None)
        self._editor = editor
        if editor is not None:
            editor.textChanged.connect(self._on_text_changed)
        if self.isVisible():
            self.refresh()

    def _on_text_changed(self):
        self._timer.start()

    def show_find(self, replace: bool = False) -> None:
        if self._editor is None:
            return
        seed = self._editor.search_seed()
        if seed and "\n" not in seed and not (seed.isspace()):
            self.find_field.setText(seed)
        self.replace_row.setVisible(replace)
        self.show()
        (self.replace_field if replace and self.find_field.text() else self.find_field).setFocus()
        if not replace:
            self.find_field.selectAll()
        self.refresh()

    def close_bar(self) -> None:
        self.hide()
        if self._editor is not None:
            self._editor.set_search_highlights([], None)
            self._editor.setFocus()
        self.closed.emit()

    # ---- searching ----------------------------------------------------------------------------
    def refresh(self, jump: bool = False) -> None:
        ed = self._editor
        self._matches, self._current = [], None
        query = self.find_field.text()
        error = ""
        if ed is not None and query:
            try:
                self._matches = search.find_all(ed.toPlainText(), query, self.options())
            except SearchError as e:
                error = str(e)
        if ed is not None and self._matches:
            start, end = ed.selection_range()
            self._current = search.index_at(self._matches, start, end)
            if self._current is None:
                self._current = search.next_index(self._matches, start)
                if jump and self._current is not None:
                    self._select(self._current)
        self.find_field.setStyleSheet("border: 1px solid %s;" % theme.ERROR if (error or (query and not self._matches)) else "")
        if error:
            self.count_label.setText("Invalid regex")
            self.count_label.setToolTip(error)
        elif not query:
            self.count_label.setText("")
        elif not self._matches:
            self.count_label.setText("No results")
        else:
            shown = (self._current + 1) if self._current is not None else "?"
            more = "+" if len(self._matches) >= search.MAX_MATCHES else ""
            self.count_label.setText("%s of %d%s" % (shown, len(self._matches), more))
        if ed is not None:
            ed.set_search_highlights(self._matches, self._current)

    def _select(self, index: int) -> None:
        start, end = self._matches[index]
        self._current = index
        self._editor.select_range(start, end)
        self.count_label.setText("%d of %d" % (index + 1, len(self._matches)))
        self._editor.set_search_highlights(self._matches, index)

    def find_next(self) -> None:
        if self._editor is None:
            return
        self.refresh()
        if not self._matches:
            return
        start, end = self._editor.selection_range()
        exact = search.index_at(self._matches, start, end)
        target = (exact + 1) % len(self._matches) if exact is not None else search.next_index(self._matches, end)
        self._select(target)

    def find_prev(self) -> None:
        if self._editor is None:
            return
        self.refresh()
        if not self._matches:
            return
        start, end = self._editor.selection_range()
        self._select(search.prev_index(self._matches, start))

    # ---- replacing ----------------------------------------------------------------------------
    def replace_current(self) -> None:
        ed = self._editor
        if ed is None or not self.find_field.text():
            return
        start, end = ed.selection_range()
        try:
            new = search.replace_one(ed.toPlainText(), start, end, self.find_field.text(),
                                     self.replace_field.text(), self.options())
        except SearchError as e:
            self.count_label.setText("Invalid replacement")
            self.count_label.setToolTip(str(e))
            return
        if new is None:                         # nothing selected that matches: just go to the next one
            self.find_next()
            return
        ed.apply_edits([(start, end, new)])
        ed.select_range(start + len(new), start + len(new))
        self.refresh()
        self.find_next()

    def replace_all(self) -> None:
        ed = self._editor
        if ed is None or not self.find_field.text():
            return
        try:
            edits = search.replace_edits(ed.toPlainText(), self.find_field.text(),
                                         self.replace_field.text(), self.options())
        except SearchError as e:
            self.count_label.setText("Invalid replacement")
            self.count_label.setToolTip(str(e))
            return
        ed.apply_edits(edits)
        self.refresh()
        self.count_label.setText("Replaced %d" % len(edits))
