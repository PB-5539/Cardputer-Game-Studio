"""Hover information with a call tree, rendered as HTML for a tooltip (no Qt)."""
from __future__ import annotations

import html
import re

from ..runtime import api_docs
from . import pyinfo
from .completion import _enclosing_class, in_string_or_comment
from .symbols import SymbolIndex, TreeNode

_IDENT = re.compile(r"[A-Za-z_]\w*")


def identifier_at(line: str, col: int):
    """Dotted name ending at the word under column `col`: hovering `move` in `self.move()` gives
    'self.move'. Returns (name, start, end) or None."""
    for m in _IDENT.finditer(line):
        if m.start() <= col <= m.end():
            start = m.start()
            while start >= 2 and line[start - 1] == ".":
                prev = re.search(r"[A-Za-z_]\w*$", line[:start - 1])
                if not prev:
                    break
                start = prev.start()
            return line[start:m.end()], start, m.end()
    return None


def _engine_doc(name: str):
    for d in api_docs.DOCS:
        if name in (d.covers or (d.title,)) or d.title == name:
            return d
    return None


def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def render_tree(nodes, prefix: str = "") -> str:
    lines = []
    for i, n in enumerate(nodes):
        last = i == len(nodes) - 1
        note = '  <span style="color:#8a8a8a">%s</span>' % _esc(n.note) if n.note else ""
        lines.append("%s%s %s%s" % (prefix, "└─" if last else "├─", _esc(n.label), note))
        if n.children:
            lines.append(render_tree(n.children, prefix + ("   " if last else "│  ")))
    return "\n".join(lines)


def _tree_block(title: str, nodes: list) -> str:
    if not nodes:
        return ""
    return "<p style='margin:6px 0 0 0'><b>%s</b></p><pre style='margin:0'>%s</pre>" % (title, render_tree(nodes))


def _header(sig: str, where: str = "") -> str:
    out = "<p style='margin:0'><b><code>%s</code></b></p>" % _esc(sig)
    if where:
        out += "<p style='margin:0;color:#8a8a8a'>%s</p>" % _esc(where)
    return out


def hover_html(text: str, line_no: int, col: int, path: str, index: SymbolIndex):
    """HTML for the identifier at 0-based (line_no, col), or None when there is nothing to show."""
    lines = text.split("\n")
    if not 0 <= line_no < len(lines):
        return None
    found = identifier_at(lines[line_no], col)
    if found is None:
        return None
    name, start, _end = found
    offset = sum(len(s) + 1 for s in lines[:line_no]) + start
    if in_string_or_comment(text, offset + len(name)):
        return None
    cls = _enclosing_class(text, line_no + 1)
    category, sym = index.classify(name, path, cls)
    parts = []

    if sym is not None:
        where = "%s %s · %s:%d" % (sym.kind, sym.qualname, sym.path, sym.line)
        parts.append(_header(sym.signature, where))
        if sym.doc:
            parts.append("<p style='margin:4px 0 0 0'>%s</p>" % _esc(sym.doc).replace("\n", "<br>"))
        parts.append(_tree_block("Calls", index.call_tree(sym, "calls")))
        parts.append(_tree_block("Called by", index.call_tree(sym, "callers")))
        return "".join(parts)

    if category == "engine":
        d = _engine_doc(name)
        parts.append(_header(d.signature if d else name, "engine · auto-imported, no import needed"))
        if d:
            parts.append("<p style='margin:4px 0 0 0'>%s</p>" % _esc(d.summary))
            for p, desc in d.params:
                parts.append("<div><code>%s</code> – %s</div>" % (_esc(p), _esc(desc)))
            if d.returns:
                parts.append("<div><b>Returns</b> %s</div>" % _esc(d.returns))
        used_by = [s for s in index.symbols.values() if name in s.calls]
        if used_by:
            nodes = [TreeNode(s.qualname, "%s:%d" % (s.path, s.line)) for s in used_by[:12]]
            parts.append(_tree_block("Used in", nodes))
        return "".join(parts)

    if category == "builtin":
        info = pyinfo.builtin_doc(name)
        if info:
            kind, sig, doc = info
            parts.append(_header(sig, "Python built-in " + kind))
            if doc:
                parts.append("<p style='margin:4px 0 0 0'>%s</p>" % _esc(pyinfo.first_line(doc)))
            return "".join(parts)
        return None

    if "." in name:                                    # module.attr from a safe stdlib module
        head, attr = name.split(".", 1)
        imp = index.imports.get(path, {}).get(head)
        module = imp[0] if imp and imp[1] is None else head
        info = pyinfo.member_doc(module, attr) if "." not in attr else None
        if info:
            kind, sig, doc = info
            parts.append(_header(sig, "Python standard library · " + module))
            if doc:
                parts.append("<p style='margin:4px 0 0 0'>%s</p>" % _esc(pyinfo.first_line(doc)))
            return "".join(parts)

    local = index.module_vars.get(path, {}).get(name)
    if local:
        return _header(name, "variable · %s:%d" % (path, local))
    return None
