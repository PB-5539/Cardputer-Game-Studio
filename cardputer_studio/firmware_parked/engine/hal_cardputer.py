"""Cardputer hardware layer: ST7789 display + keyboard matrix.

UNTESTED ON HARDWARE. Pins, panel offsets and the keyboard wiring below are written from
memory of the Cardputer schematic; check CFG/KB_* against the schematic before trusting
them. Run the `keytest` game to see raw key names, then fill in KEYMAP.
"""
import framebuf
import time
from machine import Pin, SPI

W, H = 240, 135

CFG = {
    "sck": 36, "mosi": 35, "dc": 34, "cs": 37, "rst": 33, "bl": 38,
    "xoff": 40, "yoff": 53,     # ST7789 135x240 panel offsets in landscape
    "madctl": 0x70,             # rotation / color order
    "baud": 40000000,
}
KB_SEL = (8, 9, 11)             # 74HC138 address lines (A0, A1, A2)
KB_IN = (13, 15, 3, 4, 5, 6, 7)  # 7 column inputs

# raw name ("s<select>i<input>") -> key name your games use, e.g. {"s0i0": "left"}
KEYMAP = {}


class CardputerHAL:
    def __init__(self):
        c = CFG
        self.spi = SPI(2, baudrate=c["baud"], polarity=0, phase=0,
                       sck=Pin(c["sck"]), mosi=Pin(c["mosi"]))
        self.dc = Pin(c["dc"], Pin.OUT)
        self.cs = Pin(c["cs"], Pin.OUT, value=1)
        self.rst = Pin(c["rst"], Pin.OUT, value=1)
        self.bl = Pin(c["bl"], Pin.OUT, value=1)
        self.buf = bytearray(W * H * 2)
        self.canvas = framebuf.FrameBuffer(self.buf, W, H, framebuf.RGB565)
        self.sel = [Pin(p, Pin.OUT, value=0) for p in KB_SEL]
        self.inp = [Pin(p, Pin.IN, Pin.PULL_UP) for p in KB_IN]
        self._init_display()

    def _cmd(self, cmd, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((cmd,)))
        if data is not None:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _init_display(self):
        self.rst(0)
        time.sleep_ms(20)
        self.rst(1)
        time.sleep_ms(120)
        self._cmd(0x01)                         # software reset
        time.sleep_ms(150)
        self._cmd(0x11)                         # sleep out
        time.sleep_ms(120)
        self._cmd(0x3A, b"\x55")                # 16-bit color
        self._cmd(0x36, bytes((CFG["madctl"],)))
        self._cmd(0x21)                         # inversion on (IPS panel)
        self._cmd(0x13)                         # normal mode
        self._cmd(0x29)                         # display on
        time.sleep_ms(20)

    def show(self):
        x0, y0 = CFG["xoff"], CFG["yoff"]
        x1, y1 = x0 + W - 1, y0 + H - 1
        self._cmd(0x2A, bytes((x0 >> 8, x0 & 255, x1 >> 8, x1 & 255)))
        self._cmd(0x2B, bytes((y0 >> 8, y0 & 255, y1 >> 8, y1 & 255)))
        self._cmd(0x2C, self.buf)

    def poll_keys(self):
        """Return the set of key names currently held (active-low matrix assumed)."""
        down = set()
        for s in range(8):
            for bit in range(3):
                self.sel[bit](s >> bit & 1)
            for i, pin in enumerate(self.inp):
                if not pin():
                    raw = "s%di%d" % (s, i)
                    down.add(KEYMAP.get(raw, raw))
        return down
