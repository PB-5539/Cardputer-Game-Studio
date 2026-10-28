"""Qt glue for the pure scanner in core/syntax.py."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..core import syntax
from . import theme


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document, api_names=()):
        super().__init__(document)
        self._api = frozenset(api_names)
        self._formats = {}
        for kind in syntax.KINDS:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(theme.SYNTAX[kind]))
            if kind == "comment":
                fmt.setFontItalic(True)
            if kind in ("keyword", "definition"):
                fmt.setFontWeight(QFont.Weight.DemiBold)
            self._formats[kind] = fmt

    def highlightBlock(self, text):
        state = max(self.previousBlockState(), 0)       # Qt uses -1 for "no previous state"
        spans, new_state = syntax.highlight_line(text, state, self._api)
        for start, length, kind in spans:
            self.setFormat(start, length, self._formats[kind])
        self.setCurrentBlockState(new_state)
