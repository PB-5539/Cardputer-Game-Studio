"""Cardputer key names and how PC keys map onto them in the preview (no Qt needed to test)."""
from __future__ import annotations

_LETTERS = tuple("abcdefghijklmnopqrstuvwxyz")
_DIGITS = tuple("0123456789")
_PUNCT = ("-", "=", "[", "]", "\\", ";", "'", ",", ".", "/", "`")
_SPECIAL = ("space", "enter", "backspace", "tab", "esc", "shift", "ctrl", "alt", "fn", "opt")
_ARROWS = ("up", "down", "left", "right")

KEY_NAMES = _LETTERS + _DIGITS + _PUNCT + _SPECIAL + _ARROWS

# Qt::Key integer values -> key name. Numbers are used so this module doesn't import Qt.
QT_KEY_TO_NAME: dict[int, str] = {}
for _i, _c in enumerate(_LETTERS):
    QT_KEY_TO_NAME[0x41 + _i] = _c                   # Key_A .. Key_Z
for _i, _c in enumerate(_DIGITS):
    QT_KEY_TO_NAME[0x30 + _i] = _c                   # Key_0 .. Key_9
QT_KEY_TO_NAME.update({
    0x20: "space",
    0x01000000: "esc", 0x01000001: "tab", 0x01000003: "backspace",
    0x01000004: "enter", 0x01000005: "enter",        # Return, numpad Enter
    0x01000020: "shift", 0x01000021: "ctrl", 0x01000023: "alt",
    0x01000030: "fn", 0x01000031: "opt",             # F1, F2 stand in for Fn and Opt
    0x01000012: "left", 0x01000013: "up", 0x01000014: "right", 0x01000015: "down",
    # punctuation (Qt uses the ASCII code of the unshifted character)
    0x2D: "-", 0x3D: "=", 0x5B: "[", 0x5D: "]", 0x5C: "\\", 0x3B: ";", 0x27: "'",
    0x2C: ",", 0x2E: ".", 0x2F: "/", 0x60: "`",
    # shifted variants (US layout) report a different Qt key; fold them back so press and
    # release always agree even if Shift changes in between
    0x21: "1", 0x40: "2", 0x23: "3", 0x24: "4", 0x25: "5", 0x5E: "6", 0x26: "7", 0x2A: "8",
    0x28: "9", 0x29: "0", 0x5F: "-", 0x2B: "=", 0x7B: "[", 0x7D: "]", 0x7C: "\\", 0x3A: ";",
    0x22: "'", 0x3C: ",", 0x3E: ".", 0x3F: "/", 0x7E: "`",
})


def name_from_qt_key(key: int) -> str | None:
    """Engine key name for a Qt key code, or None if that PC key has no Cardputer equivalent."""
    return QT_KEY_TO_NAME.get(int(key))
