# The main window and the tests

## Running it

`python launch.py` creates a private `.venv` the first time, installs `requirements.txt` into it (PySide6 and
pyflakes), remembers a hash of the requirements so it only reinstalls when they change, then starts
`python -m cpg_studio`. It only uses the standard library itself. `--check` prints what it would do.

## MainWindow (`ui/main_window.py`)

A `QMainWindow` with dockable panels (each `QDockWidget`, so they can be dragged, resized, floated, hidden):
Workspace (left), Preview and Docs/Problems/Runtime tabs (right), Console (bottom). The centre is a stacked widget:
a welcome label, or the editor area (find bar + editor tabs). Layout is saved with `QSettings` and `Reset Layout`
restores the default.

It owns the `Project` and is the only place that connects things together:
- `_make_actions` creates every action once; menus reuse them.
- `_wire` connects signals (workspace clicks, editor edits, runner output, audio).
- Project operations (new/open/save/rename/delete/import) change the `Project`, then refresh the tree and tabs.
- `open_file` decides which editor a file gets (`asset_kind` looks at the extension).
- Run/stop go through `RunnerController`.

Edit-menu actions like Undo and Copy call `_edit(method)`: it tries the widget that has focus, then the current tab,
so they work for text editors and for the sprite/tilemap editors, which have their own `undo`/`redo`.

## RunnerController (`ui/runner_controller.py`)

Wraps `QProcess`. `start` extracts the project to a temp folder, launches the runner, and from then on parses stdout
with `MessageParser` and emits Qt signals (`frame`, `output`, `stats`, `audio`, `started`, `stopped`). `stop` kills the
process and deletes the temp folder. Signals from a process that was already stopped are ignored (a stale process can
still deliver its last output).

## PreviewPanel / ScreenWidget (`ui/preview.py`)

Turns a frame's bytes into a `QImage` (`Format_RGB16`, no conversion needed), scales it with nearest-neighbour so pixels
stay sharp, and handles keyboard focus: click the screen to give it keys. It maps Qt key codes to Cardputer names via
`runtime/keys.py`, ignores auto-repeat (the game gets one down and one up), and releases every held key when focus is
lost so nothing is stuck down.

## Testing without a GUI

`python -m unittest discover -s tests` from the `cardputer_studio` folder (about 200 tests, a few seconds).

| Tests | Cover |
|-------|-------|
| `test_project.py` | zip format, path safety, atomic save, templates |
| `test_syntax_diag.py` | highlighting and diagnostics |
| `test_runtime_units.py` | the engine API, framebuffer, keys, docs coverage |
| `test_runner.py` | the runner in-process and as a real subprocess (frames, errors, keys, protocol) |
| `test_assets.py` | PNG reader (vs Pillow), sprites, tilemaps, sounds, mixer, API, example project |
| `test_editor_core.py` | search, multi-cursor maths, symbols, completion, hover |
| `test_editor_models.py` | the three asset-editor models |
| `test_ui_smoke.py` | the whole window: open, edit, save, rename, run, asset editors |
| `test_launch.py` | the launcher's plan, with nothing really installed |

**The fake Qt.** If PySide6 is not installed, `tests/fake_qt.py` installs a stand-in so the window code still imports
and runs. It accepts any Qt-looking name and records signal connections, so it catches typos in *your* names, wrong
wiring, and logic errors, but it **cannot** tell whether a real Qt call is valid. If PySide6 is installed the same
tests run against real Qt (offscreen). Treat a green run on the fake as "the logic works", and still try the app by
hand after changing GUI code.

Two things in the fake are easy to forget: single-word Qt method names (`copy`, `stop`, `popup`...) have to be added to
the allowlist in `fake_qt.py`, and a signal can be indexed (`activated[str]`) because overloaded signals need it.
