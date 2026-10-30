# Gotchas and lessons

Things that were non-obvious, or that went wrong and were fixed. Most would cost you an afternoon to rediscover.

## Design decisions that paid off
- **Run games in a separate process.** An infinite loop in a game would freeze an in-process preview and take the IDE
  with it. A subprocess can just be killed.
- **Keep the logic out of the widgets.** Highlighting, completion, search, the three asset models and the mixer have no Qt
  import, so they are unit tested directly. The widgets became thin.
- **Pipes split data anywhere.** A frame (64 KB) arrives in pieces. Always buffer and parse by length prefix
  (`MessageParser`), never assume one read equals one message.
- **Atomic saves.** Write to a temp file in the same folder, then `os.replace`. A crash never leaves half a project.
- **Treat zips and image files as untrusted.** Validate every path in a zip; validate PNG headers and sizes; give errors
  that say what to fix.
- **Drawing sprites in pure Python is only fast if you copy slices.** Precompute visible runs per row and use slice
  assignment into the `bytearray`; a per-pixel loop would be far too slow.

## Qt gotchas
- **`triggered` passes `checked`.** `QAction.triggered` sends a bool, which lands in your first optional parameter.
  Use `lambda checked=False: slot()` (or a zero-argument lambda) when connecting.
- **Window shortcuts beat widget key handling.** Menu actions with shortcuts (Ctrl+C, Ctrl+Z, ...) are caught at window
  level. That's why Undo/Copy are menu actions that call a method on the focused widget, and why multi-cursor overrides
  `copy`, `cut` and `paste` as methods as well as in `keyPressEvent`.
- **Don't name an attribute `screen` on a widget.** `QWidget.screen()` exists; shadowing it breaks Qt internals.
  (The preview's was renamed to `display`.)
- **Middle-click pastes on Linux.** The base `mousePressEvent` pastes the X11 selection on a middle click. Handle that
  button yourself and don't call `super()`.
- **Overloaded signals.** `QCompleter.activated` has `str` and `QModelIndex` versions; write `activated[str]`.
- **Custom completion text.** With `UnfilteredPopupCompletion`, set `setCompletionRole(UserRole)` and put the text you want
  inserted in `UserRole`; the display text can then be anything.
- **A `QTextCursor` follows document edits.** Great for multi-cursor, but only if you edit the *last* position first
  (otherwise one edit moves the cursor you haven't processed yet).
- **Qt text positions are UTF-16.** Python indexes are code points. Convert (`textpos.py`) or highlights drift on emoji.
- **Text edit `contentOffset`.** To turn a mouse x into a text column, subtract `contentOffset().x()` and the document
  margin, then divide by the width of a space (monospace font).
- **Stylesheet `text-transform`** isn't supported by Qt; remove it.
- **Enum access.** PySide6 wants the full name: `QTextCursor.MoveOperation.End`, `QFrame.Shape.NoFrame`.

## Runner gotchas
- A runner started with `--frames` (tests) has an empty stdin; "stdin closed, so stop" must only apply when running under
  the IDE. Otherwise headless tests exit at once with zero frames.
- Don't reset engine state in `Session.load()`: key events can arrive before the game finishes loading.
- A game that raises should still send its last frame, so you can see where it died.
- Floats passed to drawing functions are rounded down (`math.floor`), like a device would, so negative coordinates don't
  jitter.

## Testing gotchas
- Don't test "file can't be written" with `chmod` as root; root ignores it. Monkeypatch `os.replace` to fail instead.
- `ResourceWarning`s in tests usually mean an unclosed zip or temp file; use `with`.
- Subprocess tests need `PYTHONPATH` set to the project root so `python -m cpg_studio.runtime.runner` can import.
- The fake Qt's single-word allowlist: add new Qt one-word method names there when a test says "not a Qt-looking name".

## Things deliberately left simple
- Hover doesn't infer variable types.
- Undo in the asset editors stores whole snapshots, not diffs.
- The sprite's frame size is not stored in the PNG (the game passes it).
- WAV files aren't edited, only played.
- Audio preview is mono, 22.05 kHz, 8 voices.
- The firmware/.bin export is a placeholder.
