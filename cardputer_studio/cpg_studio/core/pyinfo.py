"""Introspection helpers for completions and hover (builtins and a few safe stdlib modules)."""
from __future__ import annotations

import builtins
import importlib
import inspect
from functools import lru_cache

# Standard-library modules that are safe to import in the IDE (no side effects) and that also
# exist, at least partly, in MicroPython.
SAFE_MODULES = ("math", "random", "time", "collections", "itertools", "string", "json", "struct", "re",
                "functools", "operator", "bisect", "heapq", "array")

_HIDDEN_BUILTINS = {"copyright", "credits", "license", "exit", "help"}


def first_line(doc: str | None) -> str:
    return inspect.cleandoc(doc or "").split("\n", 1)[0].strip()


def _signature(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return ""


def kind_of(obj) -> str:
    if inspect.isclass(obj):
        return "class"
    if callable(obj):
        return "function"
    return "constant"


@lru_cache(maxsize=None)
def _module(name: str):
    if name not in SAFE_MODULES:
        return None
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def is_safe_module(name: str) -> bool:
    return _module(name) is not None


@lru_cache(maxsize=None)
def module_members(name: str):
    """[(member, kind, one-line detail), ...] for a safe module, or []."""
    mod = _module(name)
    if mod is None:
        return []
    out = []
    for attr in sorted(dir(mod)):
        if attr.startswith("_"):
            continue
        obj = getattr(mod, attr, None)
        out.append((attr, kind_of(obj), (name + "." + attr + _signature(obj)) if callable(obj) else first_line(type(obj).__doc__)))
    return out


def member_doc(module: str, attr: str):
    """(kind, 'module.attr(sig)', doc) for a member of a safe module, or None."""
    mod = _module(module)
    if mod is None or attr.startswith("_") or not hasattr(mod, attr):
        return None
    obj = getattr(mod, attr)
    sig = _signature(obj) if callable(obj) else ""
    doc = inspect.getdoc(obj) if (callable(obj) or inspect.ismodule(obj)) else ""
    return kind_of(obj), "%s.%s%s" % (module, attr, sig), doc or ""


def builtin_names():
    return sorted(n for n in dir(builtins) if not n.startswith("_") and n not in _HIDDEN_BUILTINS)


def builtin_doc(name: str):
    """(kind, 'name(sig)', doc) for a Python builtin, or None."""
    if name.startswith("_") or name in _HIDDEN_BUILTINS or not hasattr(builtins, name):
        return None
    obj = getattr(builtins, name)
    sig = _signature(obj) if callable(obj) else ""
    return kind_of(obj), name + sig, inspect.getdoc(obj) or ""
