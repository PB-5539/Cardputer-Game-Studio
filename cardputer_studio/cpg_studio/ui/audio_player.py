"""Plays the preview's sound through the computer's speakers (Qt Multimedia)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from ..core.mixer import OUTPUT_RATE, Mixer

CHUNK_MS = 25
BUFFER_MS = 120


class AudioPlayer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mixer = Mixer(OUTPUT_RATE)
        self.muted = False
        self.available = True
        self._sink = None
        self._io = None
        self._timer = QTimer(self)
        self._timer.setInterval(CHUNK_MS)
        self._timer.timeout.connect(self._pump)

    def _ensure_sink(self) -> bool:
        if self._sink is not None:
            return True
        if not self.available:
            return False
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            fmt = QAudioFormat()
            fmt.setSampleRate(OUTPUT_RATE)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            device = QMediaDevices.defaultAudioOutput()
            if device.isNull() or not device.isFormatSupported(fmt):
                self.available = False
                return False
            self._sink = QAudioSink(device, fmt, self)
            self._sink.setBufferSize(OUTPUT_RATE * 2 * BUFFER_MS // 1000)
            self._io = self._sink.start()
        except Exception:                  # no audio backend: the preview just stays silent
            self.available = False
            self._sink = self._io = None
            return False
        return True

    def handle(self, payload: bytes) -> None:
        """An AUDIO message from the running game."""
        if self.muted:
            return
        self.mixer.handle(payload)
        if self.mixer.active() and self._ensure_sink():
            self._timer.start()

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if muted:
            self.clear()

    def clear(self) -> None:
        """Silence everything (the game stopped)."""
        self.mixer.clear()
        self._timer.stop()

    def _pump(self) -> None:
        if self._io is None or not self.mixer.active():
            self._timer.stop()
            return
        free = self._sink.bytesFree() // 2
        if free > 0:
            self._io.write(self.mixer.render(min(free, OUTPUT_RATE * CHUNK_MS * 2 // 1000)))
