"""Index of the functions, classes and calls in a project, for hover info and call trees (no Qt)."""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Symbol:
    name: str
    qualname: str            # "update" or "Player.move"
    kind: str                # "function" | "method" | "class"
    path: str
    line: int
    end_line: int
    signature: str
    doc: str
    class_name: str | None
    calls: tuple             # dotted names called inside, in source order

    @property
    def key(self):
        return (self.path, self.qualname)


@dataclass
class TreeNode:
    label: str
    note: str = ""
    children: list = field(default_factory=list)


def _dotted(expr):
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return base + "." + expr.attr if base else None
    return None


def _calls(node) -> tuple:
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _dotted(sub.func)
            if name:
                found.append((sub.lineno, sub.col_offset, name))
    seen, out = set(), []
    for _line, _col, name in sorted(found):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def _targets(node):
    if isinstance(node, ast.Name):
        yield node.id, node.lineno
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _targets(elt)


class SymbolIndex:
    def __init__(self, engine_names=()):
        self.engine_names = frozenset(engine_names)
        self.symbols: dict[tuple, Symbol] = {}
        self.imports: dict[str, dict] = {}       # path -> {alias: (module, attr or None)}
        self.module_vars: dict[str, dict] = {}   # path -> {name: line}
        self.files: set[str] = set()
        self._callers = None

    # ---- building --------------------------------------------------------------------------
    @classmethod
    def build(cls, files: dict, engine_names=(), previous: "SymbolIndex | None" = None) -> "SymbolIndex":
        """Index {path: source}. A file that doesn't parse (the user is mid-edit) keeps whatever
        `previous` knew about it, so hover and call trees don't blink out while typing."""
        idx = cls(engine_names)
        idx.files = set(files)
        for path in sorted(files):
            if not path.endswith(".py"):
                continue
            try:
                tree = ast.parse(files[path], path)
            except (SyntaxError, ValueError, RecursionError):
                if previous is not None:
                    idx._inherit(previous, path)
                continue
            idx._add_module(path, tree)
        return idx

    def _inherit(self, old: "SymbolIndex", path: str) -> None:
        for key, sym in old.symbols.items():
            if key[0] == path:
                self.symbols[key] = sym
        if path in old.imports:
            self.imports[path] = old.imports[path]
        if path in old.module_vars:
            self.module_vars[path] = old.module_vars[path]

    def _add_module(self, path: str, tree: ast.Module) -> None:
        imports, mvars = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        imports[a.asname] = (a.name, None)
                    else:
                        head = a.name.split(".")[0]
                        imports[head] = (head, None)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for a in node.names:
                    if a.name != "*":
                        imports[a.asname or a.name] = (node.module, a.name)
        self.imports[path] = imports
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_function(path, node, None)
            elif isinstance(node, ast.ClassDef):
                self._add_class(path, node)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    for name, line in _targets(t):
                        mvars.setdefault(name, line)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                for name, line in _targets(node.target):
                    mvars.setdefault(name, line)
        self.module_vars[path] = mvars

    def _add_function(self, path, node, class_name) -> None:
        qual = "%s.%s" % (class_name, node.name) if class_name else node.name
        sig = "%s(%s)" % (node.name, ast.unparse(node.args))
        if node.returns is not None:
            sig += " -> " + ast.unparse(node.returns)
        self.symbols[(path, qual)] = Symbol(
            node.name, qual, "method" if class_name else "function", path, node.lineno,
            node.end_lineno or node.lineno, sig, ast.get_docstring(node) or "", class_name, _calls(node))

    def _add_class(self, path, node: ast.ClassDef) -> None:
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        self.symbols[(path, node.name)] = Symbol(
            node.name, node.name, "class", path, node.lineno, node.end_lineno or node.lineno,
            "class %s%s" % (node.name, "(%s)" % bases if bases else ""), ast.get_docstring(node) or "", None, ())
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_function(path, item, node.name)

    # ---- lookups ---------------------------------------------------------------------------
    def module_file(self, dotted: str):
        base = dotted.replace(".", "/")
        for cand in (base + ".py", base + "/__init__.py"):
            if cand in self.files:
                return cand
        return None

    def top_level(self, path: str):
        """Top-level functions and classes of a file."""
        return [s for (p, q), s in self.symbols.items() if p == path and "." not in q]

    def methods_of(self, path: str, class_name: str):
        return [s for (p, _q), s in self.symbols.items() if p == path and s.class_name == class_name]

    def resolve(self, name: str, path: str, class_name: str | None = None):
        """Project symbol a (possibly dotted) name refers to, as seen from `path`, or None."""
        if "." in name:
            head, rest = name.split(".", 1)
            if "." in rest:
                return None
            if head == "self" and class_name:
                return self.symbols.get((path, "%s.%s" % (class_name, rest)))
            imp = self.imports.get(path, {}).get(head)
            if imp and imp[1] is None:                              # module.attr
                mf = self.module_file(imp[0])
                return self.symbols.get((mf, rest)) if mf else None
            if imp and imp[1] is not None:                          # ImportedClass.method
                mf = self.module_file(imp[0])
                return self.symbols.get((mf, "%s.%s" % (imp[1], rest))) if mf else None
            return self.symbols.get((path, name))                   # Class.method in this file
        sym = self.symbols.get((path, name))
        if sym:
            return sym
        imp = self.imports.get(path, {}).get(name)
        if imp and imp[1] is not None:
            mf = self.module_file(imp[0])
            if mf and (mf, imp[1]) in self.symbols:
                return self.symbols[(mf, imp[1])]
        matches = [s for (p, q), s in self.symbols.items() if q == name and p != path]
        return matches[0] if len(matches) == 1 else None            # e.g. `from x import *`

    def classify(self, name: str, path: str, class_name: str | None = None):
        """(category, Symbol | None); category is project / engine / builtin / external."""
        sym = self.resolve(name, path, class_name)
        if sym:
            return "project", sym
        if "." not in name:
            if name in self.engine_names:
                return "engine", None
            if not name.startswith("_") and hasattr(builtins, name):
                return "builtin", None
        return "external", None

    def enclosing(self, path: str, line: int):
        """Innermost function/method (or class) whose body contains `line`."""
        best = None
        for (p, _q), s in self.symbols.items():
            if p == path and s.line <= line <= s.end_line:
                if best is None or (s.end_line - s.line) < (best.end_line - best.line):
                    best = s
        return best

    def _calls_of(self, sym: Symbol):
        if sym.kind == "class":
            init = self.symbols.get((sym.path, sym.name + ".__init__"))
            return init.calls if init else ()
        return sym.calls

    def callees(self, sym: Symbol):
        """[(called name, category, Symbol | None)] in source order."""
        cls = sym.class_name if sym.kind != "class" else sym.name
        return [(name,) + self.classify(name, sym.path, cls) for name in self._calls_of(sym)]

    def callers(self, sym: Symbol):
        if self._callers is None:
            table: dict = {}
            for s in self.symbols.values():
                for _name, _cat, target in self.callees(s):
                    if target is not None and s not in table.setdefault(target.key, []):
                        table[target.key].append(s)
            self._callers = table
        return self._callers.get(sym.key, [])

    # ---- call trees ------------------------------------------------------------------------
    def _edges(self, sym: Symbol, direction: str):
        if direction == "callers":
            return [(c.qualname, "%s:%d" % (c.path, c.line), c) for c in self.callers(sym)]
        edges, groups = [], {"engine": [], "builtin": [], "external": []}
        for name, cat, target in self.callees(sym):
            if target is not None:
                edges.append((target.qualname, "%s:%d" % (target.path, target.line), target))
            else:
                groups[cat].append(name)
        for cat in ("engine", "builtin", "external"):
            names = groups[cat]
            if names:
                shown = ", ".join(names[:8]) + (" +%d more" % (len(names) - 8) if len(names) > 8 else "")
                edges.append((shown, cat if cat != "external" else "other", None))
        return edges

    def call_tree(self, sym: Symbol, direction: str = "calls", depth: int = 3, limit: int = 40):
        """Nested TreeNodes of what `sym` calls ("calls") or what calls it ("callers")."""
        budget = [limit]

        def expand(s, level, trail):
            nodes = []
            for label, note, target in self._edges(s, direction):
                if budget[0] <= 0:
                    nodes.append(TreeNode("…"))
                    break
                budget[0] -= 1
                node = TreeNode(label, note)
                if target is not None:
                    if target.key in trail:
                        node.note += " (recursive)"
                    elif level < depth:
                        node.children = expand(target, level + 1, trail | {target.key})
                nodes.append(node)
            return nodes

        return expand(sym, 1, frozenset({sym.key}))
