"""Line-by-line Python scanner for syntax highlighting (no Qt, so it can be tested).

highlight_line(text, state) -> (spans, new_state)
  spans: list of (start, length, kind) where kind is one of KINDS
  state: 0 normal, 1 inside a triple-single-quote string, 2 inside a triple-double-quote string
The Qt highlighter feeds each block through this, carrying `state` from line to line.
"""
from __future__ import annotations

import builtins
import keyword
import re

KINDS = ("keyword", "constant", "builtin", "api", "string", "comment", "number",
         "decorator", "definition", "self")

_KEYWORDS = frozenset(keyword.kwlist) - {"True", "False", "None"}
_KEYWORDS |= {"match", "case"}        # soft keywords; fine to colour
_CONSTANTS = frozenset({"True", "False", "None"})
_BUILTINS = frozenset(n for n in dir(builtins) if n[:1].islower() and not n.startswith("_"))
_IDENT = re.compile(r"[^\W\d]\w*")
_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+"
    r"|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?[jJ]?")
_STRING_PREFIX = re.compile(r"[rRbBfFuU]{1,2}$")


def _string_end(text: str, i: int, quote: str) -> int:
    """Index just past the closing `quote`, scanning from i; -1 if the line ends first."""
    n, q = len(text), len(quote)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if text.startswith(quote, i):
            return i + q
        i += 1
    return -1


def highlight_line(text: str, state: int = 0, api_names=frozenset()):
    spans: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    if state:
        quote = "'''" if state == 1 else '"""'
        end = _string_end(text, 0, quote)
        if end == -1:
            return ([(0, n, "string")] if n else []), state
        spans.append((0, end, "string"))
        i, state = end, 0
    expect_def = False
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "#":
            spans.append((i, n - i, "comment"))
            break
        if c in "'\"":
            start, i, state = _scan_string(text, i, i, spans)
            continue
        if c == "@" and not spans and not text[:i].strip():
            m = re.compile(r"@\s*[\w.]*").match(text, i)
            spans.append((i, m.end() - i, "decorator"))
            i = m.end()
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUMBER.match(text, i)
            if m and m.end() > i:
                spans.append((i, m.end() - i, "number"))
                i = m.end()
                continue
        m = _IDENT.match(text, i)
        if m:
            word = m.group()
            end = m.end()
            if end < n and text[end] in "'\"" and _STRING_PREFIX.match(word):
                start, i, state = _scan_string(text, i, end, spans)
                continue
            if expect_def:
                spans.append((i, len(word), "definition"))
                expect_def = False
            elif word in api_names:
                spans.append((i, len(word), "api"))
            elif word in _KEYWORDS:
                spans.append((i, len(word), "keyword"))
                expect_def = word in ("def", "class")
            elif word in _CONSTANTS:
                spans.append((i, len(word), "constant"))
            elif word in ("self", "cls"):
                spans.append((i, len(word), "self"))
            elif word in _BUILTINS:
                spans.append((i, len(word), "builtin"))
            i = end
            continue
        i += 1
    return spans, state


def _scan_string(text: str, start: int, quote_at: int, spans: list):
    """Scan a string whose first quote char is at quote_at (its prefix starts at `start`).

    Appends the span, returns (start, next_index, new_state).
    """
    n = len(text)
    q = text[quote_at]
    triple = text.startswith(q * 3, quote_at)
    quote = q * 3 if triple else q
    end = _string_end(text, quote_at + len(quote), quote)
    if end == -1:
        spans.append((start, n - start, "string"))
        return start, n, (1 if q == "'" else 2) if triple else 0
    spans.append((start, end - start, "string"))
    return start, end, 0
