"""Sprites, tilemaps and sounds: loading them from project files and drawing/describing them.

Everything here is plain Python with no GUI, so it runs in the game process and in tests.

File formats (all ordinary files inside the project):
  sprites    .png   Any PNG. Magenta (255, 0, 255) and transparent pixels are see-through.
                    A sprite sheet is sliced into frames when you pass a frame size.
  tilemaps   .json  {"tileset": "tiles.png", "tile_w": 8, "tile_h": 8, "width": W, "height": H,
                     "layers": [{"name": "ground", "data": [W*H tile numbers, -1 = empty]}],
                     "solid": [tile numbers that block movement]}
  sounds     .json  {"kind": "tones", "wave": "square", "volume": 0.5,
                     "notes": [["C4", 200], [440, 100], ["rest", 50]]}
             .wav   Any PCM WAV; it is converted to 8-bit mono at a low sample rate.
"""
from __future__ import annotations

import itertools
import json
import re
import sys
import wave
from array import array

from . import png

KEY = 0xF81F                      # RGB565 magenta: the "transparent" colour
WAVES = ("square", "triangle", "saw", "noise")
PCM_RATE = 11025                  # sample rate WAVs are converted to
MAX_PCM_SECONDS = 30
MAX_NOTES = 2000

_uids = itertools.count(1)


class AssetError(Exception):
    """A sprite, tilemap or sound file is missing or invalid (the message says what to fix)."""


def read_file(path: str, what: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        raise AssetError('%s file "%s" not found (paths are relative to the project folder)' % (what, path)) from None
    except OSError as e:
        raise AssetError('cannot read %s "%s": %s' % (what, path, e)) from None


# ---- sprites ---------------------------------------------------------------------------------
def _rgba_to_565(rows, w):
    out = []
    for row in rows:
        buf = array("H", bytes(w * 2))
        for x in range(w):
            r, g, b, a = row[x * 4:x * 4 + 4]
            buf[x] = KEY if a < 128 else ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        if sys.byteorder == "big":
            buf.byteswap()
        out.append(buf.tobytes())
    return out


def _row_runs(pixels: array):
    """[(x, bytes)] for each stretch of non-transparent pixels in a row."""
    runs, x, n = [], 0, len(pixels)
    while x < n:
        if pixels[x] == KEY:
            x += 1
            continue
        start = x
        while x < n and pixels[x] != KEY:
            x += 1
        chunk = array("H", pixels[start:x])
        if sys.byteorder == "big":
            chunk.byteswap()
        runs.append((start, chunk.tobytes()))
    return runs


class Sprite:
    """An image, or a sheet of equally sized frames. `w` and `h` are the size of one frame."""

    def __init__(self, sheet_w: int, sheet_h: int, rows, frame_w=None, frame_h=None, name: str = ""):
        fw, fh = int(frame_w or sheet_w), int(frame_h or sheet_h)
        if fw <= 0 or fh <= 0:
            raise AssetError("frame size must be positive")
        if fw > sheet_w or fh > sheet_h:
            raise AssetError('frame size %dx%d is bigger than the image %dx%d%s' % (
                fw, fh, sheet_w, sheet_h, ' ("%s")' % name if name else ""))
        self.name = name
        self.sheet_w, self.sheet_h = sheet_w, sheet_h
        self.w, self.h = fw, fh
        self.columns, self.rows_count = sheet_w // fw, sheet_h // fh
        self.frame_count = self.columns * self.rows_count
        self._rows = rows                       # sheet_h rows of sheet_w*2 bytes
        self._runs: dict = {}

    def _frame_pixels(self, frame: int):
        col, row = frame % self.columns, frame // self.columns
        x0, y0 = col * self.w, row * self.h
        out = []
        for y in range(y0, y0 + self.h):
            px = array("H")
            px.frombytes(self._rows[y][x0 * 2:(x0 + self.w) * 2])
            if sys.byteorder == "big":
                px.byteswap()
            out.append(px)
        return out

    def runs(self, frame: int = 0, flip_x: bool = False, flip_y: bool = False):
        """Cached drawing data: for each row, [(x, pixel bytes)] of the visible stretches."""
        frame = int(frame) % self.frame_count
        key = (frame, bool(flip_x), bool(flip_y))
        runs = self._runs.get(key)
        if runs is None:
            rows = self._frame_pixels(frame)
            if flip_x:
                for px in rows:
                    px.reverse()
            if flip_y:
                rows.reverse()
            runs = [_row_runs(px) for px in rows]
            self._runs[key] = runs
        return runs

    def pixel(self, x: int, y: int, frame: int = 0):
        """RGB565 colour at (x, y) of a frame, or None if transparent / outside the frame."""
        x, y = int(x), int(y)
        if not (0 <= x < self.w and 0 <= y < self.h):
            return None
        col, row = int(frame) % self.frame_count % self.columns, int(frame) % self.frame_count // self.columns
        data = self._rows[row * self.h + y]
        i = (col * self.w + x) * 2
        v = data[i] | data[i + 1] << 8
        return None if v == KEY else v

    def __repr__(self):
        return "<Sprite %s %dx%d, %d frame(s)>" % (self.name or "?", self.w, self.h, self.frame_count)


def sprite_from_png(data: bytes, frame_w=None, frame_h=None, name: str = "") -> Sprite:
    try:
        w, h, rows = png.decode(data)
    except png.PngError as e:
        raise AssetError('sprite "%s": %s' % (name, e)) from None
    return Sprite(w, h, _rgba_to_565(rows, w), frame_w, frame_h, name)


def load_sprite_file(path: str, frame_w=None, frame_h=None) -> Sprite:
    return sprite_from_png(read_file(path, "sprite"), frame_w, frame_h, path)


# ---- tilemaps --------------------------------------------------------------------------------
class Tilemap:
    def __init__(self, tileset: Sprite, w: int, h: int, layers: dict, solid=(), name: str = ""):
        self.name = name
        self.tileset = tileset
        self.tile_w, self.tile_h = tileset.w, tileset.h
        self.w, self.h = w, h                      # size in tiles
        self.px_w, self.px_h = w * self.tile_w, h * self.tile_h
        self.layers = layers                       # name -> flat list of w*h tile numbers
        self.layer_names = list(layers)
        self.solid = frozenset(solid)

    def _layer(self, layer):
        if isinstance(layer, str):
            if layer not in self.layers:
                raise KeyError('no layer named "%s" (layers: %s)' % (layer, ", ".join(self.layer_names)))
            return self.layers[layer]
        return self.layers[self.layer_names[int(layer)]]

    def get(self, tx: int, ty: int, layer=0) -> int:
        """Tile number at a tile position (-1 = empty or outside the map)."""
        tx, ty = int(tx), int(ty)
        if 0 <= tx < self.w and 0 <= ty < self.h:
            return self._layer(layer)[ty * self.w + tx]
        return -1

    def set(self, tx: int, ty: int, tile: int, layer=0) -> None:
        tx, ty, tile = int(tx), int(ty), int(tile)
        if not (0 <= tx < self.w and 0 <= ty < self.h):
            return
        if not -1 <= tile < self.tileset.frame_count:
            raise ValueError("tile %d does not exist (tileset has %d tiles)" % (tile, self.tileset.frame_count))
        self._layer(layer)[ty * self.w + tx] = tile

    def is_solid(self, tx: int, ty: int) -> bool:
        """True if any layer has a solid tile there. Outside the map counts as solid."""
        tx, ty = int(tx), int(ty)
        if not (0 <= tx < self.w and 0 <= ty < self.h):
            return True
        i = ty * self.w + tx
        return any(data[i] in self.solid for data in self.layers.values())

    def solid_at(self, x: float, y: float) -> bool:
        """is_solid for a pixel position in the map."""
        return self.is_solid(int(x // self.tile_w), int(y // self.tile_h))

    def draw(self, fb, cam_x: int = 0, cam_y: int = 0, layer=None) -> None:
        tw, th = self.tile_w, self.tile_h
        tx0, ty0 = max(0, cam_x // tw), max(0, cam_y // th)
        tx1 = min(self.w, (cam_x + fb.width + tw - 1) // tw + 1)
        ty1 = min(self.h, (cam_y + fb.height + th - 1) // th + 1)
        datas = [self._layer(layer)] if layer is not None else list(self.layers.values())
        for data in datas:
            for ty in range(ty0, ty1):
                base = ty * self.w
                for tx in range(tx0, tx1):
                    tile = data[base + tx]
                    if tile >= 0:
                        fb.blit_runs(self.tileset.runs(tile), tx * tw - cam_x, ty * th - cam_y)

    def __repr__(self):
        return "<Tilemap %s %dx%d tiles, layers: %s>" % (self.name or "?", self.w, self.h, ", ".join(self.layer_names))


def _int(doc: dict, key: str, path: str, minimum: int = 1) -> int:
    v = doc.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
        raise AssetError('tilemap "%s": "%s" must be a whole number >= %d' % (path, key, minimum))
    return v


def tilemap_from_json(text: str, load_tileset, path: str = "") -> Tilemap:
    """Build a Tilemap from its JSON text; load_tileset(name, tile_w, tile_h) returns the Sprite."""
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise AssetError('tilemap "%s" is not valid JSON: %s' % (path, e)) from None
    if not isinstance(doc, dict):
        raise AssetError('tilemap "%s" must be a JSON object' % path)
    tw, th = _int(doc, "tile_w", path), _int(doc, "tile_h", path)
    w, h = _int(doc, "width", path), _int(doc, "height", path)
    if w * h > 100_000:
        raise AssetError('tilemap "%s" is too big (%dx%d tiles)' % (path, w, h))
    tileset_name = doc.get("tileset")
    if not isinstance(tileset_name, str) or not tileset_name:
        raise AssetError('tilemap "%s": "tileset" must be the path of a PNG' % path)
    tileset = load_tileset(tileset_name, tw, th)
    raw_layers = doc.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise AssetError('tilemap "%s": "layers" must be a non-empty list' % path)
    layers = {}
    for i, layer in enumerate(raw_layers):
        name = str(layer.get("name", "layer%d" % i)) if isinstance(layer, dict) else ""
        data = layer.get("data") if isinstance(layer, dict) else None
        if not isinstance(data, list) or len(data) != w * h:
            raise AssetError('tilemap "%s": layer %d needs "data" with %d numbers (width x height)' % (path, i, w * h))
        for n in data:
            if not isinstance(n, int) or isinstance(n, bool) or not -1 <= n < tileset.frame_count:
                raise AssetError('tilemap "%s": layer "%s" has tile %r but the tileset only has tiles 0-%d (-1 = empty)'
                                 % (path, name, n, tileset.frame_count - 1))
        if name in layers:
            raise AssetError('tilemap "%s": two layers are named "%s"' % (path, name))
        layers[name] = list(data)
    solid = doc.get("solid", [])
    if not isinstance(solid, list) or not all(isinstance(n, int) for n in solid):
        raise AssetError('tilemap "%s": "solid" must be a list of tile numbers' % path)
    return Tilemap(tileset, w, h, layers, solid, path)


# ---- sounds ----------------------------------------------------------------------------------
_NOTE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_freq(note) -> int:
    """Frequency in Hz for a note name like "C4", "F#3", "Bb5" (A4 = 440), or a number; 0 for a rest."""
    if isinstance(note, (int, float)) and not isinstance(note, bool):
        return max(0, int(round(note)))
    s = str(note).strip()
    if s.lower() in ("r", "rest", "-", ""):
        return 0
    m = _NOTE.match(s)
    if not m:
        try:
            return max(0, int(round(float(s))))
        except ValueError:
            raise AssetError('"%s" is not a note (try C4, F#3, Bb5, a frequency like 440, or "rest")' % s) from None
    letter, accidental, octave = m.group(1).upper(), m.group(2), int(m.group(3))
    midi = 12 * (octave + 1) + _SEMITONE[letter] + (1 if accidental == "#" else -1 if accidental == "b" else 0)
    return int(round(440 * 2 ** ((midi - 69) / 12)))


class Sound:
    """Either a tone sequence (kind "tones") or sampled audio (kind "pcm")."""

    def __init__(self, kind: str, name: str = "", notes=(), wave_shape: str = "square", volume: float = 0.5,
                 rate: int = PCM_RATE, data: bytes = b""):
        self.uid = next(_uids)
        self.kind = kind
        self.name = name
        self.notes = [(int(f), int(ms)) for f, ms in notes]
        self.wave = wave_shape
        self.volume = max(0.0, min(1.0, float(volume)))
        self.rate = rate
        self.data = data                          # unsigned 8-bit mono samples
        if kind == "pcm":
            self.duration_ms = int(len(data) * 1000 / rate) if rate else 0
        else:
            self.duration_ms = sum(ms for _f, ms in self.notes)

    def __repr__(self):
        return "<Sound %s %s %d ms>" % (self.name or "?", self.kind, self.duration_ms)


def tones_from_notes(notes, name: str = "", wave_shape: str = "square", volume: float = 0.5) -> Sound:
    if wave_shape not in WAVES:
        raise AssetError('unknown wave "%s" (use one of: %s)' % (wave_shape, ", ".join(WAVES)))
    parsed = []
    for item in notes:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise AssetError('each note must be [note, milliseconds], got %r' % (item,))
        note, ms = item
        if not isinstance(ms, (int, float)) or isinstance(ms, bool) or not 0 < ms <= 60000:
            raise AssetError("note length must be 1-60000 ms, got %r" % (ms,))
        parsed.append((note_freq(note), int(ms)))
    if not parsed:
        raise AssetError("a sound needs at least one note")
    if len(parsed) > MAX_NOTES:
        raise AssetError("too many notes (max %d)" % MAX_NOTES)
    return Sound("tones", name, parsed, wave_shape, volume)


def parse_note_string(text: str, name: str = "", wave_shape: str = "square", volume: float = 0.5) -> Sound:
    """"C4:200 E4:200 rest:100 G4" -> Sound (a note without ":ms" lasts 200 ms)."""
    notes = []
    for token in text.split():
        note, _, ms = token.partition(":")
        try:
            length = int(ms) if ms else 200
        except ValueError:
            raise AssetError('bad note length in "%s"' % token) from None
        notes.append((note, length))
    return tones_from_notes(notes, name, wave_shape, volume)


def sound_from_json(text: str, path: str = "") -> Sound:
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise AssetError('sound "%s" is not valid JSON: %s' % (path, e)) from None
    if not isinstance(doc, dict) or doc.get("kind", "tones") != "tones":
        raise AssetError('sound "%s": expected {"kind": "tones", "notes": [...]}' % path)
    vol = doc.get("volume", 0.5)
    if not isinstance(vol, (int, float)):
        raise AssetError('sound "%s": "volume" must be a number from 0 to 1' % path)
    return tones_from_notes(doc.get("notes", []), path, doc.get("wave", "square"), vol)


def sound_from_wav(data: bytes, name: str = "") -> Sound:
    import io
    try:
        with wave.open(io.BytesIO(data)) as wf:
            channels, width, rate, frames = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
            if wf.getcomptype() != "NONE":
                raise AssetError('sound "%s": compressed WAV files are not supported (save as PCM)' % name)
            if frames / max(rate, 1) > MAX_PCM_SECONDS:
                raise AssetError('sound "%s" is longer than %d seconds' % (name, MAX_PCM_SECONDS))
            raw = wf.readframes(frames)
    except (wave.Error, EOFError) as e:
        raise AssetError('sound "%s" is not a readable WAV file: %s' % (name, e)) from None
    if width not in (1, 2, 3, 4) or channels < 1 or rate <= 0:
        raise AssetError('sound "%s": unsupported WAV format' % name)
    # to a list of signed 16-bit mono samples
    if width == 1:
        samples = array("h", [(b - 128) << 8 for b in raw])
    elif width == 2:
        samples = array("h")
        samples.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == "big":
            samples.byteswap()
    elif width == 3:
        samples = array("h", [int.from_bytes(raw[i + 1:i + 3], "little", signed=True)
                              for i in range(0, len(raw) - 2, 3)])
    else:
        samples = array("h", [int.from_bytes(raw[i + 2:i + 4], "little", signed=True)
                              for i in range(0, len(raw) - 3, 4)])
    if channels > 1:
        usable = len(samples) // channels * channels
        cols = [samples[c:usable:channels] for c in range(channels)]
        samples = array("h", [sum(vals) // channels for vals in zip(*cols)])
    target = min(rate, PCM_RATE)
    count = len(samples) * target // rate
    out = bytearray(count)
    for i in range(count):
        out[i] = (samples[i * rate // target] >> 8) + 128
    return Sound("pcm", name, rate=target, data=bytes(out))


def load_sound_file(path: str) -> Sound:
    data = read_file(path, "sound")
    low = path.lower()
    if low.endswith(".wav"):
        return sound_from_wav(data, path)
    if low.endswith(".json"):
        return sound_from_json(data.decode("utf-8", "replace"), path)
    raise AssetError('sound "%s": use a .wav file or a tone-sequence .json file' % path)
