"""Runs a project in its own process and streams frames, output and stats back to the IDE.

    python -m cpg_studio.runtime.runner <project_dir> [entry.py] [--frames N]

A separate process means a game stuck in `while True:` can never freeze the IDE; the IDE simply
kills it. Game code defines any of setup(), update(dt), draw() in the entry file (see api_docs).
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import sys
import threading
import time
import traceback

from . import api, protocol

MAX_DT = 0.1


def format_error(exc: BaseException, project_dir: str) -> str:
    """Traceback limited to the user's own files, with paths relative to the project."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename.startswith(project_dir)]
    lines = []
    if frames:
        lines.append("Traceback (most recent call last):\n")
        lines += traceback.format_list(frames)
    lines += traceback.format_exception_only(type(exc), exc)
    text = "".join(lines)
    for sep in {os.sep, "/"}:
        text = text.replace(project_dir + sep, "")
    return text


class Session:
    """Loads a project's entry file and runs its game loop, reporting through `send`."""

    def __init__(self, project_dir: str, send, entry: str = "main.py"):
        self.project_dir = os.path.abspath(project_dir)
        self.send = send
        self.entry = entry
        self.module = None
        self._hooks: dict = {}
        self._sounds_sent: set = set()

    def _audio(self, op: str, snd, options: dict) -> None:
        """Turn an engine audio call into a protocol message for the IDE's mixer."""
        def emit(cmd: dict, blob: bytes = b"") -> None:
            self.send(protocol.AUDIO, json.dumps(cmd).encode() + (b"\n" + blob if blob else b""))

        if op == "tone":
            emit({"op": "tone", "freq": options["freq"], "ms": options["ms"]})
        elif op == "stop":
            emit({"op": "stop", "id": snd.uid if snd is not None else None})
        elif op == "play":
            if snd.uid not in self._sounds_sent:
                self._sounds_sent.add(snd.uid)
                if snd.kind == "pcm":
                    emit({"op": "load", "id": snd.uid, "kind": "pcm", "rate": snd.rate}, snd.data or b" ")
                else:
                    emit({"op": "load", "id": snd.uid, "kind": "tones", "notes": snd.notes,
                          "wave": snd.wave, "volume": snd.volume})
            emit({"op": "play", "id": snd.uid, "loop": options["loop"], "volume": options["volume"]})

    def _error(self, text: str) -> None:
        self.send(protocol.ERROR, text.encode("utf-8", "replace"))

    def _report_exception(self, exc: BaseException) -> None:
        self._error(format_error(exc, self.project_dir))

    def load(self) -> bool:
        pd = self.project_dir
        if pd not in sys.path:
            sys.path.insert(0, pd)
        os.chdir(pd)
        entry_path = os.path.join(pd, self.entry)
        if not os.path.isfile(entry_path):
            self._error('Entry file "%s" not found. Set one with "Set as Entry Point" in the Workspace.\n' % self.entry)
            return False
        api._s.on_beep = lambda f, ms: self.send(protocol.STDOUT, ("[beep %d Hz, %d ms]\n" % (f, ms)).encode())
        api._s.on_audio = self._audio
        api.inject_builtins()
        name = os.path.splitext(os.path.basename(self.entry))[0]
        try:
            spec = importlib.util.spec_from_file_location(name, entry_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        except BaseException as e:           # includes SyntaxError and SystemExit from top-level code
            if isinstance(e, SystemExit):
                return False
            self._report_exception(e)
            return False
        self.module = module
        self._hooks = {h: getattr(module, h, None) for h in ("setup", "update", "draw")}
        for h, fn in self._hooks.items():
            if fn is not None and not callable(fn):
                self._error("%s must be a function, not %s.\n" % (h, type(fn).__name__))
                return False
        if not any(self._hooks.values()):
            self.send(protocol.STDOUT, b"warning: %s defines no setup(), update(dt) or draw().\n" % self.entry.encode())
        return True

    def _call(self, name: str, *args) -> None:
        fn = self._hooks.get(name)
        if fn is None:
            return
        if name == "update" and not inspect.signature(fn).parameters:
            fn()
        else:
            fn(*args)

    def run(self, max_frames=None, on_frame=None) -> bool:
        """Run until quit(), an error, or max_frames. Returns False if the game raised."""
        s = api._s
        try:
            self._call("setup")
        except SystemExit:
            self.send(protocol.EXIT, b"quit")
            return True
        except BaseException as e:
            self._report_exception(e)
            return False
        frames = 0
        last = time.perf_counter()
        stat_t, stat_frames, stat_busy = last, 0, 0.0
        while s.running and (max_frames is None or frames < max_frames):
            t0 = time.perf_counter()
            dt = min(t0 - last, MAX_DT) if frames else 1.0 / s.fps
            last = t0
            api._poll_keys()
            try:
                self._call("update", dt)
                self._call("draw")
            except SystemExit:
                break
            except BaseException as e:
                self.send(protocol.FRAME, api._frame_bytes())     # show what was on screen when it died
                self._report_exception(e)
                return False
            self.send(protocol.FRAME, api._frame_bytes())
            frames += 1
            if on_frame:
                on_frame(frames)
            busy = time.perf_counter() - t0
            stat_frames += 1
            stat_busy += busy
            spare = 1.0 / s.fps - busy
            if spare > 0:
                time.sleep(spare)
            now = time.perf_counter()
            if now - stat_t >= 0.5:
                info = {"fps": round(stat_frames / (now - stat_t), 1),
                        "frame_ms": round(stat_busy / stat_frames * 1000, 2),
                        "frames": frames, "target_fps": s.fps}
                self.send(protocol.INFO, json.dumps(info).encode())
                stat_t, stat_frames, stat_busy = now, 0, 0.0
        self.send(protocol.EXIT, b"quit")
        return True


class _TextSink(io.TextIOBase):
    """Replaces sys.stdout/stderr so a game's print() reaches the IDE console as messages."""

    def __init__(self, send):
        self._send = send

    def writable(self):
        return True

    def write(self, s):
        if s:
            self._send(protocol.STDOUT, s.encode("utf-8", "replace"))
        return len(s)

    def flush(self):
        pass


def _read_keys(stream, stop_on_eof: bool = True) -> None:
    for raw in iter(stream.readline, b""):
        parts = raw.decode("utf-8", "replace").split()
        if len(parts) == 2 and parts[0] in ("d", "u"):
            api._key_event(parts[0] == "d", parts[1])
    if stop_on_eof:
        api._s.running = False   # the IDE closed our stdin: shut down


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    max_frames = None
    if "--frames" in args:
        i = args.index("--frames")
        max_frames = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        print("usage: python -m cpg_studio.runtime.runner <project_dir> [entry.py] [--frames N]", file=sys.stderr)
        return 2
    project_dir = os.path.abspath(args[0])
    entry = args[1] if len(args) > 1 else "main.py"

    out = sys.stdout.buffer
    lock = threading.Lock()

    def send(kind, payload):
        try:
            with lock:
                out.write(protocol.pack(kind, payload))
                out.flush()
        except (BrokenPipeError, OSError):
            os._exit(0)                  # the IDE is gone

    keys_in = sys.stdin.buffer
    sys.stdout = _TextSink(send)
    sys.stderr = _TextSink(send)
    sys.stdin = io.StringIO("")          # input() raises EOFError instead of eating key events
    # With --frames (headless/testing) an empty stdin is normal, so only the IDE case stops on EOF.
    threading.Thread(target=_read_keys, args=(keys_in, max_frames is None), daemon=True).start()

    session = Session(project_dir, send, entry)
    ok = session.load() and session.run(max_frames)
    if not ok:
        send(protocol.EXIT, b"error")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
