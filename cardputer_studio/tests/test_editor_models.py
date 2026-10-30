"""Document models behind the sprite, tilemap and sound editors."""
import json
import unittest

from helpers import ROOT  # noqa: F401
from cpg_studio.core.pixelimage import History, PixelImage, TRANSPARENT
from cpg_studio.core.sounddoc import SoundDoc
from cpg_studio.core.tilemap_doc import Layer, TilemapDoc, TilemapFormatError
from cpg_studio.runtime import assets
from cpg_studio.runtime.assets import AssetError

R, G, B = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)


def pixels(img):
    return [[img.get(x, y) for x in range(img.w)] for y in range(img.h)]


class PixelImageTests(unittest.TestCase):
    def test_new_is_transparent_and_set_get_bounds(self):
        img = PixelImage(3, 2)
        self.assertEqual(img.get(2, 1), TRANSPARENT)
        img.set(1, 1, R)
        img.set(-1, 0, R)
        img.set(3, 0, R)                                  # outside: ignored
        self.assertEqual(img.get(1, 1), R)
        self.assertEqual(sum(1 for row in pixels(img) for p in row if p != TRANSPARENT), 1)
        with self.assertRaises(ValueError):
            PixelImage(0, 5)
        with self.assertRaises(ValueError):
            PixelImage(2, 2, b"123")

    def test_png_round_trip(self):
        img = PixelImage(4, 3)
        img.set(0, 0, R)
        img.set(3, 2, (1, 2, 3, 128))
        back = PixelImage.from_png(img.to_png())
        self.assertEqual((back.w, back.h, bytes(back.data)), (4, 3, bytes(img.data)))

    def test_line_rect_ellipse(self):
        img = PixelImage(8, 8)
        img.line(0, 0, 7, 7, R)
        self.assertTrue(all(img.get(i, i) == R for i in range(8)))
        img = PixelImage(8, 8)
        img.line(1, 3, 6, 3, G)
        self.assertEqual([img.get(x, 3) for x in range(8)], [TRANSPARENT] + [G] * 6 + [TRANSPARENT])
        img = PixelImage(6, 6)
        img.rect(1, 1, 4, 4, B)
        self.assertEqual((img.get(1, 1), img.get(4, 4), img.get(2, 2)), (B, B, TRANSPARENT))
        img.rect(1, 1, 4, 4, B, fill=True)
        self.assertEqual(img.get(2, 2), B)
        img = PixelImage(9, 9)
        img.ellipse(0, 0, 8, 8, R, fill=True)
        self.assertEqual((img.get(4, 4), img.get(0, 0), img.get(4, 0)), (R, TRANSPARENT, R))
        outline = PixelImage(9, 9)
        outline.ellipse(0, 0, 8, 8, R)
        self.assertEqual((outline.get(4, 4), outline.get(4, 0), outline.get(0, 4)), (TRANSPARENT, R, R))
        img.rect(-5, -5, 20, 20, R, fill=True)            # off-image shapes are clipped, not errors

    def test_brush_size(self):
        img = PixelImage(5, 5)
        img.stamp(2, 2, R, 3)
        self.assertEqual(sum(1 for row in pixels(img) for p in row if p == R), 9)
        img = PixelImage(5, 5)
        img.stamp(0, 0, R, 3)                             # clipped at the corner
        self.assertEqual(sum(1 for row in pixels(img) for p in row if p == R), 4)

    def test_flood_fill(self):
        img = PixelImage(4, 4)
        img.rect(0, 1, 3, 1, R)                           # a red wall splits the image in two
        self.assertEqual(img.flood_fill(0, 0, G), 4)
        self.assertEqual(img.get(0, 2), TRANSPARENT)
        self.assertEqual(img.flood_fill(0, 3, B), 8)
        self.assertEqual(img.flood_fill(0, 3, B), 0)      # already that colour
        self.assertEqual(img.flood_fill(9, 9, B), 0)
        # fully transparent pixels count as the same colour whatever their RGB
        img = PixelImage(2, 1, bytes([5, 5, 5, 0, 9, 9, 9, 0]))
        self.assertEqual(img.flood_fill(0, 0, R), 2)

    def test_resize_flip_shift(self):
        img = PixelImage(2, 2)
        img.set(0, 0, R)
        img.set(1, 0, G)
        img.set(0, 1, B)
        big = img.resized(3, 4)
        self.assertEqual((big.w, big.h, big.get(1, 0), big.get(2, 3)), (3, 4, G, TRANSPARENT))
        small = img.resized(1, 1)
        self.assertEqual((small.w, small.h, small.get(0, 0)), (1, 1, R))
        flipped = img.flipped(True)
        self.assertEqual((flipped.get(0, 0), flipped.get(1, 0)), (G, R))
        self.assertEqual(img.flipped(False).get(0, 0), B)
        shifted = img.shifted(1, 0)
        self.assertEqual((shifted.get(1, 0), shifted.get(0, 0)), (R, G))      # wraps around

    def test_clear_replace_copy(self):
        img = PixelImage(2, 2)
        img.set(0, 0, R)
        dup = img.copy()
        img.clear()
        self.assertEqual(dup.get(0, 0), R)
        img.replace_data(dup.resized(3, 3))
        self.assertEqual((img.w, img.get(0, 0)), (3, R))


class HistoryTests(unittest.TestCase):
    def test_undo_redo(self):
        h = History(limit=3)
        h.record("a")
        h.record("b")
        self.assertEqual(h.undo("c"), "b")
        self.assertEqual(h.undo("b"), "a")
        self.assertIsNone(h.undo("a"))
        self.assertEqual(h.redo("a"), "b")
        self.assertTrue(h.can_undo() and h.can_redo())
        h.record("x")                                    # a new change drops the redo history
        self.assertFalse(h.can_redo())

    def test_limit(self):
        h = History(limit=2)
        for s in "abcd":
            h.record(s)
        self.assertEqual([h.undo("z"), h.undo("z"), h.undo("z")], ["d", "c", None])


class TilemapDocTests(unittest.TestCase):
    def doc(self):
        d = TilemapDoc.new("assets/tiles.png", 8, 8, 4, 3)
        d.set(0, 0, 0, 5)
        d.set(0, 3, 2, 7)
        d.solid = {5, 3}
        return d

    def test_json_round_trip_and_runtime_loader_accepts_it(self):
        d = self.doc()
        d.add_layer("sky")
        text = d.to_json()
        json.loads(text)                                  # valid JSON
        back = TilemapDoc.from_json(text)
        self.assertEqual((back.snapshot()), d.snapshot())
        self.assertEqual(text.count("\n") > 8, True)      # one row per line
        tileset = assets.sprite_from_png(PixelImage(80, 8).to_png(), 8, 8)    # 10 tiles
        tm = assets.tilemap_from_json(text, lambda *_: tileset, "x.map.json")
        self.assertEqual((tm.w, tm.h, tm.layer_names, tm.get(3, 2), sorted(tm.solid)), (4, 3, ["ground", "sky"], 7, [3, 5]))

    def test_bad_json(self):
        for bad in ("{", "[]", '{"tile_w": 8}', json.dumps({"tile_w": 8, "tile_h": 8, "width": 2, "height": 2,
                                                            "layers": [{"data": [1]}]}),
                    json.dumps({"tile_w": 8, "tile_h": 8, "width": 2, "height": 2, "layers": []})):
            with self.assertRaises(TilemapFormatError):
                TilemapDoc.from_json(bad)

    def test_painting(self):
        d = TilemapDoc.new("t.png", 8, 8, 4, 3)
        self.assertTrue(d.set(0, 1, 1, 2))
        self.assertFalse(d.set(0, 1, 1, 2))               # no change
        self.assertFalse(d.set(0, 9, 9, 2))
        self.assertEqual(d.get(0, 9, 9), -1)
        self.assertEqual(d.fill_rect(0, 3, 2, 0, 0, 4), 12)
        self.assertEqual(d.flood_fill(0, 0, 0, 9), 12)
        self.assertEqual(d.flood_fill(0, 0, 0, 9), 0)
        d.set(0, 1, 1, -1)
        self.assertEqual(d.flood_fill(0, 1, 1, 3), 1)     # an enclosed single tile

    def test_flood_fill_stays_inside_region(self):
        d = TilemapDoc.new("t.png", 8, 8, 3, 3)
        for y in range(3):
            d.set(0, 1, y, 1)                              # vertical wall
        self.assertEqual(d.flood_fill(0, 0, 0, 2), 3)
        self.assertEqual(d.get(0, 2, 0), -1)

    def test_resize_keeps_top_left(self):
        d = self.doc()
        d.resize(6, 2)
        self.assertEqual((d.w, d.h, d.get(0, 0, 0), d.get(0, 3, 2), d.get(0, 5, 1)), (6, 2, 5, -1, -1))
        d.resize(2, 2)
        self.assertEqual(len(d.layers[0].data), 4)
        with self.assertRaises(TilemapFormatError):
            d.resize(0, 5)
        with self.assertRaises(TilemapFormatError):
            d.resize(1000, 1000)

    def test_layers(self):
        d = self.doc()
        self.assertEqual(d.add_layer("ground"), 1)
        self.assertEqual([layer.name for layer in d.layers], ["ground", "ground 2"])
        self.assertTrue(d.rename_layer(1, "fx"))
        self.assertFalse(d.rename_layer(1, "ground"))     # duplicate
        self.assertFalse(d.rename_layer(1, "  "))
        self.assertTrue(d.rename_layer(1, "fx"))          # same name as itself is fine
        self.assertEqual(d.move_layer(1, -1), 0)
        self.assertEqual([layer.name for layer in d.layers], ["fx", "ground"])
        self.assertEqual(d.move_layer(0, -5), 0)
        self.assertTrue(d.remove_layer(0))
        self.assertFalse(d.remove_layer(0))               # the last layer stays

    def test_snapshot_restore_and_clamp(self):
        d = self.doc()
        snap = d.snapshot()
        d.set(0, 1, 1, 9)
        d.add_layer("x")
        d.restore(snap)
        self.assertEqual((len(d.layers), d.get(0, 1, 1), d.solid), (1, -1, {3, 5}))
        d.set(0, 2, 2, 12)
        self.assertEqual(d.clamp_to_tileset(6), 2)        # tiles 7 and 12 no longer exist
        self.assertEqual((d.get(0, 3, 2), d.solid), (-1, {3, 5}))

    def test_new_rejects_silly_sizes(self):
        with self.assertRaises(TilemapFormatError):
            TilemapDoc.new("t.png", 8, 8, 0, 3)
        with self.assertRaises(TilemapFormatError):
            TilemapDoc.new("t.png", 0, 8, 3, 3)
        self.assertIsInstance(Layer("a", []).visible, bool)


class SoundDocTests(unittest.TestCase):
    def test_round_trip_and_runtime_loader(self):
        d = SoundDoc("triangle", 0.25, [["C4", 100], [440, 50], ["rest", 20]])
        text = d.to_json()
        self.assertEqual(SoundDoc.from_json(text), d)
        s = assets.sound_from_json(text)
        self.assertEqual((s.wave, s.duration_ms, [f for f, _ in s.notes]), ("triangle", 170, [262, 440, 0]))
        self.assertEqual(d.duration_ms(), 170)

    def test_validation(self):
        self.assertIsNone(SoundDoc("square", 0.5, [["C4", 10]]).error())
        self.assertIn("at least one note", SoundDoc().error())
        self.assertIn("not a note", SoundDoc("square", 0.5, [["Q", 10]]).error())
        self.assertIn("unknown wave", SoundDoc("sine", 0.5, [["C4", 10]]).error())
        with self.assertRaises(AssetError):
            SoundDoc.from_json("{")
        with self.assertRaises(AssetError):
            SoundDoc.from_json('{"kind": "pcm"}')

    def test_editing(self):
        d = SoundDoc()
        d.add_note("C4", 100)
        d.add_note("E4", 100.0)
        d.add_note("G4", 300)
        self.assertEqual(d.move_note(2, -2), 0)
        self.assertEqual([n for n, _ in d.notes], ["G4", "C4", "E4"])
        self.assertEqual(d.move_note(0, -1), 0)


if __name__ == "__main__":
    unittest.main()
