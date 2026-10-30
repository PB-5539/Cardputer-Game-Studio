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

from . import assets
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
        self.on_audio = None                 # callback(op, sound_or_None, **options); set by the runner
        self.cache: dict = {}                # loaded sprites / tilemaps / sounds by path


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
    _audio("tone", None, freq=int(freq), ms=int(ms))


# ---- sprites and tilemaps ----------------------------------------------------------------------
def _cached(kind, key, make):
    full = (kind,) + key
    value = _s.cache.get(full)
    if value is None:
        value = _s.cache[full] = make()
    return value


def load_sprite(path, frame_w=None, frame_h=None):
    """Load a PNG as a Sprite (or a sheet of frames when frame_w and frame_h are given)."""
    path = str(path).replace("\\", "/")
    return _cached("sprite", (path, frame_w, frame_h), lambda: assets.load_sprite_file(path, frame_w, frame_h))


def draw_sprite(spr, x, y, frame=0, flip_x=False, flip_y=False):
    """Draw one frame of a Sprite with its top-left corner at (x, y)."""
    if not isinstance(spr, assets.Sprite):
        raise TypeError("draw_sprite needs a Sprite from load_sprite(), got %s" % type(spr).__name__)
    _s.fb.blit_runs(spr.runs(frame, flip_x, flip_y), _i(x), _i(y))


def load_tilemap(path):
    """Load a tilemap .json file (made in the tilemap editor) as a Tilemap."""
    path = str(path).replace("\\", "/")

    def make():
        text = assets.read_file(path, "tilemap").decode("utf-8", "replace")
        return assets.tilemap_from_json(text, lambda name, tw, th: load_sprite(name, tw, th), path)
    return _cached("tilemap", (path,), make)


def draw_tilemap(tm, cam_x=0, cam_y=0, layer=None):
    """Draw the part of a Tilemap the camera sees (cam_x, cam_y = map pixel at the screen's top-left)."""
    if not isinstance(tm, assets.Tilemap):
        raise TypeError("draw_tilemap needs a Tilemap from load_tilemap(), got %s" % type(tm).__name__)
    tm.draw(_s.fb, _i(cam_x), _i(cam_y), layer)


# ---- sound -------------------------------------------------------------------------------------
def load_sound(path):
    """Load a .wav file or a tone-sequence .json file as a Sound."""
    path = str(path).replace("\\", "/")
    return _cached("sound", (path,), lambda: assets.load_sound_file(path))


def tones(song, wave="square", volume=0.5):
    """Make a Sound from text like "C4:200 E4:200 G4:400" (note:milliseconds, "rest" for silence)."""
    return assets.parse_note_string(str(song), "", wave, volume)


def _audio(op, snd=None, **options):
    cb = _s.on_audio
    if cb:
        cb(op, snd, options)


def play_sound(snd, loop=False, volume=1.0):
    """Play a Sound (from load_sound or notes). Several sounds can play at once."""
    if not isinstance(snd, assets.Sound):
        raise TypeError("play_sound needs a Sound from load_sound() or tones(), got %s" % type(snd).__name__)
    _audio("play", snd, loop=bool(loop), volume=max(0.0, min(1.0, float(volume))))


def stop_sound(snd=None):
    """Stop one Sound, or everything that is playing when called with no argument."""
    _audio("stop", snd)


def quit():
    _s.running = False


__all__ = [
    "WIDTH", "HEIGHT", "FONT_W", "FONT_H",
    "rgb", "BLACK", "WHITE", "RED", "GREEN", "BLUE", "YELLOW", "CYAN", "MAGENTA", "ORANGE", "GRAY",
    "clear", "pixel", "line", "rect", "circle", "text",
    "key_down", "key_pressed", "key_released", "keys_down", "keys_pressed",
    "load_sprite", "draw_sprite", "load_tilemap", "draw_tilemap",
    "load_sound", "tones", "play_sound", "stop_sound",
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
