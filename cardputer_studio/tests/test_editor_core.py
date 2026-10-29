"""Tests for the editor's pure-Python logic: search, multi-cursor geometry, symbols, completion, hover."""
import unittest

from cpg_studio.core import completion, hover, multicursor as mc, search
from cpg_studio.core.search import SearchError, SearchOptions
from cpg_studio.core.symbols import SymbolIndex
from cpg_studio.runtime import api

ENGINE = set(api.__all__)

FILES = {
    "main.py": (
        "from player import Player, speed_of\n"
        "import utils\n"
        "p = Player()\n"
        "score = 0\n"
        "def setup():\n"
        "    set_fps(30)\n"
        "def update(dt):\n"
        "    p.move(dt)\n"
        "    utils.clamp(1, 0, 2)\n"
        "def draw():\n"
        "    clear(BLACK)\n"
        "    p.render()\n"
        "    helper()\n"
        "def helper():\n"
        "    text(0, 0, 'x')\n"
        "    print(len('a'))\n"
    ),
    "player.py": (
        "class Player:\n"
        "    '''A player.'''\n"
        "    def __init__(self):\n"
        "        self.x = 0\n"
        "    def move(self, dt):\n"
        "        self.x += speed_of(dt)\n"
        "        self.render()\n"
        "    def render(self):\n"
        "        rect(self.x, 0, 4, 4, WHITE)\n"
        "def speed_of(dt):\n"
        "    '''Speed for dt.'''\n"
        "    return dt * 10\n"
    ),
    "utils.py": "def clamp(v, lo, hi):\n    return max(lo, min(v, hi))\n\nLIMIT = 3\n",
}


def index():
    return SymbolIndex.build(FILES, ENGINE)


class SearchTests(unittest.TestCase):
    def test_plain_case_insensitive(self):
        self.assertEqual(search.find_all("Foo foo FOO", "foo"), [(0, 3), (4, 7), (8, 11)])

    def test_case_sensitive_and_whole_word(self):
        self.assertEqual(search.find_all("Foo foo", "foo", SearchOptions(case_sensitive=True)), [(4, 7)])
        self.assertEqual(search.find_all("foo foobar", "foo", SearchOptions(whole_word=True)), [(0, 3)])

    def test_special_characters_are_literal_unless_regex(self):
        self.assertEqual(search.find_all("a.b axb", "a.b"), [(0, 3)])
        self.assertEqual(len(search.find_all("a.b axb", "a.b", SearchOptions(regex=True))), 2)

    def test_bad_regex_raises(self):
        with self.assertRaises(SearchError):
            search.find_all("x", "(", SearchOptions(regex=True))

    def test_empty_matches_are_skipped(self):
        self.assertEqual(search.find_all("abc", "x*", SearchOptions(regex=True)), [])

    def test_replace_all(self):
        self.assertEqual(search.replace_all("a b a", "a", "zz"), ("zz b zz", 2))
        self.assertEqual(search.replace_all("k1 k22", r"k(\d+)", r"v\1", SearchOptions(regex=True)), ("v1 v22", 2))

    def test_replace_one_and_navigation(self):
        self.assertEqual(search.replace_one("a b a", 4, 5, "a", "Q", SearchOptions()), "Q")
        self.assertIsNone(search.replace_one("a b a", 1, 2, "a", "Q", SearchOptions()))
        m = [(0, 1), (4, 5), (8, 9)]
        self.assertEqual(search.next_index(m, 1), 1)
        self.assertEqual(search.next_index(m, 9), 0)
        self.assertEqual(search.prev_index(m, 4), 0)
        self.assertEqual(search.prev_index(m, 0), 2)
        self.assertIsNone(search.next_index([], 0))


class MultiCursorTests(unittest.TestCase):
    def test_columns_with_tabs(self):
        self.assertEqual(mc.index_to_vcol("\tab", 1), 4)
        self.assertEqual(mc.vcol_to_index("\tab", 5), 2)
        self.assertEqual(mc.vcol_to_index("ab", 9), 2)

    def test_column_spans(self):
        lines = ["abcdef", "ab", "abcdef"]
        self.assertEqual(mc.column_spans(lines, (0, 1), (2, 4)), [(0, 1, 4), (1, 1, 2), (2, 1, 4)])
        self.assertEqual(mc.column_spans(lines, (2, 4), (0, 1)), [(0, 1, 4), (1, 1, 2), (2, 1, 4)])

    def test_vertical_target(self):
        self.assertEqual(mc.vertical_target(["abcd", "ab"], 0, 3, 1), (1, 2))
        self.assertIsNone(mc.vertical_target(["abcd"], 0, 1, -1))

    def test_keep_indices_merges_duplicates_and_overlaps(self):
        self.assertEqual(mc.keep_indices([(3, 3), (3, 3), (5, 5)]), [0, 2])
        self.assertEqual(mc.keep_indices([(0, 5), (3, 8), (8, 9)]), [0, 2])

    def test_distribute_paste(self):
        self.assertEqual(mc.distribute_paste("a\nb", 2), ["a", "b"])
        self.assertEqual(mc.distribute_paste("a\nb\n", 2), ["a", "b"])
        self.assertEqual(mc.distribute_paste("a\nb", 3), ["a\nb"] * 3)
        self.assertEqual(mc.distribute_paste("x", 1), ["x"])


class SymbolTests(unittest.TestCase):
    def test_symbols_found(self):
        idx = index()
        self.assertIn(("player.py", "Player.move"), idx.symbols)
        self.assertEqual(idx.symbols[("player.py", "speed_of")].doc, "Speed for dt.")
        self.assertEqual(idx.symbols[("main.py", "update")].signature, "update(dt)")

    def test_resolve_through_imports(self):
        idx = index()
        self.assertEqual(idx.resolve("Player", "main.py").path, "player.py")
        self.assertEqual(idx.resolve("utils.clamp", "main.py").path, "utils.py")
        self.assertEqual(idx.resolve("self.render", "player.py", "Player").qualname, "Player.render")
        self.assertIsNone(idx.resolve("nothing", "main.py"))

    def test_classify(self):
        idx = index()
        self.assertEqual(idx.classify("clear", "main.py")[0], "engine")
        self.assertEqual(idx.classify("len", "main.py")[0], "builtin")
        self.assertEqual(idx.classify("helper", "main.py")[0], "project")

    def test_callers_and_tree(self):
        idx = index()
        render = idx.symbols[("player.py", "Player.render")]
        callers = {c.qualname for c in idx.callers(render)}
        self.assertEqual(callers, {"Player.move"})      # p.render() on an instance is not guessed
        draw = idx.symbols[("main.py", "draw")]
        labels = [n.label for n in idx.call_tree(draw)]
        self.assertIn("helper", labels)
        move = idx.symbols[("player.py", "Player.move")]
        tree = idx.call_tree(move)
        self.assertEqual([n.label for n in tree][:2], ["speed_of", "Player.render"])

    def test_recursion_is_cut(self):
        idx = SymbolIndex.build({"a.py": "def f():\n    g()\ndef g():\n    f()\n"})
        tree = idx.call_tree(idx.symbols[("a.py", "f")])
        self.assertIn("recursive", tree[0].children[0].note)

    def test_enclosing(self):
        idx = index()
        self.assertEqual(idx.enclosing("main.py", 8).qualname, "update")
        self.assertIsNone(idx.enclosing("main.py", 3))

    def test_broken_file_keeps_previous_symbols(self):
        idx = index()
        broken = dict(FILES, **{"utils.py": "def clamp(:\n"})
        new = SymbolIndex.build(broken, ENGINE, previous=idx)
        self.assertIn(("utils.py", "clamp"), new.symbols)
        self.assertNotIn(("utils.py", "clamp"), SymbolIndex.build(broken, ENGINE).symbols)


def names(result):
    return [c.name for c in result[1]]


class CompletionTests(unittest.TestCase):
    def comp(self, text, path="main.py", files=None):
        idx = SymbolIndex.build(files or FILES, ENGINE)
        return completion.complete(text, len(text), path, idx)

    def test_engine_functions_without_import(self):
        res = self.comp("cle")
        self.assertEqual(res[0], 3)
        self.assertEqual(names(res)[0], "clear")
        self.assertEqual(res[1][0].kind, "engine")

    def test_project_and_local_names(self):
        self.assertIn("speed_of", names(self.comp("spee")))
        self.assertIn("my_var", names(self.comp("my_var = 1\nmy_")))

    def test_hooks_builtins_keywords(self):
        self.assertIn("update", names(self.comp("upd")))
        self.assertIn("print", names(self.comp("pri")))
        self.assertIn("return", names(self.comp("retu")))

    def test_nothing_in_strings_comments_or_after_def(self):
        self.assertEqual(self.comp("x = 'cle")[1], [])
        self.assertEqual(self.comp("# cle")[1], [])
        self.assertEqual(self.comp("def cle")[1], [])
        self.assertEqual(self.comp("x = '''a\nb cle")[1], [])

    def test_nothing_without_prefix(self):
        self.assertEqual(self.comp("x = ")[1], [])

    def test_module_members(self):
        self.assertIn("sqrt", names(self.comp("import math\nmath.sq")))
        self.assertIn("clamp", names(self.comp("import utils\nutils.cl")))
        self.assertIn("LIMIT", names(self.comp("import utils\nutils.")))

    def test_self_members(self):
        text = FILES["player.py"] + "class B:\n    def a(self):\n        self.q = 1\n    def b(self):\n        self."
        res = self.comp(text, "player.py", dict(FILES, **{"player.py": text}))
        self.assertEqual(names(res), ["a", "b", "q"])
        res = self.comp("class P:\n    def move(self):\n        pass\n    def go(self):\n        self.mo", "p.py",
                        {"p.py": "class P:\n    def move(self):\n        pass\n"})
        self.assertEqual(names(res), ["move"])

    def test_import_line(self):
        self.assertIn("math", names(self.comp("import ma")))
        self.assertIn("player", names(self.comp("from pl")))

    def test_in_string_helper(self):
        self.assertTrue(completion.in_string_or_comment('x = "ab', 7))
        self.assertFalse(completion.in_string_or_comment('x = "ab" + y', 12))
        self.assertTrue(completion.in_string_or_comment("a = 1 # hi", 10))


class HoverTests(unittest.TestCase):
    def test_identifier_at(self):
        self.assertEqual(hover.identifier_at("    self.move(dt)", 10), ("self.move", 4, 13))
        self.assertEqual(hover.identifier_at("x = foo", 5), ("foo", 4, 7))
        self.assertIsNone(hover.identifier_at("x = 1", 3))

    def test_project_function_shows_signature_and_trees(self):
        idx = index()
        html = hover.hover_html(FILES["main.py"], 12, 6, "main.py", idx)      # on `helper()` in draw
        self.assertIn("helper()", html)
        self.assertIn("Calls", html)
        self.assertIn("text", html)
        self.assertIn("Called by", html)
        self.assertIn("draw", html)

    def test_method_through_dotted_name(self):
        idx = index()
        html = hover.hover_html(FILES["main.py"], 7, 8, "main.py", idx)       # `p.move` - p isn't a module
        self.assertIsNone(html)                                                  # instance types are not guessed
        html = hover.hover_html(FILES["player.py"], 6, 14, "player.py", idx)   # self.render
        self.assertIn("Player.render", html)
        self.assertIn("Called by", html)

    def test_engine_function(self):
        html = hover.hover_html(FILES["main.py"], 10, 6, "main.py", index())
        self.assertIn("clear", html)
        self.assertIn("auto-imported", html)
        self.assertIn("Used in", html)

    def test_builtin_and_nothing(self):
        self.assertIn("built-in", hover.hover_html(FILES["main.py"], 15, 6, "main.py", index()))
        self.assertIsNone(hover.hover_html("x = 'clear'", 0, 6, "a.py", SymbolIndex(ENGINE)))
        self.assertIsNone(hover.hover_html("x = 1", 5, 0, "a.py", SymbolIndex(ENGINE)))

    def test_stdlib_member(self):
        idx = SymbolIndex.build({"a.py": "import math\nmath.sqrt(2)\n"}, ENGINE)
        self.assertIn("math.sqrt", hover.hover_html("import math\nmath.sqrt(2)\n", 1, 7, "a.py", idx))


if __name__ == "__main__":
    unittest.main()
