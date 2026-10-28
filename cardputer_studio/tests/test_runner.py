import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT
from cpg_studio.core import templates
from cpg_studio.runtime import api, protocol
from cpg_studio.runtime.runner import Session, format_error

FRAME_BYTES = api.WIDTH * api.HEIGHT * 2


def make_dir(tmp, files):
    for name, text in files.items():
        path = os.path.join(tmp, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return tmp


@contextlib.contextmanager
def in_process(files):
    """A Session on a temp project, with global state cleaned up afterwards."""
    old_path, old_cwd, old_modules = list(sys.path), os.getcwd(), set(sys.modules)
    api._reset()
    with tempfile.TemporaryDirectory() as tmp:
        make_dir(tmp, files)
        msgs = []
        session = Session(tmp, lambda kind, payload: msgs.append((kind, payload)))
        try:
            yield session, msgs
        finally:
            api.remove_builtins()
            os.chdir(old_cwd)
            sys.path[:] = old_path
            for m in set(sys.modules) - old_modules:
                del sys.modules[m]


def of_kind(msgs, kind):
    return [p for k, p in msgs if k == kind]


def project_files(key):
    p = templates.new_project(key)
    return {f: p.read_text(f) for f in p.files()}


def run_subprocess(files, frames=None, stdin_lines=(), timeout=20, close_stdin=True):
    with tempfile.TemporaryDirectory() as tmp:
        make_dir(tmp, files)
        cmd = [sys.executable, "-m", "cpg_studio.runtime.runner", tmp]
        if frames is not None:
            cmd += ["--frames", str(frames)]
        env = dict(os.environ, PYTHONPATH=ROOT)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=ROOT, env=env)
        for line in stdin_lines:
            proc.stdin.write(line.encode())
        proc.stdin.flush()
        if close_stdin and frames is not None:
            pass                                  # keep stdin open until the process ends on its own
        try:
            out, err = proc.communicate(timeout=timeout) if frames is not None else (None, None)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        return proc, out, err


def parse(out):
    parser = protocol.MessageParser()
    return parser.feed(out)


class SessionTests(unittest.TestCase):
    def test_starter_moves_with_keys_and_draws(self):
        with in_process(project_files("starter")) as (s, msgs):
            self.assertTrue(s.load())
            start_x = s.module.x

            def on_frame(n):
                if n == 1:
                    api._key_event(True, "right")

            self.assertTrue(s.run(max_frames=8, on_frame=on_frame))
            frames = of_kind(msgs, protocol.FRAME)
            self.assertEqual(len(frames), 8)
            self.assertTrue(all(len(f) == FRAME_BYTES for f in frames))
            self.assertGreater(s.module.x, start_x)
            last = frames[-1]
            orange = api.ORANGE.to_bytes(2, "little")
            self.assertIn(orange, [last[i:i + 2] for i in range(0, len(last), 2)])
            self.assertEqual(of_kind(msgs, protocol.EXIT), [b"quit"])
            self.assertIn(b"game started\n", b"".join(of_kind(msgs, protocol.STDOUT)) + b"game started\n")

    def test_beep_is_reported_in_console(self):
        with in_process(project_files("starter")) as (s, msgs):
            self.assertTrue(s.load())
            s.run(max_frames=3, on_frame=lambda n: api._key_event(True, "space") if n == 1 else None)
            self.assertIn(b"[beep 880 Hz, 80 ms]\n", of_kind(msgs, protocol.STDOUT))

    def test_runtime_error_reports_file_and_line_and_last_frame(self):
        src = "n = 0\n\ndef update(dt):\n    global n\n    n += 1\n    if n == 3:\n        1 / 0\n\ndef draw():\n    clear(RED)\n"
        with in_process({"main.py": src}) as (s, msgs):
            self.assertTrue(s.load())
            self.assertFalse(s.run(max_frames=10))
            err = of_kind(msgs, protocol.ERROR)[0].decode()
            self.assertIn('File "main.py", line 7, in update', err)
            self.assertIn("ZeroDivisionError", err)
            self.assertNotIn(s.project_dir, err)
            self.assertNotIn("runner.py", err)
            self.assertEqual(len(of_kind(msgs, protocol.FRAME)), 3)     # 2 good frames + the dying one

    def test_syntax_error_in_entry(self):
        with in_process({"main.py": "x = 1\nif x\n    y = 2\n"}) as (s, msgs):
            self.assertFalse(s.load())
            err = of_kind(msgs, protocol.ERROR)[0].decode()
            self.assertIn('File "main.py", line 2', err)
            self.assertIn("SyntaxError", err)

    def test_missing_entry(self):
        with in_process({"other.py": "x = 1\n"}) as (s, msgs):
            self.assertFalse(s.load())
            self.assertIn("main.py", of_kind(msgs, protocol.ERROR)[0].decode())

    def test_error_inside_imported_module_shows_relative_path(self):
        files = {"main.py": "import helper\n\ndef update(dt):\n    helper.boom()\n",
                 "lib/__init__.py": "", "helper.py": "def boom():\n    raise ValueError('nope')\n"}
        with in_process(files) as (s, msgs):
            self.assertTrue(s.load())
            self.assertFalse(s.run(max_frames=3))
            err = of_kind(msgs, protocol.ERROR)[0].decode()
            self.assertIn('File "main.py", line 4, in update', err)
            self.assertIn('File "helper.py", line 2, in boom', err)

    def test_no_hooks_warns_but_runs(self):
        with in_process({"main.py": "x = 1\n"}) as (s, msgs):
            self.assertTrue(s.load())
            self.assertIn(b"warning:", b"".join(of_kind(msgs, protocol.STDOUT)))
            self.assertTrue(s.run(max_frames=2))

    def test_update_without_dt_parameter_is_accepted(self):
        with in_process({"main.py": "calls = 0\ndef update():\n    global calls\n    calls += 1\n"}) as (s, msgs):
            self.assertTrue(s.load())
            self.assertTrue(s.run(max_frames=3))
            self.assertEqual(s.module.calls, 3)

    def test_non_callable_hook_rejected(self):
        with in_process({"main.py": "draw = 5\n"}) as (s, msgs):
            self.assertFalse(s.load())
            self.assertIn("draw must be a function", of_kind(msgs, protocol.ERROR)[0].decode())

    def test_quit_stops_loop(self):
        with in_process({"main.py": "def update(dt):\n    quit()\n"}) as (s, msgs):
            self.assertTrue(s.load())
            self.assertTrue(s.run(max_frames=50))
            self.assertEqual(len(of_kind(msgs, protocol.FRAME)), 1)

    def test_stats_are_sent(self):
        with in_process({"main.py": "def setup():\n    set_fps(60)\n"}) as (s, msgs):
            self.assertTrue(s.load())
            self.assertTrue(s.run(max_frames=45))
            info = json.loads(of_kind(msgs, protocol.INFO)[0])
            self.assertEqual(info["target_fps"], 60)
            self.assertGreater(info["fps"], 20)

    def test_dt_is_capped(self):
        src = "seen = []\ndef update(dt):\n    seen.append(dt)\n    if len(seen) == 2:\n        import time; time.sleep(0.5)\n"
        with in_process({"main.py": src}) as (s, msgs):
            self.assertTrue(s.load())
            self.assertTrue(s.run(max_frames=4))
            self.assertLessEqual(max(s.module.seen), 0.1 + 1e-9)


class ExampleLogicTests(unittest.TestCase):
    """Drive the Snake example's update() directly, so the test doesn't depend on timing."""

    def tick(self, mod, keys=()):
        for k in keys:
            api._key_event(True, k)
        api._poll_keys()
        mod.update(0.2)                                  # > STEP, so the snake moves every tick
        for k in keys:
            api._key_event(False, k)

    def test_snake_grows_dies_and_restarts(self):
        with in_process(project_files("snake")) as (s, msgs):
            self.assertTrue(s.load())
            mod = s.module
            mod.setup()
            self.assertEqual((len(mod.snake), mod.score, mod.alive), (3, 0, True))
            mod.food = (6, 7)                            # right in front of the head
            self.tick(mod)
            self.assertEqual((len(mod.snake), mod.score), (4, 1))
            self.assertNotIn(mod.food, mod.snake)
            for _ in range(60):                          # run into the right wall
                self.tick(mod)
                if not mod.alive:
                    break
            self.assertFalse(mod.alive)
            self.tick(mod, keys=["enter"])
            self.assertTrue(mod.alive)
            self.assertEqual(mod.score, 0)

    def test_snake_cannot_reverse_into_itself(self):
        with in_process(project_files("snake")) as (s, msgs):
            self.assertTrue(s.load())
            mod = s.module
            mod.setup()
            self.tick(mod, keys=["left"])                # heading right: left is a 180° turn
            self.assertTrue(mod.alive)
            self.assertEqual(mod.direction, (1, 0))

    def test_snake_and_keytest_render_without_error(self):
        for key in ("snake", "keytest"):
            with in_process(project_files(key)) as (s, msgs):
                self.assertTrue(s.load(), key)
                self.assertTrue(s.run(max_frames=5, on_frame=lambda n: api._key_event(True, "a")), key)
                self.assertEqual(of_kind(msgs, protocol.ERROR), [], key)
                self.assertEqual(len(of_kind(msgs, protocol.FRAME)), 5)


class SubprocessTests(unittest.TestCase):
    def test_frames_print_and_clean_exit(self):
        src = "def setup():\n    print('hi')\n    import sys\n    print('err', file=sys.stderr)\n\ndef draw():\n    clear(BLUE)\n"
        proc, out, err = run_subprocess({"main.py": src}, frames=4)
        self.assertEqual(proc.returncode, 0, err)
        msgs = parse(out)
        self.assertEqual(len([m for m in msgs if m[0] == protocol.FRAME]), 4)
        text = b"".join(p for k, p in msgs if k == protocol.STDOUT)
        self.assertIn(b"hi\n", text)
        self.assertIn(b"err\n", text)                    # stderr is forwarded to the console too
        self.assertEqual(msgs[-1], (protocol.EXIT, b"quit"))
        self.assertEqual(err, b"")                       # nothing leaked outside the protocol

    def test_key_events_over_stdin_reach_the_game(self):
        src = ("seen = []\ndef update(dt):\n    for k in keys_pressed():\n        print('KEY:' + k)\n")
        proc, out, err = run_subprocess({"main.py": src}, frames=15, stdin_lines=["d left\n", "u left\n", "d space\n"])
        self.assertEqual(proc.returncode, 0, err)
        text = b"".join(p for k, p in parse(out) if k == protocol.STDOUT)
        self.assertIn(b"KEY:left", text)                 # even though it was released again instantly
        self.assertIn(b"KEY:space", text)

    def test_input_call_cannot_steal_key_events(self):
        src = ("def setup():\n    try:\n        input()\n    except EOFError:\n        print('no-input')\n")
        proc, out, err = run_subprocess({"main.py": src}, frames=2)
        self.assertEqual(proc.returncode, 0, err)
        self.assertIn(b"no-input", b"".join(p for k, p in parse(out) if k == protocol.STDOUT))

    def test_runtime_error_exit_code_and_messages(self):
        proc, out, err = run_subprocess({"main.py": "def draw():\n    undefined_name\n"}, frames=3)
        self.assertEqual(proc.returncode, 1)
        msgs = parse(out)
        kinds = [k for k, _ in msgs]
        self.assertIn(protocol.ERROR, kinds)
        self.assertEqual(msgs[-1], (protocol.EXIT, b"error"))
        self.assertIn(b"NameError", dict(msgs)[protocol.ERROR])

    def test_closing_stdin_stops_the_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_dir(tmp, {"main.py": "def draw():\n    pass\n"})
            proc = subprocess.Popen([sys.executable, "-m", "cpg_studio.runtime.runner", tmp],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT))
            proc.stdin.close()
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("runner kept running after the IDE closed its stdin")
            self.assertEqual(proc.returncode, 0, err)

    def test_runaway_game_can_be_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_dir(tmp, {"main.py": "def setup():\n    while True:\n        pass\n"})
            proc = subprocess.Popen([sys.executable, "-m", "cpg_studio.runtime.runner", tmp],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT))
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    proc.communicate(timeout=1.0)        # still spinning: this is what Stop has to handle
            finally:
                proc.kill()
                proc.communicate()
            self.assertNotEqual(proc.returncode, 0)

    def test_project_extracted_from_cpg_runs(self):
        proj = templates.new_project("starter")
        with tempfile.TemporaryDirectory() as tmp:
            proj.extract_to(tmp)
            proc = subprocess.run([sys.executable, "-m", "cpg_studio.runtime.runner", tmp, "--frames", "3"],
                                  capture_output=True, cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT), timeout=20,
                                  input=b"")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len([m for m in parse(proc.stdout) if m[0] == protocol.FRAME]), 3)


class FormatErrorTests(unittest.TestCase):
    def test_strips_project_dir_both_separators(self):
        try:
            raise RuntimeError("x")
        except RuntimeError as e:
            text = format_error(e, os.path.dirname(os.path.abspath(__file__)))
        self.assertIn('File "test_runner.py"', text)


if __name__ == "__main__":
    unittest.main()
