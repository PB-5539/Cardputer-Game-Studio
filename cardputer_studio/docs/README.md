# Cardputer Studio: how it works

These notes explain how the program is built and why, written so you can read them before (or while) writing
your own version. Read in this order:

| # | File | What it covers |
|---|------|----------------|
| 1 | [architecture.md](architecture.md) | The big picture: layers, what talks to what, a map of every file |
| 2 | [project-format.md](project-format.md) | The `.cpg` file and the in-memory `Project` |
| 3 | [runtime.md](runtime.md) | How a game runs: the runner process, the engine API, the framebuffer, the message protocol |
| 4 | [editor.md](editor.md) | The code editor: highlighting, diagnostics, autocomplete, hover, find/replace, multi-cursor |
| 5 | [assets.md](assets.md) | Sprites, tilemaps and sound: file formats, runtime classes, the three editors, the mixer |
| 6 | [ui-and-tests.md](ui-and-tests.md) | The main window, how the UI is tested without Qt, and how to run the tests |
| 7 | [gotchas.md](gotchas.md) | Things that were non-obvious or went wrong. Worth reading before you rebuild anything |
| 8 | [rebuild-notes.md](rebuild-notes.md) | What is Cardputer-specific, what is generic, and a suggested order if you rebuild it as a general engine |

A rule that runs through the whole code base: **logic that doesn't need a window lives in `core/` and `runtime/`
and has no Qt import.** The Qt code in `ui/` is thin glue on top. That is why most of the program can be unit
tested, and it is also the part that is easiest to lift into another project.
