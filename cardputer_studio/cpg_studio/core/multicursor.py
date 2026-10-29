"""Geometry for multiple cursors and column selection (no Qt, so it can be tested).

Columns here are *visual* columns: a tab advances to the next multiple of `tab`, every other
character is one column wide (the editor uses a monospace font). Indexes are character offsets
within a line.
"""
from __future__ import annotations

TAB = 4


def index_to_vcol(text: str, index: int, tab: int = TAB) -> int:
    col = 0
    for ch in text[:index]:
        col += tab - col % tab if ch == "\t" else 1
    return col


def vcol_to_index(text: str, vcol: int, tab: int = TAB) -> int:
    """Character index nearest to visual column `vcol`; past the end of the line it's len(text)."""
    col = 0
    for i, ch in enumerate(text):
        if col >= vcol:
            return i
        width = tab - col % tab if ch == "\t" else 1
        if col + width > vcol:                      # `vcol` falls inside a tab: pick the nearer edge
            return i if vcol - col < col + width - vcol else i + 1
        col += width
    return len(text)


def column_spans(lines, anchor, current, tab: int = TAB):
    """Per-line selections for a rectangular (column) selection.

    anchor, current: (line, visual column). Returns [(line, start_index, end_index), ...] from the
    top line to the bottom one. Lines shorter than the box get a zero-width caret at their end.
    """
    (l1, v1), (l2, v2) = anchor, current
    top, bottom = sorted((l1, l2))
    top, bottom = max(top, 0), min(bottom, len(lines) - 1)
    left, right = sorted((v1, v2))
    return [(n, vcol_to_index(lines[n], left, tab), vcol_to_index(lines[n], right, tab))
            for n in range(top, bottom + 1)]


def vertical_target(lines, line: int, index: int, delta: int, tab: int = TAB):
    """(line, index) one line up/down from (line, index) keeping the visual column, or None."""
    new = line + delta
    if not 0 <= new < len(lines):
        return None
    return new, vcol_to_index(lines[new], index_to_vcol(lines[line], index, tab), tab)


def _touch(a, b) -> bool:
    (s1, e1), (s2, e2) = a, b
    if s1 == e1 or s2 == e2:                        # a caret touches anything it sits on or at the edge of
        return s2 <= s1 <= e2 if s1 == e1 else s1 <= s2 <= e1
    return s1 < e2 and s2 < e1                      # two selections must really overlap


def keep_indices(ranges):
    """Indices of `ranges` ((start, end) pairs, highest priority first) to keep once duplicate
    and overlapping carets/selections are merged away."""
    kept = []
    for i, r in enumerate(ranges):
        if not any(_touch(r, ranges[j]) for j in kept):
            kept.append(i)
    return kept


def distribute_paste(text: str, count: int):
    """VS Code behaviour: if the clipboard has exactly one line per cursor, give each its own line;
    otherwise every cursor gets the whole text. Returns a list of `count` strings."""
    lines = text.split("\n")
    if count > 1 and len(lines) == count:
        return lines
    if count > 1 and len(lines) == count + 1 and lines[-1] == "":
        return lines[:-1]                           # trailing newline from copying whole lines
    return [text] * count
