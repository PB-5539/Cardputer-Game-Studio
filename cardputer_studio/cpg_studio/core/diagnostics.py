"""Code diagnostics for the editor and the Problems panel (no Qt).

Syntax errors always come from Python's own parser. If `pyflakes` is installed it adds warnings
for undefined names, unused imports and so on. Engine functions (clear, rect, ...) are passed in
as extra builtins so they aren't reported as undefined.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int          # 1-based
    col: int           # 0-based
    end_col: int       # 0-based, exclusive; <= col means "rest of the line"
    severity: str      # "error" | "warning"
    message: str
    source: str        # "python" | "pyflakes"


def _syntax_error(path: str, text: str, e: SyntaxError) -> Diagnostic:
    line = max(1, e.lineno or 1)
    col = max(0, (e.offset or 1) - 1)
    end_col = 0
    end_offset = getattr(e, "end_offset", None)
    if end_offset and getattr(e, "end_lineno", line) == line and end_offset > e.offset:
        end_col = end_offset - 1
    return Diagnostic(path, line, col, end_col, "error", e.msg or "invalid syntax", "python")


def check_source(text: str, path: str = "<file>", builtins=()) -> list[Diagnostic]:
    try:
        tree = ast.parse(text, path)
    except SyntaxError as e:
        return [_syntax_error(path, text, e)]
    except (ValueError, RecursionError, MemoryError) as e:     # null bytes, absurd nesting
        return [Diagnostic(path, 1, 0, 0, "error", str(e) or "cannot parse file", "python")]
    out: list[Diagnostic] = []
    try:
        from pyflakes.checker import Checker
    except ImportError:
        return out
    try:
        checker = Checker(tree, path, builtins=set(builtins))
        for m in checker.messages:
            out.append(Diagnostic(path, m.lineno, m.col, 0, "warning", m.message % m.message_args, "pyflakes"))
    except Exception:           # a linter bug must never break editing
        return out
    out.sort(key=lambda d: (d.line, d.col))
    return out
