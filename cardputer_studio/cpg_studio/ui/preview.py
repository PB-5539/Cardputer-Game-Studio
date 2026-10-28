"""Middle-right panel: the simulated Cardputer screen. PC key presses go to the running game."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ..runtime import api
from ..runtime.keys import name_from_qt_key
from . import theme

SCREEN_W, SCREEN_H = api.WIDTH, api.HEIGHT


class ScreenWidget(QWidget):
    key_event = Signal(bool, str)          # (is_down, engine key name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(SCREEN_W // 2 + 40, SCREEN_H // 2 + 40)
        self._image: QImage | None = None
        self._down: set[str] = set()
        self._running = False
        self._scale_mode = 0               # 0 = fit, otherwise a fixed integer scale

    def set_running(self, running: bool) -> None:
        self._running = running
        self.update()

    def set_scale_mode(self, mode: int) -> None:
        self._scale_mode = mode
        self.update()

    def set_frame(self, payload: bytes) -> None:
        if len(payload) != SCREEN_W * SCREEN_H * 2:
            return
        # QImage doesn't own `payload`, so copy it into the image before the bytes go away
        self._image = QImage(payload, SCREEN_W, SCREEN_H, SCREEN_W * 2, QImage.Format.Format_RGB16).copy()
        self.update()

    def clear_frame(self) -> None:
        self._image = None
        self.update()

    # ---- painting ------------------------------------------------------------------------
    def _target_rect(self) -> QRectF:
        avail = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        if self._scale_mode:
            scale = float(self._scale_mode)
        else:
            fit = min(avail.width() / SCREEN_W, avail.height() / SCREEN_H)
            scale = float(int(fit)) if fit >= 1 else max(fit, 0.1)    # whole-number zoom keeps pixels crisp
        w, h = SCREEN_W * scale, SCREEN_H * scale
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0b0b0b"))
        target = self._target_rect()
        p.setPen(QPen(QColor(theme.BORDER), 2))
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(target.adjusted(-8, -8, 8, 8), 8, 8)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if self._image is not None:
            p.drawImage(target, self._image)
        else:
            p.setPen(QColor(theme.MUTED))
            p.drawText(target, Qt.AlignmentFlag.AlignCenter, "No signal\nPress Run (F5)")
        if self._running and not self.hasFocus():
            p.setPen(QColor("#ffffff"))
            p.setBrush(QColor(0, 0, 0, 170))
            band = QRectF(target.left(), target.bottom() - 26, target.width(), 26)
            p.drawRect(band)
            font = QFont(self.font())
            font.setPointSize(9)
            p.setFont(font)
            p.drawText(band, Qt.AlignmentFlag.AlignCenter, "Click here to send keys to the game")
        p.end()

    # ---- keyboard ------------------------------------------------------------------------
    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        name = name_from_qt_key(event.key())
        if name is None:
            super().keyPressEvent(event)
            return
        if name not in self._down:
            self._down.add(name)
            self.key_event.emit(True, name)
        event.accept()

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        name = name_from_qt_key(event.key())
        if name is None:
            super().keyReleaseEvent(event)
            return
        if name in self._down:
            self._down.discard(name)
            self.key_event.emit(False, name)
        event.accept()

    def focusOutEvent(self, event):
        for name in list(self._down):         # don't leave keys stuck down when focus moves away
            self.key_event.emit(False, name)
        self._down.clear()
        super().focusOutEvent(event)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusNextPrevChild(self, next_):
        return False                          # Tab must reach the game, not move focus

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)


class PreviewPanel(QWidget):
    """Screen plus a small toolbar (run/stop/restart actions come from the main window)."""

    def __init__(self, run_action, stop_action, restart_action, parent=None):
        super().__init__(parent)
        self.display = ScreenWidget()
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        for action in (run_action, stop_action, restart_action):
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            bar.addWidget(button)
        bar.addStretch(1)
        bar.addWidget(QLabel("Zoom"))
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit", "1x", "2x", "3x", "4x"])
        self.zoom.currentIndexChanged.connect(self.display.set_scale_mode)
        bar.addWidget(self.zoom)
        self.status = QLabel("Stopped")
        self.status.setStyleSheet(f"color: {theme.MUTED}; padding: 2px 8px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.display, 1)
        layout.addWidget(self.status)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
