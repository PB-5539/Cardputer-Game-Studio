# Architecture

## The big picture

```
 ┌───────────────────────────── IDE process (PySide6 / Qt) ─────────────────────────────┐
 │  ui/main_window.py  ── owns ──►  Project (core/project.py, all files in memory)       │
 │        │                                                                              │
 │        ├─ EditorTabs ► CodeEditor        text files (.py ...)                         │
 │        │               SpriteEditor      .png                                          │
 │        │               TilemapEditor     .map.json                                     │
 │        │               SoundEditor       .sfx.json  (WavViewer for .wav)               │
 │        ├─ FindBar, Workspace tree, Docs / Problems / Runtime panels, Console           │
 │        ├─ PreviewPanel (ScreenWidget draws frames, sends key events)                   │
 │        ├─ RunnerController ── starts and talks to ─────────────┐                       │
 │        └─ AudioPlayer (Mixer ► speakers)  ◄── AUDIO messages ──┤                       │
 └─────────────────────────────────────────────────────────────────┼──────────────────────┘
                                                                   │ stdin: key events (text)
                                                                   │ stdout: binary messages
 ┌────────────────────── runner process (plain Python, no Qt) ─────┴──────────────────────┐
 │  runtime/runner.py  loads the game's main.py, calls setup / update(dt) / draw           │
 │  runtime/api.py     the engine functions games call (clear, rect, draw_sprite, play...) │
 │  runtime/framebuf_sim.py  software RGB565 screen                                        │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

Two processes, on purpose. A game that gets stuck in `while True:` can never freeze the IDE; the IDE just kills
the runner. It also means a crashing game can't take your unsaved work with it.

## Layers

| Layer | Folder | Rules |
|-------|--------|-------|
| Core logic | `cpg_studio/core/` | Pure Python. No Qt, no files on disk except `project.py` saving. Fully unit tested. |
| Runtime | `cpg_studio/runtime/` | Runs inside the game process. Pure Python, standard library only. Also imported by the IDE for shared formats (PNG reader, asset classes, protocol). |
| UI | `cpg_studio/ui/` | The only place that imports PySide6. Calls into core/runtime and owns no important logic. |
| Tests | `tests/` | Unit tests for core/runtime, smoke tests for the window (using a fake Qt when PySide6 isn't installed). |

## Map of the files

### core/
| File | Purpose |
|------|---------|
| `project.py` | The `.cpg` format and the in-memory `Project` (virtual folder of files). |
| `templates.py` | The starter project and the examples under File > New From Example. |
| `syntax.py` | Tokenises one line of Python for highlighting. Pure function, no Qt. |
| `diagnostics.py` | Errors and warnings from `ast` (and pyflakes if installed). |
| `search.py` | Find and replace logic (regex, whole word, case, replacement expansion). |
| `symbols.py` | Index of functions/classes/calls in the project; call trees for hover. |
| `completion.py` | Autocomplete suggestions for a position in a file. |
| `hover.py` | Builds the hover tooltip HTML (signature, docs, call tree). |
| `pyinfo.py` | Introspects Python builtins and a few safe stdlib modules for docs. |
| `multicursor.py` | Column maths and cursor merging for multi-cursor editing. |
| `textpos.py` | Converts Python string indexes to Qt text positions (they differ for emoji). |
| `pixelimage.py` | Editable RGBA image plus drawing ops and undo history (sprite editor model). |
| `tilemap_doc.py` | Tilemap editor model and its JSON. |
| `sounddoc.py` | Sound editor model and its JSON. |
| `mixer.py` | Software audio mixer used by the preview. |
| `audio_note_names.py` | The note list (C1 to B7) for the sound editor drop-down. |

### runtime/
| File | Purpose |
|------|---------|
| `api.py` | The engine functions and constants. Names in `__all__` are injected into `builtins` so games need no imports. |
| `api_docs.py` | The documentation for every API name (single source for the Docs panel and the API reference export). |
| `runner.py` | Loads a project, runs the game loop, sends frames/output/audio back. |
| `protocol.py` | Message framing between the IDE and the runner. |
| `framebuf_sim.py` | Software screen (RGB565): pixels, lines, rectangles, circles, text, sprite blits. |
| `font8x8.py` | The bitmap font. |
| `keys.py` | Key names and the PC-key to Cardputer-key mapping. |
| `assets.py` | Sprite, Tilemap and Sound classes and loaders. |
| `png.py` | Minimal PNG reader/writer so no image library is needed. |
| `audio_msgs.py` | Builds the audio protocol messages. |

### ui/
| File | Purpose |
|------|---------|
| `main_window.py` | Builds the window, owns the project, connects everything. |
| `editor.py` | `CodeEditor` and `EditorTabs`. |
| `findbar.py` | The find/replace bar. |
| `asset_editors.py` | Sprite, tilemap and sound editors, plus the WAV player. |
| `preview.py` | The preview screen and its toolbar. |
| `runner_controller.py` | Starts the runner process (`QProcess`) and turns its output into Qt signals. |
| `audio_player.py` | Plays the mixer's output through Qt Multimedia. |
| `panels.py` | Docs, Problems, Runtime and Console panels. |
| `workspace.py` | The project file tree. |
| `highlighter.py` | Connects `core/syntax.py` to Qt's `QSyntaxHighlighter`. |
| `theme.py` | Colours, stylesheet and the monospace font. |

## Data flow for the three things you do most

**Typing code.** `CodeEditor` text changes → `EditorTabs.text_edited(path, text)` → `MainWindow.on_text_edited` writes it
into the `Project` and starts a 400 ms timer → the timer runs `check_source` and sends errors to the editor
(wavy underlines) and the Problems panel. The symbol index for hover/autocomplete is marked stale and rebuilt the
next time it is needed.

**Pressing Run.** The project is extracted to a temp folder → `RunnerController` starts `python -m
cpg_studio.runtime.runner <folder>` → the runner imports `main.py`, runs the loop and streams messages → the
IDE draws frames, prints output, shows errors, plays audio. Key presses in the preview go the other way as text lines.

**Editing a sprite/tilemap/sound.** The editor widget changes its in-memory model → emits `changed(path, data)` →
`MainWindow` writes the bytes into the `Project`. Nothing touches the disk until you Save.
