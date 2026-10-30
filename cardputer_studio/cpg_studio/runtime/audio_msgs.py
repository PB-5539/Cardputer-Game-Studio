"""Builds the AUDIO protocol messages (see core/mixer.py for what they mean)."""
from __future__ import annotations

import json


def _msg(cmd: dict, blob: bytes = b"") -> bytes:
    return json.dumps(cmd).encode() + (b"\n" + blob if blob else b"")


def load_message(snd) -> bytes:
    if snd.kind == "pcm":
        return _msg({"op": "load", "id": snd.uid, "kind": "pcm", "rate": snd.rate}, snd.data or b" ")
    return _msg({"op": "load", "id": snd.uid, "kind": "tones", "notes": snd.notes, "wave": snd.wave,
                 "volume": snd.volume})


def play_message(snd, loop: bool = False, volume: float = 1.0) -> bytes:
    return _msg({"op": "play", "id": snd.uid, "loop": bool(loop), "volume": volume})


def stop_message(snd=None) -> bytes:
    return _msg({"op": "stop", "id": snd.uid if snd is not None else None})


def tone_message(freq: int, ms: int) -> bytes:
    return _msg({"op": "tone", "freq": freq, "ms": ms})
