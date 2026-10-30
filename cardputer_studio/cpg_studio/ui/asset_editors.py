"""Editors for sprites (.png), tilemaps (.map.json) and sounds (.sfx.json, plus a .wav player)."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from ..core import audio_note_names
from ..core.pixelimage import TRANSPARENT, History, PixelImage
from ..core.sounddoc import SoundDoc
from ..core.tilemap_doc import TilemapDoc, TilemapFormatError
from ..runtime import assets, audio_msgs
from ..runtime.assets import AssetError
from . import theme

PALETTE = [(0, 0, 0), (255, 255, 255), (136, 136, 136), (68, 68, 68), (255, 0, 0), (255, 140, 0), (255, 255, 0),
           (0, 200, 0), (0, 255, 255), (0, 120, 255), (0, 0, 160), (160, 0, 255), (255, 100, 200), (120, 70, 30),
           (255, 200, 150), (30, 60, 30)]


def _qimage(data: bytes, w: int, h: int) -> QImage:
    img = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()                                   # own the pixels: `data` may go away


def _checker(painter: QPainter, rect: QRect, cell: int = 8) -> None:
    painter.fillRect(rect, QColor(60, 60, 60))
    light = QColor(90, 90, 90)
    for y in range(0, rect.height(), cell):
        for x in range(0, rect.width(), cell):
            if (x // cell + y // cell) % 2:
                painter.fillRect(rect.x() + x, rect.y() + y, min(cell, rect.width() - x), min(cell, rect.height() - y), light)


def _row(*widgets) -> QHBoxLayout:
    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        box.addWidget(w)
    return box


def _spin(low: int, high: int, value: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(low, high)
    s.setValue(value)
    return s


def _tool_buttons(parent_layout, tools, on_pick, first="pencil"):
    buttons = {}
    for key, label, tip in tools:
        b = QToolButton()
        b.setText(label)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setAutoExclusive(True)
        b.setChecked(key == first)
        b.clicked.connect(lambda checked=False, k=key: on_pick(k))
        parent_layout.addWidget(b)
        buttons[key] = b
    return buttons


def _swatch_css(rgb) -> str:
    return "background: rgb(%d,%d,%d); border: 1px solid #666; min-width: 18px; max-width: 18px; " \
           "min-height: 18px; max-height: 18px;" % tuple(rgb[:3])


# ===================================================================================================
#  Sprite editor
# ===================================================================================================
class PixelCanvas(QWidget):
    edited = Signal()
    picked = Signal(tuple)

    def __init__(self, image: PixelImage, history: History, parent=None):
        super().__init__(parent)
        self.img = image
        self.history = history
        self.zoom = 16
        self.tool = "pencil"
        self.color = (0, 0, 0, 255)
        self.brush = 1
        self.show_grid = True
        self.frame_w = image.w
        self.frame_h = image.h
        self._base = None
        self._start = None
        self._last = None
        self._erase = False
        self.setMouseTracking(False)
        self.resize_to_image()

    def resize_to_image(self) -> None:
        self.setFixedSize(self.img.w * self.zoom, self.img.h * self.zoom)
        self.update()

    def sizeHint(self):
        return QSize(self.img.w * self.zoom, self.img.h * self.zoom)

    # ---- painting -------------------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        full = QRect(0, 0, self.img.w * self.zoom, self.img.h * self.zoom)
        _checker(p, full)
        p.drawImage(full, _qimage(bytes(self.img.data), self.img.w, self.img.h))
        if self.show_grid and self.zoom >= 6:
            p.setPen(QPen(QColor(255, 255, 255, 38)))
            for x in range(1, self.img.w):
                p.drawLine(x * self.zoom, 0, x * self.zoom, full.height())
            for y in range(1, self.img.h):
                p.drawLine(0, y * self.zoom, full.width(), y * self.zoom)
        if 0 < self.frame_w < self.img.w or 0 < self.frame_h < self.img.h:     # frame boundaries of a sheet
            p.setPen(QPen(QColor(0, 220, 255, 200)))
            for x in range(self.frame_w, self.img.w, max(1, self.frame_w)):
                p.drawLine(x * self.zoom, 0, x * self.zoom, full.height())
            for y in range(self.frame_h, self.img.h, max(1, self.frame_h)):
                p.drawLine(0, y * self.zoom, full.width(), y * self.zoom)

    # ---- mouse ----------------------------------------------------------------------------------
    def _cell(self, event):
        pos = event.position()
        return int(pos.x() // self.zoom), int(pos.y() // self.zoom)

    def mousePressEvent(self, event):
        x, y = self._cell(event)
        if self.tool == "picker":
            if self.img.inside(x, y):
                self.picked.emit(self.img.get(x, y))
            return
        self._erase = event.button() == Qt.MouseButton.RightButton or self.tool == "eraser"
        self._base = self.img.copy()
        self._start = self._last = (x, y)
        color = TRANSPARENT if self._erase else self.color
        if self.tool == "fill":
            self.img.flood_fill(x, y, color)
            self._finish()
        elif self.tool in ("pencil", "eraser"):
            self.img.stamp(x, y, color, self.brush)
        else:
            self._shape(x, y)
        self.update()

    def mouseMoveEvent(self, event):
        if self._base is None:
            return
        x, y = self._cell(event)
        color = TRANSPARENT if self._erase else self.color
        if self.tool in ("pencil", "eraser"):
            self.img.line(self._last[0], self._last[1], x, y, color, self.brush)
            self._last = (x, y)
        elif self.tool != "fill":
            self.img.replace_data(self._base)
            self._shape(x, y)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._base is not None:
            self._finish()

    def _shape(self, x, y):
        color = TRANSPARENT if self._erase else self.color
        x0, y0 = self._start
        if self.tool == "line":
            self.img.line(x0, y0, x, y, color, self.brush)
        elif self.tool in ("rect", "rect_fill"):
            self.img.rect(x0, y0, x, y, color, self.tool == "rect_fill")
        elif self.tool in ("ellipse", "ellipse_fill"):
            self.img.ellipse(x0, y0, x, y, color, self.tool == "ellipse_fill")

    def _finish(self):
        base, self._base = self._base, None
        if bytes(self.img.data) != bytes(base.data):
            self.history.record(base)
            self.edited.emit()
        self.update()

    # ---- whole-image actions ---------------------------------------------------------------------
    def apply(self, new_image: PixelImage) -> None:
        """Replace the picture with `new_image` as one undoable step."""
        self.history.record(self.img.copy())
        self.img.replace_data(new_image)
        self.resize_to_image()
        self.edited.emit()

    def undo(self):
        prev = self.history.undo(self.img.copy())
        if prev is not None:
            self.img.replace_data(prev)
            self.resize_to_image()
            self.edited.emit()

    def redo(self):
        nxt = self.history.redo(self.img.copy())
        if nxt is not None:
            self.img.replace_data(nxt)
            self.resize_to_image()
            self.edited.emit()


class SpriteEditor(QWidget):
    """Pixel editor for one PNG file. Saves to the project after every change."""

    changed = Signal(str, bytes)               # path, PNG bytes

    TOOLS = (("pencil", "Pencil", "Draw (right mouse button erases)"), ("eraser", "Eraser", "Erase to transparent"),
             ("fill", "Fill", "Fill a region"), ("line", "Line", "Draw a line"),
             ("rect", "Rect", "Rectangle outline"), ("rect_fill", "Box", "Filled rectangle"),
             ("ellipse", "Oval", "Ellipse outline"), ("ellipse_fill", "Disc", "Filled ellipse"),
             ("picker", "Pick", "Pick a colour from the image"))

    def __init__(self, path: str, data: bytes, parent=None):
        super().__init__(parent)
        self.path = path
        try:
            image = PixelImage.from_png(data) if data else PixelImage(16, 16)
        except Exception as e:                       # PngError or a file that is not an image
            image = PixelImage(16, 16)
            self.load_error = "Could not read %s as a PNG (%s). Editing starts from a blank image." % (path, e)
        else:
            self.load_error = ""
        self.history = History()
        self.canvas = PixelCanvas(image, self.history)
        self.canvas.edited.connect(self._edited)
        self.canvas.picked.connect(self._picked)
        self._build()

    def _build(self):
        tools = QVBoxLayout()
        self._tool_buttons = _tool_buttons(tools, self.TOOLS, self._pick_tool)
        tools.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        side = QVBoxLayout()
        self.color_button = QPushButton("Colour…")
        self.color_button.clicked.connect(lambda checked=False: self._choose_color())
        self.color_swatch = QLabel()
        side.addLayout(_row(self.color_swatch, self.color_button))
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, rgb in enumerate(PALETTE):
            b = QToolButton()
            b.setStyleSheet(_swatch_css(rgb))
            b.clicked.connect(lambda checked=False, c=rgb: self.set_color(c + (255,)))
            grid.addWidget(b, i // 4, i % 4)
        side.addLayout(grid)
        self.brush_spin = _spin(1, 8, 1)
        self.brush_spin.valueChanged.connect(lambda v: setattr(self.canvas, "brush", int(v)))
        side.addLayout(_row(QLabel("Brush"), self.brush_spin))
        self.zoom_spin = _spin(1, 64, self.canvas.zoom)
        self.zoom_spin.valueChanged.connect(self._zoom)
        side.addLayout(_row(QLabel("Zoom"), self.zoom_spin))
        self.grid_check = QCheckBox("Pixel grid")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(self._grid)
        side.addWidget(self.grid_check)

        side.addWidget(QLabel("Image size"))
        self.w_spin = _spin(1, 1024, self.canvas.img.w)
        self.h_spin = _spin(1, 1024, self.canvas.img.h)
        apply_size = QPushButton("Resize")
        apply_size.clicked.connect(lambda checked=False: self._resize())
        side.addLayout(_row(self.w_spin, QLabel("x"), self.h_spin, apply_size))
        side.addWidget(QLabel("Frame size (sheet)"))
        self.fw_spin = _spin(1, 1024, self.canvas.img.w)
        self.fh_spin = _spin(1, 1024, self.canvas.img.h)
        self.fw_spin.valueChanged.connect(self._frames)
        self.fh_spin.valueChanged.connect(self._frames)
        side.addLayout(_row(self.fw_spin, QLabel("x"), self.fh_spin))
        self.frame_info = QLabel("")
        self.frame_info.setStyleSheet("color: %s;" % theme.MUTED)
        self.frame_info.setWordWrap(True)
        side.addWidget(self.frame_info)

        for text, fn in (("Flip horizontal", lambda: self._transform(lambda i: i.flipped(True))),
                         ("Flip vertical", lambda: self._transform(lambda i: i.flipped(False))),
                         ("Shift right", lambda: self._transform(lambda i: i.shifted(1, 0))),
                         ("Shift down", lambda: self._transform(lambda i: i.shifted(0, 1))),
                         ("Clear", lambda: self._transform(lambda i: PixelImage(i.w, i.h)))):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, f=fn: f())
            side.addWidget(b)
        undo, redo = QPushButton("Undo"), QPushButton("Redo")
        undo.clicked.connect(lambda checked=False: self.undo())
        redo.clicked.connect(lambda checked=False: self.redo())
        side.addLayout(_row(undo, redo))
        note = QLabel("Magenta (255, 0, 255) and transparent pixels are see-through in games.")
        note.setWordWrap(True)
        note.setStyleSheet("color: %s;" % theme.MUTED)
        side.addWidget(note)
        side.addStretch(1)
        side_box = QWidget()
        side_box.setLayout(side)
        side_box.setFixedWidth(210)

        layout = QHBoxLayout(self)
        layout.addLayout(tools)
        layout.addWidget(scroll, 1)
        layout.addWidget(side_box)
        self.set_color(self.canvas.color)
        self._frames()
        if self.load_error:
            QMessageBox.warning(self, "Sprite", self.load_error)

    # ---- actions -------------------------------------------------------------------------------
    def set_color(self, rgba) -> None:
        self.canvas.color = tuple(int(c) for c in rgba)
        self.color_swatch.setStyleSheet(_swatch_css(rgba))
        self.color_swatch.setToolTip("rgba%s" % (tuple(rgba),))

    def _choose_color(self):
        r, g, b, a = self.canvas.color
        picked = QColorDialog.getColor(QColor(r, g, b, a), self, "Drawing colour", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if picked.isValid():
            self.set_color((picked.red(), picked.green(), picked.blue(), picked.alpha()))

    def _picked(self, rgba):
        if rgba[3] == 0:
            self._pick_tool("eraser")
        else:
            self.set_color(rgba)
            self._pick_tool("pencil")

    def _pick_tool(self, key):
        self.canvas.tool = key
        if key in self._tool_buttons:
            self._tool_buttons[key].setChecked(True)

    def _zoom(self, value):
        self.canvas.zoom = int(value)
        self.canvas.resize_to_image()

    def _grid(self, on):
        self.canvas.show_grid = bool(on)
        self.canvas.update()

    def _frames(self, *_):
        img = self.canvas.img
        fw, fh = int(self.fw_spin.value()), int(self.fh_spin.value())
        self.canvas.frame_w, self.canvas.frame_h = fw, fh
        cols, rows = img.w // max(fw, 1), img.h // max(fh, 1)
        self.frame_info.setText("%d frame(s): load_sprite(\"%s\", %d, %d)" % (cols * rows, self.path, fw, fh))
        self.canvas.update()

    def _resize(self):
        self.canvas.apply(self.canvas.img.resized(int(self.w_spin.value()), int(self.h_spin.value())))

    def _transform(self, fn):
        self.canvas.apply(fn(self.canvas.img))

    def _edited(self):
        img = self.canvas.img
        self.w_spin.setValue(img.w)
        self.h_spin.setValue(img.h)
        self._frames()
        self.changed.emit(self.path, img.to_png())

    def undo(self):
        self.canvas.undo()

    def redo(self):
        self.canvas.redo()


# ===================================================================================================
#  Tilemap editor
# ===================================================================================================
class TilePalette(QWidget):
    selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None            # QImage of the tileset
        self.tile_w = self.tile_h = 8
        self.zoom = 3
        self.current = 0
        self.solid = set()

    def set_tileset(self, qimage, tile_w, tile_h):
        self.image, self.tile_w, self.tile_h = qimage, tile_w, tile_h
        w = qimage.width() * self.zoom if qimage is not None else 120
        h = qimage.height() * self.zoom if qimage is not None else 40
        self.setFixedSize(max(w, 40), max(h, 20))
        self.update()

    def count(self) -> int:
        if self.image is None:
            return 0
        return (self.image.width() // self.tile_w) * (self.image.height() // self.tile_h)

    def paintEvent(self, event):
        p = QPainter(self)
        if self.image is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no tileset image")
            return
        _checker(p, QRect(0, 0, self.image.width() * self.zoom, self.image.height() * self.zoom))
        p.drawImage(QRect(0, 0, self.image.width() * self.zoom, self.image.height() * self.zoom), self.image)
        cols = max(1, self.image.width() // self.tile_w)
        tw, th = self.tile_w * self.zoom, self.tile_h * self.zoom
        for n in self.solid:
            if 0 <= n < self.count():
                p.fillRect((n % cols) * tw, (n // cols) * th, tw, th, QColor(255, 0, 0, 70))
        p.setPen(QPen(QColor(255, 255, 255, 60)))
        for c in range(1, cols + 1):
            p.drawLine(c * tw, 0, c * tw, self.height())
        for r in range(1, self.image.height() // self.tile_h + 1):
            p.drawLine(0, r * th, self.width(), r * th)
        if 0 <= self.current < self.count():
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRect((self.current % cols) * tw, (self.current // cols) * th, tw, th)

    def mousePressEvent(self, event):
        if self.image is None:
            return
        pos = event.position()
        cols = max(1, self.image.width() // self.tile_w)
        n = int(pos.y() // (self.tile_h * self.zoom)) * cols + int(pos.x() // (self.tile_w * self.zoom))
        if 0 <= n < self.count():
            self.current = n
            self.selected.emit(n)
            self.update()


class MapCanvas(QWidget):
    edited = Signal()
    hovered = Signal(str)
    picked = Signal(int)

    def __init__(self, doc: TilemapDoc, history: History, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.history = history
        self.tileset = None
        self.zoom = 3
        self.tool = "paint"
        self.tile = 0
        self.layer = 0
        self.show_grid = True
        self.show_solid = True
        self._base = None
        self._start = None
        self._erase = False
        self.setMouseTracking(True)
        self.resize_to_map()

    def resize_to_map(self):
        self.setFixedSize(self.doc.w * self.doc.tile_w * self.zoom, self.doc.h * self.doc.tile_h * self.zoom)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        d, z = self.doc, self.zoom
        tw, th = d.tile_w * z, d.tile_h * z
        _checker(p, QRect(0, 0, d.w * tw, d.h * th), 8)
        cols = max(1, self.tileset.width() // d.tile_w) if self.tileset is not None else 1
        for layer in d.layers:
            if not layer.visible:
                continue
            for i, n in enumerate(layer.data):
                if n < 0:
                    continue
                x, y = (i % d.w) * tw, (i // d.w) * th
                if self.tileset is not None:
                    p.drawImage(QRect(x, y, tw, th), self.tileset,
                                QRect((n % cols) * d.tile_w, (n // cols) * d.tile_h, d.tile_w, d.tile_h))
                else:
                    p.fillRect(x, y, tw, th, QColor(120, 120, 120))
                if self.show_solid and n in d.solid:
                    p.fillRect(x, y, tw, th, QColor(255, 0, 0, 70))
        if self.show_grid:
            p.setPen(QPen(QColor(255, 255, 255, 40)))
            for c in range(1, d.w):
                p.drawLine(c * tw, 0, c * tw, d.h * th)
            for r in range(1, d.h):
                p.drawLine(0, r * th, d.w * tw, r * th)

    def _cell(self, event):
        pos = event.position()
        return int(pos.x() // (self.doc.tile_w * self.zoom)), int(pos.y() // (self.doc.tile_h * self.zoom))

    def mousePressEvent(self, event):
        x, y = self._cell(event)
        if not self.doc.inside(x, y):
            return
        if self.tool == "picker":
            n = self.doc.get(self.layer, x, y)
            if n >= 0:
                self.tile = n
                self.picked.emit(n)
            return
        self._erase = event.button() == Qt.MouseButton.RightButton
        self._base = self.doc.snapshot()
        self._start = (x, y)
        tile = -1 if self._erase else self.tile
        if self.tool == "fill":
            self.doc.flood_fill(self.layer, x, y, tile)
            self._finish()
        elif self.tool == "paint":
            self.doc.set(self.layer, x, y, tile)
        else:
            self.doc.fill_rect(self.layer, x, y, x, y, tile)
        self.update()

    def mouseMoveEvent(self, event):
        x, y = self._cell(event)
        self.hovered.emit("tile (%d, %d)  number %d" % (x, y, self.doc.get(self.layer, x, y)) if self.doc.inside(x, y) else "")
        if self._base is None or not self.doc.inside(x, y):
            return
        tile = -1 if self._erase else self.tile
        if self.tool == "paint":
            self.doc.set(self.layer, x, y, tile)
        elif self.tool == "rect":
            self.doc.restore(self._base)
            self.doc.fill_rect(self.layer, self._start[0], self._start[1], x, y, tile)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._base is not None:
            self._finish()

    def _finish(self):
        base, self._base = self._base, None
        if self.doc.snapshot() != base:
            self.history.record(base)
            self.edited.emit()
        self.update()


class TilemapEditor(QWidget):
    changed = Signal(str, str)                 # path, JSON text

    def __init__(self, path: str, text: str, read_bytes, list_pngs, parent=None):
        super().__init__(parent)
        self.path = path
        self._read_bytes = read_bytes          # project path -> bytes (raises on a missing file)
        self._list_pngs = list_pngs            # () -> project PNG paths
        self.load_error = ""
        try:
            self.doc = TilemapDoc.from_json(text)
        except TilemapFormatError as e:
            self.doc = TilemapDoc.new("", 8, 8, 30, 17)
            self.load_error = str(e)
        self.history = History()
        self.canvas = MapCanvas(self.doc, self.history)
        self.canvas.edited.connect(self._edited)
        self.canvas.picked.connect(self._picked)
        self.palette = TilePalette()
        self.palette.selected.connect(self._tile_selected)
        self._build()
        self.reload_tileset()
        self._fill_layers()
        if self.load_error:
            QMessageBox.warning(self, "Tilemap", self.load_error)

    # ---- layout ---------------------------------------------------------------------------------
    def _build(self):
        tools = QVBoxLayout()
        self._buttons = _tool_buttons(tools, (("paint", "Paint", "Paint tiles (right mouse button erases)"),
                                              ("rect", "Box", "Fill a rectangle"), ("fill", "Fill", "Flood fill"),
                                              ("picker", "Pick", "Pick the tile under the mouse")),
                                      self._pick_tool, first="paint")
        tools.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.status = QLabel("")
        self.status.setStyleSheet("color: %s;" % theme.MUTED)
        self.canvas.hovered.connect(self.status.setText)
        centre = QVBoxLayout()
        centre.addWidget(scroll, 1)
        centre.addWidget(self.status)

        side = QVBoxLayout()
        self.tileset_label = QLabel("")
        self.tileset_label.setWordWrap(True)
        change = QPushButton("Tileset image…")
        change.clicked.connect(lambda checked=False: self._choose_tileset())
        side.addWidget(self.tileset_label)
        side.addWidget(change)
        self.tw_spin = _spin(1, 256, self.doc.tile_w)
        self.th_spin = _spin(1, 256, self.doc.tile_h)
        retile = QPushButton("Set")
        retile.clicked.connect(lambda checked=False: self._set_tile_size())
        side.addLayout(_row(QLabel("Tile"), self.tw_spin, QLabel("x"), self.th_spin, retile))
        pal_scroll = QScrollArea()
        pal_scroll.setWidget(self.palette)
        pal_scroll.setMinimumHeight(140)
        side.addWidget(pal_scroll, 1)
        self.solid_check = QCheckBox("Selected tile is solid")
        self.solid_check.toggled.connect(self._solid_toggled)
        side.addWidget(self.solid_check)

        side.addWidget(QLabel("Layers (last is drawn on top)"))
        self.layer_list = QListWidget()
        self.layer_list.setMaximumHeight(110)
        self.layer_list.currentRowChanged.connect(self._layer_selected)
        side.addWidget(self.layer_list)
        buttons = QHBoxLayout()
        for text, fn in (("+", self._add_layer), ("−", self._remove_layer), ("Rename", self._rename_layer),
                         ("▲", lambda: self._move_layer(1)), ("▼", lambda: self._move_layer(-1)),
                         ("Eye", self._toggle_layer)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(lambda checked=False, f=fn: f())
            buttons.addWidget(b)
        side.addLayout(buttons)

        self.mw_spin = _spin(1, 1000, self.doc.w)
        self.mh_spin = _spin(1, 1000, self.doc.h)
        resize = QPushButton("Resize")
        resize.clicked.connect(lambda checked=False: self._resize_map())
        side.addLayout(_row(QLabel("Map"), self.mw_spin, QLabel("x"), self.mh_spin, resize))
        self.zoom_spin = _spin(1, 16, self.canvas.zoom)
        self.zoom_spin.valueChanged.connect(self._zoom)
        side.addLayout(_row(QLabel("Zoom"), self.zoom_spin))
        grid, solid = QCheckBox("Grid"), QCheckBox("Show solid")
        grid.setChecked(True)
        solid.setChecked(True)
        grid.toggled.connect(lambda on: self._view("show_grid", on))
        solid.toggled.connect(lambda on: self._view("show_solid", on))
        side.addLayout(_row(grid, solid))
        undo, redo = QPushButton("Undo"), QPushButton("Redo")
        undo.clicked.connect(lambda checked=False: self.undo())
        redo.clicked.connect(lambda checked=False: self.redo())
        side.addLayout(_row(undo, redo))
        box = QWidget()
        box.setLayout(side)
        box.setFixedWidth(260)

        layout = QHBoxLayout(self)
        layout.addLayout(tools)
        layout.addLayout(centre, 1)
        layout.addWidget(box)

    # ---- tileset -------------------------------------------------------------------------------
    def reload_tileset(self) -> None:
        d = self.doc
        qimg, note = None, ""
        if not d.tileset:
            note = "No tileset yet: choose a PNG."
        else:
            try:
                png_bytes = self._read_bytes(d.tileset)
                image = PixelImage.from_png(png_bytes)
                qimg = _qimage(bytes(image.data), image.w, image.h)
                count = (image.w // d.tile_w) * (image.h // d.tile_h)
                note = "%s: %d tiles" % (d.tileset, count)
            except Exception as e:
                note = "Can't read tileset %s (%s)" % (d.tileset, e)
        self.tileset_label.setText(note)
        self.canvas.tileset = qimg
        self.palette.solid = d.solid
        self.palette.set_tileset(qimg, d.tile_w, d.tile_h)
        self.canvas.update()

    def _choose_tileset(self):
        from PySide6.QtWidgets import QInputDialog
        choices = self._list_pngs()
        if not choices:
            QMessageBox.information(self, "Tileset", "Import or create a PNG in the project first.")
            return
        current = choices.index(self.doc.tileset) if self.doc.tileset in choices else 0
        name, ok = QInputDialog.getItem(self, "Tileset image", "PNG file:", choices, current, False)
        if ok and name:
            self._change(lambda: setattr(self.doc, "tileset", name), reload_tiles=True)

    def _set_tile_size(self):
        tw, th = int(self.tw_spin.value()), int(self.th_spin.value())
        self._change(lambda: (setattr(self.doc, "tile_w", tw), setattr(self.doc, "tile_h", th)), reload_tiles=True)

    # ---- editing -------------------------------------------------------------------------------
    def _change(self, fn, reload_tiles: bool = False):
        """Apply a document change as one undo step, then refresh and save."""
        before = self.doc.snapshot()
        fn()
        if reload_tiles:
            self.reload_tileset()
            count = self.palette.count()
            if count:
                self.doc.clamp_to_tileset(count)
        if self.doc.snapshot() != before:
            self.history.record(before)
        self._refresh_all()
        self._edited()

    def _refresh_all(self):
        self.canvas.layer = max(0, min(self.canvas.layer, len(self.doc.layers) - 1))
        self.canvas.resize_to_map()
        self.mw_spin.setValue(self.doc.w)
        self.mh_spin.setValue(self.doc.h)
        self.tw_spin.setValue(self.doc.tile_w)
        self.th_spin.setValue(self.doc.tile_h)
        self._fill_layers()
        self.palette.solid = self.doc.solid
        self.palette.update()

    def _edited(self):
        self.changed.emit(self.path, self.doc.to_json())

    def _pick_tool(self, key):
        self.canvas.tool = key

    def _tile_selected(self, n):
        self.canvas.tile = n
        self.solid_check.blockSignals(True)
        self.solid_check.setChecked(n in self.doc.solid)
        self.solid_check.blockSignals(False)
        self._pick_tool("paint")
        self._buttons["paint"].setChecked(True)

    def _picked(self, n):
        self.palette.current = n
        self.palette.update()
        self._tile_selected(n)

    def _solid_toggled(self, on):
        n = self.palette.current

        def flip():
            (self.doc.solid.add if on else self.doc.solid.discard)(n)
        self._change(flip)

    def _zoom(self, v):
        self.canvas.zoom = int(v)
        self.canvas.resize_to_map()

    def _view(self, attr, on):
        setattr(self.canvas, attr, bool(on))
        self.canvas.update()

    def _resize_map(self):
        w, h = int(self.mw_spin.value()), int(self.mh_spin.value())
        try:
            self._change(lambda: self.doc.resize(w, h))
        except TilemapFormatError as e:
            QMessageBox.warning(self, "Tilemap", str(e))

    # ---- layers --------------------------------------------------------------------------------
    def _fill_layers(self):
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for layer in self.doc.layers:
            self.layer_list.addItem(layer.name + ("" if layer.visible else "  (hidden)"))
        self.layer_list.setCurrentRow(self.canvas.layer)
        self.layer_list.blockSignals(False)

    def _layer_selected(self, row):
        if row >= 0:
            self.canvas.layer = row

    def _add_layer(self):
        self._change(lambda: setattr(self.canvas, "layer", self.doc.add_layer("layer")))

    def _remove_layer(self):
        row = self.canvas.layer
        if len(self.doc.layers) <= 1:
            QMessageBox.information(self, "Layers", "A map needs at least one layer.")
            return
        self._change(lambda: self.doc.remove_layer(row))

    def _rename_layer(self):
        from PySide6.QtWidgets import QInputDialog
        row = self.canvas.layer
        name, ok = QInputDialog.getText(self, "Rename layer", "Name:", text=self.doc.layers[row].name)
        if ok and name.strip():
            if not any(layer.name == name.strip() for i, layer in enumerate(self.doc.layers) if i != row):
                self._change(lambda: self.doc.rename_layer(row, name))
            else:
                QMessageBox.warning(self, "Layers", "Another layer already uses that name.")

    def _move_layer(self, delta):
        row = self.canvas.layer
        self._change(lambda: setattr(self.canvas, "layer", self.doc.move_layer(row, delta)))

    def _toggle_layer(self):
        layer = self.doc.layers[self.canvas.layer]
        self._change(lambda: setattr(layer, "visible", not layer.visible))

    # ---- undo ----------------------------------------------------------------------------------
    def undo(self):
        snap = self.history.undo(self.doc.snapshot())
        if snap is not None:
            self.doc.restore(snap)
            self.reload_tileset()
            self._refresh_all()
            self._edited()

    def redo(self):
        snap = self.history.redo(self.doc.snapshot())
        if snap is not None:
            self.doc.restore(snap)
            self.reload_tileset()
            self._refresh_all()
            self._edited()


# ===================================================================================================
#  Sound editor and WAV player
# ===================================================================================================
class SoundEditor(QWidget):
    changed = Signal(str, str)                 # path, JSON text

    def __init__(self, path: str, text: str, play, parent=None):
        super().__init__(parent)
        self.path = path
        self._play = play                      # play(bytes): send one audio message to the preview speaker
        self.load_error = ""
        try:
            self.doc = SoundDoc.from_json(text) if text.strip() else SoundDoc(notes=[["C4", 200], ["E4", 200], ["G4", 300]])
        except AssetError as e:
            self.doc = SoundDoc(notes=[["C4", 200]])
            self.load_error = str(e)
        self._build()
        self._fill()
        if self.load_error:
            QMessageBox.warning(self, "Sound", self.load_error)

    def _build(self):
        layout = QVBoxLayout(self)
        self.wave = QComboBox()
        self.wave.addItems(list(assets.WAVES))
        self.wave.setCurrentText(self.doc.wave)
        self.wave.currentTextChanged.connect(self._wave)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.doc.volume * 100))
        self.volume.valueChanged.connect(self._volume)
        layout.addLayout(_row(QLabel("Wave"), self.wave, QLabel("Volume"), self.volume))

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._row_selected)
        layout.addWidget(self.list, 1)

        self.note = QComboBox()
        self.note.setEditable(True)
        self.note.addItems(["rest"] + audio_note_names.NAMES)
        self.note.setCurrentText("C4")
        self.length = _spin(1, 60000, 200)
        add, update, remove = QPushButton("Add"), QPushButton("Update selected"), QPushButton("Remove")
        up, down = QToolButton(), QToolButton()
        up.setText("▲")
        down.setText("▼")
        add.clicked.connect(lambda checked=False: self._add())
        update.clicked.connect(lambda checked=False: self._update())
        remove.clicked.connect(lambda checked=False: self._remove())
        up.clicked.connect(lambda checked=False: self._move(-1))
        down.clicked.connect(lambda checked=False: self._move(1))
        layout.addLayout(_row(QLabel("Note"), self.note, QLabel("ms"), self.length, add, update, remove, up, down))

        keys = QHBoxLayout()
        keys.addWidget(QLabel("Keys"))
        self.octave = _spin(1, 7, 4)
        keys.addWidget(self.octave)
        for name in ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"):
            b = QPushButton(name)
            b.setMaximumWidth(42)
            b.clicked.connect(lambda checked=False, n=name: self._key(n))
            keys.addWidget(b)
        keys.addStretch(1)
        layout.addLayout(keys)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        play, stop = QPushButton("▶ Play"), QPushButton("■ Stop")
        play.clicked.connect(lambda checked=False: self._play_all())
        stop.clicked.connect(lambda checked=False: self._play(audio_msgs.stop_message(None)))
        layout.addLayout(_row(play, stop))

    # ---- document <-> widgets ---------------------------------------------------------------------
    def _fill(self):
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for note, ms in self.doc.notes:
            self.list.addItem("%-6s %5d ms" % (note, ms))
        if self.doc.notes:
            self.list.setCurrentRow(max(0, min(row, len(self.doc.notes) - 1)))
        self.list.blockSignals(False)
        err = self.doc.error()
        self.info.setText(("Problem: %s" % err) if err else "%d notes, %.2f seconds. In a game: play_sound(load_sound(\"%s\"))"
                          % (len(self.doc.notes), self.doc.duration_ms() / 1000, self.path))
        self.info.setStyleSheet("color: %s;" % (theme.ERROR if err else theme.MUTED))

    def _save(self):
        self._fill()
        self.changed.emit(self.path, self.doc.to_json())

    def _row_selected(self, row):
        if 0 <= row < len(self.doc.notes):
            note, ms = self.doc.notes[row]
            self.note.setCurrentText(str(note))
            self.length.setValue(int(ms))

    def _wave(self, text):
        self.doc.wave = text
        self._save()

    def _volume(self, v):
        self.doc.volume = v / 100.0
        self._save()

    def _current_note(self):
        text = self.note.currentText().strip()
        try:
            return float(text) if text.replace(".", "", 1).isdigit() else text
        except ValueError:
            return text

    def _add(self):
        self.doc.add_note(self._current_note(), int(self.length.value()))
        self._save()
        self.list.setCurrentRow(len(self.doc.notes) - 1)

    def _update(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.doc.notes):
            self.doc.notes[row] = [self._current_note(), int(self.length.value())]
            self._save()

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.doc.notes):
            del self.doc.notes[row]
            self._save()

    def _move(self, delta):
        row = self.list.currentRow()
        if 0 <= row < len(self.doc.notes):
            new = self.doc.move_note(row, delta)
            self._save()
            self.list.setCurrentRow(new)

    def _key(self, name):
        note = "%s%d" % (name, int(self.octave.value()))
        self.note.setCurrentText(note)
        self._audition([[note, int(self.length.value())]])
        self._add()

    def _audition(self, notes):
        try:
            snd = assets.tones_from_notes(notes, "", self.doc.wave, self.doc.volume)
        except AssetError:
            return
        self._play(audio_msgs.load_message(snd))
        self._play(audio_msgs.play_message(snd))

    def _play_all(self):
        try:
            snd = self.doc.to_sound()
        except AssetError as e:
            self.info.setText("Problem: %s" % e)
            return
        self._play(audio_msgs.load_message(snd))
        self._play(audio_msgs.play_message(snd))


class WavViewer(QWidget):
    """Plays a .wav file from the project (the same conversion the game will use)."""

    def __init__(self, path: str, data: bytes, play, parent=None):
        super().__init__(parent)
        self.path = path
        self._play = play
        self.sound = None
        try:
            self.sound = assets.sound_from_wav(data, path)
            text = ("%s\n\nPlays at %d Hz, 8-bit mono, %.2f seconds when converted for the game "
                    "(WAV files are never edited here).\n\nIn a game: play_sound(load_sound(\"%s\"))"
                    % (path, self.sound.rate, self.sound.duration_ms / 1000, path))
        except AssetError as e:
            text = "%s\n\n%s" % (path, e)
        label = QLabel(text)
        label.setWordWrap(True)
        play_button, stop_button = QPushButton("▶ Play"), QPushButton("■ Stop")
        play_button.setEnabled(self.sound is not None)
        play_button.clicked.connect(lambda checked=False: self._go())
        stop_button.clicked.connect(lambda checked=False: self._play(audio_msgs.stop_message(None)))
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addLayout(_row(play_button, stop_button))
        layout.addStretch(1)

    def _go(self):
        self._play(audio_msgs.load_message(self.sound))
        self._play(audio_msgs.play_message(self.sound))
