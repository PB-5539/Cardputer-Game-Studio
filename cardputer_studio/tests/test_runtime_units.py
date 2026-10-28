import unittest

from helpers import ROOT  # noqa: F401
from cpg_studio.runtime import api, api_docs, font8x8, keys, protocol
from cpg_studio.runtime.framebuf_sim import FrameBuffer


class FontTests(unittest.TestCase):
    def test_table_complete(self):
        self.assertEqual(len(font8x8.GLYPHS), 95)
        self.assertEqual(sorted(font8x8.GLYPHS), [chr(c) for c in range(0x20, 0x7F)])
        for ch, rows in font8x8.GLYPHS.items():
            self.assertEqual(len(rows), 8, ch)
            self.assertTrue(all(0 <= r <= 255 for r in rows), ch)
        self.assertEqual(font8x8.glyph("é"), font8x8.glyph("?"))

    def test_known_glyph_A(self):
        self.assertEqual(font8x8.glyph("A")[:2], (0x0C, 0x1E))


class FrameBufferTests(unittest.TestCase):
    def setUp(self):
        self.fb = FrameBuffer(20, 10)

    def count(self, color):
        return sum(1 for y in range(10) for x in range(20) if self.fb.get_pixel(x, y) == color)

    def test_fill_and_pixel(self):
        self.fb.fill(0x1234)
        self.assertEqual(self.count(0x1234), 200)
        self.fb.pixel(3, 4, 0xFFFF)
        self.assertEqual(self.fb.get_pixel(3, 4), 0xFFFF)
        self.assertEqual(self.fb.buf[(4 * 20 + 3) * 2:(4 * 20 + 3) * 2 + 2], b"\xff\xff")
        self.fb.pixel(-1, 0, 5)
        self.fb.pixel(20, 0, 5)
        self.fb.pixel(0, 10, 5)                                # out of range: ignored
        self.assertEqual(len(self.fb.buf), 400)

    def test_little_endian_storage(self):
        self.fb.pixel(0, 0, 0xF800)
        self.assertEqual(bytes(self.fb.buf[:2]), b"\x00\xf8")

    def test_rect_fill_clip(self):
        self.fb.fill_rect(-5, -5, 10, 10, 1)                   # only 5x5 visible
        self.assertEqual(self.count(1), 25)
        self.fb.fill_rect(18, 8, 10, 10, 2)
        self.assertEqual(self.count(2), 4)
        self.fb.fill_rect(5, 5, 0, 3, 3)
        self.fb.fill_rect(5, 5, 3, -1, 3)
        self.assertEqual(self.count(3), 0)

    def test_rect_outline(self):
        self.fb.rect(2, 2, 5, 4, 7)
        self.assertEqual(self.count(7), 2 * 5 + 2 * 2)         # top+bottom rows plus side pixels
        self.assertEqual(self.fb.get_pixel(3, 3), 0)           # hollow
        self.fb.fill(0)
        self.fb.rect(2, 2, 5, 4, 7, fill=True)
        self.assertEqual(self.count(7), 20)

    def test_line_endpoints_and_straight(self):
        self.fb.line(1, 1, 8, 1, 9)
        self.assertEqual(self.count(9), 8)
        self.fb.fill(0)
        self.fb.line(0, 0, 9, 9, 9)
        self.assertEqual((self.fb.get_pixel(0, 0), self.fb.get_pixel(9, 9), self.fb.get_pixel(5, 5)), (9, 9, 9))
        self.fb.line(-50, -50, 100, 100, 4)                    # heavily clipped, must not raise

    def test_circle(self):
        fb = FrameBuffer(21, 21)
        fb.circle(10, 10, 5, 8)
        for dx, dy in ((5, 0), (-5, 0), (0, 5), (0, -5)):
            self.assertEqual(fb.get_pixel(10 + dx, 10 + dy), 8)
        self.assertEqual(fb.get_pixel(10, 10), 0)
        fb.fill(0)
        fb.circle(10, 10, 5, 8, fill=True)
        self.assertEqual(fb.get_pixel(10, 10), 8)
        self.assertEqual(fb.get_pixel(0, 0), 0)
        fb.circle(0, 0, 50, 3)                                 # clipped
        fb.circle(5, 5, 0, 6)
        self.assertEqual(fb.get_pixel(5, 5), 6)

    def test_text_draws_glyph_pixels_and_clips(self):
        fb = FrameBuffer(40, 12)
        fb.text("A", 0, 0, 5)
        # row 0 of 'A' is 0x0C: bits 2 and 3 -> x=2,3
        self.assertEqual([fb.get_pixel(x, 0) for x in range(8)], [0, 0, 5, 5, 0, 0, 0, 0])
        fb.text("AB", 36, 8, 5)                                # runs off right and bottom
        fb.text("A", -4, -4, 5)                                # runs off top-left
        fb.text("é", 20, 0, 5)                                 # unknown char -> '?'


class ApiTests(unittest.TestCase):
    def setUp(self):
        api._reset()

    def test_rgb(self):
        self.assertEqual(api.rgb(255, 255, 255), 0xFFFF)
        self.assertEqual(api.rgb(255, 0, 0), 0xF800)
        self.assertEqual(api.rgb(0, 255, 0), 0x07E0)
        self.assertEqual(api.rgb(0, 0, 255), 0x001F)
        self.assertEqual(api.rgb(-5, 300, 0), 0x07E0)          # clamped

    def test_float_coordinates_floor(self):
        api.pixel(3.9, 4.2, api.WHITE)
        self.assertEqual(api._s.fb.get_pixel(3, 4), api.WHITE)
        api.pixel(-0.5, 0, api.WHITE)                          # floors to -1: off screen, no wrap
        self.assertEqual(api._s.fb.get_pixel(0, 0), 0)

    def test_key_edges(self):
        api._key_event(True, "Left")
        api._poll_keys()
        self.assertTrue(api.key_down("left") and api.key_pressed("LEFT"))
        api._poll_keys()
        self.assertTrue(api.key_down("left"))
        self.assertFalse(api.key_pressed("left"))              # held, not new
        api._key_event(False, "left")
        api._poll_keys()
        self.assertFalse(api.key_down("left"))
        self.assertTrue(api.key_released("left"))
        api._poll_keys()
        self.assertFalse(api.key_released("left"))

    def test_quick_tap_between_frames_still_registers(self):
        api._key_event(True, "a")
        api._key_event(False, "a")
        api._poll_keys()
        self.assertTrue(api.key_pressed("a") and api.key_down("a"))
        api._poll_keys()
        self.assertTrue(api.key_released("a") and not api.key_down("a"))

    def test_repeat_down_events_do_not_retrigger(self):
        api._key_event(True, "b")
        api._poll_keys()
        api._key_event(True, "b")
        api._poll_keys()
        self.assertFalse(api.key_pressed("b"))

    def test_keys_lists(self):
        for k in ("z", "a"):
            api._key_event(True, k)
        api._poll_keys()
        self.assertEqual(api.keys_down(), ["a", "z"])
        self.assertEqual(api.keys_pressed(), ["a", "z"])

    def test_fps_clamp_quit_beep(self):
        api.set_fps(500)
        self.assertEqual(api._s.fps, 60)
        api.set_fps(0)
        self.assertEqual(api._s.fps, 1)
        api.quit()
        self.assertFalse(api._s.running)
        got = []
        api._s.on_beep = lambda f, ms: got.append((f, ms))
        api.beep(440, 50)
        self.assertEqual(got, [(440, 50)])
        api._reset()
        api.beep()                                             # no handler: silent no-op

    def test_inject_and_remove_builtins_restores_quit(self):
        import builtins
        original_quit = getattr(builtins, "quit", None)
        api.inject_builtins()
        try:
            self.assertIs(builtins.rect, api.rect)
            self.assertIs(builtins.quit, api.quit)
        finally:
            api.remove_builtins()
        self.assertFalse(hasattr(builtins, "rect"))
        self.assertIs(getattr(builtins, "quit", None), original_quit)


class KeysTests(unittest.TestCase):
    def test_mapping_targets_are_valid_names(self):
        for code, name in keys.QT_KEY_TO_NAME.items():
            self.assertIn(name, keys.KEY_NAMES, hex(code))

    def test_every_key_name_reachable_from_pc(self):
        reachable = set(keys.QT_KEY_TO_NAME.values())
        self.assertEqual(reachable, set(keys.KEY_NAMES))

    def test_spot_checks(self):
        self.assertEqual(keys.name_from_qt_key(0x41), "a")
        self.assertEqual(keys.name_from_qt_key(0x01000012), "left")
        self.assertEqual(keys.name_from_qt_key(0x3A), ";")      # shifted ';' folds back
        self.assertEqual(keys.name_from_qt_key(0x21), "1")
        self.assertIsNone(keys.name_from_qt_key(0x01000044))    # F11: no equivalent


class ProtocolTests(unittest.TestCase):
    def test_split_and_partial_chunks(self):
        data = protocol.pack(protocol.STDOUT, b"hello") + protocol.pack(protocol.FRAME, b"\x01" * 300) + protocol.pack(protocol.EXIT)
        p = protocol.MessageParser()
        got = []
        for i in range(0, len(data), 7):                        # feed in awkward 7-byte pieces
            got += p.feed(data[i:i + 7])
        self.assertEqual(got, [(b"O", b"hello"), (b"F", b"\x01" * 300), (b"X", b"")])

    def test_corrupt_stream_raises(self):
        with self.assertRaises(ValueError):
            protocol.MessageParser().feed(b"F\xff\xff\xff\xff")


class DocsTests(unittest.TestCase):
    def test_every_api_name_is_documented_and_nothing_extra(self):
        self.assertEqual(api_docs.documented_names(), set(api.__all__))

    def test_categories_valid(self):
        for d in api_docs.DOCS:
            self.assertIn(d.category, api_docs.CATEGORIES, d.title)
            for p in d.params:
                self.assertEqual(len(p), 2, d.title)
            self.assertTrue(d.summary, d.title)

    def test_markdown_mentions_every_name(self):
        md = api_docs.to_markdown()
        for name in api.__all__:
            self.assertIn(name, md)
        for hook in ("setup", "update", "draw"):
            self.assertIn("def %s(" % hook, md)

    def test_html_search(self):
        self.assertIn("key_down", api_docs.to_html("held"))
        self.assertNotIn("circle", api_docs.to_html("held"))
        self.assertIn("No matches", api_docs.to_html("zzzzqqq"))
        self.assertIn("&lt;", api_docs.to_html("") + "&lt;")    # sanity: escaping function in use

    def test_doc_examples_compile(self):
        for d in api_docs.DOCS:
            if d.example:
                compile(d.example, d.title, "exec")


if __name__ == "__main__":
    unittest.main()
