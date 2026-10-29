"""Autocomplete suggestions (no Qt, so it can be tested).

`complete(text, offset, path, index)` returns (replace_len, [Completion, ...]): the editor replaces the
`replace_len` characters before the cursor with the chosen completion's name.
"""
from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass

from ..runtime import api_docs
from . import pyinfo
from .symbols import SymbolIndex

_WORD_BEFORE = re.compile(r"[A-Za-z_]\w*$")
_CHAIN_BEFORE = re.compile(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)?$")
_HOOKS = ("setup", "update", "draw")
_RANK = {"local": 0, "project": 1, "engine": 2, "member": 1, "builtin": 4, "keyword": 5}


@dataclass(frozen=True)
class Completion:
    name: str
    kind: str          # local | project | engine | member | builtin | keyword
    detail: str = ""


def in_string_or_comment(text: str, offset: int) -> bool:
    """True if `offset` is inside a string literal or a comment (a light single-pass scan)."""
    i, n = 0, len(text)
    while i < offset and i < n:
        c = text[i]
        if c == "#":
            end = text.find("\n", i)
            if end == -1 or end >= offset:
                return True
            i = end
        elif c in "'\"":
            q = text[i:i + 3] if text[i:i + 3] in ("'''", '"""') else c
            j = i + len(q)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith(q, j):
                    break
                if len(q) == 1 and text[j] == "\n":
                    break
                j += 1
            if j >= offset:
                return True
            i = j + len(q) - 1
        i += 1
    return False


def _engine_details():
    out = {}
    for d in api_docs.DOCS:
        for name in (d.covers or (d.title,)):
            out.setdefault(name, d)
    return out


def _local_names(text: str):
    """Names assigned or defined in `text` (params included), even if the file doesn't parse."""
    names = {}
    try:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.setdefault(node.name, "function")
                for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
                    names.setdefault(a.arg, "variable")
            elif isinstance(node, ast.ClassDef):
                names.setdefault(node.name, "class")
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.setdefault(node.id, "variable")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    names.setdefault((a.asname or a.name).split(".")[0], "module")
    except (SyntaxError, ValueError, RecursionError):
        for m in re.finditer(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)|^\s*([A-Za-z_]\w*)\s*=[^=]", text, re.M):
            names.setdefault(m.group(1) or m.group(2), "variable")
    return names


def _enclosing_class(text: str, line: int):
    """Name of the class whose body contains 1-based `line`, via indentation (works mid-edit)."""
    lines = text.split("\n")
    indent = None
    for n in range(min(line, len(lines)) - 1, -1, -1):
        s = lines[n]
        if not s.strip():
            continue
        cur = len(s) - len(s.lstrip())
        if indent is None:
            indent = cur
        m = re.match(r"\s*class\s+([A-Za-z_]\w*)", s)
        if m and cur < indent:
            return m.group(1)
        if cur < indent:
            indent = cur
    return None


def _class_block(text: str, class_name: str) -> str:
    """Source of `class_name`'s body, found by indentation (works while the file doesn't parse)."""
    lines = text.split("\n")
    for i, s in enumerate(lines):
        m = re.match(r"(\s*)class\s+%s\b" % re.escape(class_name), s)
        if m:
            base, body = len(m.group(1)), [s]
            for t in lines[i + 1:]:
                if t.strip() and len(t) - len(t.lstrip()) <= base:
                    break
                body.append(t)
            return "\n".join(body)
    return ""


def _self_members(text: str, class_name: str, index: SymbolIndex, path: str):
    members = {s.name: ("method", s.signature) for s in index.methods_of(path, class_name)}
    block = _class_block(text, class_name)
    for m in re.finditer(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", block, re.M):
        members.setdefault(m.group(1), ("method", m.group(1) + "(…)"))
    for m in re.finditer(r"\bself\.([A-Za-z_]\w*)\s*(?:[:+\-*/]?=)(?!=)", block):
        members.setdefault(m.group(1), ("variable", "attribute"))
    return members


def complete(text: str, offset: int, path: str, index: SymbolIndex | None, limit: int = 60):
    offset = max(0, min(offset, len(text)))
    line_start = text.rfind("\n", 0, offset) + 1
    before = text[line_start:offset]
    if in_string_or_comment(text, offset):
        return 0, []
    stripped = before.lstrip()
    if re.match(r"(def|class)\s+\w*$", stripped):
        return 0, []                                        # naming something new
    index = index or SymbolIndex()
    word = _WORD_BEFORE.search(before)
    prefix = word.group(0) if word else ""

    chain = _CHAIN_BEFORE.search(before)
    if chain or before.endswith("."):
        return _member_completions(text, offset, before, path, index, chain)
    if re.match(r"(from|import)\b", stripped):
        return _import_completions(stripped, prefix, index)
    if not prefix:
        return 0, []

    found: dict[str, Completion] = {}

    def add(name, kind, detail=""):
        if name.lower().startswith(prefix.lower()) and name != prefix:
            found.setdefault(name, Completion(name, kind, detail))

    for name, what in _local_names(text).items():
        add(name, "local", what)
    for sym in index.symbols.values():
        if sym.kind != "method":
            add(sym.name, "project", sym.signature + "  · " + sym.path)
    for p, names in index.module_vars.items():
        for name in names:
            add(name, "project", "variable  · " + p)
    engine = _engine_details()
    for name in sorted(index.engine_names):
        d = engine.get(name)
        add(name, "engine", (d.signature if d else "engine"))
    for name in _HOOKS:
        add(name, "engine", "game hook")
    for name in pyinfo.builtin_names():
        add(name, "builtin", "built-in")
    for name in keyword.kwlist:
        add(name, "keyword", "keyword")

    ordered = sorted(found.values(), key=lambda c: (_RANK[c.kind], not c.name.startswith(prefix), c.name.lower()))
    return len(prefix), ordered[:limit]


def _member_completions(text, offset, before, path, index, chain):
    base = chain.group(1) if chain else None
    prefix = (chain.group(2) or "") if chain else ""
    if base is None:                                        # something like `foo().` / `x[0].`: unknown
        return 0, []
    items: dict[str, Completion] = {}

    def add(name, kind, detail=""):
        if name.lower().startswith(prefix.lower()) and name != prefix and not name.startswith("_"):
            items.setdefault(name, Completion(name, kind, detail))

    if base == "self":
        line = text.count("\n", 0, offset) + 1
        cls = _enclosing_class(text, line)
        if cls:
            for name, (kind, detail) in _self_members(text, cls, index, path).items():
                add(name, "member" if kind == "method" else "local", detail)
    else:
        imp = index.imports.get(path, {}).get(base)
        module = imp[0] if imp and imp[1] is None else (base if base in pyinfo.SAFE_MODULES else None)
        if module:
            mf = index.module_file(module)
            if mf:
                for sym in index.top_level(mf):
                    add(sym.name, "project", sym.signature)
                for name in index.module_vars.get(mf, {}):
                    add(name, "project", "variable")
            for name, kind, detail in pyinfo.module_members(module):
                add(name, "member", detail or kind)
        else:
            for sym in index.methods_of(path, base):
                add(sym.name, "member", sym.signature)
    ordered = sorted(items.values(), key=lambda c: (not c.name.startswith(prefix), c.name.lower()))
    return len(prefix), ordered[:60]


def _import_completions(stripped, prefix, index):
    m = re.match(r"(?:from|import)\s+(\w*)$", stripped)
    if not m:
        return 0, []
    out = {}
    for mod in pyinfo.SAFE_MODULES:
        if mod.startswith(prefix.lower()) and mod != prefix:
            out[mod] = Completion(mod, "member", "module")
    for f in sorted(index.files):
        if f.endswith(".py"):
            mod = f[:-3].replace("/", ".")
            if mod.startswith(prefix) and mod != prefix:
                out.setdefault(mod, Completion(mod, "project", "project module"))
    return len(prefix), list(out.values())[:60]
