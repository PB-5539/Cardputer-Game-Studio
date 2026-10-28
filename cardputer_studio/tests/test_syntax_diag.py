import unittest

from helpers import ROOT  # noqa: F401
from cpg_studio.core import syntax
from cpg_studio.core.diagnostics import check_source


def kinds(line, state=0, api=frozenset()):
    spans, st = syntax.highlight_line(line, state, api)
    return [(line[s:s + n], k) for s, n, k in spans], st


class HighlightTests(unittest.TestCase):
    def test_keywords_builtins_numbers(self):
        got, _ = kinds("for i in range(10): print(i)")
        self.assertIn(("for", "keyword"), got)
        self.assertIn(("in", "keyword"), got)
        self.assertIn(("range", "builtin"), got)
        self.assertIn(("10", "number"), got)

    def test_api_names_win_over_builtins(self):
        got, _ = kinds("quit()", api=frozenset({"quit"}))
        self.assertEqual(got, [("quit", "api")])

    def test_def_and_class_names(self):
        self.assertIn(("update", "definition"), kinds("def update(dt):")[0])
        self.assertIn(("Foo", "definition"), kinds("class Foo:")[0])

    def test_comment_and_string_hide_keywords(self):
        got, _ = kinds('x = "if for"  # while True')
        self.assertIn(('"if for"', "string"), got)
        self.assertIn(("# while True", "comment"), got)
        self.assertNotIn(("if", "keyword"), got)
        self.assertNotIn(("while", "keyword"), got)

    def test_string_prefix_and_escape(self):
        self.assertEqual(kinds('f"a\\"b" + 1')[0][0], ('f"a\\"b"', "string"))
        self.assertEqual(kinds("rb'x'"), ([("rb'x'", "string")], 0))

    def test_multiline_triple_quotes(self):
        got, st = kinds('s = """first')
        self.assertEqual((got[-1], st), (('"""first', "string"), 2))
        got, st = kinds("middle if", st)
        self.assertEqual((got, st), ([("middle if", "string")], 2))
        got, st = kinds('end""" + 1', st)
        self.assertEqual(got[0], ('end"""', "string"))
        self.assertIn(("1", "number"), got)
        self.assertEqual(st, 0)

    def test_decorator_constants_self(self):
        self.assertEqual(kinds("@property")[0], [("@property", "decorator")])
        got, _ = kinds("return self.x is None")
        self.assertIn(("self", "self"), got)
        self.assertIn(("None", "constant"), got)

    def test_numbers(self):
        for src in ("0xFF", "1_000", "3.14", ".5", "1e-3", "0b101"):
            self.assertEqual(kinds(src)[0], [(src, "number")], src)

    def test_unterminated_single_quote_does_not_leak_state(self):
        self.assertEqual(kinds("x = 'abc")[1], 0)

    def test_spans_in_bounds_and_ordered(self):
        line = "def f(a, b=2): return f'{a}' if b else \"x\"  # c"
        spans, _ = syntax.highlight_line(line, 0, frozenset())
        last = 0
        for s, n, k in spans:
            self.assertGreaterEqual(s, last)
            self.assertLessEqual(s + n, len(line))
            self.assertIn(k, syntax.KINDS)
            last = s + n


class DiagnosticTests(unittest.TestCase):
    def test_valid_code_has_no_errors(self):
        self.assertEqual([d for d in check_source("x = 1\n", "a.py") if d.severity == "error"], [])

    def test_syntax_error_position(self):
        d = check_source("x = 1\nif x\n    y = 2\n", "a.py")
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0].path, d[0].line, d[0].severity), ("a.py", 2, "error"))
        self.assertGreaterEqual(d[0].col, 0)

    def test_indentation_error(self):
        d = check_source("def f():\nreturn 1\n", "a.py")
        self.assertEqual((d[0].line, d[0].severity), (2, "error"))

    def test_null_bytes_do_not_crash(self):
        self.assertEqual(check_source("x = 1\x00", "a.py")[0].severity, "error")

    def test_empty_file_ok(self):
        self.assertEqual(check_source("", "a.py"), [])


if __name__ == "__main__":
    unittest.main()
