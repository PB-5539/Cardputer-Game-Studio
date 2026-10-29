"""Starts the runner process for a project and turns its output into Qt signals."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..core.project import Project
from ..runtime import protocol

APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RunnerController(QObject):
    frame = Signal(bytes)
    output = Signal(str, str)          # text, kind ("out" | "error" | "info")
    stats = Signal(dict)
    audio = Signal(bytes)              # an audio command for the mixer (see core/mixer.py)
    started = Signal()
    stopped = Signal(str)              # reason shown in the status bar

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._tmp: str | None = None
        self._parser = protocol.MessageParser()
        self._exit_reason: str | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self, project: Project) -> None:
        self.stop(quiet=True)
        tmp = tempfile.mkdtemp(prefix="cpg_run_")
        try:
            project.extract_to(tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        existing = env.value("PYTHONPATH", "")
        env.insert("PYTHONPATH", APP_ROOT + (os.pathsep + existing if existing else ""))
        env.insert("PYTHONDONTWRITEBYTECODE", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(tmp)
        proc.readyReadStandardOutput.connect(lambda p=proc: self._on_stdout(p))
        proc.readyReadStandardError.connect(lambda p=proc: self._on_stderr(p))
        proc.errorOccurred.connect(lambda err, p=proc: self._on_error(p, err))
        proc.finished.connect(lambda code, status, p=proc, t=tmp: self._on_finished(p, t, code))
        self._proc, self._tmp = proc, tmp
        self._parser = protocol.MessageParser()
        self._exit_reason = None
        proc.start(sys.executable, ["-u", "-m", "cpg_studio.runtime.runner", tmp, project.entry])
        self.started.emit()

    def stop(self, quiet: bool = False) -> None:
        proc, tmp = self._proc, self._tmp
        if proc is None:
            return
        self._proc = None                  # from here on, signals from this process are ignored
        self._tmp = None
        proc.kill()                        # a game stuck in a loop can't be asked nicely
        proc.waitForFinished(2000)
        proc.deleteLater()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if not quiet:
            self.stopped.emit("Stopped")

    def send_key(self, down: bool, name: str) -> None:
        if self._proc is not None and self._proc.state() == QProcess.ProcessState.Running:
            self._proc.write(("%s %s\n" % ("d" if down else "u", name)).encode("utf-8"))

    # ---- process callbacks -----------------------------------------------------------------
    def _on_stdout(self, proc: QProcess) -> None:
        if proc is not self._proc:
            return
        data = bytes(proc.readAllStandardOutput().data())
        try:
            messages = self._parser.feed(data)
        except ValueError as e:
            self.output.emit("Runner sent garbage: %s\n" % e, "error")
            self.stop()
            return
        for kind, payload in messages:
            if kind == protocol.FRAME:
                self.frame.emit(payload)
            elif kind == protocol.STDOUT:
                self.output.emit(payload.decode("utf-8", "replace"), "out")
            elif kind == protocol.ERROR:
                self.output.emit(payload.decode("utf-8", "replace"), "error")
            elif kind == protocol.AUDIO:
                self.audio.emit(payload)
            elif kind == protocol.INFO:
                try:
                    self.stats.emit(json.loads(payload))
                except ValueError:
                    pass
            elif kind == protocol.EXIT:
                self._exit_reason = payload.decode("utf-8", "replace")

    def _on_stderr(self, proc: QProcess) -> None:
        if proc is self._proc:
            text = bytes(proc.readAllStandardError().data()).decode("utf-8", "replace")
            if text:
                self.output.emit(text, "error")

    def _on_error(self, proc: QProcess, error) -> None:
        if proc is self._proc and error == QProcess.ProcessError.FailedToStart:
            self.output.emit("Could not start Python (%s).\n" % sys.executable, "error")

    def _on_finished(self, proc: QProcess, tmp: str, exit_code: int) -> None:
        if proc is not self._proc:
            return                         # stale process we already stopped; stop() cleaned up
        self._on_stdout(proc)              # drain anything still buffered
        self._on_stderr(proc)
        self._proc, self._tmp = None, None
        proc.deleteLater()
        shutil.rmtree(tmp, ignore_errors=True)
        if self._exit_reason == "error" or (exit_code != 0 and self._exit_reason is None):
            self.stopped.emit("Stopped: error")
        else:
            self.stopped.emit("Finished")
