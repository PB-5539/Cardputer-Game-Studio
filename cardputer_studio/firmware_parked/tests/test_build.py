import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build  # noqa: E402


class StageTests(unittest.TestCase):
    def test_stage_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build.stage(ROOT / "games" / "demo", Path(tmp) / "stage")
            frozen = out / "frozen"
            self.assertTrue((frozen / "engine" / "core.py").is_file())
            self.assertTrue((frozen / "engine" / "hal_cardputer.py").is_file())
            self.assertTrue((frozen / "game" / "__init__.py").is_file())
            self.assertIn("engine.run(game.Game())", (frozen / "main.py").read_text())
            manifest = (out / "manifest.py").read_text()
            self.assertIn('freeze("/stage/frozen")', manifest)
            self.assertFalse(list(frozen.rglob("__pycache__")))

    def test_stage_rejects_non_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                build.stage(tmp, Path(tmp) / "stage")

    def test_staged_python_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build.stage(ROOT / "games" / "keytest", Path(tmp) / "stage")
            for py in out.rglob("*.py"):
                compile(py.read_text(), str(py), "exec")


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_docker_commands(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = build.main([str(ROOT / "games" / "demo"), "--dry-run"])
        text = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("docker build -t cardputer-engine-build", text)
        self.assertIn("IDF_TAG=" + build.IDF_TAG, text)
        self.assertIn("MPY_TAG=" + build.MPY_TAG, text)
        self.assertIn(":/stage:ro", text)
        self.assertIn(build.DEFAULT_BOARD, text)


if __name__ == "__main__":
    unittest.main()
