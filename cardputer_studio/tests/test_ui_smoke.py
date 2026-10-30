"""Smoke tests for the window logic.

With PySide6 installed these run against real Qt (offscreen, no display needed). Without it they
run against tests/fake_qt.py, which checks wiring and logic but not that Qt calls are valid.
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from helpers import ROOT
from cpg_studio.core import templates
from cpg_studio.core.diagnostics import Diagnostic
from cpg_studio.runtime import protocol

try:
    import PySide6.QtWidgets  # noqa: F401
    REAL_QT = True
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
except ImportError:
    import fake_qt
    fake_qt.install()
    REAL_QT = False

from PySide6.QtWidgets import QApplication  # noqa: E402

if REAL_QT:
    _app = QApplication.instance() or QApplication([])

from cpg_studio import firmware  # noqa: E402
from cpg_studio.ui import main_window as mw  # noqa: E402
from cpg_studio.ui.panels import ProblemsPanel  # noqa: E402
from cpg_studio.ui.runner_controller import RunnerController  # noqa: E402
from cpg_studio.ui import runner_controller as rc  # noqa: E402


class FakeBox:
    """Stands in for QMessageBox so no dialog ever opens."""
    StandardButton = mw.QMessageBox.StandardButton
    answer = StandardButton.Yes
    infos = []
    warnings = []

    @staticmethod
    def question(*a, **k):
        return FakeBox.answer

    @staticmethod
    def information(parent, title, text, *a, **k):
        FakeBox.infos.append(text)

    @staticmethod
    def warning(parent, title, text, *a, **k):
        FakeBox.warnings.append(text)

    critical = warning


class FakeProc:
    def __init__(self, data=b""):
        self._out = data
        self.written = []

    def readAllStandardOutput(self):
        return types.SimpleNamespace(data=lambda: self._out) if not REAL_QT else _qba(self._out)

    def readAllStandardError(self):
        return types.SimpleNamespace(data=lambda: b"") if not REAL_QT else _qba(b"")

    def state(self):
        return rc.QProcess.ProcessState.Running

    def write(self, data):
        self.written.append(bytes(data))

    def deleteLater(self):
        pass

    def kill(self):
        pass

    def waitForFinished(self, ms):
        return True


def _qba(data):
    from PySide6.QtCore import QByteArray
    return QByteArray(data)


def real_runner_output(template="starter", frames=5):
    proj = templates.new_project(template)
    with tempfile.TemporaryDirectory() as tmp:
        proj.extract_to(tmp)
        done = subprocess.run([sys.executable, "-m", "cpg_studio.runtime.runner", tmp, "--frames", str(frames)],
                              capture_output=True, input=b"", cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT), timeout=30)
    assert done.returncode == 0, done.stderr
    return done.stdout


class WindowTests(unittest.TestCase):
    def setUp(self):
        FakeBox.answer = FakeBox.StandardButton.Yes
        FakeBox.infos, FakeBox.warnings = [], []
        patcher = mock.patch.object(mw, "QMessageBox", FakeBox)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.win = mw.MainWindow()
        self.addCleanup(self.win.deleteLater)

    def test_autocomplete_and_hover_are_wired_to_the_project(self):
        w = self.win
        text = w.project.read_text("main.py")
        replace_len, items = w._complete_at("main.py", text + "\ncle", len(text) + 4)
        self.assertEqual(replace_len, 3)
        self.assertIn("clear", [c.name for c in items])
        self.assertIn("clear", w._hover_at("main.py", "clear(BLACK)\n", 0, 2))

    def test_symbol_index_follows_edits(self):
        w = self.win
        w.on_text_edited("main.py", "def brand_new_fn():\n    pass\n")
        self.assertIn(("main.py", "brand_new_fn"), w._symbol_index().symbols)

    @unittest.skipUnless(REAL_QT, "needs real Qt line edits")
    def test_find_bar_finds_and_replaces_in_the_current_file(self):
        w = self.win
        ed = w.tabs.current_editor()
        ed.setPlainText("aa bb aa\n")
        w.findbar.set_editor(ed)
        w.findbar.find_field.setText("aa")
        w.findbar.refresh()
        self.assertEqual(len(w.findbar._matches), 2)

    def test_asset_files_open_in_their_own_editors_and_save_into_the_project(self):
        from cpg_studio.core.pixelimage import PixelImage
        from cpg_studio.core.sounddoc import SoundDoc
        from cpg_studio.core.tilemap_doc import TilemapDoc
        from cpg_studio.ui.asset_editors import SoundEditor, SpriteEditor, TilemapEditor, WavViewer
        w = self.win
        w.project.write_bytes("assets/hero.png", PixelImage(16, 16).to_png())
        w.project.write_text("assets/level.map.json", TilemapDoc.new("assets/hero.png", 8, 8, 4, 4).to_json())
        w.project.write_text("assets/jump.sfx.json", SoundDoc(notes=[["C4", 100]]).to_json())
        for path, cls in (("assets/hero.png", SpriteEditor), ("assets/level.map.json", TilemapEditor),
                          ("assets/jump.sfx.json", SoundEditor)):
            w.open_file(path)
            self.assertIsInstance(w.tabs.editor_for(path), cls, path)
            self.assertEqual(w.tabs.editor_for(path).path, path)
        self.assertEqual(w.asset_kind("x/boom.wav"), "wav")
        self.assertIsNone(w.asset_kind("main.py"))
        self.assertTrue(callable(WavViewer))
        # an edit made in an asset editor lands in the project file
        w._asset_text_changed("assets/jump.sfx.json", SoundDoc(notes=[["G4", 5]]).to_json())
        self.assertIn("G4", w.project.read_text("assets/jump.sfx.json"))
        w._asset_bytes_changed("assets/hero.png", PixelImage(2, 2).to_png())
        self.assertEqual(PixelImage.from_png(w.project.read_bytes("assets/hero.png")).w, 2)
        w.tabs.close_under("assets")
        self.assertEqual(w.tabs.paths().count("assets/hero.png"), 0)

    def test_starts_with_starter_project_open(self):
        w = self.win
        self.assertEqual((w.project.entry, w.tabs.current_path()), ("main.py", "main.py"))
        self.assertEqual(w.workspace.topLevelItemCount(), 1)
        root = w.workspace.topLevelItem(0)
        self.assertEqual(root.childCount(), 2)                       # assets/ and main.py
        self.assertFalse(w.project.dirty)

    def test_editing_updates_project_and_problems(self):
        w = self.win
        ed = w.tabs.editor_for("main.py")
        ed.setPlainText("x = (\n")
        self.assertEqual(w.project.read_text("main.py"), "x = (\n")
        self.assertTrue(w.project.dirty)
        w._run_diagnostics()
        self.assertEqual(w.problems.count(), 1)
        ed.setPlainText("x = 1\n")
        w._run_diagnostics()
        self.assertEqual(w.problems.count(), 0)

    def test_new_file_rename_delete(self):
        w = self.win
        w._ask = lambda *a, **k: "foo.py"
        w.new_file("")
        self.assertTrue(w.project.is_file("foo.py"))
        self.assertEqual(w.tabs.current_path(), "foo.py")
        w.new_file("")                                               # same name again: refused, no crash
        self.assertTrue(FakeBox.warnings)
        w._ask = lambda *a, **k: "bar.py"
        w.rename_path("foo.py")
        self.assertTrue(w.project.is_file("bar.py") and not w.project.exists("foo.py"))
        self.assertEqual(w.tabs.editor_for("bar.py").path, "bar.py")
        self.assertIsNone(w.tabs.editor_for("foo.py"))
        w.delete_path("bar.py")
        self.assertFalse(w.project.exists("bar.py"))
        self.assertNotIn("bar.py", w.tabs.paths())

    def test_folder_and_entry(self):
        w = self.win
        w._ask = lambda *a, **k: "src"
        w.new_folder("")
        self.assertTrue(w.project.is_dir("src"))
        w._ask = lambda *a, **k: "game.py"
        w.new_file("src")
        self.assertTrue(w.project.is_file("src/game.py"))
        w.set_entry("src/game.py")
        self.assertEqual(w.project.entry, "src/game.py")
        w._ask = lambda *a, **k: "code"
        w.rename_path("src")
        self.assertEqual(w.project.entry, "code/game.py")
        self.assertEqual(w.tabs.editor_for("code/game.py").path, "code/game.py")

    def test_delete_entry_then_run_warns(self):
        w = self.win
        w.delete_path("main.py")
        warned = []
        w._warn = warned.append
        w.run_project()
        self.assertEqual(len(warned), 1)
        self.assertFalse(w.runner.running)

    def test_save_open_roundtrip_and_discard_prompt(self):
        w = self.win
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "my.cpg")

            class Dialogs:
                @staticmethod
                def getSaveFileName(*a, **k):
                    return target, ""

                @staticmethod
                def getOpenFileName(*a, **k):
                    return target, ""

            with mock.patch.object(mw, "QFileDialog", Dialogs):
                w.tabs.editor_for("main.py").setPlainText("# my game\n")
                self.assertTrue(w.save_project_as())
                self.assertTrue(os.path.isfile(target))
                self.assertEqual((w.project.name, w.project.dirty), ("my", False))
                w.new_project("snake")                               # clean project: no prompt
                self.assertEqual(w.project.name, "snake")
                self.assertIn("Snake", w.project.read_text("main.py"))
                w.tabs.editor_for("main.py").setPlainText("# edited\n")
                FakeBox.answer = FakeBox.StandardButton.Cancel
                w.open_project(None)                                 # dirty + Cancel: nothing happens
                self.assertEqual(w.project.name, "snake")
                FakeBox.answer = FakeBox.StandardButton.Discard
                w.open_project(None)
                self.assertEqual(w.project.name, "my")
                self.assertEqual(w.project.read_text("main.py"), "# my game\n")
                self.assertEqual(w.tabs.current_path(), "main.py")

    def test_firmware_menu_is_a_placeholder(self):
        self.win.export_firmware()
        self.assertEqual(FakeBox.infos, [firmware.PLACEHOLDER_MESSAGE])
        with self.assertRaises(firmware.FirmwareExportNotImplemented):
            firmware.export_firmware(self.win.project, "x.bin")

    def test_console_and_problem_jumps_open_files(self):
        w = self.win
        w.tabs.close_all()
        w._jump_from_console("main.py", 3)
        self.assertEqual(w.tabs.current_path(), "main.py")
        w._jump_from_console("not_there.py", 1)                      # unknown file: ignored
        w.tabs.close_all()
        w.open_file("assets/readme.txt", 1, 0)
        self.assertEqual(w.tabs.current_path(), "assets/readme.txt")

    def test_key_events_are_forwarded_to_the_runner(self):
        w = self.win
        proc = FakeProc()
        w.runner._proc = proc
        w.preview.display.key_event.emit(True, "left")
        w.preview.display.key_event.emit(False, "left")
        self.assertEqual(proc.written, [b"d left\n", b"u left\n"])
        w.runner._proc = None


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.ctl = RunnerController()
        self.frames, self.outs, self.stats, self.stopped = [], [], [], []
        self.ctl.frame.connect(self.frames.append)
        self.ctl.output.connect(lambda text, kind: self.outs.append((text, kind)))
        self.ctl.stats.connect(self.stats.append)
        self.ctl.stopped.connect(self.stopped.append)

    def feed(self, data):
        proc = FakeProc(data)
        self.ctl._proc = proc
        self.ctl._tmp = tempfile.mkdtemp()
        self.ctl._on_stdout(proc)
        return proc

    def test_real_runner_stream_becomes_signals(self):
        proc = self.feed(real_runner_output("starter", 5))
        self.assertEqual(len(self.frames), 5)
        self.assertTrue(all(len(f) == 240 * 135 * 2 for f in self.frames))
        self.assertEqual("".join(t for t, k in self.outs if k == "out"), "game started\n")   # print() sends text and "\n" separately
        self.ctl._on_finished(proc, self.ctl._tmp, 0)
        self.assertEqual(self.stopped, ["Finished"])
        self.assertFalse(self.ctl.running)

    def test_error_message_and_error_exit(self):
        data = protocol.pack(protocol.ERROR, b"Traceback...\nNameError: x\n") + protocol.pack(protocol.EXIT, b"error")
        proc = self.feed(data)
        self.assertEqual(self.outs, [("Traceback...\nNameError: x\n", "error")])
        self.ctl._on_finished(proc, self.ctl._tmp, 1)
        self.assertEqual(self.stopped, ["Stopped: error"])

    def test_chunked_stream_and_stats(self):
        info = b'{"fps": 29.9, "frame_ms": 1.5, "frames": 12, "target_fps": 30}'
        data = protocol.pack(protocol.INFO, info)
        proc = FakeProc()
        self.ctl._proc = proc
        for i in range(0, len(data), 5):
            proc._out = data[i:i + 5]
            self.ctl._on_stdout(proc)
        self.assertEqual(self.stats, [{"fps": 29.9, "frame_ms": 1.5, "frames": 12, "target_fps": 30}])

    def test_garbage_stream_stops_runner(self):
        self.feed(b"F\xff\xff\xff\xff")
        self.assertTrue(any(kind == "error" for _, kind in self.outs))
        self.assertFalse(self.ctl.running)

    def test_stale_process_output_is_ignored(self):
        old, new = FakeProc(protocol.pack(protocol.STDOUT, b"old")), FakeProc()
        self.ctl._proc = new
        self.ctl._on_stdout(old)
        self.assertEqual(self.outs, [])


class ProblemsPanelTests(unittest.TestCase):
    def test_rename_and_counts(self):
        panel = ProblemsPanel()
        counts = []
        panel.counts_changed.connect(lambda e, w: counts.append((e, w)))
        panel.set_diagnostics("a.py", [Diagnostic("a.py", 2, 4, 0, "error", "bad", "python"),
                                       Diagnostic("a.py", 5, 0, 0, "warning", "meh", "pyflakes")])
        self.assertEqual((panel.count(), counts[-1]), (2, (1, 1)))
        panel.rename_path("a.py", "lib/b.py")
        self.assertIn("lib/b.py:2:5", panel.item(0).text())
        panel.forget_path("lib")
        self.assertEqual((panel.count(), counts[-1]), (0, (0, 0)))


if __name__ == "__main__":
    unittest.main()
