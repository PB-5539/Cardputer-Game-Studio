"""Software audio mixer for the preview (pure Python, so it can be tested without Qt).

The game process sends audio commands (see runtime/protocol.AUDIO); the IDE feeds them to a Mixer
and plays whatever render() returns. Each command is one line of JSON, optionally followed by
b"\\n" and raw bytes (the samples of a "pcm" sound):

    {"op": "load", "id": 3, "kind": "tones", "notes": [[440, 100], [0, 50]], "wave": "square", "volume": 0.5}
    {"op": "load", "id": 4, "kind": "pcm", "rate": 11025}\\n<unsigned 8-bit samples>
    {"op": "play", "id": 3, "loop": false, "volume": 1.0}
    {"op": "stop", "id": 3}     {"op": "stop", "id": null}
    {"op": "tone", "freq": 880, "ms": 100}
"""
from __future__ import annotations

import json
import random
import sys
from array import array

OUTPUT_RATE = 22050
MAX_VOICES = 8
MASTER = 0.45
PEAK = 32000


class _Sound:
    def __init__(self, kind, notes=(), wave="square", volume=0.5, rate=11025, data=b""):
        self.kind, self.notes, self.wave, self.volume = kind, list(notes), wave, volume
        self.rate, self.data = rate, data


class _Voice:
    def __init__(self, sound, sound_id, loop, volume, out_rate):
        self.sound, self.id, self.loop = sound, sound_id, loop
        self.gain = max(0.0, min(1.0, volume)) * sound.volume * MASTER * PEAK
        self.out_rate = out_rate
        self.done = False
        self.phase = 0.0
        self.noise = 0.0
        self.pos = 0.0                                   # pcm: position in source samples
        self.note = 0                                    # tones: index of the current note
        self.left = self._note_samples(0)

    def _note_samples(self, i):
        return int(self.sound.notes[i][1] * self.out_rate / 1000) if i < len(self.sound.notes) else 0

    def render(self, out, n):
        """Add n samples of this voice into the float list `out`."""
        if self.sound.kind == "pcm":
            self._render_pcm(out, n)
        else:
            self._render_tones(out, n)

    def _render_pcm(self, out, n):
        data = self.sound.data
        size = len(data)
        step = self.sound.rate / self.out_rate
        gain, pos = self.gain / 128.0, self.pos
        for i in range(n):
            idx = int(pos)
            if idx >= size:
                if self.loop and size:
                    pos -= size
                    idx = int(pos)
                else:
                    self.done = True
                    break
            out[i] += (data[idx] - 128) * gain
            pos += step
        self.pos = pos

    def _render_tones(self, out, n):
        sound, gain, rate = self.sound, self.gain, self.out_rate
        i = 0
        while i < n:
            if self.left <= 0:
                self.note += 1
                if self.note >= len(sound.notes):
                    if self.loop and sound.notes:
                        self.note = 0
                    else:
                        self.done = True
                        return
                self.left = self._note_samples(self.note)
                continue
            freq = sound.notes[self.note][0]
            count = min(self.left, n - i)
            if freq > 0:
                inc = freq / rate
                phase, wave = self.phase, sound.wave
                for k in range(i, i + count):
                    if wave == "square":
                        v = 1.0 if phase < 0.5 else -1.0
                    elif wave == "triangle":
                        v = 4 * phase - 1 if phase < 0.5 else 3 - 4 * phase
                    elif wave == "saw":
                        v = 2 * phase - 1
                    else:                                    # noise: new random value every cycle
                        if phase + inc >= 1.0:
                            self.noise = random.uniform(-1, 1)
                        v = self.noise
                    out[k] += v * gain
                    phase += inc
                    if phase >= 1.0:
                        phase -= 1.0
                self.phase = phase
            else:
                self.phase = 0.0
            self.left -= count
            i += count


class Mixer:
    def __init__(self, rate: int = OUTPUT_RATE, max_voices: int = MAX_VOICES):
        self.rate = rate
        self.max_voices = max_voices
        self.sounds: dict[int, _Sound] = {}
        self.voices: list[_Voice] = []

    def clear(self) -> None:
        self.sounds.clear()
        self.voices.clear()

    def active(self) -> bool:
        return bool(self.voices)

    def handle(self, payload: bytes) -> None:
        """Process one AUDIO message from the game. Bad messages are ignored."""
        head, _, blob = payload.partition(b"\n")
        try:
            cmd = json.loads(head)
            op = cmd["op"]
            if op == "load":
                if cmd["kind"] == "pcm":
                    self.sounds[cmd["id"]] = _Sound("pcm", rate=int(cmd["rate"]), data=blob, volume=1.0)
                else:
                    self.sounds[cmd["id"]] = _Sound("tones", cmd["notes"], cmd.get("wave", "square"),
                                                    float(cmd.get("volume", 0.5)))
            elif op == "play":
                sound = self.sounds.get(cmd["id"])
                if sound is not None:
                    self._start(sound, cmd["id"], bool(cmd.get("loop")), float(cmd.get("volume", 1.0)))
            elif op == "stop":
                sid = cmd.get("id")
                self.voices = [v for v in self.voices if sid is not None and v.id != sid]
            elif op == "tone":
                ms = max(1, min(int(cmd["ms"]), 10000))
                self._start(_Sound("tones", [[max(0, int(cmd["freq"])), ms]]), None, False, 1.0)
        except (ValueError, KeyError, TypeError):
            pass

    def _start(self, sound, sound_id, loop, volume):
        self.voices.append(_Voice(sound, sound_id, loop, volume, self.rate))
        if len(self.voices) > self.max_voices:
            del self.voices[0]                                # the oldest voice is cut off

    def render(self, n: int) -> bytes:
        """n mono 16-bit little-endian samples of everything that is playing."""
        out = [0.0] * n
        for voice in self.voices:
            voice.render(out, n)
        self.voices = [v for v in self.voices if not v.done]
        buf = array("h", [max(-32768, min(32767, int(v))) for v in out])
        if sys.byteorder == "big":
            buf.byteswap()
        return buf.tobytes()
