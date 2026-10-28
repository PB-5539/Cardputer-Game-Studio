# Cardputer engine

Write Cardputer games in plain Python; `build.py` freezes the engine and your game into
MicroPython and outputs an app-only `.bin` for M5 Launcher.

    python build.py games/demo        # -> dist/demo.bin  (needs Docker running)
    python build.py games/keytest     # shows raw key names (fill in KEYMAP in engine/hal_cardputer.py)
    python build.py games/demo --stage-only   # just prepare build/stage, no Docker
    python -m unittest discover -s tests

First build creates a Docker image (clones MicroPython, downloads ESP-IDF, warm build): slow once,
quick afterwards. Versions are pinned at the top of `build.py`.

## Layout
- `engine/` device-side engine (game loop, drawing, input) + `hal_cardputer.py` (display/keyboard)
- `games/<name>/__init__.py` a game: subclass `engine.Game` as `Game` (`setup`, `update(e, dt)`, `draw(e)`)
- `docker/` build image + in-container build script
- `build.py` the one command you run

## Not verified yet
- The Docker build has not been run end to end (no Docker daemon/network where this was written).
- `hal_cardputer.py` pins, panel offsets and keyboard wiring are from memory: untested on hardware.
- Unconfirmed whether M5 Launcher runs a MicroPython app bin with no filesystem partition.
