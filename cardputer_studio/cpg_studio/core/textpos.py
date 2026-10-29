"""Convert between Python string indexes (code points) and Qt text positions (UTF-16 units).

They only differ for characters outside the Basic Multilingual Plane (emoji and the like), so for
plain text both functions are the identity.
"""
from __future__ import annotations


def qt_len(s: str) -> int:
    """Length of `s` in UTF-16 code units."""
    if s.isascii():
        return len(s)
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in s)


def qt_pos(text: str, index: int) -> int:
    """Qt position of the character at Python `index` of `text`."""
    return index if text.isascii() else qt_len(text[:index])


def py_index(text: str, pos: int) -> int:
    """Python index for the Qt position `pos` in `text`."""
    if text.isascii():
        return min(pos, len(text))
    units = 0
    for i, ch in enumerate(text):
        if units >= pos:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)
