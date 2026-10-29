"""Find and replace logic for the editor (no Qt, so it can be tested)."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_MATCHES = 20000


class SearchError(ValueError):
    """The search or replacement text is invalid (for example a broken regular expression)."""


@dataclass(frozen=True)
class SearchOptions:
    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False


def compile_query(query: str, options: SearchOptions = SearchOptions()) -> re.Pattern:
    pattern = query if options.regex else re.escape(query)
    if options.whole_word:
        pattern = r"(?<!\w)(?:%s)(?!\w)" % pattern
    flags = re.MULTILINE | (0 if options.case_sensitive else re.IGNORECASE)
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        raise SearchError(str(e)) from None


def find_all(text: str, query: str, options: SearchOptions = SearchOptions(), limit: int = MAX_MATCHES):
    """[(start, end), ...] of every non-empty match, in order."""
    if not query:
        return []
    out = []
    for m in compile_query(query, options).finditer(text):
        if m.end() == m.start():
            continue                               # empty matches (e.g. regex 'x*') can't be selected
        out.append((m.start(), m.end()))
        if len(out) >= limit:
            break
    return out


def replacement_for(match: re.Match, replacement: str, options: SearchOptions) -> str:
    if not options.regex:
        return replacement
    try:
        return match.expand(replacement)           # \1, \g<name>, \n ...
    except (re.error, IndexError) as e:
        raise SearchError("Invalid replacement: %s" % e) from None


def replace_edits(text: str, query: str, replacement: str, options: SearchOptions = SearchOptions(),
                  limit: int = MAX_MATCHES):
    """[(start, end, new_text), ...] for replacing every match; apply from the last to the first."""
    if not query:
        return []
    out = []
    for m in compile_query(query, options).finditer(text):
        if m.end() == m.start():
            continue
        out.append((m.start(), m.end(), replacement_for(m, replacement, options)))
        if len(out) >= limit:
            break
    return out


def replace_all(text: str, query: str, replacement: str, options: SearchOptions = SearchOptions()):
    """(new_text, count)."""
    edits = replace_edits(text, query, replacement, options)
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text, len(edits)


def replace_one(text: str, start: int, end: int, query: str, replacement: str, options: SearchOptions):
    """New text for the single match at [start, end), or None if that range isn't a match any more."""
    for m in compile_query(query, options).finditer(text):
        if (m.start(), m.end()) == (start, end):
            return replacement_for(m, replacement, options)
    return None


def index_at(matches, start: int, end: int):
    """Index of the match exactly covering [start, end), or None."""
    for i, (s, e) in enumerate(matches):
        if (s, e) == (start, end):
            return i
    return None


def next_index(matches, position: int, wrap: bool = True):
    """First match starting at or after `position` (wrapping to the first), or None."""
    for i, (s, _e) in enumerate(matches):
        if s >= position:
            return i
    return 0 if (matches and wrap) else None


def prev_index(matches, position: int, wrap: bool = True):
    """Last match starting before `position` (wrapping to the last), or None."""
    for i in range(len(matches) - 1, -1, -1):
        if matches[i][0] < position:
            return i
    return len(matches) - 1 if (matches and wrap) else None
