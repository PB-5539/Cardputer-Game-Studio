"""Software RGB565 framebuffer that mimics the Cardputer's display (pure Python, no deps).

Pixels are stored little-endian, 2 bytes each, row after row - exactly what Qt's
QImage.Format_RGB16 expects on the little-endian machines this runs on. Every drawing call is
clipped to the screen, so games can draw partly off-screen safely.
"""
from __future__ import annotations

import struct

from .font8x8 import glyph

_U16 = struct.Struct("<H")


class FrameBuffer:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.buf = bytearray(width * height * 2)

    # ---- primitives ----------------------------------------------------------------------
    def fill(self, color: int) -> None:
        self.buf[:] = _U16.pack(color & 0xFFFF) * (self.width * self.height)

    def pixel(self, x: int, y: int, color: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            _U16.pack_into(self.buf, (y * self.width + x) * 2, color & 0xFFFF)

    def get_pixel(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return _U16.unpack_from(self.buf, (y * self.width + x) * 2)[0]
        return 0

    def hline(self, x: int, y: int, length: int, color: int) -> None:
        if length <= 0 or not 0 <= y < self.height:
            return
        x0, x1 = max(x, 0), min(x + length, self.width)
        if x1 > x0:
            start = (y * self.width + x0) * 2
            self.buf[start:start + (x1 - x0) * 2] = _U16.pack(color & 0xFFFF) * (x1 - x0)

    def fill_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        if w <= 0 or h <= 0:
            return
        x0, x1 = max(x, 0), min(x + w, self.width)
        y0, y1 = max(y, 0), min(y + h, self.height)
        if x1 <= x0 or y1 <= y0:
            return
        row = _U16.pack(color & 0xFFFF) * (x1 - x0)
        n = len(row)
        for yy in range(y0, y1):
            start = (yy * self.width + x0) * 2
            self.buf[start:start + n] = row

    def rect(self, x: int, y: int, w: int, h: int, color: int, fill: bool = False) -> None:
        if w <= 0 or h <= 0:
            return
        if fill:
            self.fill_rect(x, y, w, h, color)
            return
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        for yy in range(max(y + 1, 0), min(y + h - 1, self.height)):
            self.pixel(x, yy, color)
            self.pixel(x + w - 1, yy, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: int) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def circle(self, cx: int, cy: int, r: int, color: int, fill: bool = False) -> None:
        if r < 0:
            return
        if r == 0:
            self.pixel(cx, cy, color)
            return
        x, y, err = r, 0, 1 - r
        while x >= y:
            if fill:
                self.hline(cx - x, cy + y, 2 * x + 1, color)
                self.hline(cx - x, cy - y, 2 * x + 1, color)
                self.hline(cx - y, cy + x, 2 * y + 1, color)
                self.hline(cx - y, cy - x, 2 * y + 1, color)
            else:
                for px, py in ((x, y), (y, x), (-x, y), (-y, x), (x, -y), (y, -x), (-x, -y), (-y, -x)):
                    self.pixel(cx + px, cy + py, color)
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def text(self, s: str, x: int, y: int, color: int) -> None:
        packed = _U16.pack(color & 0xFFFF)
        for i, ch in enumerate(s):
            cx = x + i * 8
            if cx >= self.width or cx + 8 <= 0:
                continue
            for row, bits in enumerate(glyph(ch)):
                py = y + row
                if not bits or not 0 <= py < self.height:
                    continue
                for col in range(8):
                    if bits >> col & 1:
                        px = cx + col
                        if 0 <= px < self.width:
                            self.buf[(py * self.width + px) * 2:(py * self.width + px) * 2 + 2] = packed
