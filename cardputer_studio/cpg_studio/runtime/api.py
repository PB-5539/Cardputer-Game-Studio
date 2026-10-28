"""The Cardputer engine API: the functions and constants games use.

This is the PC preview implementation. Every public name listed in __all__ is injected into
Python's builtins while a game runs, so games call clear(), rect(), key_down(), ... with no
imports. The same names are what the Cardputer firmware build will provide, so a game written
against them should behave the same in both places.

Names starting with an underscore are for the runner, not for games.
"""
from __future__ import annotations

import math
import threading
import time as _time

from .framebuf_sim import FrameBuffer

WIDTH = 240
HEIGHT = 135
FONT_W = 8
FONT_H = 8
MIN_FPS, MAX_FPS = 1, 60


def rgb(r, g, b):
    """Pack 0-255 red/green/blue values into the 16-bit RGB565 colour the display uses."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


BLACK = rgb(0, 0, 0)
WHITE = rgb(255, 255, 255)
RED = rgb(255, 0, 0)
GREEN = rgb(0, 255, 0)
BLUE = rgb(0, 0, 255)
YELLOW = rgb(255, 255, 0)
CYAN = rgb(0, 255, 255)
MAGENTA = rgb(255, 0, 255)
ORANGE = rgb(255, 140, 0)
GRAY = rgb(128, 128, 128)


class _State:
    def __init__(self):
        self.fb = FrameBuffer(WIDTH, HEIGHT)
        self.lock = threading.Lock()
        self.held: set[str] = set()          # keys currently down (updated from the IDE)
        self.taps: set[str] = set()          # keys pressed since the last poll (even if already released)
        self.down: frozenset[str] = frozenset()
        self.pressed: frozenset[str] = frozenset()
        self.released: frozenset[str] = frozenset()
        self.fps = 30
        self.running = True
        self.t0 = _time.monotonic()
        self.on_beep = None


_s = _State()


def _reset():
    global _s
    _s = _State()


def _key_event(down: bool, name: str) -> None:
    """Called by the runner when the IDE reports a key going down or up."""
    name = name.strip().lower()
    if not name:
        return
    with _s.lock:
        if down:
            if name not in _s.held:
                _s.held.add(name)
                _s.taps.add(name)
        else:
            _s.held.discard(name)


def _poll_keys() -> None:
    """Latch input once per frame so key_down/key_pressed/key_released are stable within it."""
    with _s.lock:
        held, taps = set(_s.held), _s.taps
        _s.taps = set()
    prev = _s.down
    down = frozenset(held | taps)
    _s.pressed = frozenset((down - prev) | taps)
    _s.released = frozenset(prev - down)
    _s.down = down


def _frame_bytes() -> bytes:
    return bytes(_s.fb.buf)


def _i(v):
    """Coordinates may be floats; they round down, like the device runtime."""
    return v if isinstance(v, int) else int(math.floor(v))


# ---- display -------------------------------------------------------------------------------
def clear(color=BLACK):
    _s.fb.fill(_i(color))


def pixel(x, y, color=WHITE):
    _s.fb.pixel(_i(x), _i(y), _i(color))


def line(x0, y0, x1, y1, color=WHITE):
    _s.fb.line(_i(x0), _i(y0), _i(x1), _i(y1), _i(color))


def rect(x, y, w, h, color=WHITE, fill=False):
    _s.fb.rect(_i(x), _i(y), _i(w), _i(h), _i(color), bool(fill))


def circle(cx, cy, r, color=WHITE, fill=False):
    _s.fb.circle(_i(cx), _i(cy), _i(r), _i(color), bool(fill))


def text(s, x, y, color=WHITE):
    _s.fb.text(str(s), _i(x), _i(y), _i(color))


# ---- input ---------------------------------------------------------------------------------
def key_down(name):
    return str(name).lower() in _s.down


def key_pressed(name):
    return str(name).lower() in _s.pressed


def key_released(name):
    return str(name).lower() in _s.released


def keys_down():
    return sorted(_s.down)


def keys_pressed():
    return sorted(_s.pressed)


# ---- timing, sound, control ----------------------------------------------------------------
def set_fps(fps):
    _s.fps = max(MIN_FPS, min(MAX_FPS, int(fps)))


def time_ms():
    return int((_time.monotonic() - _s.t0) * 1000)


def beep(freq=880, ms=100):
    cb = _s.on_beep
    if cb:
        cb(int(freq), int(ms))


def quit():
    _s.running = False


__all__ = [
    "WIDTH", "HEIGHT", "FONT_W", "FONT_H",
    "rgb", "BLACK", "WHITE", "RED", "GREEN", "BLUE", "YELLOW", "CYAN", "MAGENTA", "ORANGE", "GRAY",
    "clear", "pixel", "line", "rect", "circle", "text",
    "key_down", "key_pressed", "key_released", "keys_down", "keys_pressed",
    "set_fps", "time_ms", "beep", "quit",
]

_MISSING = object()
_saved_builtins: dict = {}


def inject_builtins():
    """Make every engine name visible to game code without an import."""
    import builtins
    g = globals()
    for name in __all__:
        _saved_builtins.setdefault(name, getattr(builtins, name, _MISSING))
        setattr(builtins, name, g[name])


def remove_builtins():
    import builtins
    for name, old in _saved_builtins.items():
        if old is _MISSING:
            if hasattr(builtins, name):
                delattr(builtins, name)
        else:
            setattr(builtins, name, old)
    _saved_builtins.clear()
