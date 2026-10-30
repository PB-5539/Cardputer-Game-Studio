"""An editable RGBA image plus the drawing operations the sprite editor needs (no Qt, testable)."""
from __future__ import annotations

from ..runtime import png

TRANSPARENT = (0, 0, 0, 0)
MAX_SIZE = 1024


class PixelImage:
    def __init__(self, w: int, h: int, data: bytes | bytearray | None = None):
        if not (1 <= w <= MAX_SIZE and 1 <= h <= MAX_SIZE):
            raise ValueError("image size must be 1 to %d pixels each way" % MAX_SIZE)
        self.w, self.h = w, h
        self.data = bytearray(data) if data is not None else bytearray(w * h * 4)
        if len(self.data) != w * h * 4:
            raise ValueError("pixel data has the wrong size")

    # ---- construction / conversion ---------------------------------------------------------
    @classmethod
    def from_png(cls, data: bytes) -> "PixelImage":
        w, h, rows = png.decode(data)
        return cls(w, h, b"".join(rows))

    def to_png(self) -> bytes:
        return png.encode(self.w, self.h, bytes(self.data))

    def copy(self) -> "PixelImage":
        return PixelImage(self.w, self.h, self.data)

    # ---- pixels ----------------------------------------------------------------------------
    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x: int, y: int):
        i = (y * self.w + x) * 4
        return tuple(self.data[i:i + 4])

    def set(self, x: int, y: int, color) -> None:
        if self.inside(x, y):
            i = (y * self.w + x) * 4
            self.data[i:i + 4] = bytes(color)

    def stamp(self, x: int, y: int, color, size: int = 1) -> None:
        """A square brush of `size` pixels centred (as far as possible) on x, y."""
        off = (size - 1) // 2
        for yy in range(y - off, y - off + size):
            for xx in range(x - off, x - off + size):
                self.set(xx, yy, color)

    # ---- shapes ----------------------------------------------------------------------------
    def line(self, x0, y0, x1, y1, color, size: int = 1) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.stamp(x0, y0, color, size)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def rect(self, x0, y0, x1, y1, color, fill: bool = False) -> None:
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        for y in range(max(top, 0), min(bottom, self.h - 1) + 1):
            for x in range(max(left, 0), min(right, self.w - 1) + 1):
                if fill or x in (left, right) or y in (top, bottom):
                    self.set(x, y, color)

    def ellipse(self, x0, y0, x1, y1, color, fill: bool = False) -> None:
        """Ellipse inscribed in the box between the two corners."""
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = (right - left) / 2 + 0.5, (bottom - top) / 2 + 0.5

        def in_ellipse(x, y):
            return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0

        for y in range(max(top, 0), min(bottom, self.h - 1) + 1):
            for x in range(max(left, 0), min(right, self.w - 1) + 1):
                if in_ellipse(x, y) and (fill or not (in_ellipse(x - 1, y) and in_ellipse(x + 1, y)
                                                      and in_ellipse(x, y - 1) and in_ellipse(x, y + 1))):
                    self.set(x, y, color)

    def flood_fill(self, x: int, y: int, color) -> int:
        """Fill the connected region of same-coloured pixels; returns how many pixels changed."""
        if not self.inside(x, y):
            return 0

        def norm(c):
            return TRANSPARENT if c[3] == 0 else tuple(c)

        target, color = norm(self.get(x, y)), tuple(color)
        if target == norm(color):
            return 0
        stack, count = [(x, y)], 0
        while stack:
            px, py = stack.pop()
            if not self.inside(px, py) or norm(self.get(px, py)) != target:
                continue
            self.set(px, py, color)
            count += 1
            stack += [(px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)]
        return count

    # ---- whole-image operations ----------------------------------------------------------------
    def resized(self, w: int, h: int) -> "PixelImage":
        """A w x h image with this one's pixels kept at the top-left (new area is transparent)."""
        out = PixelImage(w, h)
        for y in range(min(h, self.h)):
            n = min(w, self.w) * 4
            out.data[y * w * 4:y * w * 4 + n] = self.data[y * self.w * 4:y * self.w * 4 + n]
        return out

    def flipped(self, horizontal: bool) -> "PixelImage":
        out = PixelImage(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                out.set(self.w - 1 - x if horizontal else x, y if horizontal else self.h - 1 - y, self.get(x, y))
        return out

    def shifted(self, dx: int, dy: int) -> "PixelImage":
        """Move everything by (dx, dy), wrapping around the edges."""
        out = PixelImage(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                out.set((x + dx) % self.w, (y + dy) % self.h, self.get(x, y))
        return out

    def clear(self) -> None:
        self.data[:] = bytes(len(self.data))

    def replace_data(self, other: "PixelImage") -> None:
        self.w, self.h, self.data = other.w, other.h, bytearray(other.data)


class History:
    """Undo/redo of whole-document snapshots (images are small, so snapshots are cheap)."""

    def __init__(self, limit: int = 100):
        self.limit = limit
        self._undo: list = []
        self._redo: list = []

    def record(self, state) -> None:
        """Call with the state from *before* a change."""
        self._undo.append(state)
        del self._undo[:-self.limit]
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, current):
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current):
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
