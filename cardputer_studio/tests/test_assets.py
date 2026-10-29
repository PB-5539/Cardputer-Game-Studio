"""Sprites, tilemaps, sounds, the mixer, and the engine API that exposes them."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import wave

from helpers import ROOT  # noqa: F401  (puts the project on sys.path)
from cpg_studio.core.mixer import OUTPUT_RATE, Mixer
from cpg_studio.runtime import api, assets, png, protocol
from cpg_studio.runtime.assets import AssetError
from cpg_studio.runtime.framebuf_sim import FrameBuffer
from cpg_studio.runtime.runner import Session

try:
    from PIL import Image
except ImportError:                      # Pillow is only used to cross-check the PNG reader
    Image = None

RED, GREEN, BLUE = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)
MAGENTA, CLEAR = (255, 0, 255, 255), (9, 9, 9, 0)


def png_of(rows):
    """PNG bytes from rows of (r, g, b, a) tuples."""
    h, w = len(rows), len(rows[0])
    return png.encode(w, h, bytes(c for row in rows for px in row for c in px))


def rgb565(r, g, b):
    return api.rgb(r, g, b)


class PngTests(unittest.TestCase):
    def test_round_trip(self):
        rows = [[RED, GREEN, (1, 2, 3, 128)], [BLUE, CLEAR, (255, 255, 255, 255)]]
        w, h, got = png.decode(png_of(rows))
        self.assertEqual((w, h), (3, 2))
        self.assertEqual([tuple(r[i:i + 4]) for r in got for i in range(0, 12, 4)],
                         [px for row in rows for px in row])

    def test_bad_files(self):
        with self.assertRaises(png.PngError):
            png.decode(b"hello")
        with self.assertRaises(png.PngError):
            png.decode(png_of([[RED]])[:30])

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_matches_pillow_for_every_colour_type(self):
        import random
        rng = random.Random(7)
        cases = []
        for mode, make in (("1", lambda: rng.randint(0, 1)), ("L", lambda: rng.randint(0, 255)),
                           ("LA", lambda: (rng.randint(0, 255), rng.randint(0, 255))),
                           ("RGB", lambda: tuple(rng.randint(0, 255) for _ in range(3))),
                           ("RGBA", lambda: tuple(rng.randint(0, 255) for _ in range(4))),
                           ("P", lambda: rng.randint(0, 15))):
            im = Image.new(mode, (37, 23))          # big enough that Pillow picks varied row filters
            for y in range(23):
                for x in range(37):
                    im.putpixel((x, y), make())
            if mode == "P":
                im.putpalette([rng.randint(0, 255) for _ in range(48)])
            cases.append((mode, im, {}))
        grad = Image.new("RGB", (64, 64))
        for y in range(64):
            for x in range(64):
                grad.putpixel((x, y), (x * 4, y * 4, (x + y) * 2))
        cases.append(("gradient", grad, {}))
        paletted = Image.new("P", (8, 8))
        paletted.putpalette([rng.randint(0, 255) for _ in range(12)])
        for y in range(8):
            for x in range(8):
                paletted.putpixel((x, y), rng.randint(0, 3))
        cases.append(("2-bit palette", paletted, {"bits": 2}))
        cases.append(("palette transparency", paletted, {"transparency": 1}))
        for name, im, opts in cases:
            buf = io.BytesIO()
            im.save(buf, "PNG", **opts)
            w, h, rows = png.decode(buf.getvalue())
            ref = Image.open(io.BytesIO(buf.getvalue())).convert("RGBA")
            self.assertEqual(b"".join(rows), ref.tobytes(), name)

    def test_interlaced_is_rejected_with_advice(self):
        data = bytearray(png_of([[RED]]))
        data[8 + 8 + 12] = 1                      # IHDR interlace byte
        with self.assertRaisesRegex(png.PngError, "interlaced"):
            png.decode(bytes(data))


class SpriteTests(unittest.TestCase):
    def sheet(self):
        # 4x2 image = two 2x2 frames: frame 0 is red/green over blue/magenta, frame 1 is all clear but one pixel
        return png_of([[RED, GREEN, CLEAR, CLEAR], [BLUE, MAGENTA, CLEAR, (0, 0, 8, 255)]])

    def test_transparency_and_frames(self):
        spr = assets.sprite_from_png(self.sheet(), 2, 2, "s.png")
        self.assertEqual((spr.w, spr.h, spr.frame_count), (2, 2, 2))
        self.assertEqual(spr.pixel(0, 0), rgb565(255, 0, 0))
        self.assertIsNone(spr.pixel(1, 1))                      # magenta is the key
        self.assertIsNone(spr.pixel(0, 0, frame=1))             # transparent PNG pixel
        self.assertEqual(spr.pixel(1, 1, frame=1), rgb565(0, 0, 8))
        self.assertIsNone(spr.pixel(5, 5))
        self.assertEqual(spr.pixel(0, 0, frame=2), rgb565(255, 0, 0))     # frames wrap around

    def test_drawing_skips_transparent_pixels(self):
        spr = assets.sprite_from_png(self.sheet(), 2, 2)
        fb = FrameBuffer(8, 8)
        fb.fill(rgb565(1, 1, 1))
        fb.blit_runs(spr.runs(0), 3, 4)
        self.assertEqual(fb.get_pixel(3, 4), rgb565(255, 0, 0))
        self.assertEqual(fb.get_pixel(4, 4), rgb565(0, 255, 0))
        self.assertEqual(fb.get_pixel(3, 5), rgb565(0, 0, 255))
        self.assertEqual(fb.get_pixel(4, 5), rgb565(1, 1, 1))   # magenta pixel left the background alone

    def test_flips(self):
        spr = assets.sprite_from_png(self.sheet(), 2, 2)
        fb = FrameBuffer(4, 4)
        fb.blit_runs(spr.runs(0, flip_x=True), 0, 0)
        self.assertEqual((fb.get_pixel(0, 0), fb.get_pixel(1, 0)), (rgb565(0, 255, 0), rgb565(255, 0, 0)))
        fb = FrameBuffer(4, 4)
        fb.blit_runs(spr.runs(0, flip_y=True), 0, 0)
        self.assertEqual((fb.get_pixel(0, 0), fb.get_pixel(1, 1)), (rgb565(0, 0, 255), rgb565(0, 255, 0)))

    def test_clipping_on_every_edge(self):
        spr = assets.sprite_from_png(png_of([[RED] * 3] * 3))
        for x, y in ((-2, 0), (-5, -5), (6, 6), (2, 2), (0, -1), (-1, 3), (100, 0), (0, 100)):
            fb = FrameBuffer(5, 5)
            fb.blit_runs(spr.runs(), x, y)                      # must not raise or wrap
        fb = FrameBuffer(5, 5)
        fb.blit_runs(spr.runs(), -2, 3)
        self.assertEqual(fb.get_pixel(0, 3), rgb565(255, 0, 0))
        self.assertEqual(fb.get_pixel(1, 3), 0)
        self.assertEqual(fb.get_pixel(0, 2), 0)

    def test_errors(self):
        with self.assertRaisesRegex(AssetError, "bigger than the image"):
            assets.sprite_from_png(self.sheet(), 9, 9)
        with self.assertRaisesRegex(AssetError, "positive"):
            assets.sprite_from_png(self.sheet(), -1, 2)
        with self.assertRaisesRegex(AssetError, "not a PNG"):
            assets.sprite_from_png(b"nope", name="x.png")
        with self.assertRaisesRegex(AssetError, "not found"):
            assets.load_sprite_file("definitely/missing.png")


def tilemap_json(**over):
    doc = {"tileset": "tiles.png", "tile_w": 2, "tile_h": 2, "width": 3, "height": 2,
           "layers": [{"name": "ground", "data": [0, 1, 1, 0, -1, 1]}, {"name": "top", "data": [-1] * 6}],
           "solid": [1]}
    doc.update(over)
    return json.dumps(doc)


def tileset(*_):
    return assets.sprite_from_png(png_of([[RED, RED, GREEN, GREEN], [RED, RED, GREEN, GREEN]]), 2, 2)


class TilemapTests(unittest.TestCase):
    def load(self, **over):
        return assets.tilemap_from_json(tilemap_json(**over), tileset, "m.json")

    def test_basics(self):
        tm = self.load()
        self.assertEqual((tm.w, tm.h, tm.px_w, tm.px_h), (3, 2, 6, 4))
        self.assertEqual(tm.layer_names, ["ground", "top"])
        self.assertEqual((tm.get(1, 0), tm.get(0, 1), tm.get(1, 1), tm.get(9, 9)), (1, 0, -1, -1))
        self.assertEqual(tm.get(1, 0, "ground"), 1)
        tm.set(0, 0, 1, "top")
        self.assertEqual(tm.get(0, 0, 1), 1)
        tm.set(99, 99, 1)                                       # outside: ignored
        with self.assertRaises(ValueError):
            tm.set(0, 0, 7)
        with self.assertRaises(KeyError):
            tm.get(0, 0, "nope")

    def test_solid(self):
        tm = self.load()
        self.assertTrue(tm.is_solid(1, 0))
        self.assertFalse(tm.is_solid(0, 0))
        self.assertTrue(tm.is_solid(-1, 0) and tm.is_solid(0, 5))      # outside the map blocks
        self.assertTrue(tm.solid_at(2.5, 0.5))
        self.assertFalse(tm.solid_at(0.5, 0.5))
        tm.set(0, 0, 1, "top")                                  # solid on any layer counts
        self.assertTrue(tm.is_solid(0, 0))

    def test_draw_with_camera(self):
        tm = self.load()
        fb = FrameBuffer(6, 4)
        tm.draw(fb, 0, 0)
        self.assertEqual(fb.get_pixel(0, 0), rgb565(255, 0, 0))     # tile 0
        self.assertEqual(fb.get_pixel(2, 0), rgb565(0, 255, 0))     # tile 1
        self.assertEqual(fb.get_pixel(2, 2), 0)                     # empty tile (-1)
        fb = FrameBuffer(6, 4)
        tm.draw(fb, 3, 1)                                           # scrolled by (3, 1)
        self.assertEqual(fb.get_pixel(1, 0), rgb565(0, 255, 0))     # map x=4 is tile 1 of the top row
        fb = FrameBuffer(6, 4)
        tm.draw(fb, -100, -100)
        tm.draw(fb, 100, 100)                                       # far outside: draws nothing, no error

    def test_single_layer_draw(self):
        tm = self.load()
        tm.set(0, 0, 1, "top")
        fb = FrameBuffer(6, 4)
        tm.draw(fb, 0, 0, "top")
        self.assertEqual(fb.get_pixel(0, 0), rgb565(0, 255, 0))
        self.assertEqual(fb.get_pixel(2, 0), 0)                     # ground layer not drawn

    def test_validation_messages(self):
        for over, message in (({"width": 0}, "width"), ({"tile_w": "8"}, "tile_w"),
                              ({"tileset": ""}, "tileset"), ({"layers": []}, "layers"),
                              ({"layers": [{"name": "a", "data": [0]}]}, "needs"),
                              ({"layers": [{"name": "a", "data": [5] * 6}]}, "only has tiles 0-1"),
                              ({"layers": [{"name": "a", "data": [0] * 6}, {"name": "a", "data": [0] * 6}]}, "two layers"),
                              ({"solid": ["x"]}, "solid")):
            with self.assertRaisesRegex(AssetError, message):
                self.load(**over)
        with self.assertRaisesRegex(AssetError, "not valid JSON"):
            assets.tilemap_from_json("{", tileset, "m.json")


class SoundTests(unittest.TestCase):
    def test_note_names(self):
        self.assertEqual([assets.note_freq(n) for n in ("A4", "C4", "a4", "F#3", "Bb5", "C-1")], [440, 262, 440, 185, 932, 8])
        self.assertEqual((assets.note_freq("rest"), assets.note_freq(440.4), assets.note_freq("523")), (0, 440, 523))
        with self.assertRaisesRegex(AssetError, "not a note"):
            assets.note_freq("H9")

    def test_note_string(self):
        s = assets.parse_note_string("C4:100 rest:50 G4", wave_shape="triangle", volume=0.3)
        self.assertEqual((s.kind, s.notes, s.wave, s.duration_ms), ("tones", [(262, 100), (0, 50), (392, 200)], "triangle", 350))
        self.assertAlmostEqual(s.volume, 0.3)
        with self.assertRaises(AssetError):
            assets.parse_note_string("C4:fast")
        with self.assertRaises(AssetError):
            assets.parse_note_string("")
        with self.assertRaisesRegex(AssetError, "unknown wave"):
            assets.parse_note_string("C4", wave_shape="sine")

    def test_json(self):
        s = assets.sound_from_json('{"wave": "saw", "volume": 2, "notes": [["C4", 10], [440, 20]]}', "a.json")
        self.assertEqual((s.wave, s.volume, s.duration_ms), ("saw", 1.0, 30))
        for bad in ('{"notes": [["C4"]]}', '{"notes": [["C4", 0]]}', '{"kind": "pcm"}', "[", '{"notes": []}',
                    '{"volume": "loud", "notes": [["C4", 5]]}'):
            with self.assertRaises(AssetError, msg=bad):
                assets.sound_from_json(bad)

    def wav_bytes(self, channels=2, width=2, rate=44100, frames=4410):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.setframerate(rate)
            if width == 2:
                data = b"".join(struct.pack("<h", 12000 if (i // 50) % 2 else -12000) * channels for i in range(frames))
            else:
                data = bytes((200 if (i // 50) % 2 else 50) for i in range(frames * channels))
            w.writeframes(data)
        return buf.getvalue()

    def test_wav_conversion(self):
        s = assets.sound_from_wav(self.wav_bytes(), "a.wav")
        self.assertEqual((s.kind, s.rate), ("pcm", 11025))
        self.assertAlmostEqual(s.duration_ms, 100, delta=2)
        self.assertEqual(len(s.data), 1102)
        self.assertTrue(all(0 <= b <= 255 for b in s.data))
        self.assertGreater(max(s.data), 160)                     # the square wave survived
        self.assertLess(min(s.data), 95)

    def test_wav_variants(self):
        mono8 = assets.sound_from_wav(self.wav_bytes(channels=1, width=1, rate=8000, frames=800), "m.wav")
        self.assertEqual((mono8.rate, len(mono8.data)), (8000, 800))   # never upsampled
        with self.assertRaisesRegex(AssetError, "longer than"):
            assets.sound_from_wav(self.wav_bytes(channels=1, rate=8000, frames=8000 * 31), "long.wav")
        with self.assertRaisesRegex(AssetError, "not a readable WAV"):
            assets.sound_from_wav(b"RIFFjunk", "bad.wav")


def play_message(cmd, blob=b""):
    return json.dumps(cmd).encode() + (b"\n" + blob if blob else b"")


class MixerTests(unittest.TestCase):
    def samples(self, data):
        return struct.unpack("<%dh" % (len(data) // 2), data)

    def test_tone_plays_then_ends(self):
        m = Mixer()
        m.handle(play_message({"op": "tone", "freq": 440, "ms": 50}))
        self.assertTrue(m.active())
        first = self.samples(m.render(OUTPUT_RATE // 100))       # 10 ms
        self.assertGreater(max(first), 1000)
        self.assertLess(min(first), -1000)
        m.render(OUTPUT_RATE // 10)                              # well past its 50 ms
        self.assertFalse(m.active())
        self.assertEqual(set(self.samples(m.render(100))), {0})

    def test_tone_pitch(self):
        m = Mixer()
        m.handle(play_message({"op": "tone", "freq": 1000, "ms": 1000}))
        out = self.samples(m.render(OUTPUT_RATE))
        crossings = sum(1 for a, b in zip(out, out[1:]) if a < 0 <= b)
        self.assertAlmostEqual(crossings, 1000, delta=3)

    def test_all_waves_make_sound_and_stay_in_range(self):
        for wave_shape in assets.WAVES:
            m = Mixer()
            m.handle(play_message({"op": "load", "id": 1, "kind": "tones", "notes": [[300, 100]], "wave": wave_shape}))
            m.handle(play_message({"op": "play", "id": 1, "volume": 1.0}))
            out = self.samples(m.render(1000))
            self.assertGreater(max(map(abs, out)), 500, wave_shape)
            self.assertLessEqual(max(map(abs, out)), 32767)

    def test_sequence_loop_and_rests(self):
        m = Mixer()
        m.handle(play_message({"op": "load", "id": 1, "kind": "tones", "notes": [[500, 20], [0, 20]]}))
        m.handle(play_message({"op": "play", "id": 1, "loop": True}))
        out = self.samples(m.render(OUTPUT_RATE * 3 // 25))      # 120 ms = three 40 ms loops
        self.assertTrue(m.active())
        quiet = out[int(OUTPUT_RATE * 0.025):int(OUTPUT_RATE * 0.035)]    # inside the first rest
        self.assertEqual(set(quiet), {0})
        loud = out[int(OUTPUT_RATE * 0.045):int(OUTPUT_RATE * 0.055)]     # second pass's first note
        self.assertGreater(max(map(abs, loud)), 500)

    def test_pcm_and_stop(self):
        m = Mixer()
        m.handle(play_message({"op": "load", "id": 2, "kind": "pcm", "rate": 11025}, bytes([255] * 200)))
        m.handle(play_message({"op": "play", "id": 2, "loop": True}))
        out = self.samples(m.render(1000))
        self.assertTrue(all(v > 1000 for v in out))
        self.assertTrue(m.active())                              # loops
        m.handle(play_message({"op": "stop", "id": 99}))
        self.assertTrue(m.active())                              # other ids untouched
        m.handle(play_message({"op": "stop", "id": 2}))
        self.assertFalse(m.active())

    def test_stop_all_and_voice_limit_and_garbage(self):
        m = Mixer(max_voices=3)
        for _ in range(6):
            m.handle(play_message({"op": "tone", "freq": 300, "ms": 5000}))
        self.assertEqual(len(m.voices), 3)
        m.handle(play_message({"op": "stop", "id": None}))
        self.assertFalse(m.active())
        for junk in (b"", b"not json", b'{"op": "play", "id": 77}', b'{"op": "zzz"}', b'{"op": "load"}', b"[1]"):
            m.handle(junk)                                       # ignored, no exception
        self.assertFalse(m.active())

    def test_loud_mixes_are_clipped_not_wrapped(self):
        m = Mixer()
        for _ in range(8):
            m.handle(play_message({"op": "load", "id": 1, "kind": "pcm", "rate": 22050}, bytes([255] * 500)))
            m.handle(play_message({"op": "play", "id": 1, "volume": 1.0}))
        self.assertTrue(all(0 < v <= 32767 for v in self.samples(m.render(200))))


@contextlib.contextmanager
def project(files):
    """Run code inside a temp project folder (text files from a dict, binary ones from bytes)."""
    old_cwd, old_path = os.getcwd(), list(sys.path)
    api._reset()
    with tempfile.TemporaryDirectory() as tmp:
        for name, data in files.items():
            path = os.path.join(tmp, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data if isinstance(data, bytes) else data.encode())
        os.chdir(tmp)
        try:
            yield tmp
        finally:
            api.remove_builtins()
            os.chdir(old_cwd)
            sys.path[:] = old_path


HERO = png_of([[RED, GREEN, BLUE, MAGENTA], [RED, GREEN, BLUE, MAGENTA]])


class ApiTests(unittest.TestCase):
    def test_load_and_draw_sprite(self):
        with project({"assets/hero.png": HERO}):
            hero = api.load_sprite("assets/hero.png", 2, 2)
            self.assertIs(hero, api.load_sprite("assets/hero.png", 2, 2))          # cached
            self.assertIsNot(hero, api.load_sprite("assets/hero.png"))             # different frame size
            api.clear()
            api.draw_sprite(hero, 10.7, 20.2, frame=1)
            fb = api._s.fb
            self.assertEqual(fb.get_pixel(10, 20), rgb565(0, 0, 255))
            self.assertEqual(fb.get_pixel(11, 20), 0)                                # magenta: see-through

    def test_load_tilemap_and_draw(self):
        files = {"tiles.png": png_of([[RED, RED, GREEN, GREEN], [RED, RED, GREEN, GREEN]]),
                 "level.map.json": tilemap_json()}
        with project(files):
            level = api.load_tilemap("level.map.json")
            self.assertEqual(level.tileset.frame_count, 2)
            api.draw_tilemap(level, 1, 0)
            self.assertEqual(api._s.fb.get_pixel(0, 0), rgb565(255, 0, 0))

    def test_friendly_errors(self):
        with project({}):
            with self.assertRaisesRegex(AssetError, "not found"):
                api.load_sprite("nope.png")
            with self.assertRaisesRegex(TypeError, "needs a Sprite"):
                api.draw_sprite("hero", 0, 0)
            with self.assertRaisesRegex(TypeError, "needs a Tilemap"):
                api.draw_tilemap(None)
            with self.assertRaisesRegex(TypeError, "needs a Sound"):
                api.play_sound("jump")

    def test_sound_calls_reach_the_audio_callback(self):
        with project({"a.sfx.json": '{"notes": [["C4", 50]]}'}):
            got = []
            api._s.on_audio = lambda op, snd, opts: got.append((op, snd, opts))
            snd = api.load_sound("a.sfx.json")
            api.play_sound(snd, loop=True, volume=3)
            api.stop_sound(snd)
            api.stop_sound()
            api.play_sound(api.tones("C4 E4"))
            api.beep(440, 30)
            self.assertEqual([g[0] for g in got], ["play", "stop", "stop", "play", "tone"])
            self.assertEqual(got[0][2], {"loop": True, "volume": 1.0})              # volume is clamped
            self.assertIsNone(got[2][1])
            self.assertEqual(got[4][2], {"freq": 440, "ms": 30})

    def test_audio_calls_are_silent_without_a_listener(self):
        with project({}):
            api.play_sound(api.tones("C4"))
            api.stop_sound()
            api.beep()

    def test_new_names_are_injected_for_games(self):
        for name in ("load_sprite", "draw_sprite", "load_tilemap", "draw_tilemap", "load_sound", "tones",
                     "play_sound", "stop_sound"):
            self.assertIn(name, api.__all__)


GAME = '''
hero = load_sprite("hero.png", 2, 2)
level = load_tilemap("level.map.json")
beep_sound = tones("C4:50")

def setup():
    play_sound(beep_sound)
    play_sound(load_sound("jump.sfx.json"), loop=True)
    beep(500, 10)

def draw():
    clear()
    draw_tilemap(level)
    draw_sprite(hero, 10, 10)
    stop_sound()
    quit()
'''


class RunnerAudioTests(unittest.TestCase):
    def test_game_with_assets_streams_frames_and_audio(self):
        files = {"main.py": GAME, "hero.png": HERO, "jump.sfx.json": '{"notes": [["A4", 30]]}',
                 "tiles.png": png_of([[RED, RED, GREEN, GREEN], [RED, RED, GREEN, GREEN]]),
                 "level.map.json": tilemap_json()}
        with project(files) as tmp:
            msgs = []
            session = Session(tmp, lambda kind, payload: msgs.append((kind, payload)))
            ok = session.load() and session.run(max_frames=3)
            self.assertTrue(ok, [p for k, p in msgs if k == protocol.ERROR])
        audio = [p for k, p in msgs if k == protocol.AUDIO]
        heads = [json.loads(p.split(b"\n", 1)[0]) for p in audio]
        self.assertEqual([h["op"] for h in heads], ["load", "play", "load", "play", "tone", "stop"])
        self.assertEqual(heads[0]["kind"], "tones")
        self.assertEqual(heads[3]["loop"], True)
        # feed the very same messages to the mixer, as the IDE does
        m = Mixer()
        for p in audio[:5]:
            m.handle(p)
        self.assertEqual(len(m.voices), 3)
        frames = [p for k, p in msgs if k == protocol.FRAME]
        self.assertTrue(frames)
        self.assertEqual(struct.unpack_from("<H", frames[0], (10 * api.WIDTH + 10) * 2)[0], rgb565(255, 0, 0))

    def test_sound_data_is_only_sent_once(self):
        game = 'snd = tones("C4:50")\ndef update(dt):\n    play_sound(snd)\n    play_sound(snd)\n'
        with project({"main.py": game}) as tmp:
            msgs = []
            session = Session(tmp, lambda kind, payload: msgs.append((kind, payload)))
            self.assertTrue(session.load() and session.run(max_frames=2))
        ops = [json.loads(p.split(b"\n", 1)[0])["op"] for k, p in msgs if k == protocol.AUDIO]
        self.assertEqual(ops, ["load"] + ["play"] * 4)

    def test_pcm_sound_is_sent_with_its_samples(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(11025)
            w.writeframes(struct.pack("<h", 9000) * 1000)
        game = 'def setup():\n    play_sound(load_sound("boom.wav"))\n    quit()\n'
        with project({"main.py": game, "boom.wav": buf.getvalue()}) as tmp:
            msgs = []
            session = Session(tmp, lambda kind, payload: msgs.append((kind, payload)))
            self.assertTrue(session.load() and session.run(max_frames=1), msgs)
        load = next(p for k, p in msgs if k == protocol.AUDIO)
        head, blob = load.split(b"\n", 1)
        self.assertEqual(json.loads(head)["kind"], "pcm")
        self.assertEqual(len(blob), 1000)


if __name__ == "__main__":
    unittest.main()
