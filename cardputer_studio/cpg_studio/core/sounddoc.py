"""The sound editor's document model: a tone sequence, plus JSON in and out (no Qt)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..runtime import assets
from ..runtime.assets import AssetError


@dataclass
class SoundDoc:
    wave: str = "square"
    volume: float = 0.5
    notes: list = field(default_factory=list)       # [[note name or Hz, milliseconds], ...]

    @classmethod
    def from_json(cls, text: str) -> "SoundDoc":
        try:
            d = json.loads(text)
            if not isinstance(d, dict) or d.get("kind", "tones") != "tones":
                raise ValueError
            notes = [[n, int(ms)] for n, ms in d.get("notes", [])]
            return cls(str(d.get("wave", "square")), float(d.get("volume", 0.5)), notes)
        except (ValueError, TypeError):
            raise AssetError("this file is not a tone-sequence sound") from None

    def to_json(self) -> str:
        lines = ['{', '  "kind": "tones",', '  "wave": %s,' % json.dumps(self.wave),
                 '  "volume": %s,' % json.dumps(round(self.volume, 3)), '  "notes": [']
        for i, (note, ms) in enumerate(self.notes):
            lines.append("    [%s, %d]%s" % (json.dumps(note), ms, "," if i < len(self.notes) - 1 else ""))
        lines += ["  ]", "}", ""]
        return "\n".join(lines)

    def to_sound(self) -> assets.Sound:
        """The runtime Sound (raises AssetError describing the first problem)."""
        return assets.tones_from_notes(self.notes, "", self.wave, self.volume)

    def error(self) -> str | None:
        try:
            self.to_sound()
        except AssetError as e:
            return str(e)
        return None

    def duration_ms(self) -> int:
        return sum(ms for _n, ms in self.notes)

    def add_note(self, note, ms: int) -> None:
        self.notes.append([note, int(ms)])

    def move_note(self, index: int, delta: int) -> int:
        new = max(0, min(len(self.notes) - 1, index + delta))
        self.notes.insert(new, self.notes.pop(index))
        return new
