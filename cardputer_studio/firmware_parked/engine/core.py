"""Game loop and drawing helpers. Runs on MicroPython; also importable on CPython for tests.

Colors are RGB565 with the two bytes swapped, because the display wants big-endian
pixels while framebuf stores them little-endian. Always build colors with rgb().
"""
import time

try:
    _ticks_ms, _ticks_diff, _sleep_ms = time.ticks_ms, time.ticks_diff, time.sleep_ms
except AttributeError:  # CPython
    def _ticks_ms():
        return int(time.monotonic() * 1000)

    def _ticks_diff(a, b):
        return a - b

    def _sleep_ms(ms):
        time.sleep(ms / 1000)


def rgb(r, g, b):
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8)


BLACK = 0
WHITE = 0xFFFF
RED = rgb(255, 0, 0)
GREEN = rgb(0, 255, 0)
BLUE = rgb(0, 0, 255)
YELLOW = rgb(255, 255, 0)


class Game:
    """Subclass this in your game package's __init__.py."""

    def setup(self, e):
        pass

    def update(self, e, dt):    # dt = seconds since last frame
        pass

    def draw(self, e):
        pass


class Engine:
    W = 240
    H = 135

    def __init__(self, hal, fps=30):
        self.hal = hal
        self.fps = fps
        self.canvas = hal.canvas
        self.running = True
        self.down = set()       # keys held this frame
        self.pressed = set()    # keys that went down this frame

    # --- input ---
    def key_down(self, k):
        return k in self.down

    def key_pressed(self, k):
        return k in self.pressed

    def _poll(self):
        now = self.hal.poll_keys()
        self.pressed = now - self.down
        self.down = now

    # --- drawing ---
    def clear(self, color=BLACK):
        self.canvas.fill(color)

    def rect(self, x, y, w, h, color, fill=True):
        if fill:
            self.canvas.fill_rect(x, y, w, h, color)
        else:
            self.canvas.rect(x, y, w, h, color)

    def line(self, x0, y0, x1, y1, color):
        self.canvas.line(x0, y0, x1, y1, color)

    def text(self, s, x, y, color=WHITE):
        self.canvas.text(s, x, y, color)    # built-in 8x8 font

    def quit(self):
        self.running = False


def run(game, hal=None, fps=30):
    if hal is None:
        from .hal_cardputer import CardputerHAL
        hal = CardputerHAL()
    e = Engine(hal, fps)
    game.setup(e)
    frame_ms = 1000 // fps
    last = _ticks_ms()
    while e.running:
        start = _ticks_ms()
        dt = _ticks_diff(start, last) / 1000
        last = start
        e._poll()
        game.update(e, dt)
        game.draw(e)
        hal.show()
        spent = _ticks_diff(_ticks_ms(), start)
        if spent < frame_ms:
            _sleep_ms(frame_ms - spent)
