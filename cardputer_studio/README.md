# Cardputer Studio

A VS Code-style desktop IDE for making M5Stack Cardputer games in Python, with a built-in preview of
the Cardputer screen, so you can write and test a game without touching the device.

> **How it works:** the `docs/` folder explains the architecture, file formats, runtime, editor and assets, plus
> gotchas and notes for rebuilding it. Start with [docs/README.md](docs/README.md).

## Run it

    python launch.py

First run creates a private `.venv` here and installs PySide6 (a minute or two); after that it just
starts. `python launch.py --check` shows what it would do, `--reset` rebuilds the environment.
Needs Python 3.9+ and an internet connection for the first run only.

## What you get

| Panel | What it does |
|---|---|
| **Workspace** (left) | Your project as a folder tree. Right-click for new file/folder, import, rename, delete, *Set as Entry Point*. |
| **Editor** (middle) | Python editing: dark high-contrast syntax colours, line numbers, red/yellow squiggles for syntax errors and (with pyflakes) undefined names. Engine functions are coloured differently from normal builtins. |
| **Preview** (right) | A 240x135 Cardputer screen. **F5** runs the project, **Shift+F5** stops it. Click the screen to type into the game. |
| **Docs and Tools** (far right) | Searchable engine docs, the Problems list, and Runtime stats (FPS, frame time). |
| **Console** (bottom) | Your `print()` output, errors and tracebacks. Double-click a traceback line to jump to it. |

Every panel can be resized, closed, or dragged elsewhere (View menu; `Ctrl+B` workspace, `Ctrl+J` console;
View > Reset Layout restores the default). Layout is remembered between runs.

## Editor shortcuts

| | |
|---|---|
| Autocomplete | pops up as you type; **Ctrl+Space** forces it. Knows engine functions (no import needed), your project's functions/classes/variables, `self.` members, built-ins, and a few stdlib modules (`math.`, `random.`...) |
| Hover | engine docs, or for your own functions the signature, docstring, where it's defined, and a **Calls / Called by** tree |
| Find / replace | **Ctrl+F**, **Ctrl+H**, F3 / Shift+F3. Toggles for match case, whole word, regex (`\1` works in the replacement). Enter = next, Ctrl+Alt+Enter = replace all |
| Multi-cursor | **middle-mouse drag** = column select, **Alt+click** = add cursor, **Ctrl+Alt+Up/Down** = cursor above/below, **Ctrl+D** = next occurrence, **Esc** = back to one cursor |

Hover only follows what it can see statically: `p.move()` on a variable isn't linked to `Player.move`,
but `self.move()`, `module.func()` and plain calls are.

## Sprites, tilemaps and sound

Everything lives in the project (usually under `assets/`) and opens in its own editor when you double-click it.
Create them from **File > New Sprite / Tilemap / Sound**, or import a PNG / WAV with **Import File**.

| File | Editor | In a game |
|---|---|---|
| `hero.png` | pixel editor (pencil, fill, shapes, palette, undo, frame grid) | `hero = load_sprite("assets/hero.png", 8, 8)` then `draw_sprite(hero, x, y, frame=0)` |
| `level.map.json` | tilemap editor (layers, solid tiles, tileset picker) | `level = load_tilemap(...)`, `draw_tilemap(level, cam_x, cam_y)`, `level.solid_at(x, y)` |
| `jump.sfx.json` | tone-sequence editor with a little keyboard | `play_sound(load_sound("assets/jump.sfx.json"))` |
| `boom.wav` | player only (converted to 8-bit, 11 kHz, 30 s max) | `play_sound(load_sound("assets/boom.wav"))` |

Sound also works from code: `play_sound(tones("C4:100 E4:100 G4:200"))`. `beep()` now plays through your speakers too
(View > Mute Preview Sound turns the preview audio off). Try **File > New From Example > sprites, tilemap and sound**.

Notes: magenta (255, 0, 255) and transparent pixels are see-through. A PNG does not remember its frame size, so pass it
to `load_sprite` (the sprite editor shows the exact call). Sprites are stored as full-colour RGBA PNGs and converted to the
display's RGB565 when loaded.

## Projects (.cpg)

A `.cpg` file is a zip archive (`project.json` + `files/...`) holding your scripts and assets. The Workspace
shows it as normal folders and you never manage the archive by hand: Ctrl+S saves everything back into the
one file. You can rename it to `.zip` and open it with any archive tool.

File > New creates a starter game; File > New From Example has a key tester and Snake.

## Writing a game

No imports needed. Define any of `setup()`, `update(dt)`, `draw()` in your entry file (`main.py` by default):

```python
x = 100.0

def update(dt):
    global x
    if key_down("right"):
        x += 80 * dt

def draw():
    clear(BLACK)
    rect(int(x), 60, 16, 16, ORANGE, fill=True)
    text("hello cardputer", 4, 4)
```

The full function list (display, colours, input, timing, sound) is in the Docs panel, and
File > Export API Reference writes it to a Markdown file. The preview runs your game in a separate
process, so a game stuck in an endless loop can't freeze the IDE: press Stop.

## Firmware export (placeholder)

Build > Export Firmware is a stub that says it isn't implemented. The compiler step will be designed
separately. An earlier, never-run attempt is kept in `firmware_parked/` for reference.

## Layout of the code

    cpg_studio/core/      .cpg format, templates, syntax scanner, diagnostics   (no Qt)
    cpg_studio/runtime/   engine API, software display + font, runner process   (no Qt)
    cpg_studio/ui/        PySide6 windows and panels
    cpg_studio/firmware/  export placeholder
    tests/                python -m unittest discover -s tests

## Tests, and what they don't cover

The tests cover the project format, syntax scanner, diagnostics, engine API, display drawing, key handling,
the runner process end to end (frames, errors, key events, shutdown) and the window logic (open, edit,
rename, save, reopen, run wiring).

When PySide6 is installed, the window tests run against real Qt (offscreen). When it isn't, they run against
a permissive stand-in (`tests/fake_qt.py`) that checks wiring and logic but not that Qt calls are valid.
**The first version was built without being able to launch the real window**, so expect to hit a few
Qt-specific rough edges on first run. Run the tests after installing (`.venv/bin/python -m unittest discover
-s tests`) and send any failure or traceback back.

## Known limits (v0.1)

- Preview text uses an 8x8 font that matches the Cardputer's character size but isn't guaranteed pixel-identical.
- `beep()` prints to the console; there's no audio yet. No sprite/image helpers yet.
- No find/replace, autocomplete or debugger in the editor yet.
- Key mapping: letters, digits, punctuation, Enter/Space/Backspace/Tab/Esc/Shift/Ctrl/Alt map directly; PC arrows
  give up/down/left/right; F1/F2 stand in for Fn/Opt. How the real keyboard produces arrows is settled with the firmware step.
