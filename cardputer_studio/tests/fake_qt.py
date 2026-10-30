"""A stand-in for PySide6, used only when the real thing isn't installed (e.g. in a CI sandbox).

It does NOT check that Qt calls are valid. What it does check: every module imports, objects
are wired together correctly (signals and slots), my own attribute and method names exist, and
the window logic (open, edit, save, rename, run) works end to end. To keep typos in my own
snake_case names from being silently accepted, only Qt-looking names (camelCase, PascalCase, or
a short allowlist of Qt's one-word names) are auto-created.
"""
from __future__ import annotations

import inspect
import re
import sys
import types

_CAMEL = re.compile(r"^([a-z]+[A-Z]\w*|[A-Z]\w*)$")
_QT_WORDS = {
    "accept", "adjusted", "bottom", "center", "clear", "close", "connect", "contains", "copy", "count",
    "cut", "data", "document", "emit", "event", "exec", "finished", "find", "height", "hide", "ignore",
    "information", "insert", "key", "kill", "left", "modifiers", "move", "next", "paste", "pos", "position",
    "question", "rect", "redo", "resize", "right", "scroll", "show", "start", "state", "text", "timeout",
    "top", "translated", "triggered", "type", "undo", "update", "value", "viewport", "warning", "widget",
    "width", "write", "x", "y", "format", "font", "cursor", "item", "block", "name", "toggled", "clicked", "activated", "popup", "complete", "stop", "play", "write", "available", "copy", "cut", "paste",
}


def _qt_name_ok(name: str) -> bool:
    return not name.startswith("_") and (bool(_CAMEL.match(name)) or name in _QT_WORDS)


def _call_adaptive(fn, args):
    """Call a slot with as many of `args` as it accepts, like PySide does."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return fn(*args)
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return fn(*args)
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return fn(*args[:len(positional)])


class _Dyn:
    """Accepts any Qt-looking attribute or call and returns another _Dyn; also acts as a signal."""

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_slots", [])
        object.__setattr__(self, "_dyn_cache", {})

    def __getattr__(self, name):
        if not _qt_name_ok(name):
            raise AttributeError("%s has no attribute %r (not a Qt-looking name)" % (type(self).__name__, name))
        cache = self.__dict__.setdefault("_dyn_cache", {})
        if name not in cache:
            cache[name] = _Dyn()
        return cache[name]

    def __call__(self, *args, **kwargs):
        return _Dyn()

    def __getitem__(self, key):          # overloaded signals: signal[str]
        return self

    # signal behaviour
    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            _call_adaptive(slot, args)

    # number-ish / container-ish behaviour so arithmetic on Qt return values doesn't blow up
    def _num(self, *a):
        return _Dyn()

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __floordiv__ = _num
    __or__ = __ror__ = __and__ = __rand__ = _num

    def __neg__(self):
        return _Dyn()

    def __int__(self):
        return 0

    __index__ = __int__

    def __float__(self):
        return 0.0

    def __round__(self, n=None):
        return 0

    def __bool__(self):
        return True

    def __lt__(self, o):
        return False

    __le__ = __gt__ = __ge__ = __lt__

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0


class _Meta(type):
    def __getattr__(cls, name):
        if not _qt_name_ok(name):
            raise AttributeError("%s has no attribute %r" % (cls.__name__, name))
        value = _Dyn()
        type.__setattr__(cls, name, value)
        return value


class _Signal:
    """Class-level Signal(...) declaration: each instance gets its own connection list."""

    def __init__(self, *types):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        store = obj.__dict__.setdefault("_signals", {})
        if self.name not in store:
            store[self.name] = _Dyn()
        return store[self.name]


class _Widget(_Dyn, metaclass=_Meta):
    pass


# ---- classes with real behaviour (the code under test relies on their results) -------------------
class _PlainTextEdit(_Widget):
    def __init__(self, *a, **k):
        super().__init__()
        self._text = ""

    def setPlainText(self, text):
        self._text = text
        self.textChanged.emit()

    def toPlainText(self):
        return self._text

    def blockCount(self):
        return self._text.count("\n") + 1


class _TabWidget(_Widget):
    def __init__(self, *a, **k):
        super().__init__()
        self._tabs = []          # [widget, title]
        self._current = None

    def addTab(self, widget, title):
        self._tabs.append([widget, title])
        self.tabInserted(len(self._tabs) - 1)
        return len(self._tabs) - 1

    def removeTab(self, index):
        self._tabs.pop(index)
        self.tabRemoved(index)

    def tabInserted(self, index):
        pass

    def tabRemoved(self, index):
        pass

    def count(self):
        return len(self._tabs)

    def widget(self, index):
        return self._tabs[index][0]

    def indexOf(self, widget):
        return next((i for i, (w, _) in enumerate(self._tabs) if w is widget), -1)

    def setCurrentWidget(self, widget):
        self._current = widget

    def currentWidget(self):
        return self._current if self._current is not None else (self._tabs[-1][0] if self._tabs else None)

    def setTabText(self, index, text):
        self._tabs[index][1] = text

    def tabText(self, index):
        return self._tabs[index][1]


class _Stacked(_Widget):
    def __init__(self, *a, **k):
        super().__init__()
        self._widgets, self._cur = [], None

    def addWidget(self, w):
        self._widgets.append(w)

    def setCurrentWidget(self, w):
        self._cur = w

    def currentWidget(self):
        return self._cur


class _TreeItem(_Widget):
    def __init__(self, parent_or_texts=None, texts=None):
        super().__init__()
        self._children, self._data, self._expanded = [], {}, False
        self._text = ""
        if isinstance(parent_or_texts, list):
            texts = parent_or_texts
        elif parent_or_texts is not None:
            parent_or_texts._children.append(self)
        if texts:
            self._text = texts[0]

    def text(self, col=0):
        return self._text

    def childCount(self):
        return len(self._children)

    def child(self, i):
        return self._children[i]

    def setData(self, col, role, value):
        self._data[role] = value

    def data(self, col, role):
        return self._data.get(role)

    def setExpanded(self, v):
        self._expanded = bool(v)

    def isExpanded(self):
        return self._expanded

    def font(self, col=0):
        return _Dyn()


class _Tree(_Widget):
    def __init__(self, *a, **k):
        super().__init__()
        self._top, self._current = [], None

    def clear(self):
        self._top = []

    def addTopLevelItem(self, item):
        self._top.append(item)

    def topLevelItemCount(self):
        return len(self._top)

    def topLevelItem(self, i):
        return self._top[i]

    def setCurrentItem(self, item):
        self._current = item

    def currentItem(self):
        return self._current


class _ListWidget(_Widget):
    def __init__(self, *a, **k):
        super().__init__()
        self._items = []

    def clear(self):
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]


class _ListItem(_Widget):
    def __init__(self, text="", *a):
        super().__init__()
        self._text, self._data = text, {}

    def text(self):
        return self._text

    def setData(self, role, value):
        self._data[role] = value

    def data(self, role):
        return self._data.get(role)


class _Settings(_Widget):
    _store: dict = {}

    def value(self, key, default=None):
        return self._store.get(key, default)

    def setValue(self, key, value):
        self._store[key] = value


class _Application(_Widget):
    _focus = None

    @staticmethod
    def focusWidget():
        return _Application._focus

    @staticmethod
    def style():
        return _Dyn()


_REAL = {
    "QPlainTextEdit": _PlainTextEdit, "QTabWidget": _TabWidget, "QStackedWidget": _Stacked,
    "QTreeWidgetItem": _TreeItem, "QTreeWidget": _Tree, "QListWidget": _ListWidget,
    "QListWidgetItem": _ListItem, "QSettings": _Settings, "QApplication": _Application,
}

# Qt names that are plain value classes or must exist before being used as base classes
_BASES = {"QMainWindow": _Widget, "QWidget": _Widget, "QObject": _Widget}


class _FakeModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "Signal":
            value = _Signal
        elif name == "Qt":
            value = _Dyn()
        elif name in _REAL:
            value = _REAL[name]
        elif name.startswith("Q"):
            value = _Meta(name, (_Widget,), {})
        else:
            raise AttributeError(name)
        setattr(self, name, value)
        return value


def install() -> None:
    """Register fake PySide6 modules (only if the real package is missing)."""
    root = _FakeModule("PySide6")
    root.__path__ = []                       # behave like a package
    sys.modules["PySide6"] = root
    for sub in ("QtCore", "QtGui", "QtWidgets", "QtMultimedia"):
        mod = _FakeModule("PySide6." + sub)
        sys.modules["PySide6." + sub] = mod
        setattr(root, sub, mod)
    # one shared settings store and application object across the three fake modules
    for sub in ("QtCore", "QtGui", "QtWidgets", "QtMultimedia"):
        sys.modules["PySide6." + sub]._real = _REAL
