"""Messages between the IDE and the runner process.

IDE -> runner (runner's stdin), one text line per event:
    "d <key>\\n"   key went down      "u <key>\\n"   key went up

runner -> IDE (runner's stdout), binary messages: 1 type byte, uint32 big-endian length, payload.
"""
from __future__ import annotations

import struct

FRAME = b"F"    # payload: width*height*2 bytes of little-endian RGB565
STDOUT = b"O"   # payload: utf-8 text the game printed
ERROR = b"E"    # payload: utf-8 traceback / load error
INFO = b"I"     # payload: utf-8 JSON stats {"fps", "frame_ms", "frames", "target_fps"}
EXIT = b"X"     # payload: utf-8 reason ("ok", "error", "quit")
AUDIO = b"A"    # payload: one line of JSON (the command), then optionally raw bytes (see core/mixer.py)

_HEADER = struct.Struct(">cI")
MAX_PAYLOAD = 16 * 1024 * 1024


def pack(kind: bytes, payload: bytes = b"") -> bytes:
    return _HEADER.pack(kind, len(payload)) + payload


class MessageParser:
    """Feed it raw bytes from the pipe; it returns whole messages as they complete."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[bytes, bytes]]:
        self._buf += data
        out = []
        while len(self._buf) >= _HEADER.size:
            kind, length = _HEADER.unpack_from(self._buf)
            if length > MAX_PAYLOAD:
                self._buf.clear()
                raise ValueError("corrupt message stream (payload of %d bytes)" % length)
            end = _HEADER.size + length
            if len(self._buf) < end:
                break
            out.append((kind, bytes(self._buf[_HEADER.size:end])))
            del self._buf[:end]
        return out
