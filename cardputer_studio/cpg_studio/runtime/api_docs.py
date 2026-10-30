"""Reference documentation for the engine API: the single source for the Docs panel and API.md.

tests/test_docs.py checks that every name in api.__all__ is covered here, so the docs can't drift
from the code. To document a new function: add it to api.py's __all__ and add a Doc below.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from . import api
from .keys import KEY_NAMES

CATEGORIES = ("Game structure", "Display", "Sprites and tilemaps", "Colors and constants", "Input", "Timing and control", "Sound", "Project files")


@dataclass(frozen=True)
class Doc:
    title: str
    category: str
    signature: str
    summary: str
    covers: tuple = ()                 # api names this entry documents
    params: tuple = ()                 # ((name, description), ...)
    returns: str = ""
    example: str = ""
    notes: str = ""


DOCS = (
    # ---- game structure -------------------------------------------------------------------
    Doc("setup", "Game structure", "def setup():",
        "Optional. Called once before the first frame. Put one-time initialisation here.",
        example='def setup():\n    set_fps(30)\n    print("hello from the Cardputer")'),
    Doc("update", "Game structure", "def update(dt):",
        "Optional. Called once per frame, before draw(). Read input and move things here.",
        params=(("dt", "seconds since the previous frame (capped at 0.1), so movement stays the same at any frame rate"),),
        example='x = 0.0\n\ndef update(dt):\n    global x\n    x += 40 * dt        # 40 pixels per second'),
    Doc("draw", "Game structure", "def draw():",
        "Optional. Called once per frame after update(). Draw the frame here. The screen is not cleared "
        "for you, so start with clear().",
        example='def draw():\n    clear(BLACK)\n    text("hello", 10, 10)',
        notes="Define these in your entry file (main.py unless you chose another). Engine names such as "
              "clear() and key_down() need no import. Your own modules can use them too."),

    # ---- display --------------------------------------------------------------------------
    Doc("clear", "Display", "clear(color=BLACK)", "Fill the whole screen with one colour.", covers=("clear",),
        params=(("color", "an RGB565 colour from rgb() or a colour constant"),),
        example="clear(rgb(0, 0, 40))"),
    Doc("pixel", "Display", "pixel(x, y, color=WHITE)", "Set one pixel. Off-screen coordinates are ignored.",
        covers=("pixel",), params=(("x, y", "position; (0, 0) is the top-left corner"), ("color", "RGB565 colour")),
        example="pixel(120, 67, RED)"),
    Doc("line", "Display", "line(x0, y0, x1, y1, color=WHITE)", "Draw a 1-pixel line between two points.",
        covers=("line",), params=(("x0, y0", "start point"), ("x1, y1", "end point"), ("color", "RGB565 colour")),
        example="line(0, 0, WIDTH - 1, HEIGHT - 1, GREEN)"),
    Doc("rect", "Display", "rect(x, y, w, h, color=WHITE, fill=False)", "Draw a rectangle outline or a filled rectangle.",
        covers=("rect",),
        params=(("x, y", "top-left corner"), ("w, h", "width and height in pixels"), ("color", "RGB565 colour"),
                ("fill", "True for a solid rectangle")),
        example="rect(10, 10, 50, 30, YELLOW)\nrect(70, 10, 50, 30, ORANGE, fill=True)"),
    Doc("circle", "Display", "circle(cx, cy, r, color=WHITE, fill=False)", "Draw a circle outline or a filled circle.",
        covers=("circle",),
        params=(("cx, cy", "centre"), ("r", "radius in pixels"), ("color", "RGB565 colour"), ("fill", "True for a solid disc")),
        example="circle(120, 67, 20, CYAN)"),
    Doc("text", "Display", "text(s, x, y, color=WHITE)",
        "Draw text with the built-in 8x8 font. Each character is 8 pixels wide and 8 tall.", covers=("text",),
        params=(("s", "the text (anything else is converted with str())"), ("x, y", "top-left corner of the first character"),
                ("color", "RGB565 colour")),
        example='text("Score: " + str(score), 4, 4, WHITE)',
        notes="Only printable ASCII is drawn; other characters show as '?'. About 30 characters fit across the screen."),

    # ---- colours and constants ------------------------------------------------------------
    Doc("rgb", "Colors and constants", "rgb(r, g, b)", "Build a colour from red, green and blue.", covers=("rgb",),
        params=(("r, g, b", "0-255 each"),), returns="an RGB565 colour (an int) to pass to the drawing functions",
        example="sky = rgb(90, 160, 255)",
        notes="The display has 16-bit colour, so tiny differences between shades are lost."),
    Doc("Colour constants", "Colors and constants", "BLACK  WHITE  RED  GREEN  BLUE  YELLOW  CYAN  MAGENTA  ORANGE  GRAY",
        "Ready-made colours.", covers=("BLACK", "WHITE", "RED", "GREEN", "BLUE", "YELLOW", "CYAN", "MAGENTA", "ORANGE", "GRAY"),
        example="clear(BLACK)\ntext('hi', 0, 0, ORANGE)"),
    Doc("Screen constants", "Colors and constants", "WIDTH  HEIGHT  FONT_W  FONT_H",
        "Screen size (240 x 135 pixels) and the size of one text character (8 x 8).",
        covers=("WIDTH", "HEIGHT", "FONT_W", "FONT_H"),
        example="text('centre', WIDTH // 2 - 3 * FONT_W, HEIGHT // 2 - FONT_H // 2)"),

    # ---- input ----------------------------------------------------------------------------
    Doc("key_down", "Input", "key_down(name)", "True while the key is held.", covers=("key_down",),
        params=(("name", 'a key name such as "a", "space", "enter" or "left" (see Key names)'),),
        returns="True or False", example='if key_down("left"):\n    x -= 60 * dt'),
    Doc("key_pressed", "Input", "key_pressed(name)",
        "True only on the frame the key went down. Use it for one-shot actions like jumping or firing.",
        covers=("key_pressed",), params=(("name", "key name"),), returns="True or False",
        example='if key_pressed("space"):\n    fire()',
        notes="A very quick tap that starts and ends between two frames still counts as pressed for one frame."),
    Doc("key_released", "Input", "key_released(name)", "True only on the frame the key was let go.",
        covers=("key_released",), params=(("name", "key name"),), returns="True or False",
        example='if key_released("space"):\n    release_charge()'),
    Doc("keys_down", "Input", "keys_down()", "Names of all keys currently held, sorted.", covers=("keys_down",),
        returns="a list of key names", example='text(" ".join(keys_down()), 4, 4)'),
    Doc("keys_pressed", "Input", "keys_pressed()", "Names of keys that went down this frame, sorted.",
        covers=("keys_pressed",), returns="a list of key names", example="for k in keys_pressed():\n    print(k)"),
    Doc("Key names", "Input", "key names",
        "Names accepted by the key functions: " + ", ".join(KEY_NAMES) + ".",
        notes="Preview mapping: letters, digits and the punctuation keys map to themselves; the PC arrow keys give "
              "up/down/left/right; Enter, Space, Backspace, Tab, Esc, Shift, Ctrl and Alt give enter, space, backspace, "
              "tab, esc, shift, ctrl and alt; F1 stands in for fn and F2 for opt. Click the preview screen so it receives "
              "keystrokes. The Key Tester example shows what the engine sees. How the real keyboard produces the "
              "arrow names will be settled with the firmware build."),

    # ---- sprites and tilemaps -------------------------------------------------------------
    Doc("load_sprite", "Sprites and tilemaps", "load_sprite(path, frame_w=None, frame_h=None)",
        "Load a PNG from your project as a Sprite. Give frame_w and frame_h to treat the image as a sheet of frames.",
        covers=("load_sprite",),
        params=(("path", 'file in the project, e.g. "assets/hero.png"'),
                ("frame_w, frame_h", "size of one frame, if the image is a sprite sheet")),
        returns="a Sprite with .w and .h (one frame's size), .frame_count and .pixel(x, y, frame)",
        example='hero = load_sprite("assets/hero.png", 16, 16)   # a sheet of 16x16 frames\n\n'
                'def draw():\n    clear()\n    draw_sprite(hero, 100, 60, frame=int(time_ms() / 150) % 4)',
        notes="Magenta pixels (255, 0, 255) and transparent PNG pixels are see-through. Load sprites once (in setup or at "
              "the top of the file): loading the same file again returns the same Sprite. Draw them in the Sprite Editor "
              "(File > New Sprite) or import any PNG."),
    Doc("draw_sprite", "Sprites and tilemaps", "draw_sprite(spr, x, y, frame=0, flip_x=False, flip_y=False)",
        "Draw one frame of a Sprite with its top-left corner at (x, y). Parts off-screen are clipped.",
        covers=("draw_sprite",),
        params=(("spr", "a Sprite from load_sprite"), ("x, y", "top-left corner in pixels"),
                ("frame", "which frame of the sheet, counting left to right then top to bottom; wraps around"),
                ("flip_x, flip_y", "mirror the sprite horizontally / vertically")),
        example="draw_sprite(hero, x, y, frame=2, flip_x=facing_left)"),
    Doc("load_tilemap", "Sprites and tilemaps", "load_tilemap(path)",
        "Load a tilemap made in the Tilemap Editor (a .map.json file) together with its tileset image.",
        covers=("load_tilemap",), params=(("path", 'file in the project, e.g. "assets/level1.map.json"'),),
        returns="a Tilemap with .w and .h (in tiles), .px_w and .px_h (in pixels), .tile_w, .tile_h, .layer_names, "
                ".get(tx, ty, layer=0), .set(tx, ty, tile, layer=0), .is_solid(tx, ty) and .solid_at(x, y)",
        example='level = load_tilemap("assets/level1.map.json")\n\ndef update(dt):\n'
                '    if level.solid_at(px, py + 8):      # pixel position\n        on_ground = True',
        notes="Tile numbers count left to right, top to bottom in the tileset; -1 means empty. Positions outside the map "
              "count as solid, so characters cannot walk off it. Layers are drawn in order, first layer at the back."),
    Doc("draw_tilemap", "Sprites and tilemaps", "draw_tilemap(tm, cam_x=0, cam_y=0, layer=None)",
        "Draw the visible part of a Tilemap. Only the tiles on screen are drawn, so big maps stay fast.",
        covers=("draw_tilemap",),
        params=(("tm", "a Tilemap from load_tilemap"),
                ("cam_x, cam_y", "map pixel shown at the top-left of the screen (scrolls the map)"),
                ("layer", "draw only this layer (name or number); default draws all")),
        example="draw_tilemap(level, cam_x, cam_y)\ndraw_sprite(hero, px - cam_x, py - cam_y)"),

    # ---- timing and control ---------------------------------------------------------------
    Doc("set_fps", "Timing and control", "set_fps(fps)", "Set the target frame rate (1-60, default 30).",
        covers=("set_fps",), params=(("fps", "frames per second; values outside 1-60 are clamped"),),
        example="set_fps(60)"),
    Doc("time_ms", "Timing and control", "time_ms()", "Milliseconds since the game started.", covers=("time_ms",),
        returns="an int", example="if time_ms() - last_shot > 250:\n    shoot()"),
    Doc("quit", "Timing and control", "quit()", "Stop the game after the current frame.", covers=("quit",),
        example='if key_pressed("esc"):\n    quit()'),

    # ---- sound ----------------------------------------------------------------------------
    Doc("beep", "Sound", "beep(freq=880, ms=100)", "Play a tone on the speaker.", covers=("beep",),
        params=(("freq", "pitch in Hz"), ("ms", "length in milliseconds")), example="beep(440, 200)",
        notes="The preview plays the tone through your speakers and also prints '[beep 440 Hz, 200 ms]' in the console."),
    Doc("load_sound", "Sound", "load_sound(path)",
        "Load a sound from your project: a .wav file, or a tone sequence made in the Sound Editor (.sfx.json).",
        covers=("load_sound",), params=(("path", 'file in the project, e.g. "assets/jump.sfx.json"'),),
        returns="a Sound (pass it to play_sound)",
        example='jump = load_sound("assets/jump.sfx.json")\n\ndef update(dt):\n    if key_pressed("space"):\n'
                '        play_sound(jump)',
        notes="WAV files are converted to 8-bit mono at 11 kHz (max 30 seconds) to match what the Cardputer can play; "
              "short clips are best. Tone sequences are tiny and are the best fit for sound effects and chiptune."),
    Doc("tones", "Sound", "tones(song, wave='square', volume=0.5)",
        "Make a Sound from text: notes with a length in milliseconds, separated by spaces.",
        covers=("tones",),
        params=(("song", '"C4:200 E4:200 G4:400"; note names C4, F#3, Bb5 (A4 = 440 Hz) or a frequency like 440; '
                         '"rest:100" is silence; a note without :ms lasts 200 ms'),
                ("wave", '"square", "triangle", "saw" or "noise"'), ("volume", "0 to 1")),
        returns="a Sound", example='coin = tones("B5:60 E6:240", "square")\nplay_sound(coin)'),
    Doc("play_sound", "Sound", "play_sound(snd, loop=False, volume=1.0)",
        "Start playing a Sound. Several sounds can play at the same time.",
        covers=("play_sound",),
        params=(("snd", "a Sound from load_sound or tones"), ("loop", "repeat until stopped"),
                ("volume", "0 to 1")),
        example="play_sound(music, loop=True, volume=0.6)"),
    Doc("stop_sound", "Sound", "stop_sound(snd=None)",
        "Stop one Sound, or everything that is playing when called with no argument.",
        covers=("stop_sound",), params=(("snd", "the Sound to stop; leave out to stop all"),),
        example="stop_sound()"),

    # ---- project files --------------------------------------------------------------------
    Doc("Project files", "Project files", "open('assets/name.txt')",
        "Files in your project (for example in assets/) can be read with a normal relative path while previewing.",
        example='with open("assets/level1.txt") as f:\n    level = f.read().split("\\n")',
        notes="Your own .py files can be imported as usual (import utils). Reading project files on the device will "
              "be defined with the firmware build."),
)


def documented_names() -> set:
    names = set()
    for d in DOCS:
        names.update(d.covers)
    return names


def _matches(d: Doc, query: str) -> bool:
    q = query.lower().strip()
    if not q:
        return True
    hay = " ".join((d.title, d.signature, d.summary, d.notes, " ".join(d.covers))).lower()
    return all(word in hay for word in q.split())


def to_markdown() -> str:
    out = ["# Cardputer engine API", "",
           "Names below are available in every game with no import. "
           "Screen: %d x %d pixels, colours are 16-bit RGB565." % (api.WIDTH, api.HEIGHT), ""]
    for cat in CATEGORIES:
        entries = [d for d in DOCS if d.category == cat]
        if not entries:
            continue
        out += ["## " + cat, ""]
        for d in entries:
            out += ["### `%s`" % d.title if d.title.isidentifier() else "### " + d.title, "", "```python", d.signature, "```", "", d.summary, ""]
            if d.params:
                out += ["**Parameters**", ""] + ["- `%s`: %s" % p for p in d.params] + [""]
            if d.returns:
                out += ["**Returns:** " + d.returns, ""]
            if d.example:
                out += ["```python", d.example, "```", ""]
            if d.notes:
                out += ["_" + d.notes + "_", ""]
    return "\n".join(out)


def to_html(query: str = "") -> str:
    e = html.escape
    parts = []
    for cat in CATEGORIES:
        entries = [d for d in DOCS if d.category == cat and _matches(d, query)]
        if not entries:
            continue
        parts.append("<h2>%s</h2>" % e(cat))
        for d in entries:
            parts.append("<h3>%s</h3><pre>%s</pre><p>%s</p>" % (e(d.title), e(d.signature), e(d.summary)))
            if d.params:
                parts.append("<table cellspacing='4'>%s</table>" % "".join(
                    "<tr><td><code>%s</code></td><td>%s</td></tr>" % (e(n), e(t)) for n, t in d.params))
            if d.returns:
                parts.append("<p><b>Returns:</b> %s</p>" % e(d.returns))
            if d.example:
                parts.append("<p><b>Example</b></p><pre>%s</pre>" % e(d.example))
            if d.notes:
                parts.append("<p><i>%s</i></p>" % e(d.notes))
    return "".join(parts) or "<p>No matches.</p>"
