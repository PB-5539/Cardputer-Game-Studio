import importlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "games")]

import engine  # noqa: E402


class FakeCanvas:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name,) + a)


class FakeHAL:
    """Feeds scripted key sets and quits the engine after `frames` frames."""

    def __init__(self, key_script, frames):
        self.canvas = FakeCanvas()
        self.script = list(key_script)
        self.frames = frames
        self.shows = 0
        self.engine = None

    def poll_keys(self):
        return set(self.script.pop(0)) if self.script else set()

    def show(self):
        self.shows += 1
        if self.shows >= self.frames:
            self.engine_quit()

    def engine_quit(self):
        raise StopIteration


def run_frames(game, keys=(), frames=5):
    hal = FakeHAL(keys, frames)
    try:
        engine.run(game, hal=hal, fps=1000)
    except StopIteration:
        pass
    return hal


class EngineTests(unittest.TestCase):
    def test_rgb_is_byte_swapped_565(self):
        self.assertEqual(engine.rgb(255, 255, 255), 0xFFFF)
        self.assertEqual(engine.rgb(255, 0, 0), 0x00F8)     # 0xF800 swapped
        self.assertEqual(engine.rgb(0, 0, 255), 0x1F00)     # 0x001F swapped

    def test_key_edges(self):
        seen = []

        class G(engine.Game):
            def update(self, e, dt):
                seen.append((set(e.down), set(e.pressed)))

        run_frames(G(), keys=[{"a"}, {"a"}, set()], frames=3)
        self.assertEqual(seen, [({"a"}, {"a"}), ({"a"}, set()), (set(), set())])

    def test_demo_game_runs_and_draws(self):
        mod = importlib.import_module("demo")
        hal = run_frames(mod.Game(), keys=[set(), {"x"}], frames=4)
        names = {c[0] for c in hal.canvas.calls}
        self.assertTrue({"fill", "fill_rect", "text"} <= names)

    def test_keytest_lists_keys(self):
        mod = importlib.import_module("keytest")
        hal = run_frames(mod.Game(), keys=[{"s0i1", "s2i3"}], frames=1)
        texts = [c[1] for c in hal.canvas.calls if c[0] == "text"]
        self.assertIn("s0i1 s2i3", texts)


if __name__ == "__main__":
    unittest.main()
