"""The tilemap editor's document model: layers of tile numbers, plus JSON in and out (no Qt)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

MAX_TILES = 100_000


class TilemapFormatError(ValueError):
    pass


@dataclass
class Layer:
    name: str
    data: list
    visible: bool = True


@dataclass
class TilemapDoc:
    tileset: str = ""
    tile_w: int = 8
    tile_h: int = 8
    w: int = 30
    h: int = 17
    layers: list = field(default_factory=list)
    solid: set = field(default_factory=set)

    # ---- creation / copying ------------------------------------------------------------------
    @classmethod
    def new(cls, tileset: str, tile_w: int, tile_h: int, w: int, h: int) -> "TilemapDoc":
        if not (1 <= w and 1 <= h and w * h <= MAX_TILES and tile_w >= 1 and tile_h >= 1):
            raise TilemapFormatError("map or tile size is out of range")
        return cls(tileset, tile_w, tile_h, w, h, [Layer("ground", [-1] * (w * h))], set())

    def snapshot(self):
        return (self.tileset, self.tile_w, self.tile_h, self.w, self.h,
                [(layer.name, list(layer.data), layer.visible) for layer in self.layers], sorted(self.solid))

    def restore(self, snap) -> None:
        self.tileset, self.tile_w, self.tile_h, self.w, self.h, layers, solid = snap
        self.layers = [Layer(n, list(d), v) for n, d, v in layers]
        self.solid = set(solid)

    # ---- JSON --------------------------------------------------------------------------------
    @classmethod
    def from_json(cls, text: str) -> "TilemapDoc":
        try:
            d = json.loads(text)
            tw, th, w, h = d["tile_w"], d["tile_h"], d["width"], d["height"]
            ints = (tw, th, w, h)
            if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in ints) or w * h > MAX_TILES:
                raise ValueError
            layers = []
            for i, layer in enumerate(d["layers"]):
                data = layer["data"]
                if len(data) != w * h or not all(isinstance(n, int) for n in data):
                    raise ValueError
                layers.append(Layer(str(layer.get("name", "layer%d" % (i + 1))), list(data)))
            if not layers:
                raise ValueError
            solid = {int(n) for n in d.get("solid", [])}
            return cls(str(d.get("tileset", "")), tw, th, w, h, layers, solid)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise TilemapFormatError("this file is not a valid tilemap (see the Tilemaps section of the docs)") from None

    def to_json(self) -> str:
        """JSON with one row of tiles per line, so version control diffs stay readable."""
        out = ["{",
               '  "version": 1,',
               '  "tileset": %s,' % json.dumps(self.tileset),
               '  "tile_w": %d,' % self.tile_w,
               '  "tile_h": %d,' % self.tile_h,
               '  "width": %d,' % self.w,
               '  "height": %d,' % self.h,
               '  "solid": %s,' % json.dumps(sorted(self.solid)),
               '  "layers": [']
        for li, layer in enumerate(self.layers):
            rows = ["      " + ", ".join(str(n) for n in layer.data[y * self.w:(y + 1) * self.w]) for y in range(self.h)]
            out.append('    {"name": %s, "data": [\n%s\n    ]}%s' % (
                json.dumps(layer.name), ",\n".join(rows), "," if li < len(self.layers) - 1 else ""))
        out += ["  ]", "}", ""]
        return "\n".join(out)

    # ---- tiles -------------------------------------------------------------------------------
    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, layer: int, x: int, y: int) -> int:
        return self.layers[layer].data[y * self.w + x] if self.inside(x, y) else -1

    def set(self, layer: int, x: int, y: int, tile: int) -> bool:
        if not self.inside(x, y):
            return False
        data = self.layers[layer].data
        if data[y * self.w + x] == tile:
            return False
        data[y * self.w + x] = tile
        return True

    def fill_rect(self, layer: int, x0: int, y0: int, x1: int, y1: int, tile: int) -> int:
        changed = 0
        for y in range(max(min(y0, y1), 0), min(max(y0, y1), self.h - 1) + 1):
            for x in range(max(min(x0, x1), 0), min(max(x0, x1), self.w - 1) + 1):
                changed += self.set(layer, x, y, tile)
        return changed

    def flood_fill(self, layer: int, x: int, y: int, tile: int) -> int:
        if not self.inside(x, y):
            return 0
        target = self.get(layer, x, y)
        if target == tile:
            return 0
        stack, count = [(x, y)], 0
        while stack:
            px, py = stack.pop()
            if self.inside(px, py) and self.get(layer, px, py) == target:
                self.set(layer, px, py, tile)
                count += 1
                stack += [(px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)]
        return count

    def resize(self, w: int, h: int) -> None:
        """Change the map size, keeping tiles at the top-left; new area is empty."""
        if w < 1 or h < 1 or w * h > MAX_TILES:
            raise TilemapFormatError("map size must be at least 1x1 and at most %d tiles" % MAX_TILES)
        for layer in self.layers:
            new = [-1] * (w * h)
            for y in range(min(h, self.h)):
                for x in range(min(w, self.w)):
                    new[y * w + x] = layer.data[y * self.w + x]
            layer.data = new
        self.w, self.h = w, h

    def clamp_to_tileset(self, tile_count: int) -> int:
        """Empty any tile that does not exist in a tileset with `tile_count` tiles; returns how many."""
        fixed = 0
        for layer in self.layers:
            for i, n in enumerate(layer.data):
                if n >= tile_count:
                    layer.data[i] = -1
                    fixed += 1
        self.solid = {n for n in self.solid if n < tile_count}
        return fixed

    # ---- layers ------------------------------------------------------------------------------
    def unique_name(self, base: str) -> str:
        names = {layer.name for layer in self.layers}
        if base not in names:
            return base
        n = 2
        while "%s %d" % (base, n) in names:
            n += 1
        return "%s %d" % (base, n)

    def add_layer(self, name: str = "layer", index: int | None = None) -> int:
        layer = Layer(self.unique_name(name.strip() or "layer"), [-1] * (self.w * self.h))
        at = len(self.layers) if index is None else max(0, min(index, len(self.layers)))
        self.layers.insert(at, layer)
        return at

    def remove_layer(self, index: int) -> bool:
        if len(self.layers) <= 1:
            return False
        del self.layers[index]
        return True

    def rename_layer(self, index: int, name: str) -> bool:
        name = name.strip()
        if not name or any(layer.name == name for i, layer in enumerate(self.layers) if i != index):
            return False
        self.layers[index].name = name
        return True

    def move_layer(self, index: int, delta: int) -> int:
        """Move a layer towards the front (+1) or back (-1) of the drawing order; returns its new index."""
        new = max(0, min(len(self.layers) - 1, index + delta))
        self.layers.insert(new, self.layers.pop(index))
        return new
