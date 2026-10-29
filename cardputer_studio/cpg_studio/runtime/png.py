"""Minimal PNG reader and writer (pure Python, standard library only).

Reads non-interlaced PNGs of any colour type and bit depth; writes 8-bit RGBA. That covers what
sprite tools export, and keeps the engine free of Pillow or Qt.
"""
from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(ValueError):
    pass


def _chunks(data: bytes):
    if data[:8] != SIGNATURE:
        raise PngError("not a PNG file")
    pos = 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length:
            raise PngError("truncated PNG")
        yield kind, body
        pos += 12 + length
        if kind == b"IEND":
            return


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, h: int, stride: int, bpp: int):
    rows, pos, prev = [], 0, bytearray(stride)
    for _ in range(h):
        if pos >= len(raw):
            raise PngError("truncated PNG image data")
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        if len(line) != stride:
            raise PngError("truncated PNG image data")
        pos += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 255
        elif ft != 0:
            raise PngError("bad PNG filter type %d" % ft)
        rows.append(line)
        prev = line
    return rows


def _samples(line: bytes, depth: int, count: int):
    """`count` samples of `depth` bits from a scanline."""
    if depth == 8:
        return line[:count]
    if depth == 16:
        return line[0:count * 2:2]                       # high byte only
    per = 8 // depth
    mask = (1 << depth) - 1
    out = []
    for byte in line:
        for k in range(per):
            out.append((byte >> (8 - depth * (k + 1))) & mask)
    return out[:count]


def decode(data: bytes):
    """Decode a PNG into (width, height, rows) where each row is w*4 bytes of RGBA."""
    header = None
    palette = b""
    trns = b""
    idat = []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
    if header is None or not idat:
        raise PngError("PNG has no image data")
    w, h, depth, ctype, _comp, _filt, interlace = header
    if interlace:
        raise PngError("interlaced PNGs aren't supported; re-save without interlacing")
    if ctype not in _CHANNELS or depth not in (1, 2, 4, 8, 16):
        raise PngError("unsupported PNG format (colour type %d, %d-bit)" % (ctype, depth))
    if w * h > 4_000_000:
        raise PngError("image is too large (%dx%d)" % (w, h))
    channels = _CHANNELS[ctype]
    bits = channels * depth
    stride = (w * bits + 7) // 8
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise PngError("corrupt PNG data: %s" % e) from None
    lines = _unfilter(raw, h, stride, max(1, bits // 8))
    scale = 255 // ((1 << depth) - 1) if depth < 8 else 1
    key = None
    if ctype == 0 and len(trns) >= 2:
        key = (trns[0] << 8 | trns[1]) if depth == 16 else trns[1]
        key = key >> 8 if depth == 16 else key
    elif ctype == 2 and len(trns) >= 6:
        vals = struct.unpack(">3H", trns[:6])
        key = tuple(v >> 8 if depth == 16 else v for v in vals)
    rows = []
    for line in lines:
        out = bytearray(w * 4)
        if ctype == 3:
            idx = _samples(line, depth, w)
            for x, i in enumerate(idx):
                p = palette[i * 3:i * 3 + 3]
                if len(p) < 3:
                    raise PngError("PNG palette index out of range")
                out[x * 4:x * 4 + 3] = p
                out[x * 4 + 3] = trns[i] if i < len(trns) else 255
        elif ctype == 0:
            g = _samples(line, depth, w)
            for x, v in enumerate(g):
                a = 0 if key is not None and v == key else 255
                v8 = v * scale
                out[x * 4:x * 4 + 4] = bytes((v8, v8, v8, a))
        elif ctype == 4:
            s = _samples(line, depth, w * 2)
            for x in range(w):
                v = s[x * 2]
                out[x * 4:x * 4 + 4] = bytes((v, v, v, s[x * 2 + 1]))
        elif ctype == 2:
            s = _samples(line, depth, w * 3)
            for x in range(w):
                r, g, b = s[x * 3], s[x * 3 + 1], s[x * 3 + 2]
                a = 0 if key is not None and (r, g, b) == key else 255
                out[x * 4:x * 4 + 4] = bytes((r, g, b, a))
        else:                                              # RGBA
            s = _samples(line, depth, w * 4)
            out[:] = s
        rows.append(bytes(out))
    return w, h, rows


def encode(width: int, height: int, rgba: bytes) -> bytes:
    """Encode w*h*4 bytes of RGBA (row after row) as a PNG."""
    if len(rgba) != width * height * 4:
        raise PngError("pixel data has the wrong size")
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
