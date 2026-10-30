# How a game runs

## The game contract

A game is a folder with an entry file (default `main.py`). It may define any of:

```python
def setup():        # once, before the first frame
def update(dt):     # every frame, dt = seconds since last frame (capped at 0.1)
def draw():         # every frame, after update
```

Engine functions (`clear`, `rect`, `key_down`, `draw_sprite`, ...) need **no import**.

## How "no import" works

`runtime/api.py` lists every public name in `__all__`. While a game runs, `inject_builtins()` copies those names
into Python's `builtins` module, so they are visible from every file in the project. `remove_builtins()` puts
things back (the old value is saved first). Names starting with `_` are private plumbing for the runner.

Because the names live in `__all__`, adding an engine function is three steps: write it in `api.py`, add it to
`__all__`, add a `Doc` for it in `api_docs.py` (a test fails if a name has no docs).

## The runner process (`runtime/runner.py`)

`python -m cpg_studio.runtime.runner <project_dir> [entry.py] [--frames N]`

1. `Session.load()` puts the project on `sys.path`, injects the API, and imports the entry file with `importlib`.
   Errors become an ERROR message (traceback filtered to the user's own files, paths made relative).
2. `Session.run()` calls `setup()`, then loops: latch keys, `update(dt)`, `draw()`, send the frame, sleep to hit the
   target FPS (`set_fps`, 1-60), and every half second send a stats message.
3. If the game raises, the last frame is still sent (you see what was on screen when it died) and the loop stops.
4. `stdout`/`stderr` are replaced with a sink that turns `print()` into messages. `stdin` is replaced with an
   empty stream so `input()` fails fast instead of eating key events.

`--frames N` runs N frames and exits. It is how the tests run games headless.

## Input

The IDE sends one text line per key event on the runner's stdin: `d <key>` (down) and `u <key>` (up). A reader
thread feeds them to `api._key_event`. Once per frame `_poll_keys()` latches the state so inside a frame
`key_down`, `key_pressed` and `key_released` are stable. A key tapped and released between two frames still
counts as pressed (it is remembered in `taps`).

Key names are in `runtime/keys.py`. Qt key codes are mapped with plain integers there so the file has no Qt import.

## The screen (`framebuf_sim.py`)

240 x 135 pixels, RGB565, stored little-endian, 2 bytes per pixel, row after row. That is exactly the byte
layout of `QImage.Format_RGB16`, so the IDE can display a frame with no conversion.

All drawing is clipped, so games can draw partly off-screen safely. Text uses an 8x8 bitmap font. Sprites are
drawn with `blit_runs`, which copies whole stretches of visible pixels at once (see assets.md).

## The message protocol (`protocol.py`)

Runner → IDE, on stdout, binary: **1 type byte + 4-byte big-endian length + payload**.

| Type | Meaning | Payload |
|------|---------|---------|
| `F` | frame | 240*135*2 bytes of RGB565 |
| `O` | printed text | utf-8 |
| `E` | error | utf-8 traceback |
| `I` | stats | JSON `{fps, frame_ms, frames, target_fps}` |
| `X` | exit | `"quit"` / `"error"` |
| `A` | audio command | one JSON line, optionally `\n` + raw bytes |

`MessageParser.feed(bytes)` takes whatever chunk the pipe delivered and returns the complete messages, keeping
the leftover for next time (pipes split data at arbitrary points). A length above 16 MB is treated as a corrupt stream.

IDE → runner: the key lines above.

## Audio on the runner side

`beep`, `play_sound`, `stop_sound` call `api._audio(...)`, which calls the callback the runner installed. The
runner turns that into AUDIO messages (`audio_msgs.py`). A sound's data (notes or PCM samples) is sent once, with a
`load` message, then `play` just refers to its id. The mixer and speakers live in the IDE (see assets.md).

## Timing and the preview

Frame time (`frame_ms` in the Runtime panel) only counts your `update`+`draw`. The Cardputer is far slower than a
PC, so treat it as a lower bound. Real device timing will matter once there is a firmware.
