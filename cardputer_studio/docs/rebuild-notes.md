# If you rebuild this as a general game engine

You said the Cardputer should become one target among several, and that you want to write it yourself so you know it
by heart. These notes separate what is generic from what is Cardputer-specific, and suggest an order.

## Cardputer-specific (becomes a "target" or "profile")
- The **screen**: 240 x 135, RGB565, one 8x8 font (`runtime/api.py` constants, `framebuf_sim.py`, `font8x8.py`).
- The **key names** and PC-key mapping (`runtime/keys.py`).
- The **engine API surface** being small and immediate-mode (`clear`, `rect`, `text`...). A general engine would want
  scenes/entities/cameras, resolution settings, more input devices.
- The **audio limits** (8-bit, 11 kHz, few voices).
- The **firmware placeholder** and the dev-firmware idea.
- API docs wording that mentions the device.

A good seam: make a `Target` description (screen size, pixel format, key list, audio limits, API subset) and have the
runner and editors read it, instead of reading module constants.

## Generic (reusable as is, or nearly)
- Project format and `Project` (just rename `.cpg`).
- Editor features: highlighting, diagnostics, autocomplete, hover call trees, find/replace, multi-cursor.
- Runner process + message protocol (add more message types: scene tree, profiler data, breakpoints).
- Asset formats and editors (PNG, tilemap JSON, tone JSON) and the models behind them.
- The UI shell: docks, workspace tree, console, problems, tabs.
- The test approach (core without Qt, fake Qt for the window).

## Suggested order for your own version
1. **Project + runner first**, with a trivial game: a `Project` that loads/saves, a runner that opens a window or sends a
   frame. This is the spine; everything else hangs off it.
2. **The protocol** between the two, with a parser you test (framing is where subtle bugs live).
3. **A plain code editor** with line numbers and highlighting. Add diagnostics next (cheap, very useful).
4. **Preview + input.** Frames in, key events out.
5. **Assets**: the PNG sprite path first (load, draw, edit), then tilemaps, then sound.
6. **Editor extras** (autocomplete, hover, find, multi-cursor) last. They are the biggest and the least essential.
7. **Targets**: only now introduce the Target abstraction, when you have two things to abstract over.

## Ideas for a general engine (not built here)
Scenes and entities, a camera, collision helpers, an animation system on top of sprite frames, particle effects,
a scripting hook per object, hot reload, a profiler panel, export to desktop/web, asset hot-reload, input remapping,
a debugger with frame stepping and variable watch.

## Learning from this code
Read the pure modules first: `core/search.py`, `core/multicursor.py`, `runtime/protocol.py`, `runtime/png.py`,
`core/mixer.py`. They are short, have no Qt, and each shows one idea cleanly. Then read the matching test file to
see how the idea is checked.
